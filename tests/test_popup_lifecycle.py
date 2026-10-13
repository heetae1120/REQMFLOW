import tkinter as tk
from tkinter import ttk
import unittest

from reqm_local.ui_helpers import bind_wide_combobox,post_combobox


class PopupLifecycleTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.geometry('500x300+20+20')
        self.tabs=ttk.Notebook(self.root);self.tabs.pack(fill='both',expand=True)
        self.first=ttk.Frame(self.tabs);self.other=ttk.Frame(self.tabs)
        self.tabs.add(self.first,text='첫 화면');self.tabs.add(self.other,text='다른 화면')
        self.box=ttk.Combobox(self.first,values=['미사용','주문일시','순번']);self.box.pack()
        bind_wide_combobox(self.box)
        self.root.update();self.box.focus_force();self.root.update()
        if self.root.focus_get()!=self.box:
            self.root.destroy();self.skipTest('Interactive Tk focus unavailable')

    def tearDown(self):
        if hasattr(self,'root'):
            try:
                for job in self.root.tk.call('after','info'):self.root.after_cancel(job)
                self.root.destroy()
            except tk.TclError:
                pass

    def open(self):
        self.box._reqm_popup_suppressed=False
        post_combobox(self.box,['미사용','주문일시','순번'])
        self.root.update()
        self.assertTrue(self.box._reqm_popup.winfo_viewable())

    def test_selection_closes_list_even_if_selected_handler_requests_reopen(self):
        self.open()
        self.box.bind('<<ComboboxSelected>>',lambda _:post_combobox(self.box,['미사용','주문일시','순번']))
        self.box._reqm_popup_list.event_generate('<ButtonRelease-1>',x=8,y=8)
        self.root.update()
        self.assertEqual(self.box.get(),'미사용')
        self.assertFalse(self.box._reqm_popup.winfo_viewable())
        self.box._reqm_popup_list.event_generate('<ButtonRelease-1>',x=8,y=40)
        self.root.update();self.assertEqual(self.box.get(),'미사용')

    def test_tab_change_hides_list_and_stale_click_cannot_edit_hidden_input(self):
        self.box.set('원래값');self.open()
        self.tabs.select(self.other);self.root.update()
        self.assertFalse(self.box._reqm_popup.winfo_viewable())
        self.box._reqm_popup_list.event_generate('<ButtonRelease-1>',x=8,y=8)
        self.root.update();self.assertEqual(self.box.get(),'원래값')
        post_combobox(self.box,['새값']);self.root.update()
        self.assertFalse(self.box._reqm_popup.winfo_viewable())

    def test_modal_dialog_closes_list_and_blocks_stale_selection(self):
        self.box.set('원래값');self.open()
        dialog=tk.Toplevel(self.root);dialog.grab_set();self.root.update()
        self.assertFalse(self.box._reqm_popup.winfo_viewable())
        self.box._reqm_popup_list.event_generate('<ButtonRelease-1>',x=8,y=8)
        self.root.update();self.assertEqual(self.box.get(),'원래값')
        dialog.grab_release();dialog.destroy()

    def test_enter_selects_and_escape_dismisses(self):
        self.open();self.box._reqm_popup_list.selection_set(1)
        self.box.event_generate('<Return>');self.root.update()
        self.assertEqual(self.box.get(),'주문일시')
        self.assertFalse(self.box._reqm_popup.winfo_viewable())
        self.box.focus_force();self.open()
        self.box.event_generate('<Escape>');self.root.update()
        self.assertFalse(self.box._reqm_popup.winfo_viewable())
