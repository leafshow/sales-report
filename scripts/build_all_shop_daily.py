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
SHOPS    = config.SHOPS
SHOP_META     = {f"{k[0]}|{k[1]}": v for k, v in config.SHOPS_VISIBLE.items()}   # 内部唯一 key = 平台|店铺名（仅可见店铺）
SHOP_PLATFORM = {f"{k[0]}|{k[1]}": k[0] for k in SHOPS}
HIDDEN_SHOPS  = config.HIDDEN_SHOPS   # 隐藏店铺：仍解析入库存数据，但不参与聚合与展示
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

SELF_FIELDS   = config.SELF_FIELDS

HEAD_CITY_LIMIT = 20   # 头部 SKU 数量（按昨日出库件数）
MAIN_CITIES = ["北京", "上海", "广州", "成都", "武汉", "沈阳", "西安"]

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
    df=pd.read_excel(path, usecols=[c for c in need if c in head.columns])
    if len(df)==0 or out_col not in df.columns:
        return {}
    for c in df.columns:
        if c not in ("SKU","商品名称","店铺名称"):
            df[c]=pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["_shop"]=df["店铺名称"].fillna("未分配").astype(str).str.strip()
    result={}
    for shop,g in df.groupby("_shop"):
        top=g.nlargest(HEAD_CITY_LIMIT,out_col)
        rows=[]
        for _,r in top.iterrows():
            avg7=float(r.get(w7_col,0))/7.0
            nat_stock=float(r.get("全国现货库存",0) or 0)
            nat_days=round(nat_stock/avg7,1) if avg7>0 else None
            for city,col in stock_cols.items():
                st=float(r[col])
                days=round(st/avg7,1) if avg7>0 else None
                rows.append({"sku":str(r["SKU"]),"name":t(r["商品名称"]),"city":city,
                             "stock":st,"dailyAvg":round(avg7,1),"daysCover":days,
                             "outYesterday":float(r.get(out_col,0) or 0),
                             "out7d":float(r.get(w7_col,0) or 0),
                             "natStock":nat_stock,"natDaysCover":nat_days,
                             "price":float(r.get("全国采购价",0) or 0)})
        if rows:
            result[shop]={"date":date,"rows":rows}
    return result

def jdself_inventory_metrics(path, date):
    """解析京东自营库存表（供货口径），返回 {店铺名: {gmvOutbound, unitsOutbound, stockValue, out30dValue, skus: [...]}}"""
    # 列名兼容：新导出（10 月起）省略「全国」前缀（现货库存/昨日出库商品件数/近30日出库商品件数）
    df = pd.read_excel(path, nrows=0)
    ALIAS = {"全国现货库存": "现货库存", "全国昨日出库商品件数": "昨日出库商品件数",
             "全国近30日出库商品件数": "近30日出库商品件数"}
    colmap = {}
    for full, short in ALIAS.items():
        if full not in df.columns and short in df.columns:
            colmap[full] = short
    if colmap:
        base = ["SKU", "商品名称", "店铺名称", "一级类目", "二级类目", "三级类目", "全国采购价"]
        df = pd.read_excel(path, usecols=base + list(colmap.values()))
        df = df.rename(columns={v: k for k, v in colmap.items()})
    else:
        df = pd.read_excel(path, usecols=["SKU", "商品名称", "店铺名称", "一级类目", "二级类目",
                                           "三级类目", "全国采购价", "全国昨日出库商品件数",
                                           "全国现货库存", "全国近30日出库商品件数"])
    if len(df) == 0:
        return {}
    price = pd.to_numeric(df["全国采购价"], errors="coerce").fillna(0.0)
    out_d = pd.to_numeric(df["全国昨日出库商品件数"], errors="coerce").fillna(0.0)
    stock = pd.to_numeric(df["全国现货库存"], errors="coerce").fillna(0.0)
    out30 = pd.to_numeric(df["全国近30日出库商品件数"], errors="coerce").fillna(0.0)
    df["_gmvOut"] = price * out_d
    df["_unitsOut"] = out_d
    df["_stockVal"] = price * stock
    df["_out30Val"] = price * out30
    df["_shop"] = df["店铺名称"].fillna("未分配").astype(str).str.strip()
    result = {}
    for shop, g in df.groupby("_shop"):
        skus = [{"_date": date, "sku": str(s["SKU"]), "name": t(s["商品名称"]), "shop": shop,
                 "category1": t(s["一级类目"]), "category2": t(s["二级类目"]), "category3": t(s["三级类目"]),
                 "gmv": float(s["_gmvOut"]), "gmvOutbound": float(s["_gmvOut"]), "units": int(s["_unitsOut"]), "orders": 0,
                 "buyers": 0, "visitors": 0, "searchImpressions": 0, "searchClicks": 0, "addCartUsers": 0,
                 "refundAmount": 0.0, "conversion": None, "uvValue": None}
                for _, s in g.iterrows()]
        result[shop] = {"gmvOutbound": float(g["_gmvOut"].sum()), "unitsOutbound": int(g["_unitsOut"].sum()),
                        "stockValue": float(g["_stockVal"].sum()), "out30dValue": float(g["_out30Val"].sum()),
                        "skus": skus}
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
    return {k:x.get(k,0) for k in keys}

