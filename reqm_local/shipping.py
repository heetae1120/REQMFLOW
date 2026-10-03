from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Iterable


def compact(value: Any) -> str:
    """Match the shipping program's stable product/option normalization."""
    text = str(value or "").casefold()
    text = re.sub(r"[\[\](){}:,_/\\+\-]", " ", text)
    return re.sub(r"[^0-9a-z가-힣]", "", " ".join(text.split()))


def channel_key(value):
    key=compact(str(value or '').removeprefix('리큐엠_'))
    aliases = {
        '삼성복지몰':'삼성카드복지몰',
        '삼성카드주식회사복지몰':'삼성카드복지몰',
        '삼성쇼핑몰':'삼성카드쇼핑몰',
        '삼성카드주식회사쇼핑몰':'삼성카드쇼핑몰',
        '삼성물산주패션부문':'ssf',
        '교보문고핫트랙스':'교보문고',
        '주식회사현대이지웰':'이지웰',
        '주이제너두':'이제너두',
        '주한섬':'한섬eql',
        '한섬':'한섬eql',
        '더블유컨셉코리아':'w컨셉',
        '주식회사무신사':'무신사',
        '마켓컬리주식회사컬리':'마켓컬리',
        '주현대홈쇼핑':'현대홈쇼핑',
        '현대홈쇼핑신':'현대홈쇼핑',
    }
    return aliases.get(key,key)


def _active(row: dict[str, Any]) -> bool:
    value = row.get("is_active", True)
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _component_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [dict(row) for row in (value or []) if isinstance(row, dict)]


class ShippingCatalog:
    """Read-only, exact-match view of the proven REQM shipping catalog.

    Fuzzy or keyword matches are intentionally excluded.  FLOW may suggest those
    separately in the future, but they must never make an order exportable.
    """

    def __init__(
        self,
        items: Iterable[dict[str, Any]] = (),
        products: Iterable[dict[str, Any]] = (),
        components: Iterable[dict[str, Any]] = (),
        aliases: Iterable[dict[str, Any]] = (),
        barcodes: Iterable[dict[str, Any]] = (),
        sku_mappings: Iterable[dict[str, Any]] = (),
        load_errors: Iterable[str] = (),
    ) -> None:
        self.load_errors = tuple(load_errors)
        self.items = {
            str(row.get("item_code") or "").strip().casefold(): dict(row)
            for row in items
            if _active(row) and str(row.get("item_code") or "").strip()
        }
        self.skus = {
            str(row.get("item_code") or "").strip().casefold(): dict(row)
            for row in sku_mappings
            if _active(row)
            and str(row.get("item_code") or "").strip()
            and str(row.get("sku_no") or "").strip()
        }
        self.barcode_codes = {
            str(row.get("barcode") or "").strip().casefold(): str(row.get("item_code") or "").strip()
            for row in barcodes
            if _active(row) and row.get("barcode") and row.get("item_code")
        }

        self.aliases: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in aliases:
            if not _active(row):
                continue
            stored = compact(row.get('normalized_source'))
            canonical = compact(' '.join(filter(None,[row.get('source_product_name'),row.get('source_options')])))
            for source_key in {stored, canonical} - {''}:
                key = (channel_key(row.get("source_channel")), source_key)
                self.aliases[key].append(dict(row))

        components_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in components:
            product_id = str(row.get("registered_product_id") or "")
            if product_id:
                components_by_product[product_id].append(dict(row))
        self.products: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in products:
            if not _active(row):
                continue
            key = compact(row.get("normalized_name") or row.get("original_name"))
            if not key:
                continue
            product = dict(row)
            product_id = str(product.get("registered_product_id") or product.get("id") or "")
            product["components"] = sorted(
                components_by_product.get(product_id, []),
                key=lambda component: int(component.get("sequence") or 0),
            )
            self.products[key].append(product)

    @property
    def available(self) -> bool:
        return not self.load_errors and bool(self.items and self.skus)

    @property
    def blocking_reason(self) -> str:
        if self.load_errors:
            return "출고 DB를 모두 읽지 못했습니다: " + ", ".join(self.load_errors)
        if not self.items:
            return "출고 DB의 활성 품목이 없습니다."
        if not self.skus:
            return "출고 DB의 활성 위킵 SKU가 없습니다."
        return ""

    def sku_for(self, item_code: str) -> dict[str, Any] | None:
        return self.skus.get(str(item_code or "").strip().casefold())

    def _validate_components(self, rows: Iterable[dict[str, Any]], method: str) -> dict[str, Any]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            item_code = str(row.get("item_code") or "").strip()
            key = item_code.casefold()
            if not item_code:
                return {"state": "blocked", "reason": f"{method}: 내부 품목코드가 비어 있습니다."}
            if key in seen:
                continue
            seen.add(key)
            item = self.items.get(key)
            if not item:
                return {"state": "blocked", "reason": f"{method}: 등록되지 않은 내부 품목코드 {item_code}"}
            sku = self.skus.get(key)
            if not sku:
                return {"state": "blocked", "reason": f"{method}: 위킵 SKU 미등록 {item_code}"}
            result.append(
                {
                    "item_code": item_code,
                    "standard_name": str(item.get("standard_name") or "").strip(),
                    "wekeep_manage_code": str(sku.get("wekeep_manage_code") or item_code).strip(),
                    "wekeep_product_name": str(sku.get("product_name") or item.get("standard_name") or "").strip(),
                    "sku_no": str(sku.get("sku_no") or "").strip(),
                    "customer_barcode": str(sku.get("customer_barcode") or "").strip(),
                }
            )
        if not result:
            return {"state": "blocked", "reason": f"{method}: 연결된 구성품이 없습니다."}
        return {"state": "ready", "method": method, "components": result}

    def resolve(self, order: dict[str, Any]) -> dict[str, Any]:
        """Resolve only deterministic codes, barcodes, aliases, or exact products."""
        source_code = str(order.get("source_item_code") or "").strip()
        if source_code:
            item_code = source_code if source_code.casefold() in self.items else self.barcode_codes.get(source_code.casefold(), "")
            if item_code:
                return self._validate_components([{"item_code": item_code}], "판매처 코드/바코드 정확 일치")

        source = " ".join(filter(None, [str(order.get("product") or ""), str(order.get("option") or "")]))
        alias_key = compact(source)
        channel = channel_key(order.get("channel"))
        candidates = self.aliases.get((channel, alias_key), []) or self.aliases.get(("", alias_key), [])
        if len(candidates) > 1:
            return {"state": "blocked", "reason": "판매처 별칭이 여러 품목을 가리킵니다. 자동 출고를 중단합니다."}
        if len(candidates) == 1:
            return self._validate_components(_component_rows(candidates[0].get("components")), "판매처별 저장 별칭")

        products = self.products.get(alias_key, [])
        if len(products) > 1:
            return {"state": "blocked", "reason": "동일한 등록상품명이 여러 개입니다. 자동 출고를 중단합니다."}
        if len(products) == 1:
            return self._validate_components(products[0].get("components") or [], "등록상품명 정확 일치")
        return {"state": "no_match", "reason": "출고 DB의 확정 매칭에 없습니다."}
