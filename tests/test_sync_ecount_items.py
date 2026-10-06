import csv
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from tools.sync_ecount_items import sync


class SyncEcountItemsTests(unittest.TestCase):
    def test_adds_only_missing_codes_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            source=folder/'items.xlsx'
            book=Workbook();sheet=book.active
            sheet.append(['품목코드','품목명'])
            sheet.append(['OLD','기존 이름은 덮어쓰지 않음'])
            sheet.append(['NEW','새 품목'])
            book.save(source);book.close()
            target=folder/'ecount_item_reference.csv'
            with target.open('w',encoding='utf-8',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=(
                    'item_code','representative_name','alias_count','first_source_row','review_status','is_active',
                ),lineterminator='\n')
                writer.writeheader();writer.writerow({
                    'item_code':'OLD','representative_name':'기존 품목','alias_count':'1',
                    'first_source_row':'10','review_status':'confirmed','is_active':'true',
                })
            self.assertEqual([row['item_code'] for row in sync(source,target)],['NEW'])
            self.assertEqual(sync(source,target),[])
            with target.open(encoding='utf-8') as handle:
                rows=list(csv.DictReader(handle))
            self.assertEqual([(row['item_code'],row['representative_name']) for row in rows],[
                ('OLD','기존 품목'),('NEW','새 품목'),
            ])
            self.assertEqual(rows[1]['first_source_row'],'3')
            self.assertEqual(rows[1]['alias_count'],'0')


if __name__ == '__main__':
    unittest.main()
