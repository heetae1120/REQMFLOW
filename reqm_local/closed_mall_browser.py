"""Sequential, local browser login. Unknown layouts stop instead of guessing."""
from __future__ import annotations

import time
import re
from urllib.parse import urlsplit

from .closed_malls import LOGIN_LOCK, CodeRequest, LoginResult, LoginSession, MALLS, MAILBOXES, save_results
from .closed_mall_forms import FORMS, CODE_SELECTOR, SEND_LABELS, VERIFY_LABELS, alert_reason
from .closed_mall_codes import BrowserCodeSource, MESSAGES_URL


class LoginStopped(Exception):
    pass


def authenticated_destination(key, url, text):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    path = parsed.path.lower()
    # An SSO redirect alone does not establish that the dashboard loaded.
    if key == '29cm':
        return host == 'partner-connect.29cm.co.kr' and path.startswith('/dashboard') and any(x in text for x in ('로그아웃', '주문', '대시보드'))
    if key == 'musinsa':
        return host == 'partner.musinsa.com' and not any(x in path for x in ('login', 'oauth')) and any(x in text for x in ('로그아웃', '주문', '대시보드'))
    mall = next(m for m in MALLS if m.key == key)
    if host != urlsplit(mall.url).hostname:
        return False
    if key == 'etbs':
        return path == '/common/pomain' and any(x in text for x in ('로그아웃', '주문', '상품관리'))
    if key == 'ezwel':
        return '주문' in text and '상품관리' in text and '협력사' in text
    if key == 'zigzag':
        return path.startswith('/shop/') and '주문' in text and '상품' in text
    if key in ('ohou', 'kream', 'ably'):
        if any(part in path for part in ('login', 'signin', 'sign-in', 'browser')):
            return False
        return '주문' in text and '상품' in text
    return any(x in text.lower() for x in ('로그아웃', 'logout', 'log out', 'sign out'))


