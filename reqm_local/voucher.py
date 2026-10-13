"""Daily voucher editing and reusable, colour-independent set allocations.

Rules use a reserved namespace in the existing shared mappings store so that
they participate in row-level sync without another cloud schema migration.
"""
import hashlib
import json
from pathlib import Path
from decimal import Decimal
from fractions import Fraction

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
        return 'model:' + family if family else 'sku:' + code

    def set_voucher_family(self, code, family):
        if code not in self.active_shipping_items:
            raise ValueError('현재 활성 품목을 선택하세요.')
        family=str(family).strip()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?)',(PREFIX+'family:'+code,json.dumps([family],ensure_ascii=False)))
            self.event('전표 색상 공유 그룹 변경',code)

    def voucher_rows(self, start, end, include_exported=False):
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

    def voucher_rule_key(self, row, total):
        from .service import display_channel
        if not row['full'] or len(row['components']) < 2 or row['issue']:
            return None
        count = Fraction(str(row['data'].get('quantity') or '1'))
        if count <= 0:
            return None
        parts = [(self.voucher_family(c['code']), str(Fraction(str(c['quantity'])) / count))
                 for c in row['components']]
        # Identical model appearing twice makes correspondence ambiguous.
        if len({family for family, _ in parts}) != len(parts):
            return None
        identity = [display_channel(row['channel']), row['data'].get('account', ''), sorted(parts), str(Fraction(str(total)) / count)]
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        return PREFIX + digest

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

    def set_voucher_amounts(self, row_id, total, amounts, remember=True):
        from .service import encode
        row = next((r for r in self.voucher_rows('0001-01-01', '9999-12-31') if r['id'] == row_id), None)
        if not row or row['issue'] or not row['components']:
            raise ValueError('미매칭 또는 이미 생성한 주문은 먼저 확인하세요.')
        total = won(total)
        values = [won(v) for v in amounts]
        if len(values) != len(row['components']) or sum(values) != total:
            raise ValueError('구성품 금액 합계가 입력한 상품 총금액과 같아야 합니다.')
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
            self.db.execute('INSERT OR REPLACE INTO mappings VALUES(?,?)',
                            (PREFIX + 'fee:' + key, json.dumps([str(won(amount))])))
            self.event('전표 배송비 확정', key)

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