def trim_change(x):
    keys = ["shopRaw","shopDisplay","sku","name","previousGmv","gmv","delta"]
    return {k:x[k] for k in keys}

def svg_gmv_chart(rows):
    if not rows:
        return "<div class=callout>暂无GMV趋势数据。</div>"
    width,height,left,right,top,bottom=980,320,58,18,22,56
    plot_w,plot_h=width-left-right,height-top-bottom
    values=[x["gmv"] for x in rows]; max_value=max(values)*1.12 or 1
    slot=plot_w/len(rows); bar_width=min(28,slot*.62)
    def x(i): return left+i*slot+slot/2
    def y(v): return top+(1-v/max_value)*plot_h
    grid=[]
    for tick in [0,.25,.5,.75,1]:
        value=max_value*tick; yy=y(value)
        grid.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" stroke="#e5eaf2"/><text x="{left-8}" y="{yy+4:.1f}" text-anchor="end" class=sl>¥{value/10000:.1f}万</text>')
    bars=[]
    for i,row in enumerate(rows):
        value=row["gmv"]; xx=x(i)-bar_width/2; yy=y(value); bar_h=max(2,plot_h-(yy-top)); selected=" selected" if row["date"]==rows[-1]["date"] else ""
        label=f'{row["date"]}：¥{value:,.2f}'
        bars.append(f'<rect class="chart-bar{selected}" data-date="{row["date"]}" x="{xx:.1f}" y="{yy:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" rx="4" fill="#1657ff"><title>{label}</title></rect>')
        if i%2==0:
            bars.append(f'<text class=sl x="{x(i):.1f}" y="{height-18}" text-anchor="middle">{row["date"][5:]}</text>')
    latest=max(rows,key=lambda z:z["date"]); lx=x(rows.index(latest)); ly=y(latest["gmv"])
    marker=f'<text class="chart-marker selected" data-date="{latest["date"]}" x="{lx:.1f}" y="{ly-10:.1f}" text-anchor="middle">¥{latest["gmv"]/10000:.1f}万</text>'
    return f'<svg class=chart-svg viewBox="0 0 {width} {height}" role="img" aria-label="每日GMV趋势柱状图"><text class=sl x="{left}" y="14">GMV</text>{"".join(grid)}{"".join(bars)}{marker}</svg>'

