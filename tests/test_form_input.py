import unittest
from unittest.mock import patch
from tests import test_erp_workflow as fixture
from reqm_local.ui_helpers import after_latest

class FormInputTests(unittest.TestCase):
    def setUp(self):
        fixture.ErpWorkflowTests.setUp(self)
        self.root.deiconify();self.root.minsize(800,500);self.root.geometry('1100x650')
        self.app.workspace_tabs.select(2);self.app.settings_tabs.select(self.app.matching_frame)
        self.root.update()

    def tearDown(self):fixture.ErpWorkflowTests.tearDown(self)

    def wait_input(self):
        self.root.after(220,self.root.quit);self.root.mainloop()

    def test_matching_form_scrolls_to_bottom_and_wheel_never_changes_columns(self):
        app=self.app;canvas=app.matching_form._reqm_scroll_surface
        self.assertLess(canvas.yview()[1],1)
        box=app.mapping_boxes['product'];old=box.get()
        box.event_generate('<MouseWheel>',delta=-120);self.root.update()
        self.assertEqual(box.get(),old)
        self.assertGreater(canvas.yview()[0],0)
        canvas.yview_moveto(1);self.root.update()
        def descendants(w):
            for child in w.winfo_children():yield child;yield from descendants(child)
        save=next(w for w in descendants(app.matching_form) if w.winfo_class()=='TButton' and str(w.cget('text'))=='이 판매처 매칭 저장')
        self.assertGreaterEqual(save.winfo_rooty(),canvas.winfo_rooty())
        self.assertLessEqual(save.winfo_rooty()+save.winfo_height(),canvas.winfo_rooty()+canvas.winfo_height()+2)

    def test_input_is_immediate_but_order_query_runs_once_for_a_burst(self):
        with patch.object(self.app,'refresh_orders') as refresh,patch.object(self.app,'update_search_suggestions'):
            for value in ('품','품목','품목 금','품목 금액'):self.app.search.set(value)
            self.assertEqual(self.app.search.get(),'품목 금액')
            refresh.assert_not_called()
            self.wait_input();refresh.assert_called_once()

    def test_latest_callback_only_and_destroy_cancels_pending_work(self):
        calls=[];box=self.app.mapping_boxes['product']
        for i in range(10):after_latest(box,'test',lambda i=i:calls.append(i))
        self.wait_input();self.assertEqual(calls,[9])
        after_latest(box,'test',lambda:calls.append(10));box.destroy()
        self.wait_input();self.assertEqual(calls,[9])
