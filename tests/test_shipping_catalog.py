import unittest
from pathlib import Path

from reqm_local.cloud import load_catalog
from reqm_local.shipping import ShippingCatalog, compact


REFERENCE=Path(__file__).resolve().parents[1]/'supabase/ecount_migration/data'


class _Response:
    def __init__(self, data):
        self.data=data


class _Query:
    def __init__(self, rows):
        self.rows=rows

    def select(self, _columns):
        return self

    def range(self, start, end):
        self.page=self.rows[start:end+1]
        return self

    def execute(self):
        if isinstance(self.rows, Exception):
            raise self.rows
        return _Response(self.page)


class _Client:
    def __init__(self, tables):
        self.tables=tables

    def table(self, name):
        return _Query(self.tables.get(name, []))


class ShippingCatalogTests(unittest.TestCase):
    def catalog(self, *, aliases=(), skus=None, products=(), components=(), barcodes=()):
        items = [
            {'item_code':'PAD-BLUE','standard_name':'실리콘패드 스카이블루','is_active':True},
            {'item_code':'CABLE','standard_name':'케이블','is_active':True},
        ]
        if skus is None:
            skus = [
                {'item_code':'PAD-BLUE','product_name':'실리콘패드 클라우드','sku_no':'37474022648361','is_active':True},
                {'item_code':'CABLE','product_name':'케이블','sku_no':'SKU-CABLE','is_active':True},
            ]
        return ShippingCatalog(items, products, components, aliases, barcodes, skus)

    def test_exact_channel_alias_resolves_and_ignores_legacy_component_multiplier(self):
        source='리큐엠 실리콘패드 스카이블루'
        catalog=self.catalog(aliases=[{
            'source_channel':'29CM','normalized_source':compact(source),
            'components':[{'item_code':'PAD-BLUE','quantity':5}], 'is_active':True,
        }])
        result=catalog.resolve({'channel':'29CM','product':'리큐엠 실리콘패드','option':'스카이블루'})
        self.assertEqual(result['state'],'ready')
        self.assertEqual(result['method'],'판매처별 저장 별칭')
        self.assertEqual(result['components'][0]['sku_no'],'37474022648361')

    def test_shipping_program_legacy_channel_name_is_reused(self):
        catalog=self.catalog(aliases=[{
            'source_channel':'(주)한섬',
            'source_product_name':'리큐엠 실리콘패드',
            'source_options':'스카이블루',
            'normalized_source':'이전버전에서저장된키',
            'components':[{'item_code':'PAD-BLUE'}], 'is_active':True,
        }])
        result=catalog.resolve({'channel':'한섬EQL','product':'리큐엠 실리콘패드','option':'스카이블루'})
        self.assertEqual(result['state'],'ready')
        self.assertEqual(result['method'],'판매처별 저장 별칭')

    def test_similar_text_is_not_automatically_matched(self):
        catalog=self.catalog(products=[{'registered_product_id':'P1','original_name':'캐리어 저울','is_active':True}],
                             components=[{'registered_product_id':'P1','item_code':'PAD-BLUE','sequence':1}])
        result=catalog.resolve({'channel':'29CM','product':'캐리어용 저울 신형','option':''})
        self.assertEqual(result['state'],'no_match')

    def test_duplicate_exact_alias_is_blocked(self):
        key=compact('같은 상품 기본')
        aliases=[
            {'source_channel':'29CM','normalized_source':key,'components':[{'item_code':'PAD-BLUE'}],'is_active':True},
            {'source_channel':'29CM','normalized_source':key,'components':[{'item_code':'CABLE'}],'is_active':True},
        ]
        result=self.catalog(aliases=aliases).resolve({'channel':'29CM','product':'같은 상품','option':'기본'})
        self.assertEqual(result['state'],'blocked')
        self.assertIn('여러 품목',result['reason'])

    def test_exact_barcode_resolves_but_missing_sku_blocks(self):
        barcode=[{'barcode':'880000000001','item_code':'PAD-BLUE','is_active':True}]
        ready=self.catalog(barcodes=barcode).resolve({'source_item_code':'880000000001'})
        self.assertEqual(ready['state'],'ready')
        blocked=self.catalog(barcodes=barcode,skus=[
            {'item_code':'CABLE','product_name':'케이블','sku_no':'SKU-CABLE','is_active':True},
        ]).resolve({'source_item_code':'880000000001'})
        self.assertEqual(blocked['state'],'blocked')
        self.assertIn('위킵 SKU 미등록',blocked['reason'])

    def test_cloud_catalog_failure_is_preserved_as_a_shipping_blocker(self):
        tables={
            'items':[{'item_code':'PAD-BLUE','standard_name':'실리콘패드 스카이블루','is_active':True}],
            'wekeep_sku_mappings':[{'item_code':'PAD-BLUE','product_name':'실리콘패드','sku_no':'SKU-PAD','is_active':True}],
            'item_aliases':RuntimeError('permission denied'),
        }
        catalog,counts=load_catalog(_Client(tables),REFERENCE)
        self.assertFalse(catalog.shipping_catalog.available)
        self.assertIn('item_aliases',catalog.shipping_catalog.blocking_reason)
        self.assertEqual(counts['item_aliases'],0)


if __name__ == '__main__':
    unittest.main()
