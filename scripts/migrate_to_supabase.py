"""從本機 SQLite 遷移資料到 Supabase PostgreSQL（高速版）

使用 psycopg2.extras.execute_values 真正 multi-row INSERT，
速度比 SQLAlchemy 逐行送快 20-50 倍。

環境變數：
  FORCE_TRUNCATE=1  遇到目標表有資料時自動清空（不互動詢問）
"""
import os
import sys
import io
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parent.parent
SQLITE_PATH = ROOT / "data" / "ulld.db"

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    import tomllib
    with open(ROOT / ".streamlit" / "secrets.toml", "rb") as f:
        secrets = tomllib.load(f)
    DATABASE_URL = secrets["DATABASE_URL"]

if DATABASE_URL.startswith("postgresql://"):
    # psycopg2 接受 postgresql://
    PG_URL = DATABASE_URL
elif DATABASE_URL.startswith("postgres://"):
    PG_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    PG_URL = DATABASE_URL

print(f"SQLite: {SQLITE_PATH}")
print(f"Postgres target: {PG_URL.split('@')[1].split('/')[0]}")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


sqlite_engine = create_engine(f"sqlite:///{SQLITE_PATH}")


def pg_connect():
    conn = psycopg2.connect(PG_URL, connect_timeout=30, keepalives=1,
                            keepalives_idle=30, keepalives_interval=10,
                            keepalives_count=5)
    conn.autocommit = False
    # 放寬 statement_timeout（TRUNCATE 大表會超過預設 8 秒）
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '10min'")
        cur.execute("SET idle_in_transaction_session_timeout = '10min'")
    conn.commit()
    return conn


pg_conn = pg_connect()


def exec_batch_with_retry(sql, rows, page_size, label, max_retries=5):
    """execute_values + 遇到斷線自動重連重試"""
    global pg_conn
    for attempt in range(max_retries):
        try:
            cur = pg_conn.cursor()
            execute_values(cur, sql, rows, page_size=page_size)
            pg_conn.commit()
            cur.close()
            return
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            log(f"  ⚠ {label} 連線中斷（嘗試 {attempt + 1}/{max_retries}）：{str(e)[:80]}")
            try:
                pg_conn.close()
            except Exception:
                pass
            time.sleep(2 ** attempt)
            pg_conn = pg_connect()
    raise RuntimeError(f"{label} 重試 {max_retries} 次仍失敗")

# 檢查目標表
with pg_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM lots")
    lot_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM defects")
    def_cnt = cur.fetchone()[0]
log(f"Supabase 現有：lots={lot_cnt}, defects={def_cnt}")

def drop_and_recreate():
    """DROP 再重建，避開 TRUNCATE 的 statement timeout"""
    global pg_conn
    try:
        pg_conn.rollback()
        pg_conn.close()
    except Exception:
        pass
    tmp = psycopg2.connect(PG_URL, connect_timeout=30)
    tmp.autocommit = True
    with tmp.cursor() as cur:
        cur.execute("SET statement_timeout = 0")
        cur.execute("SHOW statement_timeout")
        log(f"  statement_timeout = {cur.fetchone()[0]}")
        cur.execute("DROP TABLE IF EXISTS defects CASCADE")
        cur.execute("DROP TABLE IF EXISTS lots CASCADE")
        cur.execute("DROP TABLE IF EXISTS import_log CASCADE")
    tmp.close()
    log("  表已 drop，重建 schema 中...")
    sys.path.insert(0, str(ROOT))
    os.environ["DATABASE_URL"] = PG_URL
    import importlib
    import src.db as _db
    importlib.reload(_db)
    _db.init_db()
    log("  schema 重建完成")
    pg_conn = pg_connect()


if lot_cnt > 0 or def_cnt > 0:
    if os.environ.get("FORCE_TRUNCATE") == "1":
        drop_and_recreate()
        log("已清空（FORCE_TRUNCATE=1）")
    else:
        resp = input("Supabase 已有資料，要先清空嗎？(y/N): ").strip().lower()
        if resp == "y":
            drop_and_recreate()
            log("已清空")
        else:
            log("取消遷移")
            sys.exit(0)

