"""批次匯入歷史原始資料：從資料夾一次讀入所有 Excel 檔（優化版）"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from src.db import init_db, upsert_lots_and_defects, log_import
from src.parser import (
    classify_file, parse_base_file, parse_defect_file, process_base,
)


def log(msg):
    """印出並立即 flush（避免 buffer 卡住）"""
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser(description="批次匯入歷史 Excel 原始資料")
    parser.add_argument("folder", help="包含 Excel 檔案的資料夾路徑")
    parser.add_argument(
        "--batch-size", type=int, default=6,
        help="一次處理幾個基礎檔（預設 6）",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        log(f"❌ 資料夾不存在: {folder}")
        sys.exit(1)

    init_db()

    t0 = time.time()
    all_files = sorted([f for f in folder.iterdir() if f.is_file()])
    base_files = [f for f in all_files if classify_file(f) == "base"]
    defect_files = [f for f in all_files if classify_file(f) == "defect"]

    log(f"📁 資料夾: {folder}")
    log(f"  基礎檔（資料匯出）: {len(base_files)} 個")
    log(f"  缺點檔（各站不良原因統計表）: {len(defect_files)} 個")

    if not base_files:
        log("❌ 沒有可處理的基礎檔")
        sys.exit(1)

    # === 步驟 1: 只讀一次所有缺點檔，建立全域缺點表 ===
    log(f"\n[1/3] 讀取 {len(defect_files)} 個缺點檔...")
    defect_list = []
    for i, f in enumerate(defect_files, 1):
        t = time.time()
        df = parse_defect_file(f)
        if not df.empty:
            defect_list.append(df)
            log(f"  ({i}/{len(defect_files)}) ✓ {f.name}: {len(df)} 列 [{time.time() - t:.1f}s]")
        else:
            log(f"  ({i}/{len(defect_files)}) ✗ {f.name}: 空白")

    if defect_list:
        global_defects = pd.concat(defect_list, ignore_index=True)
        global_defects = global_defects.groupby(
            ["RUNCARD", "製程編號", "缺點碼", "缺點中文名"], as_index=False
        )["缺點數"].sum()
        log(f"  → 合併缺點表共 {len(global_defects)} 列")
    else:
        global_defects = pd.DataFrame(columns=["RUNCARD", "製程編號", "缺點碼", "缺點中文名", "缺點數"])

    # === 步驟 2: 分批處理基礎檔 + 寫入 DB ===
    log(f"\n[2/3] 分批處理 {len(base_files)} 個基礎檔（每批 {args.batch_size} 個）...")
    total_inserted, total_updated = 0, 0
    num_batches = (len(base_files) - 1) // args.batch_size + 1

    for bi in range(0, len(base_files), args.batch_size):
        batch = base_files[bi : bi + args.batch_size]
        batch_num = bi // args.batch_size + 1
        log(f"\n--- 批次 {batch_num}/{num_batches} ---")

        base_list = []
        for f in batch:
            t = time.time()
            df = parse_base_file(f)
            if not df.empty:
                base_list.append(df)
                log(f"  ✓ 基礎檔 {f.name}: {len(df)} 列 [{time.time() - t:.1f}s]")
            else:
                log(f"  ✗ 基礎檔空白: {f.name}")

        if not base_list:
            continue

        df_base = pd.concat(base_list, ignore_index=True)
        lots_df = process_base(df_base)

        # 只過濾 defects 到這批有的 RunCard（減少資料量）
        batch_keys = set(zip(
            lots_df["RUNCARD"].astype(str),
            lots_df["製程編號"].astype(str),
        ))
        if not global_defects.empty:
            mask = list(zip(
                global_defects["RUNCARD"].astype(str),
                global_defects["製程編號"].astype(str),
            ))
            batch_defects = global_defects[[m in batch_keys for m in mask]]
        else:
            batch_defects = global_defects

        log(f"  💾 寫入: lots={len(lots_df)}, defects={len(batch_defects)}")
        t = time.time()
        inserted, updated = upsert_lots_and_defects(
            lots_df, batch_defects,
            source_file=", ".join(b.name for b in batch),
        )
        total_inserted += inserted
        total_updated += updated
        log(f"  ✅ 新增 {inserted}, 更新 {updated} [{time.time() - t:.1f}s]")

        for b in batch:
            log_import(b.name, "success", f"新增 {inserted} / 更新 {updated}")

    log(f"\n[3/3] 完成！")
    log(f"🎉 總計新增 {total_inserted}, 更新 {total_updated}")
    log(f"⏱ 總耗時 {time.time() - t0:.1f} 秒")


if __name__ == "__main__":
    main()
