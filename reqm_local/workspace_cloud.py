from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path


WORKSPACE_KEY = "default"
SCHEMA_VERSION = 3
TABLE_ORDER = (
    "orders", "mappings", "event_rules", "requests", "request_lines",
    "shipments", "smartstore_erp_rows", "esm_erp_rows", "fees", "artifacts", "events",
)
DELETE_ORDER = tuple(reversed(TABLE_ORDER))


class WorkspaceConflict(RuntimeError):
    pass


def _encode_value(value):
    if isinstance(value, bytes):
        return {"__reqm_bytes__": base64.b64encode(value).decode("ascii")}
    return value


def _decode_value(value):
    if isinstance(value, dict) and set(value) == {"__reqm_bytes__"}:
        return base64.b64decode(value["__reqm_bytes__"])
    return value


def export_workspace(service) -> dict:
    tables = {}
    for table in TABLE_ORDER:
        rows = []
        for row in service.db.execute(f'SELECT * FROM "{table}"'):
            rows.append({key:_encode_value(row[key]) for key in row.keys()})
        tables[table] = rows
    settings = {key:value for key,value in service.settings.items() if key != "cloud_email"}
    return {"schema_version":SCHEMA_VERSION,"tables":tables,"settings":settings}


def workspace_digest(state: dict) -> str:
    payload = json.dumps(state,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_workspace(service, state: dict) -> None:
    if int(state.get("schema_version",0)) not in (1, 2, SCHEMA_VERSION):
        raise RuntimeError("지원하지 않는 공유 DB 형식입니다.")
    tables = state.get("tables") or {}
    with service.db:
        for table in DELETE_ORDER:
            service.db.execute(f'DELETE FROM "{table}"')
        for table in TABLE_ORDER:
            columns = [row["name"] for row in service.db.execute(f'PRAGMA table_info("{table}")')]
            for source in tables.get(table,[]):
                values = [_decode_value(source.get(column)) for column in columns]
                marks = ",".join("?" for _ in columns)
                names = ",".join(f'"{column}"' for column in columns)
                service.db.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})',values)
    local_email = service.settings.get("cloud_email","")
    remote_settings = dict(state.get("settings") or {})
    remote_settings["cloud_email"] = local_email
    service.settings = remote_settings
    path = service.folder / "settings.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(service.settings,ensure_ascii=False,indent=2),encoding="utf-8")
    os.replace(temporary,path)


class CloudWorkspace:
    def __init__(self, client, service, workspace_key: str = WORKSPACE_KEY):
        self.client = client
        self.service = service
        self.workspace_key = workspace_key
        self.version = 0
        self.last_digest = ""

    def fetch(self):
        rows = (
            self.client.table("reqm_workspace_state")
            .select("workspace_key,version,state,updated_at")
            .eq("workspace_key",self.workspace_key)
            .limit(1).execute().data or []
        )
        return rows[0] if rows else None

    def bootstrap(self) -> str:
        row = self.fetch()
        if row:
            import_workspace(self.service,row["state"])
            self.version = int(row["version"])
            self.last_digest = workspace_digest(row["state"])
            return "downloaded"
        self.version = 0
        self.last_digest = ""
        self.push_if_changed()
        return "uploaded"

    def pull_if_newer(self) -> bool:
        row = self.fetch()
        return self.apply_if_newer(row)

    def apply_if_newer(self, row) -> bool:
        if not row or int(row["version"]) <= self.version:
            return False
        current = export_workspace(self.service)
        if self.last_digest and workspace_digest(current) != self.last_digest:
            raise WorkspaceConflict("이 PC에 아직 공유되지 않은 변경이 있어 최신 DB를 자동 적용할 수 없습니다.")
        import_workspace(self.service,row["state"])
        self.version = int(row["version"])
        self.last_digest = workspace_digest(row["state"])
        return True

    def push_if_changed(self) -> bool:
        state = export_workspace(self.service)
        digest = workspace_digest(state)
        if digest == self.last_digest:
            return False
        try:
            result = self.client.rpc("reqm_save_workspace_state",{
                "p_workspace_key":self.workspace_key,
                "p_expected_version":self.version,
                "p_state":state,
            }).execute().data or []
        except Exception as exc:
            if "REQM_VERSION_CONFLICT" in str(exc) or "40001" in str(exc):
                raise WorkspaceConflict("다른 PC가 먼저 저장했습니다. 최신 데이터를 반영한 뒤 다시 시도하세요.") from exc
            raise
        if not result:
            raise RuntimeError("공유 DB 저장 결과를 받지 못했습니다.")
        row = result[0] if isinstance(result,list) else result
        self.version = int(row["new_version"])
        self.last_digest = digest
        return True

    def snapshot(self) -> dict:
        return export_workspace(self.service)

    def restore(self, state: dict) -> None:
        import_workspace(self.service,state)
