#!/usr/bin/env python3
"""Supabase keep-alive：對一張 keep_alive 表寫入一筆，避免免費版閒置 7 天被暫停。

- 讀環境變數裡的連線字串（可多個專案），每個各 insert 一筆時間戳 + 修剪舊資料。
- 用「寫入」而非 SELECT 1：寫入是最強的活動訊號，不管 Supabase 內部怎麼算都會觸發。
- 任一專案失敗就以非零碼結束 → GitHub Actions 標記失敗並自動寄信通知（不再靜默失敗）。
"""
import os
import sys

from sqlalchemy import create_engine, text

# 要保活的專案：環境變數名 → 顯示名（GitHub repo secret 用同樣的環境變數名）
PROJECTS = {
    "ULLD_DATABASE_URL": "ulld",
    "ASSET_DATABASE_URL": "asset-mgmt",
}

PING_SQL = text("INSERT INTO keep_alive DEFAULT VALUES")
# 只留最新 5 筆，避免表無限長大
TRIM_SQL = text(
    "DELETE FROM keep_alive "
    "WHERE id NOT IN (SELECT id FROM keep_alive ORDER BY id DESC LIMIT 5)"
)


def ping(url: str) -> None:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.execute(PING_SQL)
            conn.execute(TRIM_SQL)
    finally:
        engine.dispose()


def main() -> int:
    failures = []
    pinged = 0
    for env_name, label in PROJECTS.items():
        url = os.environ.get(env_name)
        if not url:
            print(f"skip {label}: {env_name} 未設定")
            continue
        try:
            ping(url)
            print(f"OK   {label}: keep_alive 寫入成功")
            pinged += 1
        except Exception as e:  # noqa: BLE001 — 任何連線/寫入錯誤都要讓 job 失敗告警
            print(f"FAIL {label}: {e}")
            failures.append(label)

    if pinged == 0 and not failures:
        print("ERROR: 一個 DATABASE_URL secret 都沒設定")
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
