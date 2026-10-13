"""Local synthetic browser QA only. Never deployed; never uses real credentials."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
import json,datetime,urllib.parse

ROOT=Path(__file__).resolve().parents[1]/'dist'
TODAY=datetime.date.today().isoformat()
revision=1
records={}
def add(table,payload):
    key=table+':'+json.dumps([payload.get('id',payload.get('key'))],ensure_ascii=False)
    records[key]={'row_key':key,'table_name':table,'payload':payload,'deleted':False,'revision':revision}
data={'channel':'오늘의집','account':'기본','order_no':'QA-001','line_no':'QA-L1','product':'검증용 보조배터리','option':'블랙',
      'quantity':'1','amount':'34900','shipping':'3000','bundle':'','recipient':'가상 수령인','phone':'01000000000','postcode':'00123',
      'address':'실제 배송 금지 테스트 주소','memo':'','_registered_day':TODAY}
components=[{'code':'[RQM]-QP2000C1-BK','name':'QP2000C 블랙','quantity':1,'amount':'34900','unit_amount':'0','warehouse':'300','customer':'TEST'}]
add('orders',{'id':'QA-ORDER','identity':'QA-IDENTITY','data':json.dumps(data,ensure_ascii=False),'components':json.dumps(components,ensure_ascii=False),'state':'출고 준비','issue':''})
add('smartstore_erp_rows',{'id':'QA-SMART','identity':'QA-SMART','day':TODAY,'data':json.dumps({**data,'channel':'리큐엠_스마트스토어','order_no':'QA-SMART'},ensure_ascii=False),'components':'[]','erp_id':None,'issue':'상품 매칭 필요','amount_split_confirmed':0})
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=ROOT,**kwargs)
    def log_message(self,*args):pass
    def send_json(self,data,status=200):
        content=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
    def do_GET(self):
        p=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(p.query)
        if p.path=='/app.mjs':
            content=(ROOT/'app.mjs').read_text(encoding='utf-8').replace('https://jcslohuraqclhryeqxoc.supabase.co','http://127.0.0.1:4600')
            self.send_response(200);self.send_header('Content-Type','text/javascript');self.end_headers();self.wfile.write(content.encode());return
        if p.path=='/auth/v1/user':self.send_json({'email':'qa@example.invalid'});return
        if p.path=='/rest/v1/flow_sync_members':self.send_json([{'workspace_key':'default'}]);return
        if p.path=='/rest/v1/flow_sync_meta':self.send_json([{'version':revision}]);return
        if p.path=='/rest/v1/flow_sync_records':
            table=q.get('table_name',[''])[0];rows=list(records.values())
            if table.startswith('eq.'):rows=[r for r in rows if r['table_name']==table[3:]]
            elif table.startswith('in.'):rows=[r for r in rows if r['table_name'] in table[4:-1].split(',')]
            bounds=q.get('revision',[])
            for b in bounds:
                if b.startswith('gt.'):rows=[r for r in rows if r['revision']>int(b[3:])]
                if b.startswith('lte.'):rows=[r for r in rows if r['revision']<=int(b[4:])]
            if 'row_key' in q:rows=[r for r in rows if r['row_key']==q['row_key'][0][3:]]
            if 'payload->>' in q.get('select',[''])[0]:rows=[{**{k:r[k] for k in ('row_key','table_name','revision','deleted')},**{k:r['payload'].get(k) for k in ('id','identity','kind','day','registered','source_name')}} for r in rows]
            offset=int(q.get('offset',['0'])[0]);self.send_json(rows[offset:offset+int(q.get('limit',['500'])[0])]);return
        super().do_GET()
    def do_POST(self):
        global revision
        body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
        if self.path.startswith('/auth/v1/token'):
            self.send_json({'access_token':'qa-only','refresh_token':'qa-only','expires_in':3600,'user':{'email':'qa@example.invalid'}});return
        if self.path=='/rest/v1/rpc/flow_sync_apply':
            changes=body['p_changes']
            if any(records.get(c['row_key'],{}).get('revision',0)!=c['expected_revision'] for c in changes):self.send_json({'message':'FLOW_ROW_CONFLICT'},400);return
            revision+=1
            for c in changes:records[c['row_key']]={**c,'revision':revision}
            self.send_json({'version':revision});return
        self.send_json({'message':'not found'},404)
print('Synthetic QA only: http://127.0.0.1:4600',flush=True)
ThreadingHTTPServer(('127.0.0.1',4600),Handler).serve_forever()
