"""Read-only WeKeep search through the existing Selenium desktop runtime."""
from __future__ import annotations

import json
import re
import threading
from datetime import date
from urllib.parse import urlsplit

from .files import identifier, read_rows
from .esm import load_credentials

SEARCH_URL = 'https://fbw.wekeep.co.kr/fbw/admin/v2/order/searchOrder'
CHANNELS = {'b2c': ('SCNC75B2282BEYUXP', '주식회사 리큐엠(B2C)'),
            'b2c_buying': ('SCN2F09B6F8C7YUKO', '주식회사 리큐엠(사입형B2C)'),
            'b2b': ('SCN477724148DY0CS', '주식회사 리큐엠(B2B)')}
LOCK = threading.Lock()
ALIASES = {
    'order_no': ['판매처주문번호', '주문번호'],
    'line_no': ['상품주문번호', '주문상세번호'],
    'recipient': ['수령자', '수령인', '수취인명', '수령자명'],
    'phone': ['핸드폰', '수령자전화번호', '수령자연락처', '수령자휴대폰', '수취인연락처1', '연락처', '휴대폰', '전화번호'],
    'postcode': ['우편번호', '수취인우편번호'],
    'address': ['주소', '배송주소', '수령자주소', '수취인주소', '통합배송지'],
    'address2': ['상세주소', '배송지상세주소'],
    'tracking': ['송장번호', '운송장번호'],
    'additional_tracking': ['추가송장', '추가송장번호'],
    'order_status': ['주문상태'], 'registered_at': ['주문등록일'],
}


def parse_remote_rows(headers, rows):
    clean = lambda value: ''.join(identifier(value).split())
    names = [clean(h) for h in headers]
    indexes = {key: next((names.index(clean(alias)) for alias in aliases if clean(alias) in names), None)
               for key, aliases in ALIASES.items()}
    if indexes['order_no'] is None or indexes['tracking'] is None:
        raise ValueError('위킵 자료에 판매처주문번호와 송장번호 열이 필요합니다.')
    result = []
    for row in rows:
        data = {key: identifier(row[index]) if index is not None and index < len(row) else ''
                for key, index in indexes.items()}
        if not data['order_no']:
            continue
        if data.pop('address2'):
            data['address'] = ' '.join(filter(None, (data['address'], identifier(row[indexes['address2']]))))
        result.append(data)
    return result


def read_tracking_file(path):
    rows = read_rows(path)
    for index, row in enumerate(rows[:30]):
        if any(identifier(value).replace(' ', '') in ALIASES['tracking'] for value in row):
            return parse_remote_rows(row, rows[index + 1:])
    raise ValueError('위킵 송장 파일의 헤더를 찾지 못했습니다.')


TABLE_SCRIPT = r'''
const clean = v => String(v || '').replace(/\s+/g, ' ').trim();
const tables = [...document.querySelectorAll('table')];
const table = tables.find(t => {
  const hs = [...t.querySelectorAll('thead th')].map(x => clean(x.textContent));
  return hs.includes('판매처주문번호') && hs.includes('송장번호');
});
if (!table) return null;
return {headers: [...table.querySelectorAll('thead th')].map(x => clean(x.textContent)),
 rows: [...table.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => clean(td.textContent))),
 detailIds: [...table.querySelectorAll('tbody tr')].map(tr => {
   const handlers = [...tr.querySelectorAll('[onclick]')].map(x => x.getAttribute('onclick'));
   const matches = handlers.map(h => h.match(/^getOrderDetail\(\s*['"][^'"]+['"]\s*,\s*['"]([^'"]+)['"]\s*\)$/)).filter(Boolean);
   return matches.length === 1 ? matches[0][1] : '';
 })};
'''

