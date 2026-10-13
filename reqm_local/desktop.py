from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
import ctypes
import calendar
import tkinter.font as tkfont
from difflib import SequenceMatcher
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import ttk, filedialog, messagebox, simpledialog

from .files import (
    ORDER_COLUMNS, RESULT_COLUMNS, analyze_order_columns, choice_column_index,
    column_choice, identifier, profile_column_choices, read_rows, related_column_choices,
    reference_data_path, sample_header_names, settings_at, workbook_bytes, wekeep_workbook_bytes,
)
from .service import Operations
from .ui_helpers import (
    autosize_tree, bind_desktop_drag, bind_tree_sorting, bind_tree_column_resize, bind_wide_combobox, filter_combobox_choices,
    post_combobox, search_suggestions, hide_combobox_popups,
)
from .profiles import (
    PROFILE_PRESETS, SALES_CHANNELS, MATCHING_CHANNELS, SMARTSTORE_ERP_MAPPING,
    SMARTSTORE_PURCHASE_MAPPING, SMARTSTORE_PURCHASE_CHANNEL,
)
from .column_matching import match_columns
from .shipping import compact
from .esm import download_esm_orders, load_credentials, save_credentials


APP_VERSION = '1.9.34'
COMPLETED_ORDER_STATES = {'출고 요청','부분 출고','출고 완료'}


CHANNEL_TO_INTERNAL = {
    '스마트스토어': '리큐엠_스마트스토어',
    SMARTSTORE_ERP_MAPPING: '리큐엠_스마트스토어_ERP',
    SMARTSTORE_PURCHASE_MAPPING: SMARTSTORE_PURCHASE_CHANNEL,
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


def calendar_month_days(year: int, month: int) -> list[list[int]]:
    return calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)


def matching_header_row_number(value) -> int:
    """Read either a plain row number or a ``2 · preview`` selector value."""
    match=re.match(r'^\s*(\d+)',str(value or ''))
    if not match or int(match.group(1)) < 1:
        raise ValueError('헤더 행 번호를 올바르게 입력하세요.')
    return int(match.group(1))


