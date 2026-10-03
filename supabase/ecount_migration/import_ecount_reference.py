from __future__ import annotations

import csv
import getpass
import json
from pathlib import Path

from supabase import create_client

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROJECT_DIR = BASE_DIR.parents[1]
BATCH_SIZE = 300

IMPORTS = (
    ("ecount_item_reference", "ecount_item_reference.csv", "item_code"),
    ("ecount_item_aliases", "ecount_item_aliases.csv", "alias_key"),
    ("ecount_sales_channels", "ecount_sales_channels.csv", "source_name"),
    ("ecount_product_mappings", "ecount_product_mappings.csv", "mapping_key"),
    ("ecount_product_mapping_components", "ecount_product_mapping_components.csv", "mapping_key,sequence"),
    ("ecount_price_rules", "ecount_price_rules.csv", "price_rule_key"),
    ("ecount_price_rule_components", "ecount_price_rule_components.csv", "price_rule_key,sequence"),
    ("ecount_migration_issues", "ecount_migration_issues.csv", "issue_key"),
)

REQUIRED_FIELDS = {
    "ecount_item_reference": ("item_code", "representative_name"),
    "ecount_item_aliases": ("alias_key", "alias_name", "normalized_alias", "item_code"),
    "ecount_sales_channels": ("source_name", "normalized_name", "ecount_customer_code"),
    "ecount_product_mappings": ("mapping_key", "source_channel", "source_product_text", "normalized_source"),
    "ecount_product_mapping_components": ("mapping_key", "sequence", "item_code"),
    "ecount_price_rules": ("price_rule_key", "source_channel", "source_product_name", "normalized_source"),
    "ecount_price_rule_components": ("price_rule_key", "sequence", "component_alias", "normalized_component_alias"),
    "ecount_migration_issues": ("issue_key", "issue_type", "source_sheet"),
}

INTEGER_FIELDS = {
    "alias_count", "first_source_row", "occurrence_count", "source_row",
    "component_count", "sequence",
}
NUMERIC_FIELDS = {
    "quantity", "total_unit_price", "allocated_total", "allocation_variance",
    "allocated_unit_price",
}
BOOLEAN_FIELDS = {"is_active", "resolved"}
JSON_FIELDS = {"details"}
EMPTY_STRING_FIELDS = {"source_options"}


def convert_row(row: dict[str, str]) -> dict:
    converted: dict[str, object] = {}
    for key, value in row.items():
        value = value.strip()
        if value == "" and key in EMPTY_STRING_FIELDS:
            converted[key] = ""
        elif value == "":
            converted[key] = None
        elif key in INTEGER_FIELDS:
            converted[key] = int(value)
        elif key in NUMERIC_FIELDS:
            converted[key] = float(value)
        elif key in BOOLEAN_FIELDS:
            converted[key] = value.lower() in {"true", "1", "yes"}
        elif key in JSON_FIELDS:
            converted[key] = json.loads(value)
        else:
            converted[key] = value
    return converted


def read_csv(filename: str) -> list[dict]:
    with (DATA_DIR / filename).open("r", encoding="utf-8-sig", newline="") as handle:
        return [convert_row(row) for row in csv.DictReader(handle)]


def main() -> None:
    config_path = PROJECT_DIR / "config.json"
    if not config_path.exists():
        raise RuntimeError("REQM/config.json 파일이 없습니다.")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    url = str(config.get("supabase_url", "")).strip()
    key = str(config.get("supabase_publishable_key", "")).strip()
    if not url or not key:
        raise RuntimeError("config.json에 Supabase URL과 publishable/anon 키를 설정하세요.")

    report = json.loads((DATA_DIR / "validation_report.json").read_text(encoding="utf-8"))
    if not report.get("valid"):
        raise RuntimeError("validation_report.json이 실패 상태입니다. 데이터를 먼저 수정하세요.")

    prepared: list[tuple[str, str, list[dict]]] = []
    for table, filename, conflict_columns in IMPORTS:
        rows = read_csv(filename)
        required = REQUIRED_FIELDS[table]
        invalid = [index + 2 for index, row in enumerate(rows) if any(row.get(field) in (None, "") for field in required)]
        if invalid:
            raise RuntimeError(f"{filename} 필수값 누락: CSV 행 {invalid[:10]}")
        prepared.append((table, conflict_columns, rows))

    email = input("Supabase 관리자 이메일: ").strip()
    password = getpass.getpass("Supabase 비밀번호: ")
    client = create_client(url, key)
    client.auth.sign_in_with_password({"email": email, "password": password})

    for table, conflict_columns, rows in prepared:
        for start in range(0, len(rows), BATCH_SIZE):
            client.table(table).upsert(
                rows[start : start + BATCH_SIZE], on_conflict=conflict_columns
            ).execute()
        print(f"{table}: {len(rows):,}건 완료")

    client.auth.sign_out()
    print("Supabase 기준정보 이전이 완료되었습니다.")


if __name__ == "__main__":
    main()
