import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from reqm_local.service import Operations
from reqm_local.shipping_items import load_active_items


REFERENCE = Path(__file__).resolve().parents[1] / 'supabase/ecount_migration/data'


class ShippingItemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.service = Operations(self.folder, REFERENCE)

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def test_choices_names_and_recommendations_use_only_active_shipping_items(self):
        raw = json.loads((REFERENCE / 'shipping_items.json').read_text(encoding='utf-8'))
        expected = {r['item_code']:r['standard_name'] for r in raw['items'] if r['is_active']}
        self.assertEqual(len(expected),186)
        self.assertEqual({r['code']:r['name'] for r in self.service.item_choices()},expected)
        for query in ('QP1000A','QP2000A','케이스','충전기'):
            for row in self.service.item_candidates({'product':query},limit=1000):
                self.assertEqual(row['name'],expected[row['code']])
        self.assertIn('REQM-ShoppingBag-L',expected)
        self.assertNotIn('[RQM]-QP1000A1-BK',expected)
        self.assertNotIn('CASE-QP1000C-Hand-Pu',expected)

    def test_stale_database_and_legacy_catalog_cannot_expand_choices(self):
        self.service.db.execute("INSERT INTO item_names VALUES('OLD','QP1000A')")
        self.service.catalog.items['OLD']={'representative_name':'QP1000A'}
        self.assertNotIn('OLD',{r['code'] for r in self.service.item_choices()})
        self.assertNotIn('OLD',{r['code'] for r in self.service.item_candidates({'product':'QP1000A'},limit=1000)})
        with self.assertRaises(ValueError):
            self.service.save_item_name('OLD','QP1000A')
        with self.assertRaises(ValueError):
            self.service._validate_component_definitions([dict(code='OLD',name='OLD',logistics_code='OLD',
                quantity=1,unit_amount=0,warehouse='300',customer='C')])
        components,issue=self.service._build_components({'amount':'1000','quantity':'1'},[
            dict(code='OLD',name='OLD',unit_amount='0')])
        self.assertEqual(components,[])
        self.assertIn('사용 중인 품목',issue)

    def test_restart_migration_preserves_legacy_orders_artifacts_and_creates_backup(self):
        self.service.db.execute("INSERT INTO orders VALUES('O','I','{}','[]','출고 완료','')")
        self.service.db.execute("INSERT INTO artifacts VALUES('E','ERP','2026-10-12',?,1)",(b'old-export',))
        self.service.db.execute("INSERT INTO item_names VALUES('OLD','과거 품목')")
        self.service.db.commit()
        self.service.close()
        self.service=Operations(self.folder,REFERENCE)
        self.assertEqual(len(self.service.item_choices()),186)
        self.assertIsNone(self.service.db.execute("SELECT 1 FROM item_names WHERE erp_item_code='OLD'").fetchone())
        self.assertEqual(self.service.db.execute("SELECT content FROM artifacts WHERE id='E'").fetchone()[0],b'old-export')
        self.assertEqual(self.service.db.execute("SELECT state FROM orders WHERE id='O'").fetchone()[0],'출고 완료')
        with closing(sqlite3.connect(self.folder/'backups/before-shipping-item-catalog.sqlite3')) as backup:
            self.assertEqual(backup.execute("SELECT matching_name FROM item_names WHERE erp_item_code='OLD'").fetchone()[0],'과거 품목')
        self.service.close()
        self.service=Operations(self.folder,REFERENCE)
        self.assertEqual(len(self.service.item_choices()),186)

    def test_missing_or_duplicate_snapshot_does_not_fall_back_to_erp_catalog(self):
        with self.assertRaises(FileNotFoundError):
            load_active_items(self.folder)
        row={'item_code':'ABC','standard_name':'상품','is_active':True}
        (self.folder/'shipping_items.json').write_text(json.dumps({
            'source_table':'items','items':[row,{**row,'item_code':'abc'}]}),encoding='utf-8')
        with self.assertRaises(ValueError):
            load_active_items(self.folder)
