"""Opt-in real browser regression with synthetic local login pages."""
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from reqm_local.closed_malls import Account, Mall
from reqm_local.closed_mall_browser import BrowserLogin, create_login_driver


HTML = '''<!doctype html><meta charset="utf-8"><body>
<input name="p" id="loginId"><input type="password" name="c" id="password">
<input name="o" id="loginSmsCtfNo" placeholder="인증번호" maxlength="6">
<button id="lfBtnTr1" onclick="send()">인증번호 발송</button>
<button id="btn_secon" onclick="send()">인증번호 받기</button>
<button id="btnLogin" onclick="login()">로그인</button>
<script>
let sent=false;
function send(){sent=true;document.querySelectorAll('#lfBtnTr1,#btn_secon').forEach(e=>e.style.display='none');alert('인증번호를 발송했습니다.');}
function login(){
if(document.getElementById('loginId').value!=='demo' || document.getElementById('password').value!==' secret '){alert('아이디 또는 비밀번호가 일치하지 않습니다.');return;}
if(!sent || document.getElementById('loginSmsCtfNo').value!=='012345'){alert('인증번호가 일치하지 않습니다.');return;}
document.body.innerHTML='<p>로그아웃 주문 상품</p>';history.pushState({},'', '/done');
}
</script></body>'''

SSO_HTML = '''<!doctype html><meta charset="utf-8"><body>
<input type="text"><input type="password"><button onclick="begin()">로그인</button>
<script>
let sent=false;
function begin(){document.body.innerHTML='<label>OTP</label><label onclick="email()">이메일</label><input placeholder="인증코드 입력"><button onclick="verify()">인증하기</button>';}
function email(){let b=document.createElement('button');b.textContent='인증번호 받기';b.onclick=()=>{sent=true;b.remove();alert('인증번호를 발송했습니다.');};document.body.appendChild(b);}
function verify(){if(!sent || document.querySelector('input').value!=='012345'){alert('인증번호가 일치하지 않습니다.');return;}document.body.innerHTML='<p>로그아웃 주문 상품</p>';history.pushState({},'', '/done');}
</script></body>'''

OHOU_HTML = '''<!doctype html><meta charset="utf-8"><body>
<label>이메일</label><input name="email"><input name="password" type="password"><button onclick="begin()">로그인</button>
<script>
function begin(){document.body.innerHTML='<p>인증 수단을 선택해 주세요.</p><input name="EMAIL_FOR_SIGN_IN" type="radio" checked><button onclick="code()">인증하기</button>';}
function code(){document.body.innerHTML='<input name="verificationCode" type="number" onkeydown="verify(event)"><button>인증 취소</button>';}
function verify(e){if(e.key==='Enter' && e.target.value==='012345'){document.body.innerHTML='<p>로그아웃 주문 상품</p>';history.pushState({},'', '/done');}}
</script></body>'''

WCONCEPT_HTML = '''<!doctype html><meta charset="utf-8"><body>
<input id="userid"><input id="pw" type="password"><button onclick="window.open('/Auth/TwoFactorAuth','auth')">관리자 로그인</button>
</body>'''
WCONCEPT_AUTH_HTML = '''<!doctype html><meta charset="utf-8"><body>
<input placeholder="인증번호를 입력해주세요."><button onclick="sent=true;this.remove()">인증번호 발송</button>
<button onclick="verify()">확인</button><script>
let sent=false;function verify(){if(sent && document.querySelector('input').value==='012345'){opener.document.body.innerHTML='<p>로그아웃 주문 상품</p>';opener.history.pushState({},'', '/done');window.close();}}
</script></body>'''
KREAM_HTML = '''<!doctype html><meta charset="utf-8"><body>
<input name="email"><input name="password" type="password"><button onclick="code()">다음</button>
<script>function code(){document.body.innerHTML='<input placeholder="OTP 입력" maxlength="6" oninput="verify(this)">';}
function verify(e){if(e.value==='012345'){document.body.innerHTML='<p>로그아웃 주문 상품</p>';history.pushState({},'', '/done');}}
</script></body>'''