def svg_conversion_chart(rows):
    if not rows:
        return "<div class=callout>暂无转化率趋势数据。</div>"
    width,height,left,right,top,bottom=980,300,52,20,22,50
    plot_w,plot_h=width-left-right,height-top-bottom
    rows=[x for x in rows if x.get("conversion") is not None]   # 剔除无转化率数据
    values=[x["conversion"] for x in rows]
    if not values:return "<div class=callout>暂无转化率数据（该平台未提供流量/转化指标）。</div>"
    vmin,vmax=min(values),max(values); padding=(vmax-vmin or vmax or .01)*.22
    y0=max(0,vmin-padding); y1=vmax+padding
    def x(i): return left+i*plot_w/max(1,len(rows)-1)   # 单日数据时收敛为单点，避免除零
    def y(v): return top+(1-(v-y0)/(y1-y0))*plot_h
    grid=[]
    for tick in [0,.25,.5,.75,1]:
        value=y0+tick*(y1-y0); yy=y(value)
        grid.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" stroke="#e5eaf2"/><text x="{left-8}" y="{yy+4:.1f}" text-anchor="end" class=sl>{value*100:.1f}%</text>')
    points=[]
    for i,row in enumerate(rows):
        if row.get("conversion") is None: continue
        xx,yy=x(i),y(row["conversion"]); selected=" selected" if row["date"]==rows[-1]["date"] else ""
        points.append(f'<circle class="chart-point{selected}" data-date="{row["date"]}" cx="{xx:.1f}" cy="{yy:.1f}" r="4" fill="#1657ff" stroke="#fff" stroke-width="2"><title>{row["date"]}：{row["conversion"]*100:.2f}%</title></circle>')
        if i%2==0:points.append(f'<text class=sl x="{xx:.1f}" y="{height-14}" text-anchor="middle">{row["date"][5:]}</text>')
    path=" ".join(("M" if i==0 else "L")+f'{x(i):.1f},{y(row["conversion"]):.1f}' for i,row in enumerate(rows) if row.get("conversion") is not None)
    latest=max(rows,key=lambda z:z["date"]); lx,ly=x(rows.index(latest)),y(latest["conversion"])
    marker=f'<text class="chart-marker selected" data-date="{latest["date"]}" x="{lx:.1f}" y="{ly-12:.1f}" text-anchor="middle">{latest["conversion"]*100:.2f}%</text>'
    return f'<svg class=chart-svg viewBox="0 0 {width} {height}" role="img" aria-label="每日成交转化率趋势折线图"><text class=sl x="{left}" y="14">成交转化率</text>{"".join(grid)}<path d="{path}" fill="none" stroke="#1657ff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>{"".join(points)}{marker}</svg>'

