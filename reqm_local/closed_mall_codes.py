"""Read only newly arrived authentication messages in the dedicated profile."""
import re
import time
from urllib.parse import urljoin, urlsplit, parse_qs

from .closed_malls import MAILBOXES, extract_code


MAIL_WORDS = {
    'musinsa': ('무신사', 'musinsa', '29cm'), '29cm': ('무신사', 'musinsa', '29cm'),
    'benepia': ('베네피아', 'benepia'), 'ezwel': ('이지웰', 'ezwel'),
    'ohou': ('오늘의집', 'ohou', 'o.rora'), 'kream': ('kream', '크림'),
    'hmall': ('현대홈쇼핑', 'hmall'),
}
MESSAGES_URL = 'https://messages.google.com/web/conversations'


def message_id(url):
    value = parse_qs(urlsplit(url).query).get('idx', [''])[0]
    return value if value.isdigit() else None


def authentication_mail(mall, text):
    lower = text.lower()
    return any(x in lower for x in MAIL_WORDS.get(mall.key, ())) and any(x in lower for x in ('인증', 'otp', 'verification'))


def message_code(text, authenticated_mail=False):
    code = extract_code(text)
    if code:
        return code
    match = re.search(r'(?:OTP|verification code|인증코드)\s*[:：]?\s*(\d{6})(?!\d)', text, re.I)
    if match:
        return match.group(1)
    if authenticated_mail:
        # Only used after verifying a new message ID and vendor authentication subject.
        candidates = set(re.findall(r'(?<!\d)\d{6}(?!\d)', text))
        if len(candidates) == 1:
            return candidates.pop()
    return None