@unittest.skipUnless(os.environ.get('REQM_LOGIN_BROWSER_TEST') == '1', 'opt-in browser regression')
class BrowserRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                html = HTML
                if self.path == '/sso':
                    html = SSO_HTML
                if self.path == '/ohou':
                    html = OHOU_HTML
                if self.path == '/wconcept':
                    html = WCONCEPT_HTML
                if self.path == '/Auth/TwoFactorAuth':
                    html = WCONCEPT_AUTH_HTML
                if self.path == '/kream':
                    html = KREAM_HTML
                if self.path == '/handsome':
                    html = html.replace('loginId', 'userId').replace('loginSmsCtfNo', 'smsAuthNo')
                    html = html.replace('<input name="o"', '<input style="display:none" name="o"')
                    html = html.replace('function login(){', "function login(){if(document.getElementById('smsAuthNo').style.display==='none'){document.getElementById('smsAuthNo').style.display='block';return;}")
                self.wfile.write(html.encode('utf-8'))
            def log_message(self, *args): pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.temp = tempfile.TemporaryDirectory()
        cls.driver = create_login_driver(Path(cls.temp.name), True)
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port) + '/login'

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def browser(self, code):
        self.prompts = []
        def ask(request, stop):
            self.prompts.append(request)
            return code
        return BrowserLogin(self.driver, threading.Event(), lambda *a: None, ask)

    def test_ohou_email_method_then_number_code(self):
        browser = self.browser('012345')
        mall = Mall('ohou', '오늘의집', self.url.replace('/login', '/ohou'), 'email', 'orora')
        with patch('reqm_local.closed_mall_browser.authenticated_destination', side_effect=lambda key, url, text: url.endswith('/done')):
            result = browser.login(mall, Account('demo', ' secret '), True)
        self.assertIn('업무 화면 확인', result[0])
        self.assertEqual(len(self.prompts), 1)

    def test_wconcept_popup_returns_to_parent(self):
        browser = self.browser('012345')
        mall = Mall('wconcept', 'W컨셉', self.url.replace('/login', '/wconcept'), 'sms')
        with patch('reqm_local.closed_mall_browser.authenticated_destination', side_effect=lambda key, url, text: url.endswith('/done')):
            result = browser.login(mall, Account('demo', ' secret '), True)
        self.assertIn('업무 화면 확인', result[0])
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(len(self.driver.window_handles), 1)

    def test_kream_sixth_digit_auto_submits(self):
        browser = self.browser('012345')
        mall = Mall('kream', '크림', self.url.replace('/login', '/kream'), 'email', 'reqm')
        with patch('reqm_local.closed_mall_browser.authenticated_destination', side_effect=lambda key, url, text: url.endswith('/done')):
            result = browser.login(mall, Account('demo', ' secret '), True)
        self.assertIn('업무 화면 확인', result[0])
        self.assertEqual(len(self.prompts), 1)

    def test_eri_request_before_submit_and_leading_zero(self):
        browser = self.browser('012345')
        mall = Mall('eri', '이알아이', self.url, 'manual_sms')
        with patch('reqm_local.closed_mall_browser.authenticated_destination', lambda key, url, text: url.endswith('/done') and '로그아웃' in text):
            reason, mode = browser.login(mall, Account('demo', ' secret '), True)
        self.assertIn('인증번호', mode)
        self.assertEqual(len(self.prompts), 1)
        self.assertIn('카카오 알림톡', self.prompts[0].instructions)

    def test_samsung_manual_prompt_and_submit(self):
        browser = self.browser('012345')
        mall = Mall('samsung', '삼성카드복지몰', self.url, 'manual_sms')
        with patch('reqm_local.closed_mall_browser.authenticated_destination', lambda key, url, text: url.endswith('/done')):
            browser.login(mall, Account('demo', ' secret '), True)
        self.assertEqual(len(self.prompts), 1)
        self.assertIn('다른 휴대전화', self.prompts[0].instructions)

    def test_cancelled_code_never_submits_login(self):
        browser = self.browser(None)
        mall = Mall('eri', '이알아이', self.url, 'manual_sms')
        with self.assertRaisesRegex(ValueError, '취소'):
            browser.login(mall, Account('demo', ' secret '), True)
        self.assertTrue(self.driver.current_url.endswith('/login'))

    def test_handsome_code_after_credentials(self):
        browser = self.browser('012345')
        mall = Mall('handsome', '한섬', self.url.replace('/login', '/handsome'), 'manual_sms')
        with patch('reqm_local.closed_mall_browser.authenticated_destination', lambda key, url, text: url.endswith('/done')):
            browser.login(mall, Account('demo', ' secret '), True)
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.prompts[0].mall.key, 'handsome')

    def test_invalid_code_is_not_retried(self):
        browser = self.browser('654321')
        mall = Mall('samsung', '삼성카드복지몰', self.url, 'manual_sms')
        with self.assertRaisesRegex(ValueError, '거절'):
            browser.login(mall, Account('demo', ' secret '), True)
        self.assertEqual(len(self.prompts), 1)

    def test_sso_selects_email_instead_of_default_otp(self):
        browser = self.browser('012345')
        mall = Mall('musinsa', '무신사', self.url.replace('/login', '/sso'), 'email', 'reqm', shared_login='musinsa_sso')
        with patch('reqm_local.closed_mall_browser.authenticated_destination', lambda key, url, text: url.endswith('/done')):
            browser.login(mall, Account('demo', ' secret '), True)
        self.assertEqual(len(self.prompts), 1)
        self.assertIn('reqm@reqm.co.kr', self.prompts[0].instructions)


if __name__ == '__main__': unittest.main()
