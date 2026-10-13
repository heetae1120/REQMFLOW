"""Packaged end-to-end smoke test. Creates only synthetic data in the supplied folder."""
import json
import os
import sys
import shutil
import tempfile
from pathlib import Path
import tkinter as tk
from .files import reference_data_path, workbook_bytes
from .service import Operations
from .desktop import Desktop, APP_VERSION


def run_restart(folder):
    """Restart the same onefile executable through the real update replacer."""
    from .updater import launch_replacer
    folder=Path(folder).resolve()
    executable=Path(sys.executable).resolve()
    if not getattr(sys,'frozen',False) or executable.parent != folder/'install':
        raise ValueError('재시작 검증은 별도 테스트 설치 폴더에서만 실행할 수 있습니다.')
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'before-restart.json').write_text(json.dumps({
        'version':APP_VERSION,'runtime_folder':str(sys._MEIPASS),'pid':os.getpid(),
        'archive':os.environ.get('_PYI_ARCHIVE_FILE'),
    }),encoding='utf-8')
    staging=Path(tempfile.mkdtemp(prefix='REQM-FLOW-update-'))/'REQM_FLOW'
    staging.mkdir()
    shutil.copy2(executable,staging/'REQM_FLOW.exe')
    launch_replacer(staging,executable.parent,os.getpid(),restart_test_folder=folder/'after-restart')


def run(folder):
    from selenium.webdriver.edge.options import Options as EdgeOptions
    import pystray
    assert EdgeOptions
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
        service.set_mapping(row['id'],[dict(code='QWC-Q3100S-BK',logistics_code='QWC-Q3100S-BK',name='테스트 상품',quantity=1,unit_amount=0,warehouse='300',customer='DEMO-CUSTOMER')])
        service.request([row['id']],'2026-10-01',folder/'demo-request.xlsx')
        assert service.auto_import_shipments('2026-10-01') == (1,0)
        service.export_erp('2026-10-01','2026-10-01',folder/'demo-erp.xlsx')
        root=tk.Tk();root.withdraw();app=Desktop(root,service);root.update_idletasks()
        assert root.title().startswith('REQM FLOW')
        assert app.cloud_status.get() == '로컬 DB 저장'
        assert [app.workspace_tabs.tab(tab,'text') for tab in app.workspace_tabs.tabs()] == ['주문 · 출고요청','실제출고','출력 이력','설정 · 백업']
        assert [app.settings_tabs.tab(tab,'text') for tab in app.settings_tabs.tabs()] == ['설정 · 백업','매칭 설정','주문 수집']
        assert app.workspace_tabs.select() == str(app.order_frame)

        assert (service.folder/'backups'/'supabase-to-local.sqlite3').exists()
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
        assert (base/'assets/fonts/PretendardVariable.ttf').is_file()
        assert app.font_family in ('Pretendard', '맑은 고딕')
        assert app.matching_sites.get(1) == '스마트스토어 ERP매칭'
        assert tuple(app.confirmed_shipments['columns']) == (
            '구분','출고일','판매처','주문번호','이름','ERP 품목코드','ERP 품목명','출하창고','수량','송장번호',
        )
        assert tuple(app.erp_shipments['columns']) == (
            '실제 출고일','판매처','주문번호','이름','구성품 수','주문 금액','상품명','상품옵션','현재 구성품별 금액',
        )
        assert tuple(app.table['columns']) == (
            '판매처','주문번호','이름','주소','연락처','상품명','매칭품목','출하창고','진행상태','작업구분',
        )
        assert tuple(app.history['columns']) == (
            '출력일(요일)','출고일','종류','판매처','주문번호','수령인','연락처','판매품목','옵션','매칭품목',
            '수량','금액','송장번호','출하창고','비고','등록','묶음 ID',
        )
        assert len(app.item_name_tree.get_children()) == 186
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
        service.export_tracking_day('2026-10-01',folder/'demo-tracking.xlsx',confirmed_only=True)
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
        from .tracking import HEADERS
        from .tracking_store import encode
        combined=folder/'demo-combined-shipping.xlsx'
        combined.write_bytes(workbook_bytes(HEADERS[:10],[
            ['COMBINED-A','오늘의집','데모 상품',1,'가상 수령인','01000000000','00123','실제 배송 금지 테스트 주소','',''],
            ['COMBINED-B','지마켓','데모 상품',1,'가상 수령인','01000000000','00123','실제 배송 금지 테스트 주소','','']]))
        combined_job=service.import_tracking_files([combined],'2026-10-02')[0][0]
        combined_rows=service.tracking_rows(combined_job)
        assert [r['data']['channel'] for r in combined_rows]==['오늘의집','지마켓']
        combined_remote=[{**r['data'],'tracking':'001234567890'} for r in combined_rows]
        with service.db:
            for r in combined_rows:
                broken={**r['data'],'channel':'이알아이','phone':'','recipient':''}
                service.db.execute('UPDATE tracking_rows SET data=? WHERE id=?',(encode(broken),r['id']))
        service.apply_tracking_query(combined_job,combined_remote,'2026-10-02','2026-10-02')
        repaired=service.tracking_rows(combined_job)
        assert [r['data']['channel'] for r in repaired]==['오늘의집','지마켓']
        assert all(r['data']['phone']=='01000000000' and r['state']=='matched' for r in repaired)
        (folder/'self-test.json').write_text(json.dumps({'ok':True,'version':APP_VERSION,'runtime_folder':str(getattr(sys,'_MEIPASS','source')),'orders':1,'artifacts':2,
            'desktop':'OK','font':app.font_family,'storage':'LOCAL','tracking':'OK','combined_import_repair':'OK',
            'workspace_roundtrip':'OK'},ensure_ascii=False),encoding='utf-8')
    except Exception as exc:
        (folder/'self-test.json').write_text(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),encoding='utf-8')
        raise
    finally:
        if root:root.destroy()
        service.close()
