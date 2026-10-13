"""Bounded Auth refresh and small version checks; never password-login in a loop."""
import json,time,urllib.request,urllib.error,urllib.parse,sys
from pathlib import Path
from .esm import _protect,_unprotect,load_credentials

class SyncHTTPError(RuntimeError):
    def __init__(self,status,code):
        self.status,self.code=status,code
        super().__init__(f'Supabase HTTP {status} · {code}')

class SyncTransport:
    def __init__(self,folder,config,workspace='default'):
        self.folder=Path(folder);self.url=config['supabase_url'].rstrip('/');self.key=config['supabase_publishable_key'];self.workspace=workspace
        self.session={};self.session_path=self.folder/'flow_sync_session.dat'
        if self.session_path.exists():
            try:self.session=json.loads(_unprotect(self.session_path.read_bytes()).decode())
            except Exception:self.session={}

    def request(self,path,data=None,auth=True):
        if auth:self.ensure_session()
        headers={'apikey':self.key,'Content-Type':'application/json','Accept':'application/json'}
        if auth:headers['Authorization']='Bearer '+self.session['access_token']
        req=urllib.request.Request(self.url+path,data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=20) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            try:body=json.loads(exc.read(8192))
            except ValueError:body={}
            code=body.get('message','') if str(body.get('message','')).startswith('FLOW_') else body.get('code') or body.get('error_code') or 'request_failed'
            raise SyncHTTPError(exc.code,code) from None

    def ensure_session(self,email=None,password=None):
        if email is None and self.session.get('access_token') and self.session.get('expires_at',0)>time.time()+120:return
        lock=None
        if sys.platform=='win32':
            import msvcrt
            self.folder.mkdir(parents=True,exist_ok=True)
            lock=(self.folder/'flow_sync_refresh.lock').open('a+b')
            lock.seek(0,2)
            if lock.tell()==0:lock.write(b'0');lock.flush()
            lock.seek(0)
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                lock.close();raise SyncHTTPError(409,'session_refresh_in_progress') from None
        try:
            if email is None and self.session_path.exists():
                try:
                    saved=json.loads(_unprotect(self.session_path.read_bytes()).decode())
                    if saved.get('expires_at',0)>time.time()+120:self.session=saved;return
                    if saved.get('refresh_token'):self.session=saved
                except Exception:pass
            self._renew_session(email,password)
        finally:
            if lock:
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()

    def _renew_session(self,email,password):
        if email is not None:
            body=self.request('/auth/v1/token?grant_type=password',{'email':email,'password':password},False)
        elif self.session.get('refresh_token'):
            body=self.request('/auth/v1/token?grant_type=refresh_token',{'refresh_token':self.session['refresh_token']},False)
        else:
            email,password=load_credentials(self.folder/'supabase_credentials.dat')
            if not email or not password:raise SyncHTTPError(401,'login_required')
            body=self.request('/auth/v1/token?grant_type=password',{'email':email,'password':password},False)
        self.session={'access_token':body['access_token'],'refresh_token':body['refresh_token'],'expires_at':time.time()+body.get('expires_in',3600)}
        temporary=self.session_path.with_suffix('.tmp');temporary.write_bytes(_protect(json.dumps(self.session).encode(),'REQM FLOW Supabase session'));temporary.replace(self.session_path)

    def metadata(self):
        workspace=urllib.parse.quote(self.workspace,safe='')
        result=self.request(f'/rest/v1/flow_sync_meta?select=version&workspace_key=eq.{workspace}&limit=1')
        if not result:raise SyncHTTPError(403,'workspace_access_required')
        return result[0]['version']

    def delta(self,cursor,target):
        result=[];last='';workspace=urllib.parse.quote(self.workspace,safe='')
        while True:
            path=f'/rest/v1/flow_sync_records?select=row_key,table_name,payload,deleted,revision&workspace_key=eq.{workspace}&revision=gt.{cursor}&revision=lte.{target}&order=row_key.asc&limit=500'
            if last:path+='&row_key=gt.'+urllib.parse.quote(last,safe='')
            rows=self.request(path);result.extend(rows)
            if len(rows)<500:return result
            last=rows[-1]['row_key']

    def push(self,changes):
        result=self.request('/rest/v1/rpc/flow_sync_apply',{'p_workspace':self.workspace,'p_changes':changes})
        return result['version']
