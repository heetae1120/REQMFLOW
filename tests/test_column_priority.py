import tempfile
import unittest
from pathlib import Path

from reqm_local.column_matching import find_column, match_columns
from reqm_local.files import parse_orders, workbook_bytes
from reqm_local.service import Operations
from reqm_local.shipping import channel_key
from reqm_local.profiles import PROFILE_PRESETS, merge_profile_presets


class ColumnPriorityTests(unittest.TestCase):
    def test_all_supplied_closed_mall_profiles_are_enabled(self):
        names = {'29CM','SSF','W컨셉','마켓컬리','무신사','베네피아','삼성카드복지몰',
                 '삼성카드쇼핑몰','이알아이','이제너두','이지웰','한섬EQL','현대홈쇼핑'}
        profiles = {profile['name']: profile for profile in PROFILE_PRESETS}
        self.assertTrue(all(profiles[name].get('enabled', True) for name in names))
        self.assertTrue(all(profiles[name].get('columns', {}).get('product') for name in names))

    def test_samsung_welfare_extracts_postcode_and_uses_actual_quantity(self):
        profile = next(profile for profile in PROFILE_PRESETS if profile['name']=='삼성카드복지몰')
        headers = ['고객사','사번','주문번호','배송지시일','배송번호','배송유형','배송상태','택배사',
                   '출하지시일','배송희망일','송장번호','브랜드','상품코드','상품명','단품명','지시수량',
                   '취소수량','실수량','공급가','판매금액','주문요청메시지','주문자','수취인','휴대폰',
                   '가상휴대폰','전화번호','가상전화번호','주소','고객배송요청사항','개인통관고유부호']
        row = ['고객','1','BA-1','20261003','D-1','정상','출하지시','','','','','리큐엠','P-1',
               '상품','블랙',3,1,2,1000,2000,'','주문자','수취인','01012345678','','','','(12345) 서울시 테스트로 1','문앞','']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'삼성복지몰.xlsx';path.write_bytes(workbook_bytes(headers,[row]))
            parsed = parse_orders(path,[profile])[0]
        self.assertEqual(parsed['quantity'],'2')
        self.assertEqual(parsed['postcode'],'12345')
        self.assertEqual(parsed['address'],'서울시 테스트로 1')
        self.assertEqual(parsed['phone'],'01012345678')

    def test_ssf_corrected_preset_repairs_stale_custom_price_and_recipient(self):
        preset = next(profile for profile in PROFILE_PRESETS if profile['name']=='SSF')
        stale = {**preset, 'customized':True, 'columns':{**preset['columns'],
                 'amount':['쿠폰할인'], 'recipient':['업체메모']}}
        headers=['주문일자','주문번호','배송상태','수령자명','우편번호','주소','연락처','배송요청사항',
                 '업체상품코드','상품명','옵션','주문수량','판매가','쿠폰할인','결제금액','업체메모','SSF상품코드']
        row=['2026-10-03','O1','출고지시','수령인','12345','서울 테스트로 1','01012345678','',
             'CODE','테스트 상품','검정',1,4900,0,4900,'','SSF-1']
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'SSF.xlsx';path.write_bytes(workbook_bytes(headers,[row]))
            parsed=parse_orders(path,[stale])[0]
        self.assertEqual(parsed['amount'],'4900')
        self.assertEqual(parsed['recipient'],'수령인')

    def test_ssf_and_handsome_are_separated_by_unique_headers(self):
        profiles = [profile for profile in PROFILE_PRESETS if profile['name'] in ('SSF', '한섬EQL')]
        ssf_headers = ['주문일자','주문번호','배송상태','수령자명','우편번호','주소','연락처',
                       '배송요청사항','업체상품코드','상품명','옵션','주문수량','결제금액','SSF상품코드']
        handsome_headers = ['주문일시','주문번호','배송상태','수취인명','우편번호','주소','연락처',
                            '배송요청사항','업체상품코드','상품명','옵션1','옵션2','옵션3','주문수량',
                            '출고지시상품번호','주문금액','배송비','협력사상품코드']
        with tempfile.TemporaryDirectory() as folder:
            ssf_path = Path(folder)/'Report-SSF.xlsx'
            handsome_path = Path(folder)/'Report-한섬.xlsx'
            ssf_row = ['2026-10-03','S-1','출고지시','수령인','12345','서울','010','',
                       'P-1','SSF 상품','검정',1,4900,'SSF-1']
            handsome_row = ['2026-10-03','H-1','출고지시','수취인','12345','서울','010','',
                            'P-2','한섬 상품','검정','','',1,'SHIP-1',17900,0,'VENDOR-1']
            ssf_path.write_bytes(workbook_bytes(ssf_headers, [ssf_row]))
            handsome_path.write_bytes(workbook_bytes(handsome_headers, [handsome_row]))
            self.assertEqual(parse_orders(ssf_path, profiles)[0]['channel'], 'SSF')
            self.assertEqual(parse_orders(handsome_path, profiles)[0]['channel'], '한섬EQL')

    def test_customized_profiles_receive_latest_classification_rule(self):
        settings = {'profiles': [
            {'name':'SSF','channel':'SSF','customized':True,'columns':{'product':['내상품명']}},
            {'name':'한섬EQL','channel':'한섬EQL','customized':True,'columns':{'product':['내상품명']}},
        ]}
        merge_profile_presets(settings)
        profiles = {profile['name']: profile for profile in settings['profiles']}
        self.assertEqual(profiles['SSF']['columns']['product'], ['내상품명'])
        self.assertIn('SSF상품코드', profiles['SSF']['content_rule']['required_headers'])
        self.assertIn('출고지시상품번호', profiles['한섬EQL']['content_rule']['required_headers'])

    def test_new_direct_marketplace_formats_and_amount_rules(self):
        profiles = [profile for profile in PROFILE_PRESETS if profile['name'] in ('모트모트','교보문고','와이즐리')]
        cases = [
            ('모트모트.xlsx',
             ['배송구분','배송번호','배송메모','수령자명','수령자휴대전화','우편번호','주소','쇼핑몰구분',
              '주문번호','상품번호','상품명','옵션명:옵션값','주문상품옵션번호','수량','판매가(할인적용가)',
              '결제일시','기본배송비','지역별배송비'],
             ['파트너사배송','D1','문앞','수령인','01012345678','01234','서울','motemote','O1','P1',
              '모트 상품','색상: 블루','L1',2,28500,'2026-10-03',3000,2000],
             '모트모트','57000','5000'),
            ('교보문고.xlsx',
             ['주문번호','교보주문번호','수취인','수취인핸드폰','우편번호','주소1','주소2','상품코드',
              '상품이름','상품옵션','상품수량','배송상태','판매금액','매입단가'],
             ['O2','L2','수령인',1032979418,5504,'서울','101호','P2','교보 상품','블랙',1,'상품준비',77900,50000],
             '교보문고','77900',''),
            ('orders_와이즐리.xlsx',
             ['주문번호','품목주문번호','상품코드(SKU 코드)','상품명','상품옵션명','단가','수량','환불수량',
              '수령인','수령인 전화번호','우편번호','주소','상세주소','배송메시지','배송비','주문일시'],
             ['O3','L3','P3','와이즐리 상품','화이트',16500,2,0,'수령인','01012345678','01234','서울','101호','문앞',0,'2026-10-03'],
             '와이즐리','33000','0'),
        ]
        with tempfile.TemporaryDirectory() as folder:
            for filename,headers,row,channel,amount,shipping in cases:
                path=Path(folder)/filename
                path.write_bytes(workbook_bytes(headers,[row]))
                parsed=parse_orders(path,profiles)[0]
                self.assertEqual((parsed['channel'],parsed['amount'],parsed['shipping']),(channel,amount,shipping))
            parsed=parse_orders(Path(folder)/'교보문고.xlsx',profiles)[0]
            self.assertEqual((parsed['phone'],parsed['postcode']),('01032979418','05504'))

    def test_exact_wins_even_when_near_column_comes_first(self):
        match = find_column(['수취인연락처', '수취인연락처1'], ['수취인연락처1'])
        self.assertEqual((match['index'], match['method']), (1, '일치'))

    def test_unique_near_and_ambiguous_near(self):
        self.assertEqual(find_column(['수취인연락처'], ['수취인연락처1'])['method'], '근사')
        self.assertIsNone(find_column(['수취인연락처2', '수취인연락처3'], ['수취인연락처1']))

    def test_cancel_quantity_is_not_used_as_near_quantity(self):
        self.assertIsNone(find_column(['취소수량'], ['취소수량값'], field='quantity'))

    def test_exact_columns_are_reserved_before_near_matching(self):
        matched = match_columns(['수취인연락처'], {'phone': ['수취인연락처1'], 'other': ['수취인연락처']})
        self.assertNotIn('phone', matched)
        self.assertEqual(matched['other']['method'], '일치')

    def test_saved_format_applies_to_import_and_reports_near_column(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '주문.xlsx'
            path.write_bytes(workbook_bytes(['상품명', '수량', '수취인연락처'], [['테스트', 2, '01012345678']]))
            profile = {'name': '저장 양식', 'channel': '테스트몰', 'enabled': True,
                       'required': ['상품명'], 'columns': {'product': ['상품명'], 'quantity': ['수량'], 'phone': ['수취인연락처1']}}
            rows = parse_orders(path, [profile])
            self.assertEqual(rows[0]['product'], '테스트')
            self.assertEqual(rows[0]['format_name'], '저장 양식')
            self.assertEqual(rows[0]['column_matches']['phone']['method'], '근사')

    def test_prefixed_sales_rules_reused_without_mutating_catalog(self):
        reference = Path(__file__).resolve().parents[1] / 'supabase/ecount_migration/data'
        with tempfile.TemporaryDirectory() as folder:
            service = Operations(Path(folder), reference)
            try:
                catalog = service.conversion_catalog('스마트스토어')
                prefixed = [(source, value) for (channel, source), value in service.catalog.mappings.items()
                            if channel == '리큐엠_스마트스토어']
                self.assertTrue(prefixed)
                for source, value in prefixed:
                    self.assertEqual(catalog.mappings[('스마트스토어', source)], value)
                self.assertEqual(service.channel_customer_code('리큐엠_스마트스토어'), 'AC008712')
                self.assertNotEqual(channel_key('삼성복지몰'), channel_key('삼성쇼핑몰'))
            finally:
                service.close()
