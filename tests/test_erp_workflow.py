import os
import tkinter as tk
import unittest
from unittest.mock import patch

from tests import test_voucher as fixture
from reqm_local.desktop import Desktop
from reqm_local.service import encode
from reqm_local.workspace_cloud import export_workspace, workspace_digest


class ErpWorkflowTests(unittest.TestCase):
    def setUp(self):
        fixture.VoucherTests.setUp(self)
        original=fixture.VoucherTests.order(self)
        self.s.set_voucher_amounts(original['id'],34900,[28000,6900])
        component={k:v for k,v in original['components'][0].items() if k not in ('entry_id','index')}
        for table,channel,identity,amount in [('smartstore_erp_rows','리큐엠_스마트스토어','SMART',29500),('esm_erp_rows','옥션','ESM',19500)]:
            data={**original['data'],'channel':channel,'order_no':identity,'line_no':identity,
                  'quantity':'1','unit_amount':str(amount),'amount':str(amount),'shipping':'0','source_file':identity+'.xlsx'}
            fields={**component,'quantity':1,'amount':str(amount)}
            with self.s.db:
                self.s.db.execute(f'INSERT INTO {table}(id,identity,day,data,components,issue) VALUES(?,?,?,?,?,?)',
                    (identity,identity,fixture.DAY,encode(data),encode([fields]),''))
        self.root=tk.Tk();self.root.withdraw()
        with patch.dict(os.environ,{'REQM_SELF_TEST':'1'}):self.app=Desktop(self.root,self.s)
        self.app.erp_ship_from.set(fixture.DAY)
        self.app.erp_ship_through.set(fixture.DAY)
        self.root.update_idletasks()

    def tearDown(self):
        for callback in self.root.tk.call('after','info'):
            self.root.after_cancel(callback)
        self.root.destroy()
        fixture.VoucherTests.tearDown(self)

    def widgets(self,parent):
        for widget in parent.winfo_children():
            yield widget
            yield from self.widgets(widget)

    def test_four_steps_keep_dates_and_data_and_have_one_export_button(self):
        app=self.app
        self.assertEqual([app.result_tabs.tab(t,'text') for t in app.result_tabs.tabs()],
            ['1  출고·정산 자료 입력','2  품목·금액 매칭','3  전표 검수·ERP 생성','4  출력 이력'])
        before=workspace_digest(export_workspace(self.s))
        for index in (0,1,2,3):
            app.select_workflow_step(index)
            self.assertEqual(app.result_tabs.select(),str(app.workflow_frames[index]))
        self.assertEqual(app.voucher_panel.start.get(),fixture.DAY)
        self.assertEqual(app.voucher_panel.end.get(),fixture.DAY)
        self.assertEqual(workspace_digest(export_workspace(self.s)),before)
        buttons=[w for w in self.widgets(app.result_frame) if w.winfo_class()=='TButton' and str(w.cget('text'))=='ERP 파일 생성']
        self.assertEqual(len(buttons),1)
        self.assertIn(buttons[0],list(self.widgets(app.workflow_frames[2])))
        self.assertIn(app.history,list(self.widgets(app.workflow_frames[3])))

    def test_manual_smartstore_input_is_separate_from_flow_shipments(self):
        app=self.app;app.refresh_confirmed_shipments()
        self.assertEqual(len(app.confirmed_shipments.get_children()),2)
        self.assertEqual(len(app.smartstore_inputs.get_children()),1)
        app.source_tabs.select(app.smartstore_source_frame)
        key=app.smartstore_inputs.get_children()[0];app.smartstore_inputs.selection_set(key)
        self.assertTrue(app.selected_confirmed_entry()['id'].startswith('SSERP:'))
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0],1)

    def test_preview_and_export_share_scope_and_channel_exclusions(self):
        panel=self.app.voucher_panel
        panel.start.set(fixture.DAY);panel.end.set(fixture.DAY)
        self.app.erp_excluded_channels={'스마트스토어'}
        panel.refresh()
        self.assertEqual({g['kind'] for g in panel.groups()},{'shipment','esm'})
        panel.output_scope.set('옥션·지마켓만');panel.scope_changed()
        self.assertEqual({g['kind'] for g in panel.groups()},{'esm'})
        before=workspace_digest(export_workspace(self.s))
        with patch.object(self.s,'export_erp',wraps=self.s.export_erp) as export,patch.object(self.app,'save_path',return_value=None):
            panel.preview()
            preview=export.call_args.kwargs.copy()
            panel.export()
            self.assertEqual(preview,export.call_args.kwargs)
            self.assertTrue(preview['only_esm'])
            self.assertEqual(preview['excluded_channels'],{'스마트스토어'})
        self.assertEqual(workspace_digest(export_workspace(self.s)),before)

    def test_imported_smartstore_file_selects_original_payment_date(self):
        self.app.show_smartstore_import_period('SMART.xlsx')
        self.assertEqual(self.app.erp_ship_from.get(),fixture.DAY)
        self.assertEqual(self.app.erp_ship_through.get(),fixture.DAY)
        self.assertEqual(self.app.source_tabs.select(),str(self.app.smartstore_source_frame))


if __name__=='__main__':unittest.main()
