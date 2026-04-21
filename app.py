"""ULLD 資料庫儀表板 - 入口頁"""
import streamlit as st
from src.db import init_db, get_stats
from src.auth import require_view_password

st.set_page_config(
    page_title="ULLD 資料庫儀表板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

require_view_password()
init_db()

st.title("📊 ULLD 資料庫儀表板")
st.caption("Eugene's LifeOS · 產線資料即時分析")

st.markdown(
    """
    ### 👋 歡迎使用

    左側選單可進入：
    - **📊 儀表板**：良率趨勢、缺點柏拉圖、站別比較、熱力圖
    - **🔍 資料查詢**：多條件篩選 + 下載 Excel/CSV
    - **📤 資料匯入**：上傳每日原始資料（需密碼）
    """
)

st.divider()

stats = get_stats()
if stats["批號數"] == 0:
    st.info("🚀 資料庫尚無資料，請至「📤 資料匯入」頁上傳第一批檔案。")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("批號總數", f"{stats['批號數']:,}")
    c2.metric("缺點記錄數", f"{stats['缺點記錄數']:,}")
    c3.metric("總投入量", f"{stats['總投入量']:,}")
    overall_yield = (stats["總良品"] / stats["總投入量"] * 100) if stats["總投入量"] else 0
    c4.metric("整體良率", f"{overall_yield:.3f}%")

    st.caption(
        f"資料涵蓋：{stats['資料起日']} ~ {stats['資料迄日']}　｜　"
        f"總良品 {stats['總良品']:,}　｜　總報廢 {stats['總報廢']:,}"
    )
