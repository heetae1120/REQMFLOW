"""Row-level three-way sync. No network work or automatic overwrite of conflicts."""
from __future__ import annotations
import json,ast
from pathlib import Path
from .workspace_cloud import TABLE_ORDER,_encode_value,_decode_value

LOCAL_SETTINGS={'cloud_email','flow_sync_enabled','flow_sync_workspace'}

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True)

def primary_keys(db,table):
    if table=='events':return ['at','action','detail']
    return [r['name'] for r in sorted(db.execute(f'PRAGMA table_info("{table}")'),key=lambda r:r['pk']) if r['pk']]

def record_key(table,row,keys):
    return table+':'+json.dumps([row[k] for k in keys],ensure_ascii=False)

def local_records(service):
    result={}
    for table in TABLE_ORDER:
        keys=primary_keys(service.db,table)
        for source in service.db.execute(f'SELECT * FROM "{table}"'):
            row={k:_encode_value(source[k]) for k in source.keys() if not(table=='events' and k=='id')}
            result[record_key(table,row,keys)]={'table_name':table,'payload':row}
    result['settings:[]']={'table_name':'settings','payload':{k:v for k,v in service.settings.items() if k not in LOCAL_SETTINGS}}
    return result

class IncrementalSync:
    def __init__(self,service,context):
        self.service=service;self.context=context;self.conflicts={};self.choices={}
        service.db.executescript('''CREATE TABLE IF NOT EXISTS flow_local_baseline(
            context TEXT NOT NULL,row_key TEXT NOT NULL,table_name TEXT NOT NULL,payload TEXT,
            revision INTEGER NOT NULL,PRIMARY KEY(context,row_key));
            CREATE TABLE IF NOT EXISTS flow_local_cursor(context TEXT PRIMARY KEY,version INTEGER NOT NULL);''')
        service.db.execute('CREATE TABLE IF NOT EXISTS flow_local_conflicts(context TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        service.db.commit()

    def prepare(self):
        current=local_records(self.service)
        baseline={r['row_key']:{'table_name':r['table_name'],'payload':json.loads(r['payload']) if r['payload'] is not None else None,'revision':r['revision']}
            for r in self.service.db.execute('SELECT * FROM flow_local_baseline WHERE context=?',(self.context,))}
        row=self.service.db.execute('SELECT version FROM flow_local_cursor WHERE context=?',(self.context,)).fetchone()
        conflicts=self.service.db.execute('SELECT payload FROM flow_local_conflicts WHERE context=?',(self.context,)).fetchone()
        self.conflicts=json.loads(conflicts['payload']) if conflicts else {}
        defaults={}
        for table in TABLE_ORDER:
            defaults[table]={}
            for column in self.service.db.execute(f'PRAGMA table_info("{table}")'):
                if column['pk'] or (table=='events' and column['name']=='id'):continue
                value=column['dflt_value']
                try:defaults[table][column['name']]=ast.literal_eval(value) if value is not None else None
                except (ValueError,SyntaxError):defaults[table][column['name']]=None
        return {'current':current,'baseline':baseline,'cursor':row['version'] if row else 0,
            'has_business':any(r['table_name'] in ('orders','requests','shipments','mappings') for r in current.values()),'choices':dict(self.choices),'conflicts':dict(self.conflicts),'defaults':defaults}

    @staticmethod
    def plan(snapshot,remote):
        current=snapshot['current'];base=snapshot['baseline'];merged=dict(base)
        for r in remote:
            payload=None if r['deleted'] else {**snapshot.get('defaults',{}).get(r['table_name'],{}),**r['payload']}
            merged[r['row_key']]={'table_name':r['table_name'],'payload':payload,'revision':r['revision']}
        # An already-entered local order is authoritative when the same business
        # identity arrives under a different row ID. Retire the duplicate server
        # graph so the order and its existing shipping records remain intact on
        # every client, instead of failing on orders.identity's UNIQUE index.
        local_orders={}
        for row in current.values():
            payload=row.get('payload')
            if row['table_name']=='orders' and payload:
                local_orders[payload.get('identity')]=payload
        duplicate_order_ids={}
        duplicate_keys=set()
        for key,row in merged.items():
            payload=row.get('payload')
            if row['table_name']!='orders' or not payload:continue
            local=local_orders.get(payload.get('identity'))
            if local and local.get('id')!=payload.get('id'):
                duplicate_order_ids[payload['id']]=local['id'];duplicate_keys.add(key)
        duplicate_line_ids=set();duplicate_request_ids=set();suppressed=set(duplicate_keys)
        for key,row in merged.items():
            payload=row.get('payload')
            if row['table_name']=='request_lines' and payload and payload.get('order_id') in duplicate_order_ids:
                duplicate_line_ids.add(payload.get('id'));duplicate_request_ids.add(payload.get('request_id'));suppressed.add(key)
        for key,row in merged.items():
            payload=row.get('payload')
            if row['table_name']=='shipments' and payload and payload.get('line_id') in duplicate_line_ids:
                suppressed.add(key)
        local_request_ids={row['payload'].get('request_id') for row in current.values()
            if row['table_name']=='request_lines' and row.get('payload')}
        remaining_cloud_request_ids={row['payload'].get('request_id') for key,row in merged.items()
            if key not in suppressed and row['table_name']=='request_lines' and row.get('payload')}
        orphaned_requests=duplicate_request_ids-local_request_ids-remaining_cloud_request_ids
        for key,row in merged.items():
            payload=row.get('payload')
            if row['table_name']=='requests' and payload and payload.get('id') in orphaned_requests:
                suppressed.add(key)
        forced_changes=[]
        for key,row in list(merged.items()):
            payload=row.get('payload')
            if key in suppressed or not payload:continue
            duplicate_id=payload.get('order_id')
            canonical_id=duplicate_order_ids.get(duplicate_id)
            if canonical_id and duplicate_id!=canonical_id:
                updated={**payload,'order_id':canonical_id}
                forced_changes.append({'row_key':key,'table_name':row['table_name'],'payload':updated,
                    'deleted':False,'expected_revision':row['revision']})
                merged[key]={**row,'payload':updated}
        for key in suppressed:
            row=merged[key]
            if row.get('payload') is not None:
                forced_changes.append({'row_key':key,'table_name':row['table_name'],'payload':None,
                    'deleted':True,'expected_revision':row['revision']})
                merged[key]={**row,'payload':None}
        uploads=[];incoming=[];conflicts={}
        for key in set(current)|set(merged):
            local=current.get(key,{}).get('payload');old=base.get(key,{}).get('payload')
            cloud=merged.get(key,{}).get('payload');table=(current.get(key) or merged[key])['table_name']
            revision=merged.get(key,{}).get('revision',0)
            choice=snapshot['choices'].get(key)
            # The shipped Shipping catalog is authoritative; obsolete codes must not return.
            if table=='item_names':choice='local'
            if local==cloud:continue
            first=key not in base and snapshot['cursor']==0
            if key in snapshot.get('conflicts',{}) and choice is None:
                conflicts[key]={'local':local,'remote':cloud,'table_name':table,'revision':revision};continue
            if choice=='remote':incoming.append({'row_key':key,'table_name':table,'payload':cloud});continue
            if choice=='local':pass
            elif first:
                if not snapshot['has_business'] and cloud is not None:incoming.append({'row_key':key,'table_name':table,'payload':cloud});continue
                if cloud is not None and (local is not None or snapshot['has_business']):
                    conflicts[key]={'local':local,'remote':cloud,'table_name':table,'revision':revision};continue
            elif local==old:
                incoming.append({'row_key':key,'table_name':table,'payload':cloud});continue
            elif cloud!=old:
                conflicts[key]={'local':local,'remote':cloud,'table_name':table,'revision':revision};continue
            uploads.append({'row_key':key,'table_name':table,'payload':local,'deleted':local is None,'expected_revision':revision})
        # A stale PC can publish a tracking update after its linked order was
        # deleted in an earlier revision. Reproduce order_id's ON DELETE SET
        # NULL semantics even when the parent tombstone is outside this delta.
        # Keep all tracking evidence, and only detach a confirmed tombstone;
        # an unknown parent or a locally retained order is not a deletion.
        order_ids={row['payload']['id'] for row in current.values()
            if row['table_name']=='orders' and row.get('payload')}
        for item in incoming:
            if item['table_name']!='orders':continue
            if item['payload'] is not None:order_ids.add(item['payload']['id'])
            else:
                old=current.get(item['row_key'],{}).get('payload')
                if old:order_ids.discard(old['id'])
        for item in incoming:
            payload=item['payload']
            if item['table_name']!='tracking_rows' or not payload:continue
            order_id=payload.get('order_id')
            if order_id is None or order_id in order_ids:continue
            parent=merged.get(record_key('orders',{'id':order_id},['id']))
            if parent is None or parent['payload'] is not None:continue
            row=merged[item['row_key']]
            updated={**payload,'order_id':None}
            item['payload']=updated
            merged[item['row_key']]={**row,'payload':updated}
            forced_changes.append({'row_key':item['row_key'],'table_name':'tracking_rows',
                'payload':updated,'deleted':False,'expected_revision':row['revision']})
        uploads_by_key={item['row_key']:item for item in uploads}
        uploads_by_key.update({item['row_key']:item for item in forced_changes})
        return {'uploads':list(uploads_by_key.values()),'incoming':incoming,'baseline':merged,'conflicts':conflicts}

    def apply(self,snapshot,plan,version,acknowledged):
        service=self.service;now=local_records(service)
        # A worker must never overwrite a newer edit made while network I/O ran.
        for item in plan['incoming']:
            if now.get(item['row_key'])!=snapshot['current'].get(item['row_key']):
                raise ValueError('동기화 중 로컬 작업이 변경되었습니다. 다음 동기화에서 다시 대조합니다.')
        staged={**plan['baseline']}
        for item,revision in acknowledged:
            staged[item['row_key']]={'table_name':item['table_name'],'payload':item['payload'],'revision':revision}
        incoming={item['row_key']:item for item in plan['incoming']}
        # Apply the entire received relationship graph atomically, with FKs deferred.
        with service.db:
            service.db.execute('PRAGMA defer_foreign_keys=ON')
            for table in reversed(TABLE_ORDER):
                for item in incoming.values():
                    if item['table_name']==table and item['payload'] is None:
                        old=snapshot['current'].get(item['row_key'],{}).get('payload')
                        if old:
                            keys=primary_keys(service.db,table)
                            where=' AND '.join(f'"{k}"=?' for k in keys)
                            service.db.execute(f'DELETE FROM "{table}" WHERE {where}',[old[k] for k in keys])
            for table in TABLE_ORDER:
                for item in incoming.values():
                    if item['table_name']!=table or item['payload'] is None:continue
                    row=item['payload'];columns=list(row);allowed={r['name'] for r in service.db.execute(f'PRAGMA table_info("{table}")')}
                    if set(columns)-allowed:raise ValueError('공유 자료에 새 필드가 있습니다. 최신 FLOW로 업데이트하세요.')
                    if table=='events':
                        if service.db.execute('SELECT 1 FROM events WHERE at=? AND action=? AND detail=?',[row[k] for k in ('at','action','detail')]).fetchone():continue
                        suffix=''
                    else:
                        keys=primary_keys(service.db,table);updates=[k for k in columns if k not in keys]
                        suffix=' ON CONFLICT ('+','.join('"'+k+'"' for k in keys)+') DO UPDATE SET '+','.join('"'+k+'"=excluded."'+k+'"' for k in updates) if updates else ' ON CONFLICT DO NOTHING'
                    names=','.join('"'+k+'"' for k in columns);marks=','.join('?' for _ in columns)
                    service.db.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})'+suffix,[_decode_value(row[k]) for k in columns])
            settings=incoming.get('settings:[]')
            if settings and settings['payload'] is not None:
                service.settings={**settings['payload'],**{k:v for k,v in service.settings.items() if k in LOCAL_SETTINGS}}
                service._write_settings()
            for key,row in staged.items():
                if snapshot['baseline'].get(key)==row:continue
                service.db.execute('INSERT OR REPLACE INTO flow_local_baseline VALUES(?,?,?,?,?)',
                    (self.context,key,row['table_name'],canonical(row['payload']) if row['payload'] is not None else None,row['revision']))
            # Store unresolved evidence locally; do not repeatedly download a full snapshot.
            if version!=snapshot['cursor']:
                service.db.execute('INSERT OR REPLACE INTO flow_local_cursor VALUES(?,?)',(self.context,version))
            if plan['conflicts']!=snapshot.get('conflicts',{}):
                service.db.execute('INSERT OR REPLACE INTO flow_local_conflicts VALUES(?,?)',(self.context,canonical(plan['conflicts'])))
        self.conflicts=plan['conflicts']
        self.choices.clear()
        return bool(incoming)
