"""Active Shipping item snapshot; legacy ERP reference rows are history only."""
import json
from pathlib import Path


def load_active_items(reference_dir):
    path = Path(reference_dir) / 'shipping_items.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('source_table') != 'items' or not isinstance(payload.get('items'), list):
        raise ValueError('출고 품목 기준파일 형식을 확인하세요.')
    result = {}
    seen = set()
    for row in payload['items']:
        code = str(row.get('item_code') or '').strip()
        name = str(row.get('standard_name') or '').strip()
        if not code or not name or type(row.get('is_active')) is not bool or code.casefold() in seen:
            raise ValueError('출고 품목 기준파일에 누락 또는 중복 품목이 있습니다.')
        seen.add(code.casefold())
        if row['is_active']:
            result[code] = name
    if not result:
        raise ValueError('사용 중인 출고 품목이 없습니다.')
    return result
