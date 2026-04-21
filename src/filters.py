"""共用的 Streamlit 側邊欄篩選器"""
import streamlit as st
from datetime import datetime, timedelta
from src.db import get_filter_options


@st.cache_data(ttl=300)
def _cached_filter_options():
    """快取篩選器選項 5 分鐘（上傳新資料會自動失效或手動清快取）"""
    return get_filter_options()


def sidebar_filters(default_recent_days: int = 30) -> dict:
    """
    側邊欄篩選器。預設只顯示最近 30 天資料，避免一次載入數十萬筆。
    """
    st.sidebar.header("🔍 篩選條件")

    if st.sidebar.button("🔄 重新整理資料", use_container_width=True,
                         help="清除快取、重新從資料庫抓取最新資料"):
        st.cache_data.clear()
        st.rerun()

    opts = _cached_filter_options()

    # 日期區間：預設最近 N 天
    min_date = opts["日期範圍"].get("min_date")
    max_date = opts["日期範圍"].get("max_date")
    if min_date and max_date:
        start_full = datetime.strptime(min_date, "%Y-%m-%d").date()
        end = datetime.strptime(max_date, "%Y-%m-%d").date()
        start_default = max(start_full, end - timedelta(days=default_recent_days))

        st.sidebar.caption(f"📅 DB 資料範圍：{min_date} ~ {max_date}")

        # 關鍵：widget key 綁定 max_date，新資料進來會自動重設日期選擇器
        widget_key = f"date_range_{min_date}_{max_date}"

        date_range = st.sidebar.date_input(
            f"日期區間（預設最近 {default_recent_days} 天）",
            value=(start_default, end),
            min_value=start_full, max_value=end,
            key=widget_key,
        )

        # 按鈕：一鍵涵蓋全部歷史
        if st.sidebar.button("📆 涵蓋全部資料", use_container_width=True):
            # 刪掉舊 widget state，下次 rerun 會用新的 value
            for k in list(st.session_state.keys()):
                if k.startswith("date_range_"):
                    del st.session_state[k]
            st.session_state[widget_key] = (start_full, end)
            st.rerun()
    else:
        date_range = None

    產品類別 = st.sidebar.multiselect("產品類別", opts["產品類別"])
    製程編號 = st.sidebar.multiselect("製程編號", opts["製程編號"])
    Polarity = st.sidebar.multiselect("Polarity", opts["Polarity"])
    品名 = st.sidebar.multiselect("品名", opts["品名"])
    缺點碼_labels = st.sidebar.multiselect("缺點碼", opts["缺點碼"])
    缺點碼 = [s.split(" - ")[0] for s in 缺點碼_labels]

    filters = {
        "產品類別": 產品類別 or None,
        "製程編號": 製程編號 or None,
        "Polarity": Polarity or None,
        "品名": 品名 or None,
    }
    if date_range and isinstance(date_range, tuple) and len(date_range) == 2:
        filters["日期_start"] = date_range[0].strftime("%Y-%m-%d")
        filters["日期_end"] = date_range[1].strftime("%Y-%m-%d")

    filters["_defect_codes"] = 缺點碼 or None
    return filters
