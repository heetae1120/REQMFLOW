import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date
from decimal import Decimal


class VoucherPanel:
    def __init__(self, app, parent):
        self.app, self.service = app, app.service
        self.start = tk.StringVar(value=date.today().isoformat())
        self.end = tk.StringVar(value=self.start.get())
        self.voucher_day = tk.StringVar(value=self.start.get())
        self.search = tk.StringVar()
        self.status = tk.StringVar()
        line = ttk.Frame(parent); line.pack(fill='x')
        for label, variable in (('출고 시작일', self.start), ('종료일', self.end), ('전표일', self.voucher_day)):
            ttk.Label(line, text=label).pack(side='left', padx=4)
            app.date_picker(line, variable, label).pack(side='left')
        app.button(line, '조회', self.refresh)
        app.button(line, '기존 세트 금액 적용', self.reuse)
        app.button(line, '색상 공유 그룹', self.families)
        actions = ttk.Frame(parent); actions.pack(fill='x', pady=8)
        ttk.Label(actions, text='주문번호·수령인·판매처·품목 검색').pack(side='left')
        entry = ttk.Entry(actions, textvariable=self.search, width=28); entry.pack(side='left', padx=5)
        entry.bind('<Return>', lambda _: app.safe(self.refresh))
        app.button(actions, '선택 주문 금액 입력', self.edit, style='Accent.TButton')
        app.button(actions, '배송비 검수', self.fees)
        app.button(actions, '전표 미리보기', self.preview)
        app.button(actions, 'ERP 파일 생성', self.export, style='Accent.TButton')
        ttk.Label(parent, text='출고 확정 후 사용하세요. 구성품 금액은 단가가 아닌 해당 출고수량의 총금액입니다. 주문 상세는 행을 더블클릭하세요.').pack(anchor='w')
        self.tree = app.tree(parent, ['출고일', '판매처', '품목코드', '품목명', '수량', '상품금액', '상태'], [100, 130, 190, 300, 65, 110, 160])
        self.tree.bind('<Double-1>', lambda _: app.safe(self.edit))
        ttk.Label(parent, textvariable=self.status).pack(anchor='w', pady=6)
        self.rows = {}

    def refresh(self):
        self.tree.delete(*self.tree.get_children()); self.rows = {}
        groups = self.service.voucher_rows(self.start.get(), self.end.get())
        terms = self.search.get().casefold().split()
        for group in groups:
            text = str([group['channel'], group['data'].get('order_no'), group['data'].get('recipient'), group['components']]).casefold()
            if any(term not in text for term in terms):
                continue
            suggestion = self.service.voucher_suggestion(group) if not group['confirmed'] else None
            state = group['issue'] or ('금액 확정' if group['confirmed'] else '기존 기준 적용 가능' if suggestion else '금액 확인 필요')
            for component in group['components'] or [{}]:
                key = str(len(self.rows)); self.rows[key] = group
                code = component.get('code', '')
                self.tree.insert('', 'end', iid=key, values=[group['day'], group['channel'], code,
                    self.service.item_name(code, component.get('name', '')), component.get('quantity', ''), component.get('amount', ''), state])
        total = sum((g['total'] for g in groups), Decimal(0))
        pending = sum(not g['confirmed'] or bool(g['issue']) for g in groups)
        self.status.set(f'미생성 주문 {len(groups)}건 · 상품금액 {total:,.0f}원 · 금액/매칭 확인 필요 {pending}건')

    def reuse(self):
        count = self.service.reuse_voucher_amounts(self.start.get(), self.end.get())
        self.app.refresh()
        messagebox.showinfo('세트 금액 적용', f'같은 구성·판매금액의 세트 {count}건에 배분액을 적용했습니다.')

    def edit(self):
        group = self.rows[self.app.selected(self.tree)[0]]
        # Re-read after sync or an edit in another screen.
        group = next((g for g in self.service.voucher_rows(self.start.get(), self.end.get()) if g['id'] == group['id']), None)
        if not group or group['issue'] or not group['components']:
            raise ValueError('상품 매칭을 먼저 완료하거나 목록을 다시 조회하세요.')
        win = tk.Toplevel(self.app.root); win.title('전표 상품금액 입력'); win.transient(self.app.root); win.grab_set()
        frame = ttk.Frame(win, padding=18); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f"{group['channel']} · 주문 {group['data'].get('order_no', '')} · {group['data'].get('recipient', '')}").pack(anchor='w')
        total = tk.StringVar(value=str(group['total'] if group['confirmed'] or not group['full'] else group['data'].get('amount') or '0'))
        ttk.Label(frame, text='이번 출고 상품 총금액 (배송비 제외)').pack(anchor='w', pady=(12, 2))
        ttk.Entry(frame, textvariable=total).pack(anchor='w')
        suggestion = self.service.voucher_suggestion(group)
        values = []
        for index, component in enumerate(group['components']):
            name = self.service.item_name(component['code'], component.get('name', ''))
            ttk.Label(frame, text=f"{name} · {component['code']} · 수량 {component['quantity']} · 색상공유 그룹 {self.service.voucher_family(component['code'])}").pack(anchor='w', pady=(8, 2))
            variable = tk.StringVar(value=suggestion[index] if suggestion else str(component['amount']))
            values.append(variable); ttk.Entry(frame, textvariable=variable).pack(anchor='w')
        if len(values) == 1:
            total.trace_add('write', lambda *_: values[0].set(total.get()))
            values[0].set(total.get())
        difference = tk.StringVar(); ttk.Label(frame, textvariable=difference).pack(anchor='w', pady=8)
        remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text='같은 판매처·구성·금액의 다른 색상 세트에도 배분 기준 저장', variable=remember).pack(anchor='w')
        def update(*_):
            try:
                from .voucher import won
                diff = won(total.get()) - sum((won(v.get()) for v in values), Decimal(0))
                difference.set(f'상품 총금액과 차이 {diff:,.0f}원')
            except ValueError:
                difference.set('금액에는 0 이상의 정수를 입력하세요.')
        for variable in [total, *values]: variable.trace_add('write', update)
        update()
        def save():
            self.service.set_voucher_amounts(group['id'], total.get(), [v.get() for v in values], remember.get())
            if remember.get(): self.service.reuse_voucher_amounts(self.start.get(), self.end.get())
            win.destroy(); self.app.refresh()
        self.app.button(frame, '금액 확정', save, style='Accent.TButton')
        self.app.button(frame, '닫기', win.destroy)

    def fees(self):
        groups = self.service.voucher_rows(self.start.get(), self.end.get())
        win = tk.Toplevel(self.app.root); win.title('주문별 배송비 검수'); win.geometry('950x600'); win.transient(self.app.root); win.grab_set()
        ttk.Label(win, text='같은 판매처·계정·주문번호에는 배송비를 한 번 반영합니다. 금액이 다르면 행을 더블클릭해 확정하세요.', padding=12).pack(anchor='w')
        tree = self.app.tree(win, ['판매처', '계정', '주문번호', '원본 배송비', '전표 배송비', '상태'], [130, 100, 180, 180, 120, 180])
        rows = {}
        for group in groups:
            d = group['data']; key = self.service.erp_fee_key(d)
            rows.setdefault(key, []).append(d)
        for key, data in rows.items():
            amounts = {self.service.voucher_fee(d) for d in data} - {Decimal(0)}
            done = self.service.db.execute('SELECT 1 FROM fees WHERE bundle IN (?,?)', (key, self.service.bundle_key(data[0]))).fetchone()
            tree.insert('', 'end', iid=key, values=[data[0].get('channel', ''), data[0].get('account', ''), data[0]['order_no'],
                ' / '.join(sorted({str(d.get('shipping') or '0') for d in data})),
                '확인 필요' if len(amounts) > 1 else str(next(iter(amounts), Decimal(0))), '이미 반영' if done else '확인 필요' if len(amounts) > 1 else '한 번 반영'])
        def edit(_):
            from tkinter.simpledialog import askstring
            key = self.app.selected(tree)[0]; data = rows[key][0]
            value = askstring('배송비 확정', f"주문 {data['order_no']}의 배송비", parent=win)
            if value is not None:
                self.service.set_voucher_fee(data, value); win.destroy(); self.fees()
        tree.bind('<Double-1>', lambda event: self.app.safe(lambda: edit(event)))

    def families(self):
        win=tk.Toplevel(self.app.root);win.title('전표 색상 공유 그룹');win.geometry('1000x650');win.transient(self.app.root);win.grab_set()
        ttk.Label(win,text='모델·용량·길이가 같고 색상만 다른 품목에 같은 그룹명을 사용하세요. 더블클릭해 수정하며, 빈 값은 공유하지 않습니다.',padding=12).pack(anchor='w')
        tree=self.app.tree(win,['품목코드','품목명','금액 공유 그룹'],[230,330,300])
        for code,name in sorted(self.service.active_shipping_items.items()):
            family=self.service.voucher_family(code)
            tree.insert('', 'end',iid=code,values=[code,name,family.removeprefix('model:') if family.startswith('model:') else '공유 안 함'])
        def edit(_):
            from tkinter.simpledialog import askstring
            code=self.app.selected(tree)[0];family=self.service.voucher_family(code)
            value=askstring('색상 공유 그룹',self.service.item_name(code)+'의 모델 그룹명 (빈 값: 공유 안 함)',
                initialvalue=family.removeprefix('model:') if family.startswith('model:') else '',parent=win)
            if value is not None:
                self.service.set_voucher_family(code,value)
                tree.set(code,'금액 공유 그룹',value.strip() or '공유 안 함')
        tree.bind('<Double-1>',lambda event:self.app.safe(lambda:edit(event)))

    def preview(self):
        rows = self.service.export_erp(self.voucher_day.get(), self.end.get(), None, from_day=self.start.get(), preview=True)
        win = tk.Toplevel(self.app.root); win.title('전표 미리보기'); win.geometry('1100x650'); win.transient(self.app.root); win.grab_set()
        total = sum(r[15] * r[16] for r in rows)
        ttk.Label(win, text=f'전표일 {self.voucher_day.get()} · {len(rows)}행 · 배송비 포함 총금액 {total:,}원', padding=12).pack(anchor='w')
        tree = self.app.tree(win, ['거래처코드', '품목코드', '품목명', '창고', '수량', '단가', '총금액'], [120, 170, 280, 70, 70, 110, 130])
        for row in rows:
            tree.insert('', 'end', values=[row[2], row[12], row[13], row[5], row[15], row[16], row[15] * row[16]])

    def export(self):
        # Validate before prompting for a destination.
        self.service.export_erp(self.voucher_day.get(), self.end.get(), None, from_day=self.start.get(), preview=True)
        path = self.app.save_path('ERP_' + self.voucher_day.get() + '.xlsx')
        if path:
            self.service.export_erp(self.voucher_day.get(), self.end.get(), path, from_day=self.start.get())
            self.app.refresh()
            messagebox.showinfo('ERP 파일 생성', '파일을 저장했습니다. 출력 이력에서 다시 내려받을 수 있습니다.')
