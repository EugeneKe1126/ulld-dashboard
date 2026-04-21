"""資料匯入頁：上傳 Excel，需密碼（觀看密碼 + 上傳密碼 兩層）"""
import tempfile
from pathlib import Path
import streamlit as st
from src.db import init_db, upsert_lots_and_defects, log_import
from src.parser import parse_files
from src.auth import require_view_password, check_upload_password

st.set_page_config(page_title="資料匯入 - ULLD", page_icon="📤", layout="wide")
require_view_password()
init_db()

st.title("📤 資料匯入")
st.caption("上傳每日/每週原始 Excel（月份資料匯出 + 各站不良原因統計表）")

if not check_upload_password():
    st.stop()

st.success("✅ 已登入")
if st.button("🔓 登出"):
    st.session_state.pop("upload_auth", None)
    st.rerun()

st.divider()

st.markdown(
    """
    #### 支援檔案類型
    - **月份/週資料匯出檔**：檔名需含「資料匯出」（.xls / .xlsx / .htm）
    - **各站不良原因統計表**：檔名需含「各站不良原因統計表」（.xls / .xlsx）

    #### 行為
    - 同樣的 RunCard + 製程編號 會**覆蓋**（保留最新資料）
    - 缺點資料會全部重算
    """
)

files = st.file_uploader(
    "拖曳或選擇檔案（可多選）",
    type=["xls", "xlsx", "htm", "html"],
    accept_multiple_files=True,
)

if files:
    st.write(f"已選擇 {len(files)} 個檔案")
    if st.button("🚀 開始匯入", type="primary"):
        with tempfile.TemporaryDirectory() as td:
            saved = []
            for f in files:
                p = Path(td) / f.name
                with open(p, "wb") as out:
                    out.write(f.getbuffer())
                saved.append(str(p))

            with st.status("處理中...", expanded=True) as status:
                st.write("📂 解析 Excel 檔案...")
                lots_df, defects_df, msgs = parse_files(saved)
                for m in msgs:
                    st.write(m)

                if lots_df.empty:
                    status.update(label="❌ 失敗：沒有可匯入的基礎資料", state="error")
                    for f in files:
                        log_import(f.name, "failed", "無基礎資料")
                    st.stop()

                st.write(f"💾 寫入資料庫：lots={len(lots_df)}, defects={len(defects_df)}")
                inserted, updated = upsert_lots_and_defects(
                    lots_df, defects_df, source_file=", ".join(f.name for f in files),
                )

                for f in files:
                    log_import(f.name, "success", f"新增 {inserted} / 更新 {updated}")

                # 清除所有快取，讓儀表板和查詢頁立刻看到新資料
                st.cache_data.clear()

                status.update(label=f"✅ 完成！新增 {inserted} 批、更新 {updated} 批", state="complete")

        st.balloons()
        st.info("💡 儀表板與資料查詢頁的快取已清除，切過去重新整理即可看到新資料")
