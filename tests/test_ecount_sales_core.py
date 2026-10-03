from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from ecount_sales_core import (
    combine_order_sources,
    ReferenceCatalog,
    SmartStoreOrder,
    convert_orders,
    detect_smartstore_order_period,
    read_purchase_confirmed_orders,
    read_smartstore_orders,
    read_smartstore_orders_range,
    write_ecount_workbook,
)


class SalesCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = ReferenceCatalog(
            items=[
                {"item_code": "MAIN", "representative_name": "본품"},
                {"item_code": "OPTION", "representative_name": "옵션품목"},
                {"item_code": "택배운송비", "representative_name": "배송비"},
            ],
            channels=[
                {"source_name": "리큐엠_스마트스토어", "ecount_customer_code": "AC008712", "ecount_customer_name": "샵N", "is_active": True}
            ],
            mappings=[
                {"mapping_key": "set-1", "source_channel": "리큐엠_스마트스토어", "normalized_source": "상품세트옵션핑크", "mapping_type": "set", "review_status": "confirmed", "is_active": True}
            ],
            mapping_components=[
                {"mapping_key": "set-1", "sequence": 1, "item_code": "MAIN", "quantity": 1},
                {"mapping_key": "set-1", "sequence": 2, "item_code": "OPTION", "quantity": 1},
            ],
            price_rules=[
                {"price_rule_key": "price-1", "source_channel": "리큐엠_스마트스토어", "source_product_name": "상품 세트", "source_options": "옵션 핑크", "normalized_source": "상품세트옵션핑크", "total_unit_price": 35400, "review_status": "confirmed", "is_active": True}
            ],
            price_components=[
                {"price_rule_key": "price-1", "sequence": 1, "item_code": "MAIN", "quantity": 1, "allocated_unit_price": 28500},
                {"price_rule_key": "price-1", "sequence": 2, "item_code": "OPTION", "quantity": 1, "allocated_unit_price": 6900},
            ],
        )

    def test_set_discount_is_absorbed_by_main_product(self) -> None:
        order = SmartStoreOrder(
            source_row=2,
            order_no="ORDER-1",
            product_order_no="PRODUCT-1",
            paid_at=datetime(2026, 7, 21, 10, 0),
            status="구매확정",
            product_name="상품 세트",
            options="옵션 핑크",
            quantity=Decimal("1"),
            item_total=Decimal("34900"),
        )
        result = convert_orders([order], self.catalog)
        by_code = {line.item_code: line for line in result.lines}
        self.assertEqual(by_code["MAIN"].unit_price, Decimal("28000.00"))
        self.assertEqual(by_code["OPTION"].unit_price, Decimal("6900.00"))
        self.assertEqual(result.input_total, result.output_total)
        self.assertEqual(result.issues, [])

    def test_export_uses_voucher_date_and_tax_formulas(self) -> None:
        order = SmartStoreOrder(
            source_row=2,
            order_no="ORDER-1",
            product_order_no="PRODUCT-1",
            paid_at=datetime(2026, 7, 21, 10, 0),
            status="구매확정",
            product_name="상품 세트",
            options="옵션 핑크",
            quantity=Decimal("1"),
            item_total=Decimal("34900"),
        )
        result = convert_orders([order], self.catalog)
        result.lines[-1].warehouse = "100"
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "output.xlsx"
            write_ecount_workbook(output, result, date(2026, 7, 22))
            workbook = load_workbook(output, data_only=False)
            sheet = workbook["이카운트 웹입력"]
            self.assertEqual(sheet["A2"].value, 20260722)
            self.assertIsNone(sheet["D2"].value)
            self.assertIsNone(sheet["D3"].value)
            self.assertEqual(sheet["E2"].value, "00109")
            self.assertEqual(sheet["F2"].value, "100")
            self.assertEqual(sheet["F3"].value, "300")
            self.assertEqual(sheet["S2"].value, "=ROUND(Q2/1.1*P2,0)")
            self.assertEqual(sheet["T2"].value, "=Q2*P2-S2")
            workbook.close()

    def test_final_amount_is_preferred_and_shipping_is_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.xlsx"
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "배송현황관리"
            sheet.append([
                "상품주문번호", "주문번호", "상품명", "옵션정보", "수량", "결제일", "주문상태",
                "최종 상품별 총 주문금액", "최초 상품별 총 주문금액", "배송비 묶음번호",
                "배송비 합계", "제주/도서 추가배송비", "배송비 할인액",
            ])
            for product_order_no in ("P1", "P2"):
                sheet.append([
                    product_order_no, "ORDER-1", "상품 세트", "옵션 핑크", 1, "2026-07-21", "구매확정",
                    34900, 35900, "SHIP-1", 6000, 3000, 6000,
                ])
            workbook.save(source)
            workbook.close()

            orders = read_smartstore_orders(source, date(2026, 7, 21))
            self.assertEqual([order.item_total for order in orders], [Decimal("34900.00"), Decimal("34900.00")])
            result = convert_orders(orders, self.catalog)
            shipping_lines = [line for line in result.lines if line.is_shipping]
            self.assertEqual(len(result.shipping_charges), 1)
            self.assertEqual(result.shipping_charges[0].effective_amount, Decimal("6000.00"))
            self.assertTrue(result.shipping_charges[0].is_adjusted)
            self.assertEqual(len(shipping_lines), 1)
            self.assertEqual(shipping_lines[0].quantity, Decimal("1"))
            self.assertEqual(shipping_lines[0].unit_price, Decimal("6000.00"))
            self.assertTrue(result.is_reconciled)

    def test_review_issue_is_included_and_highlighted_in_export(self) -> None:
        order = SmartStoreOrder(
            source_row=2,
            order_no="ORDER-2",
            product_order_no="PRODUCT-2",
            paid_at=datetime(2026, 7, 21, 10, 0),
            status="구매확정",
            product_name="미등록 상품",
            options="",
            quantity=Decimal("1"),
            item_total=Decimal("27800"),
        )
        result = convert_orders([order], self.catalog)
        self.assertEqual(result.amount_difference, Decimal("0.00"))
        self.assertTrue(result.is_reconciled)
        self.assertTrue(result.lines[0].needs_review)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "review.xlsx"
            write_ecount_workbook(output, result, date(2026, 7, 22))
            workbook = load_workbook(output, data_only=False)
            sheet = workbook["이카운트 웹입력"]
            self.assertEqual(sheet["M2"].value, None)
            self.assertTrue(sheet["N2"].value.startswith("[확인필요]"))
            self.assertTrue(sheet["U2"].value.startswith("확인필요:"))
            self.assertEqual(sheet["A2"].fill.fgColor.rgb, "00FFF2CC")
            workbook.close()

    def test_single_item_total_is_split_without_fractional_won_error(self) -> None:
        catalog = ReferenceCatalog(
            items=[{"item_code": "MAIN", "representative_name": "본품"}],
            channels=[
                {"source_name": "리큐엠_스마트스토어", "ecount_customer_code": "AC008712", "ecount_customer_name": "샵N", "is_active": True}
            ],
            mappings=[
                {"mapping_key": "single-1", "source_channel": "리큐엠_스마트스토어", "normalized_source": "단품", "mapping_type": "single", "review_status": "confirmed", "is_active": True}
            ],
            mapping_components=[
                {"mapping_key": "single-1", "sequence": 1, "item_code": "MAIN", "quantity": 1}
            ],
            price_rules=[],
            price_components=[],
        )
        order = SmartStoreOrder(
            source_row=2,
            order_no="ORDER-3",
            product_order_no="PRODUCT-3",
            paid_at=datetime(2026, 7, 23, 10, 0),
            status="구매확정",
            product_name="단품",
            options="",
            quantity=Decimal("7"),
            item_total=Decimal("257800"),
        )
        result = convert_orders([order], catalog)
        self.assertEqual(
            sorted((line.quantity, line.unit_price) for line in result.lines),
            [(Decimal("3"), Decimal("36828.00")), (Decimal("4"), Decimal("36829.00"))],
        )
        self.assertEqual(result.output_total, Decimal("257800.00"))
        self.assertTrue(result.is_reconciled)

    def test_one_component_set_is_converted_with_single_entered_price(self) -> None:
        catalog = ReferenceCatalog(
            items=[{"item_code": "EVENT-ITEM", "representative_name": "행사상품"}],
            channels=[
                {
                    "source_name": "리큐엠_스마트스토어",
                    "ecount_customer_code": "AC008712",
                    "ecount_customer_name": "샵N",
                    "is_active": True,
                }
            ],
            mappings=[
                {
                    "mapping_key": "event-set-1",
                    "source_channel": "리큐엠_스마트스토어",
                    "normalized_source": "공동구매행사상품옵션",
                    "mapping_type": "set",
                    "review_status": "confirmed",
                    "is_active": True,
                }
            ],
            mapping_components=[
                {
                    "mapping_key": "event-set-1",
                    "sequence": 1,
                    "item_code": "EVENT-ITEM",
                    "quantity": 1,
                }
            ],
            price_rules=[
                {
                    "price_rule_key": "event-price-1",
                    "source_channel": "리큐엠_스마트스토어",
                    "source_product_name": "공동구매 행사상품",
                    "source_options": "옵션",
                    "normalized_source": "공동구매행사상품옵션",
                    "total_unit_price": 27800,
                    "review_status": "confirmed",
                    "is_active": True,
                }
            ],
            price_components=[
                {
                    "price_rule_key": "event-price-1",
                    "sequence": 1,
                    "item_code": "EVENT-ITEM",
                    "quantity": 1,
                    "allocated_unit_price": 27800,
                }
            ],
        )
        order = SmartStoreOrder(
            source_row=2,
            order_no="EVENT-O1",
            product_order_no="EVENT-P1",
            paid_at=datetime(2026, 7, 30, 10, 0),
            status="구매확정",
            product_name="공동구매 행사상품",
            options="옵션",
            quantity=Decimal("2"),
            item_total=Decimal("55600"),
        )

        result = convert_orders([order], catalog)

        self.assertEqual(result.issues, [])
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.lines[0].item_code, "EVENT-ITEM")
        self.assertEqual(result.lines[0].quantity, Decimal("2"))
        self.assertEqual(result.lines[0].unit_price, Decimal("27800.00"))
        self.assertTrue(result.is_reconciled)

    def test_order_period_is_detected_and_all_dates_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "period.xlsx"
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "배송현황관리"
            sheet.append([
                "상품주문번호", "주문번호", "상품명", "옵션정보", "수량", "결제일", "주문상태",
                "최종 상품별 총 주문금액", "최초 상품별 총 주문금액",
            ])
            for index, paid_date in enumerate(("2026-07-24", "2026-07-25", "2026-07-26"), start=1):
                sheet.append([
                    f"P{index}", f"O{index}", "상품 세트", "옵션 핑크", 1, paid_date, "구매확정",
                    34900, 34900,
                ])
            workbook.save(source)
            workbook.close()

            self.assertEqual(
                detect_smartstore_order_period(source),
                (date(2026, 7, 24), date(2026, 7, 26)),
            )
            orders = read_smartstore_orders_range(
                source,
                date(2026, 7, 24),
                date(2026, 7, 26),
            )
            self.assertEqual(len(orders), 3)
            self.assertEqual(sum(order.item_total for order in orders), Decimal("104700.00"))

    def test_purchase_confirmed_amount_and_shipping_are_added(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "confirmed.xlsx"
            from openpyxl import Workbook

            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "구매확정내역"
            sheet.append([
                "상품주문번호", "주문번호", "구매확정일", "주문상태", "상품명", "옵션정보", "수량",
                "최초 상품별 총 주문금액", "배송비 묶음번호", "배송비 합계",
            ])
            sheet.append([
                "CONFIRMED-P1", "CONFIRMED-O1", "2026-07-27", "구매확정", "상품 세트", "옵션 핑크", 2,
                69800, "CONFIRMED-SHIP", 3000,
            ])
            workbook.save(source)
            workbook.close()

            confirmed = read_purchase_confirmed_orders(source)
            self.assertEqual(len(confirmed), 1)
            self.assertEqual(confirmed[0].source_type, "구매확정")
            self.assertEqual(confirmed[0].item_total, Decimal("69800.00"))
            self.assertTrue(confirmed[0].include_shipping)
            self.assertEqual(confirmed[0].shipping_total, Decimal("3000.00"))

            result = convert_orders(confirmed, self.catalog)
            self.assertEqual(result.confirmed_order_count, 1)
            self.assertEqual(result.confirmed_item_total, Decimal("69800.00"))
            self.assertEqual(result.shipping_total, Decimal("3000.00"))
            self.assertEqual(result.output_total, Decimal("72800.00"))
            self.assertTrue(result.is_reconciled)

    def test_duplicate_product_order_between_files_is_rejected(self) -> None:
        original = SmartStoreOrder(
            source_row=2,
            order_no="O1",
            product_order_no="P1",
            paid_at=datetime(2026, 7, 24),
            status="배송완료",
            product_name="상품 세트",
            options="옵션 핑크",
            quantity=Decimal("1"),
            item_total=Decimal("34900"),
        )
        confirmed = SmartStoreOrder(
            source_row=2,
            order_no="O1",
            product_order_no="P1",
            paid_at=datetime(2026, 7, 27),
            status="구매확정",
            product_name="상품 세트",
            options="옵션 핑크",
            quantity=Decimal("1"),
            item_total=Decimal("34900"),
            source_type="구매확정",
            include_shipping=False,
        )
        with self.assertRaisesRegex(ValueError, "금액 이중계상"):
            combine_order_sources([original], [confirmed])


if __name__ == "__main__":
    unittest.main()
