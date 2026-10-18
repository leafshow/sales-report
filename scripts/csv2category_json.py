#!/usr/bin/env python3
"""桌面 CSV SKU 归属映射 → 仓库 JSON 转换工具

流程：运营编辑 ~/Desktop/Platform-Date/SKU_Info/sku_override.csv（Excel 可直接打开），
运行本脚本生成 scripts/category_override.json，提交入库；构建时扫描 JSON 改写类目与店铺归属。

CSV 列：一级类目,二级类目,三级类目,SKU[,店铺名称]
  - 店铺名称留空 → 仅改写类目；填写 → 同时将该 SKU 划转至目标店铺（须在 config.py 注册）

JSON 结构：{"category": {SKU: [一级,二级,三级]}, "shop": {SKU: 目标店铺名}}
（兼容旧扁平格式 {SKU: [c1,c2,c3]}，自动升级为两段式）

用法：python3 scripts/csv2category_json.py
"""
import csv
import json
from pathlib import Path

CSV_FILE = Path.home() / "Desktop" / "Platform-Date" / "SKU_Info" / "sku_override.csv"
JSON_FILE = Path(__file__).resolve().parent / "category_override.json"

def main():
    # 兼容旧文件名
    legacy = CSV_FILE.parent / "category_override.csv"
    src = CSV_FILE if CSV_FILE.exists() else legacy if legacy.exists() else None
    if src is None:
        raise SystemExit(f"❌ 未找到 {CSV_FILE}（或旧名 category_override.csv）")
    cats, shops, bad, dup = {}, {}, [], []
    with open(src, encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        need = {"一级类目", "二级类目", "三级类目", "SKU"}
        missing = need - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"❌ CSV 表头缺失列：{missing}（实际：{reader.fieldnames}）")
        has_shop = "店铺名称" in (reader.fieldnames or [])
        for i, row in enumerate(reader, 2):
            sku = (row["SKU"] or "").strip()
            c3 = [(row[c] or "").strip() for c in ("一级类目", "二级类目", "三级类目")]
            shop = (row.get("店铺名称") or "").strip() if has_shop else ""
            if not sku or not all(c3):
                bad.append(i); continue
            if sku in cats and cats[sku] != c3:
                dup.append(sku)
            cats[sku] = c3
            if shop:
                shops[sku] = shop
    out = {"category": cats, "shop": shops}
    JSON_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"✅ 类目映射 {len(cats)} 个 SKU，店铺划转 {len(shops)} 个 SKU → {JSON_FILE.relative_to(Path.cwd())}"
          f"（空行/缺字段 {len(bad)} 行跳过，类目冲突覆盖 {len(set(dup))} 个：{sorted(set(dup)) or '无'}）")

if __name__ == "__main__":
    main()

