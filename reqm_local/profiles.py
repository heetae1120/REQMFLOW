from __future__ import annotations

SALES_CHANNELS = [
    '스마트스토어', '쌤몰', '오늘의집', '카카오톡스토어', '에이블리', '지그재그',
    '카카오선물하기', '11번가', '크림', '29CM', '이지웰', '이제너두',
    '베네피아', '삼성카드쇼핑몰', '삼성카드복지몰', '무신사', '한섬EQL',
    'W컨셉', 'SSF', '마켓컬리', '교보문고', '현대홈쇼핑', '이알아이',
    '와이즐리', '모트모트',
]

SMARTSTORE_ERP_MAPPING = '스마트스토어 ERP매칭'
MATCHING_CHANNELS = [SALES_CHANNELS[0], SMARTSTORE_ERP_MAPPING, *SALES_CHANNELS[1:]]


def profile(name, hints, columns=None, *, required=None, password='tkdtkd8911!@@', enabled=True,
            excludes=None, content_rule=None, combine=None, sum_columns=None, amount_is_unit=False,
            purpose='order'):
    columns = columns or {}
    required = required or []
    return {
        'preset_version': 1, 'name': name,
        'channel': '리큐엠_스마트스토어' if name == '스마트스토어' else name,
        'account': '기본', 'filename_hints': hints, 'required': required,
        'columns': columns, 'password': password, 'enabled': enabled,
        'excludes': excludes or [], 'content_rule': content_rule,
        'combine': combine or {}, 'sum_columns': sum_columns or {},
        'amount_is_unit': amount_is_unit,
        'purpose': purpose,
    }


