"""Excel 解析器：移植自 ULLD 批號各站資料.py，改輸出給 DB 寫入的 DataFrame"""
import warnings
from pathlib import Path
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")


DEFECT_DESC_MAP = {
    # ULLDD 系列
    "ULLDD1": "SMT錫膏不足", "ULLDD2": "SMT料件損毀", "ULLDD3": "Strip 爆板",
    "ULLDD4": "SMT元件傾斜", "ULLDD5": "Strip 清洗破裂", "ULLDD6": "SMT未置件", "ULLDD7": "SMT Others",
    # ULLDE 系列
    "ULLDE1": "Underfill包覆不足", "ULLDE2": "Underfill飛濺", "ULLDE3": "Underfill溢膠",
    "ULLDE4": "Underfill髒污", "ULLDE5": "Underfill站Strip 破裂", "ULLDE6": "Strip 爆板",
    "ULLDE7": "Underfill Others",
    # ULLDF 系列
    "ULLDF1": "Strip膠膜未切斷", "ULLDF2": "Strip髒污", "ULLDF3": "Strip 破裂",
    "ULLDF4": "Dice 飛落", "ULLDF5": "Strip切割異常", "ULLDF7": "Strip Mount/Saw Others",
    # ULLDG 系列 (Gen 1.0)
    "ULLDG1": "ASM站Strip 破裂", "ULLDG2": "Chip 偏移", "ULLDG3": "Chip 髒污",
    "ULLDG4": "燒結銀膠量異常", "ULLDG5": "ASM站機台異常", "ULLDG6": "Strip 爆板", "ULLDG7": "ASM Others",
    # ULLDH 系列 (Gen 1.0)
    "ULLDH1": "Chip 破裂", "ULLDH2": "Chip 偏移", "ULLDH3": "外觀髒污",
    "ULLDH4": "溢膠", "ULLDH5": "拉力", "ULLDH6": "燒結異常", "ULLDH7": "Ag Sintering Others",
    # ULLDI 系列
    "ULLDI1": "引線沾黑膠", "ULLDI2": "銅殼沾黑膠", "ULLDI3": "引線變色",
    "ULLDI4": "來料異常", "ULLDI5": "膠量異常", "ULLDI6": "壓環異常",
    "ULLDI7": "Underfill(Lead)/Epoxy Others",
    # ULLDJ 系列
    "ULLDJ1": "引線沾黑膠", "ULLDJ2": "銅殼沾黑膠", "ULLDJ3": "引線銅殼受傷",
    "ULLDJ4": "髒污", "ULLDJ5": "Sleeve 異常", "ULLDJ6": "膠量異常", "ULLDJ7": "VM Others",
    # ULLDR 系列 (Gen 1.5)
    "ULLDR1": "ASM站Strip 破裂", "ULLDR2": "Chip 髒污", "ULLDR3": "引線未落下",
    "ULLDR4": "ASM站機台異常", "ULLDR5": "Strip 爆板", "ULLDR6": "ASM Others", "ULLDR7": "ASM Others",
    # ULLDS 系列 (Gen 1.5)
    "ULLDS1": "Chip 破裂", "ULLDS2": "Chip 偏移", "ULLDS3": "錫外流",
    "ULLDS4": "錫覆蓋不全", "ULLDS5": "焊接氣孔", "ULLDS6": "焊接異常", "ULLDS7": "Soldering Others",
    # ULLDT 系列 (Gen 1.5)
    "ULLDT1": "引線沾膠", "ULLDT2": "銅殼沾膠", "ULLDT3": "來料異常",
    "ULLDT4": "膠量異常", "ULLDT5": "Underfill(Lead) Others", "ULLDT7": "Underfill(Lead) Others",
    # 測試系列 (P, Q, K, L, M, N, O)
    "ULLDP1": "HTVF-VF", "ULLDP2": "HTVF-VB", "ULLDP3": "HTVF-IR", "ULLDP4": "HTVF-Short",
    "ULLDP5": "HTVF-T4 IR", "ULLDP6": "HTVF-DVF", "ULLDP7": "HTVF Others",
    "ULLDQ1": "HTVF-VF", "ULLDQ2": "HTVF-VB", "ULLDQ3": "HTVF-IR", "ULLDQ4": "HTVF-Short",
    "ULLDQ5": "HTVF-T4 IR", "ULLDQ6": "HTVF-DVF", "ULLDQ7": "HTVF Others",
    "ULLDK1": "HTIR-VB", "ULLDK2": "HTIR-IR", "ULLDK3": "HTIR-Short", "ULLDK4": "HTIR-DVR",
    "ULLDK5": "HTIR-V off", "ULLDK6": "HTIR-T4 IR", "ULLDK7": "HTIR Others",
    "ULLDL1": "PT-VF", "ULLDL2": "PT-VB", "ULLDL3": "PT-IR", "ULLDL4": "PT-Short", "ULLDL5": "PT-DVF",
    "ULLDL6": "PT-Ron VF", "ULLDL7": "PT Others",
    "ULLDM1": "PT-VF", "ULLDM2": "PT-VB", "ULLDM3": "PT-IR", "ULLDM4": "PT-Short", "ULLDM5": "PT-DVF",
    "ULLDM6": "PT-Ron VF", "ULLDM7": "PT Others",
    "ULLDN1": "PT-VF", "ULLDN2": "PT-VB", "ULLDN3": "PT-IR", "ULLDN4": "PT-Short", "ULLDN5": "PT-DVF",
    "ULLDN6": "PT-Ron VF", "ULLDN7": "PT Others",
    "ULLDO1": "PP-IR", "ULLDO2": "PP-VB", "ULLDO3": "PP-Lead bend", "ULLDO4": "PP-Dot NG",
    "ULLDO5": "PP-Laser NG", "ULLDO7": "PP Others",
}


