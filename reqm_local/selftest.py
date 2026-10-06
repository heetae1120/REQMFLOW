"""Packaged end-to-end smoke test. Creates only synthetic data in the supplied folder."""
import json
import sys
from pathlib import Path
import tkinter as tk
from .files import reference_data_path, workbook_bytes
from .service import Operations
from .desktop import Desktop


def run(folder):
    from supabase import create_client
    import pystray
    assert callable(create_client)
    assert pystray.Icon
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
    service=Operations(folder/'test-data',reference_data_path(base))
    root=None
    try:
        headers=['주문번호','상품주문번호','상품명','옵션정보','수량','최종 상품별 총 주문금액','수취인명','수취인연락처1','우편번호','통합배송지','배송비 합계']
        order=folder/'demo-orders.xlsx'
        order.write_bytes(workbook_bytes(headers,[['DEMO-ORDER','DEMO-LINE','데모 상품','데모 옵션',3,10001,'가상 수령인','01000000000','00123','실제 배송 금지 테스트 주소',3000]]))
        service.import_files([order],channel_override='오늘의집')
        row=service.orders()[0]
        service.set_mapping(row['id'],[dict(code='DEMO-ERP',logistics_code='DEMO-WMS',name='테스트 상품',quantity=1,unit_amount=0,warehouse='300',customer='DEMO-CUSTOMER')])
        service.request([row['id']],'2026-10-01',folder/'demo-request.xlsx')
        assert service.auto_import_shipments('2026-10-01') == (1,0)
        service.export_erp('2026-10-01','2026-10-01',folder/'demo-erp.xlsx')
        root=tk.Tk();root.withdraw();app=Desktop(root,service);root.update_idletasks()
        assert root.title().startswith('REQM FLOW')
        assert app.font_family == 'Pretendard'
        assert app.matching_sites.get(1) == '스마트스토어 ERP매칭'
        assert tuple(app.confirmed_shipments['columns']) == ('구분','출고일','판매처','주문번호','이름','품목','수량','송장번호')
        assert tuple(app.erp_shipments['columns'])[:2] == ('구분','실제 출고일')
        assert len(app.table.get_children())==1
        app.table.selection_set(row['id']);app.show_detail()
        assert len(app.history.get_children())==2
        assert service.orders()[0]['state']=='출고 완료'
        (folder/'self-test.json').write_text(json.dumps({'ok':True,'orders':1,'artifacts':2,'desktop':'OK','font':app.font_family},ensure_ascii=False),encoding='utf-8')
    except Exception as exc:
        (folder/'self-test.json').write_text(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),encoding='utf-8')
        raise
    finally:
        if root:root.destroy()
        service.close()
