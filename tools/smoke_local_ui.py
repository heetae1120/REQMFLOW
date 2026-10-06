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
