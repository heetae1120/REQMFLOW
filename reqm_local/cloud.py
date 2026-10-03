from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from ecount_sales_core import ReferenceCatalog
from .shipping import ShippingCatalog


TABLE_SPECS = (
    ("ecount_item_reference", ("item_code",)),
    ("ecount_sales_channels", ("source_name",)),
    ("ecount_product_mappings", ("mapping_key",)),
    ("ecount_product_mapping_components", ("mapping_key", "sequence")),
    ("ecount_price_rules", ("price_rule_key",)),
    ("ecount_price_rule_components", ("price_rule_key", "sequence")),
)

SHIPPING_TABLES = (
    "items",
    "registered_products",
    "product_components",
    "item_aliases",
    "item_barcodes",
    "wekeep_sku_mappings",
)


def config_candidates() -> list[Path]:
    source_root = Path(__file__).resolve().parent.parent
    candidates = [source_root / "config.json", Path.cwd() / "config.json"]
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve().parent
        candidates[:0] = [executable / "config.json", executable.parent / "config.json"]
    return list(dict.fromkeys(candidates))


def load_cloud_config() -> dict[str, str]:
    for path in config_candidates():
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    return {}


def _fetch_all(client, table_name: str) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = client.table(table_name).select("*").range(start, start + 999).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def _read_local(reference_dir: Path, table_name: str) -> list[dict]:
    with (reference_dir / f"{table_name}.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _merge(local_rows: list[dict], remote_rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    merged: dict[tuple[str, ...], dict] = {}
    for row in [*local_rows, *remote_rows]:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        if any(key):
            merged[key] = row
    return list(merged.values())


def load_catalog(client, reference_dir: str | Path):
    """Load and merge reference data after a client has authenticated."""
    reference_dir = Path(reference_dir)
    merged_tables: list[list[dict]] = []
    remote_counts: dict[str, int] = {}
    for table_name, key_fields in TABLE_SPECS:
        remote = _fetch_all(client, table_name)
        remote_counts[table_name] = len(remote)
        merged_tables.append(_merge(_read_local(reference_dir, table_name), remote, key_fields))
    catalog = ReferenceCatalog(*merged_tables)
    shipping_rows: dict[str, list[dict]] = {}
    shipping_errors: list[str] = []
    for table_name in SHIPPING_TABLES:
        try:
            shipping_rows[table_name] = _fetch_all(client, table_name)
        except Exception:
            # FLOW's existing sales/ERP login must remain usable when the shipping
            # schema has not yet been granted to an account.  In that case no
            # shipping auto-match is permitted.
            shipping_rows[table_name] = []
            shipping_errors.append(table_name)
        remote_counts[table_name] = len(shipping_rows[table_name])
    catalog.shipping_catalog = ShippingCatalog(
        shipping_rows["items"],
        shipping_rows["registered_products"],
        shipping_rows["product_components"],
        shipping_rows["item_aliases"],
        shipping_rows["item_barcodes"],
        shipping_rows["wekeep_sku_mappings"],
        shipping_errors,
    )
    return catalog, remote_counts


def login_and_load(email: str, password: str, reference_dir: str | Path):
    """Authenticate and return a client plus a local/remote merged reference catalog."""
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError("Supabase 기능이 설치되지 않았습니다. requirements-local.txt를 다시 설치하세요.") from exc

    config = load_cloud_config()
    url = str(config.get("supabase_url", "")).strip()
    key = str(config.get("supabase_publishable_key", "")).strip()
    if not url or not key:
        raise RuntimeError("config.json에 Supabase URL과 publishable key가 필요합니다.")
    if not email.strip() or not password:
        raise RuntimeError("이메일과 비밀번호를 입력하세요.")

    client = create_client(url, key)
    try:
        response = client.auth.sign_in_with_password({"email": email.strip(), "password": password})
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "invalid login credentials" in lowered or "invalid_credentials" in lowered:
            raise RuntimeError(
                "이메일 또는 비밀번호가 맞지 않습니다. Supabase 대시보드 팀원 계정이 아니라 "
                "이 프로젝트의 Authentication > Users에 등록된 사용자로 로그인하세요."
            ) from exc
        if "email not confirmed" in lowered or "email_not_confirmed" in lowered:
            raise RuntimeError(
                "이메일 인증이 완료되지 않았습니다. 받은 인증 메일을 확인하거나 "
                "Supabase Authentication > Users에서 사용자를 인증 처리하세요."
            ) from exc
        raise RuntimeError(f"Supabase Auth 로그인 오류: {message}") from exc
    if not response.session:
        raise RuntimeError("로그인 세션을 받지 못했습니다.")

    catalog, remote_counts = load_catalog(client, reference_dir)
    return client, catalog, remote_counts