class BrowserLogin:
    def __init__(self, driver, stop, report, ask_code):
        self.driver, self.stop, self.report, self.ask_code = driver, stop, report, ask_code
        self.code_source = None
        self.channel_switched = False
        self.stage = '시작'
        self.auth_started = None

    def check_stop(self):
        if self.stop.is_set():
            raise LoginStopped('작업자가 중단했습니다.')

    def visible(self, selector):
        from selenium.common.exceptions import StaleElementReferenceException
        result = []
        for element in self.driver.find_elements('css selector', selector):
            try:
                if element.is_displayed() and element.is_enabled():
                    result.append(element)
            except StaleElementReferenceException:
                continue
        return result

    def text(self):
        return self.driver.find_element('tag name', 'body').text

    def one(self, selector):
        fields = self.visible(selector)
        if len(fields) != 1:
            raise ValueError('판매처 입력 화면이 변경되었거나 아직 준비되지 않았습니다.')
        return fields[0]

    def click(self, selector):
        self.check_stop()
        element = self.one(selector)
        try:
            element.click()
        except Exception:
            from selenium.webdriver.common.keys import Keys
            element.send_keys(Keys.ENTER)

    def alert(self):
        from selenium.common.exceptions import NoAlertPresentException
        try:
            alert = self.driver.switch_to.alert
            text = alert.text
            reason = alert_reason(text)
            if not reason and any(word in text for word in ('인증', 'SMS', '문자')) and any(word in text for word in ('발송', '전송')):
                alert.accept()
            else:
                alert.dismiss()
            if reason:
                raise ValueError(reason)
            return True
        except NoAlertPresentException:
            return False

    def wait(self, predicate, seconds=30):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.check_stop()
            try:
                value = predicate()
                if value:
                    return value
            except Exception as exc:
                # Only transient DOM changes are retried; browser errors propagate.
                from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
                if not isinstance(exc, (NoSuchElementException, StaleElementReferenceException)):
                    raise
            self.stop.wait(.3)
        raise TimeoutError('화면 확인 시간이 초과되었습니다.')

    def button(self, labels):
        self.check_stop()
        wanted = {re.sub(r'\s+', '', label) for label in labels}
        for item in self.visible('button, input[type=submit], input[type=button], a, label'):
            text = item.text or item.get_attribute('value') or item.get_attribute('aria-label') or item.get_attribute('title') or ''
            if re.sub(r'\s+', '', text) in wanted:
                try:
                    item.click()
                except Exception:
                    from selenium.webdriver.common.keys import Keys
                    item.send_keys(Keys.ENTER)
                return True
        return False

    @staticmethod
    def fill(element, value, blur=True):
        from selenium.webdriver.common.keys import Keys
        element.click()
        element.send_keys(Keys.CONTROL, 'a')
        element.send_keys(value)
        if blur:
            element.send_keys(Keys.TAB)

    def success(self, mall):
        form = FORMS[mall.key]
        if self.visible(form.password) or self.visible(form.code or CODE_SELECTOR):
            return False
        text = self.text()
        if self.visible('[title="로그아웃"], [aria-label="로그아웃"]'):
            text += '\n로그아웃'
        return authenticated_destination(mall.key, self.driver.current_url, text)

    def code(self, mall):
        code = None
        if self.code_source and mall.method != 'manual_sms':
            try:
                code = self.code_source.get(mall)
            except LoginStopped:
                raise
            except Exception:
                self.report(mall.key, '자동 인증번호 수신 실패 · 직접 입력으로 전환')
        if not code:
            if mall.method == 'manual_sms':
                instructions = ('이 계정에 등록된 다른 휴대전화로 받은 새 인증번호를 입력하세요.'
                                + (' 이알아이는 카카오 알림톡을 확인하세요.' if mall.key == 'eri' else ''))
            elif mall.mailbox:
                instructions = f'이번 로그인에서 {MAILBOXES[mall.mailbox][1]}로 받은 새 인증번호를 입력하세요.'
            else:
                instructions = '이번 로그인에서 받은 새 인증번호를 입력하세요. SMS 대상은 REQM CS 전화번호 끝자리 2054입니다.'
            self.report(mall.key, '작업자 인증번호 입력 대기')
            budget = 300 if mall.key == 'eri' else 180
            remaining = max(0, int(budget - (time.monotonic() - (self.auth_started or time.monotonic()))))
            code = self.ask_code(CodeRequest(mall, instructions, timeout=remaining), self.stop)
        self.check_stop()
        if not code or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError('인증번호 입력이 취소되었거나 시간이 만료되었습니다.')
        return code

    def send_code(self, mall, form):
        if form.send and self.visible(form.send):
            self.click(form.send)
        elif not self.button(SEND_LABELS):
            return False
        self.auth_started = time.monotonic()
        self.stop.wait(.4)
        self.alert()
        self.button(('확인',))
        return True

    def submit(self, form):
        if form.submit:
            self.click(form.submit)
        elif not self.button(form.labels):
            raise ValueError('로그인 버튼을 찾지 못했습니다.')

    def duplicate_shopby(self):
        for frame in self.driver.find_elements('css selector', 'iframe'):
            source = frame.get_attribute('src') or ''
            if 'duplicate-login-check' not in source:
                continue
            self.driver.switch_to.frame(frame)
            try:
                self.wait(lambda: '로그인' in self.text(), 10)
                # Keep the site's default concurrent-session choice; never terminate another worker.
                if '기존 로그인 유지' not in self.text():
                    raise ValueError('shop by 중복 로그인 선택 화면을 확인하세요.')
                if not self.button(('로그인 하기', '로그인하기')):
                    raise ValueError('shop by 중복 로그인 확인 버튼을 찾지 못했습니다.')
            finally:
                self.driver.switch_to.default_content()

    def switch_ezwel(self):
        if self.channel_switched:
            return
        # Only exact user-info controls are eligible, never the broad product menu.
        known = self.driver.find_elements('css selector', '#mf_wfm_side_btn_userInfo[title="사용자정보"]')
        if len(known) == 1:
            self.driver.execute_script('arguments[0].click()', known[0])
        elif not self.button(('유저정보', '로그인유저정보', '사용자정보')):
            candidates = self.visible('[title="유저정보"], [title="사용자정보"], [aria-label="유저정보"]')
            if len(candidates) != 1:
                raise ValueError('이지웰 유저정보 버튼을 찾지 못했습니다. 복지샵 전환을 확인하세요.')
            candidates[0].click()
        def choose():
            for row in self.visible('tr, [role=row]'):
                if '복지샵' in row.text and '10064255' in row.text:
                    radios = row.find_elements('css selector', 'input[type=radio]')
                    if len(radios) == 1:
                        self.driver.execute_script('arguments[0].click()', radios[0])
                        return True
            return False
        self.wait(choose)
        choice = self.visible('#mf_wfm_side_userInfoPopup_wframe_btn_choice')
        if len(choice) == 1:
            choice[0].click()
        elif not self.button(('선택',)):
            raise ValueError('이지웰 복지샵 선택 버튼을 찾지 못했습니다.')
        self.wait(lambda: '로그인유저정보' not in self.text() and self.visible('body'))
        self.channel_switched = True

    def login(self, mall, account, background):
        self.channel_switched = False
        self.auth_started = None
        self.driver.get(mall.url)
        self.wait(lambda: self.visible('body'))
        if mall.key == 'handsome' and '접근 권한이 없습니다' in self.text():
            self.driver.get(mall.url)
            self.wait(lambda: self.visible(FORMS[mall.key].password))
        self.wait(lambda: self.success(mall) or self.visible(FORMS[mall.key].password))
        if self.success(mall):
            if mall.key == 'ezwel':
                self.switch_ezwel()
            return '기존 세션의 업무 화면 확인', '기존 세션'
        if not account:
            raise ValueError('계정 엑셀을 불러오세요.')
        # Do not send credentials after an untrusted redirect.
        if urlsplit(self.driver.current_url).hostname != urlsplit(mall.url).hostname:
            raise ValueError('로그인 주소가 예상과 다릅니다. 계정을 입력하지 않았습니다.')
        form = FORMS[mall.key]
        self.wait(lambda: self.visible(form.password))
        self.stage = '아이디 입력'
        self.fill(self.one(form.user), account.user)
        self.stage = '비밀번호 입력'
        self.fill(self.one(form.password), account.password)
        if mall.key == 'ezwel':
            if not account.merchant_code:
                raise ValueError('이지웰 거래처코드가 없습니다. 엑셀 판매처 이름에 거래처코드를 입력하세요.')
            self.fill(self.one('#mf_user_cust'), account.merchant_code)
        if self.code_source:
            self.code_source.prepare(mall)
        self.check_stop()
        if mall.key == 'benepia':
            self.fill(self.one('#preAuthEmail'), 'reqm')
            self.fill(self.one('#tailAuthEmail'), 'reqm.co.kr')
        authenticated = False
        requested = False
        email_selected = False
        login_window = self.driver.current_window_handle
        known_windows = set(self.driver.window_handles)
        auth_popup = None
        if form.send_first:
            requested = self.send_code(mall, form)
            if not requested:
                raise ValueError('인증번호 발송 버튼을 찾지 못했습니다.')
        else:
            self.stage = '로그인 버튼'
            self.auth_started = time.monotonic()
            self.submit(form)
        if mall.key == 'ohou':
            self.wait(lambda: self.success(mall) or '인증 수단을 선택' in self.text())
            if not self.success(mall):
                self.button(('이메일',))
                self.wait(lambda: any(e.is_selected() for e in self.driver.find_elements('css selector', 'input[name=EMAIL_FOR_SIGN_IN]')))
                self.wait(lambda: self.button(('인증하기',)))
                requested = True
                email_selected = True
                self.auth_started = time.monotonic()
        self.stage = '인증/완료 확인'
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            self.check_stop()
            if mall.key == 'wconcept':
                # This vendor opens the SMS form in a separate browser window.
                for handle in set(self.driver.window_handles) - known_windows:
                    self.driver.switch_to.window(handle)
                    parsed = urlsplit(self.driver.current_url)
                    if parsed.hostname == urlsplit(mall.url).hostname and parsed.path.lower() == '/auth/twofactorauth':
                        known_windows.add(handle)
                        auth_popup = handle
                        break
                    self.driver.switch_to.window(login_window)
                if auth_popup and auth_popup not in self.driver.window_handles:
                    self.driver.switch_to.window(login_window)
            self.alert()
            if self.success(mall):
                if mall.key == 'ezwel':
                    self.switch_ezwel()
                    self.wait(lambda: self.success(mall))
                return '업무 화면 확인' + (' · 복지샵 전환' if mall.key == 'ezwel' else ''), '신규 로그인' + (' + 인증번호' if authenticated else '')
            if mall.key == 'shopby':
                self.duplicate_shopby()
            selecting_email = mall.mailbox and (mall.key != 'ohou' or '인증 수단을 선택' in self.text())
            if selecting_email:
                if not email_selected:
                    email_selected = self.button(('이메일', '이메일 인증'))
                    if mall.key == 'ohou':
                        email_selected = email_selected or any(e.is_selected() for e in self.driver.find_elements('css selector', 'input[name=EMAIL_FOR_SIGN_IN]'))
                    if email_selected:
                        self.stop.wait(.3)
            if mall.key == 'ohou' and '인증 수단을 선택' in self.text() and email_selected and not requested:
                if self.button(('인증하기',)):
                    self.auth_started = time.monotonic()
                    requested = True
                    continue
            if mall.key == 'ezwel' and email_selected and not requested:
                email_fields = self.visible('input[id$="emlAdr"]')
                if len(email_fields) == 1:
                    self.fill(email_fields[0], MAILBOXES[mall.mailbox][1])
            reason_fields = self.visible('#conectCont')
            if reason_fields and not reason_fields[0].get_attribute('value'):
                self.fill(reason_fields[0], '주문 업무 로그인')
            fields = self.visible(form.code or CODE_SELECTOR)
            if fields and not authenticated:
                if not requested and self.send_code(mall, form):
                    requested = True
                    continue
                if len(fields) != 1 and not (len(fields) == 6 and all(e.get_attribute('maxlength') == '1' for e in fields)):
                    raise ValueError('인증번호 입력란을 하나로 특정하지 못했습니다.')
                code = self.code(mall)
                if len(fields) == 1:
                    self.fill(fields[0], code, blur=False)
                else:
                    for index, digit in enumerate(code):
                        self.fill(self.visible(form.code or CODE_SELECTOR)[index], digit, blur=False)
                # KREAM can submit immediately when the sixth OTP digit arrives.
                if self.success(mall):
                    authenticated = True
                    continue
                auth_window = self.driver.current_window_handle
                if mall.key == 'kream':
                    self.wait(lambda: self.success(mall) or not self.visible(form.code) or self.button(('로그인',)), 5)
                elif form.send_first:
                    self.submit(form)
                elif form.verify:
                    self.click(form.verify)
                elif not self.button(VERIFY_LABELS):
                    from selenium.webdriver.common.keys import Keys
                    fields[0].send_keys(Keys.ENTER)
                authenticated = True
                deadline = time.monotonic() + 35
                # No automatic retries of an invalid code or repeated SMS sends.
                def verified():
                    if mall.key == 'wconcept' and auth_window not in self.driver.window_handles:
                        self.driver.switch_to.window(login_window)
                    return self.alert() or not self.visible(form.code or CODE_SELECTOR) or self.success(mall)
                self.wait(verified, 15)
                if self.visible(form.code or CODE_SELECTOR) and not self.success(mall):
                    raise ValueError('인증번호 확인을 완료하지 못했습니다. 번호·유효시간을 확인하세요.')
            elif not requested and self.send_code(mall, form):
                requested = True
                deadline = time.monotonic() + 40
            self.stop.wait(.4)
        if self.visible(form.password):
            raise TimeoutError('아이디·비밀번호 제출 후 추가 인증 또는 업무 화면이 열리지 않았습니다. 화면 실행으로 사이트 안내를 확인하세요.')
        raise TimeoutError('로그인 완료 화면을 확인하지 못했습니다. 화면 실행으로 실패 사유를 확인하세요.')


def create_login_driver(folder, background):
    from selenium import webdriver
    options = webdriver.ChromeOptions()
    profile = folder / 'browser-profile'
    profile.mkdir(parents=True, exist_ok=True)
    options.add_argument('--user-data-dir=' + str(profile.resolve()))
    if background:
        options.add_argument('--headless=new')
    options.add_argument('--window-size=1440,1000')
    options.add_experimental_option('prefs', {'credentials_enable_service': False, 'profile.password_manager_enabled': False})
    return webdriver.Chrome(options=options)


def connect_auth_browser(folder):
    if not LOGIN_LOCK.acquire(blocking=False):
        raise RuntimeError('실행 중인 로그인 세션을 닫으세요.')
    session = None
    try:
        session = LoginSession(create_login_driver(folder, False))
        session.driver.set_page_load_timeout(35)
        for index, url in enumerate([item[0] for item in MAILBOXES.values()] + [MESSAGES_URL]):
            if index:
                session.driver.switch_to.new_window('tab')
            session.driver.get(url)
        return session
    except Exception:
        if session:
            session.close()
        else:
            LOGIN_LOCK.release()
        raise


def run_logins(folder, accounts, malls, stop, report, ask_code, background=True, driver_factory=None):
    if not LOGIN_LOCK.acquire(blocking=False):
        raise RuntimeError('폐쇄몰 브라우저가 실행 중입니다. 세션을 닫은 뒤 다시 실행하세요.')
    session = None
    try:
        if driver_factory:
            driver = driver_factory()
        else:
            driver = create_login_driver(folder, background)
        session = LoginSession(driver)
        driver.set_page_load_timeout(35)
        browser = BrowserLogin(driver, stop, report, ask_code)
        browser.code_source = BrowserCodeSource(browser, accounts)
        # There is exactly one worker; both SSO destinations complete sequentially.
        for mall in malls:
            if stop.is_set():
                break
            started = time.monotonic()
            report(mall.key, '로그인 진행 중')
            try:
                if session.results:
                    driver.switch_to.new_window('tab')
                session.channel_tabs[mall.key] = getattr(driver, 'current_window_handle', None)
                reason, mode = browser.login(mall, accounts.get(mall.key), background)
                result = LoginResult(mall.name, '성공', reason, round(time.monotonic()-started, 1), mode)
            except LoginStopped:
                result = LoginResult(mall.name, '중단', '작업자가 중단했습니다.', round(time.monotonic()-started, 1))
            except (ValueError, TimeoutError) as exc:
                result = LoginResult(mall.name, '실패', str(exc), round(time.monotonic()-started, 1))
            except Exception:
                # Selenium errors can contain form values, cookies and request URLs.
                result = LoginResult(mall.name, '실패', '브라우저 연결 또는 사이트 화면 오류. 화면 확인 모드에서 확인하세요.', round(time.monotonic()-started, 1))
            session.results.append(result)
            report(mall.key, result.status + ' · ' + result.reason + f' · {result.seconds}초')
        save_results(folder, session.results)
        return session
    except Exception:
        if session:
            session.close()
        else:
            LOGIN_LOCK.release()
        raise
