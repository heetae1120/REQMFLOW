"""Daily invoice workspace: import, browse evidence, confirm and download."""
from __future__ import annotations

import json
import queue
import threading
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from .ui_helpers import after_latest
from .esm import save_credentials, load_credentials
from .tracking import KINDS, STATES, delivery_key
from .tracking_store import encode, valid_day
from .wekeep_tracking import fetch_tracking, read_tracking_file


class TrackingPanel:
    def __init__(self, host, frame):
        self.host, self.frame = host, frame
        self.job_id = None
        self.busy = False
        self.messages = queue.Queue()
        self.rows = {}
        self.jobs = {}
        today = date.today().isoformat()
        self.day = tk.StringVar(value=today)
        self.start = tk.StringVar(value=today)
        self.end = tk.StringVar(value=today)
        self.kind = tk.StringVar(value='B2C')
        self.channel = tk.StringVar(value='자동 인식')
        self.filter = tk.StringVar(value='전체')
        self.confirmed_only = tk.BooleanVar(value=False)
        self.search = tk.StringVar()
        self.missing_only = tk.BooleanVar(value=True)
        self.files_open = False
        self.confirmed_only.set(True)
        self.status = tk.StringVar(value='B2C 출고요청을 자동으로 불러옵니다.')
        ttk.Label(frame, text='위킵 송장 일괄 가져오기 · B2C', font=(host.font_family, 16, 'bold')).grid(row=0,column=0,sticky='w',pady=(0,2))
        inputs=ttk.Frame(frame);inputs.grid(row=2,column=0,sticky='ew',pady=4)
        ttk.Label(inputs,text='출고요청 기준일').pack(side='left')
        host.date_picker(inputs,self.day,'출고요청 기준일').pack(side='left',padx=4)
        host.button(inputs,'작업 조회',self.refresh)
        host.button(inputs,'생성한 양식 펼치기 / 접기',self.toggle_files)
        host.button(inputs,'당일 위킵 양식 다운로드',self.export_template)
        self.files_frame=ttk.Frame(frame)
        self.job_tree=host.tree(self.files_frame,['출고일','작업 파일','판매처','위킵 유형','반영 / 전체'],[100,260,240,100,100])
        self.job_tree.configure(height=3,selectmode='extended')
        self.job_tree.bind('<<TreeviewSelect>>',self.select_job)
        query=ttk.Frame(frame);query.grid(row=4,column=0,sticky='ew',pady=6)
        ttk.Label(query,text='위킵 주문등록일').pack(side='left')
        host.date_picker(query,self.start,'위킵 등록 시작일').pack(side='left',padx=4)
        ttk.Label(query,text='~').pack(side='left')
        host.date_picker(query,self.end,'위킵 등록 종료일').pack(side='left',padx=4)
        host.button(query,'전체 송장 가져오기',self.fetch,style='Accent.TButton')
        ttk.Checkbutton(query,text='송장 없는 건만',variable=self.missing_only).pack(side='left',padx=6)
        host.button(query,'위킵 계정',self.credentials)
        filters=ttk.Frame(frame);filters.grid(row=5,column=0,sticky='ew',pady=4)
        self.counts=tk.StringVar()
        ttk.Label(filters,textvariable=self.counts).pack(side='left',padx=(0,12))
        ttk.Combobox(filters,textvariable=self.filter,values=['전체',*STATES.values()],state='readonly',width=12).pack(side='left',padx=4)
        ttk.Entry(filters,textvariable=self.search,width=32).pack(side='left',padx=4)
        ttk.Label(filters,text='송장 · 주문번호 · 수령인 검색').pack(side='left')
        self.filter.trace_add('write',lambda *_:self.render_rows())
        self.search.trace_add('write',lambda *_:after_latest(self.host.root,'tracking-search',self.render_rows))
        table_area=ttk.Frame(frame);table_area.grid(row=6,column=0,sticky='nsew',pady=5)
        self.row_tree=host.tree(table_area,['상태','송장번호','판매처','주문번호','수령인','연락처','상품 · 수량','확인 내용'],[95,165,115,170,100,130,220,280])
        self.row_tree.configure(height=12)
        ttk.Style().configure('Invoice.Treeview',font=(host.font_family,11),rowheight=36)
        self.row_tree.configure(style='Invoice.Treeview')
        self.row_tree.tag_configure('confirmed',foreground='#175E46')
        self.row_tree.tag_configure('review',foreground='#9A5700')
        self.row_tree.bind('<Double-1>',lambda event:host.safe(self.review))
        self.row_tree.bind('<<TreeviewSelect>>',self.show_detail)
        self.detail=tk.StringVar(value='선택한 주문의 주소와 대조 결과를 여기에 표시합니다.')
        ttk.Label(frame,textvariable=self.detail,wraplength=1100,foreground='#475569').grid(row=7,column=0,sticky='ew',pady=5)
        downloads=ttk.Frame(frame);downloads.grid(row=8,column=0,sticky='ew',pady=5)
        host.button(downloads,'송장 포함 통합 양식',self.export_day,style='Accent.TButton')
        host.button(downloads,'판매처 원본에 송장 반영',self.export_sources)
        ttk.Checkbutton(downloads,text='송장 반영건만',variable=self.confirmed_only).pack(side='left',padx=6)
        host.button(downloads,'선택 주문 비교 / 수동 연결',self.review)
        host.button(downloads,'합포장 후보 선택',self.select_peers)
        tools=ttk.Frame(self.files_frame);tools.pack(fill='x',pady=3)
        host.button(tools,'기존 출고파일 추가',self.import_files)
        host.button(tools,'위킵 송장파일 대조',self.import_remote)
        ttk.Label(frame,textvariable=self.status,foreground='#475569',wraplength=1100).grid(row=10,column=0,sticky='ew',pady=4)
        frame.columnconfigure(0,weight=1);frame.rowconfigure(6,weight=1)
        for widget in frame.grid_slaves():
            widget.grid_configure(pady=2)
        self.refresh()

    def toggle_files(self):
        self.files_open=not self.files_open
        if self.files_open:self.files_frame.grid(row=3,column=0,sticky='ew',pady=3)
        else:self.files_frame.grid_remove()

    def selected_jobs(self):
        return [j for j in self.job_tree.selection() if j in self.jobs]

    def show_detail(self,event=None):
        selected=self.row_tree.selection()
        if not selected or selected[0] not in self.rows:return
        row=self.rows[selected[0]];d=row['data']
        self.detail.set(f"{d.get('channel','')} · {d.get('order_no','')} · 주소: {d.get('postcode','')} {d.get('address','')} · {row['reason']}")

    def export_template(self):
        jobs=self.selected_jobs()
        if not jobs:raise ValueError('다운로드할 B2C 출고요청이 없습니다.')
        path=self.host.save_path(self.day.get()+'_위킵_출고요청.xlsx')
        if path:self.service.export_wekeep_jobs(jobs,path)

    def export_sources(self):
        jobs=self.selected_jobs()
        if not jobs:raise ValueError('다운로드할 B2C 출고요청이 없습니다.')
        path=filedialog.asksaveasfilename(parent=self.host.root,initialfile=self.day.get()+'_판매처별_송장반영.zip',defaultextension='.zip',filetypes=[('ZIP','*.zip')])
        if path:self.service.export_daily_sources(jobs,path)

    @property
    def service(self):
        return self.host.service

    def require_job(self):
        if not self.job_id or not any(j['id'] == self.job_id for j in self.service.tracking_jobs()):
            raise ValueError('저장된 출고 작업을 선택하세요.')
        return self.job_id

    def refresh(self):
        on=valid_day(self.day.get())
        jobs=self.service.daily_b2c_jobs(on)
        previous=set(self.job_tree.selection())
        same_day=getattr(self,'loaded_day',None)==on
        old_ids=set(self.jobs)
        self.job_tree.delete(*self.job_tree.get_children())
        self.jobs={j['id']:j for j in jobs}
        self.loaded_day=on
        for j in jobs:
            entries=self.service.active_tracking_rows(j['id'])
            count=sum(r['state']=='confirmed' for r in entries)
            self.job_tree.insert('','end',iid=j['id'],values=(j['day'],j['source_name'],j['channels'],'B2C',f'{count} / {len(entries)}'))
        selection=([j for j in self.jobs if j in previous or j not in old_ids] if same_day else list(self.jobs))
        self.job_tree.selection_set(selection)
        self.job_id=selection[0] if selection else None
        if not same_day:self.start.set(on);self.end.set(on)
        self.render_rows()

    def select_job(self,event=None):
        selected=self.selected_jobs()
        self.job_id=selected[0] if selected else None
        self.render_rows()

    def render_rows(self):
        selected=set(self.row_tree.selection())
        self.row_tree.delete(*self.row_tree.get_children())
        entries=[r for job in self.selected_jobs() for r in self.service.active_tracking_rows(job)]
        self.rows={r['id']:r for r in entries}
        query=self.search.get().strip().casefold()
        for r in entries:
            d=r['data']
            if self.filter.get() not in ('전체',STATES[r['state']]):continue
            if query and query not in ' '.join(str(d.get(k,'')) for k in ('order_no','recipient','phone','channel','product')).casefold()+' '+r['tracking']:continue
            invoice=r['tracking'] if r['state'] in ('confirmed','matched') else ('검토 필요' if r['state']=='review' else '발급 대기')
            self.row_tree.insert('','end',iid=r['id'],tags=(r['state'],),values=(STATES[r['state']],invoice,d.get('channel',''),d.get('order_no',''),d.get('recipient',''),d.get('phone',''),f"{d.get('product','')} · {d.get('quantity','')}개",r['reason']))
        self.row_tree.selection_set([rid for rid in selected if self.row_tree.exists(rid)])
        count=lambda state:sum(r['state']==state for r in entries)
        self.counts.set(f"전체 {len(entries)} · 송장 반영 {count('confirmed')} · 대기 {count('pending')} · 미확인 {count('not_found')} · 검토 {count('review')}")
        if not self.busy:self.status.set(f'선택한 B2C 작업 {len(self.selected_jobs())}개 · {len(entries)}행. 출고요청을 생성하면 자동으로 등록됩니다.')

    def import_files(self):
        if self.busy:
            raise ValueError('위킵 조회가 끝난 뒤 파일을 입력하세요.')
        paths = filedialog.askopenfilenames(parent=self.host.root, title='판매처별 출고 파일 선택',
                                           filetypes=[('출고 파일', '*.xlsx *.xlsm *.xls *.csv')])
        if not paths:
            return
        jobs, duplicates = self.service.import_tracking_files(paths, self.day.get(), KINDS[self.kind.get()],
                                      None if self.channel.get() == '자동 인식' else self.channel.get())
        self.job_id = jobs[0]
        self.start.set(valid_day(self.day.get()))
        self.end.set(valid_day(self.day.get()))
        self.refresh()
        messagebox.showinfo('출고 작업 저장', f'{len(jobs)}개 작업을 불러왔습니다. 중복 파일 {duplicates}개.', parent=self.host.root)

    def credentials(self):
        win = tk.Toplevel(self.host.root); win.title('위킵 로그인 계정'); win.transient(self.host.root)
        user, password = load_credentials(self.service.folder / 'wekeep_credentials.bin')
        user_var = tk.StringVar(value=user); password_var = tk.StringVar(value=password)
        for label, var, show in [('아이디', user_var, ''), ('비밀번호', password_var, '*')]:
            ttk.Label(win, text=label).pack(anchor='w', padx=16, pady=(12, 2))
            ttk.Entry(win, textvariable=var, show=show, width=36).pack(padx=16)
        ttk.Label(win, text='로그인 정보는 이 PC에 암호화해 저장합니다. 송장 조회는 이 계정으로 창 없이 진행합니다.').pack(padx=16, pady=10)
        def save():
            save_credentials(self.service.folder / 'wekeep_credentials.bin', user_var.get(), password_var.get(), '위킵')
            win.destroy()
        self.host.button(win, '저장', save)

    def fetch(self):
        if self.busy:raise ValueError('위킵 조회가 이미 진행 중입니다.')
        jobs=self.selected_jobs()
        if not jobs or (self.missing_only.get() and not any(r['state']!='confirmed' for j in jobs for r in self.service.active_tracking_rows(j))):
            raise ValueError('조회할 미반영 B2C 주문이 없습니다. 재조회하려면 송장 없는 건만을 해제하세요.')
        start,end=valid_day(self.start.get()),valid_day(self.end.get())
        if start>end:raise ValueError('위킵 등록일 범위를 확인하세요.')
        expected={job:encode(self.service.active_tracking_rows(job)) for job in jobs}
        self.busy=True;self.status.set('B2C 전체 송장을 백그라운드에서 조회합니다.')
        folder=self.service.folder
        def worker():
            try:
                rows=fetch_tracking(folder,start,end,'b2c',lambda text:self.messages.put(('status',text)))
                self.messages.put(('success',(jobs,rows,start,end,expected)))
            except Exception as exc:self.messages.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
        self.host.root.after(200,self.poll)

    def poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == 'status':
                    self.status.set(payload)
                else:
                    self.busy = False
                    if kind == 'error':
                        self.status.set('조회 실패 · 기존 저장 자료를 유지했습니다.')
                        messagebox.showerror('위킵 조회', payload, parent=self.host.root)
                    else:
                        job, rows, start, end, expected = payload
                        def apply():
                            self.service.apply_daily_tracking(job, rows, start, end, expected)
                            self.refresh()
                        self.host.safe(apply)
                    return
        except queue.Empty:
            self.host.root.after(200, self.poll)

    def import_remote(self):
        jobs=self.selected_jobs()
        if not jobs:raise ValueError('대조할 작업을 선택하세요.')
        if self.busy:
            raise ValueError('브라우저 조회가 끝난 뒤 대조 파일을 입력하세요.')
        path = filedialog.askopenfilename(parent=self.host.root, title='위킵에서 내려받은 송장 자료 선택',
                                         filetypes=[('송장 자료', '*.xlsx *.xlsm *.xls *.csv')])
        if path:
            self.service.apply_daily_tracking(jobs, read_tracking_file(path), self.start.get(), self.end.get())
            self.refresh()

    def select_peers(self):
        self.require_job()
        selected = self.row_tree.selection()
        if len(selected) != 1:
            raise ValueError('합포장을 확인할 기준 주문 하나를 선택하세요.')
        row = self.rows[selected[0]]
        key = delivery_key(row['data'])
        if key is None:
            raise ValueError('수령인·연락처·우편번호·주소가 모두 있어야 합포장 후보를 찾을 수 있습니다.')
        self.filter.set('전체')
        self.row_tree.selection_set([r['id'] for r in self.rows.values() if delivery_key(r['data']) == key])
        self.status.set('같은 배송지의 합포장 후보를 선택했습니다. 주문 비교에서 확인 후 수동 연결하세요.')

    def review(self):
        jobs=self.selected_jobs()
        row_ids = list(self.row_tree.selection())
        if not row_ids:
            raise ValueError('비교할 주문을 선택하세요.')
        rows = {r['id']: r for j in jobs for r in self.service.active_tracking_rows(j)}
        selected = [rows[rid] for rid in row_ids]
        win = tk.Toplevel(self.host.root); win.title('주문 정보 비교 · 송장 수동 연결'); win.geometry('1100x640'); win.transient(self.host.root)
        win.grab_set()
        ttk.Label(win, text=f'선택한 {len(selected)}행에 적용합니다. 원본과 위킵 후보를 비교하세요.').pack(anchor='w', padx=12, pady=10)
        comparison=ttk.PanedWindow(win,orient='horizontal');comparison.pack(fill='both',expand=True,padx=12)
        left=ttk.Frame(comparison);right=ttk.Frame(comparison);comparison.add(left,weight=1);comparison.add(right,weight=1)
        ttk.Label(left,text='FLOW 출고요청',font=(self.host.font_family,12,'bold')).pack(anchor='w',pady=6)
        ttk.Label(right,text='위킵 조회 후보',font=(self.host.font_family,12,'bold')).pack(anchor='w',pady=6)
        original_tree=self.host.tree(left,['항목','내용'],[110,400])
        candidate_tree=self.host.tree(right,['항목','내용'],[110,400])
        for row in selected:
            d = row['data']
            fields=[('판매처','channel'),('주문번호','order_no'),('상품주문번호','line_no'),('수령인','recipient'),('연락처','phone'),('우편번호','postcode'),('주소','address'),('상품명','product')]
            for label,key in fields:original_tree.insert('','end',values=(label,d.get(key,'')))
            original_tree.insert('','end',values=('현재 송장',row['tracking']))
            original_tree.insert('','end',values=('대조 결과',row['reason']))
            if not row['evidence']:candidate_tree.insert('','end',values=('조회 결과','후보 없음'))
            for index,candidate in enumerate(row['evidence'],1):
                candidate_tree.insert('','end',values=(f'후보 {index}',candidate.get('tracking','송장 미발급')))
                for label,key in fields:candidate_tree.insert('','end',values=(label,candidate.get(key,'')))
                candidate_tree.insert('','end',values=('추가 송장',candidate.get('additional_tracking','')))
                candidate_tree.insert('','end',values=('상품 상세',json.dumps(candidate.get('items',[]),ensure_ascii=False)))
        number = tk.StringVar(value=selected[0]['tracking']); reason = tk.StringVar()
        line = ttk.Frame(win); line.pack(fill='x', padx=12, pady=8)
        ttk.Label(line, text='송장번호').pack(side='left'); ttk.Entry(line, textvariable=number, width=25).pack(side='left', padx=8)
        ttk.Label(line, text='수동 연결 사유').pack(side='left'); ttk.Entry(line, textvariable=reason, width=48).pack(side='left', padx=8)
        expected = encode(selected)
        def apply(manual):
            current = {r['id']: r for j in jobs for r in self.service.active_tracking_rows(j)}
            if any(rid not in current for rid in row_ids) or encode([current[rid] for rid in row_ids]) != expected:
                raise ValueError('검토 중 주문이 변경되었습니다. 비교 화면을 다시 여세요.')
            with self.service.db:
                for job in jobs:
                    ids=[rid for rid in row_ids if current[rid]['job_id']==job]
                    if ids:self.service.confirm_tracking(job,ids,number.get() if manual else None,reason.get(),_manage_transaction=False)
            self.refresh(); win.destroy()
        buttons = ttk.Frame(win); buttons.pack(fill='x', padx=12, pady=10)
        self.host.button(buttons, '자동 매칭 결과 확정', lambda: apply(False))
        self.host.button(buttons, '확인 후 수동 송장 적용', lambda: apply(True), style='Accent.TButton')

    def confirm_all(self):
        job = self.require_job()
        ids = [r['id'] for r in self.service.tracking_rows(job) if r['state'] == 'matched']
        if not ids:
            raise ValueError('새로 확정할 자동 매칭 완료 주문이 없습니다.')
        self.service.confirm_tracking(job, ids)
        self.refresh()

    def export(self):
        job = self.require_job()
        path = filedialog.asksaveasfilename(parent=self.host.root, title='송장번호 포함 엑셀 다운로드',
                                          initialfile=f'{self.jobs[job]["day"]}_{Path(self.jobs[job]["source_name"]).stem}_송장.xlsx',
                                          defaultextension='.xlsx', filetypes=[('Excel', '*.xlsx')])
        if path:
            self.service.export_tracking(job, path, self.confirmed_only.get())
            messagebox.showinfo('송장 엑셀 저장', '주문번호·판매처·수령인정보·확정 송장번호를 저장했습니다.\n미확정 주문의 송장번호는 비워 두며 확인 상태 시트에서 확인할 수 있습니다.', parent=self.host.root)

    def export_source(self):
        job = self.require_job()
        name = Path(self.jobs[job]['source_name'])
        path = filedialog.asksaveasfilename(parent=self.host.root, title='판매처 원본 송장 반영 파일 저장',
                                          initialfile=name.stem + '_송장반영' + name.suffix,
                                          defaultextension=name.suffix)
        if path:
            self.service.export_tracking_source(job, path)
            messagebox.showinfo('판매처 파일 저장', '원본 형식에 확정된 송장번호를 반영해 저장했습니다.', parent=self.host.root)

    def export_day(self):
        jobs=self.selected_jobs()
        if not jobs:raise ValueError('다운로드할 B2C 출고요청이 없습니다.')
        path=self.host.save_path(self.day.get()+'_위킵_송장포함.xlsx')
        if path:self.service.export_wekeep_jobs(jobs,path,with_tracking=True,confirmed_only=self.confirmed_only.get())
