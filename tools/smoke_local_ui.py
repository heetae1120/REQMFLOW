"""Non-interactive desktop smoke test using synthetic data in a temporary folder."""
import os
import sys
import tempfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
resources=root/'.builddeps/tcltk8612/tcl'
if resources.exists():
    os.environ['TCL_LIBRARY']=str(resources/'tcl8.6')
    os.environ['TK_LIBRARY']=str(resources/'tk8.6')
import tkinter as tk
from reqm_local.desktop import Desktop, FIELD_LABELS, MAPPING_FIELD_ORDER
from reqm_local.profiles import MATCHING_CHANNELS
from reqm_local.service import Operations

with tempfile.TemporaryDirectory(dir=root/'outputs') as folder:
    service=Operations(folder,root/'supabase/ecount_migration/data')
    window=None
    try:
        window=tk.Tk();window.withdraw()
        app=Desktop(window,service)
        window.update_idletasks()
        assert '검토 필요' in app.summary.get()
        assert len(app.table.get_children())==0
        assert tuple(app.mapping_vars) == MAPPING_FIELD_ORDER
        assert [FIELD_LABELS[field] for field in app.mapping_vars] == [
            '주문일자', '판매처주문번호', '상품주문번호', '상품명', '옵션', '수량', '금액', '배송비',
            '수령인', '전화번호', '우편번호', '주소 1', '주소 2', '배송메모',
        ]
        assert 'address1' in app.mapping_boxes and 'address2' in app.mapping_boxes
        assert str(app.mapping_boxes['order_no'].cget('state')) == 'normal'
        assert app.erp_include_esm.get() is True
        assert tuple(app.history['columns']) == (
            '출력일(요일)','출고일','종류','판매처','주문번호','수령인','연락처',
            '판매품목','옵션','수량','금액','등록','묶음 ID',
        )
        zigzag_headers=['']*47
        for index,label in {
            1:'상품주문번호',2:'주문번호',3:'결제일',4:'주문상태',16:'상품코드',18:'상품명',
            22:'옵션정보',26:'수량',27:'상품주문액 (원)',32:'총 배송비 (원)',35:'수령인명',
            36:'수령인 연락처',37:'배송지 주소',38:'우편번호',40:'배송 메시지',44:'채널분류',
        }.items():zigzag_headers[index]=label
        zigzag_profile=app.matching_profile('지그재그')
        zigzag_profile.setdefault('columns',{})['address2']=['이전 파일 상세주소']
        zigzag_profile.setdefault('column_indexes',{})['address2']=5
        app.matching_sites.selection_clear(0,'end')
        app.matching_sites.selection_set(MATCHING_CHANNELS.index('지그재그'))
        app.load_matching_profile()
        app.sample_rows=[tuple(['지그재그 주문 보고서']+['']*46),tuple(zigzag_headers),tuple(['']*47)]
        app.matching_header_box.configure(values=[
            '1 · 지그재그 주문 보고서','2 · 상품주문번호 | 주문번호 | 결제일',
        ])
        app.matching_header_row.set('2 · 상품주문번호 | 주문번호 | 결제일')
        app.apply_sample_headers(force_auto=True)
        assert len(app.mapping_choice_values)==17
        assert all('이전 파일 상세주소' not in choice for choice in app.mapping_choice_values)
        assert app.mapping_vars['order_no'].get()=='C · 주문번호'
        assert app.mapping_vars['product'].get()=='S · 상품명'
        assert app.mapping_vars['memo'].get()=='AO · 배송 메시지'
        assert app.mapping_vars['address2'].get()=='미사용'
        assert app.matching_analysis.get().startswith('2행 기준')
        box=app.mapping_boxes['order_no']
        event=type('Event',(),{'keysym':'Hangul'})()
        for query in ('주','주문','주문번','주문번호'):
            box.delete(0,'end');box.insert(0,query)
            app.search_mapping_choices('order_no',box,event)
            window.update_idletasks()
            assert box.get()==query
        app.reload_settings=lambda:None
    finally:
        if window:window.destroy()
        service.close()
print('Desktop initialization, tabs, tables and empty-state rendering: OK')
