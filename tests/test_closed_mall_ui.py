import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reqm_local.closed_malls import Account, CodeRequest, MALLS, load_accounts


@unittest.skipUnless(sys.platform == 'win32', 'Windows Tk UI regression')
class CodeWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        from reqm_local.closed_mall_ui import ClosedMallPanel
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        with patch('reqm_local.closed_mall_ui.local_login_folder', lambda: Path(self.temp.name)):
            self.panel = ClosedMallPanel(ttk.Frame(self.root), self.root)

    def tearDown(self):
        self.panel.shutdown()
        self.root.destroy()
        self.temp.cleanup()

    def widgets(self, widget):
        result = list(widget.winfo_children())
        return result + [descendant for child in result for descendant in self.widgets(child)]

    def test_manual_code_popup_submits_masked_leading_zero(self):
        from tkinter import ttk
        request = CodeRequest(next(m for m in MALLS if m.key == 'eri'), '다른 휴대전화 인증번호')
        self.panel.show_code_window(request)
        widgets = self.widgets(self.panel.code_window)
        entry = next(w for w in widgets if isinstance(w, ttk.Entry))
        self.assertEqual(str(entry.cget('show')), '*')
        entry.insert(0, '012345')
        next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == '인증번호 제출').invoke()
        self.assertEqual(request.code, '012345')
        self.assertTrue(request.ready.is_set())
        self.assertIsNone(self.panel.code_window)

    def test_cancel_and_stale_request(self):
        from tkinter import ttk
        request = CodeRequest(MALLS[0], 'synthetic')
        self.panel.show_code_window(request)
        next(w for w in self.widgets(self.panel.code_window) if isinstance(w, ttk.Button) and w.cget('text') == '이 판매처 취소').invoke()
        self.assertTrue(request.cancelled)
        self.assertIsNone(request.code)
        self.panel.show_code_window(request)
        self.assertIsNone(self.panel.code_window)

    def account_controls(self, key):
        from tkinter import ttk
        self.panel.manage_accounts(key)
        widgets = self.widgets(self.panel.account_window)
        entries = [w for w in widgets if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox)]
        button = next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == '계정 저장')
        return entries, button

    def test_account_editor_encrypts_new_password_and_preserves_other_accounts(self):
        self.panel.accounts = {'29cm': Account('other', 'untouched')}
        entries, save = self.account_controls('kream')
        self.assertEqual(str(entries[1].cget('show')), '*')
        entries[0].insert(0, 'synthetic@example.com')
        entries[1].insert(0, ' new secret ')
        save.invoke()
        loaded = load_accounts(self.panel.folder)
        self.assertEqual(loaded['kream'].password, ' new secret ')
        self.assertEqual(loaded['29cm'].password, 'untouched')
        self.assertEqual(entries[1].get(), '')
        self.assertNotIn(b' new secret ', (self.panel.folder / 'accounts.dat').read_bytes())
        self.assertEqual(self.panel.table.set('kream', '계정'), '등록됨')

    def test_existing_password_is_not_shown_and_blank_edit_preserves_it(self):
        self.panel.accounts = {'mail_reqm': Account('old', ' private ')}
        entries, save = self.account_controls('mail_reqm')
        self.assertEqual(entries[1].get(), '')
        entries[0].delete(0, 'end')
        entries[0].insert(0, 'new')
        save.invoke()
        loaded = load_accounts(self.panel.folder)
        self.assertEqual(loaded['mail_reqm'].user, 'new')
        self.assertEqual(loaded['mail_reqm'].password, ' private ')

    def test_ezwel_requires_merchant_code_and_preserves_leading_zero(self):
        entries, save = self.account_controls('ezwel')
        entries[0].insert(0, 'synthetic')
        entries[1].insert(0, 'synthetic-secret')
        save.invoke()
        self.assertNotIn('ezwel', self.panel.accounts)
        self.assertFalse((self.panel.folder / 'accounts.dat').exists())
        entries[2].insert(0, '001234')
        save.invoke()
        self.assertEqual(load_accounts(self.panel.folder)['ezwel'].merchant_code, '001234')

    def test_save_failure_does_not_change_account_and_running_blocks_editor(self):
        self.panel.accounts = {'kream': Account('old', 'old-secret')}
        entries, save = self.account_controls('kream')
        entries[1].insert(0, 'replacement')
        with patch('reqm_local.closed_mall_ui.save_accounts', side_effect=OSError('synthetic')):
            save.invoke()
        self.assertEqual(self.panel.accounts['kream'].password, 'old-secret')
        next(w for w in self.widgets(self.panel.account_window) if w.winfo_class() == 'TButton' and w.cget('text') == '닫기').invoke()
        self.panel.running = True
        self.panel.manage_accounts('kream')
        self.assertIsNone(self.panel.account_window)


if __name__ == '__main__': unittest.main()