PROFILE_PRESETS = [
    profile('스마트스토어',['스마트스토어_전체주문배송현황_20261002_1502.xlsx','스마트스토어'],{
        'order_no':['주문번호'],'line_no':['상품주문번호'],'product':['상품명'],'option':['옵션정보'],
        'quantity':['수량'],'amount':['최종 상품별 총 주문금액'],'recipient':['수취인명'],
        'phone':['수취인연락처1'],'postcode':['우편번호'],'address':['배송지','통합배송지'],
        'memo':['배송메세지','배송메시지'],'paid_at':['결제일'],'status':['주문상태'],
        'bundle':['배송비 묶음번호'],'shipping':['배송비 합계'],
    },password='1234',excludes=[{'column':'배송속성','equals':'N배송'}]),
    profile(SMARTSTORE_ERP_MAPPING,['스마트스토어_ERP','스마트스토어 ERP'],{
        'order_no':['주문번호'],'line_no':['상품주문번호'],'product':['상품명'],'option':['옵션정보','옵션'],
        'quantity':['수량'],'amount':['최종 상품별 총 주문금액','결제금액','금액'],
        'paid_at':['결제일','주문일자'],
    },required=[],password='1234',enabled=False,purpose='smartstore_erp'),
    profile('쌤몰',['o_20260721_1509_readyDeliveryList.csv','readyDeliveryList'],{
        'order_no':['배송번호'],'line_no':['품목별 주문번호'],'product':['주문상품명(기간할인 제목+버전)'],
        'option':['상품옵션'],'quantity':['주문품목 수량'],'amount':['판매가격'],'recipient':['수령인명'],
        'phone':['수령인 핸드폰'],'postcode':['수령인 우편번호(XXXXXX)'],'memo':['배송메시지2(한줄로)'],
        'paid_at':['입금확인일(결제일)'],'status':['주문상태(품목별)'],'bundle':['배송번호'],
        'shipping':['배송비(+지역별 배송비 포함)'],
    },combine={'address':['수령인 주소1','수령인 주소2']}),
    profile('29CM',['29CM_출고관리리스트_20261001.xlsx','29CM_출고관리리스트'],{
        'order_no':['주문번호'],'line_no':['품목고유번호'],'source_item_code':['상품코드'],'product':['상품명'],'option':['옵션명'],
        'quantity':['수량'],'amount':['판매가 합계'],'recipient':['수령인'],'phone':['수령자 연락처'],
        'postcode':['수령자 우편번호'],'address':['수령자 주소'],'memo':['배송요청사항'],
        'paid_at':['결제완료일'],'status':['주문상태'],'bundle':['배송번호'],
    }),
    profile('이지웰',['배송목록.20261001153125.xlsx','이지웰 배송목록'],{
        'order_no':['주문번호'],'line_no':['장바구니 번호'],'source_item_code':['상품코드'],'product':['상품명'],'option':['옵션'],
        'quantity':['주문수량'],'amount':['실주문금액'],'recipient':['수령자명'],
        'phone':['수령자 휴대폰번호'],'postcode':['우편번호'],'address':['주소'],
        'memo':['배송메시지(요청사항)'],'paid_at':['주문일시'],'status':['배송상태'],
        'bundle':['장바구니 번호'],'shipping':['배송비'],
    }),
    profile('베네피아',['csvDownDlvyList_20260930.xls','csvDownDlvyList'],{
        'order_no':['주문번호'],'line_no':['주문순번'],'product':['상품명'],'option':['옵션명'],
        'quantity':['수량'],'amount':['결제금액'],'recipient':['수령인'],'phone':['연락처(휴대전화)'],
        'postcode':['우편번호'],'memo':['고객요청사항'],'paid_at':['주문일'],'status':['주문/배송상태'],
        'bundle':['배송번호'],'shipping':['배송비'],
    },combine={'address':['주소','상세주소']}),
    profile('무신사',['invoice_list_2026100115.xls','invoice_list'],{
        'order_no':['주문번호'],'line_no':['주문일련번호'],'product':['[상품번호]상품명'],'option':['옵션'],
        'quantity':['주문수량'],'amount':['판매가'],'recipient':['수령자'],'phone':['핸드폰'],
        'postcode':['우편번호'],'address':['주소'],'memo':['출고메시지'],'paid_at':['주문일시'],
        'status':['주문상태'],'bundle':['출고차수'],'shipping':['배송비'],
    }),
    profile('W컨셉',['상품준비중내역 (8).xlsx','상품준비중내역','W컨셉'],{
        'order_no':['주문번호'],'line_no':['상품코드'],'source_item_code':['상품코드'],'product':['상품명'],'option':['옵션1'],
        'quantity':['수량'],'amount':['판매가'],'recipient':['수취인'],'phone':['수취인연락처2','수취인연락처1'],
        'postcode':['수취인우편번호'],'address':['배송지'],'memo':['배송메모'],'paid_at':['결제일시'],
        'status':['요청유형'],'bundle':['주문번호'],'shipping':['선결제 배송비'],
    }),
    profile('SSF',['배송조회 (16).xls','SSF 배송조회'],{
        'order_no':['주문번호'],'line_no':['업체상품코드'],'source_item_code':['업체상품코드'],'product':['상품명'],'option':['옵션'],
        'quantity':['주문수량'],'amount':['결제금액'],'recipient':['수령자명'],'phone':['연락처'],
        'postcode':['우편번호'],'address':['주소'],'memo':['배송요청사항'],'paid_at':['주문일자'],
        'status':['배송상태'],'bundle':['주문번호'],
    },content_rule={'required_headers':['SSF상품코드','결제금액'],
                    'forbidden_headers':['출고지시상품번호','협력사상품코드']}),
    profile('교보문고',['vendor_order_list (13).xls','vendor_order_list','교보문고'],{
        'order_no':['주문번호'],'line_no':['교보주문번호'],'source_item_code':['상품코드'],'product':['상품이름'],
        'option':['상품옵션','사양명'],'quantity':['상품수량'],'amount':['판매금액'],
        'recipient':['수취인'],'phone':['수취인핸드폰'],'postcode':['우편번호'],'memo':['배송메세지'],
        'paid_at':['고객결제일'],'status':['배송상태','주문상태'],'bundle':['주문번호'],
    },content_rule={'required_headers':['교보주문번호','상품이름','매입단가']},
            combine={'address':['주소1','주소2']}),
    profile('현대홈쇼핑',['260819-현대홈쇼핑(1).xls','현대홈쇼핑'],{
        'order_no':['주문번호'],'line_no':['순번'],'product':['상품명'],'option':['속성명'],
        'quantity':['대상\n수량'],'amount':['판매가'],'recipient':['인수자'],'phone':['인수자 HP'],
        'postcode':['우편번호'],'address':['인수자 주소'],'memo':['고객메시지'],'paid_at':['출고요청일'],
        'status':['진행단계'],'bundle':['합포장번호'],'shipping':['배송비'],
    },password='020360'),
    profile('이알아이',['DeliveryReadyList_1790835302204.xls','DeliveryReadyList','이알아이'],{
        'order_no':['주문번호'],'line_no':['주문상품일련번호'],'source_item_code':['상품코드'],'product':['상품명'],'option':['상품옵션'],
        'quantity':['주문수량'],'amount':['판매가'],'recipient':['수령인명'],'phone':['수령인핸드폰번호'],
        'postcode':['우편번호'],'memo':['배송메세지'],'paid_at':['주문일자'],'status':['처리상황'],
        'bundle':['주문번호'],
    },password='5666',combine={'address':['주소','상세주소']}),
    profile('삼성카드복지몰',['Excel_20261001153442.xlsx','Excel','삼성복지몰'],{
        'order_no':['주문번호'],'line_no':['배송번호'],'source_item_code':['상품코드'],
        'product':['상품명'],'option':['단품명'],'quantity':['실수량','지시수량'],'amount':['판매금액'],
        'recipient':['수취인'],'phone':['가상휴대폰','휴대폰','가상전화번호','전화번호'],
        'address':['주소'],'memo':['고객배송요청사항','주문요청메시지'],'paid_at':['배송지시일'],
        'status':['배송상태'],'bundle':['배송번호'],
    },required=[],content_rule={'column_index':2,'prefix':'BA'}),
    profile('삼성카드쇼핑몰',['Excel_20260907151205.xlsx','Excel','삼성쇼핑몰'],{
        'order_no':['주문번호'],'line_no':['배송번호'],'source_item_code':['상품코드'],
        'product':['상품명'],'option':['단품명'],'quantity':['실수량','지시수량'],'amount':['판매금액'],
        'recipient':['수취인'],'phone':['가상휴대폰','휴대폰','가상전화번호','전화번호'],
        'address':['주소'],'memo':['고객배송요청사항','주문요청메시지'],'paid_at':['배송지시일'],
        'status':['배송상태'],'bundle':['배송번호'],
    },required=[],content_rule={'not':{'column_index':2,'prefix':'BA'}}),
    profile('한섬EQL',['한섬-Excel_20261001153442.xlsx','한섬 Excel','한섬'],{
        'order_no':['주문번호'],'line_no':['출고지시상품번호'],'source_item_code':['업체상품코드'],
        'product':['상품명'],'quantity':['주문수량'],'amount':['주문금액'],'recipient':['수취인명'],
        'phone':['연락처'],'postcode':['우편번호'],'address':['주소'],'memo':['배송요청사항'],
        'paid_at':['주문일시'],'status':['배송상태'],'bundle':['주문번호'],'shipping':['배송비'],
    },required=[],content_rule={'required_headers':['출고지시상품번호','협력사상품코드','옵션1']},
            combine={'option':['옵션1','옵션2','옵션3']}),
    profile('이제너두',['Excel (46).xlsx','이제너두 Excel','이제너두'],{
        'order_no':['주문번호'],'line_no':['상세순번'],'source_item_code':['업체상품번호'],
        'product':['상품명'],'option':['단품명'],'quantity':['수량'],'amount':['판매금액'],
        'recipient':['수령인'],'phone':['수령인핸드폰번호','수령인전화번호'],'postcode':['수령인우편번호'],
        'address':['수령인주소'],'memo':['배송요청사항'],'paid_at':['출고지시일'],'status':['주문상태'],
        'bundle':['주문번호'],'shipping':['배송비'],
    },required=[]),
    profile('마켓컬리',['260918-마켓컬리.xlsx','마켓컬리'],{
        'order_no':['대표주문번호'],'line_no':['개별주문번호'],'source_item_code':['상품번호'],
        'product':['상품명'],'option':['옵션명'],'quantity':['수량'],'amount':['주문금액'],
        'recipient':['수취인명'],'phone':['수취인 연락처'],'postcode':['우편번호'],'address':['배송지 주소'],
        'memo':['배송메모'],'paid_at':['주문일시'],'status':['주문상태'],'bundle':['대표주문번호'],
    },required=[]),
    profile('모트모트',['260626-모트모트.xls','모트모트','motemote'],{
        'order_no':['주문번호'],'line_no':['주문상품옵션번호'],'source_item_code':['상품번호','상품관리코드'],
        'product':['상품명'],'option':['옵션명:옵션값'],'quantity':['수량'],'amount':['판매가(할인적용가)'],
        'recipient':['수령자명'],'phone':['수령자휴대전화'],'postcode':['우편번호'],'address':['주소'],
        'memo':['배송메모'],'paid_at':['결제일시','주문일시'],'status':['배송구분'],'bundle':['배송번호'],
    },content_rule={'required_headers':['쇼핑몰구분','주문상품옵션번호','판매가(할인적용가)']},
            amount_is_unit=True, sum_columns={'shipping':['기본배송비','지역별배송비']}),
    profile('와이즐리',['orders_','와이즐리','리큐엠'],{
        'order_no':['주문번호'],'line_no':['품목주문번호'],'source_item_code':['상품코드(SKU 코드)'],
        'product':['상품명'],'option':['상품옵션명','상품옵션코드'],'quantity':['수량'],'amount':['단가'],
        'recipient':['수령인'],'phone':['수령인 전화번호'],'postcode':['우편번호'],'memo':['배송메시지'],
        'paid_at':['주문일시'],'bundle':['주문번호'],'shipping':['배송비'],
    },content_rule={'required_headers':['품목주문번호','상품코드(SKU 코드)','환불수량']},
            amount_is_unit=True, combine={'address':['주소','상세주소']}),
]

