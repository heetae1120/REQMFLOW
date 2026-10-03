from __future__ import annotations

import csv
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"


def load(name: str) -> list[dict[str, str]]:
    with (DATA_DIR / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def assert_unique(rows: list[dict[str, str]], *fields: str) -> None:
    keys = [tuple(row[field] for field in fields) for row in rows]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    assert not duplicates, f"중복 키 {fields}: {duplicates[:5]}"


def assert_required(rows: list[dict[str, str]], *fields: str) -> None:
    missing = [index + 2 for index, row in enumerate(rows) if any(not row[field].strip() for field in fields)]
    assert not missing, f"필수값 누락 {fields}: CSV 행 {missing[:10]}"


def main() -> None:
    items = load("ecount_item_reference.csv")
    aliases = load("ecount_item_aliases.csv")
    channels = load("ecount_sales_channels.csv")
    mappings = load("ecount_product_mappings.csv")
    mapping_components = load("ecount_product_mapping_components.csv")
    price_rules = load("ecount_price_rules.csv")
    price_components = load("ecount_price_rule_components.csv")
    issues = load("ecount_migration_issues.csv")

    assert_unique(items, "item_code")
    assert_unique(aliases, "alias_key")
    assert_unique(aliases, "normalized_alias", "item_code")
    assert_unique(channels, "source_name")
    assert_unique(mappings, "mapping_key")
    assert_unique(mapping_components, "mapping_key", "sequence")
    assert_unique(price_rules, "price_rule_key")
    assert_unique(price_components, "price_rule_key", "sequence")
    assert_unique(issues, "issue_key")

    assert_required(items, "item_code", "representative_name")
    assert_required(aliases, "alias_key", "alias_name", "normalized_alias", "item_code")
    assert_required(channels, "source_name", "normalized_name", "ecount_customer_code")
    assert_required(mappings, "mapping_key", "source_channel", "source_product_text", "normalized_source")
    assert_required(price_rules, "price_rule_key", "source_channel", "source_product_name", "normalized_source")

    item_codes = {row["item_code"] for row in items}
    mapping_keys = {row["mapping_key"] for row in mappings}
    price_rule_keys = {row["price_rule_key"] for row in price_rules}
    assert all(row["item_code"] in item_codes for row in aliases)
    assert all(row["mapping_key"] in mapping_keys for row in mapping_components)
    assert all(row["item_code"] in item_codes for row in mapping_components)
    assert all(row["price_rule_key"] in price_rule_keys for row in price_components)
    assert all(not row["item_code"] or row["item_code"] in item_codes for row in price_components)

    mapping_counts = Counter(row["mapping_key"] for row in mapping_components)
    assert all(mapping_counts[row["mapping_key"]] == int(row["component_count"]) for row in mappings)

    component_totals: dict[str, Decimal] = defaultdict(Decimal)
    component_counts = Counter()
    for row in price_components:
        component_totals[row["price_rule_key"]] += Decimal(row["allocated_unit_price"])
        component_counts[row["price_rule_key"]] += 1
    for row in price_rules:
        key = row["price_rule_key"]
        assert component_counts[key] == int(row["component_count"])
        assert component_totals[key] == Decimal(row["allocated_total"])
        assert component_totals[key] - Decimal(row["total_unit_price"]) == Decimal(row["allocation_variance"])

    print("검증 완료")
    print(f"품목코드 {len(items):,}건 / 별칭 {len(aliases):,}건 / 판매처 {len(channels):,}건")
    print(f"상품 매핑 {len(mappings):,}건 / 구성품 {len(mapping_components):,}건")
    print(f"가격 규칙 {len(price_rules):,}건 / 가격 구성품 {len(price_components):,}건")
    print(f"검수 항목 {len(issues):,}건")


if __name__ == "__main__":
    main()
