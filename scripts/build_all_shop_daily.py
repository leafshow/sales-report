from __future__ import annotations
import json, re, warnings
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import duckdb
import config  # noqa: F401 — 路径已在 config.py 中定义

warnings.filterwarnings("ignore", message="Workbook contains no default style")
PLATFORM_DIRS = config.PLATFORM_DIRS
OUT      = config.OUT
TEMPLATE = config.TEMPLATE
API_DATA_DIR = config.API_DATA_DIR  # API 数据目录
DB_PATH = config.DB_PATH            # DuckDB 数据库路径
FILE_RE  = re.compile(config.FILE_PATTERN)
FILE_RE_PDD = re.compile(config.FILE_PATTERN_PDD)
FILE_RE_JD_SELF = re.compile(config.FILE_PATTERN_JD_SELF)
FILE_RE_JD_SELF_TRAFFIC = re.compile(config.FILE_PATTERN_JD_SELF_TRAFFIC)
FILE_RE_JD_SELF_SHOPRANK = re.compile(config.FILE_PATTERN_JD_SELF_SHOPRANK)
FILE_RE_JD_SELF_CITY = re.compile(config.FILE_PATTERN_JD_SELF_CITY)
FILE_RE_TMALL = re.compile(config.FILE_PATTERN_TMALL)
FILE_RE_VIP_JITX = re.compile(config.FILE_PATTERN_VIP_JITX)
SHOPS    = config.SHOPS
SHOP_META     = {f"{k[0]}|{k[1]}": v for k, v in config.SHOPS_VISIBLE.items()}   # 内部唯一 key = 平台|店铺名（仅可见店铺）
SHOP_PLATFORM = {f"{k[0]}|{k[1]}": k[0] for k in SHOPS}
HIDDEN_SHOPS  = config.HIDDEN_SHOPS   # 隐藏店铺：仍解析入库存数据，但不参与聚合与展示
SHOP_START_DATES = config.SHOP_START_DATES  # 店铺数据起始日期：早于此的空报表不告警（开业前正常形态）
def _bark_notify(data):
    """构建完成后通过 Bark 推送各平台店铺日报更新情况。
    推送内容：每平台一段，按店铺列出最新日期 GMV；当日无数据的店铺标「未更新」；
    开业前（早于 shop_start_dates）店铺不列。失败仅打印警告，不影响构建结果。"""
    base = (config.BARK_URL or "").rstrip("/")
    if not base:
        return
    import urllib.request, urllib.parse
    latest = data["quality"]["latestAvailableDate"]
    sd = SHOP_START_DATES
    by_plat = defaultdict(list)
    for key in SHOP_META:  # 仅可见店铺，按注册顺序
        plat = key.split("|", 1)[0]
        rows = data["shopDaily"].get(key, [])
        row = next((r for r in rows if r["date"] == latest), None)
        if row is None and sd.get(key) and latest < sd[key]:
            continue  # 开业前：正常无数据，不推送
        disp = SHOP_META[key][0]
        by_plat[plat].append(f"{disp}: " + (f"¥{row['gmv']:,.0f}" if row else "未更新"))
    if not any(by_plat.values()):
        return
    plat_names = PLATFORMS
    lines = [f"📅 {latest} 日报更新"]
    for plat in PLATFORM_DIRS:
        if plat not in by_plat:
            continue
        lines.append(f"— {plat_names.get(plat, plat)} —")
        lines.extend(by_plat[plat])
    missing = len(data["quality"].get("missingDates", []))
    if missing:
        lines.append(f"⚠️ 缺失日期: {missing} 天")
    body = "\n".join(lines)
    try:
        qs = urllib.parse.urlencode({
            "title": f"日报 {latest}",
            "body": body,
            "group": "shop-daily",
            "icon": "https://vercel.com/icon",
        })
        url = f"{base}/push?{qs}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"🔔 Bark 推送完成: {resp.status}")
    except Exception as e:
        print(f"⚠️  Bark 推送失败（不影响构建）: {e}")
def _record_empty(q, shop_key, shop_name, date, fname):
    """记录空报表；店铺开业前（早于 shop_start_dates.json 起始日期）的空表为正常形态，不告警"""
    sd = SHOP_START_DATES.get(shop_key, "")
    if sd and date < sd:
        return  # 开业前空表：静默跳过
    q.setdefault("emptyFiles", []).append({"shop": shop_name, "date": date, "file": fname})
PLATFORMS = config.PLATFORMS
FIELDS   = config.FIELDS
COLUMNS  = config.COLUMNS
# 从 config 导入阈值与限制（供本文件函数引用）
ALERT_RULES     = config.ALERT_RULES
OPP_MIN_VISITORS = config.OPP_MIN_VISITORS
OPP_CONV_RATIO   = config.OPP_CONV_RATIO
OPP_PER_ALERT    = config.OPP_PER_ALERT
ALERT_PER_DATE   = config.ALERT_PER_DATE
TOP_SKU_POOL         = config.TOP_SKU_POOL
TOP_PER_SHOP_POOL    = config.TOP_PER_SHOP_POOL
DAILY_SHIFT_LIMIT    = config.DAILY_SHIFT_LIMIT
DAILY_PER_SHOP       = config.DAILY_PER_SHOP
OPP_PER_DAY          = config.OPP_PER_DAY
OPPORTUNITIES_MAX    = config.OPPORTUNITIES_MAX
RECENT_DAYS          = config.RECENT_DAYS
PRIOR_DAYS           = config.PRIOR_DAYS
RESEARCH_DAYS        = config.RESEARCH_DAYS
BASELINE_WIN         = config.BASELINE_WIN
WEEK_AGO_WIN         = config.WEEK_AGO_WIN

def n(v):
    try:
        if pd.isna(v): return 0.0
        return float(v)
    except Exception: return 0.0

def t(v): return "-" if pd.isna(v) else str(v)
def r(a,b): return None if not b else a/b
def sqlnum(v):
    """f-string 插入 DuckDB 时的数值格式化：None → NULL（避免写入字符串 'None'）"""
    if v is None: return "NULL"
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))): return "NULL"
    return repr(float(v)) if isinstance(v, float) else str(v)

def calc(row):
    row["conversion"]=r(row["buyers"],row["visitors"]); row["aov"]=r(row["gmv"],row["buyers"])
    row["unitPrice"]=r(row["gmv"],row["units"]); row["uvValue"]=r(row["gmv"],row["visitors"])
    row["searchCtr"]=r(row["searchClicks"],row["searchImpressions"])
    row["addCartRate"]=r(row["addCartUsers"],row["visitors"])
    row["orderConversion"]=r(row["orderBuyers"],row["visitors"])
    row["orderCompletion"]=r(row["orders"],row["orderCount"]); row["refundRate"]=r(row["refundAmount"],row["gmv"])
    return row

def base(rows):
    if not rows: return None
    x={k:sum(z[k] for z in rows)/len(rows) for k in FIELDS}
    return calc(x)

def pdd_parse_file(path, date):
    """解析拼多多商品数据 CSV（单日商品维度快照），返回 (店铺行, SKU 明细)

    源表 60 列，仅取报表框架已有字段，其余（推广策略/同行均值/活动信息/各类环比等）一律丢弃。
    口径：SKU 级流量与成交直接求和。
    """
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    if len(df) == 0:
        return None, []
    num = lambda c: pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    cnt = lambda c: int(num(c).sum())
    x = {"date": date, "skuCount": int(df["商品ID"].nunique()), "sourceFile": path.name,
         "gmv": float(num("成交金额").sum()), "units": cnt("成交件数"),
         "orders": cnt("成交订单数"), "buyers": cnt("成交买家数"),
         "visitors": cnt("商品访客数"), "pv": cnt("商品浏览量"),
         "searchImpressions": 0, "searchClicks": 0,
         "productImpressions": 0, "productImpressionUsers": 0,
         "addCartUsers": cnt("商品收藏用户数"),   # 拼多多无加购口径，收藏用户数等同加购
         "orderAmount": float(num("成交金额").sum()), "orderCount": cnt("确认订单数"),
         "orderBuyers": cnt("下单用户数"), "refundAmount": 0.0}
    row = calc(x)
    skus = []
    for _, s in df.iterrows():
        sgmv = float(pd.to_numeric(s["成交金额"], errors="coerce") or 0)
        svis = int(pd.to_numeric(s["商品访客数"], errors="coerce") or 0)
        sbuy = int(pd.to_numeric(s["成交买家数"], errors="coerce") or 0)
        skus.append({"_date": date, "sku": str(s["商品ID"]), "name": t(s["商品名称"]),
                     "category1": t(s["一级类目"]), "category2": t(s["二级类目"]),
                     "category3": t(s["三级类目"]),
                     "gmv": sgmv, "units": int(pd.to_numeric(s["成交件数"], errors="coerce") or 0),
                     "orders": int(pd.to_numeric(s["成交订单数"], errors="coerce") or 0),
                     "buyers": sbuy, "visitors": svis,
                     "searchImpressions": 0, "searchClicks": 0,
                     "addCartUsers": int(pd.to_numeric(s["商品收藏用户数"], errors="coerce") or 0),
                     "refundAmount": 0.0, "conversion": r(sbuy, svis),
                     "uvValue": r(sgmv, svis)})
    return row, skus

def tmall_parse_file(path, date):
    """解析天猫生意参谋商品报表 .xls（表头第 5 行，明细行），返回 (店铺行, SKU 明细)

    口径映射：支付金额→gmv、支付件数→units、支付买家数→buyers、下单买家数→orders（单量近似）、
    商品访客数→visitors、商品浏览量→pv、商品加购人数→addCartUsers、成功退款金额→refundAmount。
    """
    df = pd.read_excel(path, header=4)
    if len(df) == 0:
        return None, []
    # 数值列可能是带千分位逗号的文本（如 "3,561.65"），先统一去逗号再转数值
    num = lambda c: pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce").fillna(0.0)
    cnt = lambda c: int(num(c).sum())
    gmv = float(num("支付金额").sum())
    x = {"date": date, "skuCount": int(df["商品ID"].nunique()), "sourceFile": path.name,
         "gmv": gmv, "units": cnt("支付件数"), "orders": cnt("支付买家数"),
         "buyers": cnt("支付买家数"), "visitors": cnt("商品访客数"), "pv": cnt("商品浏览量"),
         "searchImpressions": 0, "searchClicks": 0,
         "productImpressions": 0, "productImpressionUsers": 0,
         "addCartUsers": cnt("商品加购人数"),
         "orderAmount": float(num("下单金额").sum()), "orderCount": cnt("下单买家数"),
         "orderBuyers": cnt("下单买家数"), "refundAmount": float(num("成功退款金额").sum())}
    row = calc(x)
    skus = []
    num_s = lambda c: pd.to_numeric(str(s[c]).replace(",", ""), errors="coerce")
    for _, s in df.iterrows():
        sgmv = num_s("支付金额")
        sgmv = 0.0 if pd.isna(sgmv) else float(sgmv)
        v = num_s("商品访客数"); svis = 0 if pd.isna(v) else int(v)
        v = num_s("支付买家数"); sbuy = 0 if pd.isna(v) else int(v)
        v = num_s("支付件数"); units = 0 if pd.isna(v) else int(v)
        v = num_s("商品加购人数"); cart = 0 if pd.isna(v) else int(v)
        v = num_s("成功退款金额"); refund = 0.0 if pd.isna(v) else float(v)
        skus.append({"_date": date, "sku": str(s["商品ID"]), "name": t(s["商品名称"]),
                     "category1": "未分类", "category2": "未分类", "category3": "未分类",
                     "gmv": sgmv, "units": units,
                     "orders": sbuy, "buyers": sbuy, "visitors": svis,
                     "searchImpressions": 0, "searchClicks": 0,
                     "addCartUsers": cart,
                     "refundAmount": refund,
                     "conversion": r(sbuy, svis), "uvValue": r(sgmv, svis)})
    return row, skus

