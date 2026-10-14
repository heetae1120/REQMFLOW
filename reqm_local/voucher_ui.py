import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, timedelta
from decimal import Decimal
from .ui_helpers import format_money


class VoucherPanel:
    def __init__(self, app, parent):
        self.app, self.service = app, app.service
        self.start = tk.StringVar(value=(date.today()-timedelta(days=6)).isoformat())
        self.end = tk.StringVar(value=date.today().isoformat())
        self.voucher_day = tk.StringVar(value=self.end.get())
        self.search = tk.StringVar()
        self.status = tk.StringVar()
        self.show_exported=tk.BooleanVar(value=True)
        self.output_scope=tk.StringVar(value='전체 판매처')
        line = ttk.Frame(parent); line.pack(fill='x')
        for label, variable in (('출고 시작일', self.start), ('종료일', self.end), ('전표일', self.voucher_day)):
            ttk.Label(line, text=label).pack(side='left', padx=4)
            app.date_picker(line, variable, label).pack(side='left')
        app.button(line, '조회', self.refresh)
        app.button(line, '기존 세트 금액 적용', self.reuse)
        app.button(line, '색상 공유 그룹', self.families)
        ttk.Checkbutton(line,text='기존 생성 이력 포함',variable=self.show_exported,command=lambda:app.safe(self.refresh)).pack(side='left',padx=4)
        output=ttk.Frame(parent);output.pack(fill='x',pady=(8,0))
        ttk.Label(output,text='출력 대상').pack(side='left',padx=4)
        scope=ttk.Combobox(output,textvariable=self.output_scope,state='readonly',width=22,
                           values=['전체 판매처','옥션·지마켓 제외','옥션·지마켓만'])
        scope.pack(side='left',padx=4)
        scope.bind('<<ComboboxSelected>>',lambda _event:app.safe(self.scope_changed))
        ttk.Button(output,textvariable=app.erp_exclusion_text,command=lambda:app.safe(lambda:app.choose_channel_exclusions('erp'))).pack(side='left',padx=4)
        ttk.Label(output,text='배송비는 주문당 한 번 반영합니다.',foreground='#64748B').pack(side='left',padx=8)
        actions = ttk.Frame(parent); actions.pack(fill='x', pady=8)
        ttk.Label(actions, text='주문번호·수령인·판매처·품목 검색').pack(side='left')
        entry = ttk.Entry(actions, textvariable=self.search, width=28); entry.pack(side='left', padx=5)
        entry.bind('<Return>', lambda _: app.safe(self.refresh))
        app.button(actions, '선택 주문 금액 입력', self.edit, style='Accent.TButton')
        app.button(actions, '배송비 검수', self.fees)
        app.button(actions, '전표 미리보기', self.preview)
        app.button(actions, 'ERP 파일 생성', self.export, style='Accent.TButton')
        ttk.Label(parent, text='출고요청 파일 생성 시 요청수량 전체가 출고로 반영됩니다. 구성품 금액은 출고수량의 총금액입니다. 주문 상세는 행을 더블클릭하세요.').pack(anchor='w')
        self.tree = app.tree(parent, ['출고일', '판매처', '품목코드', '품목명', '수량', '상품금액', '상태'], [100, 130, 190, 300, 65, 110, 160])
        self.tree.bind('<Double-1>', lambda _: app.safe(self.edit))
        self.tree.tag_configure('warning', foreground='#B45309')
        ttk.Label(parent, textvariable=self.status).pack(anchor='w', pady=6)
        self.rows = {}

    def export_options(self):
        return dict(include_esm=self.output_scope.get()!='옥션·지마켓 제외' and self.app.erp_include_esm.get(),
                    only_esm=self.output_scope.get()=='옥션·지마켓만',
                    excluded_channels=self.app.erp_excluded_channels)

    def scope_changed(self):
        self.app.erp_include_esm.set(self.output_scope.get()!='옥션·지마켓 제외')
        self.refresh()

    def groups(self):
        from .service import is_excluded_channel
        options=self.export_options()
        return [group for group in self.service.voucher_rows(self.start.get(),self.end.get(),self.show_exported.get())
                if not is_excluded_channel(group['channel'],options['excluded_channels'])
                and (not options['only_esm'] or group['kind']=='esm')
                and (options['include_esm'] or group['kind']!='esm')]

    def refresh(self):
        self.tree.delete(*self.tree.get_children()); self.rows = {}
        groups = self.groups()
        terms = self.search.get().casefold().split()
        history = self.service.voucher_review_history(self.service.voucher_rows('0001-01-01', self.end.get(), True))
        review_count = 0
        for group in groups:
            text = str([group['channel'], group['data'].get('order_no'), group['data'].get('recipient'), group['components']]).casefold()
            if any(term not in text for term in terms):
                continue
            suggestion = self.service.voucher_suggestion(group) if not group['confirmed'] else None
            state = '이미 ERP 생성' if group['exported'] else group['issue'] or ('금액 확정' if group['confirmed'] else '기존 기준 적용 가능' if suggestion else '금액 확인 필요')
            warnings = self.service.voucher_review_pending(group, history) if group['components'] and not group['exported'] and not group['issue'] else []
            if warnings:
                state = ' / '.join(warnings)
                review_count += 1
            for component in group['components'] or [{}]:
                key = str(len(self.rows)); self.rows[key] = group
                code = component.get('code', '')
                self.tree.insert('', 'end', iid=key, values=[group['day'], group['channel'], code,
                    self.service.item_name(code, component.get('name', '')) if code else group['data'].get('product',''),
                    component.get('quantity',group['data'].get('quantity','')), format_money(component.get('amount',group['data'].get('amount',''))), state], tags=('warning',) if warnings else ())
        total = sum((g['total'] for g in groups), Decimal(0))
        pending = sum((not g['confirmed'] or bool(g['issue'])) and not g['exported'] for g in groups)
        exported=sum(g['exported'] for g in groups)
        self.status.set(f'조회 주문 {len(groups)}건 · 이미 생성 {exported}건 · 금액/매칭 확인 필요 {pending}건 · 금액 차이 확인 {review_count}건 · 표의 금액 {total:,.0f}원')
        self.app.workflow_statuses[2].set(f'대상 {len(groups):,}건 · 금액/매칭 확인 {pending:,}건 · 금액 차이 확인 {review_count:,}건 · 생성 완료 {exported:,}건')

    def reuse(self):
        count = self.service.reuse_voucher_amounts(self.start.get(), self.end.get())
        self.app.refresh()
        messagebox.showinfo('세트 금액 적용', f'같은 구성·판매금액의 세트 {count}건에 배분액을 적용했습니다.')

    def edit(self):
        group = self.rows[self.app.selected(self.tree)[0]]
        if group['exported']:
            raise ValueError('이미 ERP 파일로 생성한 주문입니다. 출력 이력에서 재다운로드하세요.')
        if group['kind']=='smartstore' and (group['issue'] or not group['components']):
            self.app.erp_amount_from.set(group['day']);self.app.erp_amount_through.set(group['day'])
            self.app.refresh_erp_shipments()
            key=next((k for k,r in self.app.amount_split_rows.items() if r['order_id']=='SSERP:'+group['order_id']),None)
            if key is None:raise ValueError('미매칭 주문을 다시 조회하세요.')
            self.app.erp_shipments.selection_set(key)
            self.app.edit_erp_set()
            return
        # Re-read after sync or an edit in another screen.
        group = next((g for g in self.service.voucher_rows(self.start.get(), self.end.get()) if g['id'] == group['id']), None)
        if not group or group['issue'] or not group['components']:
            raise ValueError('상품 매칭을 먼저 완료하거나 목록을 다시 조회하세요.')
        win = tk.Toplevel(self.app.root); win.title('전표 상품금액 입력'); win.transient(self.app.root); win.grab_set()
        frame = ttk.Frame(win, padding=18); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f"{group['channel']} · 주문 {group['data'].get('order_no', '')} · {group['data'].get('recipient', '')}").pack(anchor='w')
        total = tk.StringVar(master=win,value=format_money(group['total'] if group['confirmed'] or not group['full'] else group['data'].get('amount') or '0', grouped=False))
        ttk.Label(frame, text='이번 출고 상품 총금액 (배송비 제외)').pack(anchor='w', pady=(12, 2))
        ttk.Entry(frame, textvariable=total).pack(anchor='w')
        suggestion = self.service.voucher_suggestion(group)
        values = []
        for index, component in enumerate(group['components']):
            name = self.service.item_name(component['code'], component.get('name', ''))
            ttk.Label(frame, text=f"{name} · {component['code']} · 수량 {component['quantity']} · 색상공유 그룹 {self.service.voucher_family(component['code'])}").pack(anchor='w', pady=(8, 2))
            variable = tk.StringVar(master=win,value=format_money(suggestion[index] if suggestion else component['amount'], grouped=False))
            values.append(variable); ttk.Entry(frame, textvariable=variable).pack(anchor='w')
        if len(values) == 1:
            total.trace_add('write', lambda *_: values[0].set(total.get()))
            values[0].set(total.get())
        difference = tk.StringVar(master=win)
        difference_label = ttk.Label(frame, textvariable=difference, font=('', 11, 'bold'))
        difference_label.pack(anchor='w', pady=8)
        review_text = tk.StringVar(master=win)
        ttk.Label(frame, textvariable=review_text, foreground='#B45309', wraplength=700).pack(anchor='w')
        review_reason = tk.StringVar(master=win)
        ttk.Label(frame, text='차이 확인 사유 (할인·행사·금액 수정 등)').pack(anchor='w', pady=(8,2))
        ttk.Entry(frame, textvariable=review_reason, width=60).pack(anchor='w')
        remember = tk.BooleanVar(master=win,value=True)
        ttk.Checkbutton(frame, text='같은 판매처·구성·금액의 다른 색상 세트에도 배분 기준 저장', variable=remember).pack(anchor='w')
        history = self.service.voucher_review_history(self.service.voucher_rows('0001-01-01',group['day'],True))
        def update(*_):
            try:
                from .voucher import allocation_feedback, won
                text, color, balanced = allocation_feedback(total.get(), [v.get() for v in values])
                difference.set(f'목표 총금액 {won(total.get()):,.0f}원 · '+text)
                difference_label.configure(foreground=color)
                valid = all(v.get().strip() for v in values)
                warnings = self.service.voucher_review(group,total.get(),[v.get() for v in values],history) if balanced and valid else []
                review_text.set('\n'.join(warnings))
                save_button.state(['!disabled'] if balanced and valid and (not warnings or review_reason.get().strip()) else ['disabled'])
            except ValueError:
                difference.set('금액에는 0 이상의 정수를 입력하세요.')
                difference_label.configure(foreground='#BE123C')
                review_text.set('')
                save_button.state(['disabled'])
        def save():
            self.service.set_voucher_amounts(group['id'], total.get(), [v.get() for v in values], remember.get(), review_reason.get())
            if remember.get(): self.service.reuse_voucher_amounts(self.start.get(), self.end.get())
            win.destroy(); self.app.refresh()
        save_button = ttk.Button(frame, text='금액 확정', command=lambda:self.app.safe(save), style='Accent.TButton')
        save_button.pack(anchor='w', pady=4)
        for variable in [total, *values, review_reason]: variable.trace_add('write', update)
        update()
        self.app.button(frame, '닫기', win.destroy)

    def fees(self):
        groups = self.groups()
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
                ' / '.join(sorted({format_money(d.get('shipping') or '0') for d in data})),
                '확인 필요' if len(amounts) > 1 else format_money(next(iter(amounts), Decimal(0))), '이미 반영' if done else '확인 필요' if len(amounts) > 1 else '한 번 반영'])
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
        rows = self.service.export_erp(self.voucher_day.get(), self.end.get(), None, from_day=self.start.get(), preview=True, **self.export_options())
        win = tk.Toplevel(self.app.root); win.title('전표 미리보기'); win.geometry('1100x650'); win.transient(self.app.root); win.grab_set()
        total = sum(r[15] * r[16] for r in rows)
        ttk.Label(win, text=f'전표일 {self.voucher_day.get()} · {len(rows)}행 · 배송비 포함 총금액 {total:,}원', padding=12).pack(anchor='w')
        tree = self.app.tree(win, ['거래처코드', '품목코드', '품목명', '창고', '수량', '단가', '총금액'], [120, 170, 280, 70, 70, 110, 130])
        for row in rows:
            tree.insert('', 'end', values=[row[2], row[12], row[13], row[5], row[15], format_money(row[16]), format_money(row[15] * row[16])])

    def export(self):
        # Validate before prompting for a destination.
        self.service.export_erp(self.voucher_day.get(), self.end.get(), None, from_day=self.start.get(), preview=True, **self.export_options())
        path = self.app.save_path('ERP_' + self.voucher_day.get() + '.xlsx')
        if path:
            self.service.export_erp(self.voucher_day.get(), self.end.get(), path, from_day=self.start.get(), **self.export_options())
            self.app.refresh()
            messagebox.showinfo('ERP 파일 생성', '파일을 저장했습니다. 출력 이력에서 다시 내려받을 수 있습니다.')
