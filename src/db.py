"""資料庫層：雙模式支援（SQLite 本機 / PostgreSQL Supabase）

判斷邏輯：
- 若 Streamlit secrets 或環境變數有 DATABASE_URL → 使用 PostgreSQL
- 否則 fallback 到本機 SQLite（data/ulld.db）
"""
import os
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, text

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ulld.db"


def _get_database_url() -> str:
    """優先序：Streamlit secrets → 環境變數 → 本機 SQLite"""
    try:
        import streamlit as st
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DB_PATH}"


DATABASE_URL = _get_database_url()
# postgres:// → postgresql://（SQLAlchemy 要求）
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_POSTGRES = DATABASE_URL.startswith("postgresql")

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        if IS_POSTGRES:
            _engine = create_engine(
                DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5,
            )
        else:
            _engine = create_engine(
                DATABASE_URL, connect_args={"timeout": 30, "check_same_thread": False},
            )
    return _engine


@contextmanager
def get_conn():
    """交易式連線 context manager（commit on success, rollback on error）"""
    with get_engine().begin() as conn:
        yield conn


# ---------- Schema ----------
SCHEMA_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS lots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        日期 TEXT, 年 INTEGER, 季 TEXT, 月 INTEGER, 週 TEXT,
        產品類別 TEXT,
        RUNCARD TEXT NOT NULL, 製程編號 TEXT NOT NULL,
        作業名稱 TEXT, 產品名稱 TEXT, Polarity TEXT,
        品名 TEXT, 規格 TEXT,
        良品數 INTEGER DEFAULT 0, 報廢數 INTEGER DEFAULT 0,
        投入量 INTEGER DEFAULT 0, 不良率 REAL DEFAULT 0.0,
        上傳時間 TEXT, 來源檔案 TEXT,
        UNIQUE(RUNCARD, 製程編號)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_lots_date ON lots(日期)",
    "CREATE INDEX IF NOT EXISTS idx_lots_category ON lots(產品類別)",
    "CREATE INDEX IF NOT EXISTS idx_lots_process ON lots(製程編號)",
    "CREATE INDEX IF NOT EXISTS idx_lots_polarity ON lots(Polarity)",
    "CREATE INDEX IF NOT EXISTS idx_lots_品名 ON lots(品名)",
    "CREATE INDEX IF NOT EXISTS idx_lots_年週 ON lots(年, 週)",
    """
    CREATE TABLE IF NOT EXISTS defects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lot_id INTEGER NOT NULL,
        缺點碼 TEXT NOT NULL, 缺點中文名 TEXT, 缺點數 INTEGER DEFAULT 0,
        FOREIGN KEY (lot_id) REFERENCES lots(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_defects_lot ON defects(lot_id)",
    "CREATE INDEX IF NOT EXISTS idx_defects_code ON defects(缺點碼)",
    """
    CREATE TABLE IF NOT EXISTS import_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        檔名 TEXT, 狀態 TEXT, 訊息 TEXT, 匯入時間 TEXT
    )
    """,
]

SCHEMA_POSTGRES = [
    """
    CREATE TABLE IF NOT EXISTS lots (
        id BIGSERIAL PRIMARY KEY,
        "日期" TEXT, "年" INTEGER, "季" TEXT, "月" INTEGER, "週" TEXT,
        "產品類別" TEXT,
        "RUNCARD" TEXT NOT NULL, "製程編號" TEXT NOT NULL,
        "作業名稱" TEXT, "產品名稱" TEXT, "Polarity" TEXT,
        "品名" TEXT, "規格" TEXT,
        "良品數" INTEGER DEFAULT 0, "報廢數" INTEGER DEFAULT 0,
        "投入量" INTEGER DEFAULT 0, "不良率" DOUBLE PRECISION DEFAULT 0.0,
        "上傳時間" TEXT, "來源檔案" TEXT,
        UNIQUE("RUNCARD", "製程編號")
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_lots_date ON lots("日期")',
    'CREATE INDEX IF NOT EXISTS idx_lots_category ON lots("產品類別")',
    'CREATE INDEX IF NOT EXISTS idx_lots_process ON lots("製程編號")',
    'CREATE INDEX IF NOT EXISTS idx_lots_polarity ON lots("Polarity")',
    'CREATE INDEX IF NOT EXISTS idx_lots_品名 ON lots("品名")',
    'CREATE INDEX IF NOT EXISTS idx_lots_年週 ON lots("年", "週")',
    """
    CREATE TABLE IF NOT EXISTS defects (
        id BIGSERIAL PRIMARY KEY,
        lot_id BIGINT NOT NULL REFERENCES lots(id) ON DELETE CASCADE,
        "缺點碼" TEXT NOT NULL, "缺點中文名" TEXT, "缺點數" INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_defects_lot ON defects(lot_id)",
    'CREATE INDEX IF NOT EXISTS idx_defects_code ON defects("缺點碼")',
    """
    CREATE TABLE IF NOT EXISTS import_log (
        id BIGSERIAL PRIMARY KEY,
        "檔名" TEXT, "狀態" TEXT, "訊息" TEXT, "匯入時間" TEXT
    )
    """,
]


def init_db():
    """初始化資料庫（若不存在則建立）。

    連線自癒：上一輪匯入若把連線弄死（例如長交易被 Supabase 掐斷），
    池裡會殘留壞連線導致這裡丟 OperationalError — dispose 掉整個池重試一次。
    """
    statements = SCHEMA_POSTGRES if IS_POSTGRES else SCHEMA_SQLITE
    try:
        with get_conn() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
    except Exception:
        get_engine().dispose()
        with get_conn() as conn:
            for stmt in statements:
                conn.execute(text(stmt))


LOT_COLS = [
    "日期", "年", "季", "月", "週", "產品類別", "RUNCARD", "製程編號",
    "作業名稱", "產品名稱", "Polarity", "品名", "規格",
    "良品數", "報廢數", "投入量", "不良率", "上傳時間", "來源檔案",
]


def _q(col: str) -> str:
    """欄位名加引號（PostgreSQL 中文欄位一定要雙引號）"""
    return f'"{col}"'


def upsert_lots_and_defects(lots_df: pd.DataFrame, defects_df: pd.DataFrame, source_file: str = ""):
    """批量寫入。存在則覆蓋。回傳 (新增數, 更新數)

    效能關鍵：一定要用「多列 VALUES 一次 INSERT」。原版用 executemany（text() SQL），
    psycopg2 底下=每列一趟網路來回；十萬列 × Streamlit Cloud↔Supabase 延遲=十幾分鐘，
    交易撐太久被掐斷、整頁當掉（2026-07-21 W23~W29 匯入實際炸過）。
    改批次多列後全程 ~160 個 statement，秒級完成。
    覆蓋邏輯用 ON CONFLICT DO UPDATE（PostgreSQL 與 SQLite 3.24+ 語法相同）。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lots_df = lots_df.copy()
    lots_df["上傳時間"] = now
    lots_df["來源檔案"] = source_file
    lots_df["RUNCARD"] = lots_df["RUNCARD"].astype(str)
    lots_df["製程編號"] = lots_df["製程編號"].astype(str)
    # 同一次上傳內同 key 出現多次會讓 ON CONFLICT 報錯（cannot affect row a second time）→ 留最後一筆
    lots_df = lots_df.drop_duplicates(subset=["RUNCARD", "製程編號"], keep="last")

    col_names = ", ".join(_q(c) for c in LOT_COLS)
    non_key_cols = [c for c in LOT_COLS if c not in ("RUNCARD", "製程編號")]
    update_set = ", ".join(f"{_q(c)} = excluded.{_q(c)}" for c in non_key_cols)

    # 先把每列轉成純 Python 值（NaN→None、numpy→原生）
    all_values = []
    for _, row in lots_df.iterrows():
        values = {c: row.get(c) for c in LOT_COLS}
        for k, v in list(values.items()):
            if pd.isna(v):
                values[k] = None
            elif hasattr(v, "item"):
                values[k] = v.item()
        all_values.append(values)

    with get_conn() as conn:
        before_cnt = conn.execute(text("SELECT COUNT(*) FROM lots")).scalar()

        # 1+2. 批次多列 upsert（500 列/句 → 19 欄 × 500 = 9,500 個參數，遠低於上限）
        BATCH_LOTS = 500
        for i in range(0, len(all_values), BATCH_LOTS):
            batch = all_values[i : i + BATCH_LOTS]
            tuples, params = [], {}
            for j, vals in enumerate(batch):
                names = [f"p{j}_{k}" for k in range(len(LOT_COLS))]
                tuples.append("(" + ", ".join(f":{n}" for n in names) + ")")
                for n, c in zip(names, LOT_COLS):
                    params[n] = vals[c]
            conn.execute(
                text(
                    f"INSERT INTO lots ({col_names}) VALUES {', '.join(tuples)} "
                    f'ON CONFLICT ({_q("RUNCARD")}, {_q("製程編號")}) DO UPDATE SET {update_set}'
                ),
                params,
            )

        after_cnt = conn.execute(text("SELECT COUNT(*) FROM lots")).scalar()
        inserted = after_cnt - before_cnt
        updated = len(all_values) - inserted

        # 3. 查全部目標 key 的 id（含剛 insert 的）
        all_keys = list(set(zip(lots_df["RUNCARD"].tolist(), lots_df["製程編號"].tolist())))
        id_map = {}
        BATCH = 500
        for i in range(0, len(all_keys), BATCH):
            batch = all_keys[i : i + BATCH]
            combined = [f"{k[0]}|{k[1]}" for k in batch]
            params = {f"k{j}": v for j, v in enumerate(combined)}
            placeholders = ",".join(f":k{j}" for j in range(len(combined)))
            rows = conn.execute(
                text(
                    f'SELECT id, {_q("RUNCARD")}, {_q("製程編號")} FROM lots '
                    f'WHERE {_q("RUNCARD")} || \'|\' || {_q("製程編號")} IN ({placeholders})'
                ),
                params,
            ).fetchall()
            for r in rows:
                id_map[(r[1], r[2])] = r[0]

        # 4. 刪除這些 lot 的舊缺點
        if id_map:
            lot_ids = list(id_map.values())
            for i in range(0, len(lot_ids), BATCH):
                batch = lot_ids[i : i + BATCH]
                params = {f"i{j}": v for j, v in enumerate(batch)}
                placeholders = ",".join(f":i{j}" for j in range(len(batch)))
                conn.execute(
                    text(f"DELETE FROM defects WHERE lot_id IN ({placeholders})"),
                    params,
                )

        # 5. 批量寫入缺點
        if not defects_df.empty:
            d = defects_df.copy()
            d["RUNCARD"] = d["RUNCARD"].astype(str)
            d["製程編號"] = d["製程編號"].astype(str)
            d = d[pd.to_numeric(d["缺點數"], errors="coerce").fillna(0) > 0]
            d["lot_id"] = list(zip(d["RUNCARD"], d["製程編號"]))
            d["lot_id"] = d["lot_id"].map(id_map)
            d = d.dropna(subset=["lot_id"])
            if not d.empty:
                rows_params = list(zip(
                    d["lot_id"].astype(int).tolist(),
                    d["缺點碼"].tolist(),
                    d["缺點中文名"].tolist(),
                    d["缺點數"].astype(int).tolist(),
                ))
                # 批次多列 INSERT（1000 列/句 × 4 參數；同上，executemany 會逐列來回）
                BATCH_DEF = 1000
                for i in range(0, len(rows_params), BATCH_DEF):
                    batch = rows_params[i : i + BATCH_DEF]
                    tuples, params = [], {}
                    for j, (lid, code, name, qty) in enumerate(batch):
                        tuples.append(f"(:l{j}, :c{j}, :n{j}, :q{j})")
                        params[f"l{j}"] = int(lid)
                        params[f"c{j}"] = code
                        params[f"n{j}"] = name
                        params[f"q{j}"] = int(qty)
                    conn.execute(
                        text(
                            f'INSERT INTO defects (lot_id, {_q("缺點碼")}, {_q("缺點中文名")}, {_q("缺點數")}) '
                            f"VALUES {', '.join(tuples)}"
                        ),
                        params,
                    )

        return inserted, updated


def log_import(檔名: str, 狀態: str, 訊息: str = ""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            text(
                f'INSERT INTO import_log ({_q("檔名")}, {_q("狀態")}, {_q("訊息")}, {_q("匯入時間")}) '
                f"VALUES (:f, :s, :m, :t)"
            ),
            {"f": 檔名, "s": 狀態, "m": 訊息, "t": now},
        )


def _build_where(filters: dict = None, alias: str = ""):
    """回傳 (where_sql, params_dict)。alias 為欄位 prefix，例如 'l.'"""
    if not filters:
        return "", {}
    prefix = alias
    clauses, params = [], {}

    if filters.get("日期_start"):
        clauses.append(f'{prefix}{_q("日期")} >= :日期_start')
        params["日期_start"] = filters["日期_start"]
    if filters.get("日期_end"):
        clauses.append(f'{prefix}{_q("日期")} <= :日期_end')
        params["日期_end"] = filters["日期_end"]

    for field in ["產品類別", "製程編號", "Polarity", "品名"]:
        vals = filters.get(field)
        if vals:
            pnames = [f"{field}_{j}" for j in range(len(vals))]
            placeholders = ",".join(f":{p}" for p in pnames)
            clauses.append(f"{prefix}{_q(field)} IN ({placeholders})")
            for p, v in zip(pnames, vals):
                params[p] = v

    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def fetch_lots(filters: dict = None) -> pd.DataFrame:
    """依篩選條件查詢 lots 表"""
    where_sql, params = _build_where(filters)
    query = f'SELECT * FROM lots WHERE 1=1{where_sql} ORDER BY {_q("日期")} DESC'
    with get_engine().connect() as conn:
        return pd.read_sql_query(text(query), conn, params=params)


def fetch_defects_with_lots(filters: dict = None, defect_codes: list = None) -> pd.DataFrame:
    """查詢缺點明細並 join lots 基本資訊"""
    where_sql, params = _build_where(filters, alias="l.")
    query = f"""
        SELECT l.{_q("日期")}, l.{_q("年")}, l.{_q("季")}, l.{_q("月")}, l.{_q("週")},
               l.{_q("產品類別")}, l.{_q("RUNCARD")}, l.{_q("製程編號")},
               l.{_q("Polarity")}, l.{_q("品名")}, l.{_q("投入量")}, l.{_q("不良率")},
               d.{_q("缺點碼")}, d.{_q("缺點中文名")}, d.{_q("缺點數")}
        FROM defects d
        JOIN lots l ON d.lot_id = l.id
        WHERE 1=1{where_sql}
    """
    if defect_codes:
        pnames = [f"dc_{j}" for j in range(len(defect_codes))]
        placeholders = ",".join(f":{p}" for p in pnames)
        query += f' AND d.{_q("缺點碼")} IN ({placeholders})'
        for p, v in zip(pnames, defect_codes):
            params[p] = v

    with get_engine().connect() as conn:
        return pd.read_sql_query(text(query), conn, params=params)


def get_filter_options() -> dict:
    """取得各篩選欄位的唯一值（給 UI 下拉選單用）"""
    eng = get_engine()
    with eng.connect() as conn:
        q_cat = text(f'SELECT DISTINCT {_q("產品類別")} AS v FROM lots WHERE {_q("產品類別")} IS NOT NULL ORDER BY v')
        q_proc = text(f'SELECT DISTINCT {_q("製程編號")} AS v FROM lots WHERE {_q("製程編號")} IS NOT NULL ORDER BY v')
        q_pol = text(f'SELECT DISTINCT {_q("Polarity")} AS v FROM lots WHERE {_q("Polarity")} IS NOT NULL ORDER BY v')
        q_name = text(f'SELECT DISTINCT {_q("品名")} AS v FROM lots WHERE {_q("品名")} IS NOT NULL ORDER BY v')
        q_defect = text(f'SELECT DISTINCT {_q("缺點碼")} AS code, {_q("缺點中文名")} AS name FROM defects ORDER BY code')
        q_range = text(f'SELECT MIN({_q("日期")}) AS min_date, MAX({_q("日期")}) AS max_date FROM lots')

        return {
            "產品類別": pd.read_sql_query(q_cat, conn)["v"].tolist(),
            "製程編號": pd.read_sql_query(q_proc, conn)["v"].tolist(),
            "Polarity": pd.read_sql_query(q_pol, conn)["v"].tolist(),
            "品名": pd.read_sql_query(q_name, conn)["v"].tolist(),
            "缺點碼": pd.read_sql_query(q_defect, conn).apply(
                lambda r: f"{r['code']} - {r['name']}", axis=1
            ).tolist(),
            "日期範圍": pd.read_sql_query(q_range, conn).iloc[0].to_dict(),
        }


def get_stats() -> dict:
    """首頁 KPI 統計"""
    eng = get_engine()
    with eng.connect() as conn:
        lot_count = pd.read_sql_query(text("SELECT COUNT(*) AS c FROM lots"), conn).iloc[0]["c"]
        defect_count = pd.read_sql_query(text("SELECT COUNT(*) AS c FROM defects"), conn).iloc[0]["c"]
        date_range = pd.read_sql_query(
            text(f'SELECT MIN({_q("日期")}) AS min_date, MAX({_q("日期")}) AS max_date FROM lots'),
            conn,
        ).iloc[0]
        totals = pd.read_sql_query(
            text(
                f'SELECT SUM({_q("投入量")}) AS 投入, '
                f'SUM({_q("良品數")}) AS 良品, '
                f'SUM({_q("報廢數")}) AS 報廢 FROM lots'
            ),
            conn,
        ).iloc[0]
    return {
        "批號數": int(lot_count),
        "缺點記錄數": int(defect_count),
        "資料起日": date_range["min_date"],
        "資料迄日": date_range["max_date"],
        "總投入量": int(totals["投入"] or 0),
        "總良品": int(totals["良品"] or 0),
        "總報廢": int(totals["報廢"] or 0),
    }


if __name__ == "__main__":
    init_db()
    print(f"DB 已初始化（backend={'PostgreSQL' if IS_POSTGRES else 'SQLite'}）")