class BrowserCodeSource:
    def __init__(self, browser, accounts, sms_account='reqm.cs@gmail.com'):
        self.browser = browser
        self.driver = browser.driver
        self.accounts = accounts
        self.sms_account = sms_account
        self.tabs = {}
        self.baseline = {}

    def _tab(self, name, url):
        if name not in self.tabs:
            self.driver.switch_to.new_window('tab')
            self.tabs[name] = self.driver.current_window_handle
        else:
            self.driver.switch_to.window(self.tabs[name])
        self.driver.get(url)
        self.browser.wait(lambda: self.browser.visible('body'))

    def _mail(self, name, mall):
        address, recipient = MAILBOXES[name]
        self._tab(name, address)
        if urlsplit(self.driver.current_url).hostname != urlsplit(address).hostname:
            raise ValueError('메일 로그인 주소가 예상과 다릅니다.')
        if self.browser.visible('input[type=password]'):
            account = self.accounts.get('mail_' + name)
            if not account:
                raise ValueError('메일 계정이 미등록입니다.')
            self.browser.fill(self.browser.one('input[name=mail]'), account.user)
            self.browser.fill(self.browser.one('input[name=password]'), account.password)
            if not self.browser.button(('로그인',)):
                raise ValueError('메일 로그인 양식이 변경되었습니다.')
        self.browser.wait(lambda: recipient in self.browser.text())
        self.driver.get(urljoin(address, '/user/mail/main.php?page=list&mbox=INBOX'))
        self.browser.wait(lambda: recipient in self.browser.text() and not self.browser.visible('input[type=password]'))
        # Authentication mail may be automatically filed by Cafe24 rules.
        # Use the observed all-mailbox search rather than guessing a private folder URL.
        from selenium.webdriver.support.ui import Select
        Select(self.browser.one('select[name=mbox]')).select_by_value('')
        Select(self.browser.one('select[name=keyField]')).select_by_value('')
        self.browser.fill(self.browser.one('input[name=keyWord]'), MAIL_WORDS[mall.key][0])
        if not self.browser.button(('검색',)):
            raise ValueError('메일 전체 검색 버튼을 찾지 못했습니다.')
        self.browser.wait(lambda: self._links(), 12)

    def _links(self):
        links = []
        for element in self.driver.find_elements('css selector', 'a[href*="page=read"]'):
            url = element.get_attribute('href') or ''
            if not message_id(url):
                continue
            rows = element.find_elements('xpath', 'ancestor::tr[1]')
            links.append((url, rows[0].text if rows else element.text))
        return links

    def _sms_rows(self, mall):
        rows = self.browser.visible('mws-conversation-list-item')
        expected = re.sub(r'\D', '', mall.sender)
        return [e.text for e in rows if e.text.splitlines() and re.sub(r'\D', '', e.text.splitlines()[0]) == expected]

    def _sms(self):
        self._tab('sms', MESSAGES_URL)
        self.browser.wait(lambda: self.browser.visible('mws-conversation-list-item'), 12)
        labels = [e.get_attribute('aria-label') or '' for e in self.driver.find_elements('css selector', '[aria-label]')]
        if not any(self.sms_account.lower() in label.lower() for label in labels):
            raise ValueError('Google 메시지를 REQM CS 계정으로 연결하세요.')

    def prepare(self, mall):
        if not mall.automatic_code or mall.method == 'manual_sms' or not (mall.mailbox or mall.sender):
            return
        original = self.driver.current_window_handle
        try:
            if mall.mailbox:
                self._mail(mall.mailbox, mall)
                links = self.browser.wait(lambda: self._links(), 12)
                self.baseline[mall.key] = ('mail', {message_id(url) for url, _ in links}, max((int(message_id(url)) for url, _ in links), default=0))
            else:
                self._sms()
                self.browser.report('__sms__', '메시지 접근 확인 · 새 SMS 수신 검증 전')
                rows = self._sms_rows(mall)
                if not rows:
                    raise ValueError('인증 발신번호 대화가 없습니다.')
                codes = {message_code(row) for row in rows} - {None}
                if not codes:
                    raise ValueError('직전 인증 문자 상태를 확인할 수 없습니다.')
                self.baseline[mall.key] = ('sms', codes, 0)
        except Exception:
            self.browser.check_stop()
            self.baseline.pop(mall.key, None)
            if mall.sender:
                self.browser.report('__sms__', '확인 불가 · 자동 수신 연결 실패')
            self.browser.report(mall.key, '인증 수신 연결 미확인 · 필요시 FLOW에서 직접 입력')
        finally:
            self.driver.switch_to.window(original)

    def get(self, mall, seconds=45):
        baseline = self.baseline.get(mall.key)
        if not baseline:
            return None
        kind, seen, highest = baseline
        original = self.driver.current_window_handle
        deadline = time.monotonic() + seconds
        try:
            self.driver.switch_to.window(self.tabs[mall.mailbox if kind == 'mail' else 'sms'])
            self.browser.report(mall.key, '이번 로그인에서 새로 도착한 인증 메시지 확인 중')
            while time.monotonic() < deadline:
                self.browser.check_stop()
                if kind == 'mail':
                    self.driver.refresh()
                    for url, title in self._links():
                        identifier = message_id(url)
                        if identifier in seen or int(identifier) <= highest or not authentication_mail(mall, title):
                            continue
                        # A workbook or a message cannot redirect this reader off the configured mailbox host.
                        if urlsplit(url).hostname != urlsplit(MAILBOXES[mall.mailbox][0]).hostname:
                            continue
                        self.driver.get(url)
                        self.browser.wait(lambda: self.browser.visible('body'))
                        text = self.browser.text()
                        for frame in self.driver.find_elements('css selector', 'iframe'):
                            self.driver.switch_to.frame(frame)
                            try:
                                text += '\n' + self.browser.text()
                            finally:
                                self.driver.switch_to.default_content()
                        code = message_code(text, authenticated_mail=True)
                        if code:
                            self.baseline.pop(mall.key, None)
                            return code
                        self.driver.back()
                        break
                else:
                    for row in self._sms_rows(mall):
                        code = message_code(row)
                        if code and code not in seen:
                            self.browser.report('__sms__', '이번 요청의 새 인증 문자 읽기 확인 · 로그인 성공 여부 별도 확인')
                            self.baseline.pop(mall.key, None)
                            return code
                self.browser.stop.wait(2)
            return None
        finally:
            self.driver.switch_to.window(original)