def detail_rows(row, api, provider_order_no, sale_channel_no):
    if not isinstance(api, dict) or not api.get('result') or not isinstance(api.get('data'), dict):
        raise RuntimeError('위킵 주문 상세 조회에 실패했습니다. 일부 결과만 적용하지 않습니다.')
    data = api['data']
    order, delivery, items = data.get('orderDetail') or {}, data.get('deliveryDetail') or {}, data.get('orderItemList') or []
    if identifier(order.get('orderNo')) != provider_order_no or identifier(order.get('saleChannelNo')) != sale_channel_no:
        raise RuntimeError('위킵 주문 상세의 주문번호 또는 판매처가 조회 대상과 다릅니다.')
    # A combined order can contain multiple seller order numbers. Expand only the
    # numbers explicitly present in the provider response, sharing its package.
    order_numbers = list(dict.fromkeys(identifier(i.get('channelOrderNo')) for i in items if i.get('channelOrderNo')))
    parent_number = identifier(order.get('channelOrderNo'))
    if parent_number and parent_number not in order_numbers:
        order_numbers.append(parent_number)
    if not order_numbers:
        return [row]
    shipment = {**row, 'recipient': identifier(order.get('recipient')),
                'phone': identifier(order.get('recipientMobile') or order.get('recipientTelephone')),
                'postcode': identifier(order.get('deliveryZipcode')),
                'address': ' '.join(filter(None, (identifier(order.get('deliveryAddress')),
                                                identifier(order.get('deliveryAddressDetail'))))),
                'provider_order_no': provider_order_no, 'provider_sale_channel': sale_channel_no,
                'provider_grouped': order.get('groupOrderYn') == 'Y',
                'order_status': identifier(order.get('orderStatus')),
                'shipment_status': identifier(order.get('shipmentStatus')),
                'shipout_date': identifier(delivery.get('shipoutDate')),
                'detail_tracking': identifier(delivery.get('trackingNo')),
                'items': [{k: i.get(k) for k in ('channelOrderNo', 'channelOrderSeq', 'channelProductName',
                                                'channelOptionName', 'orderQty')} for i in items]}
    # Retain both list and detail invoices so differences trigger review.
    if shipment['detail_tracking'] and shipment['detail_tracking'] != shipment.get('tracking'):
        shipment['additional_tracking'] = ', '.join(filter(None, (shipment.get('additional_tracking'), shipment['detail_tracking'])))
    return [{**shipment, 'order_no': number} for number in order_numbers]


def enrich_delivery(driver, rows, sale_channel_no, report):
    enriched, cache = [], {}
    driver.set_script_timeout(40)
    for index, row in enumerate(rows):
        no = row.pop('_detail_id', '')
        if no:
            if no not in cache:
                cache[no] = driver.execute_async_script('''
                  const [orderNo, done] = arguments;
                  // This exact read endpoint is used by WeKeep's getOrderDetail.
                  CommonApiCall.requestPost('/fbw/admin/v2/order/getOrderDetail', {orderNo})
                    .then(done).catch(() => done(null));
                ''', no)
            enriched.extend(detail_rows(row, cache[no], no, sale_channel_no))
        else:
            enriched.append(row)
        if index % 10 == 0:
            report(f'위킵 주문 상세 대조 {index + 1}/{len(rows)}건')
    return enriched


def search_destination(url):
    parsed = urlsplit(url)
    return parsed.hostname == 'fbw.wekeep.co.kr' and parsed.path.rstrip('/') == urlsplit(SEARCH_URL).path


