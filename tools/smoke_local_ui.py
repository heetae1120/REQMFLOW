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
from reqm_local.desktop import Desktop
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
        assert '중복' in app.table['columns']
        assert '이벤트' in app.table['columns']
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
