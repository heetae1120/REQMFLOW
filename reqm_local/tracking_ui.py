"""Daily invoice workspace: import, browse evidence, confirm and download."""
from __future__ import annotations

import json
import queue
import threading
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

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
        self.status = tk.StringVar(value='판매처별 출고 파일을 입력하거나 저장된 작업을 선택하세요.')
        ttk.Label(frame, text='위킵 송장 가져오기', font=(host.font_family, 18, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='출고 파일과 조회 결과를 저장합니다. 송장 확정은 실제 출고 수량·ERP 상태를 변경하지 않습니다.',
                  foreground='#64748B').pack(anchor='w', pady=(4, 10))
        inputs = ttk.Frame(frame); inputs.pack(fill='x', pady=5)
        ttk.Label(inputs, text='출고 기준일').pack(side='left')
        host.date_picker(inputs, self.day, '송장 작업 출고 기준일').pack(side='left', padx=4)
        ttk.Combobox(inputs, textvariable=self.kind, values=list(KINDS), state='readonly', width=13).pack(side='left', padx=4)
        channels = sorted({p['channel'] for p in host.service.settings['profiles'] if p.get('purpose', 'order') == 'order'})
        ttk.Combobox(inputs, textvariable=self.channel, values=['자동 인식', *channels], state='readonly', width=22).pack(side='left', padx=4)
        import_actions = ttk.Frame(frame); import_actions.pack(fill='x', pady=(0, 6))
        host.button(import_actions, '판매처 출고파일 입력', self.import_files, style='Accent.TButton')
        host.button(import_actions, '작업 조회', self.refresh)
        host.button(import_actions, '위킵 계정', self.credentials)
        self.job_tree = host.tree(frame, ['출고일', '작업 파일', '판매처', '위킵 유형', '확정 / 전체'], [105, 300, 220, 120, 110])
        self.job_tree.configure(height=2, selectmode='browse')
        self.job_tree.bind('<<TreeviewSelect>>', self.select_job)
        query = ttk.Frame(frame); query.pack(fill='x', pady=8)
        ttk.Label(query, text='위킵 주문등록일').pack(side='left')
        host.date_picker(query, self.start, '위킵 주문등록 시작일').pack(side='left', padx=4)
        ttk.Label(query, text='~').pack(side='left')
        host.date_picker(query, self.end, '위킵 주문등록 종료일').pack(side='left', padx=4)
        query_actions = ttk.Frame(frame); query_actions.pack(fill='x', pady=(0, 6))
        host.button(query_actions, '선택 작업 송장 조회 / 재조회', self.fetch, style='Accent.TButton')
        host.button(query_actions, '위킵 송장파일 대조', self.import_remote)
        ttk.Combobox(query_actions, textvariable=self.filter, values=['전체', *STATES.values()], state='readonly', width=12).pack(side='left', padx=5)
        self.filter.trace_add('write', lambda *_: self.render_rows())
        self.row_tree = host.tree(frame, ['상태', '판매처', '주문번호', '수령인', '연락처', '주소', '송장번호', '확인 내용'],
                                  [100, 130, 160, 100, 130, 240, 140, 330])
        self.row_tree.configure(height=3)
        self.row_tree.bind('<Double-1>', lambda event: host.safe(self.review))
        actions = ttk.Frame(frame); actions.pack(fill='x', pady=8)
        host.button(actions, '선택 주문 비교 / 수동 연결', self.review)
        host.button(actions, '합포장 후보 선택', self.select_peers)
        host.button(actions, '매칭 완료건 전체 확정', self.confirm_all, style='Accent.TButton')
        downloads = ttk.Frame(frame); downloads.pack(fill='x', pady=(0, 8))
        ttk.Checkbutton(downloads, text='확정건만 다운로드', variable=self.confirmed_only).pack(side='left', padx=5)
        host.button(downloads, '송장 엑셀 다운로드', self.export, style='Accent.TButton')
        host.button(downloads, '당일 전체 엑셀', self.export_day)
        host.button(downloads, '판매처 원본에 송장 반영', self.export_source)
        ttk.Label(frame, textvariable=self.status, foreground='#475569', wraplength=1150).pack(anchor='w')
        # Reserve fixed controls first; the two scrollable tables share remaining
        # height, keeping downloads visible even at the desktop's minimum size.
        frame.columnconfigure(0, weight=1)
        children = frame.winfo_children()
        for widget in children:
            widget.pack_forget()
        for index, widget in enumerate(children):
            table = widget in (self.job_tree.master, self.row_tree.master)
            widget.grid(row=index, column=0, sticky='nsew' if table else 'ew', pady=3)
            frame.rowconfigure(index, weight=(1 if widget == self.job_tree.master else 3) if table else 0)
        self.refresh()

    @property
    def service(self):
        return self.host.service

    def require_job(self):
        if not self.job_id or not any(j['id'] == self.job_id for j in self.service.tracking_jobs()):
            raise ValueError('저장된 출고 작업을 선택하세요.')
        return self.job_id

    def refresh(self):
        jobs = self.service.tracking_jobs(valid_day(self.day.get()))
        previous = self.job_id
        self.job_tree.delete(*self.job_tree.get_children())
        self.jobs = {j['id']: j for j in jobs}
        labels = {v: k for k, v in KINDS.items()}
        for j in jobs:
            self.job_tree.insert('', 'end', iid=j['id'], values=(j['day'], j['source_name'], j['channels'],
                                 labels[j['kind']], f"{j['confirmed']} / {j['total']}"))
        if previous in self.jobs:
            self.job_tree.selection_set(previous)
            self.job_id = previous
        elif jobs:
            self.job_id = jobs[0]['id']
            self.start.set(jobs[0]['day'])
            self.end.set(jobs[0]['day'])
            self.job_tree.selection_set(self.job_id)
        else:
            self.job_id = None
        self.render_rows()

    def select_job(self, event=None):
        selected = self.job_tree.selection()
        if selected:
            changed = self.job_id != selected[0]
            self.job_id = selected[0]
            if changed:
                self.start.set(self.jobs[self.job_id]['day'])
                self.end.set(self.jobs[self.job_id]['day'])
        self.render_rows()

    def render_rows(self):
        selected = set(self.row_tree.selection())
        self.row_tree.delete(*self.row_tree.get_children())
        entries = self.service.tracking_rows(self.job_id) if self.job_id else []
        self.rows = {r['id']: r for r in entries}
        for r in entries:
            d = r['data']
            if self.filter.get() not in ('전체', STATES[r['state']]):
                continue
            self.row_tree.insert('', 'end', iid=r['id'], values=(STATES[r['state']], d.get('channel', ''),
                                 d.get('order_no', ''), d.get('recipient', ''), d.get('phone', ''),
                                 d.get('address', ''), r['tracking'], r['reason']))
        self.row_tree.selection_set([rid for rid in selected if self.row_tree.exists(rid)])
        if not self.busy:
            counts = {state: sum(r['state'] == state for r in entries) for state in STATES}
            self.status.set(' · '.join(f'{STATES[s]} {n}건' for s, n in counts.items()) if entries else '판매처 출고파일을 입력하세요.')

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
        ttk.Label(win, text='로그인 정보는 이 PC에 암호화해 저장합니다. 브라우저에서 직접 로그인할 수도 있습니다.').pack(padx=16, pady=10)
        def save():
            save_credentials(self.service.folder / 'wekeep_credentials.bin', user_var.get(), password_var.get(), '위킵')
            win.destroy()
        self.host.button(win, '저장', save)

    def fetch(self):
        job = self.require_job()
        if self.busy:
            raise ValueError('위킵 조회가 이미 진행 중입니다.')
        start, end = valid_day(self.start.get()), valid_day(self.end.get())
        if start > end:
            raise ValueError('위킵 등록일 범위를 확인하세요.')
        kind = self.jobs[job]['kind']
        expected = encode(self.service.tracking_rows(job))
        self.busy = True
        self.status.set('위킵 브라우저를 여는 중입니다.')
        folder = self.service.folder
        def worker():
            try:
                rows = fetch_tracking(folder, start, end, kind, lambda text: self.messages.put(('status', text)))
                self.messages.put(('success', (job, rows, start, end, expected)))
            except Exception as exc:
                self.messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.host.root.after(200, self.poll)

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
                            self.service.apply_tracking_query(job, rows, start, end, expected)
                            self.refresh()
                        self.host.safe(apply)
                    return
        except queue.Empty:
            self.host.root.after(200, self.poll)

    def import_remote(self):
        job = self.require_job()
        if self.busy:
            raise ValueError('브라우저 조회가 끝난 뒤 대조 파일을 입력하세요.')
        path = filedialog.askopenfilename(parent=self.host.root, title='위킵에서 내려받은 송장 자료 선택',
                                         filetypes=[('송장 자료', '*.xlsx *.xlsm *.xls *.csv')])
        if path:
            self.service.apply_tracking_query(job, read_tracking_file(path), self.start.get(), self.end.get())
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
        job = self.require_job()
        row_ids = list(self.row_tree.selection())
        if not row_ids:
            raise ValueError('비교할 주문을 선택하세요.')
        rows = {r['id']: r for r in self.service.tracking_rows(job)}
        selected = [rows[rid] for rid in row_ids]
        win = tk.Toplevel(self.host.root); win.title('주문 정보 비교 · 송장 수동 연결'); win.geometry('1100x640'); win.transient(self.host.root)
        ttk.Label(win, text=f'선택한 {len(selected)}행에 적용합니다. 원본과 위킵 후보를 비교하세요.').pack(anchor='w', padx=12, pady=10)
        text = tk.Text(win, wrap='word', font=(self.host.font_family, 10)); text.pack(fill='both', expand=True, padx=12)
        for row in selected:
            d = row['data']
            lines = '\n'.join(f'{label}: {d.get(key, "")}' for label, key in
                              [('판매처', 'channel'), ('주문번호', 'order_no'), ('상품주문번호', 'line_no'),
                               ('수령인', 'recipient'), ('연락처', 'phone'), ('우편번호', 'postcode'), ('주소', 'address'), ('상품명', 'product')])
            text.insert('end', f'판매처 원본\n{lines}\n현재 송장: {row["tracking"]}\n상태: {STATES[row["state"]]} · {row["reason"]}\n')
            text.insert('end', '위킵 후보\n' + (json.dumps(row['evidence'], ensure_ascii=False, indent=2) if row['evidence'] else '조회된 후보 없음') + '\n\n')
        text.configure(state='disabled')
        number = tk.StringVar(value=selected[0]['tracking']); reason = tk.StringVar()
        line = ttk.Frame(win); line.pack(fill='x', padx=12, pady=8)
        ttk.Label(line, text='송장번호').pack(side='left'); ttk.Entry(line, textvariable=number, width=25).pack(side='left', padx=8)
        ttk.Label(line, text='수동 연결 사유').pack(side='left'); ttk.Entry(line, textvariable=reason, width=48).pack(side='left', padx=8)
        expected = encode(selected)
        def apply(manual):
            current = {r['id']: r for r in self.service.tracking_rows(job)}
            if any(rid not in current for rid in row_ids) or encode([current[rid] for rid in row_ids]) != expected:
                raise ValueError('검토 중 주문이 변경되었습니다. 비교 화면을 다시 여세요.')
            self.service.confirm_tracking(job, row_ids, number.get() if manual else None, reason.get())
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
        on = valid_day(self.day.get())
        if not self.service.tracking_jobs(on):
            raise ValueError('선택 날짜에 저장된 송장 작업이 없습니다.')
        path = filedialog.asksaveasfilename(parent=self.host.root, title='당일 판매처 전체 송장 엑셀 다운로드',
                                          initialfile=f'{on}_전체판매처_송장.xlsx', defaultextension='.xlsx',
                                          filetypes=[('Excel', '*.xlsx')])
        if path:
            self.service.export_tracking_day(on, path, self.confirmed_only.get())
            messagebox.showinfo('당일 전체 엑셀 저장', '선택 날짜의 모든 판매처 작업을 하나의 송장 엑셀로 저장했습니다.', parent=self.host.root)
