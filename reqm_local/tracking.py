"""Conservative invoice reconciliation, independent of shipping quantities."""
from __future__ import annotations

import re
from collections import defaultdict

STATES = {'matched': '매칭 완료', 'pending': '송장 대기', 'not_found': '주문 미확인',
          'review': '검토 필요', 'confirmed': '확정'}
KINDS = {'B2C': 'b2c', '사입형 B2C': 'b2c_buying', 'B2B': 'b2b'}
HEADERS = ['주문번호', '판매처', '상품명', '수량', '수령자', '핸드폰', '우편번호',
           '주소', '배송메세지', '송장번호', '일련번호']


def identity(value):
    # Keep punctuation in order numbers: AB-12 and AB12 are different orders.
    return str(value or '').strip()


def compact(value):
    return re.sub(r'\s+', '', identity(value)).casefold()


def phone(value):
    digits = re.sub(r'\D', '', identity(value))
    if digits.startswith('82'):
        digits = '0' + digits[2:].lstrip('0')
    return digits


def invoices(value):
    text = identity(value).replace('-', '')
    parts = re.split(r'[,;/\s]+', text)
    return list(dict.fromkeys(p for p in parts if re.fullmatch(r'[0-9]{8,20}', p)))


def manual_invoice(value):
    number = identity(value).replace('-', '').replace(' ', '')
    if not re.fullmatch(r'[0-9]{8,20}', number):
        raise ValueError('송장번호는 하이픈을 제외한 8~20자리 숫자로 입력하세요.')
    return number


def delivery_key(row):
    key = (compact(row.get('recipient')), phone(row.get('phone')),
           compact(row.get('postcode')), compact(row.get('address')))
    return key if all(key) else None


def reconcile(orders, remote_rows):
    by_order = defaultdict(list)
    source_channels = defaultdict(set)
    for order in orders:
        for key in ('order_no', 'line_no'):
            if order.get(key):
                source_channels[identity(order[key])].add(identity(order.get('channel')))
    for remote in remote_rows:
        by_order[identity(remote.get('order_no'))].append(remote)
    results = []
    for order in orders:
        candidates = list(by_order.get(identity(order.get('order_no')), [])) if order.get('order_no') else []
        alternate = False
        if not candidates and order.get('line_no'):
            candidates = list(by_order.get(identity(order['line_no']), []))
            alternate = bool(candidates)
        result = {'state': 'not_found', 'reason': '위킵에서 주문번호를 찾지 못했습니다.',
                  'tracking': '', 'candidates': candidates}
        if candidates:
            result.update(state='review', reason='배송정보가 다르거나 확인할 정보가 부족합니다.')
            verified = []
            for candidate in candidates:
                if len(source_channels[identity(candidate.get('order_no'))]) > 1 and not candidate.get('channel'):
                    continue
                # Explicit different channel/account/line values must not be collapsed.
                if any(order.get(k) and candidate.get(k) and identity(order[k]) != identity(candidate[k])
                       for k in ('channel', 'account')):
                    continue
                if not alternate and order.get('line_no') and candidate.get('line_no') and identity(order['line_no']) != identity(candidate['line_no']):
                    continue
                key = delivery_key(order)
                if key is not None and delivery_key(candidate) == key:
                    verified.append(candidate)
            if verified:
                numbers = list(dict.fromkeys(n for c in verified
                               for k in ('tracking', 'additional_tracking') for n in invoices(c.get(k))))
                # A conflicting candidate for the same identity must remain visible.
                if len(verified) != len(candidates):
                    result['reason'] = '같은 주문번호에 서로 다른 배송정보가 있습니다. 후보를 확인하세요.'
                elif len(numbers) == 1:
                    result.update(state='matched', reason=('상품주문번호' if alternate else '주문번호') + '·수령인·연락처·우편번호·주소 일치', tracking=numbers[0])
                elif not numbers:
                    result.update(state='pending', reason='주문은 확인됐지만 송장이 아직 발급되지 않았습니다.')
                else:
                    result['reason'] = '여러 송장 확인: ' + ', '.join(numbers)
        if not candidates and delivery_key(order) is not None:
            peers = [r for r in remote_rows if delivery_key(r) == delivery_key(order)
                     and not any(order.get(k) and r.get(k) and identity(order[k]) != identity(r[k])
                                 for k in ('channel', 'account'))]
            if peers:
                result.update(state='review', reason='배송정보는 일치하지만 주문번호가 다릅니다. 판매처·상품과 후보 송장을 확인하세요.', candidates=peers)
        results.append(result)
    return results