# 1. 讀 SQLite lots
log("讀 SQLite lots 全表...")
lots = pd.read_sql_query("SELECT * FROM lots ORDER BY id", sqlite_engine)
log(f"讀到 {len(lots):,} 筆 lots")

LOT_COLS = [
    "日期", "年", "季", "月", "週", "產品類別", "RUNCARD", "製程編號",
    "作業名稱", "產品名稱", "Polarity", "品名", "規格",
    "良品數", "報廢數", "投入量", "不良率", "上傳時間", "來源檔案",
]


def py_val(v):
    if pd.isna(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


# 2. 批量 INSERT lots
log("寫入 Postgres lots（execute_values, batch=2000, 含斷線重試）...")
t0 = time.time()
col_names = ", ".join(f'"{c}"' for c in LOT_COLS)
insert_sql = f"INSERT INTO lots ({col_names}) VALUES %s"

BATCH = 2000
for i in range(0, len(lots), BATCH):
    chunk = lots.iloc[i : i + BATCH]
    rows = [tuple(py_val(r.get(c)) for c in LOT_COLS) for _, r in chunk.iterrows()]
    exec_batch_with_retry(insert_sql, rows, page_size=500, label="lots")
    log(f"  lots 已寫 {min(i + BATCH, len(lots)):,} / {len(lots):,}")

log(f"lots 寫完，耗時 {time.time() - t0:.1f}s")

# 3. 建立 old_id → new_id 對應
log("建立 id 對應表...")
with pg_conn.cursor() as cur:
    cur.execute('SELECT id, "RUNCARD", "製程編號" FROM lots')
    new_id_map = {(str(rc), str(pid)): lid for lid, rc, pid in cur.fetchall()}
log(f"new_id_map: {len(new_id_map):,} 筆")

old_id_to_key = {
    int(r["id"]): (str(r["RUNCARD"]), str(r["製程編號"])) for _, r in lots.iterrows()
}

# 4. 讀 defects
log("讀 SQLite defects...")
defects = pd.read_sql_query("SELECT * FROM defects", sqlite_engine)
log(f"讀到 {len(defects):,} 筆 defects")

log("對應 lot_id...")
defects["_key"] = defects["lot_id"].map(old_id_to_key)
defects["new_lot_id"] = defects["_key"].map(new_id_map)
missing = defects["new_lot_id"].isna().sum()
if missing:
    log(f"  ⚠ 有 {missing} 筆 defects 對應不到 lot，將丟棄")
    defects = defects.dropna(subset=["new_lot_id"])
defects["new_lot_id"] = defects["new_lot_id"].astype(int)

# 5. 批量 INSERT defects
log("寫入 Postgres defects（execute_values, batch=5000, 含斷線重試）...")
t0 = time.time()
defect_sql = (
    'INSERT INTO defects (lot_id, "缺點碼", "缺點中文名", "缺點數") VALUES %s'
)

BATCH_D = 5000
for i in range(0, len(defects), BATCH_D):
    chunk = defects.iloc[i : i + BATCH_D]
    rows = [
        (
            int(r["new_lot_id"]),
            r["缺點碼"],
            r["缺點中文名"],
            int(r["缺點數"]) if not pd.isna(r["缺點數"]) else 0,
        )
        for _, r in chunk.iterrows()
    ]
    exec_batch_with_retry(defect_sql, rows, page_size=1000, label="defects")
    log(f"  defects 已寫 {min(i + BATCH_D, len(defects)):,} / {len(defects):,}")

log(f"defects 寫完，耗時 {time.time() - t0:.1f}s")

# 6. 驗證
with pg_conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM lots")
    pg_lot = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM defects")
    pg_def = cur.fetchone()[0]
log(f"✅ Postgres: lots={pg_lot:,}, defects={pg_def:,}")
log(f"✅ SQLite 原本: lots={len(lots):,}, defects={len(defects):,}")

pg_conn.close()
