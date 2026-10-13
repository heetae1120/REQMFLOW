"""Single background sync worker, bounded retries, explicit conflict review."""
import json,os,queue,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from .cloud import load_cloud_config
from .esm import save_credentials,load_credentials
from .incremental_sync import IncrementalSync,canonical
from .sync_transport import SyncTransport,SyncHTTPError

class SyncPanel:
    def __init__(self,host,parent):
        self.host=host;self.service=host.service;self.messages=queue.Queue();self.busy=False;self.paused=False;self.failures=0;self.next_at=0
        self.transport=SyncTransport(self.service.folder,load_cloud_config())
        self.engine=IncrementalSync(self.service,self.transport.url+'/default')
        self.enabled=tk.BooleanVar(value=bool(self.service.settings.get('flow_sync_enabled',False)))
        box=ttk.LabelFrame(parent,text='Supabase 공유 작업공간',padding=10);box.pack(fill='x',pady=8)
        row=ttk.Frame(box);row.pack(fill='x')
        ttk.Checkbutton(row,text='자동 동기화 사용',variable=self.enabled,command=self.toggle).pack(side='left',padx=4)
        host.button(row,'로그인 / 다시 연결',self.login)
        host.button(row,'지금 동기화',self.manual)
        host.button(row,'충돌 자료 비교',self.review)
        ttk.Label(box,text='변경된 행만 공유합니다. 초기 대조와 동시 편집 충돌은 확인 전 덮어쓰지 않습니다.',wraplength=1000).pack(anchor='w',pady=(6,0))
        if os.environ.get('REQM_SELF_TEST')!='1':host.root.after(800,self.tick)

    def toggle(self):
        self.service.settings['flow_sync_enabled']=self.enabled.get();self.service._write_settings()
        self.paused=False;self.failures=0;self.next_at=0
        if self.enabled.get():self.manual()
        else:self.host.cloud_status.set('로컬 저장 · 동기화 꺼짐')

    def login(self):
        if self.busy:raise ValueError('동기화가 끝난 뒤 로그인하세요.')
        win=tk.Toplevel(self.host.root);win.title('Supabase 공유 작업공간 로그인');win.transient(self.host.root);win.grab_set()
        user,password=load_credentials(self.service.folder/'supabase_credentials.dat')
        email=tk.StringVar(value=user);secret=tk.StringVar(value=password)
        for label,value,show in [('이메일',email,''),('비밀번호',secret,'*')]:
            ttk.Label(win,text=label).pack(anchor='w',padx=16,pady=(10,3));ttk.Entry(win,textvariable=value,show=show,width=40).pack(padx=16)
        status=tk.StringVar(value='각 PC에서 프로젝트 사용자 계정으로 로그인합니다.')
        ttk.Label(win,textvariable=status,wraplength=360).pack(padx=16,pady=10)
        def connect():
            if self.busy:return
            self.busy=True;button.configure(state='disabled');status.set('로그인 확인 중…')
            user=email.get().strip();password=secret.get()
            def worker():
                try:
                    self.transport.ensure_session(user,password)
                    self.transport.metadata()
                    self.messages.put(('login', (win,user,password)))
                except Exception as exc:self.messages.put(('login_error',(status,button,exc)))
            threading.Thread(target=worker,daemon=True).start()
            self.host.root.after(100,self.poll)
        button=ttk.Button(win,text='연결',command=connect);button.pack(pady=(0,12))

    def manual(self):
        self.paused=False;self.failures=0;self.next_at=0
        self.start()

    def tick(self):
        if self.host._quitting:return
        if self.enabled.get() and not self.paused and not self.busy and self.host.root.grab_current() is None and time.monotonic()>=self.next_at:self.start()
        self.host.root.after(1000,self.tick)

    def start(self):
        if self.busy:return
        snapshot=self.engine.prepare()
        self.busy=True;self.host.cloud_status.set('공유 변경 확인 중…')
        def worker():
            try:
                target=self.transport.metadata()
                remote=self.transport.delta(snapshot['cursor'],target) if target>snapshot['cursor'] else []
                plan=self.engine.plan(snapshot,remote)
                acknowledgements=[]
                if plan['uploads']:
                    revision=self.transport.push(plan['uploads'])
                    acknowledgements=[(entry,revision) for entry in plan['uploads']]
                self.messages.put(('success',(snapshot,plan,target,acknowledgements)))
            except Exception as exc:self.messages.put(('error',exc))
        threading.Thread(target=worker,daemon=True).start()
        self.host.root.after(100,self.poll)

    def poll(self):
        if self.host._quitting:return
        try:kind,payload=self.messages.get_nowait()
        except queue.Empty:
            self.host.root.after(100,self.poll);return
        if kind=='success' and self.host.root.grab_current() is not None:
            self.messages.put((kind,payload));self.host.root.after(250,self.poll);return
        self.busy=False
        if kind=='login_error':
            status,button,exc=payload
            if button.winfo_exists():button.configure(state='normal');status.set(str(exc))
            self.failed(exc);return
        if kind=='login':
            win,email,password=payload
            save_credentials(self.service.folder/'supabase_credentials.dat',email,password,'Supabase API')
            self.service.settings['cloud_email']=email
            self.enabled.set(True);self.service.settings['flow_sync_enabled']=True;self.service._write_settings()
            self.paused=False
            backup=self.service.folder/'backups'/'before-incremental-sharing.sqlite3'
            if not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);self.service.backup(backup)
            if win.winfo_exists():win.destroy()
            self.start();return
        if kind=='error':self.failed(payload);return
        snapshot,plan,target,ack=payload
        try:
            changed=self.engine.apply(snapshot,plan,target,ack)
            if changed:
                self.host.refresh()
                if hasattr(self.host,'load_matching_profile'):self.host.load_matching_profile()
            self.failures=0;self.next_at=time.monotonic()+30
            count=len(self.engine.conflicts)
            pending=self.engine.plan(self.engine.prepare(),[])['uploads']
            if pending:self.next_at=time.monotonic()+1
            self.host.cloud_status.set(f'공유 DB · 검토 {count}건' if count else '공유 저장 대기' if pending else '공유 DB 동기화됨')
        except Exception as exc:self.failed(exc)

    def failed(self,exc):
        self.failures+=1;self.next_at=time.monotonic()+min(300,30*2**min(self.failures-1,4))
        if 'FLOW_ROW_CONFLICT' in str(exc):
            message='동시 편집 확인 중';self.next_at=time.monotonic()+5
        elif 'FLOW_BATCH_TOO_LARGE' in str(exc):
            self.paused=True;message='공유 자료 크기 초과 · 검토 필요'
        elif isinstance(exc,SyncHTTPError) and exc.status in (400,401,403,402,429):
            self.paused=True
            message='사용량 제한 · 자동 재시도 중단' if exc.status in (402,429) else '로그인·권한 확인 필요'
        else:message='연결 대기 · 로컬 자료 유지'
        self.host.cloud_status.set(message)

    def review(self):
        self.engine.prepare()
        if not self.engine.conflicts:
            messagebox.showinfo('공유 자료 대조','확인할 충돌 자료가 없습니다.',parent=self.host.root);return
        win=tk.Toplevel(self.host.root);win.title('초기 자료 대조 / 동시 편집 충돌');win.geometry('1100x650');win.transient(self.host.root);win.grab_set()
        ttk.Label(win,text='서버와 이 PC의 자료가 다른 항목입니다. 선택한 항목의 기준을 결정하세요. 원본 DB는 백업되어 있습니다.',wraplength=1000).pack(anchor='w',padx=12,pady=10)
        tree=self.host.tree(win,['자료','키','차이'],[150,380,400]);tree.configure(height=7)
        keys={}
        for index,(key,entry) in enumerate(self.engine.conflicts.items()):
            rid=str(index);keys[rid]=key
            local=entry['local'];remote=entry['remote']
            changed='서버에만 있음' if local is None else '이 PC에만 있음' if remote is None else ', '.join(k for k in set(local)|set(remote) if local.get(k)!=remote.get(k))
            tree.insert('','end',iid=rid,values=(entry['table_name'],key,changed))
        detail=tk.Text(win,height=12,wrap='word');detail.pack(fill='both',expand=True,padx=12)
        def show(_=None):
            selection=tree.selection()
            if not selection:return
            entry=self.engine.conflicts[keys[selection[0]]]
            def safeview(data):return {k:('[파일 원본]' if isinstance(v,dict) and '__reqm_bytes__' in v else v) for k,v in (data or {}).items()}
            detail.configure(state='normal');detail.delete('1.0','end')
            detail.insert('end','이 PC\n'+json.dumps(safeview(entry['local']),ensure_ascii=False,indent=2)+'\n\n서버\n'+json.dumps(safeview(entry['remote']),ensure_ascii=False,indent=2));detail.configure(state='disabled')
        tree.bind('<<TreeviewSelect>>',show)
        def choose(direction):
            if self.busy:raise ValueError('진행 중인 동기화가 끝난 뒤 선택하세요.')
            chosen=[keys[r] for r in tree.selection()]
            if not chosen:raise ValueError('대조할 항목을 선택하세요.')
            self.engine.choices.update({key:direction for key in chosen});win.destroy();self.manual()
        actions=ttk.Frame(win);actions.pack(fill='x',padx=12,pady=10)
        self.host.button(actions,'선택 항목: 이 PC 자료 사용',lambda:choose('local'))
        self.host.button(actions,'선택 항목: 서버 자료 사용',lambda:choose('remote'))
        self.host.button(actions,'전체 선택',lambda:tree.selection_set(tree.get_children()))
