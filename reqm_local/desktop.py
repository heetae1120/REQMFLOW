from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
import ctypes
import tkinter.font as tkfont
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog

from .files import (
    ORDER_COLUMNS, RESULT_COLUMNS, analyze_order_columns, choice_column_index,
    column_choice, identifier, profile_column_choices, read_rows, related_column_choices,
    reference_data_path, sample_header_names, settings_at, workbook_bytes, wekeep_workbook_bytes,
)
from .service import Operations
from .cloud import login_and_load, load_catalog
from .ui_helpers import (
    autosize_tree, bind_desktop_drag, bind_wide_combobox, filter_combobox_choices,
    post_combobox, search_suggestions,
)
from .workspace_cloud import CloudWorkspace, WorkspaceConflict
from .profiles import PROFILE_PRESETS, SALES_CHANNELS, MATCHING_CHANNELS, SMARTSTORE_ERP_MAPPING
from .column_matching import match_columns
from .shipping import compact, channel_key
from .esm import download_esm_orders, load_credentials, save_credentials


APP_VERSION = '1.8.0'


CHANNEL_TO_INTERNAL = {
    '스마트스토어': '리큐엠_스마트스토어',
    SMARTSTORE_ERP_MAPPING: '리큐엠_스마트스토어_ERP',
}
INTERNAL_TO_CHANNEL = {value: key for key, value in CHANNEL_TO_INTERNAL.items()}

FIELD_LABELS = {
    'order_no': '판매처주문번호', 'line_no': '상품주문번호',
    'source_item_code': '판매처 상품코드',
    'product': '상품명', 'option': '옵션',
    'quantity': '수량', 'amount': '금액',
    'recipient': '수령인', 'phone': '전화번호',
    'postcode': '우편번호', 'address': '주소',
    'address1': '주소 1', 'address2': '주소 2',
    'memo': '배송메모', 'paid_at': '주문일자',
    'status': '주문 상태', 'bundle': '배송비 묶음번호',
    'shipping': '배송비',
}
MAPPING_FIELD_ORDER = (
    'paid_at', 'order_no', 'line_no', 'product', 'option', 'quantity', 'amount', 'shipping',
    'recipient', 'phone', 'postcode', 'address1', 'address2', 'memo',
)
SUGGESTED_MAPPING_FIELDS = ('order_no', 'line_no', 'product', 'quantity', 'amount')
FONT_FAMILY = 'Pretendard'
EMPTY_COLUMN_CHOICES = ['미사용']


