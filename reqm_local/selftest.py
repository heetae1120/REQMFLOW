"""Packaged end-to-end smoke test. Creates only synthetic data in the supplied folder."""
import json
import os
import sys
from pathlib import Path
import tkinter as tk
from .files import reference_data_path, workbook_bytes
from .cloud import load_cloud_config
from .service import Operations
from .desktop import Desktop, APP_VERSION


def run(folder):
    from supabase import create_client
    from selenium.webdriver.edge.options import Options as EdgeOptions
    import pystray
    assert callable(create_client)
    assert EdgeOptions
    assert pystray.Icon
    cloud_config=load_cloud_config()
    assert cloud_config.get('supabase_url') == 'https://jcslohuraqclhryeqxoc.supabase.co'
    assert str(cloud_config.get('supabase_publishable_key','')).startswith('sb_publishable_')
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
        from .closed_malls import MALLS
        assert len(app.closed_mall_panel.table.get_children()) == len(MALLS)
        assert set(app.closed_mall_panel.table.selection()) == {'musinsa', '29cm'}
        if os.environ.get('REQM_LOGIN_BROWSER_TEST') == '1':
            from .closed_mall_browser import create_login_driver
            driver = create_login_driver(folder / 'browser-smoke', True)
            try:
                driver.get('data:text/html,<title>REQM-login-smoke</title><p>synthetic</p>')
                assert driver.title == 'REQM-login-smoke'
            finally:
                driver.quit()
        assert app.font_family == 'Pretendard'
        assert app.matching_sites.get(1) == '스마트스토어 ERP매칭'
        assert tuple(app.confirmed_shipments['columns']) == ('구분','출고일','판매처','주문번호','이름','품목','수량','송장번호')
        assert tuple(app.erp_shipments['columns'])[:2] == ('구분','실제 출고일')
        assert len(app.table.get_children())==1
        app.table.selection_set(row['id']);app.show_detail()
        assert len(app.history.get_children())==2
        assert service.orders()[0]['state']=='출고 완료'
        job=service.import_tracking_files([order],'2026-10-01',channel_override='오늘의집')[0][0]
        remote={**service.tracking_rows(job)[0]['data'],'tracking':'001234567890'}
        service.apply_tracking_query(job,[remote],'2026-10-01','2026-10-01')
        tracked=service.tracking_rows(job)[0]
        assert tracked['state']=='matched'
        shipment_count=service.db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0]
        service.confirm_tracking(job,[tracked['id']])
        service.export_tracking_day('2026-10-01',folder/'demo-tracking.xlsx')
        from openpyxl import load_workbook
        book=load_workbook(folder/'demo-tracking.xlsx')
        assert book.active['J2'].value=='001234567890' and book.active['J2'].data_type=='s'
        assert book.active['B2'].value=='오늘의집'
        book.close()
        assert service.db.execute('SELECT COUNT(*) FROM shipments').fetchone()[0]==shipment_count
        from .workspace_cloud import export_workspace,import_workspace,workspace_digest
        state=export_workspace(service)
        import_workspace(service,state)
        assert workspace_digest(export_workspace(service))==workspace_digest(state)
        app.tracking_panel.day.set('2026-10-01');app.refresh();root.update_idletasks()
        assert len(app.tracking_panel.job_tree.get_children())==1
        assert len(app.tracking_panel.row_tree.get_children())==1
        (folder/'self-test.json').write_text(json.dumps({'ok':True,'version':APP_VERSION,'orders':1,'artifacts':2,
            'desktop':'OK','font':app.font_family,'cloud_config':'OK','tracking':'OK','workspace_roundtrip':'OK'},ensure_ascii=False),encoding='utf-8')
    except Exception as exc:
        (folder/'self-test.json').write_text(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),encoding='utf-8')
        raise
    finally:
        if root:root.destroy()
        service.close()
