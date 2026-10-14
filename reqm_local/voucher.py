"""Daily voucher editing and reusable, colour-independent set allocations.

Rules use a reserved namespace in the existing shared mappings store so that
they participate in row-level sync without another cloud schema migration.
"""
import hashlib
import json
from pathlib import Path
from decimal import Decimal
from fractions import Fraction
from datetime import datetime, timezone

PREFIX = 'voucher:v1:'
COLORS = ('블랙', '화이트', '블루', '핑크', '그린', '베이지', '버터', '민트',
          '그레이', '퍼플', '옐로우', '레드', '오렌지', '라벤더', '네이비', '실버', '포레그린')


def won(value):
    try:
        amount = Decimal(str(value).replace(',', ''))
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            raise ValueError
        return amount
    except Exception:
        raise ValueError('금액은 0 이상의 원 단위 정수로 입력하세요.') from None


def allocation_feedback(total, values):
    """Blank component entries count as zero only in live feedback."""
    target = won(total)
    entered = sum((won(str(v).strip() or '0') for v in values), Decimal(0))
    remaining = target - entered
    if remaining > 0:
        return f'입력 합계 {entered:,.0f}원 · 남은 금액 {remaining:,.0f}원', '#B45309', False
    if remaining < 0:
        return f'입력 합계 {entered:,.0f}원 · 초과 금액 {-remaining:,.0f}원', '#BE123C', False
    return f'입력 합계 {entered:,.0f}원 · 금액 일치', '#15803D', True


