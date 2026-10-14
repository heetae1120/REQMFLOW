import unittest
from decimal import Decimal
from tests import test_local_operations as local_fixture
from reqm_local.service import Operations


class OhouShippingAmountTests(unittest.TestCase):
    setUp = local_fixture.LocalTests.setUp
    tearDown = local_fixture.LocalTests.tearDown
    import_order = local_fixture.LocalTests.import_order
    map = local_fixture.LocalTests.map
    request = local_fixture.LocalTests.request
    def test_import_mapping_and_erp_keep_payment_total(self):
        _,order=self.import_order(q=1,amount=32500,fee=3000)
        self.assertEqual(order['data']['amount'],'29500')
        self.assertEqual(order['data']['ohou_payment_total'],'32500')
        self.map(order)
        order=next(o for o in self.s.orders() if o['id']==order['id'])
        self.assertEqual(order['components'][0]['amount'],'29500')
        self.request(order)
        self.s.auto_import_shipments('2026-10-01')
        rows=self.s.export_erp('2026-10-01','2026-10-01',None,preview=True)
        self.assertEqual(sum(Decimal(str(r[18]))+Decimal(str(r[19])) for r in rows),Decimal('32500'))
        self.assertEqual(sum(r[15] for r in rows if r[12]=='택배운송비'),1)

    def test_multiple_items_deduct_order_shipping_once(self):
        _,first=self.import_order(q=1,amount=32500,fee=3000,line='A1')
        _,second=self.import_order(q=1,amount=10000,fee=3000,line='B2')
        self.assertEqual(first['data']['amount'],'29500')
        self.assertEqual(second['data']['amount'],'10000')
        self.s.refresh_matches()
        data={o['data']['line_no']:o['data']['amount'] for o in self.s.orders()}
        self.assertEqual(data,{'A1':'29500','B2':'10000'})

    def test_fee_confirmation_recalculates_from_original_payment(self):
        _,order=self.import_order(q=1,amount=32500,fee=3000)
        self.map(order)
        self.s.set_voucher_fee(order['data'],5000)
        order=next(o for o in self.s.orders() if o['id']==order['id'])
        self.assertEqual(order['data']['amount'],'27500')
        self.assertEqual(order['components'][0]['amount'],'27500')
        self.s.set_voucher_fee(order['data'],0)
        order=next(o for o in self.s.orders() if o['id']==order['id'])
        self.assertEqual(order['data']['amount'],'32500')

    def test_zero_shipping_and_excess_fee(self):
        data={'channel':'오늘의집','amount':'32500','shipping':'0'}
        Operations._apply_ohou_shipping_rule(data)
        self.assertEqual(data['amount'],'32500')
        with self.assertRaisesRegex(ValueError,'총 결제금액보다'):
            Operations._apply_ohou_shipping_rule(data,33000)

    def test_confirm_fee_after_shipping_updates_unexported_erp_total(self):
        _,order=self.import_order(q=1,amount=32500,fee=0)
        self.map(order)
        self.request(order)
        self.s.auto_import_shipments('2026-10-01')
        self.s.set_voucher_fee(order['data'],3000)
        rows=self.s.export_erp('2026-10-01','2026-10-01',None,preview=True)
        self.assertEqual(sum(Decimal(str(r[18]))+Decimal(str(r[19])) for r in rows),Decimal('32500'))
        self.assertEqual(sum(r[15]*r[16] for r in rows if r[12]!='택배운송비'),29500)

    def test_fee_change_with_partial_shipment_rolls_back(self):
        _,order=self.import_order(q=2,amount=32500,fee=3000)
        self.map(order)
        line=self.request(order)
        local_fixture.LocalTests.result(self,line,1)
        before=self.s.orders()[0]['data']['amount']
        with self.assertRaisesRegex(ValueError,'부분 출고'):
            self.s.set_voucher_fee(order['data'],5000)
        self.assertEqual(self.s.orders()[0]['data']['amount'],before)
        self.assertEqual(self.s.voucher_fee(order['data']),Decimal('3000'))

    def test_invalid_legacy_price_is_reviewed_without_blocking_startup(self):
        from reqm_local.service import encode
        data={'channel':'오늘의집','order_no':'OLD','line_no':'OLD-LINE','account':'기본',
              'amount':'0','shipping':'3000','quantity':'1'}
        with self.s.db:
            self.s.db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?)',
                ('LEGACY','LEGACY',encode(data),'[]','출고 준비',''))
        self.s.apply_pending_channel_amount_rules()
        order=self.s.orders()[0]
        self.assertEqual(order['state'],'검토 필요')
        self.assertEqual(order['data']['amount'],'0')
        self.assertIn('총 결제금액보다',order['issue'])


if __name__=='__main__':
    unittest.main()
