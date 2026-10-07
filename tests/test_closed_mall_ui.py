import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reqm_local.closed_malls import CodeRequest, MALLS


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


if __name__ == '__main__': unittest.main()
