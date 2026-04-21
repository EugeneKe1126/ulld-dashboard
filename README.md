# ULLD 資料庫儀表板

Eugene 的 ULLD 產線資料庫 + 互動式儀表板系統。

## 功能

- 📤 上傳每日 Excel 原始資料（密碼保護）
- 📊 即時儀表板：良率趨勢、缺點柏拉圖、站別比較、熱力圖
- 🔍 多維度篩選：產品類別 / 製程編號 / Polarity / 品名 / 缺點碼 / 日期區間
- 💾 下載篩選後資料（Excel / CSV）

## 本機啟動

```bash
pip install -r requirements.txt
streamlit run app.py
```

開啟 http://localhost:8501

## 專案結構

```
ulld-dashboard/
├── app.py                    # 入口
├── pages/
│   ├── 1_📊_儀表板.py
│   ├── 2_🔍_資料查詢.py
│   └── 3_📤_資料匯入.py       # 需密碼
├── src/
│   ├── parser.py             # Excel 解析
│   ├── db.py                 # 資料庫操作
│   ├── charts.py             # Plotly 圖表
│   └── auth.py               # 密碼驗證
├── scripts/
│   └── bulk_import.py        # 批次匯入歷史
└── data/
    └── ulld.db               # SQLite 本機資料庫
```
