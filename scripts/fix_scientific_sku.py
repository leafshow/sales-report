#!/usr/bin/env python3
"""修复被 Excel 科学计数损坏的 SKU 列（category_override.csv / sku_override.csv）

背景：运营用 Excel 编辑 CSV 保存时，SKU 列（12 位纯数字）被当数值格式化为 1.00406E+11，
只保留 6 位有效数字，后 6 位丢失。本脚本用「前缀反查」恢复：
  - 从 scripts/.build_cache/*.pkl（全平台解析缓存，含全量 SKU 明细）建前缀索引
  - 前缀在全局唯一 → 自动还原完整 SKU，直接改写 CSV（UTF-8-sig + CRLF，Excel 可直接打开）
  - 前缀多候选 / 无候选 → 列出清单人工确认，不改动
CSV 修复后运行 csv2category_json.py 生成 JSON。

用法：python3 scripts/fix_scientific_sku.py [--dry]
"""
import csv
import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path

CSV_CANDIDATES = [
    Path.home() / "Desktop" / "Platform-Date" / "SKU_Info" / "sku_override.csv",
    Path.home() / "Desktop" / "Platform-Date" / "SKU_Info" / "category_override.csv",
]
CACHE_DIR = Path(__file__).resolve().parent / ".build_cache"
SCI_RE = re.compile(r"^1\.(\d+)E\+\d+$", re.I)

def build_index():
    """全部平台缓存 → {SKU前6位: [(sku, name), ...]}；同时返回 {规范化名称: {sku}}"""
    idx = defaultdict(dict)  # prefix -> {sku: name} 去重
    nm = defaultdict(set)    # 规范化名称 -> {sku}
    for pkl in sorted(CACHE_DIR.glob("*.pkl")):
        try:
            d = pickle.load(open(pkl, "rb"))
        except Exception:
            continue
        for rows in (d.get("sku") or {}).values():
            for r in rows:
                sku = str(r.get("sku") or "")
                name = (r.get("name") or "")
                if not (sku.isdigit() and len(sku) >= 10):
                    continue
                idx[sku[:6]][sku] = name
                nm[name.replace(" ", "")].add(sku)
    return idx, nm

def main():
    dry = "--dry" in sys.argv
    src = next((p for p in CSV_CANDIDATES if p.exists()), None)
    if src is None:
        raise SystemExit(f"❌ 未找到 {' 或 '.join(str(p.name) for p in CSV_CANDIDATES)}")

    # 权威对照：仓库现存 JSON（未损坏时的转换产物），前缀 → 完整 SKU
    json_file = Path(__file__).resolve().parent / "category_override.json"
    known = {}
    if json_file.exists():
        import json
        jd = json.load(open(json_file, encoding="utf-8"))
        for sku in jd.get("category", {}):
            known.setdefault(sku[:6], set()).add(sku)


    with open(src, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or "SKU" not in fields:
        raise SystemExit(f"❌ CSV 表头异常：{fields}")

    sci_rows = [(i, r) for i, r in enumerate(rows) if SCI_RE.match((r["SKU"] or "").strip())]
    if not sci_rows:
        print("✅ 未发现科学计数 SKU，无需修复")
        return
    print(f"科学计数行 {len(sci_rows)}，建全局 SKU 前缀索引…")
    idx, nm_idx = build_index()

    def match_name(key, cand=None):
        """按商品名称消歧：精确 → 子串唯一（限候选集或全量）"""
        k = (key or "").replace(" ", "")
        if not k:
            return None
        exact = nm_idx.get(k, set())
        if len(exact) == 1:
            return next(iter(exact))
        pool = {s: 1 for s in exact} if exact else (cand or {})
        if not pool:
            # 全量子串：CSV 名是源长名的截断（如去掉规格尾部）
            pool = {s: 1 for n, ss in nm_idx.items()
                    if len(n) > len(k) and (k in n or n in k) for s in ss}
        hits = [s for s in pool if any(
            k in n or n in k for n in nm_idx if s in nm_idx[n])][:1]
        return hits[0] if len(hits) == 1 and len(pool) == 1 else None

    fixed, ambiguous, missing = 0, defaultdict(list), []
    for i, r in sci_rows:
        m = SCI_RE.match(r["SKU"].strip())
        prefix = "1" + m.group(1)
        # ① 仓库 JSON 前缀唯一命中（权威）② 全局索引唯一 ③ 三级类目消歧 ④ 商品名称消歧
        src_cand = known.get(prefix) or {}
        if len(src_cand) == 1:
            rows[i]["SKU"] = next(iter(src_cand)); fixed += 1; continue
        cand = idx.get(prefix, {})
        if len(cand) == 1:
            rows[i]["SKU"] = next(iter(cand)); fixed += 1; continue
        c3 = (r.get("三级类目") or "").strip()
        hit = {s: v for s, v in cand.items() if c3 and c3 in v[1]} if cand else {}
        if len(hit) == 1:
            rows[i]["SKU"] = next(iter(hit)); fixed += 1; continue
        pname = match_name(r.get("商品名称"), cand)
        if pname:
            rows[i]["SKU"] = pname; fixed += 1; continue
        pool = hit or cand or src_cand
        if pool:
            ambiguous[prefix].append((i + 2, r["SKU"].strip(), r.get("店铺名称", ""),
                                      [(s, v[0] if isinstance(v, tuple) else v) for s, v in pool.items()]))
        else:
            missing.append((i + 2, r["SKU"].strip(), c3, r.get("店铺名称", "")))

    print(f"\n✅ 自动还原 {fixed} 行")
    if ambiguous:
        print(f"\n⚠️ 前缀多候选 {len(ambiguous)} 组（人工确认后手改 CSV，或换更精确源）：")
        for prefix, items in sorted(ambiguous.items()):
            print(f"  前缀 {prefix}：")
            for line_no, old, shop, cand in items:
                print(f"    行{line_no} {old} [{shop or '仅改类目'}]")
                for sku, name in cand:
                    print(f"      → {sku}  {name}")
    if missing:
        print(f"\n❌ 全局索引无候选 {len(missing)} 行（SKU 可能未出现在任何源数据中，需运营补全表）：")
        for line_no, old, c3, shop in missing:
            print(f"    行{line_no} {old}  三级类目={c3}  店铺={shop or '-'}")

    if fixed and not dry:
        with open(src, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\r\n")
            w.writeheader()
            w.writerows(rows)
        print(f"\n💾 已写回 {src}（剩余问题行见上方清单）")
        print("   下一步：人工处理多候选/缺失行后，运行 python3 scripts/csv2category_json.py")
    elif fixed:
        print("\n(dry 模式，未写回)")

if __name__ == "__main__":
    main()