def smart_read_file(file_path, header_row, sheet_name=None):
    """讀 Excel，若失敗則用 read_html（處理 HTML 假裝成 xls 的檔案）"""
    try:
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_row)
        else:
            df = pd.read_excel(file_path, header=header_row)
    except Exception:
        try:
            dfs = pd.read_html(file_path, header=header_row)
            df = dfs[0] if dfs else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    if not df.empty:
        df.columns = [str(c).replace("\xa0", " ").strip() for c in df.columns]
    return df


def _is_base_file(filename: str) -> bool:
    """判斷是否為「月份/週資料匯出」基礎檔"""
    name = filename.lower()
    return "資料匯出" in filename and name.endswith((".xls", ".xlsx", ".htm", ".html"))


def _is_defect_file(filename: str) -> bool:
    """判斷是否為「各站不良原因統計表」缺點檔"""
    name = filename.lower()
    return "各站不良原因統計表" in filename and name.endswith((".xls", ".xlsx", ".htm", ".html"))


def classify_file(file_path: Path) -> str:
    """回傳 'base' / 'defect' / 'unknown'"""
    name = file_path.name
    if _is_base_file(name):
        return "base"
    if _is_defect_file(name):
        return "defect"
    return "unknown"


def parse_base_file(file_path) -> pd.DataFrame:
    """讀取月份/週資料匯出檔，回傳原始 DataFrame（尚未處理日期等）"""
    df = smart_read_file(file_path, header_row=1)
    if df.empty:
        return df
    df = df.rename(columns={
        "Run Card": "RUNCARD",
        "生產料件": "產品名稱",
        "開工日期": "日期",
        "作業編號": "製程編號",
    })
    return df


def parse_defect_file(file_path) -> pd.DataFrame:
    """讀取各站不良原因統計表 → long format (RUNCARD, 製程編號, 缺點碼, 缺點數)"""
    df = smart_read_file(
        file_path,
        header_row=3,
        sheet_name="各站不良原因碼統計過去七天 (依缺點碼) ",
    )
    if df.empty:
        return df
    df = df.dropna(how="all").ffill()
    if "RUNCARD" not in df.columns or "製程編號" not in df.columns:
        return pd.DataFrame()
    df["RUNCARD"] = df["RUNCARD"].astype(str).str.strip()
    df["製程編號"] = df["製程編號"].astype(str).str.strip()
    df["缺點數"] = pd.to_numeric(df["缺點數"], errors="coerce").fillna(0)
    df["缺點中文名"] = df["缺點碼"].map(DEFECT_DESC_MAP).fillna("")
    return df[["RUNCARD", "製程編號", "缺點碼", "缺點中文名", "缺點數"]]