def collect_tracking(driver, start, end, kind, wait_factory=None, report=lambda text: None):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    wait = (wait_factory or WebDriverWait)(driver, 30)
    if kind not in CHANNELS:
        raise ValueError('위킵 주문 유형을 확인하세요.')
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError('위킵 등록일 범위를 확인하세요.')
    value, label = CHANNELS[kind]
    wait.until(lambda d: d.find_elements('css selector', f'#saleChannel_search option[value="{value}"]'))
    previous = driver.find_elements('css selector', 'table tbody tr')
    # Set filters once. WeKeep select change handlers otherwise discard date values.
    driver.execute_script(r'''
      const [value, label, start, end] = arguments;
      const sale = document.querySelector('#saleChannel_search');
      const option = [...sale.options].find(o => o.value === value);
      if (!option || option.textContent.replace(/\s/g, '') !== label.replace(/\s/g, ''))
        throw new Error('위킵 판매처를 확인하지 못했습니다.');
      sale.value = option.value;
      document.querySelector('#dateType').value = 'CREATE_YMD';
      document.querySelector('#ymd').value = '';
      document.querySelector('#startDate_search').value = start;
      document.querySelector('#endDate_search').value = end;
      for (const id of ['orderName_search', 'recipient_search', 'trackingNo_search',
                        'channelOrderNo_search', 'addTrackingNo_search', 'productName_search']) {
        const input = document.getElementById(id);
        if (input) input.value = '';
      }
      for (const id of ['orderStatus_search', 'arrivalGuaranteeYn_search']) {
        const input = document.getElementById(id);
        const all = input && input.options && [...input.options].find(o => o.value === '' || o.textContent.includes('ALL'));
        if (all) input.value = all.value;
      }
      const length = document.querySelector('#searchLength');
      const hundred = length && [...length.options].find(o => o.textContent.includes('100개'));
      if (hundred) length.value = hundred.value;
      if (typeof searchDetailOrderList !== 'function') throw new Error('위킵 검색 화면이 변경되었습니다.');
      searchDetailOrderList();
    ''', value, label, start, end)
    if previous:
        wait.until(EC.staleness_of(previous[0]))
    results, signatures = [], set()
    for _ in range(1000):
        payload = wait.until(lambda d: d.execute_script(TABLE_SCRIPT))
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if signature in signatures:
            raise RuntimeError('위킵 결과 페이지가 반복됩니다. 일부 자료만 적용하지 않고 조회를 중단했습니다.')
        signatures.add(signature)
        for cells, detail_id in zip(payload['rows'], payload.get('detailIds', ['' for _ in payload['rows']])):
            parsed = parse_remote_rows(payload['headers'], [cells])
            for row in parsed:
                registered = re.sub(r'\D', '', row.get('registered_at', ''))[:8]
                if len(registered) == 6:
                    registered = '20' + registered  # WeKeep displays YY.MM.DD.
                if registered and not start.replace('-', '') <= registered <= end.replace('-', ''):
                    raise RuntimeError('위킵 조회 결과의 주문등록일이 요청 범위를 벗어납니다.')
                row['_detail_id'] = detail_id
                results.append(row)
        links = [link for link in driver.find_elements('tag name', 'a')
                 if link.text.strip() == '>' and link.is_displayed() and link.is_enabled()
                 and link.get_attribute('aria-disabled') != 'true'
                 and 'disabled' not in (link.get_attribute('class') or '').split()]
        if not links:
            return enrich_delivery(driver, results, value, report)
        if len(links) != 1:
            raise RuntimeError('위킵 다음 페이지를 정확히 확인하지 못했습니다.')
        links[0].click()
        wait.until(lambda d: (p := d.execute_script(TABLE_SCRIPT)) and
                   json.dumps(p, ensure_ascii=False, sort_keys=True) != signature)
    raise RuntimeError('위킵 조회 페이지 한도를 초과했습니다.')


def fetch_tracking(folder, start, end, kind, report=lambda text: None):
    from .closed_mall_browser import create_login_driver
    from selenium.webdriver.support.ui import WebDriverWait
    if not LOCK.acquire(blocking=False):
        raise RuntimeError('이미 위킵 송장을 조회하고 있습니다.')
    driver = None
    try:
        # Dedicated FLOW profile; Shipping's saved browser and credentials are untouched.
        driver = create_login_driver(folder / 'wekeep', False)
        driver.set_page_load_timeout(45)
        driver.get(SEARCH_URL)
        if not search_destination(driver.current_url):
            user, password = load_credentials(folder / 'wekeep_credentials.bin')
            fields = driver.find_elements('css selector', 'input[name="j_username"]')
            passwords = driver.find_elements('css selector', 'input[name="j_password"]')
            if user and password and len(fields) == len(passwords) == 1:
                fields[0].send_keys(user)
                passwords[0].send_keys(password)
                buttons = driver.find_elements('css selector', 'input[type="submit"][value="시작하기"]')
                if len(buttons) == 1:
                    buttons[0].click()
            report('위킵 브라우저에서 로그인을 완료하세요. 로그인 후 송장 조회를 이어갑니다.')
            WebDriverWait(driver, 180).until(lambda d: urlsplit(d.current_url).hostname == 'fbw.wekeep.co.kr'
                                            and '/order/' in urlsplit(d.current_url).path)
            driver.get(SEARCH_URL)
        if not search_destination(driver.current_url):
            raise RuntimeError('위킵 주문 상세검색에 연결하지 못했습니다.')
        report('위킵 주문과 송장번호를 조회하고 있습니다.')
        return collect_tracking(driver, start, end, kind, report=report)
    finally:
        try:
            if driver is not None:
                driver.quit()
        finally:
            LOCK.release()