SELF_FIELDS   = config.SELF_FIELDS

HEAD_CITY_LIMIT = 20   # 头部 SKU 数量（按昨日出库件数）
MAIN_CITIES = config.MAIN_CITIES
JD_CITY_SOURCE = config.JD_CITY_SOURCE

def jdself_city_stock(path, date):
    """解析头部 SKU 的主要城市现货库存。
    返回 {店铺名: [{sku,name,city,stock,daysCover}...]}，仅头部 SKU × 主要城市。
    兼容两种列名格式（{城市}现货库存 / {城市}城市现货库存）；无城市列返回 {}。
    """
    head=pd.read_excel(path, nrows=0)
    stock_cols={}
    for city in MAIN_CITIES:
        col=city+"现货库存"
        if col not in head.columns:
            col=city+"城市现货库存"
        if col in head.columns:
            stock_cols[city]=col
    if not stock_cols:
        return {}
    out_col="全国昨日出库商品件数" if "全国昨日出库商品件数" in head.columns else "昨日出库商品件数"
    w7_col="全国近7日出库商品件数" if "全国近7日出库商品件数" in head.columns else "近7日出库商品件数"
    need=["SKU","商品名称","店铺名称","全国采购价",out_col,w7_col]+list(stock_cols.values())
    if "全国现货库存" in head.columns:
        need.append("全国现货库存")
    for c in ("全国采购在途数量","采购在途数量","采购在途"):
        if c in head.columns:
            need.append(c)
            nat_transit_col=c
            break
    if "是否售完即止" in head.columns:
        need.append("是否售完即止")
    df=pd.read_excel(path, usecols=[c for c in need if c in head.columns])
    if len(df)==0 or out_col not in df.columns:
        return {}
    non_num_cols={"SKU","商品名称","店铺名称","是否售完即止"}
    for c in df.columns:
        if c not in non_num_cols:
            df[c]=pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["_shop"]=df["店铺名称"].fillna("未分配").astype(str).str.strip()
    if "是否售完即止" in df.columns:
        df = df[df["是否售完即止"].astype(str).str.strip() != "是"]
        if len(df)==0: return {}
    result={}
    for shop,g in df.groupby("_shop"):
        top=g.nlargest(HEAD_CITY_LIMIT,out_col)
        rows=[]
        for _,r in top.iterrows():
            avg7=float(r.get(w7_col,0))/7.0
            nat_stock=float(r.get("全国现货库存",0) or 0)
            nat_transit=float(r.get(nat_transit_col,0) or 0) if nat_transit_col else 0.0
            nat_days=round(nat_stock/avg7,1) if avg7>0 else None
            for city,col in stock_cols.items():
                st=float(r[col])
                days=round(st/avg7,1) if avg7>0 else None
                rows.append({"sku":str(r["SKU"]),"name":t(r["商品名称"]),"city":city,
                             "stock":st,"dailyAvg":round(avg7,1),"daysCover":days,
                             "outYesterday":float(r.get(out_col,0) or 0),
                             "out7d":float(r.get(w7_col,0) or 0),
                             "natStock":nat_stock,"natDaysCover":nat_days,
                             "natTransit":nat_transit,
                             "natOutYesterday":float(r.get(out_col,0) or 0),
                             "natOut7d":float(r.get(w7_col,0) or 0),
                             "price":float(r.get("全国采购价",0) or 0)})
        if rows:
            result[shop]={"date":date,"rows":rows}
    return result

def jdself_city_stock_vertical(path, date):
    """解析纵版自营商品明细的 RDC 列（长表：每 SKU × RDC 一行）。
    RDC 值形态：全国 / 无 / 城市名 / 城市名+后缀（如 上海FDC配送中心、临沂配送中心、北京城市）。
    城市归一：剥离 FDC/配送中心/本地仓中心/城市/大商超/零售/补货B 等后缀后匹配 MAIN_CITIES。
    返回与横版 jdself_city_stock 相同结构：{店铺名: {gmvOutbound,unitsOutbound,stockValue,out30dValue,rows:[...]}}。
    """
    df = pd.read_excel(path, usecols=lambda c: c in ("SKU","商品名称","店铺名称","RDC","现货库存",
                                                      "昨日出库商品件数","近7日出库商品件数","全国采购价","是否售完即止",
                                                      "采购在途数量"))
    need={"SKU","商品名称","店铺名称","RDC","现货库存","昨日出库商品件数","全国采购价"}
    if not need <= set(df.columns) or len(df)==0:
        return {}
    for c in ("现货库存","昨日出库商品件数","近7日出库商品件数","全国采购价"):
        if c in df.columns: df[c]=pd.to_numeric(df[c],errors="coerce").fillna(0.0)
    if "近7日出库商品件数" not in df.columns: df["近7日出库商品件数"]=0.0
    if "采购在途数量" in df.columns:
        df["采购在途数量"]=pd.to_numeric(df["采购在途数量"],errors="coerce").fillna(0.0)
    # 售完即止商品不再补货，无预警意义，进入任何统计前整行剔除
    if "是否售完即止" in df.columns:
        df = df[df["是否售完即止"].astype(str).str.strip() != "是"]
        if len(df) == 0: return {}
    # RDC=全国 行是全国合计口径（现货=全国现货库存件数），仅用于全国库存/覆盖；分仓行用于城市格
    nat_cols = ["现货库存", "近7日出库商品件数", "昨日出库商品件数"] + (["采购在途数量"] if "采购在途数量" in df.columns else [])
    nat = df[df["RDC"].astype(str).str.strip() == "全国"].groupby("SKU")[nat_cols].sum()
    # 无全国行的 SKU：全国=分仓合计，用全部行合计兜底
    nat = nat.combine_first(df.groupby("SKU")[nat_cols].sum())
    nat.index = nat.index.astype(str)
    def norm_city(v):
        v=str(v).strip()
        if not v or v in ("全国","无","nan"): return None
        for suf in ("FDC配送中心","配送中心","本地仓中心","大商超","补货B","FDC","零售","城市"):
            if v.endswith(suf): v=v[:-len(suf)]
        return v if v in MAIN_CITIES else None
    df["_city"]=df["RDC"].map(norm_city)
    df=df[df["_city"].notna()]
    if len(df)==0: return {}
    result={}
    for shop,g in df.groupby("店铺名称"):
        g=g.copy()
        # 头部 SKU：按该店总出库件数 TOP N
        top_skus=g.groupby("SKU")["昨日出库商品件数"].sum().nlargest(HEAD_CITY_LIMIT).index
        g=g[g["SKU"].astype(str).isin(set(str(x) for x in top_skus))]
        name_map=g.assign(_s=g["SKU"].astype(str)).drop_duplicates("_s").set_index("_s")["商品名称"]
        rows=[]
        for (sku,city),r in g.groupby(["SKU","_city"]):
            sku=str(sku)
            stock=float(r["现货库存"].sum()); out7=float(r["近7日出库商品件数"].sum())
            avg7=out7/7.0
            nat_stock=float(nat.loc[sku, "现货库存"]) if sku in nat.index else 0.0
            nat_avg7=float(nat.loc[sku, "近7日出库商品件数"])/7.0 if sku in nat.index else 0.0
            nat_transit=float(nat.loc[sku, "采购在途数量"]) if sku in nat.index and "采购在途数量" in nat.columns else 0.0
            nat_out_d=float(nat.loc[sku, "昨日出库商品件数"]) if sku in nat.index else 0.0
            nat_out7=float(nat.loc[sku, "近7日出库商品件数"]) if sku in nat.index else 0.0
            rows.append({"sku":sku,"name":t(name_map.get(sku,"")),"city":city,
                         "stock":stock,"dailyAvg":round(avg7,1),
                         "daysCover":round(stock/avg7,1) if avg7>0 else None,
                         "outYesterday":float(r["昨日出库商品件数"].sum()),
                         "out7d":out7,
                         "natStock":nat_stock,"natDaysCover":round(nat_stock/nat_avg7,1) if nat_avg7>0 else None,
                         "natTransit":nat_transit,
                         "natOutYesterday":nat_out_d,"natOut7d":nat_out7,
                         "price":float(r["全国采购价"].iloc[0])})
        if rows: result[shop]={"rows":rows}
    return result

def jdself_city_stock_auto(path, date):
    """城市库存解析自适配入口（数据源由 config.JD_CITY_SOURCE 控制，默认 vertical 纵版）。"""
    if JD_CITY_SOURCE == "vertical":
        return jdself_city_stock_vertical(path, date)
    return jdself_city_stock(path, date)

def jdself_inventory_metrics(path, date):
    """解析京东自营库存表（供货口径），返回 {店铺名: {gmvOutbound, unitsOutbound, stockValue, out30dValue, skus: [...]}}"""
    # 列名兼容：新导出（10 月起）省略「全国」前缀（现货库存/昨日出库商品件数/近30日出库商品件数）
    df = pd.read_excel(path, nrows=0)
    ALIAS = {"全国现货库存": "现货库存", "全国昨日出库商品件数": "昨日出库商品件数",
             "全国近30日出库商品件数": "近30日出库商品件数", "全国月至今出库商品件数": "月至今出库商品件数"}
    colmap = {}
    for full, short in ALIAS.items():
        if full not in df.columns and short in df.columns:
            colmap[full] = short
    if colmap:
        base = ["SKU", "商品名称", "店铺名称", "一级类目", "二级类目", "三级类目", "全国采购价"]
        use = base + list(colmap.values()) + (["RDC"] if "RDC" in df.columns else [])
        df = pd.read_excel(path, usecols=use)
        df = df.rename(columns={v: k for k, v in colmap.items()})
    else:
        df = pd.read_excel(path, usecols=["SKU", "商品名称", "店铺名称", "一级类目", "二级类目",
                                           "三级类目", "全国采购价", "全国昨日出库商品件数",
                                           "全国现货库存", "全国近30日出库商品件数",
                                           "全国月至今出库商品件数"] +
                                   (["RDC"] if "RDC" in df.columns else []))
    if len(df) == 0:
        return {}
    # 纵版新格式：每 SKU 一行 RDC=全国（全国合计）+ N 行分仓明细，全国=分仓合计，直接求和会翻倍。
    # 存在 RDC=全国 行时仅保留全国行；旧横版（无 RDC 列）每 SKU 一行，不受影响。
    if "RDC" in df.columns:
        nat = df[df["RDC"].astype(str).str.strip() == "全国"]
        if len(nat) > 0:
            df = nat
    price = pd.to_numeric(df["全国采购价"], errors="coerce").fillna(0.0)
    out_d = pd.to_numeric(df["全国昨日出库商品件数"], errors="coerce").fillna(0.0)
    stock = pd.to_numeric(df["全国现货库存"], errors="coerce").fillna(0.0)
    out30 = pd.to_numeric(df["全国近30日出库商品件数"], errors="coerce").fillna(0.0)
    out_m = pd.to_numeric(df["全国月至今出库商品件数"], errors="coerce").fillna(0.0)
    df["_gmvOut"] = price * out_d
    df["_unitsOut"] = out_d
    df["_stockVal"] = price * stock
    df["_out30Val"] = price * out30
    df["_outMtdVal"] = price * out_m
    df["_shop"] = df["店铺名称"].fillna("未分配").astype(str).str.strip()
    result = {}
    for shop, g in df.groupby("_shop"):
        skus = [{"_date": date, "sku": str(s["SKU"]), "name": t(s["商品名称"]), "shop": shop,
                 "category1": t(s["一级类目"]), "category2": t(s["二级类目"]), "category3": t(s["三级类目"]),
                 "gmv": float(s["_gmvOut"]), "gmvOutbound": float(s["_gmvOut"]), "units": int(s["_unitsOut"]), "orders": 0,
                 "unitsOutbound": int(s["_unitsOut"]), "stockValue": float(s["_stockVal"]),
                 "out30dValue": float(s["_out30Val"]), "outMtdValue": float(s["_outMtdVal"]), "orders": 0,
                 "buyers": 0, "visitors": 0, "searchImpressions": 0, "searchClicks": 0, "addCartUsers": 0,
                 "refundAmount": 0.0, "conversion": None, "uvValue": None}
                for _, s in g.iterrows()]
        result[shop] = {"gmvOutbound": float(g["_gmvOut"].sum()), "unitsOutbound": int(g["_unitsOut"].sum()),
                        "stockValue": float(g["_stockVal"].sum()), "out30dValue": float(g["_out30Val"].sum()),
                        "outMtdValue": float(g["_outMtdVal"].sum()), "skus": skus}
    return result