class VoucherOperations:
    def voucher_family(self, code):
        record=self.db.execute('SELECT components FROM mappings WHERE key=?',(PREFIX+'family:'+code,)).fetchone()
        if record:
            family=json.loads(record[0])[0]
        else:
            if not hasattr(self,'_voucher_family_defaults'):
                path=Path(self.reference_dir)/'voucher_families.json'
                self._voucher_family_defaults=json.loads(path.read_text(encoding='utf-8'))['families'] if path.exists() else {}
            family=self._voucher_family_defaults.get(code,'')
        # Older entries used a visual trailing dash in some family labels.
        # It is not part of the model identity and prevented equivalent colours
        # from sharing the same allocation.
        family=family.rstrip(' -')
        return 'model:' + family if family else 'sku:' + code

    def set_voucher_family(self, code, family):
        if code not in self.active_shipping_items:
            raise ValueError('현재 활성 품목을 선택하세요.')
        family=str(family).strip()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?)',(PREFIX+'family:'+code,json.dumps([family],ensure_ascii=False)))
            self.event('전표 색상 공유 그룹 변경',code)

    def voucher_rows(self, start, end, include_exported=False, include_requests=False):
        from .service import day
        start, end = day(start), day(end)
        if start > end:
            raise ValueError('조회 시작일은 종료일보다 늦을 수 없습니다.')
        groups = {}
        orders = {o['id']: o for o in self.orders()}
        for line in self.db.execute('''SELECT s.*,r.order_id,r.component FROM shipments s
            JOIN request_lines r ON r.id=s.line_id WHERE s.day BETWEEN ? AND ?
            ORDER BY s.day,s.rowid''', (start, end)):
            order = orders[line['order_id']]
            from .service import is_smartstore_channel
            if self.smartstore_erp_enabled() and is_smartstore_channel(order['data'].get('channel')):
                continue
            key = 'shipment:' + line['order_id'] + ':' + line['day']
            group = groups.setdefault(key, {'id': key, 'kind': 'shipment', 'day': line['day'],
                'order_id': line['order_id'], 'data': order['data'], 'components': [], 'exported': False,
                'confirmed': True, 'issue': '', 'full': True})
            component = self._shipment_component(line, order)
            group['components'].append({**component, 'entry_id': line['id'], 'index': line['component'],
                'quantity': line['qty'], 'amount': line['erp_amount'] or '0'})
            group['exported'] |= bool(line['erp_id'])
            group['confirmed'] &= bool(line['amount_split_confirmed'])
        for group in groups.values():
            definitions = orders[group['order_id']]['components']
            group['full'] = len(group['components']) == len(definitions) and all(
                Decimal(str(c['quantity'])) == Decimal(str(definitions[c['index']]['quantity']))
                for c in group['components'])
        if include_requests:
            for line in self.db.execute('''SELECT r.*,q.day FROM request_lines r
                JOIN requests q ON q.id=r.request_id
                WHERE q.day BETWEEN ? AND ? AND NOT EXISTS
                (SELECT 1 FROM shipments s WHERE s.line_id=r.id) ORDER BY q.day,r.rowid''',(start,end)):
                order=orders[line['order_id']]
                from .service import is_smartstore_channel
                if self.smartstore_erp_enabled() and is_smartstore_channel(order['data'].get('channel')):
                    continue
                key='request:'+line['order_id']+':'+line['day']
                group=groups.setdefault(key,{'id':key,'kind':'request','day':line['day'],
                    'order_id':line['order_id'],'data':order['data'],'components':[],
                    'exported':False,'confirmed':False,'issue':'출고 확인 필요','full':False})
                c=order['components'][line['component']]
                group['components'].append({**c,'index':line['component'],'entry_id':line['id'],
                                            'quantity':line['qty']})
        for table, kind in (('smartstore_erp_rows', 'smartstore'), ('esm_erp_rows', 'esm')):
            for row in self.db.execute(f'SELECT * FROM {table} WHERE day BETWEEN ? AND ? ORDER BY day,rowid', (start, end)):
                data = json.loads(row['data'])
                groups[kind + ':' + row['id']] = {'id': kind + ':' + row['id'], 'kind': kind,
                    'order_id': row['id'], 'day': row['day'], 'data': data,
                    'components': [{**c, 'index': i} for i, c in enumerate(json.loads(row['components']))],
                    'exported': bool(row['erp_id']), 'issue': row['issue'], 'full': True,
                    'confirmed': bool(row['amount_split_confirmed']) if kind == 'smartstore' else not row['issue']}
        result = []
        for group in groups.values():
            if group['exported'] and not include_exported:
                continue
            group['channel'] = group['data'].get('channel', '스마트스토어' if group['kind'] == 'smartstore' else '')
            group['total'] = sum((Decimal(str(c['amount'] or '0')) for c in group['components']), Decimal(0))
            result.append(group)
        return result

    def confirm_voucher_requests(self, row_ids, shipping_day):
        from .service import day
        shipping_day=day(shipping_day)
        rows={r['id']:r for r in self.voucher_rows('0001-01-01','9999-12-31',include_requests=True) if r['kind']=='request'}
        if not row_ids or any(key not in rows for key in row_ids):
            raise ValueError('출고요청 목록이 변경되었습니다. 다시 조회하세요.')
        added=0
        with self.db:
            for key in dict.fromkeys(row_ids):
                for component in rows[key]['components']:
                    line=self.db.execute('SELECT * FROM request_lines WHERE id=?',(component['entry_id'],)).fetchone()
                    if self._record_shipment(line,shipping_day,line['qty'],'')=='added':added+=1
            self.event('전표 작업표 선택 출고 확정',f'{shipping_day}: {added}개 구성품')
        return added

    def voucher_rule_key(self, row, total=None):
        from .service import display_channel
        if not row['full'] or not row['components'] or row['issue']:
            return None
        if total is not None and len(row['components']) < 2:
            return None
        count = Fraction(str(row['data'].get('quantity') or '1'))
        if count <= 0:
            return None
        parts = [(self.voucher_family(c['code']), str(Fraction(str(c['quantity'])) / count))
                 for c in row['components']]
        # Identical model appearing twice makes correspondence ambiguous.
        if len({family for family, _ in parts}) != len(parts):
            return None
        identity = [display_channel(row['channel']), row['data'].get('account', ''), sorted(parts)]
        if display_channel(row['channel']) == '오늘의집':
            identity.append(['배송비 차감', str(Fraction(str(row['data'].get('ohou_shipping_deducted') or '0')) / count)])
        if total is not None:
            identity.append(str(Fraction(str(total)) / count))
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        return PREFIX + digest

    def voucher_review_signature(self, row, total, amounts):
        financial_data = {key:row['data'].get(key,'') for key in
                          ('channel','account','order_no','product','option','quantity','amount')}
        payload = [financial_data, row['full'],
                   [(c['code'], self.voucher_family(c['code']), str(c['quantity'])) for c in row['components']],
                   str(won(total)), [str(won(v)) for v in amounts]]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def voucher_review_history(self, rows):
        groups = {}
        for row in rows:
            key = self.voucher_rule_key(row)
            if key and row['confirmed'] and self.voucher_history_trusted(row):
                groups.setdefault(key, []).append(row)
        return groups

    def voucher_review_approved(self, row):
        record = self.db.execute('SELECT components FROM mappings WHERE key=?', (PREFIX+'review:'+row['id'],)).fetchone()
        return bool(record and json.loads(record[0])[0]['signature'] ==
                    self.voucher_review_signature(row,row['total'],[c['amount'] for c in row['components']]))

    def voucher_history_trusted(self, row):
        try:
            return won(row['data'].get('amount')) == won(row['total']) or self.voucher_review_approved(row)
        except ValueError:
            return False

    def voucher_review(self, row, total=None, amounts=None, history=None):
        """Compare source and confirmed compositions; fuzzy names never approve prices."""
        total = won(row['total'] if total is None else total)
        amounts = [won(c['amount']) for c in row['components']] if amounts is None else [won(v) for v in amounts]
        warnings = []
        if sum(amounts, Decimal(0)) != total:
            return ['구성품 금액 합계 불일치']
        if row['full']:
            try:
                source = won(row['data'].get('amount'))
            except ValueError:
                warnings.append('원본 상품금액 확인 필요')
            else:
                if source != total:
                    warnings.append(f'원본 금액 불일치: 원본 {source:,.0f}원 · 전표 {total:,.0f}원 · 차액 {total-source:+,.0f}원')
        key = self.voucher_rule_key(row)
        if key:
            count = Fraction(str(row['data'].get('quantity') or '1'))
            price = Fraction(str(total)) / count
            allocations = {self.voucher_family(c['code']): Fraction(str(v))/count for c,v in zip(row['components'],amounts)}
            peers = history if history is not None else self.voucher_rows('0001-01-01', row['day'], True)
            if isinstance(peers, dict):peers = peers.get(key, [])
            prices, splits = set(), []
            for peer in peers:
                if peer['id'] == row['id'] or peer['day'] > row['day'] or not peer['confirmed'] or self.voucher_rule_key(peer) != key or not self.voucher_history_trusted(peer):
                    continue
                peer_count = Fraction(str(peer['data'].get('quantity') or '1'))
                peer_price = Fraction(str(peer['total'])) / peer_count
                prices.add(peer_price)
                if peer_price == price:
                    splits.append({self.voucher_family(c['code']): Fraction(str(c['amount']))/peer_count for c in peer['components']})
            if prices and price not in prices:
                def money(value):
                    return f'{Decimal(value.numerator)/Decimal(value.denominator):,.2f}'.rstrip('0').rstrip('.')+'원'
                previous = ' / '.join(money(p) for p in sorted(prices))
                warnings.append(f'가격 차이 확인: 기존 세트당 {previous} · 현재 {money(price)}')
            if splits and (any(split != allocations for split in splits)):
                warnings.append('배분 차이 확인: 같은 총금액의 과거 구성품별 배분과 다릅니다.')
        return warnings

    def voucher_review_pending(self, row, history=None):
        if self.voucher_review_approved(row):
            return []
        return self.voucher_review(row, history=history)

    def remember_voucher_split(self, row):
        if self.db.execute('SELECT 1 FROM mappings WHERE key=?', (PREFIX + 'no-reuse:' + row['id'],)).fetchone():
            return
        key = self.voucher_rule_key(row, row['total'])
        if not key or not row['confirmed']:
            return
        count = Fraction(str(row['data'].get('quantity') or '1'))
        allocation = {self.voucher_family(c['code']): str(Fraction(str(c['amount'])) / count)
                      for c in row['components']}
        previous = self.db.execute('SELECT components FROM mappings WHERE key=?', (key,)).fetchone()
        values = json.loads(previous[0]) if previous else []
        if allocation not in values:
            values.append(allocation)
        self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?)', (key, json.dumps(values, ensure_ascii=False)))

    def voucher_suggestion(self, row):
        # Use the seller's original amount, not a sum of provisional components.
        try:total = won(row['data'].get('amount') or '0')
        except ValueError:return None
        key = self.voucher_rule_key(row, total)
        record = self.db.execute('SELECT components FROM mappings WHERE key=?', (key,)).fetchone() if key else None
        if not record:
            return None
        values = json.loads(record[0])
        if len(values) != 1:
            return None  # Conflicting historical prices require an operator.
        count = Fraction(str(row['data'].get('quantity') or '1'))
        amounts = [Fraction(values[0][self.voucher_family(c['code'])]) * count for c in row['components']]
        if any(v.denominator != 1 for v in amounts) or sum(amounts) != Fraction(str(total)):
            return None
        return [str(v.numerator) for v in amounts]

    def set_voucher_amounts(self, row_id, total, amounts, remember=True, review_reason=''):
        from .service import encode
        row = next((r for r in self.voucher_rows('0001-01-01', '9999-12-31') if r['id'] == row_id), None)
        if not row or row['issue'] or not row['components']:
            raise ValueError('미매칭 또는 이미 생성한 주문은 먼저 확인하세요.')
        total = won(total)
        values = [won(v) for v in amounts]
        if len(values) != len(row['components']) or sum(values) != total:
            raise ValueError('구성품 금액 합계가 입력한 상품 총금액과 같아야 합니다.')
        warnings = self.voucher_review(row,total,values)
        if warnings and not str(review_reason).strip():
            raise ValueError(' / '.join(warnings)+' 확인 사유를 입력하세요.')
        with self.db:
            skip_key=PREFIX + 'no-reuse:' + row_id
            if remember:self.db.execute('DELETE FROM mappings WHERE key=?', (skip_key,))
            else:self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?)', (skip_key, '[]'))
            if row['kind'] == 'shipment':
                for c, value in zip(row['components'], values):
                    self.db.execute('UPDATE shipments SET erp_amount=?,amount_split_confirmed=1 WHERE id=? AND erp_id IS NULL',
                                    (str(value), c['entry_id']))
            else:
                table = 'smartstore_erp_rows' if row['kind'] == 'smartstore' else 'esm_erp_rows'
                components = [{k: v for k, v in c.items() if k != 'index'} for c in row['components']]
                for c, value in zip(components, values):
                    c['amount'] = str(value)
                extra = ',amount_split_confirmed=1' if row['kind'] == 'smartstore' else ''
                self.db.execute(f'UPDATE {table} SET components=?{extra} WHERE id=? AND erp_id IS NULL',
                                (encode(components), row['order_id']))
            row['total'] = total
            row['confirmed'] = True
            for c, value in zip(row['components'], values):
                c['amount'] = str(value)
            review = {'signature':self.voucher_review_signature(row,total,values),
                      'reason':str(review_reason).strip(), 'warnings':warnings,
                      'confirmed_at':datetime.now(timezone.utc).isoformat()}
            self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?)',
                            (PREFIX+'review:'+row_id,json.dumps([review],ensure_ascii=False)))
            if warnings:self.event('전표 금액 차이 확인',json.dumps({'row_id':row_id,**review},ensure_ascii=False))
            if remember and row['full']:
                # A manually changed total must not be assigned to unrelated
                # orders whose source amount differs from this voucher amount.
                self.remember_voucher_split(row)
            self.event('전표 금액 확정', row_id)

    def reuse_voucher_amounts(self, start, end):
        with self.db:
            for row in self.voucher_rows('0001-01-01', '9999-12-31', True):
                self.remember_voucher_split(row)
        count = 0
        for row in self.voucher_rows(start, end):
            if row['confirmed']:
                continue
            values = self.voucher_suggestion(row)
            if values:
                if self.voucher_review(row,sum(won(v) for v in values),values):
                    continue
                self.set_voucher_amounts(row['id'], sum(won(v) for v in values), values)
                count += 1
        return count

    def erp_fee_key(self, data):
        from .service import display_channel
        return json.dumps(['voucher-order', display_channel(data.get('channel', '')), data.get('account', ''), data.get('order_no', '')], ensure_ascii=False)

    def voucher_fee(self, data):
        override = self.db.execute('SELECT components FROM mappings WHERE key=?', (PREFIX + 'fee:' + self.erp_fee_key(data),)).fetchone()
        return won(json.loads(override[0])[0]) if override else won(data.get('shipping') or '0')

    def set_voucher_fee(self, data, amount):
        key = self.erp_fee_key(data)
        if self.db.execute('SELECT 1 FROM fees WHERE bundle IN (?,?)', (key, self.bundle_key(data))).fetchone():
            raise ValueError('이미 전표에 반영한 배송비는 변경할 수 없습니다.')
        with self.db:
            from .service import display_channel
            if display_channel(data.get('channel', '')) == '오늘의집':
                self._update_ohou_shipping_amounts(data, won(amount))
            self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?)',
                            (PREFIX + 'fee:' + key, json.dumps([str(won(amount))])))
            self.event('전표 배송비 확정', key)

    def _update_ohou_shipping_amounts(self, data, amount):
        from .service import encode, number
        key = self.erp_fee_key(data)
        orders = [o for o in self.orders() if self.erp_fee_key(o['data']) == key]
        orders.sort(key=lambda o: (not bool(number(o['data'].get('ohou_shipping_deducted') or '0')), o['data'].get('source_row', 0), o['id']))
        for index, order in enumerate(orders):
            current = order['data']
            old = number(current.get('amount') or '0')
            current['ohou_shipping_owner'] = index == 0
            self._apply_ohou_shipping_rule(current, amount)
            delta = number(current['amount']) - old
            components = order['components']
            if components and delta:
                main = number(components[0]['amount']) + delta
                if main < 0:
                    raise ValueError('오늘의집 배송비 차감 후 본품 금액이 음수입니다. 세트 배분을 확인하세요.')
                components[0]['amount'] = str(main)
                shipped = self.db.execute('''SELECT s.id,s.qty,s.erp_amount,s.erp_id FROM shipments s
                    JOIN request_lines r ON r.id=s.line_id WHERE r.order_id=? AND r.component=0 ORDER BY s.rowid''',
                    (order['id'],)).fetchall()
                if any(s['erp_id'] for s in shipped):
                    raise ValueError('이미 전표에 반영한 오늘의집 상품금액은 변경할 수 없습니다.')
                if shipped:
                    q = sum(s['qty'] for s in shipped)
                    if q != int(current['quantity']):
                        raise ValueError('오늘의집 부분 출고 주문은 상품금액 배분을 확인한 뒤 배송비를 확정하세요.')
                    remaining = delta
                    for pos, shipment in enumerate(shipped):
                        change = remaining if pos == len(shipped)-1 else won(delta * Decimal(shipment['qty']) / Decimal(q))
                        adjusted = number(shipment['erp_amount'] or '0') + change
                        if adjusted < 0:
                            raise ValueError('배송비 차감 후 출고 상품금액이 음수입니다. 금액 배분을 확인하세요.')
                        self.db.execute('UPDATE shipments SET erp_amount=? WHERE id=?',
                            (str(adjusted),shipment['id']))
                        remaining -= change
            self.db.execute('UPDATE orders SET data=?,components=? WHERE id=?',
                            (encode(current),encode(components),order['id']))

    def append_voucher_fees(self, sources, append, batch, regenerate=False, preview=False):
        groups = {}
        originals={}
        data_rows=[o['data'] for o in self.orders()]
        for table in ('smartstore_erp_rows', 'esm_erp_rows'):
            data_rows.extend(json.loads(record[0]) for record in self.db.execute(f'SELECT data FROM {table}'))
        for data in data_rows:originals.setdefault(self.erp_fee_key(data),[]).append(data)
        for data, base in sources:
            if not data.get('order_no'):
                raise ValueError('배송비 중복 확인에 필요한 주문번호가 없습니다.')
            groups.setdefault(self.erp_fee_key(data), []).append((data, base))
        emitted_legacy=set()
        for key, group in groups.items():
            existing = self.db.execute('SELECT erp_id FROM fees WHERE bundle=?', (key,)).fetchone()
            legacy = [self.db.execute('SELECT erp_id FROM fees WHERE bundle=?', (self.bundle_key(d),)).fetchone() for d, _ in group]
            if regenerate:
                if not ((existing and existing[0] == batch) or any(r and r[0] == batch for r in legacy)):
                    continue
                if not existing:
                    legacy_keys={self.bundle_key(d) for (d,_),record in zip(group,legacy) if record and record[0]==batch}
                    if legacy_keys & emitted_legacy:continue
                    emitted_legacy.update(legacy_keys)
            elif existing or any(legacy):
                continue
            all_data = [d for d, _ in group]
            # Inspect every original row of the same order even on a partial
            # shipment, so a zero fee row cannot hide a fee on a later item.
            all_data.extend(originals.get(key,[]))
            amounts = {self.voucher_fee(d) for d in all_data} - {Decimal(0)}
            if len(amounts) > 1:
                raise ValueError('동일 주문번호의 배송비가 다릅니다. 전표 작업표에서 배송비를 확정하세요.')
            amount = next(iter(amounts), Decimal(0))
            if amount:
                append({**group[0][1], 'code': '택배운송비', 'name': '배송비'}, 1, amount)
            if not regenerate and not preview:
                self.db.execute('INSERT INTO fees VALUES(?,?)', (key, batch))