def build():
    # 收集各平台文件：[(path, platform)]
    file_list=[]
    for plat, pdir in PLATFORM_DIRS.items():
        if pdir.exists():
            if plat == "pdd":
                file_list.extend((f, plat) for f in sorted(pdir.glob("*.csv")) if FILE_RE_PDD.match(f.name))
            elif plat == "jd_self":
                # 排除 Excel 锁文件 ~$xxx.xlsx；库存表 + 流量表双源
                for f in sorted(pdir.glob("*.xlsx")):
                    if f.name.startswith("~$"): continue
                    if FILE_RE_JD_SELF.match(f.name) or FILE_RE_JD_SELF_TRAFFIC.match(f.name):
                        file_list.append((f, plat))
            else:
                file_list.extend((f, plat) for f in sorted(pdir.glob("*.xlsx")) if FILE_RE.match(f.name))
        else:
            print(f"⚠️  平台 {plat} 数据目录不存在: {pdir}")
    file_list.sort(key=lambda x: x[0].name)
    q={"sourceFiles":len(file_list),"parsedFiles":0,"schemaOk":True,"totalRowsOk":True,
        "duplicateSkuCount":0,"reconciliationOk":True,"unexpectedShops":[],"windowFiles":[],"emptyFiles":[]}
    shop_rows={s:[] for s in SHOP_META}; sku={}; pairs=set()
    jd_self_files=defaultdict(list)  # date -> [(kind, path)]
    
    # 第一轮：其他平台 + 记录 jd_self 文件按日期分组
    for f, plat in file_list:
        if plat == "jd_self":
            m_inv = FILE_RE_JD_SELF.match(f.name)
            m_traf = FILE_RE_JD_SELF_TRAFFIC.match(f.name)
            if m_inv:
                jd_self_files[m_inv.group(2)].append(("inventory", f))
            elif m_traf:
                jd_self_files[m_traf.group(2)].append(("traffic", f))
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
                q.setdefault("emptyFiles", []).append({"shop": raw_shop, "date": date, "file": f.name}); continue
            q["parsedFiles"]+=1
            pairs.add((key,date))
            row_p["shopRaw"]=key; row_p["shopDisplay"]=shop_display(key)
            shop_rows[key].append(row_p)
            for sk in skus_p:
                sk.update({"date":date,"shopRaw":key,"shopDisplay":shop_display(key)})
                sku.setdefault(date,[]).append(sk)
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
                q.setdefault("emptyFiles", []).append({"shop": shop, "date": date, "file": f.name}); continue
            q["parsedFiles"]+=1; pairs.add((shop,date))
            totals={c: df[c].sum() for c in ("销售额","销售量","客户数","商详UV")}
            shop_rows[shop].append(vip_total_row(date,shop,totals,len(df),f.name)); sku.setdefault(date,[]).extend(vip_sku_rows(date,shop,df))
        else:
            missing=[c for c in COLUMNS if c not in df.columns]
            if missing: raise RuntimeError(f"{f.name} missing {missing}")
            if len(df)<2 or t(df.iloc[0]["SKU"])!="合计": raise RuntimeError(f"{f.name} missing total row")
            total=df.iloc[0]; detail=df.iloc[1:]
            q["parsedFiles"]+=1; pairs.add((shop,date)); q["duplicateSkuCount"]+=int(detail["SKU"].astype(str).duplicated().sum())
            ok=abs(n(total["成交金额"])-sum(n(x) for x in detail["成交金额"]))<=max(.01,abs(n(total["成交金额"]))*.001)
            ok2=abs(n(total["成交商品件数"])-sum(n(x) for x in detail["成交商品件数"]))<=max(.01,abs(n(total["成交商品件数"]))*.001)
            q["reconciliationOk"] &= ok and ok2
            shop_rows[shop].append(total_row(date,shop,total,len(detail),f.name)); sku.setdefault(date,[]).extend(sku_rows(date,shop,detail))

    # ── jd_self：按 (日期) 聚合库存表 + 经营状况表，合并为唯一一行 ──
    city_stock={}
    for date, entries in sorted(jd_self_files.items()):
        inv={}; traf={}
        for kind, f in entries:
            if kind == "inventory":
                inv = jdself_inventory_metrics(f, date)  # 同日多份时后者覆盖（正常仅一份）
                try:
                    cs=jdself_city_stock(f, date)
                    if cs: city_stock[date]=cs
                except Exception as e:
                    print(f"⚠️  城市库存解析失败 {f.name}: {e}")
            else:
                tr = jdself_traffic_metrics(f, date)
                if tr is None:
                    # 窗口累计文件（时间列含「至」），跳过并记录
                    q.setdefault("windowFiles", []).append({"date": date, "file": f.name})
                    continue
                traf = tr
            q["parsedFiles"]+=1
        all_shops = set(inv) | set(traf)
        for shop_name in sorted(all_shops):
            key=f"jd_self|{shop_name}"
            if key not in SHOP_META:
                q["unexpectedShops"].append(f"jd_self:{shop_name}"); continue
            i = inv.get(shop_name, {}); tr = traf.get(shop_name, {})
            x = {"date": date, "skuCount": tr.get("skuCount", i.get("skuCount", 0)),
                 "sourceFile": (tr.get("sourceFile") or i.get("sourceFile") or ""),
                 # 零售口径（经营状况表）：有则用，无则 0
                 "gmv": float(tr.get("gmv", 0.0)), "units": int(tr.get("units", 0)),
                 "orders": int(tr.get("orders", 0)), "buyers": int(tr.get("buyers", 0)),
                 "visitors": int(tr.get("visitors", 0)), "pv": int(tr.get("pv", 0)),
                 "addCartUsers": int(tr.get("addCartUsers", 0)),
                 # 供货口径（库存表）：有则用，无则 0
                 "gmvOutbound": float(i.get("gmvOutbound", 0.0)),
                 "unitsOutbound": int(i.get("unitsOutbound", 0)),
                 "stockValue": float(i.get("stockValue", 0.0)),
                 "out30dValue": float(i.get("out30dValue", 0.0)),
                 # 框架其他字段补 0
                 "searchImpressions": 0, "searchClicks": 0,
                 "productImpressions": 0, "productImpressionUsers": 0,
                 "orderAmount": float(tr.get("gmv", 0.0)), "orderCount": int(tr.get("orders", 0)),
                 "orderBuyers": int(tr.get("buyers", 0)), "refundAmount": 0.0}
            pairs.add((key,date))
            x["shopRaw"]=key; x["shopDisplay"]=shop_display(key)
            shop_rows[key].append(calc(x))
            # SKU 层：库存 SKU + 流量 SKU，按 (shop, sku) 合并——成交/流量字段取流量表，供货字段取库存表
            merged={}
            for src in (i.get("skus", []), tr.get("skus", [])):
                for sk in src:
                    sid=str(sk["sku"])
                    if sid in merged:
                        merged[sid].update({k:v for k,v in sk.items() if v not in (0, 0.0, None)}) 
                    else:
                        merged[sid]=dict(sk)
            for sid, sk in merged.items():
                sk.pop("shop", None)
                sk.update({"date":date,"shopRaw":key,"shopDisplay":shop_display(key)})
                sku.setdefault(date,[]).append(sk)
    dates=sorted({d for _,d in pairs}); shops=sorted(SHOP_META,key=lambda s:SHOP_META[s][2])
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
        for _x in d: _x.setdefault("gmvOutbound",0.0)
        cat=(pd.DataFrame(d).groupby(["shopRaw","shopDisplay","category1","category2","category3"]).agg(
            gmv=("gmv","sum"),units=("units","sum"),orders=("orders","sum"),visitors=("visitors","sum"),
            addCartUsers=("addCartUsers","sum"),refundAmount=("refundAmount","sum"),skuCount=("sku","count"),gmvOutbound=("gmvOutbound","sum")).reset_index().sort_values("gmv",ascending=False))
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
              "missingCombinations":[{"shop":s,"date":d} for s in shops for d in dates if (s,d) not in pairs],
              "expectedLatestDate":expected_latest,"missingDates":missing_dates,"isFresh":not missing_dates,
              "emptyFiles":q.get("emptyFiles",[])})
    # 空文件（如 VIP 导出 0 行）也算数据不全 → 追加到 missingDates 触发前端提醒
    for ef in q.get("emptyFiles", []):
        if ef["date"] not in missing_dates:
            missing_dates.append(ef["date"])
    q["missingDates"] = sorted(missing_dates); q["isFresh"] = not q["missingDates"]
    charts={"ALL":{"gmv":svg_gmv_chart(overall),"conversion":svg_conversion_chart(overall)}}
    # 按平台聚合图表（前端平台切换时使用）
    for plat in PLATFORMS:
        plat_shops=[s for s in shops if shop_platform(s)==plat]
        plat_overall=[]
        for date in dates:
            cur=[next((x for x in shop_rows[s] if x["date"]==date),None) for s in plat_shops]
            cur=[x for x in cur if x is not None]
            if not cur: continue
            x={"date":date,"shopCount":len(cur),"skuCount":sum(z["skuCount"] for z in cur)}
            for k in FIELDS:x[k]=sum(z[k] for z in cur)
            plat_overall.append(calc(x))
        charts[plat]={"gmv":svg_gmv_chart(plat_overall),"conversion":svg_conversion_chart(plat_overall)}
    for shop in shops:
        charts[shop]={"gmv":svg_gmv_chart(shop_rows[shop]),"conversion":svg_conversion_chart(shop_rows[shop])}
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
            "recentGmvOutbound":recent.get("gmvOutbound",0.0),
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
    optimization_shops.sort(key=lambda x:abs(x["recentGmv"]-x["priorGmv"]),reverse=True)
    latest=dates[-1]
    concentration=[]
    for shop in shops:
        row_latest=next((x for x in shop_rows[shop] if x["date"]==latest),None)
        if row_latest is None: continue  # 该店最新日无数据（如数据缺失）
        shop_gmv=row_latest["gmv"]
        ranked=sorted([x for x in tops[latest] if x["shopRaw"]==shop],key=lambda x:x["gmv"],reverse=True)
        concentration.append({
            "shopRaw":shop,"shopDisplay":shop_display(shop),"gmv":shop_gmv,"gmvOutbound":row_latest.get("gmvOutbound",0.0),
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
            "shopDaily":shop_rows,"categories":cats,"topSkus":tops,"movers":movers,"alerts":alerts,"quality":q,"charts":charts,"cityStock":city_stock,
            "optimization":optimization}

if __name__=="__main__":
    data=build()
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
    html = html.replace("__GMV_CHART__", data["charts"]["ALL"]["gmv"])
    html = html.replace("__CONV_CHART__", data["charts"]["ALL"]["conversion"])
    OUT.write_text(html, encoding="utf-8")
    # ④ 写入 DuckDB 数据库（Vercel serverless function 运行时读取）
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute("CREATE TABLE meta (key VARCHAR PRIMARY KEY, value VARCHAR)")
        con.execute("CREATE TABLE quality (key VARCHAR PRIMARY KEY, value VARCHAR)")
        con.execute("CREATE TABLE charts (schema_key VARCHAR, chart_type VARCHAR, svg_text VARCHAR, PRIMARY KEY(schema_key, chart_type))")
        con.execute("CREATE TABLE overall (date VARCHAR PRIMARY KEY, shop_count BIGINT, sku_count BIGINT, gmv DOUBLE, units BIGINT, orders BIGINT, buyers BIGINT, visitors BIGINT, conversion DOUBLE, aov DOUBLE, uv_value DOUBLE, add_cart_users BIGINT, refund_amount DOUBLE, refund_rate DOUBLE, baseline VARCHAR, week VARCHAR)")
        con.execute("CREATE TABLE shop_daily (date VARCHAR, shop VARCHAR, sku_count BIGINT, gmv DOUBLE, units BIGINT, orders BIGINT, buyers BIGINT, visitors BIGINT, conversion DOUBLE, aov DOUBLE, uv_value DOUBLE, refund_amount DOUBLE, refund_rate DOUBLE, baseline VARCHAR, week VARCHAR, gmv_outbound DOUBLE, units_outbound BIGINT, stock_value DOUBLE, out30d_value DOUBLE, PRIMARY KEY(date, shop))")
        con.execute("CREATE TABLE categories (date VARCHAR, path VARCHAR, l1 VARCHAR, l2 VARCHAR, l3 VARCHAR, gmv DOUBLE, units BIGINT, orders BIGINT, sku_count BIGINT, visitors BIGINT, refund_amount DOUBLE, gmv_outbound DOUBLE)")
        con.execute("CREATE TABLE city_stock (date VARCHAR, shop VARCHAR, sku VARCHAR, name VARCHAR, city VARCHAR, stock DOUBLE, daily_avg DOUBLE, days_cover DOUBLE, out_yesterday DOUBLE, out_7d DOUBLE, nat_stock DOUBLE, nat_days_cover DOUBLE, price DOUBLE)")
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
        # quality
        for k, v in data["quality"].items():
            if isinstance(v, (int, float)):
                con.execute(f"INSERT INTO quality VALUES ('{k}', '{v}')")
            elif isinstance(v, bool):
                con.execute(f"INSERT INTO quality VALUES ('{k}', '{str(v).lower()}')")
            else:
                sv = json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)
                con.execute(f"INSERT INTO quality VALUES ('{k}', '{sv.replace(chr(39), chr(92)+chr(39))}')")
        # charts
        for s, ch in data["charts"].items():
            for ct, svg in ch.items():
                escaped = svg.replace(chr(39), chr(92)+chr(39))
                con.execute(f"INSERT INTO charts VALUES ('{s}', '{ct}', '{escaped}')")
        # overall
        for r in data["overall"]:
            bl = json.dumps(r.get("baseline"), ensure_ascii=False) if r.get("baseline") else None
            wk = json.dumps(r.get("week"), ensure_ascii=False) if r.get("week") else None
            bl_s = f"'{bl.replace(chr(39), chr(92)+chr(39))}'" if bl else "NULL"
            wk_s = f"'{wk.replace(chr(39), chr(92)+chr(39))}'" if wk else "NULL"
            con.execute(f"INSERT INTO overall VALUES ('{r['date']}', {r.get('shopCount',0)}, {r.get('skuCount',0)}, {r.get('gmv',0)}, {r.get('units',0)}, {r.get('orders',0)}, {r.get('buyers',0)}, {r.get('visitors',0)}, {sqlnum(r.get('conversion'))}, {sqlnum(r.get('aov'))}, {sqlnum(r.get('uvValue'))}, {r.get('addCartUsers',0)}, {r.get('refundAmount',0)}, {sqlnum(r.get('refundRate'))}, {bl_s}, {wk_s})")
        # shop_daily
        for shop, rows in data["shopDaily"].items():
            for r in rows:
                bl = json.dumps(r.get("baseline"), ensure_ascii=False) if r.get("baseline") else None
                wk = json.dumps(r.get("week"), ensure_ascii=False) if r.get("week") else None
                bl_s = f"'{bl.replace(chr(39), chr(92)+chr(39))}'" if bl else "NULL"
                wk_s = f"'{wk.replace(chr(39), chr(92)+chr(39))}'" if wk else "NULL"
                con.execute(f"INSERT INTO shop_daily VALUES ('{r['date']}', '{r['shopRaw']}', {r.get('skuCount',0)}, {r.get('gmv',0)}, {r.get('units',0)}, {r.get('orders',0)}, {r.get('buyers',0)}, {r.get('visitors',0)}, {sqlnum(r.get('conversion'))}, {sqlnum(r.get('aov'))}, {sqlnum(r.get('uvValue'))}, {r.get('refundAmount',0)}, {sqlnum(r.get('refundRate'))}, {bl_s}, {wk_s}, {r.get('gmvOutbound',0)}, {r.get('unitsOutbound',0)}, {r.get('stockValue',0)}, {r.get('out30dValue',0)})")
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
                con.execute(f"INSERT INTO categories VALUES ('{date}', '{p_esc}', '{l1_esc}', '{l2_esc}', '{l3_esc}', {gmv_val}, {int(r.get('units',0))}, {int(r.get('orders',0))}, {int(r.get('skuCount',0))}, {visitors}, {refund}, {r.get('gmvOutbound',0)})")
        # city_stock
        for date, shops_cs in data.get("cityStock", {}).items():
            for shop, cs in shops_cs.items():
                key=f"jd_self|{shop}"
                if key not in SHOP_META: continue
                for r in cs["rows"]:
                    name_esc=str(r["name"]).replace(chr(39), chr(92)+chr(39))
                    con.execute(f"INSERT INTO city_stock VALUES ('{date}', '{key}', '{r['sku']}', '{name_esc}', '{r['city']}', {r['stock']}, {r['dailyAvg']}, {r['daysCover'] if r['daysCover'] is not None else 'NULL'}, {r['outYesterday']}, {r['out7d']}, {r['natStock']}, {r['natDaysCover'] if r['natDaysCover'] is not None else 'NULL'}, {r['price']})")

        # top_skus
        for date, rows in data["topSkus"].items():
            for r in rows:
                name_esc = r["name"].replace(chr(39), chr(92)+chr(39))
                conv = sqlnum(r.get('conversion'))
                uvv = sqlnum(r.get('uvValue'))
                con.execute(f"INSERT INTO top_skus VALUES ('{date}', '{r['shopRaw']}', '{r['sku']}', '{name_esc}', {r['gmv']}, {int(r['units'])}, {int(r['visitors'])}, {conv}, {uvv}, {r['refundAmount']}, {r.get('gmvOutbound',0)})")
        # movers
        for date, mv in data["movers"].items():
            for r in mv.get("risers", []):
                name_esc = r["name"].replace(chr(39), chr(92)+chr(39))
                con.execute(f"INSERT INTO movers VALUES ('{date}', 'riser', '{r['shopRaw']}', '{r['sku']}', '{name_esc}', {r['previousGmv']}, {r['gmv']}, {r['delta']})")
            for r in mv.get("fallers", []):
                name_esc = r["name"].replace(chr(39), chr(92)+chr(39))
                con.execute(f"INSERT INTO movers VALUES ('{date}', 'faller', '{r['shopRaw']}', '{r['sku']}', '{name_esc}', {r['previousGmv']}, {r['gmv']}, {r['delta']})")
        # alerts
        for date, aa in data["alerts"].items():
            for a in aa:
                detail_esc = a["detail"].replace(chr(39), chr(92)+chr(39))
                scope_esc = a["scope"].replace(chr(39), chr(92)+chr(39))
                change_v = a.get("change")
                con.execute(f"INSERT INTO alerts VALUES ('{date}', '{a['level']}', '{scope_esc}', '{a['type']}', '{detail_esc}', {a['current']}, {a['previous']}, {change_v})")
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
    latest=next(x for x in data["overall"] if x["date"]==data["quality"]["latestCompleteDate"])
    # 同步数据库到函数读取位置（api/report.duckdb，随 @vercel/python 打包）
    api_db = DB_PATH.parent.parent / "report.duckdb"
    if api_db != DB_PATH:
        import shutil
        shutil.copy2(DB_PATH, api_db)
        print(f"同步: {api_db}")
    print(OUT); print(json.dumps(data["quality"],ensure_ascii=False,indent=2))
    print(f"latest={latest['date']} gmv={latest['gmv']:.2f} html_size={OUT.stat().st_size} db_size={config.DB_PATH.stat().st_size}")
