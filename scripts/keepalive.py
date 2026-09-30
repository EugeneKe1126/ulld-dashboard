#!/usr/bin/env python3
"""Supabase keep-alive：對每個專案的 keep_alive 表寫入一筆，避免免費版閒置 7 天被暫停。

兩種接法（每個專案擇一，看 secret 有設哪組）：
  A. Postgres 連線字串：<NAME>_DATABASE_URL           → SQLAlchemy INSERT（ULLD 用這個）
  B. Supabase REST + service key：<NAME>_SUPABASE_URL + <NAME>_SUPABASE_SERVICE_KEY
     → PostgREST POST /rest/v1/keep_alive（asset-mgmt 用這個，不需要 DB 密碼）

- 用「寫入」而非 SELECT 1：寫入是最強的活動訊號。
- 任一專案失敗就以非零碼結束 → GitHub Actions 標記失敗並自動寄信通知。
- keep_alive 表要先在各專案 SQL Editor 建好（scripts/keep_alive_setup.sql）。
"""
import os
import sys

for _s in (sys.stdout, sys.stderr):   # Windows 主控台 cp950/cp1252 印中文會炸
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# 顯示名 → (Postgres 連線字串 env, (REST URL env, service key env))
PROJECTS = {
    "ulld": ("ULLD_DATABASE_URL", ("ULLD_SUPABASE_URL", "ULLD_SUPABASE_SERVICE_KEY")),
    "asset-mgmt": ("ASSET_DATABASE_URL", ("ASSET_MGMT_SUPABASE_URL", "ASSET_MGMT_SUPABASE_SERVICE_KEY")),
}
KEEP_ROWS = 5
TIMEOUT = 20


def ping_sql(url: str) -> None:
    from sqlalchemy import create_engine, text

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):   # 明確用 psycopg2；SQLAlchemy 2.1 預設改 psycopg 3
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO keep_alive DEFAULT VALUES"))
            conn.execute(text(
                f"DELETE FROM keep_alive WHERE id NOT IN "
                f"(SELECT id FROM keep_alive ORDER BY id DESC LIMIT {KEEP_ROWS})"))
    finally:
        engine.dispose()


def ping_rest(base_url: str, service_key: str) -> None:
    import requests

    base = base_url.rstrip("/") + "/rest/v1/keep_alive"
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}",
               "Content-Type": "application/json"}
    r = requests.post(base, headers={**headers, "Prefer": "return=minimal"}, json={}, timeout=TIMEOUT)
    if r.status_code == 404:
        raise RuntimeError("keep_alive 表不存在，請在該專案的 SQL Editor 跑 scripts/keep_alive_setup.sql")
    if r.status_code >= 300:
        raise RuntimeError(f"insert HTTP {r.status_code}: {r.text[:200]}")
    # 修剪：留最新 KEEP_ROWS 筆
    r = requests.get(f"{base}?select=id&order=id.desc&limit={KEEP_ROWS}", headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    ids = [row["id"] for row in r.json()]
    if len(ids) == KEEP_ROWS:
        r = requests.delete(f"{base}?id=lt.{min(ids)}", headers={**headers, "Prefer": "return=minimal"}, timeout=TIMEOUT)
        if r.status_code >= 300:
            raise RuntimeError(f"trim HTTP {r.status_code}: {r.text[:200]}")


def main() -> int:
    failures, pinged = [], 0
    for label, (sql_env, (url_env, key_env)) in PROJECTS.items():
        sql_url = os.environ.get(sql_env, "").strip()
        rest_url, rest_key = os.environ.get(url_env, "").strip(), os.environ.get(key_env, "").strip()
        try:
            if sql_url:
                ping_sql(sql_url)
                print(f"OK   {label}: keep_alive 寫入成功（Postgres）")
            elif rest_url and rest_key:
                ping_rest(rest_url, rest_key)
                print(f"OK   {label}: keep_alive 寫入成功（REST）")
            else:
                print(f"skip {label}: 沒設 {sql_env} 也沒設 {url_env}/{key_env}")
                continue
            pinged += 1
        except Exception as e:  # noqa: BLE001 — 任何錯誤都要讓 job 失敗告警
            print(f"FAIL {label}: {e}")
            failures.append(label)

    if pinged == 0 and not failures:
        print("ERROR: 一個專案的 secret 都沒設定")
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
