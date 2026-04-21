"""Plotly 圖表函式集"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


COLOR_SEQ = px.colors.qualitative.Set2
PRIMARY = "#2E86AB"
ACCENT = "#E63946"


def yield_trend(lots: pd.DataFrame, freq: str = "D") -> go.Figure:
    """良率趨勢線圖。freq: D(日) / W(週) / M(月)"""
    if lots.empty:
        return _empty_fig("無資料")

    df = lots.copy()
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df = df.dropna(subset=["日期"])

    if freq == "W":
        df["期間"] = df["日期"].dt.to_period("W").dt.start_time
        x_label = "週別"
    elif freq == "M":
        df["期間"] = df["日期"].dt.to_period("M").dt.start_time
        x_label = "月份"
    else:
        df["期間"] = df["日期"]
        x_label = "日期"

    grouped = df.groupby("期間").agg(
        投入量=("投入量", "sum"),
        良品數=("良品數", "sum"),
        報廢數=("報廢數", "sum"),
    ).reset_index()
    grouped["良率"] = (grouped["良品數"] / grouped["投入量"] * 100).round(3)
    grouped["不良率"] = (grouped["報廢數"] / grouped["投入量"] * 100).round(3)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=grouped["期間"], y=grouped["投入量"], name="投入量",
               marker_color="#BEE3DB", opacity=0.7),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=grouped["期間"], y=grouped["良率"], name="良率 (%)",
                   mode="lines+markers", line=dict(color=PRIMARY, width=3),
                   marker=dict(size=8)),
        secondary_y=True,
    )
    fig.update_layout(
        title=f"良率趨勢（依{x_label}）",
        xaxis_title=x_label,
        hovermode="x unified",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="投入量", secondary_y=False)
    fig.update_yaxes(title_text="良率 (%)", secondary_y=True, range=[max(0, grouped["良率"].min() - 2), 100])
    return fig


def defect_pareto(defects: pd.DataFrame, top_n: int = 15) -> go.Figure:
    """缺點柏拉圖：Top N 缺點 + 累積百分比"""
    if defects.empty:
        return _empty_fig("無缺點資料")

    agg = defects.groupby(["缺點碼", "缺點中文名"], as_index=False)["缺點數"].sum()
    agg = agg.sort_values("缺點數", ascending=False).head(top_n)
    agg["標籤"] = agg.apply(
        lambda r: f"{r['缺點中文名']}\n{r['缺點碼']}" if r["缺點中文名"] else r["缺點碼"], axis=1
    )
    total = agg["缺點數"].sum()
    agg["累積%"] = (agg["缺點數"].cumsum() / total * 100).round(2)

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=agg["標籤"], y=agg["缺點數"], name="缺點數",
               marker_color=PRIMARY, text=agg["缺點數"], textposition="outside"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=agg["標籤"], y=agg["累積%"], name="累積 %",
                   mode="lines+markers", line=dict(color=ACCENT, width=3),
                   marker=dict(size=8)),
        secondary_y=True,
    )
    fig.update_layout(
        title=f"缺點柏拉圖 Top {top_n}",
        xaxis_title="缺點項目",
        height=480,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="缺點數", secondary_y=False)
    fig.update_yaxes(title_text="累積 %", secondary_y=True, range=[0, 105])
    fig.update_xaxes(tickangle=-35)
    return fig


def station_yield_compare(lots: pd.DataFrame) -> go.Figure:
    """各製程站別良率橫條圖"""
    if lots.empty:
        return _empty_fig("無資料")

    agg = lots.groupby("製程編號").agg(
        投入量=("投入量", "sum"),
        良品數=("良品數", "sum"),
        報廢數=("報廢數", "sum"),
    ).reset_index()
    agg["良率"] = (agg["良品數"] / agg["投入量"] * 100).round(3)
    agg["不良率"] = (agg["報廢數"] / agg["投入量"] * 100).round(3)
    agg = agg.sort_values("不良率", ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=agg["製程編號"],
        x=agg["不良率"],
        orientation="h",
        marker=dict(
            color=agg["不良率"],
            colorscale="Reds",
            showscale=True,
            colorbar=dict(title="不良率 %"),
        ),
        text=agg["不良率"].apply(lambda x: f"{x:.2f}%"),
        textposition="outside",
        hovertemplate="製程:%{y}<br>不良率:%{x:.3f}%<br>投入量:%{customdata[0]:,}<br>報廢:%{customdata[1]:,}<extra></extra>",
        customdata=agg[["投入量", "報廢數"]].values,
    ))
    fig.update_layout(
        title="各製程站別不良率比較",
        xaxis_title="不良率 (%)",
        yaxis_title="製程編號",
        height=max(380, 28 * len(agg) + 120),
    )
    return fig


def defect_heatmap(defects: pd.DataFrame, top_n_codes: int = 20) -> go.Figure:
    """製程站 × 缺點類型 熱力圖"""
    if defects.empty:
        return _empty_fig("無缺點資料")

    top_codes = defects.groupby(["缺點碼", "缺點中文名"])["缺點數"].sum().nlargest(top_n_codes).index
    top_code_keys = [c[0] for c in top_codes]
    df = defects[defects["缺點碼"].isin(top_code_keys)].copy()
    df["缺點標籤"] = df.apply(
        lambda r: f"{r['缺點中文名']} ({r['缺點碼']})" if r["缺點中文名"] else r["缺點碼"], axis=1
    )

    pivot = df.pivot_table(
        index="製程編號", columns="缺點標籤", values="缺點數", aggfunc="sum", fill_value=0
    )
    if pivot.empty:
        return _empty_fig("無資料")

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        colorscale="YlOrRd",
        hovertemplate="製程:%{y}<br>缺點:%{x}<br>數量:%{z}<extra></extra>",
        colorbar=dict(title="缺點數"),
    ))
    fig.update_layout(
        title=f"製程站 × 缺點類型熱力圖 (Top {top_n_codes} 缺點)",
        xaxis_title="缺點",
        yaxis_title="製程編號",
        height=max(400, 28 * len(pivot.index) + 180),
        xaxis=dict(tickangle=-35),
    )
    return fig


def category_compare(lots: pd.DataFrame) -> go.Figure:
    """產品類別 (Gen 1.0 vs 1.5) 比較"""
    if lots.empty:
        return _empty_fig("無資料")

    agg = lots.groupby("產品類別").agg(
        投入量=("投入量", "sum"),
        良品數=("良品數", "sum"),
        報廢數=("報廢數", "sum"),
    ).reset_index()
    agg["不良率"] = (agg["報廢數"] / agg["投入量"] * 100).round(3)

    fig = make_subplots(rows=1, cols=2, subplot_titles=("投入量", "不良率 (%)"))
    fig.add_trace(
        go.Bar(x=agg["產品類別"], y=agg["投入量"], marker_color=PRIMARY,
               text=agg["投入量"].apply(lambda x: f"{x:,}"), textposition="outside",
               showlegend=False),
        row=1, col=1,
    )
    fig.add_trace(
        go.Bar(x=agg["產品類別"], y=agg["不良率"], marker_color=ACCENT,
               text=agg["不良率"].apply(lambda x: f"{x:.3f}%"), textposition="outside",
               showlegend=False),
        row=1, col=2,
    )
    fig.update_layout(title="產品類別比較", height=380)
    return fig


def polarity_distribution(lots: pd.DataFrame) -> go.Figure:
    """Polarity 堆疊長條（依產品類別）"""
    if lots.empty:
        return _empty_fig("無資料")
    agg = lots.groupby(["產品類別", "Polarity"])["投入量"].sum().reset_index()
    fig = px.bar(
        agg, x="產品類別", y="投入量", color="Polarity",
        text="投入量", barmode="stack",
        color_discrete_sequence=COLOR_SEQ,
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="inside")
    fig.update_layout(title="Polarity 分布", height=380)
    return fig


def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=16, color="gray"),
    )
    fig.update_layout(height=320, xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig
