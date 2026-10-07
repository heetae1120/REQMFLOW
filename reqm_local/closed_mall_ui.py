"""Closed-mall panel; secrets stay in the local Windows account."""
import threading
import queue
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .closed_malls import MALLS, CodeRequest, load_accounts, local_login_folder, read_account_workbook, save_accounts
from .closed_mall_browser import run_logins, connect_auth_browser


class ClosedMallPanel:
    def __init__(self, parent, root):
        self.root = root
        self.folder = local_login_folder()
        self.session = None
        self.running = False
        self.closing = False
        self.stop = threading.Event()
        self.code_window = None
        self.code_request = None
        self.accounts = {}
        self.message = tk.StringVar(value='계정 엑셀을 불러오고 판매처를 선택하세요.')
        self.background = tk.BooleanVar(value=True)
        ttk.Label(parent, text='폐쇄몰 로그인', font=('', 16, 'bold')).pack(anchor='w')
        ttk.Label(parent, text='판매처 계정을 자동 입력하고 로그인 결과를 확인합니다. 무신사·29CM 인증은 순서대로 진행합니다.\n이알아이·삼성카드복지몰·한섬은 다른 휴대전화로 받은 인증번호를 FLOW 입력창에 입력하세요.\n이지웰은 로그인 후 복지샵 채널로 전환합니다.', wraplength=1050).pack(anchor='w', pady=12)
        actions = ttk.Frame(parent)
        actions.pack(fill='x')
        for label, callback in [('계정 엑셀 불러오기', self.import_accounts), ('선택 판매처 실행', self.start), ('인증 수신 연결', self.connect_auth), ('중단', self.stop.set), ('브라우저 세션 닫기', self.close_session), ('결과 기록 열기', self.open_results)]:
            ttk.Button(actions, text=label, command=callback).pack(side='left', padx=4)
        ttk.Checkbutton(parent, text='백그라운드 실행 · 크림은 해제하여 화면 실행', variable=self.background).pack(anchor='w', pady=8)
        ttk.Label(parent, textvariable=self.message, wraplength=1050).pack(anchor='w', pady=6)
        self.table = ttk.Treeview(parent, columns=('판매처', '인증', '계정', '실행 결과'), show='headings', selectmode='extended')
        for name, width in [('판매처', 150), ('인증', 150), ('계정', 100), ('실행 결과', 580)]:
            self.table.heading(name, text=name)
            self.table.column(name, width=width)
        self.table.pack(fill='both', expand=True)
        methods = {'email': '이메일', 'optional_email': '필요시 이메일', 'sms': 'SMS', 'manual_sms': '작업자 인증번호', 'password': '일반 로그인', 'unverified': 'ID/PW · 추가 인증 미확인'}
        for mall in MALLS:
            self.table.insert('', 'end', iid=mall.key, values=(mall.name, methods[mall.method], '미등록', '대기'))
        self.table.selection_set(('musinsa', '29cm'))
        self.accounts = {}
        try:
            self.accounts = load_accounts(self.folder)
            self.refresh_accounts()
        except RuntimeError as exc:
            self.message.set(str(exc))
        self.events = queue.Queue()
        self.root.after(200, self.poll)

    def refresh_accounts(self):
        for mall in MALLS:
            self.table.set(mall.key, '계정', '등록됨' if mall.key in self.accounts else '미등록')

    def open_results(self):
        folder = self.folder / 'runs'
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def connect_auth(self):
        if self.running or self.session:
            self.message.set('진행 중인 작업을 마치고 브라우저 세션을 닫은 뒤 연결하세요.')
            return
        self.running = True
        self.message.set('메일·Google 메시지 연결 화면을 여는 중입니다.')
        def work():
            try:
                session = connect_auth_browser(self.folder)
                if self.closing:
                    session.close()
                else:
                    self.events.put(('connected', session))
            except Exception:
                self.events.put(('error',))
        threading.Thread(target=work, daemon=True).start()

    def import_accounts(self):
        if self.running:
            return
        path = filedialog.askopenfilename(parent=self.root, filetypes=[('계정 엑셀', '*.xlsx')])
        if not path:
            return
        try:
            accounts = read_account_workbook(path)
            if not accounts:
                raise ValueError('등록된 판매처 URL의 계정이 없습니다.')
            save_accounts(self.folder, accounts)
            self.accounts = accounts
            self.refresh_accounts()
            self.message.set('계정을 이 PC의 Windows 암호화 저장소에 저장했습니다.')
        except Exception:
            messagebox.showerror('계정 불러오기', '계정입력양식 시트와 열 이름·URL을 확인하세요. 계정 저장에 실패했습니다.', parent=self.root)

    def start(self):
        if self.running or self.session:
            self.message.set('진행 중인 작업을 마치고 브라우저 세션을 닫은 뒤 실행하세요.')
            return
        keys = set(self.table.selection())
        malls = [m for m in MALLS if m.key in keys]
        if not malls:
            self.message.set('실행할 판매처를 선택하세요.')
            return
        background = self.background.get()
        self.stop.clear()
        self.running = True
        self.message.set('브라우저 시작 중 · 동일 통합 로그인 인증은 순차 실행합니다.')
        accounts = dict(self.accounts)
        def work():
            try:
                session = run_logins(self.folder, accounts, malls, self.stop,
                    lambda key, text: self.events.put(('progress', key, text)), self.ask_code, background)
                if self.closing:
                    session.close()
                else:
                    self.events.put(('done', session))
            except Exception:
                self.events.put(('error',))
        threading.Thread(target=work, daemon=True).start()

    def ask_code(self, request, stop):
        self.events.put(('code', request))
        while not request.ready.wait(.2):
            if stop.is_set() or not request.remaining():
                request.cancel()
        code, request.code = request.code, None
        return code

    def show_code_window(self, request):
        if request.cancelled or not request.remaining():
            return
        if self.code_window:
            self.code_window.destroy()
            if self.code_request:
                self.code_request.cancel()
        self.code_request = request
        window = self.code_window = tk.Toplevel(self.root)
        window.title(request.mall.name + ' 인증번호 입력')
        window.transient(self.root)
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=request.mall.name, font=('', 14, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=request.instructions, wraplength=410).pack(anchor='w', pady=12)
        entry = ttk.Entry(frame, width=24, show='*')
        entry.pack(fill='x')
        feedback = tk.StringVar()
        ttk.Label(frame, textvariable=feedback, wraplength=410).pack(anchor='w', pady=8)
        def finish(cancel=False):
            if cancel:
                request.cancel()
            elif not request.submit(entry.get()):
                feedback.set(f'인증번호 숫자 {request.digits}자리를 입력하세요.')
                return
            entry.delete(0, 'end')
            window.destroy()
            self.code_window = self.code_request = None
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='인증번호 제출', command=finish).pack(side='left')
        ttk.Button(buttons, text='이 판매처 취소', command=lambda: finish(True)).pack(side='right')
        window.protocol('WM_DELETE_WINDOW', lambda: finish(True))
        entry.bind('<Return>', lambda event: finish())
        def tick():
            if not window.winfo_exists():
                return
            if self.stop.is_set() or request.ready.is_set() or not request.remaining():
                finish(True)
                return
            feedback.set(f'남은 입력 시간 {int(request.remaining())}초 · 인증번호는 저장하지 않습니다.')
            window.after(500, tick)
        entry.focus_set()
        window.lift()
        tick()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'progress':
                    self.table.set(event[1], '실행 결과', event[2])
                    self.message.set(event[2])
                elif event[0] == 'code':
                    if not self.stop.is_set():
                        self.show_code_window(event[1])
                    else:
                        event[1].cancel()
                elif event[0] == 'done':
                    self.session = event[1]
                    self.running = False
                    results = self.session.results
                    successes = sum(r.status == '성공' for r in results)
                    self.message.set(f'실행 종료 · 성공 {successes}/{len(results)}개 · 결과를 이 PC에 저장했습니다. 브라우저 세션을 닫으면 다시 실행할 수 있습니다.')
                elif event[0] == 'connected':
                    self.session = event[1]
                    self.running = False
                    self.message.set('열린 Chrome에서 두 메일에 로그인하고 Google 메시지를 REQM CS(reqm.cs@gmail.com)·전화번호 끝자리 2054로 연결하세요. 완료 후 FLOW의 브라우저 세션 닫기를 누르고 로그인 실행하세요.')
                elif event[0] == 'error':
                    self.running = False
                    self.message.set('브라우저 시작 또는 결과 저장 실패. Chrome 설치와 네트워크·저장 폴더를 확인하세요.')
                elif event[0] == 'closed':
                    self.running = False
                    self.message.set('브라우저 세션을 닫았습니다.')
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(200, self.poll)

    def close_session(self):
        if self.running:
            self.stop.set()
            self.message.set('중단 요청을 처리 중입니다. 완료 후 세션을 닫으세요.')
            return
        if self.session:
            session, self.session = self.session, None
            self.running = True
            def close():
                try:
                    session.close()
                finally:
                    self.events.put(('closed',))
            threading.Thread(target=close, daemon=True).start()

    def shutdown(self):
        self.closing = True
        self.stop.set()
        if self.code_request:
            self.code_request.cancel()
        if self.session:
            threading.Thread(target=self.session.close, daemon=True).start()
