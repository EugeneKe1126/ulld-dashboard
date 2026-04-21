"""儀表板頁：KPI + 六張互動圖"""
import streamlit as st
import pandas as pd
from src.db import init_db, fetch_lots, fetch_defects_with_lots
from src.filters import sidebar_filters
from src.auth import require_view_password
from src.charts import (
    yield_trend, defect_pareto, station_yield_compare,
    defect_heatmap, category_compare, polarity_distribution,
)

st.set_page_config(page_title="儀表板 - ULLD", page_icon="📊", layout="wide")
require_view_password()
init_db()

st.title("📊 儀表板")
st.caption("依左側篩選條件動態更新（預設最近 30 天，可在左側調整）")


@st.cache_data(ttl=120, show_spinner="查詢資料中...")
def _cached_lots(filter_key: str, _filters: dict) -> pd.DataFrame:
    return fetch_lots(_filters)


@st.cache_data(ttl=120, show_spinner="查詢缺點中...")
def _cached_defects(filter_key: str, _filters: dict, codes) -> pd.DataFrame:
    return fetch_defects_with_lots(_filters, defect_codes=list(codes) if codes else None)


filters = sidebar_filters(default_recent_days=30)
defect_codes = filters.pop("_defect_codes", None)

filter_key = str(sorted(filters.items())) + str(defect_codes)
lots = _cached_lots(filter_key, filters)
defects = _cached_defects(filter_key, filters, tuple(defect_codes) if defect_codes else None)

if lots.empty:
    st.warning("目前篩選條件下沒有資料")
    st.stop()

# --- KPI 卡片 ---
total_input = int(lots["投入量"].sum())
total_good = int(lots["良品數"].sum())
total_scrap = int(lots["報廢數"].sum())
overall_yield = (total_good / total_input * 100) if total_input else 0
overall_defect = (total_scrap / total_input * 100) if total_input else 0

# 不良率最高的站
worst_station_info = ""
if not lots.empty:
    sta = lots.groupby("製程編號").agg(i=("投入量", "sum"), s=("報廢數", "sum")).reset_index()
    sta["rate"] = (sta["s"] / sta["i"] * 100).round(3)
    sta = sta.sort_values("rate", ascending=False)
    if len(sta):
        worst_station_info = f"{sta.iloc[0]['製程編號']} ({sta.iloc[0]['rate']:.2f}%)"

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("批號數", f"{len(lots):,}")
c2.metric("總投入量", f"{total_input:,}")
c3.metric("整體良率", f"{overall_yield:.3f}%")
c4.metric("整體不良率", f"{overall_defect:.3f}%")
c5.metric("最弱站", worst_station_info or "-")

st.divider()

# --- 良率趨勢 ---
freq_label = st.radio(
    "趨勢粒度", ["日", "週", "月"], horizontal=True, key="trend_freq", index=1,
)
freq_map = {"日": "D", "週": "W", "月": "M"}
st.plotly_chart(yield_trend(lots, freq_map[freq_label]),
                use_container_width=True, key="ch_trend")

# --- 柏拉圖 + 類別比較 ---
col_a, col_b = st.columns([2, 1])
with col_a:
    top_n = st.slider("柏拉圖 Top N", 5, 30, 15, key="pareto_n")
    st.plotly_chart(defect_pareto(defects, top_n),
                    use_container_width=True, key="ch_pareto")
with col_b:
    st.plotly_chart(category_compare(lots),
                    use_container_width=True, key="ch_category")
    st.plotly_chart(polarity_distribution(lots),
                    use_container_width=True, key="ch_polarity")

# --- 站別比較 + 熱力圖 ---
col_c, col_d = st.columns(2)
with col_c:
    st.plotly_chart(station_yield_compare(lots),
                    use_container_width=True, key="ch_station")
with col_d:
    top_codes = st.slider("熱力圖 Top 缺點數", 10, 40, 20, key="hm_n")
    st.plotly_chart(defect_heatmap(defects, top_codes),
                    use_container_width=True, key="ch_heatmap")
