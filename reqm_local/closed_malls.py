"""Local-only account storage and the confirmed closed-mall login contract."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .esm import _protect, _unprotect


@dataclass(frozen=True)
class Mall:
    key: str
    name: str
    url: str
    method: str = 'password'
    mailbox: str = ''
    sender: str = ''
    shared_login: str = ''
    automatic_code: bool = True


MALLS = (
    Mall('eri', '이알아이', 'https://mpointadmin.hyundaicard.com/login.do', 'manual_sms'),
    Mall('samsung', '삼성카드복지몰', 'https://ecpartner.samsungcard.com/loginForm.do', 'manual_sms'),
    Mall('handsome', '한섬', 'https://po.thehandsome.com/pologin', 'manual_sms'),
    Mall('ably', '에이블리', 'https://my.a-bly.com/login', 'unverified'),
    Mall('zigzag', '지그재그', 'https://partners.kakaostyle.com/login', 'unverified'),
    Mall('ohou', '오늘의집', 'https://orora.ohou.se/', 'email', 'orora'),
    Mall('kream', '크림', 'https://partner.kream.co.kr/sign-in', 'email', 'reqm'),
    Mall('hmall', '현대홈쇼핑', 'https://partner.hmall.com/', 'optional_email', 'orora'),
    Mall('sammall', '삼몰', 'https://www.sammall.co.kr/provider/index.html'),
    Mall('kurly', '컬리', 'https://3p-partner.kurly.com/login'),
    Mall('shopby', 'shop by', 'https://partner.shopby.co.kr/login'),
    Mall('etbs', '이제너두 ETBS', 'https://malladmin.benecafe.co.kr/common/poMain'),
    Mall('ssf', 'SSF SHOP', 'https://withus.ssfshop.com/pologin', 'sms', sender='1599-0007'),
    Mall('wconcept', 'W컨셉', 'https://newpin.wconcept.co.kr/Auth/Login', 'sms', sender='1566-5027'),
    Mall('hottracks', '핫트랙스', 'https://admin.hottracks.co.kr/admin/login/form', 'sms', sender='1661-1112'),
    Mall('benepia', '베네피아', 'https://newmallvenadm.benepia.co.kr/login/loginView.do', 'email', 'reqm'),
    Mall('ezwel', '현대이지웰', 'https://hpas.ezwel.com/views/websquare/websquare.html', 'email', 'orora'),
    Mall('musinsa', '무신사', 'https://partner-sso.one.musinsa.com/oauth/login?clientId=MUSINSA_PARTNER&platform=mss&redirectUri=https%3A%2F%2Fpartner.musinsa.com', 'email', 'reqm', shared_login='musinsa_sso'),
    Mall('29cm', '29CM', 'https://partner-sso.one.musinsa.com/oauth/login?clientId=E9_PARTNER&platform=29cm&redirectUri=https%3A%2F%2Fpartner-connect.29cm.co.kr%2Fdashboard', 'email', 'reqm', shared_login='musinsa_sso'),
)
MAILBOXES = {
    'reqm': ('http://webmail.reqm.co.kr/intro.php', 'reqm@reqm.co.kr'),
    'orora': ('https://webmail.ororamobile.com/intro.php', 'orora@ororamobile.com'),
}
MANUAL_CHANNELS = ('이알아이', '삼성카드복지몰', '한섬')


@dataclass(repr=False)
class CodeRequest:
    mall: Mall
    instructions: str
    timeout: int = 180
    digits: int = 6
    created: float = field(default_factory=time.monotonic)
    ready: object = field(default_factory=threading.Event)
    code: str | None = None
    cancelled: bool = False

    def remaining(self):
        return max(0, self.timeout - (time.monotonic() - self.created))

    def submit(self, value):
        value = str(value or '').strip()
        if self.cancelled or self.ready.is_set() or not self.remaining():
            return False
        if len(value) != self.digits or not value.isascii() or not value.isdigit():
            return False
        self.code = value
        self.ready.set()
        return True

    def cancel(self):
        self.cancelled = True
        self.code = None
        self.ready.set()


@dataclass(repr=False)
class Account:
    user: str
    password: str
    merchant_code: str = ''

    def __repr__(self):
        return 'Account(<protected>)'


def account_key(url: str) -> str | None:
    """Only route credentials to pre-registered hosts, never workbook URLs."""
    parsed = urlsplit(str(url or '').strip())
    if parsed.username or parsed.password or parsed.scheme not in ('http', 'https'):
        return None
    host = (parsed.hostname or '').lower()
    if host == 'partner-sso.one.musinsa.com':
        query = parse_qs(parsed.query)
        pair = (query.get('platform', [''])[0], query.get('clientId', [''])[0])
        return {('mss', 'MUSINSA_PARTNER'): 'musinsa', ('29cm', 'E9_PARTNER'): '29cm'}.get(pair)
    for key, (address, _) in MAILBOXES.items():
        if host == urlsplit(address).hostname:
            return 'mail_' + key
    return next((m.key for m in MALLS if host == urlsplit(m.url).hostname), None)


def read_account_workbook(path) -> dict[str, Account]:
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    accounts = {}
    try:
        sheet = book['계정입력양식']
        rows = iter(sheet.values)
        headers = [str(v or '').strip() for v in next(rows)]
        headers = ['비밀번호' if h.startswith('비밀번호 (') else h for h in headers]
        required = ('판매처·서비스명', '아이디', '비밀번호', 'URL')
        if any(h not in headers for h in required):
            raise ValueError('계정입력양식의 판매처·서비스명, 아이디, 비밀번호, URL 열을 확인하세요.')
        columns = {h: headers.index(h) for h in required}
        for row in rows:
            key = account_key(row[columns['URL']])
            if key is None:
                continue
            if key in accounts:
                raise ValueError('같은 판매처 계정이 두 번 있습니다. URL을 확인하세요.')
            user = str(row[columns['아이디']] or '').strip()
            # Spaces and punctuation in passwords are significant.
            password = str(row[columns['비밀번호']] or '')
            if not user or not password:
                continue
            code = re.search(r'거래처\s*코드\D*(\d+)', str(row[columns['판매처·서비스명']] or ''))
            accounts[key] = Account(user, password, code.group(1) if code else '')
        return accounts
    finally:
        book.close()


def local_login_folder() -> Path:
    """Keep cookies and secrets outside the shared/cloud order workspace."""
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'REQMFLOW' / 'closed-malls'


def save_accounts(folder, accounts: dict[str, Account]) -> None:
    target = Path(folder) / 'accounts.dat'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    payload = json.dumps({k: asdict(a) for k, a in accounts.items()}, ensure_ascii=False).encode('utf-8')
    temporary.write_bytes(_protect(payload, 'REQM FLOW closed mall accounts'))
    os.replace(temporary, target)


def load_accounts(folder) -> dict[str, Account]:
    path = Path(folder) / 'accounts.dat'
    if not path.exists():
        return {}
    try:
        data = json.loads(_unprotect(path.read_bytes()).decode('utf-8'))
        return {key: Account(**value) for key, value in data.items()}
    except Exception as exc:
        raise RuntimeError('저장 계정을 읽지 못했습니다. 이 Windows 계정에서 엑셀을 다시 불러오세요.') from exc


def extract_code(text: str) -> str | None:
    """Only extract a code tied to an authentication label; preserve leading zero."""
    patterns = (
        r'인증번호(?:는|입니다|\s안내\s드립니다\.)?\s*(?:[:：]|\[|\()?\s*(\d{6})(?!\d)',
        r'이메일 인증을 완료해 주세요\.\s*(\d{6})(?!\d)',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


@dataclass
class LoginResult:
    channel: str
    status: str
    reason: str
    seconds: float
    mode: str = '신규 로그인'


def save_results(folder, results: list[LoginResult]) -> Path:
    from datetime import datetime
    target = Path(folder) / 'runs' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'created_at': datetime.now().isoformat(), 'results': [asdict(r) for r in results]}, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


# No two flows may own the browser/mailbox at once, including separate UI jobs.
LOGIN_LOCK = threading.Lock()


@dataclass
class LoginSession:
    driver: object
    results: list[LoginResult] = field(default_factory=list)
    closed: bool = False
    channel_tabs: dict = field(default_factory=dict)
    _close_lock: object = field(default_factory=threading.Lock, repr=False)

    def close(self):
        with self._close_lock:
            if not self.closed:
                self.closed = True
                try:
                    self.driver.quit()
                finally:
                    LOGIN_LOCK.release()