def process_base(df: pd.DataFrame) -> pd.DataFrame:
    """處理基礎 DataFrame：日期衍生欄位、產品類別、Polarity、投入量、不良率"""
    if df.empty:
        return df
    df = df.copy()
    df["良品數"] = pd.to_numeric(df["良品數"], errors="coerce").fillna(0).astype(int)
    df["報廢數"] = pd.to_numeric(df["報廢數"], errors="coerce").fillna(0).astype(int)

    dt = pd.to_datetime(df["日期"], format="%y/%m/%d", errors="coerce")
    if dt.isna().all():
        dt = pd.to_datetime(df["日期"], errors="coerce")

    df["日期"] = dt.dt.strftime("%Y-%m-%d")
    df["年"] = dt.dt.year
    df["月"] = dt.dt.month
    df["季"] = dt.apply(lambda x: f"Q{(x.month - 1) // 3 + 1}" if pd.notnull(x) else None)
    df["週"] = dt.apply(lambda x: f"W{x.isocalendar()[1]:02d}" if pd.notnull(x) else None)

    if "產品名稱" not in df.columns:
        df["產品名稱"] = ""
    df["Polarity"] = df["產品名稱"].astype(str).str[-1]
    df["投入量"] = df["良品數"] + df["報廢數"]
    df["不良率"] = np.where(df["投入量"] > 0, df["報廢數"] / df["投入量"], 0.0)

    df["製程編號"] = df["製程編號"].astype(str).str.strip()
    df["RUNCARD"] = df["RUNCARD"].astype(str).str.strip()

    conditions = [
        df["製程編號"].str.startswith("U", na=False),
        df["製程編號"].str.startswith("G", na=False),
    ]
    choices = ["ULLD Gen 1.0", "ULLD Gen 1.5"]
    df["產品類別"] = np.select(conditions, choices, default="Other")
    df = df[df["產品類別"] != "Other"].copy()

    for col in ["作業名稱", "品名", "規格"]:
        if col not in df.columns:
            df[col] = ""

    output_cols = [
        "日期", "年", "季", "月", "週", "產品類別", "RUNCARD", "製程編號",
        "作業名稱", "產品名稱", "Polarity", "品名", "規格",
        "良品數", "報廢數", "投入量", "不良率",
    ]
    for c in output_cols:
        if c not in df.columns:
            df[c] = None

    df = df.drop_duplicates(subset=["RUNCARD", "製程編號"], keep="last")
    return df[output_cols].reset_index(drop=True)


def parse_folder(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """
    讀取整個資料夾，自動分類 base 檔與 defect 檔，合併產出：
    - lots_df: 批號主表（已處理）
    - defects_df: 缺點明細 long format
    - messages: 處理訊息列表
    """
    folder = Path(folder)
    base_list, defect_list, messages = [], [], []

    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        kind = classify_file(f)
        if kind == "base":
            df = parse_base_file(f)
            if not df.empty:
                base_list.append(df)
                messages.append(f"  ✓ 讀取基礎檔: {f.name} ({len(df)} 列)")
            else:
                messages.append(f"  ✗ 基礎檔空白: {f.name}")
        elif kind == "defect":
            df = parse_defect_file(f)
            if not df.empty:
                defect_list.append(df)
                messages.append(f"  ✓ 讀取缺點檔: {f.name} ({len(df)} 列)")
            else:
                messages.append(f"  ✗ 缺點檔空白: {f.name}")

    if not base_list:
        return pd.DataFrame(), pd.DataFrame(), messages

    df_base = pd.concat(base_list, ignore_index=True)
    lots_df = process_base(df_base)

    if defect_list:
        defects_df = pd.concat(defect_list, ignore_index=True)
        defects_df = defects_df.groupby(
            ["RUNCARD", "製程編號", "缺點碼", "缺點中文名"], as_index=False
        )["缺點數"].sum()
    else:
        defects_df = pd.DataFrame(columns=["RUNCARD", "製程編號", "缺點碼", "缺點中文名", "缺點數"])

    return lots_df, defects_df, messages


def parse_files(file_paths: list) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """直接處理檔案列表（給 Streamlit 上傳流程用）"""
    base_list, defect_list, messages = [], [], []

    for f in file_paths:
        fp = Path(f)
        kind = classify_file(fp)
        if kind == "base":
            df = parse_base_file(fp)
            if not df.empty:
                base_list.append(df)
                messages.append(f"✓ 基礎檔 {fp.name}: {len(df)} 列")
            else:
                messages.append(f"✗ 基礎檔空白: {fp.name}")
        elif kind == "defect":
            df = parse_defect_file(fp)
            if not df.empty:
                defect_list.append(df)
                messages.append(f"✓ 缺點檔 {fp.name}: {len(df)} 列")
            else:
                messages.append(f"✗ 缺點檔空白: {fp.name}")
        else:
            messages.append(f"⚠ 無法辨識: {fp.name}（需要「資料匯出」或「各站不良原因統計表」關鍵字）")

    if not base_list:
        return pd.DataFrame(), pd.DataFrame(), messages

    df_base = pd.concat(base_list, ignore_index=True)
    lots_df = process_base(df_base)

    if defect_list:
        defects_df = pd.concat(defect_list, ignore_index=True)
        defects_df = defects_df.groupby(
            ["RUNCARD", "製程編號", "缺點碼", "缺點中文名"], as_index=False
        )["缺點數"].sum()
    else:
        defects_df = pd.DataFrame(columns=["RUNCARD", "製程編號", "缺點碼", "缺點中文名", "缺點數"])

    return lots_df, defects_df, messages
