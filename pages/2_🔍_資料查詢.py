"""資料查詢頁：完整資料表 + 下載（優化版：懶生成、分頁顯示）"""
import io
import streamlit as st
import pandas as pd
from src.db import init_db, fetch_lots, fetch_defects_with_lots
from src.filters import sidebar_filters
from src.auth import require_view_password

st.set_page_config(page_title="資料查詢 - ULLD", page_icon="🔍", layout="wide")
require_view_password()
init_db()

st.title("🔍 資料查詢與下載")
st.caption("依篩選條件顯示明細，可下載 Excel 或 CSV")

filters = sidebar_filters(default_recent_days=30)
defect_codes = filters.pop("_defect_codes", None)

PREVIEW_ROWS = 1000


@st.cache_data(ttl=120, show_spinner="查詢中...")
def _fetch_lots(filter_key: str, _filters: dict) -> pd.DataFrame:
    return fetch_lots(_filters)


@st.cache_data(ttl=120, show_spinner="查詢中...")
def _fetch_defects(filter_key: str, _filters: dict, codes) -> pd.DataFrame:
    return fetch_defects_with_lots(_filters, defect_codes=list(codes) if codes else None)


filter_key = str(sorted(filters.items())) + str(defect_codes)

tab_lots, tab_defects, tab_wide = st.tabs(["批號明細", "缺點明細", "彙整寬表"])

# ========== Tab 1: 批號明細 ==========
with tab_lots:
    lots = _fetch_lots(filter_key, filters)
    st.info(f"共 **{len(lots):,}** 筆批號資料" +
            (f"（僅顯示前 {PREVIEW_ROWS:,} 筆，下載包含全部）" if len(lots) > PREVIEW_ROWS else ""))
    st.dataframe(
        lots.head(PREVIEW_ROWS) if len(lots) > PREVIEW_ROWS else lots,
        use_container_width=True, hide_index=True,
    )

    if not lots.empty:
        st.subheader("下載完整資料")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("📄 產生 CSV", key="lots_csv_gen"):
                with st.spinner("產生 CSV 中..."):
                    csv = lots.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                st.session_state["lots_csv"] = csv
            if st.session_state.get("lots_csv"):
                st.download_button(
                    "📥 下載 CSV", st.session_state["lots_csv"],
                    "lots.csv", "text/csv", key="lots_csv_dl",
                )

        with col2:
            if st.button("📊 產生 Excel", key="lots_xlsx_gen"):
                with st.spinner("產生 Excel 中（資料量大時約 5-10 秒）..."):
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                        lots.to_excel(writer, index=False, sheet_name="批號明細")
                    st.session_state["lots_xlsx"] = buf.getvalue()
            if st.session_state.get("lots_xlsx"):
                st.download_button(
                    "📥 下載 Excel", st.session_state["lots_xlsx"],
                    "lots.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="lots_xlsx_dl",
                )

# ========== Tab 2: 缺點明細 ==========
with tab_defects:
    defects = _fetch_defects(filter_key, filters, tuple(defect_codes) if defect_codes else None)
    st.info(f"共 **{len(defects):,}** 筆缺點記錄" +
            (f"（僅顯示前 {PREVIEW_ROWS:,} 筆）" if len(defects) > PREVIEW_ROWS else ""))
    st.dataframe(
        defects.head(PREVIEW_ROWS) if len(defects) > PREVIEW_ROWS else defects,
        use_container_width=True, hide_index=True,
    )

    if not defects.empty:
        st.subheader("下載完整資料")
        col1, col2 = st.columns(2)

        with col1:
            if st.button("📄 產生 CSV", key="def_csv_gen"):
                with st.spinner("產生 CSV 中..."):
                    csv = defects.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                st.session_state["def_csv"] = csv
            if st.session_state.get("def_csv"):
                st.download_button(
                    "📥 下載 CSV", st.session_state["def_csv"],
                    "defects.csv", "text/csv", key="def_csv_dl",
                )

        with col2:
            if st.button("📊 產生 Excel", key="def_xlsx_gen"):
                with st.spinner("產生 Excel 中..."):
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                        defects.to_excel(writer, index=False, sheet_name="缺點明細")
                    st.session_state["def_xlsx"] = buf.getvalue()
            if st.session_state.get("def_xlsx"):
                st.download_button(
                    "📥 下載 Excel", st.session_state["def_xlsx"],
                    "defects.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="def_xlsx_dl",
                )

# ========== Tab 3: 彙整寬表 ==========
with tab_wide:
    st.caption("一個批號一列、缺點展開為欄位（類似原本 Excel 格式）。"
               "資料量大時產生較慢，**請縮小篩選範圍**或按下方按鈕再產生。")

    if st.button("🔧 產生彙整寬表"):
        with st.spinner("產生彙整寬表中..."):
            lots = _fetch_lots(filter_key, filters)
            defects = _fetch_defects(filter_key, filters, tuple(defect_codes) if defect_codes else None)

            if lots.empty:
                st.warning("篩選範圍內無資料")
            elif defects.empty:
                st.warning("篩選範圍內無缺點資料")
            else:
                pivot = defects.pivot_table(
                    index=["RUNCARD", "製程編號"], columns="缺點碼",
                    values="缺點數", aggfunc="sum", fill_value=0,
                ).reset_index()
                wide = lots.merge(pivot, on=["RUNCARD", "製程編號"], how="left").fillna(0)
                st.session_state["wide"] = wide

    if "wide" in st.session_state:
        wide = st.session_state["wide"]
        st.success(f"共 {len(wide):,} 列 × {len(wide.columns)} 欄")
        st.dataframe(wide.head(PREVIEW_ROWS), use_container_width=True, hide_index=True)

        if st.button("📊 產生寬表 Excel", key="wide_xlsx_gen"):
            with st.spinner("產生 Excel 中..."):
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                    wide.to_excel(writer, index=False, sheet_name="彙整寬表")
                st.session_state["wide_xlsx"] = buf.getvalue()
        if st.session_state.get("wide_xlsx"):
            st.download_button(
                "📥 下載彙整寬表 Excel", st.session_state["wide_xlsx"],
                "ulld_wide.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="wide_xlsx_dl",
            )
