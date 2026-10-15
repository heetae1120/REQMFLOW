import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from reqm_local.service import Operations
from reqm_local.incremental_sync import IncrementalSync,local_records,canonical,record_key
from reqm_local.sync_transport import SyncTransport,SyncHTTPError
from tests.test_tracking import REFERENCE

class Server:
    def __init__(self,records):
        self.version=1;self.rows={key:{'row_key':key,**value,'deleted':False,'revision':1} for key,value in records.items()}
        self.uploads=[]
    def push(self,changes):
        for c in changes:
            if self.rows.get(c['row_key'],{}).get('revision',0)!=c['expected_revision']:raise ValueError('FLOW_ROW_CONFLICT')
        self.version+=1;self.uploads.append(changes)
        for c in changes:self.rows[c['row_key']]={**c,'revision':self.version}
        return self.version
    def cycle(self,engine):
        snapshot=engine.prepare();target=self.version
        delta=[r for r in self.rows.values() if snapshot['cursor']<r['revision']<=target]
        plan=engine.plan(snapshot,delta);ack=[]
        if plan['uploads']:
            version=self.push(plan['uploads']);ack=[(c,version) for c in plan['uploads']]
        engine.apply(snapshot,plan,target,ack)
        return plan

class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.a=Operations(self.folder/'a',REFERENCE);self.b=Operations(self.folder/'b',REFERENCE)
        with self.a.db:self.a.db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?)',('ORDER','key',canonical({'order_no':'A'}),'[]','출고 준비',''))
        self.server=Server(local_records(self.a));self.sa=IncrementalSync(self.a,'test');self.sb=IncrementalSync(self.b,'test')
        self.server.cycle(self.sa);self.server.cycle(self.sb)
    def tearDown(self):
        self.a.close();self.b.close();self.temp.cleanup()
    def edit(self,service,value):
        with service.db:service.db.execute('UPDATE orders SET issue=? WHERE id=?',(value,'ORDER'))
    def test_a_edits_are_visible_to_b_and_only_one_row_is_uploaded(self):
        self.edit(self.a,'A 변경');plan=self.server.cycle(self.sa)
        self.assertEqual(len(plan['uploads']),1);self.assertEqual(plan['uploads'][0]['table_name'],'orders')
        self.server.cycle(self.sb)
        self.assertEqual(self.b.db.execute('SELECT issue FROM orders').fetchone()[0],'A 변경')
        self.assertEqual(self.server.cycle(self.sa)['uploads'],[])
    def test_same_row_conflict_preserves_local_and_requires_choice(self):
        self.edit(self.a,'A');self.edit(self.b,'B');self.server.cycle(self.sa);self.server.cycle(self.sb)
        self.assertEqual(len(self.sb.conflicts),1)
        self.assertEqual(self.b.db.execute('SELECT issue FROM orders').fetchone()[0],'B')
        cursor=self.sb.prepare()['cursor'];self.assertEqual(cursor,self.server.version)
        self.assertEqual(self.server.cycle(self.sb)['uploads'],[])
        key=next(iter(self.sb.conflicts));self.sb.choices[key]='remote';self.server.cycle(self.sb)
        self.assertEqual(self.b.db.execute('SELECT issue FROM orders').fetchone()[0],'A')
    def test_remote_delete_propagates_as_tombstone(self):
        with self.a.db:self.a.db.execute('DELETE FROM orders WHERE id=?',('ORDER',))
        self.server.cycle(self.sa);self.server.cycle(self.sb)
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
        self.assertTrue(any(r['deleted'] for r in self.server.rows.values()))
    def test_inflight_local_edit_is_never_overwritten(self):
        self.edit(self.a,'A');self.server.cycle(self.sa)
        snapshot=self.sb.prepare();delta=list(self.server.rows.values());plan=self.sb.plan(snapshot,delta)
        self.edit(self.b,'B')
        with self.assertRaises(ValueError):self.sb.apply(snapshot,plan,self.server.version,[])
        self.assertEqual(self.b.db.execute('SELECT issue FROM orders').fetchone()[0],'B')
    def test_initial_conflict_does_not_repeat_full_snapshot(self):
        c=Operations(self.folder/'c',REFERENCE)
        try:
            with c.db:c.db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?)',('ORDER','key',canonical({'order_no':'A'}),'[]','출고 준비','다른 자료'))
            sync=IncrementalSync(c,'test');self.server.cycle(sync)
            self.assertTrue(sync.conflicts);self.assertEqual(sync.prepare()['cursor'],self.server.version)
            sync=IncrementalSync(c,'test');self.assertTrue(sync.prepare()['conflicts'])
            self.assertEqual(self.server.cycle(sync)['uploads'],[])
        finally:c.close()
    def test_entered_order_collision_keeps_local_shipping_and_retires_remote_duplicate(self):
        with self.b.db:
            self.b.db.execute('INSERT INTO requests VALUES(?,?)',('LOCAL-REQUEST','2026-10-15'))
            self.b.db.execute('INSERT INTO request_lines VALUES(?,?,?,?,?)',('LOCAL-LINE','LOCAL-REQUEST','ORDER',0,1))
            self.b.db.execute('INSERT INTO shipments VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                ('LOCAL-SHIPMENT','LOCAL-LINE',1,'TRACK-1','2026-10-15','ERP-1','100','100','상품','100',0))
        order=next(row['payload'] for row in local_records(self.a).values() if row['table_name']=='orders')
        duplicate={**order,'id':'REMOTE-ORDER','data':canonical({'order_no':'A','recipient':'서버 자료'})}
        records=[
            ('orders',duplicate,['id']),
            ('requests',{'id':'REMOTE-REQUEST','day':'2026-10-15'},['id']),
            ('request_lines',{'id':'REMOTE-LINE','request_id':'REMOTE-REQUEST','order_id':'REMOTE-ORDER','component':0,'qty':1},['id']),
            ('shipments',{'id':'REMOTE-SHIPMENT','line_id':'REMOTE-LINE','qty':1,'tracking':'TRACK-1','day':'2026-10-14',
                'erp_id':'ERP-OLD','erp_amount':None,'erp_code':None,'erp_name':None,'erp_warehouse':None,'amount_split_confirmed':0},['id']),
            ('tracking_jobs',{'id':'REMOTE-JOB','identity':'remote-job','day':'2026-10-15','kind':'b2c','source_name':'',
                'source_content':{'__reqm_bytes__':'YQ=='},'created_by':'worker','created_at':'2026-10-15T00:00:00'},['id']),
            ('tracking_rows',{'id':'REMOTE-TRACKING-ROW','job_id':'REMOTE-JOB','order_id':'REMOTE-ORDER',
                'data':canonical({'order_no':'A'}),'state':'pending','tracking':'','reason':'','evidence':'[]',
                'queried_at':'','confirmed_at':'','confirmed_by':''},['id']),
        ]
        duplicate_keys=[]
        for table,payload,keys in records:
            key=record_key(table,payload,keys);duplicate_keys.append(key);self.server.version+=1
            self.server.rows[key]={'row_key':key,'table_name':table,'payload':payload,'deleted':False,'revision':self.server.version}

        plan=self.server.cycle(self.sb)

        self.assertEqual(plan['conflicts'],{})
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
        self.assertEqual(self.b.db.execute('SELECT id FROM orders').fetchone()[0],'ORDER')
        self.assertEqual(self.b.db.execute('SELECT id FROM shipments').fetchone()[0],'LOCAL-SHIPMENT')
        self.assertEqual(self.b.db.execute('SELECT order_id FROM tracking_rows').fetchone()[0],'ORDER')
        self.assertEqual(self.server.rows[duplicate_keys[-1]]['payload']['order_id'],'ORDER')
        self.assertFalse(self.server.rows[duplicate_keys[-1]]['deleted'])
        for key in duplicate_keys:
            if self.server.rows[key]['table_name'] in ('orders','requests','request_lines','shipments'):
                self.assertTrue(self.server.rows[key]['deleted'])
        self.server.cycle(self.sa)
        self.assertEqual(self.a.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
        self.assertEqual(self.a.db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0],1)
        self.assertEqual(self.a.db.execute('SELECT order_id FROM tracking_rows').fetchone()[0],'ORDER')
        self.server.cycle(self.sb)
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0],1)
    def test_no_change_does_not_rewrite_local_cache(self):
        self.server.cycle(self.sa);before=self.a.db.total_changes
        self.server.cycle(self.sa);self.assertEqual(self.a.db.total_changes,before)
    def test_login_refresh_is_single_and_reused(self):
        transport=SyncTransport(self.folder,{'supabase_url':'https://example.invalid','supabase_publishable_key':'public'})
        transport.session={'refresh_token':'old'}
        with patch.object(transport,'request',return_value={'access_token':'new','refresh_token':'rotated','expires_in':3600}) as request,patch('reqm_local.sync_transport._protect',side_effect=lambda value,*_:value):
            transport.ensure_session();transport.ensure_session()
        request.assert_called_once();self.assertIn('grant_type=refresh_token',request.call_args.args[0])
    def test_failed_refresh_does_not_fall_back_to_password_loop(self):
        transport=SyncTransport(self.folder,{'supabase_url':'https://example.invalid','supabase_publishable_key':'public'})
        transport.session={'refresh_token':'bad'}
        with patch.object(transport,'request',side_effect=SyncHTTPError(400,'invalid_refresh_token')) as request:
            with self.assertRaises(SyncHTTPError):transport.ensure_session()
        request.assert_called_once()
