import tempfile
import unittest
from pathlib import Path

from reqm_local.files import parse_orders, workbook_bytes
from reqm_local.profiles import profile
from reqm_local.service import Operations


class ChannelAmountRulesTests(unittest.TestCase):
    def test_missing_ably_price_is_preserved_as_missing_and_reviewed(self):
        ably_profile=profile('에이블리',['에이블리'],{
            'line_no':['상품주문번호'],'order_no':['주문번호'],'product':['상품명'],
            'option':['옵션 정보'],'quantity':['수량'],'amount':['금액']})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'에이블리_발송 관리.xlsx'
            path.write_bytes(workbook_bytes(
                ['상품주문번호','주문번호','상품명','옵션 정보','수량'],
                [['LINE','ORDER','QP1000C','블루/선택안함',1]]))
            data=parse_orders(path,[ably_profile])[0]
        self.assertTrue(data['amount_missing'])
        service=Operations.__new__(Operations)
        components,issue=service.match(data)
        self.assertEqual(components,[])
        self.assertIn('금액 누락',issue)

    def test_missing_ably_price_is_reviewed_before_shipping(self):
        service=Operations.__new__(Operations)
        components,issue=service.match({'channel':'에이블리','amount':'0','amount_missing':True})
        self.assertEqual(components,[])
        self.assertIn('0원으로 전표 생성 불가',issue)

    def test_eri_rule_is_not_a_vat_exclusion(self):
        data={'channel':'이알아이','amount':'42900'}
        Operations._apply_channel_amount_rule(data)
        self.assertEqual(data['amount'],'27885')
        Operations._apply_channel_amount_rule(data)
        self.assertEqual(data['amount'],'27885')

    def test_legacy_ably_order_without_amount_column_is_not_a_free_order(self):
        data={'channel':'에이블리','amount':'0','column_matches':{'quantity':{}}}
        Operations._apply_channel_amount_rule(data)
        self.assertTrue(data['amount_missing'])
        gift={'channel':'에이블리','amount':'0','column_matches':{'amount':{}}}
        Operations._apply_channel_amount_rule(gift)
        self.assertNotIn('amount_missing',gift)

    def test_event_source_retains_eri_gross_price(self):
        data={'channel':'이알아이','amount':'42900','product':'QP2000C','option':'그린'}
        Operations._apply_channel_amount_rule(data)
        service=Operations.__new__(Operations)
        self.assertEqual(service._event_source(data)[2],'42900')


if __name__=='__main__':
    unittest.main()
