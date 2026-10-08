"""Non-secret authentication routing and conservative SMS health checks."""
import json
import os
from dataclasses import replace
from urllib.parse import urlsplit

from .closed_malls import MALLS


def defaults():
    return {'sms_enabled': False, 'sms_account': 'reqm.cs@gmail.com', 'sms_phone': '2054', 'vendors': {}}


def load_settings(folder):
    path = folder / 'authentication.json'
    settings = defaults()
    if path.exists():
        values = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(values, dict):
            raise ValueError('인증 설정 파일을 확인하세요.')
        settings.update({k: values[k] for k in settings if k in values})
    validate(settings)
    return settings


def validate(settings):
    if type(settings['sms_enabled']) is not bool:
        raise ValueError('SMS 자동 수신 설정을 확인하세요.')
    if not isinstance(settings['sms_account'], str) or '@' not in settings['sms_account']:
        raise ValueError('SMS 수신 Google 계정을 입력하세요.')
    phone = settings['sms_phone']
    if not isinstance(phone, str) or len(phone) != 4 or not phone.isascii() or not phone.isdigit():
        raise ValueError('SMS 수신 전화번호 끝자리 4자리를 입력하세요.')
    if not isinstance(settings['vendors'], dict):
        raise ValueError('판매처 인증 설정을 확인하세요.')
    for key, values in settings['vendors'].items():
        mall = next((m for m in MALLS if m.key == key), None)
        if mall is None or not isinstance(values, dict) or type(values.get('automatic', True)) is not bool:
            raise ValueError('판매처 인증 설정을 확인하세요.')
        if values.get('mailbox', mall.mailbox) not in (('reqm', 'orora') if mall.mailbox else ('',)):
            raise ValueError('지원하는 인증 메일을 선택하세요.')


def save_settings(folder, settings):
    validate(settings)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'authentication.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def configured_mall(mall, settings):
    values = settings['vendors'].get(mall.key, {})
    automatic = values.get('automatic', True)
    if mall.method == 'manual_sms':
        automatic = False
    if mall.method == 'sms':
        automatic = automatic and settings['sms_enabled']
    return replace(mall, mailbox=values.get('mailbox', mall.mailbox), automatic_code=automatic)


def sms_page_status(url, text, labels, has_messages, account):
    host = urlsplit(url).hostname
    if host == 'accounts.google.com':
        return '재연결 필요 · Google 로그인 필요'
    if host != 'messages.google.com':
        return '확인 불가 · 예상하지 않은 주소'
    if any(word in text.lower() for word in ('phone disconnected', 'trying to connect', '휴대전화에 연결', '휴대전화와 연결이 끊', '기기 페어링', 'pair your phone')):
        return '재연결 필요 · 휴대전화 연결 확인'
    if not any(account.lower() in label.lower() for label in labels):
        return '확인 불가 · 수신 계정 확인 필요'
    if has_messages:
        return '메시지 접근 확인 · 새 SMS 수신 검증 전'
    return '확인 불가 · 메시지 목록을 읽을 수 없음'


def inspect_sms(driver, account):
    from .closed_mall_codes import MESSAGES_URL
    original = driver.current_window_handle
    handle = None
    try:
        driver.switch_to.new_window('tab')
        handle = driver.current_window_handle
        driver.get(MESSAGES_URL)
        from selenium.webdriver.support.ui import WebDriverWait
        WebDriverWait(driver, 8).until(lambda d: urlsplit(d.current_url).hostname == 'accounts.google.com' or d.find_elements('css selector', 'mws-conversation-list-item') or any(x in d.find_element('css selector', 'body').text.lower() for x in ('기기 페어링', 'pair your phone', '로그인', 'sign in')))
        text = driver.find_element('css selector', 'body').text
        labels = [e.get_attribute('aria-label') or '' for e in driver.find_elements('css selector', '[aria-label]')]
        rows = driver.find_elements('css selector', 'mws-conversation-list-item')
        return sms_page_status(driver.current_url, text, labels, any(e.is_displayed() for e in rows), account)
    except Exception:
        return '확인 불가 · 브라우저 또는 네트워크 연결 오류'
    finally:
        try:
            if handle and handle in driver.window_handles:
                driver.switch_to.window(handle)
                driver.close()
            driver.switch_to.window(original)
        except Exception:
            pass
