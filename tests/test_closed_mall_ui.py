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
        self.assertIn('kream', self.panel.accounts)

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

    def test_sms_settings_saved_separately_and_disconnected_is_not_ready(self):
        from tkinter import ttk
        from reqm_local.auth_settings import load_settings
        self.panel.manage_accounts('ssf')
        widgets = self.widgets(self.panel.account_window)
        next(w for w in widgets if isinstance(w, ttk.Checkbutton) and w.cget('text') == 'SMS 자동 수신 시도 활성화').invoke()
        next(w for w in widgets if isinstance(w, ttk.Button) and w.cget('text') == '인증 설정 저장').invoke()
        self.assertTrue(load_settings(self.panel.folder)['sms_enabled'])
        self.assertFalse((self.panel.folder / 'accounts.dat').exists())
        self.panel.check_sms()
        self.assertIn('확인 불가', self.panel.sms_status.get())
        self.assertFalse(self.panel.sms_check_running)

    def test_collection_columns_and_live_login_result_do_not_claim_download(self):
        from reqm_local.closed_malls import LoginResult
        self.assertEqual(tuple(self.panel.table['columns']), ('판매처', '로그인', '수집 대상 주문', '엑셀 다운로드', '진행 상태 / 결과'))
        self.panel.selected_run = {'29cm'}
        self.panel.events.put(('login_result', LoginResult('29CM', '성공', '업무 화면 확인', 2.5)))
        self.panel.poll()
        self.assertEqual(self.panel.table.set('29cm', '로그인'), '성공')
        self.assertEqual(self.panel.table.set('29cm', '수집 대상 주문'), '—')
        self.assertEqual(self.panel.table.set('29cm', '엑셀 다운로드'), '—')
        self.assertIn('미구현', self.panel.table.set('29cm', '진행 상태 / 결과'))
        self.assertIn('완료 0', self.panel.summary_text.get())

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