def amount_split_totals(total, values):
    """Return the order total, entered sum, and live difference for split amounts."""
    try:
        expected=Decimal(str(total or '0').replace(',','').strip() or '0')
        entered=sum(
            (Decimal(str(value or '').replace(',','').strip() or '0') for value in values),
            Decimal('0'),
        )
    except InvalidOperation:
        return None
    return expected,entered,entered-expected


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
        style.configure('Channel.TButton', padding=(9,3), background='#FFFFFF', foreground='#334155', bordercolor='#E2E8F0', relief='flat')
        style.configure('Complete.Channel.TButton', padding=(9,3), background='#ECFDF3', foreground='#067647', bordercolor='#A6F4C5', relief='flat')
        style.map('Complete.Channel.TButton', background=[('active','#D1FADF')])
        style.configure('Visible.Eye.TButton', padding=(5,3), background='#ECFDF3', foreground='#047857', bordercolor='#A6F4C5', relief='flat')
        style.configure('Hidden.Eye.TButton', padding=(5,3), background='#F1F5F9', foreground='#94A3B8', bordercolor='#E2E8F0', relief='flat')
        for compact_style in ('Compact.TButton','Compact.Accent.TButton','Compact.Quiet.TButton','Compact.Danger.TButton'):
            style.configure(compact_style,padding=(7,4),font=(f,9),width=0)
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
        self.cloud_status = tk.StringVar(value='로컬 DB 저장')
        tk.Label(
            badge_box,textvariable=self.cloud_status,
            fg='#166534',bg='#DCFCE7',activebackground='#BBF7D0',relief='flat',borderwidth=0,
            font=(f,9,'bold'),padx=11,pady=6,
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
        self.order_day = tk.StringVar(value=date.today().isoformat())
        # Registration, request creation and review share one selected work day.
        self.today = self.order_day
        self.request_excluded_channels=set(service.settings.get('request_excluded_channels',[]))
        self.erp_excluded_channels=set(service.settings.get('erp_excluded_channels',[]))
        self.request_exclusion_text=tk.StringVar(value=self.exclusion_label(self.request_excluded_channels))
        self.erp_exclusion_text=tk.StringVar(value=self.exclusion_label(self.erp_excluded_channels))
        self.request_warehouse=tk.StringVar(value='전체창고')
        self.workspace_tabs = tabs
        self.order_frame = ttk.Frame(tabs,padding=12)
        result_frame = ttk.Frame(tabs,padding=16)
        history_frame = ttk.Frame(tabs,padding=12)
        settings_page = ttk.Frame(tabs,padding=8)
        for frame,title in [(self.order_frame,'주문 · 출고요청'),(result_frame,'실제출고'),(history_frame,'출력 이력'),(settings_page,'설정 · 백업')]:
            tabs.add(frame,text=title)
        self.settings_tabs = ttk.Notebook(settings_page,style='Workspace.TNotebook')
        self.settings_tabs.pack(fill='both',expand=True)
        settings_frame = ttk.Frame(self.settings_tabs,padding=16)
        matching_frame = self.matching_frame = ttk.Frame(self.settings_tabs,padding=18)
        login_frame = ttk.Frame(self.settings_tabs,padding=16)
        for frame,title in [(settings_frame,'설정 · 백업'),(matching_frame,'매칭 설정'),(login_frame,'주문 수집')]:
            self.settings_tabs.add(frame,text=title)
        from .closed_mall_ui import ClosedMallPanel
        self.closed_mall_panel = ClosedMallPanel(login_frame,self.root)
        nav_items = [('▣  주문 · 출고요청',0),('↗  실제출고',1),('◫  출력 이력',2),('⚙  설정 · 백업',3)]
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
        channels = ttk.LabelFrame(self.order_frame,text='판매처 주문 파일',padding=(8,4))
        channels.pack(fill='x',pady=(0,5))
        channel_day = ttk.Frame(channels)
        channel_day.grid(row=0,column=0,columnspan=6,sticky='ew',padx=4,pady=(0,3))
        ttk.Label(channel_day,text='작업일',font=(self.font_family,10,'bold')).pack(side='left')
        self.date_picker(channel_day,self.order_day,'주문 등록·출고 조회일').pack(side='left',padx=6)
        ttk.Label(channel_day,text='선택 날짜에 등록했거나 출고한 주문만 표시됩니다.',foreground='#64748B').pack(side='left',padx=10)
        self.channels_expanded = True
        self.channel_toggle = ttk.Button(channel_day,text='판매처 접기 ▴',style='Compact.TButton',command=self.toggle_channel_panel)
        self.channel_toggle.pack(side='right',padx=4)
        self.channel_grid = ttk.Frame(channels)
        self.channel_grid.grid(row=1,column=0,columnspan=6,sticky='ew')
        self.channel_status = {}
        self.channel_visibility = {channel:True for channel in SALES_CHANNELS}
        self.channel_eye_text = {}
        self.channel_eye_buttons = {}
        self.channel_buttons = {}
        for index, channel in enumerate(SALES_CHANNELS):
            status = tk.StringVar(value=f'□  {channel}')
            self.channel_status[channel] = status
            eye_text=tk.StringVar(value='👁')
            self.channel_eye_text[channel]=eye_text
            cell=ttk.Frame(self.channel_grid)
            cell.grid(row=index // 6,column=index % 6,sticky='ew',padx=3,pady=2)
            button = ttk.Button(
                cell, textvariable=status,
                command=lambda selected=channel:self.safe(lambda:self.import_channel(selected)),
                style='Channel.TButton',
            )
            self.channel_buttons[channel] = button
            button.pack(side='left',fill='x',expand=True)
            eye=ttk.Button(
                cell,textvariable=eye_text,width=3,style='Visible.Eye.TButton',
                command=lambda selected=channel:self.toggle_channel_visibility(selected),
            )
            eye.pack(side='left',padx=(3,0))
            self.channel_eye_buttons[channel]=eye
        for column in range(6):
            self.channel_grid.columnconfigure(column,weight=1)
        ttk.Label(
            channels,
            text='판매처: 파일 입력 · ✓ 입력 완료 · 눈 아이콘: 목록 표시 · 표 제목 경계를 드래그하면 열 너비가 바뀝니다.',
            foreground='#64748B',
        ).grid(row=2,column=0,columnspan=6,sticky='w',padx=4,pady=(3,0))
        self.drop_zone = tk.Label(
            self.order_frame,
            text='↓  주문 파일을 여기에 드래그하세요   ·   XLSX / XLS / CSV',
            bg='#172033', fg='#C7FF4A', font=(self.font_family,11,'bold'),
            padx=12, pady=5, cursor='hand2',
        )
        self.drop_zone.pack(fill='x',pady=(0,5))
        self.drop_zone.bind('<Button-1>',lambda _event:self.safe(self.import_files))
        self.setup_file_drop(self.drop_zone)
        workflow = ttk.Frame(self.order_frame)
        workflow.pack(fill='x',pady=(0,5))
        organize = ttk.Frame(workflow,padding=(2,1))
        organize.pack(fill='x',pady=(0,2))
        self.compact_button(organize,'＋ 주문 파일 입력',self.import_files,style='Accent.TButton')
        self.compact_button(organize,'상품 매칭',self.mapping)
        self.compact_button(organize,'출하창고 입력',self.change_order_warehouse,style='Quiet.TButton')
        self.compact_button(organize,'미매칭 검토',self.batch_matching_review)
        self.compact_button(organize,'배송정보 수정',self.delivery)
        self.compact_button(organize,'강제 승인',self.force_shipping_approval,style='Quiet.TButton')
        self.compact_button(organize,'삭제',self.delete_orders,style='Danger.TButton')
        release = ttk.Frame(workflow,padding=(2,1))
        release.pack(fill='x')
        ttk.Label(release,text='출고요청일').pack(side='left',padx=(0,4))
        ttk.Entry(release,textvariable=self.today,width=11).pack(side='left')
        ttk.Combobox(
            release,textvariable=self.request_warehouse,
            values=['전체창고','100 본사창고','300 위킵창고'],state='readonly',width=14,
        ).pack(side='left',padx=4)
        ttk.Button(release,style='Compact.TButton',textvariable=self.request_exclusion_text,command=lambda:self.safe(lambda:self.choose_channel_exclusions('request'))).pack(side='left',padx=4)
        self.compact_button(release,'사전검사',self.preflight_review,style='Quiet.TButton')
        self.compact_button(release,'선택 주문 파일 생성',self.request,style='Accent.TButton')
        self.search = tk.StringVar()
        self.filter = tk.StringVar(value='전체')
        self.unmatched_first = tk.BooleanVar(value=False)
        self.hide_completed_orders = tk.BooleanVar(value=False)
        self.hide_completed_text = tk.StringVar(value='출고 완료건 제외 · 꺼짐')
        self.order_counts = tk.StringVar(value='전체 0건 · 미매칭 0건')
        filters = ttk.Frame(self.order_frame)
        filters.pack(fill='x',pady=(0,3))
        ttk.Label(filters,text='주문 검색',font=(self.font_family,10,'bold')).pack(side='left')
        ttk.Entry(filters,textvariable=self.search,width=26).pack(side='left',padx=8)
        ttk.Label(filters,textvariable=self.order_counts,foreground='#475569',font=(self.font_family,9,'bold')).pack(side='left',padx=(0,10))
        ttk.Combobox(filters,textvariable=self.filter,values=['전체','중복 주문','검토 필요','출고 준비','출고 요청','부분 출고','출고 완료'],state='readonly',width=14).pack(side='left')
        ttk.Checkbutton(filters,text='미매칭 상단',variable=self.unmatched_first,command=self.refresh_orders).pack(side='left',padx=(8,0))
        self.compact_button(filters,'출고 준비 전체 선택',self.select_ready,style='Quiet.TButton')
        ttk.Button(filters,textvariable=self.hide_completed_text,command=self.toggle_completed_orders,style='Compact.Quiet.TButton').pack(side='left',padx=(4,0))
        self.search.trace_add('write',self.on_search_changed)
        self.filter.trace_add('write',lambda *_:self.refresh_orders())
        self.search_suggestion_bar = ttk.Frame(self.order_frame)
        self.search_suggestion_bar.pack(fill='x',padx=(44,0),pady=(0,4))
        self.detail = tk.StringVar(value='주문을 선택하면 구성품을 확인할 수 있습니다. Ctrl/Shift로 여러 주문을 선택하세요.')
        ttk.Label(self.order_frame,textvariable=self.detail,wraplength=1200,padding=(4,2),foreground='#64748B').pack(fill='x')
        self.table = self.tree(
            self.order_frame,
            ['판매처','주문번호','이름','주소','연락처','상품명','매칭품목','출하창고','진행상태','작업구분'],
            [125,155,110,330,135,300,280,110,95,120],
        )
        self.table._reqm_minimum_widths=dict(zip(self.table['columns'],[110,150,90,280,125,260,240,110,95,100]))
        layout_path=self.service.folder/'order_table_layout.json'
        try:
            saved=json.loads(layout_path.read_text(encoding='utf-8'))
            if not isinstance(saved,dict):saved={}
        except (OSError,ValueError):saved={}
        bind_tree_column_resize(self.table,saved,self.save_order_column_widths)
        self.order_day.trace_add('write',lambda *_:self.refresh_orders_for_day())
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
        self.erp_ship_from = tk.StringVar(value=date.today().isoformat())
        self.erp_ship_through = tk.StringVar(value=date.today().isoformat())
        self.erp_ship_customer = tk.StringVar(value='전체 거래처')
        self.erp_ship_day = tk.StringVar(value=date.today().isoformat())
        self.erp_amount_from = tk.StringVar(value=date.today().isoformat())
        self.erp_amount_through = tk.StringVar(value=date.today().isoformat())
        result_tabs.add(result_input,text='1  출고건 확인')
        result_tabs.add(amount_frame,text='2  금액 매칭 및 세트 분리')
        result_tabs.add(esm_frame,text='2-1  옥션/지마켓 ERP전환')
        result_tabs.add(erp_frame,text='3  ERP 파일 생성 및 다운로드')
        tracking_frame = ttk.Frame(result_tabs,padding=20)
        result_tabs.add(tracking_frame,text='4  위킵 송장 가져오기')
        from .tracking_ui import TrackingPanel
        self.tracking_panel = TrackingPanel(self,tracking_frame)
        ttk.Label(result_input,text='당일 출고건 확인',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(result_input,text='선택한 날짜의 출고건을 불러온 뒤, 이번 ERP Excel에 적용할 창고와 품목만 변경할 수 있습니다.',foreground='#64748B').pack(anchor='w',pady=(4,18))
        confirmed_line=ttk.Frame(result_input);confirmed_line.pack(fill='x',pady=(0,10))
        ttk.Label(confirmed_line,text='조회 기간').pack(side='left')
        self.date_picker(confirmed_line,self.erp_ship_from,'실제 출고 조회 시작일').pack(side='left',padx=6)
        ttk.Label(confirmed_line,text='~').pack(side='left')
        self.date_picker(confirmed_line,self.erp_ship_through,'실제 출고 조회 종료일').pack(side='left',padx=6)
        ttk.Label(confirmed_line,text='거래처').pack(side='left',padx=(12,4))
        self.erp_ship_customer_box=ttk.Combobox(
            confirmed_line,textvariable=self.erp_ship_customer,state='readonly',width=18,values=['전체 거래처'],
        )
        self.erp_ship_customer_box.pack(side='left',padx=(0,6))
        self.erp_ship_customer_box.bind('<<ComboboxSelected>>',lambda _event:self.safe(self.refresh_confirmed_shipments))
        self.button(confirmed_line,'기간 조회',self.refresh_actual_erp_day,style='Accent.TButton')
        result_card = ttk.LabelFrame(result_input,text='입력 파일',padding=18)
        result_card.pack(fill='x')
        ttk.Label(result_card,text='일반 판매처는 출고요청 기준으로 불러오며, 스마트스토어는 전용 파일을 입력합니다.',foreground='#64748B').pack(anchor='w',pady=(0,12))
        result_actions = ttk.Frame(result_card);result_actions.pack(fill='x')
        self.button(result_actions,'당일 출고건 불러오기',self.auto_results,style='Accent.TButton')
        self.button(result_actions,'출하 창고 변경',self.change_shipment_warehouse,style='Quiet.TButton')
        self.button(result_actions,'품목 변경',self.change_shipment_item,style='Quiet.TButton')
        self.button(result_actions,'스마트스토어 출고파일',self.smartstore_erp_results,style='Accent.TButton')
        self.button(result_actions,'구매확정파일 입력',self.smartstore_purchase_results,style='Accent.TButton')
        self.button(result_actions,'선택 주문 삭제',self.delete_confirmed_shipments,style='Danger.TButton')
        self.confirmed_shipments = self.tree(result_input,['구분','출고일','판매처','주문번호','이름','ERP 품목코드','ERP 품목명','출하창고','수량','송장번호'],[125,105,130,150,100,155,240,95,65,140])
        ttk.Label(amount_frame,text='금액 매칭 및 세트 분리',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(amount_frame,text='일반 출고의 금액 분리 대상과 스마트스토어 미매칭·세트 주문을 함께 표시합니다.',foreground='#64748B').pack(anchor='w',pady=(4,16))
        amount_line = ttk.Frame(amount_frame); amount_line.pack(fill='x',pady=(0,10))
        ttk.Label(amount_line,text='조회 기간').pack(side='left')
        self.date_picker(amount_line,self.erp_amount_from,'금액 매칭 조회 시작일').pack(side='left',padx=6)
        ttk.Label(amount_line,text='~').pack(side='left')
        self.date_picker(amount_line,self.erp_amount_through,'금액 매칭 조회 종료일').pack(side='left',padx=6)
        self.button(amount_line,'기간 조회',self.refresh_erp_shipments,style='Accent.TButton')
        self.button(amount_line,'스마트스토어 상품·세트 매칭',self.edit_erp_set,style='Quiet.TButton')
        self.button(amount_line,'선택 일반출고 금액 수정',self.split_order_amount,style='Accent.TButton')
        self.erp_shipments = self.tree(amount_frame,['실제 출고일','판매처','주문번호','이름','구성품 수','주문 금액','상품명','상품옵션','현재 구성품별 금액'],[110,120,160,110,85,120,260,220,520])
        self.erp_shipments.bind('<Double-1>',lambda _event:self.safe(self.open_amount_split_action))
        self.erp_ship_from.trace_add('write',lambda *_:self.refresh_confirmed_shipments())
        self.erp_ship_through.trace_add('write',lambda *_:self.refresh_confirmed_shipments())
        self.esm_start_day = tk.StringVar(value=date.today().isoformat())
        self.esm_end_day = tk.StringVar(value=date.today().isoformat())
        self.esm_view_from = tk.StringVar(value=date.today().isoformat())
        self.esm_view_through = tk.StringVar(value=date.today().isoformat())
        self.esm_show_all = False
        self.esm_user_id = tk.StringVar()
        self.esm_password = tk.StringVar()
        self.esm_progress = tk.StringVar(value='조회 기간과 로그인 정보를 확인한 뒤 자동 다운로드를 실행하세요.')
        saved_user,saved_password=load_credentials(self.service.folder/'esm_credentials.dat')
        self.esm_user_id.set(saved_user);self.esm_password.set(saved_password)
        ttk.Label(esm_frame,text='옥션/지마켓 ESM PLUS ERP전환',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(esm_frame,text='A/G 전체에서 주문일과 배송상태별 파일을 내려받아 옥션·지마켓 ERP 행으로 변환합니다.',foreground='#64748B').pack(anchor='w',pady=(4,14))
        esm_card=ttk.LabelFrame(esm_frame,text='ESM PLUS 자동 수집',padding=14);esm_card.pack(fill='x')
        form=ttk.Frame(esm_card);form.pack(fill='x')
        for label,var in [('시작 주문일',self.esm_start_day),('종료 주문일',self.esm_end_day)]:
            ttk.Label(form,text=label).pack(side='left',padx=(8,4))
            self.date_picker(form,var,label).pack(side='left')
        for label,var,secret in [('아이디',self.esm_user_id,False),('비밀번호',self.esm_password,True)]:
            ttk.Label(form,text=label).pack(side='left',padx=(8,4))
            ttk.Entry(form,textvariable=var,width=22,show='●' if secret else '').pack(side='left')
        self.button(form,'로그인 정보 보호 저장',self.save_esm_login,style='Quiet.TButton')
        self.button(form,'ESM PLUS 자동 다운로드',self.download_esm,style='Accent.TButton')
        self.button(form,'ESM만 ERP 파일 생성',self.export_esm_erp,style='Accent.TButton')
        self.button(form,'파일 직접 추가',self.import_esm_files,style='Quiet.TButton')
        ttk.Label(esm_card,textvariable=self.esm_progress,foreground='#2563EB').pack(anchor='w',padx=8,pady=(10,0))
        esm_actions=ttk.Frame(esm_frame);esm_actions.pack(fill='x',pady=(12,8))
        ttk.Label(esm_actions,text='변환 내역',font=(self.font_family,11,'bold')).pack(side='left')
        ttk.Label(esm_actions,text='조회 기간').pack(side='left',padx=(14,4))
        self.date_picker(esm_actions,self.esm_view_from,'ESM 조회 시작일').pack(side='left')
        ttk.Label(esm_actions,text='~').pack(side='left',padx=3)
        self.date_picker(esm_actions,self.esm_view_through,'ESM 조회 종료일').pack(side='left')
        self.button(esm_actions,'기간 조회',self.show_esm_day,style='Accent.TButton')
        self.button(esm_actions,'전체 내역',self.show_all_esm,style='Quiet.TButton')
        self.button(esm_actions,'선택 상품 매칭',self.edit_esm_set,style='Accent.TButton')
        self.button(esm_actions,'선택 주문 삭제',self.delete_esm_entries,style='Danger.TButton')
        self.button(esm_actions,'목록 새로고침',self.refresh_esm_entries,style='Quiet.TButton')
        self.esm_entries=self.tree(esm_frame,['기준일','판매처','주문번호','상품명','옵션','수량','단가','합계','ERP 품목','상태'],[105,90,145,280,220,65,95,105,170,180])
        self.esm_entries.bind('<Double-1>',lambda _event:self.safe(self.edit_esm_set))
        ttk.Label(erp_frame,text='이카운트 ERP 파일 생성 및 다운로드',font=(self.font_family,18,'bold')).pack(anchor='w')
        ttk.Label(erp_frame,text='출고일 범위의 실제출고·스마트스토어 주문을 만들며, ESM 포함 여부를 선택할 수 있습니다.',foreground='#64748B').pack(anchor='w',pady=(4,18))
        self.erp_from = tk.StringVar(value=date.today().isoformat())
        self.through = tk.StringVar(value=date.today().isoformat())
        self.voucher = tk.StringVar(value=date.today().isoformat())
        self.erp_include_esm = tk.BooleanVar(value=True)
        erp_card = ttk.LabelFrame(erp_frame,text='출력 조건',padding=18);erp_card.pack(fill='x')
        line = ttk.Frame(erp_card); line.pack(anchor='w')
        ttk.Label(line,text='출고일').pack(side='left',padx=6)
        self.date_picker(line,self.erp_from,'출고 시작일').pack(side='left')
        ttk.Label(line,text='~').pack(side='left',padx=5)
        self.date_picker(line,self.through,'출고 종료일').pack(side='left')
        ttk.Label(line,text='ERP 전표일').pack(side='left',padx=(14,6))
        self.date_picker(line,self.voucher,'ERP 전표일').pack(side='left')
        ttk.Checkbutton(line,text='ESM 포함',variable=self.erp_include_esm).pack(side='left',padx=(14,4))
        ttk.Button(line,textvariable=self.erp_exclusion_text,command=lambda:self.safe(lambda:self.choose_channel_exclusions('erp'))).pack(side='left',padx=4)
        self.button(line,'ERP 파일 생성',self.erp,style='Accent.TButton')
        self.button(line,'현재 정보로 ERP 재다운로드',self.download_erp_again,style='Quiet.TButton')
        ttk.Label(erp_card,text='이미 생성한 출고는 제외됩니다. 배송비는 묶음 전체 출고 완료 후 한 번 반영하며, 부가세 포함·10% 과세 기준입니다.',foreground='#64748B',wraplength=1000).pack(anchor='w',pady=(16,0))
        self.history_day=tk.StringVar(value=date.today().isoformat())
        self.history_show_all=True
        history_filters=ttk.Frame(history_frame);history_filters.pack(fill='x',pady=(0,3))
        self.history_search=tk.StringVar()
        ttk.Label(history_filters,text='출력일').pack(side='left',padx=(0,5))
        self.date_picker(history_filters,self.history_day,'출력 이력 날짜').pack(side='left')
        self.button(history_filters,'선택일 조회',self.show_history_day,style='Accent.TButton')
        self.button(history_filters,'전체 이력',self.show_all_history,style='Quiet.TButton')
        ttk.Label(history_filters,text='검색').pack(side='left',padx=(14,5))
        ttk.Entry(history_filters,textvariable=self.history_search,width=34).pack(side='left')
        self.history_search.trace_add('write',lambda *_:self.refresh_history())
        line = ttk.Frame(history_frame); line.pack(fill='x',pady=8)
        self.button(line,'선택 파일 재저장',self.reexport)
        self.button(line,'송장 반영 주문파일 저장',self.export_tracked_order_file,style='Quiet.TButton')
        self.button(line,'비고 수정',self.edit_history_note,style='Quiet.TButton')
        self.button(line,'ERP 등록 확인',self.registered)
        ttk.Label(line,text='생성 파일의 주문 상세를 출력일별로 조회합니다.').pack(side='left',padx=20)
        self.history = self.tree(
            history_frame,
            ['출력일(요일)','출고일','종류','판매처','주문번호','수령인','연락처','판매품목','옵션','매칭품목','수량','금액','송장번호','출하창고','비고','등록','묶음 ID'],
            [120,105,120,130,160,100,125,260,190,260,65,100,150,90,220,90,190],
        )
        self.history.bind('<Double-1>',lambda _event:self.safe(self.edit_history_note))
        ttk.Label(settings_frame,text='모든 주문·매칭·출고·ERP 자료는 이 PC에만 저장됩니다.',font=(self.font_family,16,'bold')).pack(anchor='w',pady=10)
        ttk.Label(settings_frame,text=str(service.folder),wraplength=1100).pack(anchor='w')
        ttk.Label(settings_frame,text='설정 파일에서 판매처별 헤더·계정·파일명 단서와 출력 열 이름을 변경할 수 있습니다.\n주문에 포함된 배송비는 원본의 배송비 합계를 사용합니다. 실제 거래처 규칙을 확인하세요.\nDB는 operations.sqlite3에 저장되며 Supabase 사용량이나 인터넷 연결에 영향을 받지 않습니다.\n전환 전 로컬 캐시는 backups\\supabase-to-local.sqlite3에 한 번 자동 백업됩니다.',wraplength=1100).pack(anchor='w',pady=16)
        line = ttk.Frame(settings_frame); line.pack(anchor='w')
        self.button(line,'설정 파일 열기',lambda:os.startfile(service.folder/'settings.json'))
        self.button(line,'설정 다시 읽기',self.reload_settings)
        self.button(line,'DB 백업',self.backup)
        self.button(line,'저장 폴더 열기',lambda:os.startfile(service.folder))
        item_box=ttk.LabelFrame(settings_frame,text='ERP 품목코드 · 매칭품목명 관리',padding=12)
        item_box.pack(fill='both',expand=True,pady=(16,0))
        item_actions=ttk.Frame(item_box);item_actions.pack(fill='x',pady=(0,8))
        ttk.Label(item_actions,text='출고 프로그램에서 사용 중인 품목만 표시합니다. 코드와 품목명은 출고 기준을 따릅니다.',foreground='#64748B').pack(side='left')
        self.item_name_tree=self.tree(item_box,['ERP 품목코드','매칭품목명'],[300,520])
        tk.Label(content,text='LOCAL DATABASE   ·   날짜 YYYY-MM-DD   ·   REQM FLOW',bg='#F4F7FB',fg='#94A3B8',font=(self.font_family,8,'bold'),pady=6).pack(fill='x')
        self.refresh()
        self.root.protocol('WM_DELETE_WINDOW',self.hide_to_tray)
        self.root.bind('<Destroy>',self.on_root_destroy,add='+')
        self.setup_tray()
        self.root.after(4000,self.check_for_source_update)
        if getattr(sys,'frozen',False):
            self.root.after(1800,self.check_remote_update)

    @staticmethod
    def exclusion_label(channels):
        return '판매처 제외 없음' if not channels else f'판매처 제외 {len(channels):,}개'

    def choose_channel_exclusions(self, scope):
        if scope not in ('request','erp'):
            raise ValueError('판매처 제외 범위를 확인하세요.')
        current=set(self.request_excluded_channels if scope=='request' else self.erp_excluded_channels)
        choices=list(SALES_CHANNELS)
        if scope=='erp':
            choices.extend(channel for channel in ('옥션','지마켓') if channel not in choices)
        win=tk.Toplevel(self.root)
        win.title('출고요청 판매처 제외' if scope=='request' else '실제출고 ERP 판매처 제외')
        win.geometry('650x500');win.transient(self.root);win.grab_set()
        ttk.Label(win,text='파일에서 제외할 판매처 선택',font=(self.font_family,16,'bold'),padding=(18,16)).pack(anchor='w')
        ttk.Label(
            win,
            text='체크한 판매처는 이번 이후 출력에서 빠지며, 체크를 해제하면 다시 포함됩니다.',
            foreground='#64748B',padding=(18,0),
        ).pack(anchor='w')
        body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
        variables={channel:tk.BooleanVar(value=channel in current) for channel in choices}
        for index,channel in enumerate(choices):
            ttk.Checkbutton(body,text=channel,variable=variables[channel]).grid(
                row=index//3,column=index%3,sticky='w',padx=(0,28),pady=7,
            )
        for column in range(3):body.columnconfigure(column,weight=1)
        def clear():
            for variable in variables.values():variable.set(False)
        def save():
            selected={channel for channel,variable in variables.items() if variable.get()}
            key='request_excluded_channels' if scope=='request' else 'erp_excluded_channels'
            self.service.settings[key]=sorted(selected)
            self.service._write_settings()
            if scope=='request':
                self.request_excluded_channels=selected
                self.request_exclusion_text.set(self.exclusion_label(selected))
            else:
                self.erp_excluded_channels=selected
                self.erp_exclusion_text.set(self.exclusion_label(selected))
            win.destroy()
        actions=ttk.Frame(win,padding=14);actions.pack(fill='x')
        self.button(actions,'전체 포함',clear,style='Quiet.TButton')
        self.button(actions,'취소',win.destroy,style='Quiet.TButton')
        self.button(actions,'제외 설정 저장',save,style='Accent.TButton')

    def date_picker(self, parent, variable, title='날짜 선택'):
        holder=ttk.Frame(parent)
        ttk.Entry(holder,textvariable=variable,width=11,state='readonly').pack(side='left')
        ttk.Button(holder,text='▾',width=3,command=lambda:self.open_calendar(variable,title)).pack(side='left',padx=(2,0))
        return holder

    def open_calendar(self, variable, title='날짜 선택'):
        try:selected=date.fromisoformat(variable.get())
        except ValueError:selected=date.today()
        win=tk.Toplevel(self.root);win.title(title);win.transient(self.root);win.resizable(False,False);win.grab_set()
        body=ttk.Frame(win,padding=12);body.pack(fill='both',expand=True)
        state={'year':selected.year,'month':selected.month}
        heading=ttk.Frame(body);heading.pack(fill='x',pady=(0,8))
        grid=ttk.Frame(body);grid.pack()
        month_text=tk.StringVar()
        ttk.Button(heading,text='‹',width=3,command=lambda:move(-1)).pack(side='left')
        ttk.Label(heading,textvariable=month_text,font=(self.font_family,11,'bold'),anchor='center').pack(side='left',fill='x',expand=True,padx=12)
        ttk.Button(heading,text='›',width=3,command=lambda:move(1)).pack(side='right')
        def choose(day):
            variable.set(date(state['year'],state['month'],day).isoformat());win.destroy()
        def draw():
            for child in grid.winfo_children():child.destroy()
            month_text.set(f"{state['year']}년 {state['month']}월")
            for column,label in enumerate(('일','월','화','수','목','금','토')):
                ttk.Label(grid,text=label,width=4,anchor='center',foreground='#64748B').grid(row=0,column=column,pady=(0,4))
            for row,week in enumerate(calendar_month_days(state['year'],state['month']),start=1):
                for column,day_value in enumerate(week):
                    if day_value:
                        style='Accent.TButton' if date(state['year'],state['month'],day_value)==selected else 'Quiet.TButton'
                        ttk.Button(grid,text=str(day_value),width=4,style=style,command=lambda value=day_value:choose(value)).grid(row=row,column=column,padx=1,pady=1)
        def move(delta):
            month=state['month']+delta
            state['year']+=(month-1)//12;state['month']=(month-1)%12+1;draw()
        draw();win.update_idletasks()
        win.geometry(f'+{self.root.winfo_rootx()+180}+{self.root.winfo_rooty()+160}')

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
            if not messagebox.askyesno('업데이트',f'REQM FLOW {version} 실행파일만 교체할까요?\n저장된 주문·설정·내부 파일은 그대로 유지됩니다.',parent=self.root):
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
        self.closed_mall_panel.shutdown()
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
        self.matching_header_box=ttk.Combobox(
            header_controls,textvariable=self.matching_header_row,values=['1'],width=34,state='normal',
        )
        self.matching_header_box.pack(side='left')
        bind_wide_combobox(self.matching_header_box)
        ttk.Button(header_controls,text='행 적용',command=lambda:self.safe(self.apply_sample_headers)).pack(side='left',padx=6)
        ttk.Button(identity,text='파일 추가 · 1차 자동 매칭',style='Accent.TButton',command=lambda:self.safe(self.load_matching_sample)).grid(row=3,column=2,sticky='w',padx=8,pady=(10,5))
        ttk.Label(identity,textvariable=self.matching_sample,foreground='#64748B').grid(row=3,column=3,sticky='w',pady=(10,5))
        ttk.Label(identity,textvariable=self.matching_analysis,foreground='#2563EB').grid(row=4,column=1,columnspan=3,sticky='w',pady=(2,5))
        ttk.Label(identity,text='엑셀 비밀번호').grid(row=5,column=0,sticky='w',padx=(0,12),pady=5)
        ttk.Entry(identity,textvariable=self.matching_password,show='•').grid(row=5,column=1,sticky='ew',pady=5)
        ttk.Label(identity,text='이 PC의 로컬 설정 파일에 저장됩니다.',foreground='#64748B').grid(row=5,column=2,columnspan=2,sticky='w',padx=8)
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
        self.matching_header_row.set('1')
        self.matching_header_box.configure(values=['1'])
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
        header_rows=[]
        for index,row in enumerate(rows[:30]):
            cells=[identifier(value) for value in row if identifier(value)]
            preview=' | '.join(value[:28] for value in cells[:6]) or '(빈 행)'
            if len(preview)>110:preview=preview[:107]+'…'
            header_rows.append(f'{index+1} · {preview}')
        self.matching_header_box.configure(values=header_rows)
        self.matching_header_row.set(header_rows[best])
        self.matching_sample.set(Path(path).name)
        if not self.matching_filename.get().strip():
            self.matching_filename.set(Path(path).name)
        self.apply_sample_headers(force_auto=True)

    def apply_sample_headers(self, force_auto=False):
        if self.sample_rows is None:
            return
        try:
            row_index = matching_header_row_number(self.matching_header_row.get())-1
            row = self.sample_rows[row_index]
        except (ValueError, IndexError):
            raise ValueError('헤더 행 번호를 올바르게 입력하세요.') from None
        profile = self.matching_profile(self.selected_matching_channel()) or {}
        preset = self.matching_preset(self.selected_matching_channel())
        # Once a sample is loaded, the selected row is the sole source of the
        # visible columns. Saved indexes belong to the previous file and can
        # silently point at unrelated columns in a changed/new marketplace
        # format. The explicitly selected row also prevents report titles in
        # rows above it from being mistaken for selectable Excel columns.
        self.sample_headers = sample_header_names(self.sample_rows, row_index, include_previous=False)
        choices = ['미사용']+[column_choice(index, header) for index,header in enumerate(self.sample_headers) if header]
        self.mapping_choice_values = choices
        aliases = {}
        for field in MAPPING_FIELD_ORDER:
            values, _saved_index = self.matching_field_config(profile, preset, field)
            aliases[field] = list(dict.fromkeys([*values, *ORDER_COLUMNS[field]]))
        matched=match_columns(self.sample_headers,aliases)
        automatic = analyze_order_columns(self.sample_headers, self.sample_rows[row_index+1:row_index+21],aliases)
        for field, box in self.mapping_boxes.items():
            box.configure(values=related_column_choices(field,choices))
            selected_index = automatic.get(field)
            if isinstance(selected_index, int) and 0 <= selected_index < len(self.sample_headers):
                self.mapping_vars[field].set(column_choice(selected_index, self.sample_headers[selected_index]))
                method=matched.get(field,{}).get('method')
                self.mapping_status_vars[field].set(method or '내용추정')
            else:
                self.mapping_vars[field].set('미사용')
                self.mapping_status_vars[field].set('미사용')
        exact=sum(m['method']=='일치' for m in matched.values())
        near=sum(m['method']=='근사' for m in matched.values())
        visible_columns=sum(bool(header) for header in self.sample_headers)
        self.matching_analysis.set(
            f'{row_index+1}행 기준 · 실제 열 {visible_columns}개 · 1순위 일치 {exact}개 · '
            f'2순위 근사 {near}개 · 샘플 추정 {max(0,len(automatic)-len(matched))}개. '
            '미매칭 항목도 실제 열 목록에서 직접 선택할 수 있습니다.'
        )

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
            'header_row': matching_header_row_number(self.matching_header_row.get()),
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
        messagebox.showinfo('매칭 설정 저장',f'{channel}의 파일명과 열 설정을 이 PC에 저장했습니다.',parent=self.root)

    def toggle_channel_panel(self):
        self.channels_expanded=not self.channels_expanded
        if self.channels_expanded:
            self.channel_grid.grid()
        else:
            self.channel_grid.grid_remove()
        self.channel_toggle.configure(text='판매처 접기 ▴' if self.channels_expanded else '판매처 펼치기 ▾')

    def save_order_column_widths(self, widths):
        path=self.service.folder/'order_table_layout.json'
        temporary=path.with_suffix('.json.tmp')
        try:
            temporary.write_text(json.dumps(widths,ensure_ascii=False),encoding='utf-8')
            os.replace(temporary,path)
        except OSError:
            pass

    def compact_button(self,parent,label,fn,style='TButton'):
        self.button(parent,label,fn,style='Compact.'+style)

    def button(self,parent,label,fn,style='TButton'):
        ttk.Button(parent,text=label,style=style,command=lambda:self.safe(fn)).pack(side='left',padx=4)

    def safe(self,fn):
        try:
            fn()
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
        bind_tree_sorting(tree)
        return tree

    def refresh_orders(self):
        self.rows={o['id']:o for o in self.service.orders()}
        self.table.delete(*self.table.get_children())
        try:selected_day=date.fromisoformat(self.order_day.get()).isoformat()
        except ValueError:selected_day=''
        ordered=list(self.rows.items())
        if self.unmatched_first.get():
            ordered.sort(key=lambda item:item[1]['state']!='검토 필요')
        shown=0
        for key,o in ordered:
            d=o['data']
            legacy_pending=not o.get('activity_days') and o['state'] in ('검토 필요','출고 준비')
            if selected_day and selected_day not in o.get('activity_days',[]) and not legacy_pending:
                continue
            channel = INTERNAL_TO_CHANNEL.get(d['channel'],d['channel'])
            if not self.channel_visibility.get(channel,True):
                continue
            if self.hide_completed_orders.get() and o['state'] in COMPLETED_ORDER_STATES:
                continue
            duplicate = '강제 승인' if d.get('force_shipping_approved') else (f"중복 {o['duplicate_count']}건" if o['duplicate_count'] > 1 else '')
            source_product=d.get('source_product',d['product']);source_option=d.get('source_option',d['option'])
            converted=' / '.join(
                self.service.item_name(c.get('code'),c.get('name'))
                for c in o['components'] if c.get('code') or c.get('name')
            )
            warehouse_code_value=self.service.order_warehouse(o)
            warehouse={'100':'100 본사창고','300':'300 위킵창고'}.get(warehouse_code_value,warehouse_code_value)
            work_kind=[]
            if selected_day == o.get('registered_day'):work_kind.append('등록')
            if selected_day in o.get('request_days',[]):work_kind.append('출고요청')
            if selected_day in o.get('shipment_days',[]):work_kind.append('실제출고')
            if legacy_pending:work_kind.append('기존 미처리')
            source_name=' + '.join(part for part in (source_product,source_option) if identifier(part))
            values=[channel,d['order_no'],d['recipient'],f"{d.get('postcode','')} {d['address']}".strip(),d['phone'],source_name,converted,warehouse,o['state'],'·'.join(work_kind)]
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
            shown+=1
        unmatched=sum(order['state']=='검토 필요' for order in self.rows.values())
        self.order_counts.set(f'전체 {len(self.rows):,}건 · 미매칭 {unmatched:,}건 · 표시 {shown:,}건')
        self.root.after_idle(lambda:autosize_tree(self.table))

    def refresh_orders_for_day(self):
        try:date.fromisoformat(self.order_day.get())
        except ValueError:return
        self.refresh_orders()
        self.refresh_channel_status()

    def toggle_channel_visibility(self, channel):
        visible=not self.channel_visibility.get(channel,True)
        self.channel_visibility[channel]=visible
        self.channel_eye_text[channel].set('👁' if visible else '◌')
        self.channel_eye_buttons[channel].configure(style='Visible.Eye.TButton' if visible else 'Hidden.Eye.TButton')
        self.refresh_orders()

    def toggle_completed_orders(self):
        hidden=not self.hide_completed_orders.get()
        self.hide_completed_orders.set(hidden)
        self.hide_completed_text.set('출고 완료건 제외 · 켜짐' if hidden else '출고 완료건 제외 · 꺼짐')
        self.refresh_orders()

    def refresh(self):
        if hasattr(self,'tracking_panel'):self.tracking_panel.refresh()
        self.refresh_orders()
        self.refresh_erp_shipments()
        self.refresh_confirmed_shipments()
        self.refresh_esm_entries()
        self.refresh_item_names()
        self.refresh_channel_status()
        counts={state:sum(o['state']==state for o in self.rows.values()) for state in ['검토 필요','출고 준비','출고 요청','부분 출고','출고 완료']}
        stats=self.service.match_statistics(self.rows.values())
        self.summary.set(f"자동 매칭 {stats['ready']:,}/{stats['total']:,}건 ({stats['rate']}%)   "+'   '.join(f'{key}  {value:,}건' for key,value in counts.items()))
        self.refresh_history()

    def refresh_history(self):
        if not hasattr(self,'history'):return
        self.history.delete(*self.history.get_children())
        selected_day=None if self.history_show_all else self.history_day.get()
        self.history_artifacts={}
        self.history_rows={}
        weekdays=('월','화','수','목','금','토','일')
        for row in self.service.artifact_history_rows(selected_day):
            try:day_label=f"{row['artifact_day']} ({weekdays[date.fromisoformat(row['artifact_day']).weekday()]})"
            except ValueError:day_label=row['artifact_day']
            iid=row['row_id']
            self.history_artifacts[iid]=row['artifact_id']
            self.history_rows[iid]=row
            channel=INTERNAL_TO_CHANNEL.get(row['channel'],row['channel']).removeprefix('리큐엠_')
            try:amount=f"{int(Decimal(row['amount'])):,}"
            except Exception:amount=row['amount']
            values=[
                day_label,row['source_day'],row['source'],channel,row['order_no'],row['recipient'],row['phone'],
                row['product'],row['option'],row.get('matching_item',''),row['quantity'],amount,row['tracking'] or '—',row['warehouse'] or '—',
                row['note'] or '', '확인 완료' if row['registered'] else '—',row['artifact_id'],
            ]
            terms=[term for term in self.history_search.get().casefold().split() if term]
            haystack=' '.join(str(value) for value in values).casefold()
            if not all(term in haystack for term in terms):continue
            self.history.insert('', 'end',iid=iid,values=values)
        self.root.after_idle(lambda:autosize_tree(self.history,maximum=360))

    def show_history_day(self):
        date.fromisoformat(self.history_day.get())
        self.history_show_all=False;self.refresh_history()

    def show_all_history(self):
        self.history_show_all=True;self.refresh_history()

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
            if self.table.identify_column(event.x)=='#8':
                self.safe(self.change_order_warehouse)
            else:
                self.safe(self.mapping)

    def change_order_warehouse(self):
        ids=list(self.selected(self.table))
        current=self.service.order_warehouse(self.rows[ids[0]])
        initial={'100':'100 본사창고','300':'300 위킵창고'}.get(current,'300 위킵창고')
        win=tk.Toplevel(self.root);win.title('주문 출하창고 입력');win.geometry('470x210');win.transient(self.root);win.grab_set()
        body=ttk.Frame(win,padding=20);body.pack(fill='both',expand=True)
        ttk.Label(body,text=f'선택 주문 {len(ids):,}건의 출하창고',font=(self.font_family,15,'bold')).pack(anchor='w')
        value=tk.StringVar(value=initial)
        ttk.Combobox(
            body,textvariable=value,values=['100 본사창고','300 위킵창고'],state='readonly',width=28,
        ).pack(anchor='w',pady=18)
        def save():
            self.service.set_order_warehouse(ids,value.get());win.destroy();self.refresh()
        actions=ttk.Frame(body);actions.pack(fill='x')
        self.button(actions,'적용',save,style='Accent.TButton')
        self.button(actions,'취소',win.destroy,style='Quiet.TButton')

    def select_ready(self):
        self.table.selection_set([
            key for key in self.table.get_children()
            if self.rows[key]['state']=='출고 준비'
            and INTERNAL_TO_CHANNEL.get(self.rows[key]['data']['channel'],self.rows[key]['data']['channel']) not in self.request_excluded_channels
        ])

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
        new,duplicate=self.service.import_files(
            paths,channel_override=channel_override,registered_on=self.order_day.get(),
        )
        source_names={Path(path).name for path in paths}
        imported=[order for order in self.service.orders() if order['data'].get('source_file') in source_names]
        self.refresh()
        stats=self.service.match_statistics(imported)
        methods=' · '.join(f'{name} {count}건' for name,count in stats['methods'].items())
        messagebox.showinfo(title,
            f"파일 {len(paths)}개 분석 완료\n신규 {new}건 · 동일 주문 제외 {duplicate}건\n\n"
            f"자동 확정 {stats['ready']}건 ({stats['rate']}%) · 확인 필요 {stats['review']}건\n"
            f"{methods or '적용된 자동 규칙 없음'}",parent=self.root)

    def refresh_channel_status(self):
        files = {channel:set() for channel in SALES_CHANNELS}
        selected_day=self.order_day.get()
        event_channels = {rule['channel'] for rule in self.service.event_rules() if rule['active']}
        for order in self.rows.values():
            data = order['data']
            channel = INTERNAL_TO_CHANNEL.get(data.get('channel'), data.get('channel'))
            source = data.get('source_file')
            if channel in files and source and order.get('registered_day') == selected_day:
                files[channel].add(source)
        for channel, status in self.channel_status.items():
            count = len(files[channel])
            internal = CHANNEL_TO_INTERNAL.get(channel,channel)
            event = internal in event_channels
            prefix = 'EVENT · ' if event else ('✓  ' if count else '□  ')
            suffix = f'  ({count}개)' if count else ''
            status.set(f'{prefix}{channel}{suffix}')
            self.channel_buttons[channel].configure(style='Complete.Channel.TButton' if count else 'Channel.TButton')

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
        labels=['ERP 품목코드','물류사 품목코드','매칭품목명','구성 수량(곱셈 안 함)','출하창고','거래처코드']
        widths=[40,40,40,12,16,40]
        for column,label in enumerate(labels):ttk.Label(grid,text=label).grid(row=0,column=column,padx=3,pady=6)
        for column in (0,1,2,5):grid.columnconfigure(column,weight=2)
        for column in (3,4):grid.columnconfigure(column,weight=1)
        entries=[]
        customer=self.service.channel_customer_code(d['channel'])
        customer_choices=self.service.customer_choices()
        item_choices={item['code']:item['name'] for item in self.service.item_choices()}
        catalog_choices=[f'{code} · {name}' if name else code for code,name in item_choices.items()]
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
                        variables['code'].set(value)
                        variables['logistics_code'].set(value)
                        variables['name'].set(self.service.item_name(value,item_choices.get(value,value)))
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
                widget.grid(row=len(entries)+1,column=column,padx=3,pady=4,sticky='ew');widgets.append(widget)
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
            self.refresh(); win.destroy()
            messagebox.showinfo('매칭 저장',f'이 PC의 로컬 DB에 저장했습니다.\n동일 상품·옵션 주문 {affected}건을 다시 매칭했습니다.',parent=self.root)
        line=ttk.Frame(win,padding=12); line.pack(fill='x')
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
        widths=[38,38,38,12,15,12,38]
        for column,label in enumerate(labels):ttk.Label(component_box,text=label).grid(row=0,column=column,padx=3,pady=5)
        for column in (0,1,2,6):component_box.columnconfigure(column,weight=2)
        for column in (3,4,5):component_box.columnconfigure(column,weight=1)
        catalog_choices=[f"{item['code']} · {item['name']}" for item in self.service.item_choices()]
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
                        variables['code'].set(value)
                        variables['logistics_code'].set(value);variables['name'].set(self.service.item_name(value))
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
                widget.grid(row=len(entries)+1,column=column,padx=3,pady=3,sticky='ew');widgets.append(widget)
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
        selected=list(self.selected(self.table))
        ids=[key for key in selected if INTERNAL_TO_CHANNEL.get(
            self.rows[key]['data']['channel'],self.rows[key]['data']['channel']
        ) not in self.request_excluded_channels]
        warehouse=self.request_warehouse.get()
        if warehouse!='전체창고':
            code=warehouse.split(' ',1)[0]
            ids=[key for key in ids if self.service.order_warehouse(self.rows[key])==code]
        if not ids:
            raise ValueError('선택한 조건에 맞는 주문이 없습니다. 판매처 제외와 출하창고를 확인하세요.')
        if not self.preflight_review(ids,show_success=False):return
        if not self.confirm_request_review(ids):return
        warehouse_suffix='' if warehouse=='전체창고' else '_'+warehouse.split(' ',1)[0]
        path=self.save_path('출고요청_'+self.today.get()+warehouse_suffix+'.xlsx')
        if path:
            batch=self.service.request(
                ids,self.today.get(),path,excluded_channels=self.request_excluded_channels,warehouse=warehouse,
            ); self.refresh()
            excluded=len(selected)-len(ids)
            suffix=f'\n선택 조건에서 제외된 주문 {excluded:,}건은 포함하지 않았습니다.' if excluded else ''
            messagebox.showinfo('파일 생성',f'{batch}\n{warehouse} 출고요청 파일을 저장했습니다. 물류사 양식을 확인한 뒤 전달하세요.{suffix}')

    def result_template(self):
        path=self.save_path('위킵_출고결과_양식.xlsx')
        if path:Path(path).write_bytes(wekeep_workbook_bytes([]))

    def auto_results(self):
        selected_day=self.erp_ship_day.get()
        new,duplicate=self.service.auto_import_shipments(selected_day,self.erp_excluded_channels);self.refresh()
        excluded=', '.join(sorted(self.erp_excluded_channels)) or '없음'
        messagebox.showinfo(
            '자동 반영 완료',
            f'{selected_day} 출고요청 기준\n실제 출고 {new}행 · 기존 반영 {duplicate}행\n스마트스토어는 자동으로 제외했습니다.\n선택 제외: {excluded}',
            parent=self.root,
        )

    def results(self):
        path=filedialog.askopenfilename(filetypes=[('물류 결과','*.xlsx *.xls *.csv')])
        if path:
            new,duplicate=self.service.import_results(path,self.erp_ship_day.get());self.refresh()
            messagebox.showinfo('반영 완료',f'실제 출고 {new}행 · 중복 제외 {duplicate}행')

    def smartstore_erp_results(self):
        path=filedialog.askopenfilename(
            parent=self.root,title='스마트스토어 출고파일 선택',
            filetypes=[('스마트스토어 출고파일','*.xlsx *.xlsm *.xls *.csv')],
        )
        if path:
            new,duplicate=self.service.import_smartstore_erp(path,None);self.refresh()
            messagebox.showinfo('반영 완료',f'스마트스토어 출고파일 {new}행 · 중복 제외 {duplicate}행\n원본 결제일 기준으로 저장했습니다.')

    def smartstore_purchase_results(self):
        path=filedialog.askopenfilename(
            parent=self.root,title='스마트스토어 구매확정파일 선택',
            filetypes=[('스마트스토어 구매확정파일','*.xlsx *.xlsm *.xls *.csv')],
        )
        if path:
            new,duplicate=self.service.import_smartstore_purchase(path,None);self.refresh()
            messagebox.showinfo('반영 완료',f'스마트스토어 구매확정 {new}행 · 중복 제외 {duplicate}행\n원본 결제일 기준으로 저장했습니다.')

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

    def export_esm_erp(self):
        start=date.fromisoformat(self.esm_start_day.get()).isoformat()
        end=date.fromisoformat(self.esm_end_day.get()).isoformat()
        if start>end:raise ValueError('시작 주문일은 종료 주문일보다 늦을 수 없습니다.')
        path=self.save_path(f'ESM_ERP_{start}_{end}.xlsx')
        if path:
            self.service.export_erp(end,end,path,from_day=start,only_esm=True)
            self.refresh()
            messagebox.showinfo('ESM ERP 파일 생성','선택 기간의 옥션·지마켓 주문만 ERP 파일로 저장했습니다.',parent=self.root)

    def refresh_esm_entries(self):
        if not hasattr(self,'esm_entries'):return
        self.esm_entries.delete(*self.esm_entries.get_children())
        selected_from=None if self.esm_show_all else date.fromisoformat(self.esm_view_from.get()).isoformat()
        selected_through=None if self.esm_show_all else date.fromisoformat(self.esm_view_through.get()).isoformat()
        for entry in self.service.esm_erp_entries(selected_from,selected_through):
            status='ERP 반영 완료' if entry['erp_id'] else entry['issue'] or '변환 준비'
            self.esm_entries.insert('', 'end', iid=entry['id'], values=[
                entry['day'],entry['channel'],entry['order_no'],entry['product'],entry['option'],
                entry['quantity'],f"{int(Decimal(entry['unit_amount'])):,}",f"{int(Decimal(entry['amount'])):,}",
                entry['component_summary'] or '미매칭',status,
            ],tags=('review',) if entry['issue'] and not entry['erp_id'] else ())
        self.esm_entries.tag_configure('review',foreground='#BE123C',background='#FFF1F2')
        self.root.after_idle(lambda:autosize_tree(self.esm_entries,maximum=340))

    def show_esm_day(self):
        start=date.fromisoformat(self.esm_view_from.get()).isoformat()
        end=date.fromisoformat(self.esm_view_through.get()).isoformat()
        if start>end:raise ValueError('조회 시작일은 종료일보다 늦을 수 없습니다.')
        self.esm_show_all=False
        self.refresh_esm_entries()

    def show_all_esm(self):
        self.esm_show_all=True
        self.refresh_esm_entries()

    def delete_esm_entries(self):
        ids=list(self.selected(self.esm_entries))
        if not messagebox.askyesno(
            '옥션/지마켓 주문 삭제',
            f'선택한 주문 {len(ids):,}건을 삭제할까요?\nERP 반영 상태와 관계없이 변환 목록에서 삭제됩니다.',
            parent=self.root,
        ):return
        deleted=self.service.delete_esm_erp_entries(ids)
        self.refresh()
        messagebox.showinfo('삭제 완료',f'옥션/지마켓 주문 {deleted:,}건을 삭제했습니다.',parent=self.root)

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
        labels=['ERP 품목코드','매칭품목명','부속품 단가','출하창고','거래처코드']
        for column,label in enumerate(labels):ttk.Label(grid,text=label).grid(row=0,column=column,padx=4,pady=6,sticky='w')
        for column in (0,1,4):grid.columnconfigure(column,weight=2)
        entries=[];customer=self.service.channel_customer_code(channel)
        customer_choices=self.service.customer_choices()
        item_choices={item['code']:item['name'] for item in self.service.item_choices()}
        catalog_choices=[f'{code} · {name}' if name else code for code,name in item_choices.items()]
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
                if key in ('code','warehouse','customer'):
                    choices=(catalog_choices if key=='code' else
                             ['100 본사창고','300 위킵창고'] if key=='warehouse' else customer_choices)
                    widget=ttk.Combobox(
                        grid,textvariable=values[key],values=choices,
                        width=(24 if key in ('code','customer') else 13),
                    )
                    def chosen(_event,values=values,key=key):
                        value=_event.widget.get().split(' · ',1)[0]
                        values[key].set(value)
                        if key=='code':
                            values['name'].set(self.service.item_name(value,item_choices.get(value,value)))
                    widget.bind('<<ComboboxSelected>>',chosen)
                    def search_catalog(event,widget=widget,choices=choices):
                        if event.keysym in ('Up','Down','Left','Right','Return','Escape','Tab'):return
                        query=widget.get();cursor=widget.index('insert')
                        def update():
                            if widget.get()!=query:return
                            post_combobox(widget,filter_combobox_choices(query,choices))
                            widget.icursor(min(cursor,len(query)))
                        widget.after_idle(update)
                    widget.bind('<KeyRelease>',search_catalog)
                    bind_wide_combobox(widget)
                else:
                    widget=ttk.Entry(grid,textvariable=values[key],width=(34 if key=='name' else 13))
                widget.bind('<Double-1>',self.select_all_text)
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
        self.confirmed_entry_ids={}
        start=date.fromisoformat(self.erp_ship_from.get()).isoformat()
        end=date.fromisoformat(self.erp_ship_through.get()).isoformat()
        if start>end:raise ValueError('조회 시작일은 종료일보다 늦을 수 없습니다.')
        entries=self.service.confirmed_erp_entries(start,end)
        customers=sorted({INTERNAL_TO_CHANNEL.get(entry['channel'],entry['channel']) for entry in entries})
        choices=['전체 거래처',*customers]
        self.erp_ship_customer_box.configure(values=choices)
        if self.erp_ship_customer.get() not in choices:
            self.erp_ship_customer.set('전체 거래처')
        selected_customer=self.erp_ship_customer.get()
        if selected_customer!='전체 거래처':
            entries=[entry for entry in entries if INTERNAL_TO_CHANNEL.get(entry['channel'],entry['channel'])==selected_customer]
        for index,entry in enumerate(entries):
            item_id=f'confirmed-{index}';self.confirmed_entry_ids[item_id]=entry['id']
            self.confirmed_shipments.insert('', 'end', iid=item_id, values=[
                entry['source'],entry['day'],INTERNAL_TO_CHANNEL.get(entry['channel'],entry['channel']),
                entry['order_no'],entry['recipient'],entry['code'],entry['product'],entry.get('warehouse',''),
                entry['quantity'],entry['tracking'] or '—',
            ])
        self.root.after_idle(lambda:autosize_tree(self.confirmed_shipments,maximum=300))

    def refresh_actual_erp_day(self):
        self.refresh_confirmed_shipments()
        self.refresh_erp_shipments()

    def selected_confirmed_entry(self):
        item_id=self.selected(self.confirmed_shipments)[0]
        entry_id=self.confirmed_entry_ids[item_id]
        return next(entry for entry in self.service.confirmed_erp_entries(
            self.erp_ship_from.get(),self.erp_ship_through.get()
        ) if entry['id']==entry_id)

    def delete_confirmed_shipments(self):
        item_ids=list(self.selected(self.confirmed_shipments))
        entry_ids=[self.confirmed_entry_ids[item_id] for item_id in item_ids]
        unique_orders=len(set(entry_id.split(':',2)[1] if entry_id.startswith('SSERP:') else entry_id for entry_id in entry_ids))
        if not messagebox.askyesno(
            '출고 주문 삭제',
            f'선택한 출고 주문 {unique_orders:,}건을 삭제할까요?\n이미 만든 출력 이력 파일은 그대로 유지됩니다.',
            parent=self.root,
        ):return
        deleted=self.service.delete_confirmed_erp_entries(entry_ids)
        self.refresh()
        messagebox.showinfo('삭제 완료',f'출고 주문 {deleted:,}건을 삭제했습니다.',parent=self.root)

    def change_shipment_warehouse(self):
        entry=self.selected_confirmed_entry()
        value=simpledialog.askstring(
            '출하 창고 변경',
            f"주문번호: {entry['order_no']}\n품목: {entry['product']}\n\n100 본사창고 또는 300 위킵창고를 입력하세요.\n이 변경은 이번 ERP Excel에만 적용됩니다.",
            initialvalue=entry.get('warehouse',''),parent=self.root,
        )
        if value is None:return
        self.service.set_erp_entry_output(entry['id'],warehouse=value)
        self.refresh_actual_erp_day()

    def change_shipment_item(self):
        entry=self.selected_confirmed_entry()
        code=simpledialog.askstring(
            '품목 변경 · ERP 품목코드',
            f"주문번호: {entry['order_no']}\n현재 품목: {entry['product']}\n\n이번 ERP Excel에 사용할 품목코드를 입력하세요.",
            initialvalue=entry.get('code',''),parent=self.root,
        )
        if code is None:return
        name=simpledialog.askstring(
            '품목 변경 · 품목명',
            '이번 ERP Excel에 표시할 품목명을 입력하세요.\n저장된 상품 매칭에는 영향을 주지 않습니다.',
            initialvalue=entry.get('product',''),parent=self.root,
        )
        if name is None:return
        self.service.set_erp_entry_output(entry['id'],code=code,name=name)
        self.refresh_actual_erp_day()

    def refresh_erp_shipments(self):
        if not hasattr(self,'erp_shipments'):
            return
        self.erp_shipments.delete(*self.erp_shipments.get_children())
        self.amount_split_rows={}
        start=date.fromisoformat(self.erp_amount_from.get()).isoformat()
        end=date.fromisoformat(self.erp_amount_through.get()).isoformat()
        if start>end:raise ValueError('조회 시작일은 종료일보다 늦을 수 없습니다.')
        for index,row in enumerate(self.service.pending_amount_splits(start,end)):
            item_id=f'amount-split-{index}';self.amount_split_rows[item_id]=row
            self.erp_shipments.insert('', 'end', iid=item_id, values=[
                row['day'],row['channel'],row['order_no'],row['recipient'],row['component_count'],
                f"{int(Decimal(row['total'])):,}",row.get('product',''),row.get('option',''),row['summary'],
            ])
        self.root.after_idle(lambda:autosize_tree(self.erp_shipments,maximum=320))

    def split_order_amount(self):
        item_id=self.selected(self.erp_shipments)[0]
        row=self.amount_split_rows[item_id]
        if row.get('kind')=='smartstore' and len(row['components']) < 2:
            raise ValueError('먼저 스마트스토어 상품·세트 매칭에서 구성품을 2개 이상 등록하세요.')
        win=tk.Toplevel(self.root);win.title('구성품별 금액 나누기');win.geometry('900x600');win.transient(self.root);win.grab_set()
        ttk.Label(win,text='구성품별 금액 나누기',font=(self.font_family,17,'bold'),padding=(18,16)).pack(anchor='w')
        ttk.Label(win,text=f"주문번호 {row['order_no']} · {row['recipient']}",padding=(18,0)).pack(anchor='w')
        ttk.Label(win,text='각 구성품의 총 반영금액을 입력하세요. 합계가 주문 금액과 같아야 저장됩니다.',foreground='#64748B',padding=(18,7)).pack(anchor='w')
        grid=ttk.Frame(win,padding=18);grid.pack(fill='both',expand=True)
        for column,label in enumerate(('ERP 품목코드','ERP 품목명','출고수량','반영금액')):
            ttk.Label(grid,text=label,font=(self.font_family,10,'bold')).grid(row=0,column=column,sticky='w',padx=5,pady=6)
        amounts={}
        for position,component in enumerate(row['components'],start=1):
            ttk.Label(grid,text=component['code']).grid(row=position,column=0,sticky='w',padx=5,pady=6)
            ttk.Label(grid,text=component['name']).grid(row=position,column=1,sticky='w',padx=5,pady=6)
            ttk.Label(grid,text=str(component['quantity'])).grid(row=position,column=2,sticky='w',padx=5,pady=6)
            variable=tk.StringVar(value=str(int(Decimal(component['amount']))));amounts[component['index']]=variable
            ttk.Entry(grid,textvariable=variable,width=18).grid(row=position,column=3,sticky='w',padx=5,pady=6)
        grid.columnconfigure(1,weight=1)
        summary=ttk.Frame(win,padding=(18,8));summary.pack(fill='x')
        total_text=tk.StringVar(value=f"주문 전체금액  {int(Decimal(row['total'])):,}원")
        entered_text=tk.StringVar()
        difference_text=tk.StringVar()
        ttk.Label(summary,textvariable=total_text,font=(self.font_family,11,'bold')).pack(anchor='w')
        ttk.Label(summary,textvariable=entered_text,font=(self.font_family,11,'bold')).pack(anchor='w',pady=(5,0))
        difference_label=ttk.Label(summary,textvariable=difference_text,font=(self.font_family,11,'bold'))
        difference_label.pack(anchor='w',pady=(5,0))
        def save():
            self.service.set_amount_split(
                row['order_id'],row['day'],
                {index:variable.get().replace(',','') for index,variable in amounts.items()},
            )
            win.destroy();self.refresh_erp_shipments();self.refresh_confirmed_shipments()
        actions=ttk.Frame(win,padding=18);actions.pack(fill='x')
        save_button=ttk.Button(actions,text='저장',style='Accent.TButton',command=lambda:self.safe(save))
        save_button.pack(side='left',padx=4)
        self.button(actions,'취소',win.destroy,style='Quiet.TButton')
        def refresh_totals(*_):
            totals=amount_split_totals(row['total'],[variable.get() for variable in amounts.values()])
            if totals is None:
                entered_text.set('현재 입력 합계  계산할 수 없음')
                difference_text.set('금액에는 숫자와 쉼표만 입력하세요.')
                difference_label.configure(foreground='#BE123C')
                save_button.state(['disabled'])
                return
            _expected,entered,difference=totals
            entered_text.set(f'현재 입력 합계  {int(entered):,}원')
            if difference > 0:
                difference_text.set(f'전체금액 대비 +{int(difference):,}원 초과')
                difference_label.configure(foreground='#BE123C')
                save_button.state(['disabled'])
            elif difference < 0:
                difference_text.set(f'전체금액 대비 -{abs(int(difference)):,}원 부족')
                difference_label.configure(foreground='#BE123C')
                save_button.state(['disabled'])
            else:
                difference_text.set('전체금액과 일치합니다.')
                difference_label.configure(foreground='#15803D')
                save_button.state(['!disabled'])
        for variable in amounts.values():
            variable.trace_add('write',refresh_totals)
        refresh_totals()

    def open_amount_split_action(self):
        item_id=self.selected(self.erp_shipments)[0]
        row=self.amount_split_rows[item_id]
        if row.get('kind')=='smartstore':
            self.edit_erp_set()
        else:
            self.split_order_amount()

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
        item_id=self.selected(self.erp_shipments)[0]
        selected_row=self.amount_split_rows[item_id]
        if selected_row.get('kind')!='smartstore':
            raise ValueError('스마트스토어 미매칭 또는 세트 주문을 선택하세요.')
        entry_id=selected_row['id']
        row=self.service.smartstore_erp_row(entry_id)
        if not row:
            raise ValueError('세트 구성 수정은 스마트스토어 ERP 입력 건에서 사용할 수 있습니다.')
        data=row['data']
        win=tk.Toplevel(self.root);win.title('스마트스토어 ERP 세트 분리');win.geometry('1120x620');win.transient(self.root);win.grab_set()
        ttk.Label(win,text='스마트스토어 ERP 세트 분리',font=(self.font_family,17,'bold'),padding=(16,14)).pack(anchor='w')
        ttk.Label(win,text=f"{data.get('order_no')}  |  {data.get('product')} / {data.get('option')}",padding=(16,0)).pack(anchor='w')
        ttk.Label(win,text='첫 구성품은 주문 총금액에서 부속품 단가를 뺀 금액으로 자동 계산됩니다.',foreground='#64748B',padding=(16,6)).pack(anchor='w')
        grid=ttk.Frame(win,padding=16);grid.pack(fill='both',expand=True)
        labels=['ERP 품목코드','품목명','부속품 단가','출하창고','거래처코드','계산 반영금액']
        for column,label in enumerate(labels):ttk.Label(grid,text=label).grid(row=0,column=column,padx=4,pady=6,sticky='w')
        for column in (0,1,4):grid.columnconfigure(column,weight=2)
        entries=[]
        order_total=Decimal(data.get('amount') or '0')
        source_quantity=max(1,int(Decimal(data.get('quantity') or '1')))
        customer=self.service.channel_customer_code('리큐엠_스마트스토어')
        customer_choices=self.service.customer_choices()
        item_choices={item['code']:item['name'] for item in self.service.item_choices()}
        catalog_choices=[f'{code} · {name}' if name else code for code,name in item_choices.items()]
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
                if key in ('code','warehouse','customer'):
                    choices=(catalog_choices if key=='code' else
                             ['100 본사창고','300 위킵창고'] if key=='warehouse' else customer_choices)
                    widget=ttk.Combobox(
                        grid,textvariable=values[key],values=choices,
                        width=(30 if key in ('code','customer') else 16),
                    )
                    def chosen(_event,values=values,key=key):
                        value=_event.widget.get().split(' · ',1)[0]
                        values[key].set(value)
                        if key=='code':
                            values['name'].set(self.service.item_name(value,item_choices.get(value,value)))
                    widget.bind('<<ComboboxSelected>>',chosen)
                    def search_catalog(event,widget=widget,choices=choices):
                        if event.keysym in ('Up','Down','Left','Right','Return','Escape','Tab'):return
                        query=widget.get();cursor=widget.index('insert')
                        def update():
                            if widget.get()!=query:return
                            post_combobox(widget,filter_combobox_choices(query,choices))
                            widget.icursor(min(cursor,len(query)))
                        widget.after_idle(update)
                    widget.bind('<KeyRelease>',search_catalog)
                    bind_wide_combobox(widget)
                else:
                    widget=ttk.Entry(grid,textvariable=values[key],width=(34 if key=='name' else 13))
                widget.bind('<Double-1>',self.select_all_text)
                widget.grid(row=index+1,column=column,padx=4,pady=4,sticky='ew');widgets.append(widget)
            calculated=tk.StringVar(value='계산 중')
            calculated_label=ttk.Label(grid,textvariable=calculated,font=(self.font_family,10,'bold'))
            calculated_label.grid(row=index+1,column=5,padx=4,pady=4,sticky='w');widgets.append(calculated_label)
            entries.append((values,widgets,calculated))
        for component in row['components']:add_row(component)
        if not entries:add_row()
        def remove_row():
            if len(entries)>1:
                _,widgets,_=entries.pop()
                for widget in widgets:widget.destroy()
                refresh_totals()
        def save():
            components=[]
            for values,_,_ in entries:
                item={key:value.get().strip() for key,value in values.items()}
                item.update({'logistics_code':item['code'],'quantity':'1'})
                components.append(item)
            self.service.set_smartstore_erp_components(entry_id,components)
            win.destroy();self.refresh_erp_shipments();self.refresh_confirmed_shipments()
        summary=ttk.Frame(win,padding=(16,4));summary.pack(fill='x')
        total_text=tk.StringVar(value=f'주문 전체금액  {int(order_total):,}원')
        entered_text=tk.StringVar()
        difference_text=tk.StringVar()
        ttk.Label(summary,textvariable=total_text,font=(self.font_family,11,'bold')).pack(anchor='w')
        ttk.Label(summary,textvariable=entered_text,font=(self.font_family,11,'bold')).pack(anchor='w',pady=(5,0))
        difference_label=ttk.Label(summary,textvariable=difference_text,font=(self.font_family,11,'bold'))
        difference_label.pack(anchor='w',pady=(5,0))
        actions=ttk.Frame(win,padding=16);actions.pack(fill='x')
        self.button(actions,'구성품 추가',lambda:(add_row(),bind_amount_traces(),refresh_totals()))
        self.button(actions,'마지막 구성품 삭제',remove_row,style='Danger.TButton')
        save_button=ttk.Button(actions,text='세트 구성 저장',style='Accent.TButton',command=lambda:self.safe(save))
        save_button.pack(side='left',padx=4)
        self.button(actions,'닫기',win.destroy)
        traced=set()
        def refresh_totals(*_):
            try:
                accessory=[]
                for position,(values,_widgets,calculated) in enumerate(entries):
                    unit=Decimal(values['unit_amount'].get().replace(',','').strip() or '0')
                    amount=(order_total-sum(accessory,Decimal('0'))) if position==0 else unit*source_quantity
                    if position>0:accessory.append(amount)
                    calculated.set(f'{int(amount):,}원')
                accessory_total=sum(accessory,Decimal('0'))
                main_amount=order_total-accessory_total
                if entries:entries[0][2].set(f'{int(main_amount):,}원')
                entered=main_amount+accessory_total
                entered_text.set(f'현재 입력 합계  {int(entered):,}원')
                difference=accessory_total-order_total
                if difference>0:
                    difference_text.set(f'부속품 합계가 전체금액 대비 +{int(difference):,}원 초과')
                    difference_label.configure(foreground='#BE123C');save_button.state(['disabled'])
                else:
                    difference_text.set('전체금액과 일치합니다.')
                    difference_label.configure(foreground='#15803D');save_button.state(['!disabled'])
            except (InvalidOperation,ValueError):
                entered_text.set('현재 입력 합계  계산할 수 없음')
                difference_text.set('금액에는 숫자와 쉼표만 입력하세요.')
                difference_label.configure(foreground='#BE123C');save_button.state(['disabled'])
                for _values,_widgets,calculated in entries:calculated.set('확인 필요')
        def bind_amount_traces():
            for values,_widgets,_calculated in entries:
                variable=values['unit_amount']
                token=str(variable)
                if token not in traced:
                    variable.trace_add('write',refresh_totals);traced.add(token)
        bind_amount_traces();refresh_totals()

    def erp(self):
        path=self.save_path('ERP_'+self.voucher.get()+'.xlsx')
        if path:
            self.service.export_erp(
                self.voucher.get(),self.through.get(),path,
                from_day=self.erp_from.get(),include_esm=self.erp_include_esm.get(),
                excluded_channels=self.erp_excluded_channels,
            );self.refresh()
            messagebox.showinfo('ERP 파일 생성','ERP 파일을 저장했습니다. 사이트 등록 후 출력 이력에서 등록 확인을 표시하세요.')

    def download_erp_again(self):
        artifacts=[row for row in self.service.artifacts() if row['kind'] in ('ERP','ESM ERP')]
        if not artifacts:raise ValueError('재생성할 ERP 파일 이력이 없습니다.')
        win=tk.Toplevel(self.root);win.title('현재 정보로 ERP 재다운로드');win.geometry('720x480');win.transient(self.root);win.grab_set()
        ttk.Label(win,text='현재 정보로 ERP 재다운로드',font=(self.font_family,17,'bold'),padding=(18,16)).pack(anchor='w')
        ttk.Label(win,text='선택한 이력의 주문을 현재 DB의 최신 주문·출고·창고 정보로 다시 생성합니다.',foreground='#64748B',padding=(18,0)).pack(anchor='w')
        tree=self.tree(win,['출력일','종류','파일 ID','등록 확인'],[120,120,260,100])
        rows={}
        for index,row in enumerate(artifacts):
            item_id=f'erp-artifact-{index}';rows[item_id]=row
            tree.insert('', 'end',iid=item_id,values=[row['day'],row['kind'],row['id'],'확인 완료' if row['registered'] else '—'])
        def save():
            selected=tree.selection()
            if not selected:raise ValueError('재생성할 ERP 파일 이력을 선택하세요.')
            row=rows[selected[0]];path=self.save_path(f"{row['kind']}_{row['day']}_{row['id']}.xlsx")
            if path:
                self.service.regenerate_erp(row['id'],path);win.destroy()
                messagebox.showinfo('ERP 파일 저장','현재 주문정보 기준으로 ERP 파일을 새로 생성했습니다. ERP 반영 상태는 변경되지 않았습니다.',parent=self.root)
        actions=ttk.Frame(win,padding=14);actions.pack(fill='x')
        self.button(actions,'현재 정보로 재생성',save,style='Accent.TButton')
        self.button(actions,'닫기',win.destroy,style='Quiet.TButton')

    def reexport(self):
        row_id=self.selected(self.history)[0];key=self.history_artifacts[row_id];path=self.save_path(key+'.xlsx')
        if path:self.service.reexport(key,path)

    def export_tracked_order_file(self):
        row_id=self.selected(self.history)[0];row=self.history_rows[row_id]
        source=row.get('source_file','')
        if not source:raise ValueError('선택한 이력에 연결된 판매처 주문 파일이 없습니다.')
        if not self.service.source_file_available(source):
            original=filedialog.askopenfilename(
                parent=self.root,title=f'기존 원본 주문파일 연결 · {source}',
                filetypes=[('주문 파일','*.xlsx *.xlsm *.csv')],
            )
            if not original:return
            self.service.attach_source_file(source,original)
        original=Path(source)
        path=filedialog.asksaveasfilename(
            parent=self.root,title='송장번호가 반영된 판매처 주문 파일 저장',
            initialfile=f'{original.stem}_송장반영{original.suffix}',defaultextension=original.suffix,
            filetypes=[('원본 형식',f'*{original.suffix}'),('모든 파일','*.*')],
        )
        if path:
            self.service.export_source_file(source,path)
            messagebox.showinfo('주문 파일 저장','송장번호가 반영된 판매처 주문 파일을 저장했습니다.',parent=self.root)

    def edit_history_note(self):
        row_id=self.selected(self.history)[0];row=self.history_rows[row_id]
        note=simpledialog.askstring(
            '출력 이력 비고',
            f"주문번호: {row['order_no']}\n수령인: {row['recipient']}\n\n비고를 입력하세요.",
            initialvalue=row.get('note',''),parent=self.root,
        )
        if note is None:return
        self.service.set_artifact_note(row['artifact_id'],row['note_key'],note)
        self.refresh_history()

    def registered(self):
        row_id=self.selected(self.history)[0];key=self.history_artifacts[row_id]
        if messagebox.askyesno('ERP 등록 확인','ERP 사이트에 해당 파일을 정상 등록했습니까?'):
            self.service.mark_registered(key);self.refresh()

    def reload_settings(self):
        self.service.settings=settings_at(self.service.folder)
        self.load_matching_profile()
        messagebox.showinfo('설정','설정을 다시 읽었습니다. 기존 출고 구성과 파일은 변경되지 않습니다.')

    def refresh_item_names(self):
        if not hasattr(self,'item_name_tree'):return
        self.item_name_tree.delete(*self.item_name_tree.get_children())
        self.item_name_rows={}
        for index,row in enumerate(self.service.item_name_rows()):
            item_id=f'item-name-{index}';self.item_name_rows[item_id]=row
            self.item_name_tree.insert('', 'end',iid=item_id,values=[row['erp_item_code'],row['matching_name']])
        self.root.after_idle(lambda:autosize_tree(self.item_name_tree,maximum=600))

    def edit_selected_item_name(self):
        item_id=self.selected(self.item_name_tree)[0]
        self.edit_item_name(self.item_name_rows[item_id])

    def edit_item_name(self, row=None):
        row=row or {}
        win=tk.Toplevel(self.root);win.title('ERP 품목 기준 저장');win.geometry('620x260');win.transient(self.root);win.grab_set()
        body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text='ERP 품목코드와 매칭품목명',font=(self.font_family,16,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,16))
        ttk.Label(body,text='ERP 품목코드').grid(row=1,column=0,sticky='w',pady=6)
        ttk.Label(body,text='매칭품목명').grid(row=2,column=0,sticky='w',pady=6)
        code=tk.StringVar(value=row.get('erp_item_code',''));name=tk.StringVar(value=row.get('matching_name',''))
        ttk.Entry(body,textvariable=code,width=48).grid(row=1,column=1,sticky='ew',padx=(12,0),pady=6)
        ttk.Entry(body,textvariable=name,width=48).grid(row=2,column=1,sticky='ew',padx=(12,0),pady=6)
        body.columnconfigure(1,weight=1)
        def save():
            self.service.save_item_name(code.get(),name.get(),row.get('erp_item_code',''))
            win.destroy();self.refresh_item_names();self.refresh_orders();self.refresh_confirmed_shipments()
        actions=ttk.Frame(body);actions.grid(row=3,column=0,columnspan=2,sticky='w',pady=(18,0))
        self.button(actions,'저장',save,style='Accent.TButton')
        self.button(actions,'취소',win.destroy,style='Quiet.TButton')

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