PRESET_COLUMN_INDEXES = {
    '스마트스토어': {'order_no':1,'line_no':0,'product':16,'option':20,'quantity':21,'amount':27,'recipient':13,'phone':48,'postcode':52,'address':50,'paid_at':29,'status':3,'bundle':42,'shipping':45},
    SMARTSTORE_ERP_MAPPING: {},
    '쌤몰': {'order_no':0,'line_no':1,'product':3,'option':4,'quantity':6,'amount':22,'recipient':8,'phone':10,'postcode':11,'memo':15,'paid_at':28,'status':26,'bundle':0,'shipping':16},
    '29CM': {'order_no':3,'line_no':0,'source_item_code':7,'product':8,'option':10,'quantity':11,'amount':21,'recipient':6,'phone':22,'postcode':23,'address':24,'memo':25,'paid_at':29,'status':33,'bundle':1},
    '이지웰': {'order_no':3,'line_no':5,'source_item_code':10,'product':11,'option':13,'quantity':14,'amount':45,'recipient':36,'phone':37,'postcode':38,'address':39,'memo':40,'paid_at':2,'status':21,'bundle':6,'shipping':44},
    '베네피아': {'order_no':0,'line_no':1,'product':10,'option':12,'quantity':14,'amount':16,'recipient':18,'phone':25,'postcode':28,'memo':31,'paid_at':6,'status':4,'bundle':5,'shipping':17},
    '무신사': {'order_no':1,'line_no':2,'product':12,'option':13,'quantity':14,'amount':23,'recipient':5,'phone':11,'postcode':6,'address':7,'memo':3,'paid_at':36,'status':27,'bundle':0,'shipping':33},
    'W컨셉': {'order_no':1,'line_no':11,'source_item_code':11,'product':12,'option':13,'quantity':16,'amount':19,'recipient':3,'phone':5,'postcode':6,'address':7,'memo':8,'paid_at':0,'status':9,'bundle':1,'shipping':28},
    'SSF': {'order_no':1,'line_no':20,'source_item_code':20,'product':21,'option':22,'quantity':23,'amount':28,'recipient':13,'phone':16,'postcode':14,'address':15,'memo':17,'paid_at':0,'status':3,'bundle':1},
    '교보문고': {'order_no':8,'line_no':9,'source_item_code':20,'product':21,'option':23,'quantity':24,'amount':36,'recipient':10,'phone':11,'postcode':16,'memo':13,'paid_at':4,'status':32,'bundle':8},
    '현대홈쇼핑': {'order_no':8,'line_no':9,'product':5,'option':7,'quantity':14,'amount':29,'recipient':33,'phone':35,'postcode':36,'address':37,'memo':40,'paid_at':23,'status':20,'bundle':18,'shipping':31},
    '이알아이': {'order_no':11,'line_no':13,'source_item_code':12,'product':14,'option':15,'quantity':17,'amount':19,'recipient':23,'phone':28,'postcode':24,'memo':29,'paid_at':10,'status':9,'bundle':11},
    '삼성카드복지몰': {'order_no':2,'line_no':4,'source_item_code':12,'product':13,'option':14,'quantity':17,'amount':19,'recipient':22,'phone':24,'address':27,'memo':28,'paid_at':3,'status':6,'bundle':4},
    '삼성카드쇼핑몰': {'order_no':0,'line_no':2,'source_item_code':9,'product':10,'option':11,'quantity':14,'amount':16,'recipient':19,'phone':21,'address':24,'memo':25,'paid_at':1,'status':4,'bundle':2},
    '한섬EQL': {'order_no':2,'line_no':30,'source_item_code':20,'product':21,'option':22,'quantity':26,'amount':42,'recipient':14,'phone':17,'postcode':15,'address':16,'memo':18,'paid_at':1,'status':5,'bundle':2,'shipping':43},
    '이제너두': {'order_no':3,'line_no':4,'source_item_code':6,'product':8,'option':9,'quantity':13,'amount':17,'recipient':25,'phone':27,'postcode':28,'address':29,'memo':30,'paid_at':1,'status':11,'bundle':3,'shipping':18},
    '마켓컬리': {'order_no':1,'line_no':0,'source_item_code':4,'product':5,'option':6,'quantity':12,'amount':13,'recipient':19,'phone':20,'postcode':22,'address':21,'memo':23,'paid_at':3,'status':2,'bundle':1},
    '모트모트': {'order_no':22,'line_no':35,'source_item_code':27,'product':31,'option':34,'quantity':37,'amount':38,'recipient':3,'phone':4,'postcode':5,'address':6,'memo':2,'paid_at':40,'status':0,'bundle':1,'shipping':14},
    '와이즐리': {'order_no':1,'line_no':2,'source_item_code':3,'product':4,'option':6,'quantity':9,'amount':8,'recipient':11,'phone':12,'postcode':13,'address':14,'memo':16,'paid_at':26,'bundle':1,'shipping':23},
}
for _preset in PROFILE_PRESETS:
    _preset['column_indexes'] = PRESET_COLUMN_INDEXES.get(_preset['name'], {})


def merge_profile_presets(settings):
    profiles = settings.setdefault('profiles', [])
    for preset in PROFILE_PRESETS:
        existing = next((item for item in profiles if item.get('name') == preset['name'] or item.get('channel') == preset['channel']), None)
        if existing and existing.get('customized'):
            # 판매처별 사용자 열 매칭은 유지하되, 서로 유사한 양식을 가르는
            # 안전 규칙은 최신 프리셋을 따른다.
            if preset.get('content_rule'):
                existing['content_rule'] = preset['content_rule']
            # 금액 단위와 배송비 합산은 열 이름 사용자 지정과 무관한 판매처 규칙이다.
            existing['amount_is_unit'] = preset.get('amount_is_unit', False)
            existing['sum_columns'] = preset.get('sum_columns', {})
            existing['purpose'] = preset.get('purpose', 'order')
            continue
        if existing:
            existing.clear(); existing.update(preset)
        else:
            profiles.append(dict(preset))
    return settings
