import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl

from reqm_local.closed_malls import Account, MALLS, CodeRequest, LOGIN_LOCK, account_key, extract_code, read_account_workbook, save_accounts, load_accounts
from reqm_local.closed_mall_forms import FORMS, alert_reason
from reqm_local.closed_mall_codes import message_id, authentication_mail, message_code
from reqm_local.closed_mall_browser import authenticated_destination, BrowserLogin, run_logins


class ClosedMallTests(unittest.TestCase):
    def test_manual_channels_import_routes_and_forms(self):
        self.assertEqual(len(MALLS), 19)
        self.assertEqual(set(FORMS), {m.key for m in MALLS})
        self.assertEqual({m.key for m in MALLS if m.method == 'manual_sms'}, {'eri', 'samsung', 'handsome'})
        for mall in MALLS:
            self.assertEqual(account_key(mall.url), mall.key)

    def test_code_request_leading_zero_validation_and_single_use(self):
        request = CodeRequest(MALLS[0], 'synthetic request')
        self.assertFalse(request.submit('１２３４５６'))
        self.assertFalse(request.submit('12345'))
        self.assertTrue(request.submit('012345'))
        self.assertEqual(request.code, '012345')
        self.assertFalse(request.submit('654321'))
        self.assertNotIn('012345', repr(request))

    def test_expired_cancelled_request_never_accepts_code(self):
        request = CodeRequest(MALLS[0], 'synthetic request', timeout=0)
        self.assertFalse(request.submit('123456'))
        request = CodeRequest(MALLS[0], 'synthetic request')
        request.cancel()
        self.assertFalse(request.submit('123456'))
        self.assertTrue(request.ready.is_set())
        self.assertIsNone(request.code)

    def test_mail_matching_and_message_identity(self):
        mall = next(m for m in MALLS if m.key == 'kream')
        self.assertTrue(authentication_mail(mall, '[KREAM] 판매자센터 OTP'))
        self.assertFalse(authentication_mail(mall, '[KREAM] 주문번호 안내'))
        self.assertFalse(authentication_mail(mall, '[BENEPIA] 인증번호 안내'))
        self.assertEqual(message_id('https://webmail.reqm.co.kr/user/mail/main.php?page=read&idx=123'), '123')
        self.assertIsNone(message_id('https://webmail.reqm.co.kr/user/mail/main.php?page=read&idx='))
        self.assertEqual(message_code('OTP: 012345'), '012345')
        self.assertIsNone(message_code('012345'))
        self.assertEqual(message_code('012345', authenticated_mail=True), '012345')
        self.assertIsNone(message_code('012345 654321', authenticated_mail=True))

    def test_site_errors_redact_raw_values(self):
        message = alert_reason('비밀번호 synthetic-secret 가 일치하지 않습니다')
        self.assertIsNotNone(message)
        self.assertNotIn('synthetic-secret', message)
    def test_sso_accounts_have_distinct_routes(self):
        routes = {m.key: account_key(m.url) for m in MALLS}
        self.assertEqual(routes['musinsa'], 'musinsa')
        self.assertEqual(routes['29cm'], '29cm')
        self.assertIsNone(account_key('https://partner-sso.one.musinsa.com.evil.test/oauth/login'))
        self.assertIsNone(account_key('https://user:password@partner.musinsa.com'))
        self.assertIsNone(account_key('https://partner-sso.one.musinsa.com/oauth/login?platform=29cm&clientId=MUSINSA_PARTNER'))

    def test_workbook_password_spaces_and_merchant_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accounts.xlsx'
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.title = '계정입력양식'
            sheet.append(['판매처·서비스명', '아이디', '비밀번호 (직접 입력)', 'URL'])
            sheet.append(['이지웰 거래처 코드 1437423', ' demo ', ' secret ', next(m.url for m in MALLS if m.key == 'ezwel')])
            sheet.append(['untrusted', 'demo', 'secret', 'https://evil.test'])
            book.save(path)
            accounts = read_account_workbook(path)
            self.assertEqual(set(accounts), {'ezwel'})
            self.assertEqual(accounts['ezwel'].password, ' secret ')
            self.assertEqual(accounts['ezwel'].merchant_code, '1437423')
            self.assertNotIn('secret', repr(accounts['ezwel']))

    def test_dpapi_roundtrip_and_no_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            save_accounts(directory, {'29cm': Account('synthetic-user', 'synthetic-secret')})
            self.assertNotIn(b'synthetic-secret', (Path(directory)/'accounts.dat').read_bytes())
            self.assertEqual(load_accounts(directory)['29cm'].password, 'synthetic-secret')

    def test_authentication_code_requires_label(self):
        self.assertEqual(extract_code('인증번호는 [012345]입니다'), '012345')
        self.assertIsNone(extract_code('주문번호 012345'))
        self.assertIsNone(extract_code('인증번호 1234567'))

    def test_intermediate_sso_page_never_succeeds(self):
        self.assertFalse(authenticated_destination('29cm', next(m.url for m in MALLS if m.key == '29cm'), '로그아웃 주문'))
        self.assertFalse(authenticated_destination('29cm', 'https://partner-connect.29cm.co.kr/dashboard', '로딩 중'))
        self.assertTrue(authenticated_destination('29cm', 'https://partner-connect.29cm.co.kr/dashboard', '주문 관리'))

    def test_sequential_sso_and_lock_released_on_close(self):
        class Driver:
            switch_to = None
            def __init__(self): self.switch_to = self
            def set_page_load_timeout(self, value): pass
            def new_window(self, kind): pass
            def quit(self): pass
        calls = []
        def login(browser, mall, account, background):
            calls.append(mall.key)
            return 'test dashboard', 'test'
        with tempfile.TemporaryDirectory() as directory, patch.object(BrowserLogin, 'login', login):
            malls = [m for m in MALLS if m.shared_login]
            session = run_logins(Path(directory), {}, malls, threading.Event(), lambda *args: None, lambda *args: None, driver_factory=Driver)
            try:
                self.assertEqual(calls, ['musinsa', '29cm'])
                self.assertFalse(LOGIN_LOCK.acquire(blocking=False))
                result = json.loads(next((Path(directory)/'runs').iterdir()).read_text(encoding='utf-8'))
                self.assertEqual(len(result['results']), 2)
            finally:
                session.close()
            self.assertTrue(LOGIN_LOCK.acquire(blocking=False))
            LOGIN_LOCK.release()

    def test_failed_channel_does_not_abort_next(self):
        class Driver:
            def __init__(self): self.switch_to = self
            def set_page_load_timeout(self, value): pass
            def new_window(self, kind): pass
            def quit(self): pass
        def login(browser, mall, account, background):
            if mall.key == 'musinsa': raise ValueError('입력 화면 변경')
            return '업무 화면 확인', 'test'
        with tempfile.TemporaryDirectory() as directory, patch.object(BrowserLogin, 'login', login):
            session = run_logins(Path(directory), {}, [m for m in MALLS if m.shared_login], threading.Event(), lambda *a: None, lambda *a: None, driver_factory=Driver)
            try:
                self.assertEqual([r.status for r in session.results], ['실패', '성공'])
            finally:
                session.close()


if __name__ == '__main__':
    unittest.main()