def asset_path(*parts: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return base.joinpath('assets', *parts)


def register_brand_font():
    if os.name != 'nt':
        return
    font = asset_path('fonts', 'PretendardVariable.ttf')
    if font.exists():
        ctypes.windll.gdi32.AddFontResourceExW(str(font),0x10,0)


class Desktop:
    def __init__(self, root, service):
        self.root, self.service = root, service
        self.cloud_client = None
        self.cloud_workspace = None
        self.cloud_polling = False
        self.tray_icon = None
        self._quitting = False
        self._source_stamp = self.source_stamp()
        self.available_update = None
        self.update_checking = False
        self.update_error = None
        self._update_after_id = None
        register_brand_font()
        self.font_family = FONT_FAMILY if FONT_FAMILY in tkfont.families(root) else '맑은 고딕'
        self.app_icon = None
        icon_file = asset_path('branding', 'rq_mark_64.png')
        if icon_file.exists():
            try:
                self.app_icon = tk.PhotoImage(file=str(icon_file))
                root.iconphoto(True, self.app_icon)
            except tk.TclError:
                self.app_icon = None
        root.title('REQM FLOW · 주문에서 출고와 ERP까지')
        root.geometry('1460x900')
        root.minsize(1120,720)
        root.configure(bg='#F6F8FC')
        style = ttk.Style()
        style.theme_use('clam')
        f = self.font_family
        style.configure('.', background='#F6F8FC', foreground='#172033', font=(f,10))
        style.configure('TFrame', background='#F6F8FC')
        style.configure('TLabel', background='#F6F8FC', foreground='#172033', font=(f,10))
        style.configure('TButton', padding=(12,7), font=(f,10,'bold'), background='#FFFFFF', foreground='#334155', bordercolor='#D8E0EC', relief='flat')
        style.map('TButton', background=[('active','#EFF6FF'),('pressed','#DBEAFE')], foreground=[('active','#1D4ED8')])
        style.configure('Accent.TButton', background='#2563EB', foreground='white', bordercolor='#2563EB', relief='flat')
        style.map('Accent.TButton', background=[('active','#3B82F6'),('pressed','#1D4ED8')], foreground=[('active','white')])
        style.configure('Quiet.TButton', background='#F8FAFC', foreground='#475569', bordercolor='#E2E8F0')
        style.configure('Danger.TButton', background='#FFF7F7', foreground='#B42318', bordercolor='#FECACA')
        style.map('Danger.TButton', background=[('active','#FEE2E2')])
        style.configure('Channel.TButton', padding=(9,7), background='#FFFFFF', foreground='#334155', bordercolor='#E2E8F0', relief='flat')
        style.configure('Complete.Channel.TButton', padding=(9,7), background='#ECFDF3', foreground='#067647', bordercolor='#A6F4C5', relief='flat')
        style.map('Complete.Channel.TButton', background=[('active','#D1FADF')])
        style.configure('Treeview', rowheight=34, font=(f,10), background='white', fieldbackground='white', foreground='#172033', bordercolor='#E2E8F0', relief='flat')
        style.configure('Treeview.Heading', font=(f,10,'bold'), background='#F1F5F9', foreground='#334155', bordercolor='#E2E8F0', relief='flat', padding=(8,8))
        style.map('Treeview', background=[('selected','#2563EB')], foreground=[('selected','white')])
        style.configure('Flow.TNotebook', background='#F4F7FB', borderwidth=0)
        style.layout('Flow.TNotebook.Tab',[])
        style.configure('Workspace.TNotebook', background='#F6F8FC', borderwidth=0, tabmargins=(0,0,0,12))
        style.configure('Workspace.TNotebook.Tab', padding=(18,10), font=(f,10,'bold'), background='#E9EEF6', foreground='#64748B')
        style.map('Workspace.TNotebook.Tab', background=[('selected','#FFFFFF')], foreground=[('selected','#1D4ED8')])
        style.configure('TLabelframe', background='#FFFFFF', bordercolor='#D9E3F0', relief='solid')
        style.configure('TLabelframe.Label', background='#FFFFFF', foreground='#172033', font=(f,11,'bold'))
        style.configure('TEntry', fieldbackground='white', bordercolor='#D5DFEC', padding=7)
        style.configure('TCombobox', fieldbackground='white', bordercolor='#D5DFEC', padding=5)

        shell = tk.Frame(root,bg='#F6F8FC')
        shell.pack(fill='both',expand=True)
        sidebar = tk.Frame(shell,bg='#FFFFFF',width=210,padx=16,pady=18,highlightbackground='#E2E8F0',highlightthickness=1)
        sidebar.pack(side='left',fill='y')
        sidebar.pack_propagate(False)
        logo = tk.Frame(sidebar,bg='#FFFFFF');logo.pack(fill='x',pady=(0,28))
        self.sidebar_logo = None
        sidebar_logo_file = asset_path('branding', 'rq_mark_40.png')
        if sidebar_logo_file.exists():
            try:self.sidebar_logo = tk.PhotoImage(file=str(sidebar_logo_file))
            except tk.TclError:pass
        if self.sidebar_logo:
            tk.Label(logo,image=self.sidebar_logo,bg='#FFFFFF',borderwidth=0).pack(side='left')
        else:
            tk.Label(logo,text='RQ',fg='white',bg='#111111',font=(f,14,'bold'),width=3,pady=6).pack(side='left')
        tk.Label(logo,text='REQM',fg='#172033',bg='#FFFFFF',font=(f,16,'bold')).pack(side='left',padx=(9,4))
        tk.Label(logo,text='FLOW',fg='#2563EB',bg='#FFFFFF',font=(f,9,'bold')).pack(side='left',pady=(7,0))
        tk.Label(sidebar,text='WORKSPACE',fg='#94A3B8',bg='#FFFFFF',font=(f,8,'bold')).pack(anchor='w',padx=8,pady=(0,7))
        nav_holder = tk.Frame(sidebar,bg='#FFFFFF');nav_holder.pack(fill='x')
        tk.Label(sidebar,text='LOCAL  ·  PRIVATE',fg='#475569',bg='#F1F5F9',font=(f,8,'bold'),padx=10,pady=7).pack(side='bottom',anchor='w')

        content = tk.Frame(shell,bg='#F6F8FC',padx=24,pady=18)
        content.pack(side='left',fill='both',expand=True)
        top = tk.Frame(content,bg='#F6F8FC');top.pack(fill='x',pady=(0,12))
        title_box = tk.Frame(top,bg='#F6F8FC');title_box.pack(side='left')
        tk.Label(title_box,text='주문 출고 워크스페이스',fg='#172033',bg='#F6F8FC',font=(f,21,'bold')).pack(anchor='w')
        tk.Label(title_box,text='주문 확인부터 실제 출고와 ERP 반영까지',fg='#64748B',bg='#F6F8FC',font=(f,9)).pack(anchor='w',pady=(2,0))
        badge_box = tk.Frame(top,bg='#F6F8FC');badge_box.pack(side='right',anchor='n')
        self.cloud_status = tk.StringVar(value='API 로그인')
        tk.Button(
            badge_box,textvariable=self.cloud_status,command=self.open_cloud_login,
            fg='#166534',bg='#DCFCE7',activebackground='#BBF7D0',relief='flat',borderwidth=0,
            font=(f,9,'bold'),padx=11,pady=6,cursor='hand2',
        ).pack(side='left')
        self.update_text = tk.StringVar(value=f'업데이트 · {APP_VERSION}')
        tk.Button(
            badge_box,textvariable=self.update_text,command=self.apply_update,
            fg='#1D4ED8',bg='#E6EFFF',activebackground='#DBEAFE',relief='flat',borderwidth=0,
            font=(f,9,'bold'),padx=11,pady=6,cursor='hand2',
        ).pack(side='left',padx=(5,0))
        self.summary = tk.StringVar()
        tk.Label(content,textvariable=self.summary,bg='#FFFFFF',fg='#475569',font=(f,10,'bold'),padx=16,pady=10,anchor='w',highlightbackground='#E2E8F0',highlightthickness=1).pack(fill='x',pady=(0,12))
        tabs = ttk.Notebook(content,style='Flow.TNotebook')
        tabs.pack(fill='both',expand=True)
        self.today = tk.StringVar(value=date.today().isoformat())
        matching_frame = ttk.Frame(tabs,padding=18)
        self.order_frame = ttk.Frame(tabs,padding=12)
        result_frame = ttk.Frame(tabs,padding=16)
        history_frame = ttk.Frame(tabs,padding=12)
        settings_frame = ttk.Frame(tabs,padding=16)
        for frame,title in [(matching_frame,'★  매칭 설정'),(self.order_frame,'1  주문 · 출고요청'),(result_frame,'2  실제 출고 · ERP'),(history_frame,'3  출력 이력'),(settings_frame,'4  설정 · 백업')]:
            tabs.add(frame,text=title)
        nav_items = [('✦  매칭 설정',0),('▣  주문 · 출고요청',1),('↗  실제 출고 · ERP',2),('◫  출력 이력',3),('⚙  설정 · 백업',4)]
        self.nav_buttons = []
        def select_page(index):
            tabs.select(index)
            for item,button in enumerate(self.nav_buttons):
                active = item == index
                button.configure(bg='#EFF6FF' if active else '#FFFFFF',fg='#1D4ED8' if active else '#475569')
        for label,index in nav_items:
            button = tk.Button(nav_holder,text=label,command=lambda i=index:select_page(i),anchor='w',relief='flat',borderwidth=0,
                bg='#FFFFFF',fg='#475569',activebackground='#EFF6FF',activeforeground='#1D4ED8',font=(f,10,'bold'),padx=13,pady=11,cursor='hand2')
            button.pack(fill='x',pady=2)
            self.nav_buttons.append(button)
        select_page(0)
        self.build_matching_settings(matching_frame)
        channels = ttk.LabelFrame(self.order_frame,text='판매처 주문 파일',padding=(12,8))
        channels.pack(fill='x',pady=(0,10))
        self.channel_status = {}
        for index, channel in enumerate(SALES_CHANNELS):
            status = tk.StringVar(value=f'□  {channel}')
            self.channel_status[channel] = status
            button = ttk.Button(
                channels, textvariable=status,
                command=lambda selected=channel:self.safe(lambda:self.import_channel(selected)),
                style='Channel.TButton',
            )
            if not hasattr(self, 'channel_buttons'):
                self.channel_buttons = {}
            self.channel_buttons[channel] = button
            button.grid(row=index // 6,column=index % 6,sticky='ew',padx=4,pady=4)
        for column in range(6):
            channels.columnconfigure(column,weight=1)
        ttk.Label(
            channels,
            text='판매처를 누르거나 아래 영역에 파일을 드래그하세요. 입력 완료된 판매처는 ✓로 표시됩니다.',
            foreground='#64748B',
        ).grid(row=(len(SALES_CHANNELS)+5)//6,column=0,columnspan=6,sticky='w',padx=4,pady=(7,2))
        self.drop_zone = tk.Label(
            self.order_frame,
            text='↓  주문 파일을 여기에 드래그하세요   ·   XLSX / XLS / CSV',
            bg='#172033', fg='#C7FF4A', font=(self.font_family,11,'bold'),
            padx=18, pady=12, cursor='hand2',
        )
        self.drop_zone.pack(fill='x',pady=(0,10))
        self.drop_zone.bind('<Button-1>',lambda _event:self.safe(self.import_files))
        self.setup_file_drop(self.drop_zone)
        workflow = ttk.Frame(self.order_frame)
        workflow.pack(fill='x',pady=(0,10))
        organize = ttk.LabelFrame(workflow,text='주문 정리',padding=(10,8))
        organize.pack(side='left',fill='x',expand=True,padx=(0,6))
        self.button(organize,'＋ 주문 파일 입력',self.import_files,style='Accent.TButton')
        self.button(organize,'상품 매칭',self.mapping)
        self.button(organize,'미매칭 검토',self.batch_matching_review)
        self.button(organize,'배송정보 수정',self.delivery)
        self.button(organize,'강제 승인',self.force_shipping_approval,style='Quiet.TButton')
        self.button(organize,'삭제',self.delete_orders,style='Danger.TButton')
        release = ttk.LabelFrame(workflow,text='출고 파일 생성',padding=(10,8))
        release.pack(side='left',fill='x',padx=(6,0))
        ttk.Label(release,text='요청일').pack(side='left',padx=(0,4))
        ttk.Entry(release,textvariable=self.today,width=11).pack(side='left')
        self.button(release,'사전검사',self.preflight_review,style='Quiet.TButton')
        self.button(release,'선택 주문 파일 생성',self.request,style='Accent.TButton')
        self.search = tk.StringVar()
        self.filter = tk.StringVar(value='전체')
        filters = ttk.Frame(self.order_frame)
        filters.pack(fill='x',pady=(0,8))
        ttk.Label(filters,text='주문 검색',font=(self.font_family,10,'bold')).pack(side='left')
        ttk.Entry(filters,textvariable=self.search,width=38).pack(side='left',padx=8)
        ttk.Combobox(filters,textvariable=self.filter,values=['전체','중복 주문','검토 필요','출고 준비','출고 요청','부분 출고','출고 완료'],state='readonly',width=14).pack(side='left')
        self.button(filters,'출고 준비 전체 선택',self.select_ready,style='Quiet.TButton')
        self.search.trace_add('write',self.on_search_changed)
        self.filter.trace_add('write',lambda *_:self.refresh_orders())
        self.search_suggestion_bar = ttk.Frame(self.order_frame)
        self.search_suggestion_bar.pack(fill='x',padx=(44,0),pady=(0,4))
        self.detail = tk.StringVar(value='주문을 선택하면 구성품을 확인할 수 있습니다. Ctrl/Shift로 여러 주문을 선택하세요.')
        ttk.Label(self.order_frame,textvariable=self.detail,wraplength=1200,padding=(8,6),foreground='#64748B').pack(fill='x')
        self.table = self.tree(
            self.order_frame,
            ['주문번호','이름','주소','연락처','상품명','매칭할 상품명'],
            [155,110,330,135,300,320],
        )
        self.table.tag_configure('review',foreground='#BE123C',background='#FFF1F2')
        self.table.tag_configure('duplicate',foreground='#854D0E',background='#FEF9C3')
        self.table.tag_configure('forced',foreground='#166534',background='#F0FDF4')
        self.table.bind('<<TreeviewSelect>>',self.show_detail)
        self.table.bind('<Double-1>',self.open_mapping_from_click)
        result_tabs = ttk.Notebook(result_frame,style='Workspace.TNotebook')
        result_tabs.pack(fill='both',expand=True)
        result_input = ttk.Frame(result_tabs,padding=20)
        amount_frame = ttk.Frame(result_tabs,padding=20)
        esm_frame = ttk.Frame(result_tabs,padding=20)
        erp_frame = ttk.Frame(result_tabs,padding=20)
        self.erp_ship_day = tk.StringVar(value=date.today().isoformat())
        result_tabs.add(result_input,text='1  출고건 확인')
        result_tabs.add(amount_frame,text='2  금액 매칭 및 세트 분리')
        result_tabs.add(esm_frame,text='2-1  옥션/지마켓 ERP전환')
        result_tabs.add(erp_frame,text='3  ERP 파일 생성 및 다운로드')
        ttk.Label(result_input,text='당일 출고건 확인',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(result_input,text='당일 생성한 출고요청은 자동으로 불러오거나, 위킵 반환 파일로 직접 반영할 수 있습니다.',foreground='#64748B').pack(anchor='w',pady=(4,18))
        result_card = ttk.LabelFrame(result_input,text='입력 파일',padding=18)
        result_card.pack(fill='x')
        ttk.Label(result_card,text='입력 구분',foreground='#64748B').grid(row=0,column=0,sticky='w')
        ttk.Label(result_card,text='일반 판매처: 당일 출고요청 자동 반영 또는 위킵 출고파일 · 스마트스토어: ERP 입력 원본',font=(self.font_family,10,'bold')).grid(row=1,column=0,sticky='w',pady=(2,14))
        ttk.Label(result_card,text='자동·파일 반영 모두 스마트스토어를 제외합니다. 위킵 반환 파일은 송장번호를 채운 출고요청 양식을 사용합니다.',foreground='#64748B').grid(row=2,column=0,sticky='w')
        result_actions = ttk.Frame(result_card);result_actions.grid(row=0,column=1,rowspan=3,sticky='e',padx=(40,0))
        self.button(result_actions,'위킵 출고양식 저장',self.result_template,style='Quiet.TButton')
        self.button(result_actions,'당일 출고건 자동 불러오기',self.auto_results,style='Accent.TButton')
        self.button(result_actions,'일반 실제출고 입력',self.results,style='Accent.TButton')
        self.button(result_actions,'스마트스토어 ERP 입력',self.smartstore_erp_results,style='Accent.TButton')
        result_card.columnconfigure(0,weight=1)
        confirmed_line=ttk.Frame(result_input);confirmed_line.pack(fill='x',pady=(12,8))
        ttk.Label(confirmed_line,text='출고일').pack(side='left')
        ttk.Entry(confirmed_line,textvariable=self.erp_ship_day,width=12).pack(side='left',padx=6)
        self.button(confirmed_line,'출고건 조회',self.refresh_confirmed_shipments,style='Quiet.TButton')
        self.confirmed_shipments = self.tree(result_input,['구분','출고일','판매처','주문번호','이름','품목','수량','송장번호'],[130,105,140,160,100,260,70,150])
        ttk.Label(amount_frame,text='금액 매칭 및 세트 분리',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(amount_frame,text='출고 확인된 품목의 ERP 금액을 확인하고, 스마트스토어 세트 구성은 필요할 때 수정합니다.',foreground='#64748B').pack(anchor='w',pady=(4,16))
        amount_line = ttk.Frame(amount_frame); amount_line.pack(fill='x',pady=(0,10))
        ttk.Label(amount_line,text='실제 출고일').pack(side='left')
        ttk.Entry(amount_line,textvariable=self.erp_ship_day,width=12).pack(side='left',padx=6)
        self.button(amount_line,'조회',self.refresh_erp_shipments)
        self.button(amount_line,'선택 금액 매칭',self.match_erp_amount,style='Accent.TButton')
        self.button(amount_line,'선택 세트 구성',self.edit_erp_set,style='Quiet.TButton')
        self.erp_shipments = self.tree(amount_frame,['구분','실제 출고일','주문번호','이름','ERP 품목코드','ERP 품목명','출고수량','ERP 반영금액'],[125,110,150,110,150,250,80,120])
        self.erp_shipments.bind('<Double-1>',lambda _event:self.safe(self.match_erp_amount))
        self.esm_start_day = tk.StringVar(value=date.today().isoformat())
        self.esm_end_day = tk.StringVar(value=date.today().isoformat())
        self.esm_user_id = tk.StringVar()
        self.esm_password = tk.StringVar()
        self.esm_progress = tk.StringVar(value='조회 기간과 로그인 정보를 확인한 뒤 자동 다운로드를 실행하세요.')
        saved_user,saved_password=load_credentials(self.service.folder/'esm_credentials.dat')
        self.esm_user_id.set(saved_user);self.esm_password.set(saved_password)
        ttk.Label(esm_frame,text='옥션/지마켓 ESM PLUS ERP전환',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(esm_frame,text='A/G 전체에서 주문일과 배송상태별 파일을 내려받아 옥션·지마켓 ERP 행으로 변환합니다.',foreground='#64748B').pack(anchor='w',pady=(4,14))
        esm_card=ttk.LabelFrame(esm_frame,text='ESM PLUS 자동 수집',padding=14);esm_card.pack(fill='x')
        form=ttk.Frame(esm_card);form.pack(fill='x')
        for label,var,width,secret in [
            ('시작 주문일',self.esm_start_day,12,False),('종료 주문일',self.esm_end_day,12,False),
            ('아이디',self.esm_user_id,22,False),('비밀번호',self.esm_password,22,True),
        ]:
            ttk.Label(form,text=label).pack(side='left',padx=(8,4))
            ttk.Entry(form,textvariable=var,width=width,show='●' if secret else '').pack(side='left')
        self.button(form,'로그인 정보 보호 저장',self.save_esm_login,style='Quiet.TButton')
        self.button(form,'ESM PLUS 자동 다운로드',self.download_esm,style='Accent.TButton')
        self.button(form,'파일 직접 추가',self.import_esm_files,style='Quiet.TButton')
        ttk.Label(esm_card,textvariable=self.esm_progress,foreground='#2563EB').pack(anchor='w',padx=8,pady=(10,0))
        esm_actions=ttk.Frame(esm_frame);esm_actions.pack(fill='x',pady=(12,8))
        ttk.Label(esm_actions,text='변환 내역',font=(self.font_family,11,'bold')).pack(side='left')
        self.button(esm_actions,'선택 상품 매칭',self.edit_esm_set,style='Accent.TButton')
        self.button(esm_actions,'목록 새로고침',self.refresh_esm_entries,style='Quiet.TButton')
        self.esm_entries=self.tree(esm_frame,['기준일','판매처','주문번호','상품명','옵션','수량','단가','합계','ERP 품목','상태'],[105,90,145,280,220,65,95,105,170,180])
        self.esm_entries.bind('<Double-1>',lambda _event:self.safe(self.edit_esm_set))
        ttk.Label(erp_frame,text='이카운트 ERP 파일 생성 및 다운로드',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(erp_frame,text='2번 실제출고·스마트스토어와 2-1 옥션/지마켓의 매칭 완료 건을 한 파일에 포함합니다.',foreground='#64748B').pack(anchor='w',pady=(4,18))
        self.through = tk.StringVar(value=date.today().isoformat())
        self.voucher = tk.StringVar(value=date.today().isoformat())
        erp_card = ttk.LabelFrame(erp_frame,text='출력 조건',padding=18);erp_card.pack(fill='x')
        line = ttk.Frame(erp_card); line.pack(anchor='w')
        for label,var in [('실제 출고일 ≤',self.through),('ERP 전표일',self.voucher)]:
            ttk.Label(line,text=label).pack(side='left',padx=6)
            ttk.Entry(line,textvariable=var,width=12).pack(side='left')
        self.button(line,'ERP 파일 생성',self.erp,style='Accent.TButton')
        ttk.Label(erp_card,text='이미 생성한 출고는 제외됩니다. 배송비는 묶음 전체 출고 완료 후 한 번 반영하며, 부가세 포함·10% 과세 기준입니다.',foreground='#64748B',wraplength=1000).pack(anchor='w',pady=(16,0))
        line = ttk.Frame(history_frame); line.pack(fill='x',pady=8)
        self.button(line,'선택 파일 재저장',self.reexport)
        self.button(line,'ERP 등록 확인',self.registered)
        ttk.Label(line,text='파일 생성과 ERP 사이트 등록 완료는 별개입니다.').pack(side='left',padx=20)
        self.history = self.tree(history_frame,['묶음 ID','종류','기준일','ERP 등록 확인'],[320,140,180,180])
        ttk.Label(settings_frame,text='로그인 전에는 이 PC에 저장되고, API 로그인 후에는 공유 DB와 동기화됩니다.',font=(self.font_family,16,'bold')).pack(anchor='w',pady=10)
        ttk.Label(settings_frame,text=str(service.folder),wraplength=1100).pack(anchor='w')
        ttk.Label(settings_frame,text='설정 파일에서 판매처별 헤더·계정·파일명 단서와 출력 열 이름을 변경할 수 있습니다.\n주문에 포함된 배송비는 원본의 배송비 합계를 사용합니다. 실제 거래처 규칙을 확인하세요.\nAPI 로그인 후 주문·매칭·출고·ERP 이력은 Supabase 공유 작업공간으로 동기화됩니다.\n동시에 같은 자료를 수정하면 버전 충돌로 저장을 중단하고 최신 자료를 다시 불러옵니다.',wraplength=1100).pack(anchor='w',pady=16)
        line = ttk.Frame(settings_frame); line.pack(anchor='w')
        self.button(line,'설정 파일 열기',lambda:os.startfile(service.folder/'settings.json'))
        self.button(line,'설정 다시 읽기',self.reload_settings)
        self.button(line,'DB 백업',self.backup)
        self.button(line,'저장 폴더 열기',lambda:os.startfile(service.folder))
        tk.Label(content,text='LOCAL CACHE + SUPABASE LIVE WORKSPACE   ·   날짜 YYYY-MM-DD   ·   REQM FLOW',bg='#F4F7FB',fg='#94A3B8',font=(self.font_family,8,'bold'),pady=6).pack(fill='x')
        self.refresh()
        self.root.protocol('WM_DELETE_WINDOW',self.hide_to_tray)
        self.root.bind('<Destroy>',self.on_root_destroy,add='+')
        self.setup_tray()
        self.root.after(4000,self.check_for_source_update)
        if getattr(sys,'frozen',False):
            self.root.after(1800,self.check_remote_update)

    def source_stamp(self):
        if getattr(sys,'frozen',False):
            return 0.0
        base = Path(__file__).resolve().parent.parent
        files = [base/'reqm_local_app.py',base/'ecount_sales_core.py',*base.joinpath('reqm_local').glob('*.py')]
        return max((path.stat().st_mtime for path in files if path.exists()),default=0.0)

    def check_for_source_update(self):
        if self._quitting:
            return
        stamp = self.source_stamp()
        if stamp and stamp > self._source_stamp + .01:
            self.update_text.set('업데이트 준비됨 · 재시작')
            if self.tray_icon and not getattr(self,'_update_notified',False):
                self._update_notified = True
                try:self.tray_icon.notify('수정된 프로그램이 준비됐습니다. 업데이트 버튼으로 재시작하세요.','REQM FLOW')
                except Exception:pass
        self.root.after(4000,self.check_for_source_update)

    def check_remote_update(self, user_initiated=False):
        if self._quitting or self.update_checking or not getattr(sys,'frozen',False):
            return
        if self._update_after_id:
            try:self.root.after_cancel(self._update_after_id)
            except tk.TclError:pass
            self._update_after_id = None
        self.update_checking = True
        self.update_error = None
        def worker():
            try:
                from .updater import latest_release
                release = latest_release(APP_VERSION)
                self.root.after(0,lambda:self.remote_update_result(release,None,user_initiated))
            except Exception as exc:
                detail = str(exc) or exc.__class__.__name__
                self.root.after(0,lambda:self.remote_update_result(None,detail,user_initiated))
        threading.Thread(target=worker,daemon=True).start()

    def remote_update_result(self, release, error=None, user_initiated=False):
        self.update_checking = False
        self.available_update = release
        self.update_error = error
        if not self._quitting:
            self._update_after_id = self.root.after(60 * 60 * 1000,self.check_remote_update)
        if error:
            self.update_text.set(f'업데이트 확인 재시도 · {APP_VERSION}')
            if user_initiated:
                messagebox.showerror('업데이트 확인 실패',f'업데이트 서버를 확인하지 못했습니다.\n\n{error}',parent=self.root)
            return
        if release:
            self.update_text.set(f"업데이트 {release['version']} 받기")
            if self.tray_icon and not getattr(self,'_remote_update_notified',False):
                self._remote_update_notified=True
                try:self.tray_icon.notify(f"REQM FLOW {release['version']} 업데이트가 있습니다.",'업데이트')
                except Exception:pass
            if not getattr(self,'_remote_update_prompted',False):
                self._remote_update_prompted=True
                self.root.after(250,self.apply_update)
        else:
            self.update_text.set(f'최신 버전 · {APP_VERSION}')

    def apply_update(self):
        if getattr(sys,'frozen',False):
            if not self.available_update:
                self.update_text.set('업데이트 확인 중…')
                self.check_remote_update(user_initiated=True)
                return
            version=self.available_update['version']
            if not messagebox.askyesno('업데이트',f'REQM FLOW {version}을 받아 현재 폴더에 적용할까요?\n저장된 주문과 설정은 그대로 유지됩니다.',parent=self.root):
                return
            self.update_text.set(f'{version} 다운로드 중…')
            threading.Thread(target=self._download_update_worker,daemon=True).start()
            return
        changed = bool(self.source_stamp() and self.source_stamp() > self._source_stamp + .01)
        message = '수정된 내용을 적용하려면 프로그램을 재시작합니다.' if changed else '현재 파일로 프로그램을 다시 시작할까요?'
        if not messagebox.askyesno('업데이트 적용',message,parent=self.root):
            return
        self._quitting = True
        if self.tray_icon:
            try:self.tray_icon.stop()
            except Exception:pass
        self.service.close()
        if getattr(sys,'frozen',False):
            argv = [sys.executable,*sys.argv[1:]]
        else:
            argv = [sys.executable,*sys.argv]
        os.execv(sys.executable,argv)

    def _download_update_worker(self):
        try:
            from .updater import install_directory,launch_replacer,prepare_update
            source=prepare_update(self.available_update)
            self.root.after(0,lambda:self._apply_downloaded_update(source,install_directory()))
        except Exception as exc:
            detail=str(exc)
            self.root.after(0,lambda:self._update_download_failed(detail))

    def _apply_downloaded_update(self, source, install_dir):
        from .updater import launch_replacer
        launch_replacer(source,install_dir,os.getpid())
        self._quitting=True
        if self.tray_icon:
            try:self.tray_icon.stop()
            except Exception:pass
        self.service.close()
        self.root.destroy()

    def _update_download_failed(self, detail):
        self.update_text.set(f'업데이트 재시도 · {APP_VERSION}')
        messagebox.showerror('업데이트 실패',detail,parent=self.root)

    def setup_tray(self):
        if os.environ.get('REQM_SELF_TEST') == '1':
            return
        try:
            import pystray
            from PIL import Image
        except ImportError:
            return
        icon_file = asset_path('branding', 'rq_mark_64.png')
        image = Image.open(icon_file).convert('RGBA') if icon_file.exists() else Image.new('RGBA',(64,64),'#111111')
        menu = pystray.Menu(
            pystray.MenuItem('REQM FLOW 열기',lambda *_:self.root.after(0,self.show_from_tray),default=True),
            pystray.MenuItem('완전히 종료',lambda *_:self.root.after(0,self.quit_app)),
        )
        self.tray_icon = pystray.Icon('REQM_FLOW',image,'REQM FLOW',menu)
        self.tray_icon.run_detached()

    def hide_to_tray(self):
        if not self.tray_icon:
            self.quit_app()
            return
        self.root.withdraw()
        try:self.tray_icon.notify('프로그램은 종료되지 않고 상태 표시줄에서 실행 중입니다.','REQM FLOW')
        except Exception:pass

    def show_from_tray(self):
        self.root.deiconify()
        self.root.state('normal')
        self.root.lift()
        self.root.focus_force()

    def quit_app(self):
        self._quitting = True
        if self.tray_icon:
            try:self.tray_icon.stop()
            except Exception:pass
            self.tray_icon = None
        self.root.destroy()

    def on_root_destroy(self,event):
        if event.widget is self.root and self.tray_icon:
            try:self.tray_icon.stop()
            except Exception:pass
            self.tray_icon = None

    def open_cloud_login(self):
        if self.cloud_client is not None:
            if messagebox.askyesno('API 새로고침','로그인 세션으로 최신 품목·매칭 정보를 다시 불러올까요?',parent=self.root):
                self.cloud_status.set('API 불러오는 중…')
                threading.Thread(target=self._refresh_cloud_worker,daemon=True).start()
            return
        win=tk.Toplevel(self.root);win.title('Supabase API 로그인');win.transient(self.root);win.grab_set();win.resizable(False,False)
        frame=ttk.Frame(win,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Supabase Auth 사용자',font=(self.font_family,14,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,12))
        ttk.Label(
            frame,
            text='Supabase 대시보드 팀원 계정이 아닙니다.\n이 프로젝트의 Authentication > Users에 등록된 계정을 입력하세요.',
            foreground='#64748B',
        ).grid(row=1,column=0,columnspan=2,sticky='w',pady=(0,12))
        email=tk.StringVar(value=self.service.settings.get('cloud_email',''));password=tk.StringVar()
        ttk.Label(frame,text='이메일').grid(row=2,column=0,sticky='w',padx=(0,10),pady=5)
        email_entry=ttk.Entry(frame,textvariable=email,width=38);email_entry.grid(row=2,column=1,sticky='ew',pady=5)
        ttk.Label(frame,text='비밀번호').grid(row=3,column=0,sticky='w',padx=(0,10),pady=5)
        password_entry=ttk.Entry(frame,textvariable=password,show='•',width=38);password_entry.grid(row=3,column=1,sticky='ew',pady=5)
        status=tk.StringVar(value='로그인하면 품목과 주문·출고·ERP 공유 작업공간을 연결합니다.')
        ttk.Label(frame,textvariable=status,foreground='#2563EB').grid(row=4,column=0,columnspan=2,sticky='w',pady=(8,4))
        actions=ttk.Frame(frame);actions.grid(row=5,column=0,columnspan=2,sticky='e',pady=(10,0))
        ttk.Button(actions,text='취소',command=win.destroy).pack(side='left',padx=4)
        login_button=ttk.Button(actions,text='로그인',style='Accent.TButton')
        login_button.pack(side='left',padx=4)
        def start(*_):
            user=email.get().strip();secret=password.get()
            if not user or not secret:
                status.set('이메일과 비밀번호를 입력하세요.');return
            login_button.configure(state='disabled');status.set('로그인 및 DB 불러오는 중…');self.cloud_status.set('API 연결 중…')
            threading.Thread(target=self._cloud_login_worker,args=(win,user,secret,status,login_button),daemon=True).start()
        login_button.configure(command=start);password_entry.bind('<Return>',start)
        (email_entry if not email.get() else password_entry).focus_set()

    def _cloud_login_worker(self,win,email,password,status,login_button):
        try:
            client,catalog,counts=login_and_load(email,password,self.service.reference_dir)
            self.root.after(0,lambda:self._cloud_login_success(win,email,client,catalog,counts))
        except Exception as exc:
            detail=str(exc)
            self.root.after(0,lambda:self._cloud_login_failed(status,login_button,detail))

    def _cloud_login_success(self,win,email,client,catalog,counts):
        self.cloud_client=client;self.service.catalog=catalog
        self.service.settings['cloud_email']=email
        path=self.service.folder/'settings.json';temporary=path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(self.service.settings,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,path)
        try:
            workspace=CloudWorkspace(client,self.service)
            direction=workspace.bootstrap()
            self.service.refresh_matches()
            workspace.push_if_changed()
        except Exception as exc:
            self.cloud_client=None;self.cloud_workspace=None;self.cloud_status.set('API 로그인')
            if win.winfo_exists():win.destroy()
            messagebox.showerror(
                '공유 DB 연결 실패',
                f'{exc}\n\nSupabase SQL Editor에서 002_reqm_shared_workspace.sql을 먼저 실행했는지 확인하세요.',
                parent=self.root,
            )
            return
        self.cloud_workspace=workspace
        self.cloud_status.set(f'공유 DB 연결됨 · v{workspace.version}')
        if win.winfo_exists():win.destroy()
        self.refresh()
        self.load_matching_profile()
        self.root.after(5000,self.poll_cloud_workspace)
        total=counts.get('ecount_item_reference',0)
        action='기존 공유 자료를 이 PC에 적용했습니다.' if direction=='downloaded' else '이 PC의 기존 자료를 첫 공유 자료로 올렸습니다.'
        messagebox.showinfo('공유 DB 연결 완료',f'{action}\n전표 품목 {total:,}개 · 출고 별칭 {counts.get("item_aliases",0):,}개 · 전표 변환 {counts.get("ecount_product_mappings",0):,}개\n기존 주문의 별칭·변환 규칙을 다시 적용했습니다.',parent=self.root)

    def _cloud_login_failed(self,status,login_button,detail):
        self.cloud_status.set('API 로그인')
        status.set(f'로그인 실패: {detail}')
        login_button.configure(state='normal')

    def _refresh_cloud_worker(self):
        try:
            catalog,counts=load_catalog(self.cloud_client,self.service.reference_dir)
            self.root.after(0,lambda:self._cloud_refresh_success(catalog,counts))
        except Exception as exc:
            detail=str(exc);self.root.after(0,lambda:self._cloud_refresh_failed(detail))

    def _cloud_refresh_success(self,catalog,counts):
        self.service.catalog=catalog
        try:
            changed=self.cloud_workspace.pull_if_newer() if self.cloud_workspace else False
            self.service.refresh_matches()
            self.refresh()
            if changed:
                self.refresh()
                self.load_matching_profile()
            if self.cloud_workspace:self.cloud_workspace.push_if_changed()
            version=self.cloud_workspace.version if self.cloud_workspace else 0
            self.cloud_status.set(f'공유 DB 연결됨 · v{version}')
            messagebox.showinfo('API 새로고침',f"최신 원격 품목 {counts.get('ecount_item_reference',0):,}개와 공유 DB를 반영했습니다.",parent=self.root)
        except Exception as exc:
            self._cloud_refresh_failed(str(exc))

    def _cloud_refresh_failed(self,detail):
        self.cloud_status.set('API 연결 오류')
        messagebox.showerror('API 새로고침 실패',detail,parent=self.root)

    def poll_cloud_workspace(self):
        if self._quitting or not self.cloud_workspace:
            return
        try:
            if self.root.grab_current() is None and self.cloud_workspace.pull_if_newer():
                self.refresh()
                self.load_matching_profile()
            self.cloud_status.set(f'공유 DB 연결됨 · v{self.cloud_workspace.version}')
        except WorkspaceConflict:
            self.cloud_status.set('공유 DB 충돌 · 새로고침')
        except Exception:
            self.cloud_status.set('공유 DB 연결 확인 중')
        self.root.after(5000,self.poll_cloud_workspace)

    def on_search_changed(self,*_):
        self.refresh_orders();self.update_search_suggestions()

    def update_search_suggestions(self):
        if not hasattr(self,'search_suggestion_bar'):
            return
        for child in self.search_suggestion_bar.winfo_children():child.destroy()
        query=self.search.get().strip()
        if not query:return
        candidates=['중복 주문','검토 필요','출고 준비','출고 요청','부분 출고','출고 완료']
        for order in getattr(self,'rows',{}).values():
            data=order.get('data',{})
            candidates.extend(data.get(key,'') for key in ('channel','order_no','line_no','product','option','recipient','event_name','status'))
        suggestions=search_suggestions(query,candidates,8)
        if not suggestions:return
        ttk.Label(self.search_suggestion_bar,text='연관검색',foreground='#64748B').pack(side='left',padx=(0,5))
        for value in suggestions:
            label=value if len(value)<=20 else value[:19]+'…'
            ttk.Button(self.search_suggestion_bar,text=label,command=lambda selected=value:self.search.set(selected)).pack(side='left',padx=2)

    def build_matching_settings(self, parent):
        heading = ttk.Frame(parent)
        heading.pack(fill='x',pady=(0,14))
        ttk.Label(heading,text='판매처 파일 매칭',font=(self.font_family,19,'bold')).pack(anchor='w')
        ttk.Label(
            heading,
            text='판매처별 파일명 특징과 엑셀 열을 저장합니다. 날짜와 일련번호가 달라져도 파일명의 핵심 단어로 자동 판별합니다.',
            foreground='#64748B',
        ).pack(anchor='w',pady=(5,0))

        body = ttk.Frame(parent)
        body.pack(fill='both',expand=True)
        left = tk.Frame(body,bg='#172033',width=245,padx=13,pady=13)
        left.pack(side='left',fill='y',padx=(0,14))
        left.pack_propagate(False)
        tk.Label(left,text='SALES CHANNEL',bg='#172033',fg='#BFDBFE',font=(self.font_family,10,'bold')).pack(anchor='w',pady=(0,9))
        self.matching_sites = tk.Listbox(
            left, activestyle='none', exportselection=False, relief='flat', borderwidth=0,
            bg='#172033', fg='#E2E8F0', selectbackground='#C7FF4A', selectforeground='#172033',
            font=(self.font_family,10,'bold'), highlightthickness=0,
        )
        for channel in MATCHING_CHANNELS:
            self.matching_sites.insert('end',channel)
        self.matching_sites.pack(fill='both',expand=True)
        self.matching_sites.bind('<<ListboxSelect>>',self.load_matching_profile)

        right = ttk.Frame(body,padding=(8,0,0,0))
        right.pack(side='left',fill='both',expand=True)
        identity = ttk.LabelFrame(right,text='01  파일 인식 기준',padding=13)
        identity.pack(fill='x')
        self.matching_channel = tk.StringVar(value=MATCHING_CHANNELS[0])
        self.matching_filename = tk.StringVar()
        self.matching_sample = tk.StringVar(value='예시 파일을 선택하지 않았습니다.')
        self.matching_analysis = tk.StringVar(value='파일을 추가하면 열을 분석해 1차 매칭을 채웁니다.')
        self.matching_header_row = tk.StringVar(value='1')
        self.matching_password = tk.StringVar()
        ttk.Label(identity,text='선택 판매처',foreground='#6B6762').grid(row=0,column=0,sticky='w',padx=(0,12),pady=5)
        ttk.Label(identity,textvariable=self.matching_channel,font=(self.font_family,11,'bold'),foreground='#2563EB').grid(row=0,column=1,sticky='w',pady=5)
        ttk.Label(identity,text='파일명 예시').grid(row=1,column=0,sticky='w',padx=(0,12),pady=5)
        ttk.Entry(identity,textvariable=self.matching_filename).grid(row=1,column=1,columnspan=3,sticky='ew',pady=5)
        ttk.Label(identity,text='여러 예시는 ; 로 구분 · 날짜/숫자/확장자는 자동 제외',foreground='#64748B').grid(row=2,column=1,columnspan=3,sticky='w')
        ttk.Label(identity,text='헤더 행').grid(row=3,column=0,sticky='w',padx=(0,12),pady=(10,5))
        header_controls = ttk.Frame(identity)
        header_controls.grid(row=3,column=1,sticky='w',pady=(10,5))
        ttk.Entry(header_controls,textvariable=self.matching_header_row,width=7).pack(side='left')
        ttk.Button(header_controls,text='행 적용',command=lambda:self.safe(self.apply_sample_headers)).pack(side='left',padx=6)
        ttk.Button(identity,text='파일 추가 · 1차 자동 매칭',style='Accent.TButton',command=lambda:self.safe(self.load_matching_sample)).grid(row=3,column=2,sticky='w',padx=8,pady=(10,5))
        ttk.Label(identity,textvariable=self.matching_sample,foreground='#64748B').grid(row=3,column=3,sticky='w',pady=(10,5))
        ttk.Label(identity,textvariable=self.matching_analysis,foreground='#2563EB').grid(row=4,column=1,columnspan=3,sticky='w',pady=(2,5))
        ttk.Label(identity,text='엑셀 비밀번호').grid(row=5,column=0,sticky='w',padx=(0,12),pady=5)
        ttk.Entry(identity,textvariable=self.matching_password,show='•').grid(row=5,column=1,sticky='ew',pady=5)
        ttk.Label(identity,text='API 로그인 시 모든 PC의 공유 설정으로 저장됩니다.',foreground='#64748B').grid(row=5,column=2,columnspan=2,sticky='w',padx=8)
        identity.columnconfigure(1,weight=1); identity.columnconfigure(3,weight=2)

        mapping = ttk.LabelFrame(right,text='02  주문 파일 열 연결',padding=13)
        mapping.pack(fill='both',expand=True,pady=(14,0))
        ttk.Label(mapping,text='프로그램 항목',font=(self.font_family,9,'bold'),foreground='#64748B').grid(row=0,column=0,sticky='w',padx=(0,8))
        ttk.Label(mapping,text='엑셀 열 이름',font=(self.font_family,9,'bold'),foreground='#64748B').grid(row=0,column=1,sticky='w')
        ttk.Label(mapping,text='판정',font=(self.font_family,9,'bold'),foreground='#64748B').grid(row=0,column=2,sticky='w',padx=(6,0))
        self.mapping_vars = {}
        self.mapping_boxes = {}
        self.mapping_status_vars = {}
        for index, field in enumerate(MAPPING_FIELD_ORDER):
            row = index+1
            ttk.Label(mapping,text=FIELD_LABELS[field]).grid(row=row,column=0,sticky='w',padx=(0,8),pady=4)
            variable = tk.StringVar(value='미사용')
            box = ttk.Combobox(mapping,textvariable=variable,values=related_column_choices(field,EMPTY_COLUMN_CHOICES),width=48)
            box.grid(row=row,column=1,sticky='ew',pady=4)
            box.bind('<FocusIn>',lambda event,current=field:self.prepare_mapping_search(current,event.widget))
            box.bind('<KeyRelease>',lambda event,current=field:self.search_mapping_choices(current,event.widget,event))
            box.bind('<Double-1>',self.select_all_text)
            bind_wide_combobox(box)
            status=tk.StringVar(value='저장값')
            ttk.Label(mapping,textvariable=status,foreground='#64748B',width=6).grid(row=row,column=2,sticky='w',padx=(6,0))
            self.mapping_vars[field] = variable
            self.mapping_boxes[field] = box
            self.mapping_status_vars[field] = status
        mapping.columnconfigure(1,weight=1)
        footer = ttk.Frame(mapping)
        footer.grid(row=len(MAPPING_FIELD_ORDER)+2,column=0,columnspan=3,sticky='ew',pady=(12,0))
        ttk.Label(footer,text='필수 항목 없음 · 같은 열을 여러 항목에 선택 가능 · 입력하면 관련 열을 검색',foreground='#DB2777').pack(side='left')
        ttk.Button(footer,text='이 판매처 매칭 저장',style='Accent.TButton',command=lambda:self.safe(self.save_matching_profile)).pack(side='right')

        self.sample_headers = []
        self.sample_rows = None
        self.matching_sites.selection_set(0)
        self.load_matching_profile()

    def selected_matching_channel(self):
        selection = self.matching_sites.curselection()
        return MATCHING_CHANNELS[selection[0]] if selection else MATCHING_CHANNELS[0]

    def matching_profile(self, channel):
        internal = CHANNEL_TO_INTERNAL.get(channel,channel)
        for profile in self.service.settings.get('profiles',[]):
            if profile.get('channel') == internal or profile.get('name') == channel:
                return profile
        return None

    def matching_preset(self, channel):
        internal = CHANNEL_TO_INTERNAL.get(channel, channel)
        return next((profile for profile in PROFILE_PRESETS
                     if profile.get('channel') == internal or profile.get('name') == channel), {})

    @staticmethod
    def matching_field_config(profile, preset, field):
        """Return saved aliases/index while migrating the legacy single address field."""
        profile = profile or {}
        preset = preset or {}
        columns = profile.get('columns', {})
        indexes = profile.get('column_indexes', {})
        preset_columns = preset.get('columns', {})
        if field not in ('address1', 'address2'):
            values = columns.get(field, []) if 'columns' in profile else ORDER_COLUMNS[field]
            if not values:
                values = preset_columns.get(field, [])
            return list(values), indexes.get(field)
        position = 0 if field == 'address1' else 1
        values = columns.get(field, [])
        index = indexes.get(field)
        if not values and field == 'address1':
            values = columns.get('address', [])
            index = indexes.get('address') if index is None else index
        combine = profile.get('combine', {}).get('address', [])
        if not values and len(combine) > position:
            values = [combine[position]]
        if not values and field == 'address1':
            values = preset_columns.get('address', [])
        preset_combine = preset.get('combine', {}).get('address', [])
        if not values and len(preset_combine) > position:
            values = [preset_combine[position]]
        return list(values), index

    def load_matching_profile(self, *_):
        channel = self.selected_matching_channel()
        self.matching_channel.set(channel)
        profile = self.matching_profile(channel) or {}
        preset = self.matching_preset(channel)
        self.matching_filename.set('; '.join(profile.get('filename_hints',[])))
        self.matching_password.set(profile.get('password','tkdtkd8911!@@'))
        choices = profile_column_choices(profile, preset)
        for field, variable in self.mapping_vars.items():
            values, saved_index = self.matching_field_config(profile, preset, field)
            if isinstance(saved_index, int):
                variable.set(column_choice(saved_index, values[0] if values else ''))
                self.mapping_status_vars[field].set('저장값')
            else:
                variable.set(values[0] if values else '미사용')
                self.mapping_status_vars[field].set('미사용' if not values else '이름')
            field_choices = list(choices)
            if variable.get() not in field_choices:
                field_choices.append(variable.get())
            self.mapping_boxes[field].configure(values=related_column_choices(field,field_choices))
        self.sample_headers = []
        self.sample_rows = None
        self.mapping_choice_values = list(choices)
        self.matching_sample.set('예시 파일을 선택하지 않았습니다.')
        if profile and not profile.get('enabled',True):
            self.matching_analysis.set('제공된 샘플에 주문행이 없어 부분 설정만 적용됐습니다. 실제 주문 파일로 확인하세요.')
        else:
            self.matching_analysis.set('샘플 분석 초기값입니다. 틀린 열은 바로 수정할 수 있습니다.')

    def prepare_mapping_search(self, field, box):
        box.configure(values=related_column_choices(field, getattr(self,'mapping_choice_values',EMPTY_COLUMN_CHOICES)))

    def search_mapping_choices(self, field, box, event):
        if event.keysym in ('Up','Down','Left','Right','Return','Escape','Tab'):
            return
        query = box.get()
        try: cursor = box.index('insert')
        except tk.TclError: cursor = len(query)
        def update():
            if box.get() != query:
                return
            choices = related_column_choices(field, getattr(self,'mapping_choice_values',EMPTY_COLUMN_CHOICES), query)
            post_combobox(box,choices or ['미사용'])
            box.icursor(min(cursor,len(query)))
        box.after_idle(update)

    def select_all_text(self, event):
        event.widget.after_idle(lambda:event.widget.selection_range(0,'end'))
        return 'break'

    def load_matching_sample(self):
        path = filedialog.askopenfilename(
            parent=self.root, title=f'{self.selected_matching_channel()} 예시 주문 파일',
            filetypes=[('주문 파일','*.xlsx *.xlsm *.xls *.csv')],
        )
        if not path:
            return
        rows = read_rows(path,[self.matching_password.get().strip()])
        if not rows:
            raise ValueError('파일에 읽을 수 있는 행이 없습니다.')
        scored = []
        for index,row in enumerate(rows[:30]):
            headers = [identifier(value) for value in row]
            score = len(analyze_order_columns(headers, rows[index+1:index+11]))
            scored.append((score, sum(bool(value) for value in headers), -index, index))
        best = max(scored)[3]
        self.sample_rows = rows
        self.matching_header_row.set(str(best+1))
        self.matching_sample.set(Path(path).name)
        if not self.matching_filename.get().strip():
            self.matching_filename.set(Path(path).name)
        self.apply_sample_headers(force_auto=True)

    def apply_sample_headers(self, force_auto=False):
        if self.sample_rows is None:
            return
        try:
            row_index = int(self.matching_header_row.get())-1
            row = self.sample_rows[row_index]
        except (ValueError, IndexError):
            raise ValueError('헤더 행 번호를 올바르게 입력하세요.') from None
        profile = self.matching_profile(self.selected_matching_channel()) or {}
        preset = self.matching_preset(self.selected_matching_channel())
        self.sample_headers = sample_header_names(self.sample_rows, row_index, profile, preset)
        choices = ['미사용']+[column_choice(index, header) for index,header in enumerate(self.sample_headers) if header]
        self.mapping_choice_values = choices
        configured = profile.get('columns',{})
        aliases = {}
        configured_indexes = {}
        for field in MAPPING_FIELD_ORDER:
            values, saved_index = self.matching_field_config(profile, preset, field)
            aliases[field] = list(dict.fromkeys([*values, *ORDER_COLUMNS[field]]))
            configured_indexes[field] = saved_index
        matched=match_columns(self.sample_headers,aliases)
        automatic = analyze_order_columns(self.sample_headers, self.sample_rows[row_index+1:row_index+21],aliases)
        for field, box in self.mapping_boxes.items():
            box.configure(values=related_column_choices(field,choices))
            selected_index = None
            if force_auto and field in automatic:
                selected_index = automatic[field]
            elif isinstance(configured_indexes.get(field), int):
                selected_index = configured_indexes[field]
            else:
                field_aliases = aliases[field]
                selected_index = next((index for index,name in enumerate(self.sample_headers) if name in field_aliases),None)
            if isinstance(selected_index, int) and 0 <= selected_index < len(self.sample_headers):
                self.mapping_vars[field].set(column_choice(selected_index, self.sample_headers[selected_index]))
                method=matched.get(field,{}).get('method')
                self.mapping_status_vars[field].set(method or ('내용추정' if field in automatic else '저장값'))
            else:
                self.mapping_vars[field].set('미사용')
                self.mapping_status_vars[field].set('미사용')
        suggested_count = sum(field in automatic for field in SUGGESTED_MAPPING_FIELDS)
        exact=sum(m['method']=='일치' for m in matched.values())
        near=sum(m['method']=='근사' for m in matched.values())
        self.matching_analysis.set(f'1순위 일치 {exact}개 · 2순위 근사 {near}개 · 샘플 추정 {len(automatic)-len(matched)}개. 저장하면 주문 입력에 적용됩니다.')

    def save_matching_profile(self):
        channel = self.selected_matching_channel()
        hints = [value.strip() for value in self.matching_filename.get().replace('\n',';').split(';') if value.strip()]
        if not hints:
            raise ValueError('자동 판별에 사용할 파일명 예시를 한 개 이상 입력하세요.')
        selected = {field:variable.get().strip() for field,variable in self.mapping_vars.items()}
        selected_indexes = {field:choice_column_index(value) for field,value in selected.items()}
        old = self.matching_profile(channel) or {}
        preset = self.matching_preset(channel)
        visible = set(MAPPING_FIELD_ORDER)
        columns = {field:list(values) for field,values in old.get('columns',{}).items()
                   if field not in visible and field != 'address'}
        column_indexes = {field:index for field,index in old.get('column_indexes',{}).items()
                          if field not in visible and field != 'address'}
        for field,value in selected.items():
            if value in ('','미사용'):
                continue
            index = selected_indexes[field]
            if index is not None:
                if index < len(self.sample_headers):
                    header = self.sample_headers[index]
                elif old.get('column_indexes',{}).get(field) == index:
                    saved = old.get('columns',{}).get(field) or preset.get('columns',{}).get(field) or []
                    header = saved[0] if saved else ''
                else:
                    raise ValueError(f'{FIELD_LABELS[field]} 열 위치를 확인하려면 주문 파일을 먼저 추가하세요.')
                if header:
                    columns[field] = [header]
                column_indexes[field] = index
            else:
                columns[field] = [value]
        internal = CHANNEL_TO_INTERNAL.get(channel,channel)
        profile = {
            'customized': True,
            'name': channel,
            'channel': internal,
            'account': old.get('account','기본'),
            'filename_hints': hints,
            'required': [],
            'columns': columns,
            'column_indexes': column_indexes,
            'detected_headers': (
                {str(index):header for index,header in enumerate(self.sample_headers) if header}
                if self.sample_headers else old.get('detected_headers', {})
            ),
            'header_row': int(self.matching_header_row.get()),
            'password': self.matching_password.get().strip() or old.get('password','tkdtkd8911!@@'),
            'enabled': bool(columns),
            'excludes': old.get('excludes',[]),
            'content_rule': old.get('content_rule'),
            'combine': {field:list(values) for field,values in (old.get('combine') or preset.get('combine',{})).items()
                        if field != 'address'},
            'sum_columns': old.get('sum_columns') or preset.get('sum_columns',{}),
            'amount_is_unit': old.get('amount_is_unit', preset.get('amount_is_unit',False)),
            'purpose': old.get('purpose', preset.get('purpose','order')),
        }
        profiles = self.service.settings.setdefault('profiles',[])
        for index,item in enumerate(profiles):
            if item.get('channel') == internal or item.get('name') == channel:
                profiles[index] = profile
                break
        else:
            profiles.append(profile)
        path = self.service.folder/'settings.json'
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(self.service.settings,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,path)
        self.service.settings = settings_at(self.service.folder)
        destination = '공유 DB와 이 PC' if self.cloud_workspace else '이 PC'
        messagebox.showinfo('매칭 설정 저장',f'{channel}의 파일명과 열 설정을 {destination}에 저장했습니다.',parent=self.root)

    def button(self,parent,label,fn,style='TButton'):
        ttk.Button(parent,text=label,style=style,command=lambda:self.safe(fn)).pack(side='left',padx=4)

    def safe(self,fn):
        before=None
        try:
            if self.cloud_workspace:
                if self.cloud_workspace.pull_if_newer():
                    self.refresh()
                    self.load_matching_profile()
                    messagebox.showinfo('공유 DB 갱신','다른 PC의 최신 작업을 반영했습니다. 항목을 다시 선택해 작업해주세요.',parent=self.root)
                    return
                before=self.cloud_workspace.snapshot()
            fn()
            if self.cloud_workspace:
                self.cloud_workspace.push_if_changed()
                self.cloud_status.set(f'공유 DB 연결됨 · v{self.cloud_workspace.version}')
        except WorkspaceConflict as exc:
            if self.cloud_workspace and before is not None:
                self.cloud_workspace.restore(before)
                try:self.cloud_workspace.pull_if_newer()
                except Exception:pass
                self.refresh()
            messagebox.showerror('동시 작업 충돌',f'{exc}\n현재 작업은 적용하지 않았습니다. 최신 화면에서 다시 시도하세요.',parent=self.root)
        except Exception as exc:
            messagebox.showerror('작업 확인',str(exc),parent=self.root)

    def tree(self,parent,columns,widths):
        frame=ttk.Frame(parent); frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='extended')
        for col,width in zip(columns,widths):
            tree.heading(col,text=col); tree.column(col,width=width,minwidth=50)
        vertical=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        tree.grid(row=0,column=0,sticky='nsew'); vertical.grid(row=0,column=1,sticky='ns'); horizontal.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1); frame.columnconfigure(0,weight=1)
        bind_desktop_drag(tree)
        return tree

    def refresh_orders(self):
        self.rows={o['id']:o for o in self.service.orders()}
        self.table.delete(*self.table.get_children())
        for key,o in self.rows.items():
            d=o['data']
            channel = INTERNAL_TO_CHANNEL.get(d['channel'],d['channel'])
            duplicate = '강제 승인' if d.get('force_shipping_approved') else (f"중복 {o['duplicate_count']}건" if o['duplicate_count'] > 1 else '')
            source_product=d.get('source_product',d['product']);source_option=d.get('source_option',d['option'])
            converted=' / '.join(f"{c.get('name') or c.get('code')} [{c.get('logistics_code') or c.get('code')}]" for c in o['components'])
            values=[d['order_no'],d['recipient'],f"{d.get('postcode','')} {d['address']}".strip(),d['phone'],f"{source_product} / {source_option}",converted]
            selected_filter = self.filter.get()
            if selected_filter == '중복 주문' and o['duplicate_count'] <= 1:
                continue
            if selected_filter not in ('전체','중복 주문',o['state']):
                continue
            searchable = values + list(d.values())
            for component in o['components']:
                searchable.extend(component.values())
            haystack = ' '.join(str(value) for value in searchable if value is not None).casefold()
            terms = [term for term in self.search.get().casefold().split() if term]
            if not all(term in haystack for term in terms):
                continue
            tags = []
            if d.get('force_shipping_approved'): tags.append('forced')
            elif o['duplicate_count'] > 1: tags.append('duplicate')
            elif o['issue']: tags.append('review')
            self.table.insert('', 'end',iid=key,values=values,tags=tags)
        self.root.after_idle(lambda:autosize_tree(self.table))

    def refresh(self):
        self.refresh_orders()
        self.refresh_erp_shipments()
        self.refresh_confirmed_shipments()
        self.refresh_esm_entries()
        self.refresh_channel_status()
        counts={state:sum(o['state']==state for o in self.rows.values()) for state in ['검토 필요','출고 준비','출고 요청','부분 출고','출고 완료']}
        stats=self.service.match_statistics(self.rows.values())
        self.summary.set(f"자동 매칭 {stats['ready']:,}/{stats['total']:,}건 ({stats['rate']}%)   "+'   '.join(f'{key}  {value:,}건' for key,value in counts.items()))
        self.history.delete(*self.history.get_children())
        for a in self.service.artifacts():
            self.history.insert('', 'end',iid=a['id'],values=[a['id'],a['kind'],a['day'],'확인 완료' if a['registered'] else '—'])
        self.root.after_idle(lambda:autosize_tree(self.history,maximum=360))

    def selected(self,tree):
        ids=tree.selection()
        if not ids: raise ValueError('항목을 선택하세요.')
        return ids

    def show_detail(self,*_):
        ids=self.table.selection()
        if ids:
            o=self.rows[ids[0]]
            event = f"이벤트: {o['data'].get('event_name')}  " if o['data'].get('event_name') else ''
            duplicate = f"중복 주문 {o['duplicate_count']}건  " if o['duplicate_count'] > 1 else ''
            methods=' / '.join(dict.fromkeys(c.get('match_method','전표 DB / 저장 매칭') for c in o['components']))
            near=' · '.join(f"{FIELD_LABELS.get(field,field)}←{m['header']}" for field,m in o['data'].get('column_matches',{}).items() if m['method']=='근사')
            self.detail.set(event+duplicate+'상품 연결: '+methods+' · 구성품: '+' / '.join(f"{c['code']} × {c['quantity']}" for c in o['components'])+' · 근사 열: '+(near or '없음')+'  '+o['issue'])

    def open_mapping_from_click(self, event):
        row = self.table.identify_row(event.y)
        if row:
            self.table.selection_set(row)
            self.safe(self.mapping)

    def select_ready(self):
        self.table.selection_set([key for key in self.table.get_children() if self.rows[key]['state']=='출고 준비'])

    def force_shipping_approval(self):
        ids=list(self.selected(self.table))
        orders=[self.rows[key] for key in ids]
        if all(order['data'].get('force_shipping_approved') for order in orders):
            if not messagebox.askyesno('강제 출고 승인 해제',f'선택한 {len(ids):,}건의 강제 출고 승인을 해제할까요?',parent=self.root):return
            self.service.set_force_shipping_approval(ids,False)
            self.refresh()
            return
        reason=simpledialog.askstring('강제 출고 승인','중복·특수 주문을 출고하는 사유를 입력하세요.\n예: 정상 재구매, 교환 재출고, 고객 요청',parent=self.root)
        if reason is None:return
        reason=reason.strip()
        if not reason:raise ValueError('강제 출고 승인 사유를 입력하세요.')
        if not messagebox.askyesno('강제 출고 승인',f'선택한 {len(ids):,}건을 강제 출고 승인할까요?\n\n사유: {reason}\n\n승인 후 출고 사전검사를 다시 실행합니다.',parent=self.root):return
        self.service.set_force_shipping_approval(ids,True,reason)
        self.refresh()
        if self.preflight_review(ids,show_success=False):
            messagebox.showinfo('강제 출고 승인','승인되었습니다. 선택 주문 출고파일 버튼으로 변환할 수 있습니다.',parent=self.root)

    def batch_matching_review(self):
        groups={}
        for order in self.rows.values():
            if order['state']!='검토 필요':continue
            data=order['data'];key=(data['channel'],data['product'],data['option'])
            groups.setdefault(key,[]).append(order)
        if not groups:
            messagebox.showinfo('미매칭 묶음 검토','현재 검토가 필요한 상품이 없습니다.',parent=self.root);return
        win=tk.Toplevel(self.root);win.title('미매칭 상품 묶음 검토');win.geometry('1100x620');win.transient(self.root)
        ttk.Label(win,text='같은 판매처·상품·옵션 주문을 한 묶음으로 표시합니다.',font=(self.font_family,15,'bold'),padding=(16,14)).pack(anchor='w')
        ttk.Label(win,text='한 묶음을 매칭하면 해당 상품·옵션의 출고요청 전 주문 전체에 적용됩니다.',foreground='#64748B',padding=(16,0)).pack(anchor='w')
        tree=self.tree(win,['판매처','원본 상품','옵션','주문 수','총 수량','현재 사유'],[150,310,240,90,90,280])
        ordered=list(groups.items())
        for index,((channel,product,option),orders) in enumerate(ordered):
            total=sum(int(o['data']['quantity']) for o in orders)
            tree.insert('', 'end',iid=str(index),values=[INTERNAL_TO_CHANNEL.get(channel,channel),product,option,len(orders),total,orders[0]['issue']])
        def edit_selected(*_):
            selected=tree.selection()
            if not selected:return
            order=ordered[int(selected[0])][1][0]
            self.table.selection_set(order['id']);self.mapping()
            self.refresh()
            if win.winfo_exists():win.destroy();self.batch_matching_review()
        tree.bind('<Double-1>',edit_selected)
        line=ttk.Frame(win,padding=12);line.pack(fill='x')
        self.button(line,'선택 묶음 매칭',edit_selected,style='Accent.TButton')
        self.button(line,'닫기',win.destroy)

    def save_path(self,name):
        return filedialog.asksaveasfilename(parent=self.root,initialfile=name,defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')])

    def order_files(self, title):
        return filedialog.askopenfilenames(
            parent=self.root,
            title=title,
            filetypes=[('주문 파일','*.xlsx *.xlsm *.xls *.csv')],
        )

    def setup_file_drop(self, widget):
        """tkinterdnd2가 포함된 실행 환경에서 탐색기 파일 드롭을 활성화한다."""
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind('<<Drop>>',self.on_files_dropped)
        except (ImportError, tk.TclError, AttributeError):
            widget.configure(text='＋  주문 파일 선택   ·   XLSX / XLS / CSV')

    def on_files_dropped(self, event):
        paths = [Path(value) for value in self.root.tk.splitlist(event.data)]
        supported = [path for path in paths if path.is_file() and path.suffix.lower() in ('.xlsx','.xlsm','.xls','.csv')]
        if not supported:
            messagebox.showwarning('파일 드래그','XLSX, XLS, CSV 주문 파일을 넣어주세요.',parent=self.root)
            return
        self.safe(lambda:self.import_paths(supported))

    def import_paths(self, paths, channel_override=None, title='판매 입력'):
        new,duplicate=self.service.import_files(paths,channel_override=channel_override)
        source_names={Path(path).name for path in paths}
        imported=[order for order in self.service.orders() if order['data'].get('source_file') in source_names]
        history_duplicates=0
        if self.cloud_client and imported:
            try:history_duplicates=self.service.check_shipping_history(self.cloud_client,[order['id'] for order in imported])
            except Exception:pass
        self.refresh()
        stats=self.service.match_statistics(imported)
        methods=' · '.join(f'{name} {count}건' for name,count in stats['methods'].items())
        messagebox.showinfo(title,
            f"파일 {len(paths)}개 분석 완료\n신규 {new}건 · 동일 주문 제외 {duplicate}건\n\n"
            f"자동 확정 {stats['ready']}건 ({stats['rate']}%) · 확인 필요 {stats['review']}건\n"
            f"{methods or '적용된 자동 규칙 없음'}"
            +(f"\n출고 프로그램 이력 중복 {history_duplicates}건" if history_duplicates else ''),parent=self.root)

    def refresh_channel_status(self):
        files = {channel:set() for channel in SALES_CHANNELS}
        event_channels = {rule['channel'] for rule in self.service.event_rules() if rule['active']}
        for order in self.rows.values():
            data = order['data']
            channel = INTERNAL_TO_CHANNEL.get(data.get('channel'), data.get('channel'))
            source = data.get('source_file')
            if channel in files and source:
                files[channel].add(source)
        for channel, status in self.channel_status.items():
            count = len(files[channel])
            internal = CHANNEL_TO_INTERNAL.get(channel,channel)
            event = internal in event_channels
            prefix = 'EVENT · ' if event else ('✓  ' if count else '□  ')
            suffix = f'  ({count}개)' if count else ''
            status.set(f'{prefix}{channel}{suffix}')
            self.channel_buttons[channel].configure(style='Complete.Channel.TButton' if count or event else 'Channel.TButton')

    def import_channel(self, channel):
        paths = self.order_files(f'{channel} 주문 파일 선택')
        if paths:
            internal = CHANNEL_TO_INTERNAL.get(channel, channel)
            self.import_paths(paths,channel_override=internal,title=f'{channel} 주문 입력')

    def import_files(self):
        paths=self.order_files('판매 주문 파일 선택 · 파일명과 등록된 양식으로 자동 판별')
        if paths:
            self.import_paths(paths)

    def mapping(self):
        key=self.selected(self.table)[0]; o=self.rows[key]; d=o['data']
        win=tk.Toplevel(self.root); win.title('상품 구성 · ERP 거래처 연결')
        win.geometry(f"{max(960,min(1500,win.winfo_screenwidth()-80))}x790")
        ttk.Label(win,text=f"{d['channel']}  |  {d['product']} / {d['option']}",wraplength=1000,padding=12).pack(anchor='w')
        ttk.Label(win,text='상품에 포함되는 출고 품목을 입력하세요. 첫 줄은 본품입니다.\n최종 출고수량은 모든 품목에 원본 엑셀 수량을 그대로 적용하며 구성 수량을 곱하지 않습니다.',padding=12).pack(anchor='w')
        grid=ttk.Frame(win,padding=12);grid.pack(fill='both',expand=True)
        fields=['code','logistics_code','name','quantity','warehouse','customer']
        labels=['ERP 품목코드','물류사 품목코드','품목명','구성 수량(곱셈 안 함)','출하창고','거래처코드']
        widths=[34,34,34,10,14,34]
        for column,label in enumerate(labels):ttk.Label(grid,text=label).grid(row=0,column=column,padx=3,pady=6)
        entries=[]
        customer=self.service.channel_customer_code(d['channel'])
        customer_choices=self.service.customer_choices()
        catalog_choices = []
        for code,item in sorted(self.service.catalog.items.items()):
            name = item.get('representative_name') or item.get('item_name') or ''
            catalog_choices.append(f'{code} · {name}' if name else code)
        source_key=compact(f"{d['product']} {d['option']}")
        def score_choice(choice):
            return SequenceMatcher(None,source_key,compact(choice)).ratio()
        suggested_choices=sorted(catalog_choices,key=score_choice,reverse=True)
        suggested_choices=[choice for choice in suggested_choices if score_choice(choice)>=.35][:8]
        if suggested_choices:
            ttk.Label(win,text='유사 품목 추천: '+'  /  '.join(suggested_choices[:4]),wraplength=1350,
                      foreground='#1D4ED8',padding=(12,0)).pack(anchor='w')
            catalog_choices=suggested_choices+[choice for choice in catalog_choices if choice not in suggested_choices]
        candidates=self.service.item_candidates(d)
        candidate_box=ttk.LabelFrame(win,text='유사 품목 후보 비교 · 두 번 클릭하면 첫 구성품에 적용',padding=8)
        candidate_box.pack(fill='x',padx=12,pady=(8,0))
        candidate_tree=ttk.Treeview(candidate_box,columns=['점수','품목코드','품목명','추천 이유','기존 별칭','위킵 SKU'],show='headings',height=5)
        for column,width in zip(candidate_tree['columns'],[70,150,390,180,90,90]):
            candidate_tree.heading(column,text=column);candidate_tree.column(column,width=width,anchor='w')
        candidate_tree.pack(fill='x')
        for index,candidate in enumerate(candidates):
            candidate_tree.insert('','end',iid=str(index),values=[f"{candidate['score']:.0%}",candidate['code'],candidate['name'],candidate['reason'],
                '저장됨' if candidate['alias'] else '—','등록' if candidate['sku'] else '미등록'])
        def add_row(component=None):
            if len(entries)>=12:raise ValueError('한 상품은 최대 12개 구성품을 입력할 수 있습니다.')
            defaults=dict(code='',logistics_code='',name='',quantity=1,unit_amount=0,warehouse=self.service.settings['warehouse'],customer=customer)
            defaults.update(component or {})
            variables={field:tk.StringVar(value=str(defaults[field])) for field in fields}
            widgets=[]
            for column,field in enumerate(fields):
                if field in ('code','customer','warehouse'):
                    choices=catalog_choices if field=='code' else (customer_choices if field=='customer' else ['100 본사창고','300 위킵창고'])
                    widget=ttk.Combobox(grid,textvariable=variables[field],values=choices,width=widths[column])
                    def chosen(_event,variables=variables,field=field):
                        value=_event.widget.get().split(' · ',1)[0]
                        if field=='customer':
                            variables['customer'].set(value)
                            return
                        if field=='warehouse':
                            variables['warehouse'].set(value)
                            return
                        variables['code'].set(value);item=self.service.catalog.items.get(value,{})
                        variables['logistics_code'].set(value)
                        variables['name'].set(item.get('representative_name') or item.get('item_name') or value)
                    widget.bind('<<ComboboxSelected>>',chosen)
                    def search_catalog(event,widget=widget,choices=choices):
                        if event.keysym in ('Up','Down','Left','Right','Return','Escape','Tab'): return
                        query=widget.get();cursor=widget.index('insert')
                        def update():
                            if widget.get()!=query:return
                            post_combobox(widget,filter_combobox_choices(query,choices))
                            widget.icursor(min(cursor,len(query)))
                        widget.after_idle(update)
                    widget.bind('<KeyRelease>',search_catalog)
                    widget.bind('<Double-1>',self.select_all_text)
                    bind_wide_combobox(widget)
                else:widget=ttk.Entry(grid,textvariable=variables[field],width=widths[column])
                widget.grid(row=len(entries)+1,column=column,padx=3,pady=4);widgets.append(widget)
            entries.append((variables,widgets))
        from decimal import Decimal
        for c in o['components']:
            per=int(c['quantity'])//int(d['quantity'])
            if per:
                add_row({**c,'quantity':per,'unit_amount':str((Decimal(c['amount'])/Decimal(c['quantity'])).quantize(Decimal('1')))})
        if not entries:add_row()
        def use_candidate(*_):
            selected=candidate_tree.selection()
            if not selected or not entries:return
            candidate=candidates[int(selected[0])];variables=entries[0][0]
            variables['code'].set(candidate['code']);variables['logistics_code'].set(candidate['code']);variables['name'].set(candidate['name'])
        candidate_tree.bind('<Double-1>',use_candidate)
        def remove_row():
            if len(entries)>1:
                _,widgets=entries.pop()
                for widget in widgets:widget.destroy()
        def save():
            components=[{field:var.get().strip() for field,var in variables.items()} for variables,_ in entries]
            for component in components: component['quantity'] = '1'
            self.service.set_mapping(key,components)
            affected=sum(1 for order in self.service.orders() if self.service.mapping_key(order['data'])==self.service.mapping_key(d))
            alias_result='이 PC와 공유 작업공간에 저장했습니다.'
            if save_alias.get():
                if not self.cloud_client:
                    alias_result='로컬 매칭은 저장했습니다. 출고 DB 별칭 저장은 API 로그인 후 사용할 수 있습니다.'
                else:
                    payload={
                        'source_channel':d['channel'],
                        'source_product_name':d['product'],
                        'source_options':d['option'],
                        'normalized_source':compact(f"{d['product']} {d['option']}"),
                        'components':[{'item_code':component['code'],'quantity':1,'sequence':index}
                                      for index,component in enumerate(components,1)],
                        'is_active':True,
                    }
                    try:
                        self.cloud_client.table('item_aliases').upsert(
                            payload,on_conflict='source_channel,normalized_source').execute()
                        shipping=self.service._shipping_catalog()
                        if shipping is not None:
                            shipping.aliases[(channel_key(d['channel']),payload['normalized_source'])]=[payload]
                        alias_result='로컬 매칭과 출고 DB 공용 별칭을 저장했습니다.'
                    except Exception as exc:
                        alias_result=f'로컬 매칭은 저장했습니다. 출고 DB 별칭 저장 실패: {exc}'
            self.refresh(); win.destroy()
            messagebox.showinfo('매칭 저장',f'{alias_result}\n동일 상품·옵션 주문 {affected}건을 다시 매칭했습니다.',parent=self.root)
        line=ttk.Frame(win,padding=12); line.pack(fill='x')
        save_alias=tk.BooleanVar(value=True)
        ttk.Checkbutton(line,text='출고 프로그램 DB 별칭에도 저장',variable=save_alias).pack(side='left',padx=(0,12))
        self.button(line,'구성품 추가',add_row);self.button(line,'마지막 구성품 제거',remove_row)
        self.button(line,'같은 상품·옵션 전체에 매칭 저장',save,style='Accent.TButton')

    def event_rule(self):
        key=self.selected(self.table)[0]; order=self.rows[key]; data=order['data']
        source_product=data.get('source_product',data['product']); source_option=data.get('source_option',data['option'])
        from decimal import Decimal
        event_unit_amount=data.get('event_unit_amount') or str((Decimal(data['amount'])/Decimal(max(1,int(data['quantity'])))).quantize(Decimal('1')))
        win=tk.Toplevel(self.root);win.title('판매처 이벤트 상품 규칙')
        win.geometry(f"{max(960,min(1500,win.winfo_screenwidth()-80))}x680")
        frame=ttk.Frame(win,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='이벤트 상품 변환 규칙',font=(self.font_family,16,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,8))
        ttk.Label(frame,text='같은 판매처에서 조건 상품명과 조건 옵션이 모두 일치하면 아래 이벤트 금액과 출고 구성품으로 자동 변환합니다.',foreground='#64748B').grid(row=1,column=0,columnspan=2,sticky='w',pady=(0,10))
        values={
            'name':tk.StringVar(value=data.get('event_name','')),
            'product':tk.StringVar(value=data['product']),
            'option':tk.StringVar(value=data['option']),
            'amount':tk.StringVar(value=event_unit_amount),
        }
        rows=[('판매처',INTERNAL_TO_CHANNEL.get(data['channel'],data['channel'])),('조건 상품명',source_product),('조건 옵션',source_option)]
        for row,(label,value) in enumerate(rows,start=2):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=5);ttk.Label(frame,text=value,foreground='#475569',wraplength=500).grid(row=row,column=1,sticky='w',pady=5)
        for row,(field,label) in enumerate([('name','이벤트 이름'),('product','표시 상품명'),('option','표시 옵션'),('amount','이벤트 단가 (주문수량 자동 곱셈)')],start=5):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=5);entry=ttk.Entry(frame,textvariable=values[field],width=58);entry.grid(row=row,column=1,sticky='ew',pady=5);entry.bind('<Double-1>',self.select_all_text)
        frame.columnconfigure(1,weight=1)

        component_box=ttk.LabelFrame(frame,text='이벤트 출고 구성품',padding=10)
        component_box.grid(row=9,column=0,columnspan=2,sticky='nsew',pady=(12,5))
        frame.rowconfigure(9,weight=1)
        fields=['code','logistics_code','name','quantity','unit_amount','warehouse','customer']
        labels=['ERP 품목코드','물류사 품목코드','품목명','구성 수량(곱셈 안 함)','부속품 단가','창고','거래처코드']
        widths=[34,34,34,10,14,10,34]
        for column,label in enumerate(labels):ttk.Label(component_box,text=label).grid(row=0,column=column,padx=3,pady=5)
        catalog_choices=[]
        for code,item in sorted(self.service.catalog.items.items()):
            name=item.get('representative_name') or item.get('item_name') or ''
            catalog_choices.append(f'{code} · {name}' if name else code)
        customer=self.service.channel_customer_code(data['channel'])
        customer_choices=self.service.customer_choices()
        entries=[]
        def add_component(component=None):
            if len(entries)>=12:raise ValueError('이벤트 구성품은 최대 12개까지 입력할 수 있습니다.')
            defaults=dict(code='',logistics_code='',name='',quantity=1,unit_amount=0,warehouse=self.service.settings['warehouse'],customer=customer)
            defaults.update(component or {})
            variables={field:tk.StringVar(value=str(defaults[field])) for field in fields};widgets=[]
            for column,field in enumerate(fields):
                if field in ('code','customer'):
                    choices=catalog_choices if field=='code' else customer_choices
                    widget=ttk.Combobox(component_box,textvariable=variables[field],values=choices,width=widths[column])
                    def chosen(_event,variables=variables,field=field):
                        value=_event.widget.get().split(' · ',1)[0]
                        if field=='customer':
                            variables['customer'].set(value)
                            return
                        variables['code'].set(value);item=self.service.catalog.items.get(value,{})
                        variables['logistics_code'].set(value);variables['name'].set(item.get('representative_name') or item.get('item_name') or value)
                    def search(event,widget=widget,choices=choices):
                        if event.keysym in ('Up','Down','Left','Right','Return','Escape','Tab'):return
                        query=widget.get();cursor=widget.index('insert')
                        def update():
                            if widget.get()!=query:return
                            post_combobox(widget,filter_combobox_choices(query,choices))
                            widget.icursor(min(cursor,len(query)))
                        widget.after_idle(update)
                    widget.bind('<<ComboboxSelected>>',chosen);widget.bind('<KeyRelease>',search);widget.bind('<Double-1>',self.select_all_text);bind_wide_combobox(widget)
                else:
                    widget=ttk.Entry(component_box,textvariable=variables[field],width=widths[column]);widget.bind('<Double-1>',self.select_all_text)
                widget.grid(row=len(entries)+1,column=column,padx=3,pady=3);widgets.append(widget)
            entries.append((variables,widgets))
        definitions=data.get('event_components',[])
        if not definitions and order['components']:
            definitions=[]
            for index,component in enumerate(order['components']):
                unit='0' if index==0 else str((Decimal(component['amount'])/Decimal(data['quantity'])).quantize(Decimal('1')))
                definitions.append({**component,'quantity':1,'unit_amount':unit})
        for component in definitions:add_component(component)
        if not entries:add_component()
        def remove_component():
            if len(entries)>1:
                _,widgets=entries.pop()
                for widget in widgets:widget.destroy()

        def save():
            components=[{field:value.get().strip() for field,value in variables.items()} for variables,_ in entries]
            for component in components: component['quantity'] = '1'
            self.service.set_event_rule(key,values['name'].get(),values['product'].get(),values['option'].get(),values['amount'].get(),components);self.refresh();win.destroy()
        def clear():
            self.service.clear_event_rule(key);self.refresh();win.destroy()
        actions=ttk.Frame(frame);actions.grid(row=10,column=0,columnspan=2,sticky='ew',pady=(10,0))
        self.button(actions,'구성품 추가',add_component);self.button(actions,'마지막 구성품 제거',remove_component)
        self.button(actions,'이벤트 규칙 삭제',clear)
        self.button(actions,'이벤트 규칙 저장',save,style='Accent.TButton')

    def delete_orders(self):
        ids=self.selected(self.table)
        states=', '.join(f'{state} {sum(self.rows[key]["state"]==state for key in ids)}건' for state in sorted({self.rows[key]['state'] for key in ids}))
        if not messagebox.askyesno('주문 삭제',
            f'선택한 주문 {len(ids)}건을 삭제할까요?\n{states}\n\n매칭 후 주문과 취소 주문도 삭제할 수 있습니다. 연결된 출고요청·실제출고 작업자료도 함께 정리됩니다.',parent=self.root):
            return
        count=self.service.delete_orders(ids);self.refresh();messagebox.showinfo('주문 삭제',f'{count}건을 삭제했습니다.',parent=self.root)

    def delivery(self):
        key=self.selected(self.table)[0];d=self.rows[key]['data']
        win=tk.Toplevel(self.root);win.title('주문 배송정보 수정');win.geometry('720x500');win.transient(self.root);win.grab_set()
        frame=ttk.Frame(win,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='주문 배송정보 수정',font=(self.font_family,16,'bold')).grid(row=0,column=0,columnspan=2,sticky='w')
        ttk.Label(frame,text=f"{d['order_no']}  ·  {d['product']} / {d['option']}",foreground='#64748B',wraplength=650).grid(row=1,column=0,columnspan=2,sticky='w',pady=(4,16))
        changes=d.get('delivery_changes',{})
        if changes:
            detail=' · '.join(f"{FIELD_LABELS.get(field,field)}: {value['original']} → {value['normalized'] or '확인 필요'}" for field,value in changes.items())
            ttk.Label(frame,text='자동 정리: '+detail,foreground='#B45309',wraplength=650).grid(row=2,column=0,columnspan=2,sticky='w',pady=(0,10))
        offset=1 if changes else 0
        variables={field:tk.StringVar(value=d.get(field,'')) for field in ('recipient','phone','postcode','address','memo')}
        for row,(field,label) in enumerate([('recipient','수령인'),('phone','연락처'),('postcode','우편번호'),('address','주소'),('memo','배송메모')],start=2+offset):
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='nw',padx=(0,12),pady=7)
            if field in ('address','memo'):
                entry=tk.Text(frame,height=3,font=(self.font_family,10),wrap='word');entry.insert('1.0',variables[field].get());entry.grid(row=row,column=1,sticky='ew',pady=7)
                variables[field]._text_widget=entry
            else:
                ttk.Entry(frame,textvariable=variables[field]).grid(row=row,column=1,sticky='ew',pady=7)
        frame.columnconfigure(1,weight=1)
        def save():
            fields={}
            for field,var in variables.items():
                widget=getattr(var,'_text_widget',None)
                fields[field]=widget.get('1.0','end-1c') if widget else var.get()
            self.service.edit_delivery(key,fields);self.refresh();win.destroy()
        line=ttk.Frame(frame);line.grid(row=7+offset,column=0,columnspan=2,sticky='e',pady=(18,0))
        self.button(line,'취소',win.destroy);self.button(line,'배송정보 저장',save,style='Accent.TButton')

    def preflight_review(self, ids=None, show_success=True):
        ids=list(ids or self.table.selection() or self.table.get_children())
        if not ids:raise ValueError('검사할 주문이 없습니다.')
        issues=self.service.preflight(ids)
        if not issues:
            if show_success:messagebox.showinfo('출고 사전검사','위킵 출고와 판매전표에 필요한 값이 모두 준비됐습니다.',parent=self.root)
            return True
        win=tk.Toplevel(self.root);win.title('출고 사전검사 · 수정 필요');win.geometry('1000x560');win.transient(self.root);win.grab_set()
        ttk.Label(win,text=f'수정이 필요한 항목 {len(issues):,}개',font=(self.font_family,16,'bold'),padding=(16,14)).pack(anchor='w')
        ttk.Label(win,text='항목을 두 번 클릭하면 해당 주문의 상품 또는 배송정보 수정 화면으로 이동합니다.',foreground='#64748B',padding=(16,0)).pack(anchor='w')
        tree=self.tree(win,['구분','내용'],[130,800])
        for index,(_order_id,kind,detail) in enumerate(issues):tree.insert('','end',iid=str(index),values=[kind,detail],tags=('review',))
        tree.tag_configure('review',foreground='#BE123C',background='#FFF1F2')
        def open_issue(*_):
            selected=tree.selection()
            if not selected:return
            order_id,kind,_=issues[int(selected[0])]
            win.destroy();self.table.selection_set(order_id);self.table.see(order_id)
            self.delivery() if kind=='배송정보' else self.mapping()
        tree.bind('<Double-1>',open_issue)
        line=ttk.Frame(win,padding=12);line.pack(fill='x');self.button(line,'선택 항목 수정',open_issue,style='Accent.TButton');self.button(line,'닫기',win.destroy)
        return False

    def confirm_request_review(self, ids):
        orders=[self.rows[key] for key in ids]
        result={'approved':False}
        win=tk.Toplevel(self.root);win.title('위킵 출고 전 최종 검토');win.geometry('1180x680');win.transient(self.root);win.grab_set()
        ttk.Label(win,text='위킵 출고 전 최종 검토',font=(self.font_family,17,'bold'),padding=(16,14)).pack(anchor='w')
        total=sum(int(order['data']['quantity']) for order in orders)
        channels=len({order['data']['channel'] for order in orders})
        ttk.Label(win,text=f'선택 주문 {len(orders):,}건 · 총 출고수량 {total:,}개 · 판매처 {channels:,}곳',
                  foreground='#1D4ED8',padding=(16,0)).pack(anchor='w')
        ttk.Label(win,text='원본 상품, 변환 출고품목, 수령인과 주소를 확인한 뒤 승인하세요.',foreground='#64748B',padding=(16,6)).pack(anchor='w')
        ttk.Label(win,text='위킵 SKU · ERP 거래처코드 · ERP 품목코드 사전검사 정상',foreground='#166534',padding=(16,0)).pack(anchor='w')
        tree=self.tree(win,['상태','판매처','주문번호','원본 상품 / 옵션','변환 출고품목 · 수량','수령인','연락처','주소'],[90,130,145,260,300,90,120,300])
        for order in orders:
            d=order['data'];converted=' / '.join(f"{c.get('name') or c.get('code')} × {c.get('quantity')}" for c in order['components'])
            tree.insert('','end',values=[order['state'],INTERNAL_TO_CHANNEL.get(d['channel'],d['channel']),d['order_no'],
                f"{d['product']} / {d['option']}",converted,d['recipient'],d['phone'],f"{d['postcode']} {d['address']}"])
        def approve():result['approved']=True;win.destroy()
        line=ttk.Frame(win,padding=12);line.pack(fill='x')
        self.button(line,'돌아가서 수정',win.destroy);self.button(line,'검토 완료 · 출고파일 생성',approve,style='Accent.TButton')
        win.protocol('WM_DELETE_WINDOW',win.destroy);self.root.wait_window(win)
        return result['approved']

    def request(self):
        ids=self.selected(self.table)
        if not self.preflight_review(ids,show_success=False):return
        if not self.confirm_request_review(ids):return
        path=self.save_path('출고요청_'+self.today.get()+'.xlsx')
        if path:
            batch=self.service.request(ids,self.today.get(),path); self.refresh()
            messagebox.showinfo('파일 생성',f'{batch}\n출고요청 파일을 저장했습니다. 물류사 양식을 확인한 뒤 전달하세요.')

    def result_template(self):
        path=self.save_path('위킵_출고결과_양식.xlsx')
        if path:Path(path).write_bytes(wekeep_workbook_bytes([]))

    def auto_results(self):
        selected_day=self.erp_ship_day.get()
        new,duplicate=self.service.auto_import_shipments(selected_day);self.refresh()
        messagebox.showinfo(
            '자동 반영 완료',
            f'{selected_day} 출고요청 기준\n실제 출고 {new}행 · 기존 반영 {duplicate}행\n스마트스토어는 자동으로 제외했습니다.',
            parent=self.root,
        )

    def results(self):
        path=filedialog.askopenfilename(filetypes=[('물류 결과','*.xlsx *.xls *.csv')])
        if path:
            new,duplicate=self.service.import_results(path,self.erp_ship_day.get());self.refresh()
            messagebox.showinfo('반영 완료',f'실제 출고 {new}행 · 중복 제외 {duplicate}행')

    def smartstore_erp_results(self):
        path=filedialog.askopenfilename(
            parent=self.root,title='스마트스토어 ERP 입력 원본 선택',
            filetypes=[('스마트스토어 ERP 파일','*.xlsx *.xlsm *.xls *.csv')],
        )
        if path:
            new,duplicate=self.service.import_smartstore_erp(path,self.erp_ship_day.get());self.refresh()
            messagebox.showinfo('반영 완료',f'스마트스토어 ERP {new}행 · 중복 제외 {duplicate}행')

    def save_esm_login(self):
        save_credentials(
            self.service.folder/'esm_credentials.dat',
            self.esm_user_id.get(), self.esm_password.get(),
        )
        messagebox.showinfo(
            '보호 저장 완료',
            'ESM PLUS 로그인 정보를 Windows 사용자 계정으로 암호화해 이 PC에만 저장했습니다.',
            parent=self.root,
        )

    def import_esm_files(self):
        paths=filedialog.askopenfilenames(
            parent=self.root,title='ESM PLUS 전체주문 엑셀 선택',
            filetypes=[('ESM PLUS 주문 파일','*.xls *.xlsx')],
        )
        if not paths:return
        imported_on=date.fromisoformat(self.esm_end_day.get()).isoformat()
        new,duplicate=self.service.import_esm_erp(paths,imported_on)
        self.refresh()
        messagebox.showinfo('ESM 변환 완료',f'옥션/지마켓 {new:,}행 · 중복 제외 {duplicate:,}행',parent=self.root)

    def download_esm(self):
        if getattr(self,'_esm_downloading',False):
            raise ValueError('ESM PLUS 자동 다운로드가 이미 진행 중입니다.')
        start=date.fromisoformat(self.esm_start_day.get()).isoformat()
        end=date.fromisoformat(self.esm_end_day.get()).isoformat()
        if start>end:raise ValueError('시작 주문일은 종료 주문일보다 늦을 수 없습니다.')
        user_id,password=self.esm_user_id.get().strip(),self.esm_password.get()
        if not user_id or not password:raise ValueError('ESM PLUS 아이디와 비밀번호를 입력하세요.')
        self._esm_downloading=True
        self.esm_progress.set('ESM PLUS 자동 다운로드를 시작합니다. 브라우저를 닫지 마세요.')
        download_dir=self.service.folder/'esm_downloads'/f'{start}_{end}'
        def progress(item):
            self.root.after(0,lambda:self.esm_progress.set(f'{item.status} · {item.detail}'))
        def worker():
            try:
                paths=download_esm_orders(user_id,password,start,end,download_dir,progress)
                self.root.after(0,lambda:(setattr(self,'_esm_downloading',False),self.safe(lambda:self._finish_esm_download(paths,end))))
            except Exception as exc:
                detail=str(exc) or exc.__class__.__name__
                self.root.after(0,lambda:self._esm_download_failed(detail))
        threading.Thread(target=worker,daemon=True).start()

    def _finish_esm_download(self, paths, imported_on):
        self._esm_downloading=False
        new,duplicate=self.service.import_esm_erp(paths,imported_on)
        self.esm_progress.set(f'완료 · 파일 {len(paths):,}개 · 신규 {new:,}행 · 중복 {duplicate:,}행')
        self.refresh()
        messagebox.showinfo('ESM 자동 수집 완료',f'파일 {len(paths):,}개에서 신규 {new:,}행을 변환했습니다.\n중복 {duplicate:,}행은 제외했습니다.',parent=self.root)

    def _esm_download_failed(self, detail):
        self._esm_downloading=False
        self.esm_progress.set('자동 다운로드 실패 · 파일 직접 추가도 사용할 수 있습니다.')
        messagebox.showerror('ESM 자동 다운로드 확인',detail,parent=self.root)

    def refresh_esm_entries(self):
        if not hasattr(self,'esm_entries'):return
        self.esm_entries.delete(*self.esm_entries.get_children())
        for entry in self.service.esm_erp_entries():
            status='ERP 반영 완료' if entry['erp_id'] else entry['issue'] or '변환 준비'
            self.esm_entries.insert('', 'end', iid=entry['id'], values=[
                entry['day'],entry['channel'],entry['order_no'],entry['product'],entry['option'],
                entry['quantity'],f"{int(Decimal(entry['unit_amount'])):,}",f"{int(Decimal(entry['amount'])):,}",
                entry['component_summary'] or '미매칭',status,
            ],tags=('review',) if entry['issue'] and not entry['erp_id'] else ())
        self.esm_entries.tag_configure('review',foreground='#BE123C',background='#FFF1F2')
        self.root.after_idle(lambda:autosize_tree(self.esm_entries,maximum=340))

    def edit_esm_set(self):
        entry_id=self.selected(self.esm_entries)[0]
        row=self.service.esm_erp_row(entry_id)
        if not row:raise ValueError('옥션/지마켓 ERP 행을 찾지 못했습니다.')
        data=row['data'];channel=data['channel']
        win=tk.Toplevel(self.root);win.title(f'{channel} ERP 상품 매칭');win.geometry('1120x620');win.transient(self.root);win.grab_set()
        ttk.Label(win,text=f'{channel} ERP 상품 매칭',font=(self.font_family,17,'bold'),padding=(16,14)).pack(anchor='w')
        ttk.Label(win,text=f"{data.get('order_no')}  |  {data.get('product')} / {data.get('option')}",padding=(16,0),wraplength=1050).pack(anchor='w')
        ttk.Label(win,text=f"주문수량 {data['quantity']} · ERP 총금액 {int(Decimal(data['amount'])):,}원 · 첫 구성품 금액은 나머지 금액으로 자동 계산됩니다.",foreground='#64748B',padding=(16,6)).pack(anchor='w')
        grid=ttk.Frame(win,padding=16);grid.pack(fill='both',expand=True)
        labels=['ERP 품목코드','품목명','부속품 단가','출하창고','거래처코드']
        for column,label in enumerate(labels):ttk.Label(grid,text=label).grid(row=0,column=column,padx=4,pady=6,sticky='w')
        entries=[];customer=self.service.channel_customer_code(channel)
        def add_row(component=None):
            component=component or {};index=len(entries);q=max(1,int(component.get('quantity') or data.get('quantity') or 1))
            unit='0' if index==0 else str(int(Decimal(component.get('amount','0'))/Decimal(q)))
            values={
                'code':tk.StringVar(value=component.get('code','')),
                'name':tk.StringVar(value=component.get('name','')),
                'unit_amount':tk.StringVar(value=unit),
                'warehouse':tk.StringVar(value=component.get('warehouse',self.service.settings['warehouse'])),
                'customer':tk.StringVar(value=component.get('customer',customer)),
            }
            widgets=[]
            for column,key in enumerate(('code','name','unit_amount','warehouse','customer')):
                widget=ttk.Entry(grid,textvariable=values[key],width=(24 if key in ('code','customer') else 34 if key=='name' else 13))
                widget.grid(row=index+1,column=column,padx=4,pady=4,sticky='ew');widgets.append(widget)
            entries.append((values,widgets))
        for component in row['components']:add_row(component)
        if not entries:add_row()
        def remove_row():
            if len(entries)>1:
                _,widgets=entries.pop()
                for widget in widgets:widget.destroy()
        def save():
            components=[]
            for values,_ in entries:
                item={key:value.get().strip() for key,value in values.items()}
                item.update({'logistics_code':item['code'],'quantity':'1'})
                components.append(item)
            self.service.set_esm_erp_components(entry_id,components)
            win.destroy();self.refresh()
        actions=ttk.Frame(win,padding=16);actions.pack(fill='x')
        self.button(actions,'구성품 추가',lambda:add_row())
        self.button(actions,'마지막 구성품 삭제',remove_row,style='Danger.TButton')
        self.button(actions,'상품 매칭 저장',save,style='Accent.TButton')
        self.button(actions,'닫기',win.destroy)

    def refresh_confirmed_shipments(self):
        if not hasattr(self,'confirmed_shipments'):
            return
        self.confirmed_shipments.delete(*self.confirmed_shipments.get_children())
        for entry in self.service.confirmed_erp_entries(self.erp_ship_day.get()):
            self.confirmed_shipments.insert('', 'end', iid='confirmed-'+entry['id'], values=[
                entry['source'],entry['day'],INTERNAL_TO_CHANNEL.get(entry['channel'],entry['channel']),
                entry['order_no'],entry['recipient'],entry['product'],entry['quantity'],entry['tracking'] or '—',
            ])
        self.root.after_idle(lambda:autosize_tree(self.confirmed_shipments,maximum=300))

    def refresh_erp_shipments(self):
        if not hasattr(self,'erp_shipments'):
            return
        self.erp_shipments.delete(*self.erp_shipments.get_children())
        for shipment in self.service.pending_erp_entries(self.erp_ship_day.get()):
            self.erp_shipments.insert('', 'end', iid=shipment['id'], values=[
                shipment['source'],shipment['day'],shipment['order_no'],shipment['recipient'],shipment['code'],shipment['product'],
                shipment['quantity'],f"{int(Decimal(shipment['amount'])):,}" if shipment['amount'] else '미매칭',
            ],tags=('review',) if shipment.get('issue') else ())
        self.erp_shipments.tag_configure('review',foreground='#BE123C',background='#FFF1F2')
        self.root.after_idle(lambda:autosize_tree(self.erp_shipments,maximum=320))

    def match_erp_amount(self):
        shipment_id=self.selected(self.erp_shipments)[0]
        shipment=next(row for row in self.service.pending_erp_entries() if row['id']==shipment_id)
        value=simpledialog.askstring(
            'ERP 금액 매칭',
            f"주문번호: {shipment['order_no']}\n품목: {shipment['product']}\n출고수량: {shipment['quantity']}\n\n이카운트에 반영할 총금액을 입력하세요.",
            initialvalue=shipment['amount'],parent=self.root,
        )
        if value is None:return
        self.service.set_erp_amount(shipment_id,value.replace(',',''))
        self.refresh_erp_shipments()

    def edit_erp_set(self):
        entry_id=self.selected(self.erp_shipments)[0]
        row=self.service.smartstore_erp_row(entry_id)
        if not row:
            raise ValueError('세트 구성 수정은 스마트스토어 ERP 입력 건에서 사용할 수 있습니다.')
        data=row['data']
        win=tk.Toplevel(self.root);win.title('스마트스토어 ERP 세트 분리');win.geometry('1120x620');win.transient(self.root);win.grab_set()
        ttk.Label(win,text='스마트스토어 ERP 세트 분리',font=(self.font_family,17,'bold'),padding=(16,14)).pack(anchor='w')
        ttk.Label(win,text=f"{data.get('order_no')}  |  {data.get('product')} / {data.get('option')}",padding=(16,0)).pack(anchor='w')
        ttk.Label(win,text='첫 구성품은 주문 총금액에서 부속품 단가를 뺀 금액으로 자동 계산됩니다.',foreground='#64748B',padding=(16,6)).pack(anchor='w')
        grid=ttk.Frame(win,padding=16);grid.pack(fill='both',expand=True)
        labels=['ERP 품목코드','품목명','부속품 단가','출하창고','거래처코드']
        for column,label in enumerate(labels):ttk.Label(grid,text=label).grid(row=0,column=column,padx=4,pady=6,sticky='w')
        entries=[]
        customer=self.service.channel_customer_code('리큐엠_스마트스토어')
        def add_row(component=None):
            component=component or {}
            index=len(entries)
            quantity=max(1,int(component.get('quantity') or data.get('quantity') or 1))
            unit='0' if index==0 else str(int(Decimal(component.get('amount','0'))/Decimal(quantity)))
            values={
                'code':tk.StringVar(value=component.get('code','')),
                'name':tk.StringVar(value=component.get('name','')),
                'unit_amount':tk.StringVar(value=unit),
                'warehouse':tk.StringVar(value=component.get('warehouse',self.service.settings['warehouse'])),
                'customer':tk.StringVar(value=component.get('customer',customer)),
            }
            widgets=[]
            for column,key in enumerate(('code','name','unit_amount','warehouse','customer')):
                widget=ttk.Entry(grid,textvariable=values[key],width=(24 if key in ('code','customer') else 34 if key=='name' else 13))
                widget.grid(row=index+1,column=column,padx=4,pady=4,sticky='ew');widgets.append(widget)
            entries.append((values,widgets))
        for component in row['components']:add_row(component)
        if not entries:add_row()
        def remove_row():
            if len(entries)>1:
                _,widgets=entries.pop()
                for widget in widgets:widget.destroy()
        def save():
            components=[]
            for values,_ in entries:
                item={key:value.get().strip() for key,value in values.items()}
                item.update({'logistics_code':item['code'],'quantity':'1'})
                components.append(item)
            self.service.set_smartstore_erp_components(entry_id,components)
            win.destroy();self.refresh_erp_shipments();self.refresh_confirmed_shipments()
        actions=ttk.Frame(win,padding=16);actions.pack(fill='x')
        self.button(actions,'구성품 추가',lambda:add_row())
        self.button(actions,'마지막 구성품 삭제',remove_row,style='Danger.TButton')
        self.button(actions,'세트 구성 저장',save,style='Accent.TButton')
        self.button(actions,'닫기',win.destroy)

    def erp(self):
        path=self.save_path('ERP_'+self.voucher.get()+'.xlsx')
        if path:
            self.service.export_erp(self.voucher.get(),self.through.get(),path);self.refresh()
            messagebox.showinfo('ERP 파일 생성','ERP 파일을 저장했습니다. 사이트 등록 후 출력 이력에서 등록 확인을 표시하세요.')

    def reexport(self):
        key=self.selected(self.history)[0];path=self.save_path(key+'.xlsx')
        if path:self.service.reexport(key,path)

    def registered(self):
        key=self.selected(self.history)[0]
        if messagebox.askyesno('ERP 등록 확인','ERP 사이트에 해당 파일을 정상 등록했습니까?'):
            self.service.mark_registered(key);self.refresh()

    def reload_settings(self):
        self.service.settings=settings_at(self.service.folder)
        self.load_matching_profile()
        messagebox.showinfo('설정','설정을 다시 읽었습니다. 기존 출고 구성과 파일은 변경되지 않습니다.')

    def backup(self):
        path=filedialog.asksaveasfilename(initialfile=f'reqm_backup_{date.today()}.sqlite3',defaultextension='.sqlite3')
        if path:self.service.backup(path);messagebox.showinfo('백업','DB 백업 완료. settings.json도 함께 보관하세요.')


def main():
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
    data=Path(os.environ.get('REQM_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'REQM-Local')))
    try:
        from tkinterdnd2 import TkinterDnD
        root=TkinterDnD.Tk()
    except (ImportError, tk.TclError):
        root=tk.Tk()
    try:
        service=Operations(data,reference_data_path(base))
        Desktop(root,service)
        root.mainloop()
        service.close()
    except Exception as exc:
        messagebox.showerror('시작 오류',str(exc));root.destroy();raise