def jdself_traffic_metrics(path, date):
    """解析京东自营流量表（经营状况商品明细，商智 22 列标准口径），返回 {店铺名: 指标}。

    时间列含「至」为窗口累计（非日快照），跳过并返回 {}。
    口径：gmv=成交金额（零售实付），visitors/pv/buyers/orders/units/addCartUsers 直接取列。
    仅保留已注册店铺（如 西麦食品官方旗舰店 是 POP 店，不在 jd_self 白名单则被跳过）。
    """
    df = pd.read_excel(path, usecols=["时间", "SKU", "商品名称", "店铺名称", "一级类目", "二级类目",
                                       "三级类目", "浏览量", "访客数", "成交人数", "成交单量",
                                       "成交商品件数", "成交金额", "加购人数"])
    if len(df) == 0:
        return {}
    if "至" in str(df["时间"].iloc[0]):
        return None  # 窗口累计，调用方跳过
    for c in ["浏览量", "访客数", "成交人数", "成交单量", "成交商品件数", "成交金额", "加购人数"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["_shop"] = df["店铺名称"].fillna("未分配").astype(str).str.strip()
    result = {}
    for shop, g in df.groupby("_shop"):
        result[shop] = {"gmv": float(g["成交金额"].sum()), "units": int(g["成交商品件数"].sum()),
                        "orders": int(g["成交单量"].sum()), "buyers": int(g["成交人数"].sum()),
                        "visitors": int(g["访客数"].sum()), "pv": int(g["浏览量"].sum()),
                        "addCartUsers": int(g["加购人数"].sum()),
                        "skuCount": int(g["SKU"].nunique()), "sourceFile": path.name,
                        "skus": [{"_date": date, "sku": str(s["SKU"]), "name": t(s["商品名称"]), "shop": shop,
                                  "category1": t(s["一级类目"]), "category2": t(s["二级类目"]),
                                  "category3": t(s["三级类目"]),
                                  "gmv": float(s["成交金额"]), "units": int(s["成交商品件数"]),
                                  "orders": int(s["成交单量"]), "buyers": int(s["成交人数"]),
                                  "visitors": int(s["访客数"]),
                                  "searchImpressions": 0, "searchClicks": 0, "addCartUsers": int(s["加购人数"]),
                                  "refundAmount": 0.0, "conversion": r(int(s["成交人数"]), int(s["访客数"])),
                                  "uvValue": r(float(s["成交金额"]), int(s["访客数"]))}
                                 for _, s in g.iterrows()]}
    return result

def jdself_shoprank_metrics(path, date):
    """解析京东自营店铺排行表（商智店铺级日快照，访客去重口径，8 列），返回 {店铺名: 指标}。

    用途：覆盖经营状况商品明细表（分 SKU 不去重）累加出的店铺级访客/成交人数等，
    修正店铺转化率被低估的问题。时间列含「至」为窗口累计，返回 None 跳过。
    无 SKU 明细，仅影响店铺行，SKU 层数据仍取流量/库存表。
    """
    df = pd.read_excel(path)
    if len(df) == 0:
        return {}
    if "至" in str(df["时间"].iloc[0]):
        return None  # 窗口累计，调用方跳过
    for c in ["浏览量", "访客数", "成交人数", "成交单量", "成交商品件数", "成交金额"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["_shop"] = df["店铺名称"].fillna("未分配").astype(str).str.strip()
    result = {}
    for shop, g in df.groupby("_shop"):
        result[shop] = {"gmv": float(g["成交金额"].sum()), "units": int(g["成交商品件数"].sum()),
                        "orders": int(g["成交单量"].sum()), "buyers": int(g["成交人数"].sum()),
                        "visitors": int(g["访客数"].sum()), "pv": int(g["浏览量"].sum()),
                        "sourceFile": path.name}
    return result

def total_row(date, shop, row, count, source, platform='jd'):
    if platform == 'vip':
        return vip_total_row(date, shop, row, count, source)
    x={"date":date,"shopRaw":shop,"shopDisplay":shop_display(shop),"skuCount":count,"sourceFile":source,
       "gmv":n(row["成交金额"]),"units":n(row["成交商品件数"]),"orders":n(row["成交单量"]),
       "buyers":n(row["成交客户数"]),"visitors":n(row["商品访客数"]),"pv":n(row["商品浏览量"]),
       "searchImpressions":n(row["搜索曝光次数"]),"searchClicks":n(row["搜索点击次数"]),
       "productImpressions":n(row["商品曝光次数"]),"productImpressionUsers":n(row["商品曝光人数"]),
       "addCartUsers":n(row["加购客户数"]),"orderAmount":n(row["下单金额"]),"orderCount":n(row["下单单量"]),
       "orderBuyers":n(row["下单客户数"]),"refundAmount":n(row["取消及售后退款金额"])}
    return calc(x)

def shop_platform(shop):
    """返回店铺所属平台（'jd' / 'vip' / 'pdd'）"""
    return SHOP_PLATFORM.get(shop, 'jd')

def shop_display(shop):
    """店铺显示名：统一加平台前缀，避免跨平台同名店铺混淆（如京东与拼多多的「飞鹤成人奶粉旗舰店」）"""
    return f"{PLATFORMS[shop_platform(shop)]}/{SHOP_META[shop][0]}"

def vip_total_row(date, shop, row, count, source):
    """唯品会合计行：字段精简，缺失指标置 0/None"""
    x={"date":date,"shopRaw":shop,"shopDisplay":shop_display(shop),"skuCount":count,"sourceFile":source,
       "gmv":n(row["销售额"]),"units":n(row["销售量"]),"orders":0,
       "buyers":n(row["客户数"]),"visitors":n(row["商详UV"]),"pv":n(row["商详UV"]),
       "searchImpressions":0,"searchClicks":0,"productImpressions":0,"productImpressionUsers":0,
       "addCartUsers":0,"orderAmount":0,"orderCount":0,"orderBuyers":0,"refundAmount":0}
    return calc(x)

def vip_sku_rows(date, shop, df):
    """唯品会明细行"""
    out=[]
    for _,q in df.iterrows():
        x={"date":date,"shopRaw":shop,"shopDisplay":shop_display(shop),"sku":t(q["商品ID"]),"name":t(q["商品名称"]),
           "category1":"未分类","category2":"未分类","category3":"未分类",
           "gmv":n(q["销售额"]),"units":n(q["销售量"]),"orders":0,
           "buyers":n(q["客户数"]),"visitors":n(q["商详UV"]),"searchImpressions":0,
           "searchClicks":0,"addCartUsers":0,"refundAmount":0}
        x["conversion"]=r(x["buyers"],x["visitors"]); x["uvValue"]=r(x["gmv"],x["visitors"]); out.append(x)
    return out

def sku_rows(date, shop, df, platform='jd'):
    if platform == 'vip':
        return vip_sku_rows(date, shop, df)
    out=[]
    for _,q in df.iterrows():
        x={"date":date,"shopRaw":shop,"shopDisplay":shop_display(shop),"sku":t(q["SKU"]),"name":t(q["SKU名称"]),
           "category1":t(q["一级类目"]),"category2":t(q["二级类目"]),"category3":t(q["三级类目"]),
           "gmv":n(q["成交金额"]),"units":n(q["成交商品件数"]),"orders":n(q["成交单量"]),
           "buyers":n(q["成交客户数"]),"visitors":n(q["商品访客数"]),"searchImpressions":n(q["搜索曝光次数"]),
           "searchClicks":n(q["搜索点击次数"]),"addCartUsers":n(q["加购客户数"]),"refundAmount":n(q["取消及售后退款金额"])}
        x["conversion"]=r(x["buyers"],x["visitors"]); x["uvValue"]=r(x["gmv"],x["visitors"]); out.append(x)
    return out

def trim_sku(x):
    keys = ["shopRaw","shopDisplay","sku","name","gmv","units","visitors",
            "refundAmount","conversion","uvValue","gmvOutbound"]
    return {k:x.get(k) if (k=="gmvOutbound" and x.get("gmvOutbound") is None) else x.get(k,0) for k in keys}

def trim_change(x):
    keys = ["shopRaw","shopDisplay","sku","name","previousGmv","gmv","delta"]
    return {k:x[k] for k in keys}

def build(plat_only=None, force=False):
    # 收集各平台文件：[(path, platform)]
    # plat_only：指定平台时仅重新解析该平台目录，其余平台从缓存（.build_cache/<plat>.pkl）载入解析中间产物
    # force：忽略目录指纹缓存，强制重新解析全部文件
    file_list=[]
    for plat, pdir in PLATFORM_DIRS.items():
        if plat_only and plat != plat_only:
            continue
        if pdir.exists():
            if plat == "pdd":
                file_list.extend((f, plat) for f in sorted(pdir.glob("*.csv")) if FILE_RE_PDD.match(f.name))
            elif plat == "tmall":
                file_list.extend((f, plat) for f in sorted(list(pdir.glob("*.xls")) + list(pdir.glob("*.xlsx")))
                                 if FILE_RE_TMALL.match(f.name) and not f.name.startswith("~$"))
            elif plat == "vip_jitx":
                # 唯品会 JITX：单文件多日累积报表（{店铺}JITX销售*销售数据.xlsx）
                file_list.extend((f, plat) for f in sorted(pdir.glob("*.xlsx"))
                                 if FILE_RE_VIP_JITX.match(f.name) and not f.name.startswith("~$"))
            elif plat == "jd_self":
                # 排除 Excel 锁文件 ~$xxx.xlsx；库存表 + 流量表双源
                for f in sorted(pdir.glob("*.xlsx")):
                    if f.name.startswith("~$"): continue
                    if FILE_RE_JD_SELF.match(f.name) or FILE_RE_JD_SELF_TRAFFIC.match(f.name) or FILE_RE_JD_SELF_CITY.match(f.name) or FILE_RE_JD_SELF_SHOPRANK.match(f.name):
                        file_list.append((f, plat))
            else:
                file_list.extend((f, plat) for f in sorted(pdir.glob("*.xlsx"))
                                 if FILE_RE.match(f.name) and not f.name.startswith("~$"))
        else:
            print(f"⚠️  平台 {plat} 数据目录不存在: {pdir}")
    file_list.sort(key=lambda x: x[0].name)
    q={"sourceFiles":len(file_list),"parsedFiles":0,"schemaOk":True,"totalRowsOk":True,
        "duplicateSkuCount":0,"reconciliationOk":True,"unexpectedShops":[],"windowFiles":[],"emptyFiles":[]}
    shop_rows={s:[] for s in SHOP_META}; sku={}; pairs=set()
    jd_self_files=defaultdict(list)  # date -> [(kind, path)]

    # ── 目录指纹：平台全部源文件 (mtime, size) 摘要；与上次一致 → 该平台直接读缓存跳过解析 ──
    import pickle
    CACHE_DIR = Path(__file__).resolve().parent / ".build_cache"
    CACHE_DIR.mkdir(exist_ok=True)
    full_file_list = list(file_list)  # 完整文件清单（未过滤），供指纹保存
    def _fingerprint(plat):
        return sorted((f.name, int(f.stat().st_mtime), f.stat().st_size) for f, p in full_file_list if p == plat)
    city_stock = {}
    unchanged_plats = set()
    if not force:
        for plat in {p for _, p in file_list}:
            fp_file = CACHE_DIR / f"{plat}.fp"
            if not fp_file.exists(): continue
            try:
                if pickle.load(open(fp_file, "rb")) == _fingerprint(plat):
                    cf = CACHE_DIR / f"{plat}.pkl"
                    if cf.exists(): unchanged_plats.add(plat)
            except Exception:
                pass
    # 从缓存载入无变化平台的解析产物；剩余平台进入解析
    for plat in sorted(unchanged_plats):
        with open(CACHE_DIR / f"{plat}.pkl", "rb") as fh:
            blob = pickle.load(fh)
        shop_rows.update(blob["shop_rows"])
        for d, lst in blob["sku"].items(): sku.setdefault(d, []).extend(lst)
        pairs |= blob["pairs"]
        if plat == "jd_self": city_stock.update(blob.get("city_stock", {}))
        cq = blob.get("q", {})
        q["sourceFiles"] = q["sourceFiles"] - sum(1 for f, p in file_list if p == plat) + cq.get("sourceFiles", 0)
        q["emptyFiles"] += cq.get("emptyFiles", [])
        # 该平台文件与上次完全一致：解析计数按上次口径（≈源文件数，排除空文件）
        q["parsedFiles"] += cq.get("sourceFiles", 0) - len(cq.get("emptyFiles", []))
        print(f"⚡ 平台 [{plat}] 源文件无变化，读缓存跳过解析")
    file_list = [(f, p) for f, p in file_list if p not in unchanged_plats]

    # 第一轮：其他平台 + 记录 jd_self 文件按日期分组
    for f, plat in file_list:
        if plat == "jd_self":
            m_inv = FILE_RE_JD_SELF.match(f.name)
            m_traf = FILE_RE_JD_SELF_TRAFFIC.match(f.name)
            m_city=FILE_RE_JD_SELF_CITY.match(f.name)
            m_rank = FILE_RE_JD_SELF_SHOPRANK.match(f.name)
            if m_city:
                d2=f"{m_city.group(1)[:4]}-{m_city.group(1)[4:6]}-{m_city.group(1)[6:]}"
                jd_self_files.setdefault(d2,[]).append(("city", f))
            elif m_inv:
                jd_self_files[m_inv.group(2)].append(("inventory", f))
            elif m_traf:
                jd_self_files[m_traf.group(2)].append(("traffic", f))
            elif m_rank:
                jd_self_files[m_rank.group(2)].append(("rank", f))
            continue  # jd_self 稍后单独处理
        if plat == "pdd":
            m=FILE_RE_PDD.match(f.name)
            if not m: continue
            raw_shop=m.group(1)
            key=f"{plat}|{raw_shop}"
            if key not in SHOP_META:
                q["unexpectedShops"].append(f"pdd:{raw_shop}"); continue
            date=m.group(2)
            row_p, skus_p = pdd_parse_file(f, date)
            if not row_p:
                _record_empty(q, key, raw_shop, date, f.name); continue
            q["parsedFiles"]+=1
            pairs.add((key,date))
            row_p["shopRaw"]=key; row_p["shopDisplay"]=shop_display(key)
            shop_rows[key].append(row_p)
            for sk in skus_p:
                sk.update({"date":date,"shopRaw":key,"shopDisplay":shop_display(key)})
                sku.setdefault(date,[]).append(sk)
            continue
        if plat == "tmall":
            m=FILE_RE_TMALL.match(f.name)
            if not m: continue
            raw_shop=m.group(1)
            key=f"{plat}|{raw_shop}"
            if key not in SHOP_META:
                q["unexpectedShops"].append(f"tmall:{raw_shop}"); continue
            date=m.group(2)
            row_t, skus_t = tmall_parse_file(f, date)
            if not row_t:
                _record_empty(q, key, raw_shop, date, f.name); continue
            q["parsedFiles"]+=1
            pairs.add((key,date))
            row_t["shopRaw"]=key; row_t["shopDisplay"]=shop_display(key)
            shop_rows[key].append(row_t)
            for sk in skus_t:
                sk.update({"date":date,"shopRaw":key,"shopDisplay":shop_display(key)})
                sku.setdefault(date,[]).append(sk)
            continue
        if plat == "vip_jitx":
            # 单文件多日累积报表，按「品牌名称」拆分为多店铺（维维JITX / 飞鹤JITX），再按「日期」拆分为逐日数据
            if not FILE_RE_VIP_JITX.match(f.name): continue
            df=pd.read_excel(f)
            df["日期"]=df["日期"].astype(str).str.slice(0,10)
            for brand, bg in df.groupby(df["品牌名称"].fillna("未知").astype(str).str.strip()):
                key=f"{plat}|{brand}JITX"
                if key not in SHOP_META:
                    q["unexpectedShops"].append(f"{plat}:{brand}"); continue
                for date,g in bg.groupby("日期"):
                    if len(g)==0: continue
                    q["parsedFiles"]+=1; pairs.add((key,date))
                    totals={c: g[c].sum() for c in ("销售额","销售量","客户数","商详UV")}
                    shop_rows[key].append(vip_total_row(date,key,totals,len(g),f.name)); sku.setdefault(date,[]).extend(vip_sku_rows(date,key,g))
            continue
        m=FILE_RE.match(f.name)
        if not m: continue
        shop,date=m.groups()
        key=f"{plat}|{shop}"
        if key not in SHOP_META:
            q["unexpectedShops"].append(f"{plat}:{shop}"); continue
        shop=key
        df=pd.read_excel(f)
        if plat == 'vip':
            # 唯品会：无合计行，全部为明细行；指标取明细求和
            if len(df)==0:
                _record_empty(q, shop, shop, date, f.name); continue
            q["parsedFiles"]+=1; pairs.add((shop,date))
            totals={c: df[c].sum() for c in ("销售额","销售量","客户数","商详UV")}
            shop_rows[shop].append(vip_total_row(date,shop,totals,len(df),f.name)); sku.setdefault(date,[]).extend(vip_sku_rows(date,shop,df))
        else:
            # 空报表（0 数据行，无合计行）：店铺开业前或当日无销售，跳过（开业前不告警）
            if len(df)==0:
                _record_empty(q, shop, shop, date, f.name); continue
            missing=[c for c in COLUMNS if c not in df.columns]
            if missing: raise RuntimeError(f"{f.name} missing {missing}")
            if len(df)<2 or t(df.iloc[0]["SKU"])!="合计": raise RuntimeError(f"{f.name} missing total row")
            total=df.iloc[0]; detail=df.iloc[1:]
            q["parsedFiles"]+=1; pairs.add((shop,date)); q["duplicateSkuCount"]+=int(detail["SKU"].astype(str).duplicated().sum())
            ok=abs(n(total["成交金额"])-sum(n(x) for x in detail["成交金额"]))<=max(.01,abs(n(total["成交金额"]))*.001)
            ok2=abs(n(total["成交商品件数"])-sum(n(x) for x in detail["成交商品件数"]))<=max(.01,abs(n(total["成交商品件数"]))*.001)
            q["reconciliationOk"] &= ok and ok2
            # 赠品过滤：成交金额<0 的商品为赠品（随单附赠），除成交金额（负值冲抵退款/调整）与
            # 访客数（明细合计不去重，店铺访客取源表总合计行去重值，故不参与过滤）外，
            # 件数/人数/曝光等全部清零，避免虚增店铺正常经营指标；合计行对应字段按清零后明细重算
            gift = pd.to_numeric(detail["成交金额"], errors="coerce").fillna(0) < 0
            if gift.any():
                zero_cols=[c for c in ("成交商品件数","成交单量","成交客户数","商品浏览量",
                                       "搜索曝光次数","搜索点击次数","商品曝光次数","商品曝光人数",
                                       "加购客户数","下单金额","下单单量","下单客户数","取消及售后退款金额")
                           if c in detail.columns]
                detail=detail.copy(); detail.loc[gift, zero_cols]=0
                total=total.copy()
                for c in zero_cols: total[c]=pd.to_numeric(detail[c], errors="coerce").fillna(0).sum()
            shop_rows[shop].append(total_row(date,shop,total,len(detail),f.name)); sku.setdefault(date,[]).extend(sku_rows(date,shop,detail))

    # ── jd_self：按 (日期) 聚合库存表 + 经营状况表，合并为唯一一行 ──
    # city_stock 已在缓存载入阶段初始化；此处勿重复置空（否则命中缓存的平台数据被清掉）
    for date, entries in sorted(jd_self_files.items()):
        inv={}; traf={}; rank={}
        for kind, f in entries:
            if kind == "city":
                try:
                    cs=jdself_city_stock_auto(f, date)
                    if cs:
                        if date in city_stock:
                            print(f"⚠️  同日多份城市库存文件，{f.name} 覆盖已有数据")
                        city_stock[date]=cs
                except Exception as e:
                    print(f"⚠️  城市库存解析失败 {f.name}: {e}")
            elif kind == "inventory":
                inv = jdself_inventory_metrics(f, date)  # 同日多份时后者覆盖（正常仅一份）
                try:
                    cs=jdself_city_stock_auto(f, date)
                    if cs:
                        if date in city_stock:
                            print(f"⚠️  同日多份城市库存文件，{f.name} 覆盖已有数据")
                        city_stock[date]=cs
                except Exception as e:
                    print(f"⚠️  城市库存解析失败 {f.name}: {e}")
            elif kind == "rank":
                rk = jdself_shoprank_metrics(f, date)
                if rk is None:
                    q.setdefault("windowFiles", []).append({"date": date, "file": f.name})
                    continue
                rank = rk
            else:
                tr = jdself_traffic_metrics(f, date)
                if tr is None:
                    # 窗口累计文件（时间列含「至」），跳过并记录
                    q.setdefault("windowFiles", []).append({"date": date, "file": f.name})
                    continue
                traf = tr
            q["parsedFiles"]+=1
        # 排行表店铺不在 inv/traf 时也应生成店铺行（如当日只有排行表导出）
        all_shops = set(inv) | set(traf) | set(rank)
        for shop_name in sorted(all_shops):
            key=f"jd_self|{shop_name}"
            if key not in SHOP_META:
                q["unexpectedShops"].append(f"jd_self:{shop_name}"); continue
            i = inv.get(shop_name, {}); tr = traf.get(shop_name, {}); rk = rank.get(shop_name, {})
            # 零售口径优先级：店铺排行表（店铺级去重，转化率正确口径）> 经营状况明细累加。
            # 仅覆盖店铺行 gmv/units/orders/buyers/visitors/pv；addCartUsers/skuCount 排行表无，仍取明细表
            retail = rk if rk else tr
            x = {"date": date, "skuCount": tr.get("skuCount", i.get("skuCount", 0)),
                 "sourceFile": (rk.get("sourceFile") or tr.get("sourceFile") or i.get("sourceFile") or ""),
                 # 零售口径：有则用，无则 0
                 "gmv": float(retail.get("gmv", 0.0)), "units": int(retail.get("units", 0)),
                 "orders": int(retail.get("orders", 0)), "buyers": int(retail.get("buyers", 0)),
                 "visitors": int(retail.get("visitors", 0)), "pv": int(retail.get("pv", 0)),
                 "addCartUsers": int(tr.get("addCartUsers", 0)),
                 # 供货口径（库存表）：有则用，无则 0
                 "gmvOutbound": float(i.get("gmvOutbound", 0.0)),
                 "unitsOutbound": int(i.get("unitsOutbound", 0)),
                 "stockValue": float(i.get("stockValue", 0.0)),
                 "out30dValue": float(i.get("out30dValue", 0.0)),
                 "outMtdValue": float(i.get("outMtdValue", 0.0)),
                 # 框架其他字段补 0
                 "searchImpressions": 0, "searchClicks": 0,
                 "productImpressions": 0, "productImpressionUsers": 0,
                 "orderAmount": float(retail.get("gmv", 0.0)), "orderCount": int(retail.get("orders", 0)),
                 "orderBuyers": int(retail.get("buyers", 0)), "refundAmount": 0.0}
            pairs.add((key,date))
            x["shopRaw"]=key; x["shopDisplay"]=shop_display(key)
            shop_rows[key].append(calc(x))
            # SKU 层：库存 SKU + 流量 SKU，按 (shop, sku) 合并——成交/流量字段取流量表，供货字段取库存表
            merged={}
            for src in (i.get("skus", []), tr.get("skus", [])):
                for sk in src:
                    sid=str(sk["sku"])
                    if sid in merged:
                        merged[sid].update({k: v for k, v in sk.items()
                                            if k not in ("units", "gmv") and v not in (0, 0.0, None)})
                    else:
                        merged[sid]=dict(sk)
            for sid, sk in merged.items():
                sk.pop("shop", None)
                sk.update({"date":date,"shopRaw":key,"shopDisplay":shop_display(key)})
                sku.setdefault(date,[]).append(sk)

    # ── 平台级解析缓存（增量更新用）──────────────────────────────────
    # 无变化平台在循环前已读缓存（见 unchanged_plats）；此处保存本轮实际解析平台的
    # 解析中间产物 + 目录指纹，之后聚合、指标、图表、落库仍全量重算，口径与全量一致。
    import pickle
    CACHE_DIR = Path(__file__).resolve().parent / ".build_cache"
    CACHE_DIR.mkdir(exist_ok=True)
    # 本轮实际解析的平台 = 参与解析的 file_list 中的平台
    parsed_plats = {p for _, p in file_list}
    def _fingerprint_full(plat):
        return sorted((f.name, int(f.stat().st_mtime), f.stat().st_size) for f, p in full_file_list if p == plat)
    # 保存本轮解析结果（按平台拆分）
    def _plat_of(key):  # shop_rows/sku 键 → 平台
        return key.split("|", 1)[0] if isinstance(key, str) else None
    for plat in parsed_plats:
        c_shop = {s: rows for s, rows in shop_rows.items() if _plat_of(s) == plat}
        c_sku = {}
        for d, lst in sku.items():
            flt = [x for x in lst if _plat_of(x.get("shopRaw","")) == plat]
            if flt: c_sku[d] = flt
        c_pairs = {p for p in pairs if _plat_of(p[0]) == plat}
        c_city = city_stock if plat == "jd_self" else {}
        c_q = {"sourceFiles": sum(1 for f, p in full_file_list if p == plat),
               "parsedFiles": None,  # per-platform 精确计数不做拆分，见载入逻辑
               "emptyFiles": [x for x in q["emptyFiles"] if x.get("shop","") in [s.split("|",1)[1] for s in c_shop]]}
        blob = {"shop_rows": c_shop, "sku": c_sku, "pairs": c_pairs, "city_stock": c_city, "q": c_q}
        with open(CACHE_DIR / f"{plat}.pkl", "wb") as fh:
            pickle.dump(blob, fh, protocol=pickle.HIGHEST_PROTOCOL)
        # 指纹基于完整文件清单（含无变化平台），保证 -p 模式不覆盖其他平台指纹
        with open(CACHE_DIR / f"{plat}.fp", "wb") as fh:
            pickle.dump(_fingerprint_full(plat), fh, protocol=pickle.HIGHEST_PROTOCOL)
    # 载入未解析平台的缓存（plat_only 模式）
    if plat_only:
        for plat in PLATFORM_DIRS:
            if plat in parsed_plats: continue
            cf = CACHE_DIR / f"{plat}.pkl"
            if not cf.exists():
                raise SystemExit(f"❌ 平台 {plat} 无缓存（{cf}）。请先跑一次全量构建：python3 build_all_shop_daily.py")
            with open(cf, "rb") as fh:
                blob = pickle.load(fh)
            shop_rows.update(blob["shop_rows"])
            for d, lst in blob["sku"].items(): sku.setdefault(d, []).extend(lst)
            pairs |= blob["pairs"]
            if plat == "jd_self": city_stock.update(blob["city_stock"])
            cq = blob.get("q", {})
            q["sourceFiles"] += cq.get("sourceFiles", 0)
            q["emptyFiles"] += cq.get("emptyFiles", [])
        print(f"⚡ 增量模式：仅重新解析 [{plat_only}]，其余平台读缓存 {CACHE_DIR}")

    # ── SKU 类目/店铺归属人工改写：scripts/category_override.json ──
    #    源头为桌面 CSV（sku_override.csv，运营用 Excel 编辑），转换后入库；构建扫描 JSON 覆盖全平台明细。
    #    结构（两段式，兼容旧扁平 {SKU:[c1,c2,c3]}）：{"category": {...}, "shop": {SKU: 目标店铺名}} ──
    CAT_OVERRIDE_FILE = Path(__file__).resolve().parent / "category_override.json"
    shop_key_map = {}  # SKU -> 划入店铺 key（city_stock 落库等阶段引用；JSON 不存在时为空）
    if CAT_OVERRIDE_FILE.exists():
        try:
            _ov = json.load(open(CAT_OVERRIDE_FILE, encoding="utf-8"))
            # 兼容旧扁平格式
            cat_override = _ov.get("category", _ov if "shop" not in _ov and "category" not in _ov else {})
            shop_override = _ov.get("shop", {})
            # 店铺划转目标须已注册（同平台内划转）
            shop_key_map = {}
            for sku_id, tname in shop_override.items():
                plats = {s.split("|", 1)[0] for s in SHOP_META}
                cands = [f"{p}|{tname}" for p in plats if f"{p}|{tname}" in SHOP_META]
                if not cands:
                    print(f"⚠️  店铺划转目标未注册，忽略：SKU {sku_id} → {tname}")
                    continue
                shop_key_map[sku_id] = cands[0]
            cat_hits = shop_hits = 0
            xfer_skus = {}; xfer_src = {}  # (划入店,日期) -> 划入 SKU 集 / 来源店集
            TRANSFER_FIELDS = ["gmv", "units", "orders", "buyers", "pv", "addCartUsers",
                               "orderAmount", "orderCount", "orderBuyers", "refundAmount",
                               "gmvOutbound", "unitsOutbound", "stockValue", "out30dValue", "outMtdValue"]
            delta = {}  # (shopRaw, date) -> {field: delta}：划出店记负、划入店记正
            for d, lst in sku.items():
                for x in lst:
                    k = str(x.get("sku", "")).strip()
                    ov = cat_override.get(k)
                    if ov:
                        x["category1"], x["category2"], x["category3"] = ov[0], ov[1], ov[2]; cat_hits += 1
                    tk = shop_key_map.get(k)
                    if tk and x.get("shopRaw") != tk:
                        src = x["shopRaw"]
                        x["shopRaw"] = tk; x["shopDisplay"] = shop_display(tk); shop_hits += 1
                        xfer_skus.setdefault((tk, x["date"]), set()).add(k)          # 划入店 SKU 清单
                        xfer_src.setdefault((tk, x["date"]), set()).add(src)         # 划出来源店
                        _city_xfer = shop_key_map                                # 供落库阶段 city_stock 改写引用
                        for f in TRANSFER_FIELDS:
                            v = x.get(f) or 0
                            if v:
                                delta.setdefault((src, x["date"]), {}).setdefault(f, 0.0)
                                delta[(src, x["date"])][f] -= v
                                delta.setdefault((tk, x["date"]), {}).setdefault(f, 0.0)
                                delta[(tk, x["date"])][f] += v
            print(f"🏷️  类目改写：{len(cat_override)} 个 SKU，命中 {cat_hits} 条明细行")
            if shop_key_map:
                print(f"🏪 店铺划转：{len(shop_key_map)} 个 SKU，命中 {shop_hits} 条明细行"
                      f"（{', '.join(sorted({v.split('|',1)[1] for v in shop_key_map.values()}))}）")
            # ── 店铺行修正：按 delta 调整划出/划入店铺行；访客为店铺级去重口径不可拆分 → 不划转 ──
            moved_dates = {}
            # 划入店补齐：访客取划出源店全店值（转化率口径=源店全店，按用户约定）；skuCount 取划入 SKU 数
            for s, rows in shop_rows.items():
                for r in rows:
                    dd = delta.get((s, r["date"]))
                    if not dd: continue
                    for f, v in dd.items():
                        r[f] = (r.get(f) or 0) + v
                    calc(r)  # 重算转化率/客单价/UV价值等派生指标
                    moved_dates.setdefault(s, set()).add(r["date"])
            # 划入店（如虚拟新品类店）可能无既有店铺行 → 按 delta 补建
            tk_shops = {v for v in shop_key_map.values()}
            for (s, d), dd in delta.items():
                if s in tk_shops and not any(r["date"] == d for r in shop_rows.get(s, [])):
                    # 访客：取划出源店全店访客（转化率=源店全店口径，按约定）；skuCount=划入 SKU 数
                    srcs = xfer_src.get((s, d), set())
                    v_src = sum(next((r["visitors"] for r in shop_rows.get(src, []) if r["date"] == d), 0)
                                for src in srcs) if srcs else 0
                    x = {"date": d, "skuCount": len(xfer_skus.get((s, d), set())),
                         "sourceFile": "virtual(划转)",
                         "shopRaw": s, "shopDisplay": shop_display(s),
                         "visitors": v_src, "pv": 0, "searchImpressions": 0, "searchClicks": 0,
                         "productImpressions": 0, "productImpressionUsers": 0}
                    for f in dd: x[f] = dd[f]
                    for f in ("gmv","units","orders","buyers","pv","addCartUsers","orderAmount",
                              "orderCount","orderBuyers","refundAmount","gmvOutbound","unitsOutbound",
                              "stockValue","out30dValue","outMtdValue"):
                        x.setdefault(f, 0)
                    calc(x)
                    # 转化率/UV价值直接沿用源店全店口径（按约定：访客与转化率均取原店全店值，不按划入数据重算）
                    # 多源店时按源店访客加权平均（避免无数据源店把比率稀释为 0）
                    _src_rows = [r for src in srcs for r in shop_rows.get(src, []) if r["date"] == d]
                    _w = [r.get("visitors") or 0 for r in _src_rows]
                    if _src_rows and sum(_w) > 0:
                        x["conversion"] = sum((r.get("conversion") or 0) * w for r, w in zip(_src_rows, _w)) / sum(_w)
                        x["uvValue"] = sum((r.get("uvValue") or 0) * w for r, w in zip(_src_rows, _w)) / sum(_w)
                    elif _src_rows:
                        x["conversion"] = sum(r.get("conversion") or 0 for r in _src_rows) / len(_src_rows)
                        x["uvValue"] = sum(r.get("uvValue") or 0 for r in _src_rows) / len(_src_rows)
                    shop_rows.setdefault(s, []).append(x)
                    moved_dates.setdefault(s, set()).add(d)
            for s, ds in sorted(moved_dates.items()):
                print(f"   ↳ {SHOP_META[s][1]} 店铺行已修正/补建（{len(ds)} 天）")
        except Exception as e:
            print(f"⚠️  类目/店铺改写文件读取失败，跳过：{e}")

    dates=sorted({d for _,d in pairs})
    _pord={p:i for i,p in enumerate(PLATFORMS)}
    shops=sorted(SHOP_META,key=lambda s:(_pord.get(shop_platform(s),99), SHOP_META[s][2]))
    # 日期取各平台并集：各店铺按 (shop,date) 独立参与聚合，缺失日期自动跳过
    plat_dates={}
    for (sh,dt) in pairs: plat_dates.setdefault(shop_platform(sh), set()).add(dt)
    for plat,ds in plat_dates.items():
        print(f"📅 {PLATFORMS[plat]}: {len(ds)} 天 ({min(ds)} ~ {max(ds)})")
    if not dates:
        raise SystemExit(
            "❌ 未解析到任何数据。请检查：\n"
            f"  - 各平台数据目录是否存在且含匹配的 Excel：{ {k: str(v) for k, v in PLATFORM_DIRS.items()} }\n"
            f"  - 文件名格式须为 店铺名_商品明细_YYYY-MM-DD[_sku].xlsx\n"
            f"  - 店铺名须在 config.py 的 SHOPS 中注册（未识别的店铺: {q['unexpectedShops'][:5]}）\n"
            "  - 可用环境变量 DATA_DIR_JD / DATA_DIR_VIP 覆盖目录"
        )
    for s in shops:
        rows=sorted(shop_rows[s],key=lambda x:x["date"])
        for i,x in enumerate(rows): x["baseline"]=base(rows[max(0,i-BASELINE_WIN):i]); x["week"]=rows[i-WEEK_AGO_WIN] if i>=WEEK_AGO_WIN else None
        shop_rows[s]=rows
    overall=[]
    for date in dates:
        rows=[shop_rows[s] for s in shops if (s,date) in pairs]; cur=[]
        for rr in rows: cur.append(next(x for x in rr if x["date"]==date))
        x={"date":date,"shopCount":len(cur),"skuCount":sum(z["skuCount"] for z in cur)}
        for k in FIELDS:x[k]=sum(z[k] for z in cur)
        overall.append(calc(x))
    for i,x in enumerate(overall):x["baseline"]=base(overall[max(0,i-BASELINE_WIN):i]);x["week"]=overall[i-WEEK_AGO_WIN] if i>=WEEK_AGO_WIN else None
    cats={}; tops={}; movers={}; alerts={}
    for di,date in enumerate(dates):
        d=sku[date]
        for _x in d:
            if "gmvOutbound" not in _x or _x["gmvOutbound"] is None:
                _x["gmvOutbound"] = 0.0 if _x.get("shopRaw","").startswith("jd_self|") else None
        cat=(pd.DataFrame(d).groupby(["shopRaw","shopDisplay","category1","category2","category3"]).agg(
            gmv=("gmv","sum"),units=("units","sum"),orders=("orders","sum"),visitors=("visitors","sum"),
            addCartUsers=("addCartUsers","sum"),refundAmount=("refundAmount","sum"),skuCount=("sku","count"),gmvOutbound=("gmvOutbound","sum")).reset_index().sort_values("gmv",ascending=False))
        cat["gmvOutbound"]=cat.apply(lambda r_: None if not str(r_["shopRaw"]).startswith("jd_self|") else r_["gmvOutbound"], axis=1)
        cats[date]=cat.to_dict("records")
        ranked=sorted(d,key=lambda x:x["gmv"],reverse=True)
        top_pool=ranked[:TOP_SKU_POOL]
        for s in shops: top_pool.extend([x for x in ranked if x["shopRaw"]==s][:TOP_PER_SHOP_POOL])
        seen={(x["shopRaw"],x["sku"]) for x in top_pool}
        tops[date]=[trim_sku(x) for x in ranked if (x["shopRaw"],x["sku"]) in seen]
        if di==0: movers[date]={"risers":[],"fallers":[],"opportunities":[]}; alerts[date]=[]; continue
        prev=dates[di-1]; cm={(x["shopRaw"],x["sku"]):x for x in d}; pm={(x["shopRaw"],x["sku"]):x for x in sku[prev]}; changes=[]
        for k,x in cm.items():
            p=pm.get(k); changes.append({"shopRaw":x["shopRaw"],"shopDisplay":x["shopDisplay"],"sku":x["sku"],"name":x["name"],
                "previousGmv":p["gmv"] if p else 0,"gmv":x["gmv"],"delta":x["gmv"]-(p["gmv"] if p else 0),"visitors":x["visitors"],"conversion":x["conversion"]})
        for k,p in pm.items():
            if k not in cm: changes.append({"shopRaw":p["shopRaw"],"shopDisplay":p["shopDisplay"],"sku":p["sku"],"name":p["name"],
                "previousGmv":p["gmv"],"gmv":0,"delta":-p["gmv"],"visitors":0,"conversion":None})
        ranked_ris=sorted(changes,key=lambda x:x["delta"],reverse=True); ranked_fal=sorted(changes,key=lambda x:x["delta"])
        ris=ranked_ris[:DAILY_SHIFT_LIMIT]; fal=ranked_fal[:DAILY_SHIFT_LIMIT]
        for s in shops:
            ris.extend([x for x in ranked_ris if x["shopRaw"]==s][:DAILY_PER_SHOP])
            fal.extend([x for x in ranked_fal if x["shopRaw"]==s][:DAILY_PER_SHOP])
        ris_keys={(x["shopRaw"],x["sku"]) for x in ris}; fal_keys={(x["shopRaw"],x["sku"]) for x in fal}
        ris=[x for x in ranked_ris if (x["shopRaw"],x["sku"]) in ris_keys]
        fal=[x for x in ranked_fal if (x["shopRaw"],x["sku"]) in fal_keys]
        ov=next(x for x in overall if x["date"]==date)
        opp=sorted([x for x in d if x["visitors"]>=OPP_MIN_VISITORS and x["conversion"] is not None and ov["conversion"] is not None and x["conversion"]<ov["conversion"]*OPP_CONV_RATIO],
                   key=lambda x:x["visitors"],reverse=True)[:OPP_PER_DAY]
        movers[date]={"risers":[trim_change(x) for x in ris],"fallers":[trim_change(x) for x in fal]}
        aa=[]
        for s in shops:
            c=next((x for x in shop_rows[s] if x["date"]==date),None); p=next((x for x in shop_rows[s] if x["date"]==prev),None)
            if not c or not p: continue
            def add(level,typ,cur,pre,ch,detail): aa.append({"level":level,"scope":c["shopDisplay"],"type":typ,"current":cur,"previous":pre,"change":ch,"detail":detail})
            if p["gmv"] and c["gmv"]/p["gmv"]-1<=-.20 and p["gmv"]-c["gmv"]>=500: add("high","GMV下滑",c["gmv"],p["gmv"],c["gmv"]/p["gmv"]-1,"店铺GMV环比下降超20%且减少金额超500元")
            if p["visitors"] and c["visitors"]/p["visitors"]-1<=-.30 and p["visitors"]-c["visitors"]>=100: add("medium","流量下滑",c["visitors"],p["visitors"],c["visitors"]/p["visitors"]-1,"店铺访客数环比下降超30%且减少超100人")
            if c["conversion"] is not None and p["conversion"] is not None and c["conversion"]<p["conversion"]*.75 and p["conversion"]-c["conversion"]>=.01: add("medium","转化走弱",c["conversion"],p["conversion"],c["conversion"]-p["conversion"],"店铺成交转化率低于前日75%且下降超1个百分点")
            if c["refundRate"] is not None and c["refundRate"]>=.05 and c["refundAmount"]>=300: add("medium","退款偏高",c["refundRate"],p["refundRate"],c["refundRate"]-p["refundRate"],"店铺退款金额率达5%以上且金额超300元")
        for x in fal:
            if x["delta"]<=-500 and x["previousGmv"] and x["gmv"]/x["previousGmv"]<=.5: aa.append({"level":"sku","scope":f'{x["shopDisplay"]} / {x["name"]}',"type":"SKU大幅下滑","current":x["gmv"],"previous":x["previousGmv"],"change":x["delta"],"detail":"SKU GMV环比减少超过500元且降幅超过50%"})
        for x in opp[:OPP_PER_ALERT]: aa.append({"level":"opportunity","scope":f'{x["shopDisplay"]} / {x["name"]}',"type":"高流量低转化","current":x["conversion"],"previous":x["visitors"],"change":x["gmv"],"detail":f"访客数不低于{OPP_MIN_VISITORS}且转化率低于整体均值{int(OPP_CONV_RATIO*100)}%"})
        alerts[date]=aa[:ALERT_PER_DATE]
    complete=[d for d in dates if all((s,d) in pairs for s in shops)]
    if not complete:
        # 跨平台日期范围不一致时（如 VIP 到 28 号、JD 到 25 号），按单平台最大覆盖回退
        from collections import Counter
        cnt = Counter(d for _, d in pairs)
        max_cov = max(cnt.values())
        complete = sorted(d for d, c in cnt.items() if c == max_cov)
    expected_latest=(datetime.now().date()-timedelta(days=1)).isoformat()
    missing_dates=[]
    if dates and dates[-1] < expected_latest:
        check=datetime.fromisoformat(dates[-1]).date()
        while check < datetime.fromisoformat(expected_latest).date():
            check += timedelta(days=1); missing_dates.append(check.isoformat())
    q.update({"expectedCombinations":len(shops)*len(dates),"actualCombinations":len(pairs),"shopCount":len(shops),"dateCount":len(dates),
              "emptyFiles":q.get("emptyFiles",[]),
              "completeDateCount":len(complete),"latestCompleteDate":complete[-1],"latestAvailableDate":dates[-1],
              "missingCombinations":[{"shop":s,"date":d} for s in shops for d in dates
                                    if (s,d) not in pairs and not (SHOP_START_DATES.get(s) and d < SHOP_START_DATES[s])],
              "expectedLatestDate":expected_latest,"missingDates":missing_dates,"isFresh":not missing_dates,
              "emptyFiles":q.get("emptyFiles",[])})
    # 空文件（如 VIP 导出 0 行）也算数据不全 → 追加到 missingDates 触发前端提醒
    for ef in q.get("emptyFiles", []):
        if ef["date"] not in missing_dates:
            missing_dates.append(ef["date"])
    q["missingDates"] = sorted(missing_dates); q["isFresh"] = not q["missingDates"]
    # 图表以月度展示：默认取末行所在月
    def month_rows(rs):
        return rs if not rs else [r for r in rs if r["date"][:7]==rs[-1]["date"][:7]]
    recent_dates=dates[-RECENT_DAYS:]
    prior_dates=dates[-RESEARCH_DAYS:-RECENT_DAYS] if len(dates)>=RESEARCH_DAYS else dates[:max(0,len(dates)-RECENT_DAYS)]
    def window_rows(rows,window):
        # 店铺可能缺少部分日期（如唯品会起始日期不同），只取存在的
        have={x["date"] for x in rows}
        return [next(x for x in rows if x["date"]==date) for date in window if date in have]
    def window_summary(rows,window):
        items=window_rows(rows,window)
        summary={field:sum(x.get(field,0) for x in items) for field in FIELDS+config.SELF_FIELDS}
        return calc(summary)
    def optimization_shop(shop):
        rows=shop_rows[shop]
        recent=window_summary(rows,recent_dates); prior=window_summary(rows,prior_dates)
        return {
            "shopRaw":shop,"shopDisplay":shop_display(shop),
            "recentGmv":recent["gmv"],"priorGmv":prior["gmv"],
            "recentGmvOutbound":recent.get("gmvOutbound") if shop_platform(shop)=='jd_self' else None,
            "gmvWow":recent["gmv"]/prior["gmv"]-1 if prior["gmv"] else None,
            "recentVisitors":recent["visitors"],"priorVisitors":prior["visitors"],
            "visitorWow":recent["visitors"]/prior["visitors"]-1 if prior["visitors"] else None,
            "recentConversion":recent["conversion"],"priorConversion":prior["conversion"],
            "conversionChange":recent["conversion"]-prior["conversion"] if recent["conversion"] is not None and prior["conversion"] is not None else None,
            "recentAov":recent["aov"],"priorAov":prior["aov"],
            "aovChange":recent["aov"]-prior["aov"] if recent["aov"] is not None and prior["aov"] is not None else None,
            "recentUvValue":recent["uvValue"],"priorUvValue":prior["uvValue"],
            "uvValueChange":recent["uvValue"]-prior["uvValue"] if recent["uvValue"] is not None and prior["uvValue"] is not None else None,
            "recentRefundRate":recent["refundRate"],"priorRefundRate":prior["refundRate"],
        }
    optimization_shops=[optimization_shop(shop) for shop in shops]
    _plat_order={p:i for i,p in enumerate(PLATFORMS)}
    optimization_shops.sort(key=lambda x:(_plat_order.get(shop_platform(x["shopRaw"]),99), SHOP_META[x["shopRaw"]][2]))
    latest=dates[-1]
    concentration=[]
    for shop in shops:
        row_latest=next((x for x in shop_rows[shop] if x["date"]==latest),None)
        if row_latest is None: continue  # 该店最新日无数据（如数据缺失）
        shop_gmv=row_latest["gmv"]
        ranked=sorted([x for x in tops[latest] if x["shopRaw"]==shop],key=lambda x:x["gmv"],reverse=True)
        concentration.append({
            "shopRaw":shop,"shopDisplay":shop_display(shop),"gmv":shop_gmv,"gmvOutbound":row_latest.get("gmvOutbound") if shop_platform(shop)=='jd_self' else None,
            "top1Share":ranked[0]["gmv"]/shop_gmv if shop_gmv and ranked else 0,
            "top3Share":sum(x["gmv"] for x in ranked[:3])/shop_gmv if shop_gmv else 0,
            "top5Share":sum(x["gmv"] for x in ranked[:5])/shop_gmv if shop_gmv else 0,
            "topSku":ranked[0]["name"] if ranked else "-",
        })
    recurring={}
    research_dates=dates[-RESEARCH_DAYS:]
    for date in research_dates:
        day_overall=next(x for x in overall if x["date"]==date)
        for item in sku[date]:
            if item["visitors"]<OPP_MIN_VISITORS or item["conversion"] is None or not day_overall["conversion"]:
                continue
            if item["conversion"]>=day_overall["conversion"]*OPP_CONV_RATIO:
                continue
            key=(item["shopRaw"],item["sku"])
            state=recurring.setdefault(key,{
                "shopRaw":item["shopRaw"],"shopDisplay":item["shopDisplay"],"sku":item["sku"],
                "name":item["name"],"hitDays":0,"totalVisitors":0,"totalGmv":0,"latest":item,
            })
            state["hitDays"]+=1;state["totalVisitors"]+=item["visitors"];state["totalGmv"]+=item["gmv"]
            if date>=state.get("lastDate",""):
                state["latest"]=item;state["lastDate"]=date
    recurring_opportunities=[]
    for state in recurring.values():
        if state["hitDays"]<3:continue
        latest_item=state["latest"];last_date=state["lastDate"]
        day_overall=next(x for x in overall if x["date"]==last_date)
        overall_cart_rate=day_overall["addCartUsers"]/day_overall["visitors"] if day_overall["visitors"] else None
        item_cart_rate=latest_item["addCartUsers"]/latest_item["visitors"] if latest_item["visitors"] else None
        action="优化主图、价格与卖点承接"
        if overall_cart_rate and item_cart_rate and item_cart_rate>=overall_cart_rate*.75:
            action="检查详情页优惠、库存与下单承接"
        recurring_opportunities.append({
            "shopRaw":state["shopRaw"],"shopDisplay":state["shopDisplay"],"sku":state["sku"],
            "name":state["name"],"hitDays":state["hitDays"],"researchDays":len(research_dates),
            "totalVisitors":state["totalVisitors"],"totalGmv":state["totalGmv"],
            "latestDate":last_date,"latestVisitors":latest_item["visitors"],
            "latestConversion":latest_item["conversion"],"overallConversion":day_overall["conversion"],
            "conversionGap":day_overall["conversion"]-latest_item["conversion"],
            "latestUvValue":latest_item["gmv"]/latest_item["visitors"] if latest_item["visitors"] else None,
            "action":action,
        })
    recurring_opportunities.sort(key=lambda x:(x["hitDays"],x["totalVisitors"]),reverse=True)
    alert_counts=[len(alerts.get(date,[])) for date in dates[1:]]
    opt_platforms={}
    for plat in PLATFORMS:
        pshops=[s for s in shops if shop_platform(s)==plat]
        popt=[optimization_shop(s) for s in pshops]
        # 聚合平台级卡片（GMV/访客求和，转化/UV价值用整体序列）
        poverall=[]
        for date in dates:
            cur=[next((x for x in shop_rows[s] if x["date"]==date),None) for s in pshops]
            cur=[x for x in cur if x is not None]
            if not cur: continue
            x={"date":date,"shopCount":len(cur),"skuCount":sum(z["skuCount"] for z in cur)}
            for k in FIELDS:x[k]=sum(z[k] for z in cur)
            poverall.append(calc(x))
        for i,x in enumerate(poverall):x["baseline"]=base(poverall[max(0,i-BASELINE_WIN):i]);x["week"]=poverall[i-WEEK_AGO_WIN] if i>=WEEK_AGO_WIN else None
        opt_platforms[plat]={"overallRecent":window_summary(poverall,recent_dates),"overallPrior":window_summary(poverall,prior_dates),
                             "shops":popt,"concentration":[c for c in concentration if shop_platform(c["shopRaw"])==plat],
                             "opportunities":[o for o in recurring_opportunities if o.get("shopRaw") in pshops]}
    optimization={
        "latestDate":latest,"recentStart":recent_dates[0],"recentEnd":recent_dates[-1],
        "priorStart":prior_dates[0],"priorEnd":prior_dates[-1],
        "overallRecent":window_summary(overall,recent_dates),"overallPrior":window_summary(overall,prior_dates),
        "shops":optimization_shops,"concentration":concentration,
        "opportunities":recurring_opportunities[:OPPORTUNITIES_MAX],
        "platforms":opt_platforms,
        "averageAlertCount":sum(alert_counts)/len(alert_counts) if alert_counts else 0,
        "latestAlertCount":len(alerts.get(latest,[])),
    }
    return {"generatedAt":datetime.now().strftime("%Y-%m-%d %H:%M"),"sourceDir":"多平台导出（京东商智 + 唯品会 + 拼多多）",
            "shops":[{"raw":s,"display":shop_display(s),"brand":SHOP_META[s][1],"platform":shop_platform(s)} for s in shops],"platforms":PLATFORMS,"dates":dates,"overall":overall,
            "shopDaily":shop_rows,"categories":cats,"topSkus":tops,"movers":movers,"alerts":alerts,"quality":q,"cityStock":city_stock,
            "_shopOverride": shop_key_map,
            "optimization":optimization,
            "moduleFilters":config.MODULE_SHOPS_FILTER,
            "targets":{f"{k[0]}|{k[1]}":v for k,v in config.SHOP_TARGETS.items()}}

if __name__=="__main__":
    import argparse, math
    ap = argparse.ArgumentParser(description="多平台销售日报构建（全量 / 指定平台增量）")
    ap.add_argument("-p", "--platform", choices=sorted(PLATFORM_DIRS), default=None,
                    help="仅重新解析该平台的源文件（其余平台用上次缓存），聚合与落库仍全量重算；不传则全量构建")
    ap.add_argument("-f", "--force", action="store_true",
                    help="忽略目录指纹缓存，强制重新解析全部源文件（源数据被原地修改/排查缓存问题时使用）")
    args = ap.parse_args()
    def _denan(o):
        if isinstance(o,dict): return {k:_denan(v) for k,v in o.items()}
        if isinstance(o,list): return [_denan(v) for v in o]
        if isinstance(o,float) and not math.isfinite(o): return None
        return o
    data=build(plat_only=args.platform, force=args.force)
    data=_denan(data)
    slim_keys=["gmv","units","orders","buyers","visitors","conversion","aov","uvValue","addCartUsers","refundRate"]
    all_rows=list(data["overall"])
    for rows in data["shopDaily"].values(): all_rows.extend(rows)
    for row in all_rows:
        row.pop("sourceFile",None)
        if row.get("baseline"): row["baseline"]={k:row["baseline"][k] for k in slim_keys if row["baseline"].get(k) is not None}
        if row.get("week"): row["week"]={k:row["week"][k] for k in slim_keys if row["week"].get(k) is not None}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload=json.dumps(data,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    # ① 输出轻量版 HTML（从 /api/data 加载数据，供 Vercel 部署）
    html = TEMPLATE.read_text(encoding="utf-8")
    # 首页模块排布顺序：读 scripts/section_order.json（格式 ["模块ID | 中文名", ...]，按行序排列）；
    # 缺省/损坏时保持模板默认；未列出的模块排在最后
    try:
        _so = json.loads((TEMPLATE.parent.parent / "scripts" / "section_order.json").read_text(encoding="utf-8"))
        _ids = [str(x).split("|")[0].strip() for x in _so if str(x).strip()]
        _order = json.dumps(_ids, ensure_ascii=False).replace('"', '\\"')
    except Exception:
        _order = "[]"
    html = html.replace("__SECTION_ORDER__", _order)
    OUT.write_text(html, encoding="utf-8")
    # ④ 写入 DuckDB 数据库（Vercel serverless function 运行时读取）
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("CREATE TABLE meta (key VARCHAR PRIMARY KEY, value VARCHAR)")
        con.execute("CREATE TABLE quality (key VARCHAR PRIMARY KEY, value VARCHAR)")
        con.execute("CREATE TABLE overall (date VARCHAR PRIMARY KEY, shop_count BIGINT, sku_count BIGINT, gmv DOUBLE, units BIGINT, orders BIGINT, buyers BIGINT, visitors BIGINT, conversion DOUBLE, aov DOUBLE, uv_value DOUBLE, add_cart_users BIGINT, refund_amount DOUBLE, refund_rate DOUBLE, baseline VARCHAR, week VARCHAR)")
        con.execute("CREATE TABLE shop_daily (date VARCHAR, shop VARCHAR, sku_count BIGINT, gmv DOUBLE, units BIGINT, orders BIGINT, buyers BIGINT, visitors BIGINT, conversion DOUBLE, aov DOUBLE, uv_value DOUBLE, refund_amount DOUBLE, refund_rate DOUBLE, baseline VARCHAR, week VARCHAR, gmv_outbound DOUBLE, units_outbound BIGINT, stock_value DOUBLE, out30d_value DOUBLE, out_mtd_value DOUBLE, PRIMARY KEY(date, shop))")
        con.execute("CREATE TABLE categories (date VARCHAR, path VARCHAR, l1 VARCHAR, l2 VARCHAR, l3 VARCHAR, gmv DOUBLE, units BIGINT, orders BIGINT, sku_count BIGINT, visitors BIGINT, refund_amount DOUBLE, gmv_outbound DOUBLE)")
        con.execute("CREATE TABLE city_stock (date VARCHAR, shop VARCHAR, sku VARCHAR, name VARCHAR, city VARCHAR, stock DOUBLE, daily_avg DOUBLE, days_cover DOUBLE, out_yesterday DOUBLE, out_7d DOUBLE, nat_stock DOUBLE, nat_days_cover DOUBLE, nat_transit DOUBLE, nat_out_yesterday DOUBLE, nat_out_7d DOUBLE, price DOUBLE)")
        con.execute("CREATE TABLE top_skus (date VARCHAR, shop VARCHAR, sku VARCHAR, name VARCHAR, gmv DOUBLE, units BIGINT, visitors BIGINT, conversion DOUBLE, uv_value DOUBLE, refund_amount DOUBLE, gmv_outbound DOUBLE)")
        con.execute("CREATE TABLE movers (date VARCHAR, type VARCHAR, shop VARCHAR, sku VARCHAR, name VARCHAR, previous_gmv DOUBLE, gmv DOUBLE, delta DOUBLE)")
        con.execute("CREATE TABLE alerts (date VARCHAR, level VARCHAR, scope VARCHAR, type VARCHAR, detail VARCHAR, current DOUBLE, previous DOUBLE, change DOUBLE)")
        con.execute("CREATE TABLE optimization (key VARCHAR PRIMARY KEY, value VARCHAR)")
        # meta
        con.execute(f"INSERT INTO meta VALUES ('generatedAt', '{data['generatedAt']}')")
        con.execute(f"INSERT INTO meta VALUES ('sourceDir', '{data['sourceDir']}')")
        con.execute(f"INSERT INTO meta VALUES ('shops', '{json.dumps(data['shops'], ensure_ascii=False).replace(chr(39), chr(92)+chr(39))}')")
        con.execute(f"INSERT INTO meta VALUES ('platforms', '{json.dumps(data['platforms'], ensure_ascii=False)}')")
        con.execute(f"INSERT INTO meta VALUES ('dates', '{json.dumps(data['dates'], ensure_ascii=False).replace(chr(39), chr(92)+chr(39))}')")
        con.execute(f"INSERT INTO meta VALUES ('moduleFilters', '{json.dumps(data.get('moduleFilters', {}), ensure_ascii=False).replace(chr(39), chr(92)+chr(39))}')")
        con.execute(f"INSERT INTO meta VALUES ('targets', '{json.dumps(data.get('targets', {}), ensure_ascii=False).replace(chr(39), chr(92)+chr(39))}')")
        # quality
        for k, v in data["quality"].items():
            if isinstance(v, (int, float)):
                con.execute(f"INSERT INTO quality VALUES ('{k}', '{v}')")
            elif isinstance(v, bool):
                con.execute(f"INSERT INTO quality VALUES ('{k}', '{str(v).lower()}')")
            else:
                sv = json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)
                con.execute(f"INSERT INTO quality VALUES ('{k}', '{sv.replace(chr(39), chr(92)+chr(39))}')")
        # overall
        for r in data["overall"]:
            bl = json.dumps(r.get("baseline"), ensure_ascii=False) if r.get("baseline") else None
            wk = json.dumps(r.get("week"), ensure_ascii=False) if r.get("week") else None
            bl_s = f"'{bl.replace(chr(39), chr(92)+chr(39))}'" if bl else "NULL"
            wk_s = f"'{wk.replace(chr(39), chr(92)+chr(39))}'" if wk else "NULL"
            con.execute(f"INSERT INTO overall VALUES ('{r['date']}', {r.get('shopCount',0)}, {r.get('skuCount',0)}, {r.get('gmv',0)}, {r.get('units',0)}, {r.get('orders',0)}, {r.get('buyers',0)}, {r.get('visitors',0)}, {sqlnum(r.get('conversion'))}, {sqlnum(r.get('aov'))}, {sqlnum(r.get('uvValue'))}, {r.get('addCartUsers',0)}, {r.get('refundAmount',0)}, {sqlnum(r.get('refundRate'))}, {bl_s}, {wk_s})")
        # shop_daily
        shop_daily_keys = set()
        for shop, rows in data["shopDaily"].items():
            for r in rows:
                # 数据源异常防护：同店铺同日期多行（如 JITX 多文件日期重叠），明确报错而非静默写入脏数据
                if (r["date"], r["shopRaw"]) in shop_daily_keys:
                    raise SystemExit(f"❌ 数据源异常：店铺 {r['shopRaw']} 在 {r['date']} 出现重复数据（多文件日期重叠），请检查导出文件命名与内容是否一致")
                shop_daily_keys.add((r["date"], r["shopRaw"]))
                bl = json.dumps(r.get("baseline"), ensure_ascii=False) if r.get("baseline") else None
                wk = json.dumps(r.get("week"), ensure_ascii=False) if r.get("week") else None
                bl_s = f"'{bl.replace(chr(39), chr(92)+chr(39))}'" if bl else "NULL"
                wk_s = f"'{wk.replace(chr(39), chr(92)+chr(39))}'" if wk else "NULL"
                con.execute(f"INSERT INTO shop_daily VALUES ('{r['date']}', '{r['shopRaw']}', {r.get('skuCount',0)}, {r.get('gmv',0)}, {r.get('units',0)}, {r.get('orders',0)}, {r.get('buyers',0)}, {r.get('visitors',0)}, {sqlnum(r.get('conversion'))}, {sqlnum(r.get('aov'))}, {sqlnum(r.get('uvValue'))}, {r.get('refundAmount',0)}, {sqlnum(r.get('refundRate'))}, {bl_s}, {wk_s}, {sqlnum(r.get('gmvOutbound'))}, {sqlnum(r.get('unitsOutbound'))}, {sqlnum(r.get('stockValue'))}, {sqlnum(r.get('out30dValue'))}, {sqlnum(r.get('outMtdValue'))})")
        # categories
        for date, rows in data["categories"].items():
            for r in rows:
                p = r["shopRaw"] + "/" + r["category3"]   # 用内部 key（平台|店铺名），供前端按平台过滤
                p_esc = p.replace(chr(39), chr(92)+chr(39))
                l1_esc = r["category1"].replace(chr(39), chr(92)+chr(39))
                l2_esc = r["category2"].replace(chr(39), chr(92)+chr(39))
                l3_esc = r["category3"].replace(chr(39), chr(92)+chr(39))
                visitors = int(r.get('visitors',0)) if r.get('visitors') is not None else 0
                gmv_val = r.get('gmv',0) if r.get('gmv') is not None else 0
                refund = r.get('refundAmount',0) if r.get('refundAmount') is not None else 0
                con.execute(f"INSERT INTO categories VALUES ('{date}', '{p_esc}', '{l1_esc}', '{l2_esc}', '{l3_esc}', {sqlnum(gmv_val) if gmv_val else 0}, {int(r.get('units',0) or 0)}, {int(r.get('orders',0) or 0)}, {int(r.get('skuCount',0) or 0)}, {visitors}, {refund if refund is not None else 0}, {sqlnum(r.get('gmvOutbound'))})")
        # city_stock（划转 SKU 的城市库存行归属划入店——店铺划转口径）
        _cx = data.get("_shopOverride") or {}
        for date, shops_cs in data.get("cityStock", {}).items():
            for shop, cs in shops_cs.items():
                for r in cs["rows"]:
                    _sku = str(r["sku"]).strip()
                    _tk = _cx.get(_sku)
                    key = _tk if (_tk and _tk in SHOP_META) else f"jd_self|{shop}"
                    if key not in SHOP_META: continue
                    name_esc=str(r["name"]).replace(chr(39), chr(92)+chr(39))
                    con.execute(f"INSERT INTO city_stock VALUES ('{date}', '{key}', '{r['sku']}', '{name_esc}', '{r['city']}', {r['stock']}, {r['dailyAvg']}, {r['daysCover'] if r['daysCover'] is not None else 'NULL'}, {r['outYesterday']}, {r['out7d']}, {r['natStock']}, {r['natDaysCover'] if r['natDaysCover'] is not None else 'NULL'}, {r.get('natTransit', 0)}, {r.get('natOutYesterday', 0)}, {r.get('natOut7d', 0)}, {r['price']})")

        # top_skus
        for date, rows in data["topSkus"].items():
            for r in rows:
                name_esc = r["name"].replace(chr(39), chr(92)+chr(39))
                conv = sqlnum(r.get('conversion'))
                uvv = sqlnum(r.get('uvValue'))
                con.execute(f"INSERT INTO top_skus VALUES ('{date}', '{r['shopRaw']}', '{r['sku']}', '{name_esc}', {r['gmv'] if r['gmv'] is not None else 0}, {int(r['units'] or 0)}, {int(r['visitors'] or 0)}, {conv}, {uvv}, {r['refundAmount'] if r.get('refundAmount') is not None else 0}, {sqlnum(r.get('gmvOutbound'))})")
        # movers
        for date, mv in data["movers"].items():
            for r in mv.get("risers", []):
                name_esc = r["name"].replace(chr(39), chr(92)+chr(39))
                con.execute(f"INSERT INTO movers VALUES ('{date}', 'riser', '{r['shopRaw']}', '{r['sku']}', '{name_esc}', {sqlnum(r.get('previousGmv'))}, {sqlnum(r.get('gmv'))}, {sqlnum(r.get('delta'))})")
            for r in mv.get("fallers", []):
                name_esc = r["name"].replace(chr(39), chr(92)+chr(39))
                con.execute(f"INSERT INTO movers VALUES ('{date}', 'faller', '{r['shopRaw']}', '{r['sku']}', '{name_esc}', {sqlnum(r.get('previousGmv'))}, {sqlnum(r.get('gmv'))}, {sqlnum(r.get('delta'))})")
        # alerts
        for date, aa in data["alerts"].items():
            for a in aa:
                detail_esc = a["detail"].replace(chr(39), chr(92)+chr(39))
                scope_esc = a["scope"].replace(chr(39), chr(92)+chr(39))
                con.execute(f"INSERT INTO alerts VALUES ('{date}', '{a['level']}', '{scope_esc}', '{a['type']}', '{detail_esc}', {sqlnum(a.get('current'))}, {sqlnum(a.get('previous'))}, {sqlnum(a.get('change'))})")
        # optimization
        opt_flat = {}
        def _flatten(d, p=""):
            for k, v in d.items():
                if isinstance(v, dict):
                    _flatten(v, f"{p}.{k}" if p else k)
                else:
                    opt_flat[f"{p}.{k}" if p else k] = v
        _flatten(data["optimization"])
        for k, v in opt_flat.items():
            if isinstance(v, (list, dict)):
                sv = json.dumps(v, ensure_ascii=False).replace(chr(39), chr(92)+chr(39))
            else:
                sv = str(v).replace(chr(39), chr(92)+chr(39))
            con.execute(f"INSERT INTO optimization VALUES ('{k}', '{sv}')")
        pass  # DuckDB auto-commits
    finally:
        con.close()
    latest=next(x for x in data["overall"] if x["date"]==data["quality"]["latestAvailableDate"])
    # 同步数据库到函数读取位置（api/report.duckdb，随 @vercel/python 打包）
    api_db = DB_PATH.parent.parent / "report.duckdb"
    if api_db != DB_PATH:
        import shutil
        shutil.copy2(DB_PATH, api_db)
        print(f"同步: {api_db}")
    print(OUT); print(json.dumps(data["quality"],ensure_ascii=False,indent=2))
    print(f"latest={latest['date']} gmv={latest['gmv']:.2f} html_size={OUT.stat().st_size} db_size={config.DB_PATH.stat().st_size}")
    _bark_notify(data)
