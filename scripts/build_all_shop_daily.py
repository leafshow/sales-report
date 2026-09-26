from __future__ import annotations
import json, re, warnings
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import duckdb
import config  # noqa: F401 — 路径已在 config.py 中定义

warnings.filterwarnings("ignore", message="Workbook contains no default style")
INPUT    = config.INPUT
OUT      = config.OUT
TEMPLATE = config.TEMPLATE
API_DATA_DIR = config.API_DATA_DIR  # API 数据目录
DB_PATH = config.DB_PATH            # DuckDB 数据库路径
FILE_RE  = re.compile(config.FILE_PATTERN)
SHOPS    = config.SHOPS
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

def total_row(date, shop, row, count, source):
    x={"date":date,"shopRaw":shop,"shopDisplay":SHOPS[shop][0],"skuCount":count,"sourceFile":source,
       "gmv":n(row["成交金额"]),"units":n(row["成交商品件数"]),"orders":n(row["成交单量"]),
       "buyers":n(row["成交客户数"]),"visitors":n(row["商品访客数"]),"pv":n(row["商品浏览量"]),
       "searchImpressions":n(row["搜索曝光次数"]),"searchClicks":n(row["搜索点击次数"]),
       "productImpressions":n(row["商品曝光次数"]),"productImpressionUsers":n(row["商品曝光人数"]),
       "addCartUsers":n(row["加购客户数"]),"orderAmount":n(row["下单金额"]),"orderCount":n(row["下单单量"]),
       "orderBuyers":n(row["下单客户数"]),"refundAmount":n(row["取消及售后退款金额"])}
    return calc(x)

def sku_rows(date, shop, df):
    out=[]
    for _,q in df.iterrows():
        x={"date":date,"shopRaw":shop,"shopDisplay":SHOPS[shop][0],"sku":t(q["SKU"]),"name":t(q["SKU名称"]),
           "category1":t(q["一级类目"]),"category2":t(q["二级类目"]),"category3":t(q["三级类目"]),
           "gmv":n(q["成交金额"]),"units":n(q["成交商品件数"]),"orders":n(q["成交单量"]),
           "buyers":n(q["成交客户数"]),"visitors":n(q["商品访客数"]),"searchImpressions":n(q["搜索曝光次数"]),
           "searchClicks":n(q["搜索点击次数"]),"addCartUsers":n(q["加购客户数"]),"refundAmount":n(q["取消及售后退款金额"])}
        x["conversion"]=r(x["buyers"],x["visitors"]); x["uvValue"]=r(x["gmv"],x["visitors"]); out.append(x)
    return out

def trim_sku(x):
    keys = ["shopRaw","shopDisplay","sku","name","gmv","units","visitors",
            "refundAmount","conversion","uvValue"]
    return {k:x[k] for k in keys}

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
    values=[x["conversion"] for x in rows if x.get("conversion") is not None]
    if not values:return "<div class=callout>暂无转化率数据。</div>"
    vmin,vmax=min(values),max(values); padding=(vmax-vmin or vmax or .01)*.22
    y0=max(0,vmin-padding); y1=vmax+padding
    def x(i): return left+i*plot_w/(len(rows)-1)
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
    files=sorted(f for f in INPUT.glob("*.xlsx") if FILE_RE.match(f.name)); q={"sourceFiles":len(files),"parsedFiles":0,"schemaOk":True,"totalRowsOk":True,
        "duplicateSkuCount":0,"reconciliationOk":True,"unexpectedShops":[]}
    shop_rows={s:[] for s in SHOPS}; sku={date:[] for date in sorted({FILE_RE.match(f.name).group(2) for f in files if FILE_RE.match(f.name)})}
    pairs=set()
    for f in files:
        m=FILE_RE.match(f.name)
        if not m: continue
        shop,date=m.groups()
        if shop not in SHOPS:
            q["unexpectedShops"].append(shop); continue
        df=pd.read_excel(f); missing=[c for c in COLUMNS if c not in df.columns]
        if missing: raise RuntimeError(f"{f.name} missing {missing}")
        if len(df)<2 or t(df.iloc[0]["SKU"])!="合计": raise RuntimeError(f"{f.name} missing total row")
        total=df.iloc[0]; detail=df.iloc[1:]
        q["parsedFiles"]+=1; pairs.add((shop,date)); q["duplicateSkuCount"]+=int(detail["SKU"].astype(str).duplicated().sum())
        ok=abs(n(total["成交金额"])-sum(n(x) for x in detail["成交金额"]))<=max(.01,abs(n(total["成交金额"]))*.001)
        ok2=abs(n(total["成交商品件数"])-sum(n(x) for x in detail["成交商品件数"]))<=max(.01,abs(n(total["成交商品件数"]))*.001)
        q["reconciliationOk"] &= ok and ok2
        shop_rows[shop].append(total_row(date,shop,total,len(detail),f.name)); sku[date].extend(sku_rows(date,shop,detail))
    dates=sorted({d for _,d in pairs}); shops=sorted(SHOPS,key=lambda s:SHOPS[s][2])
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
        cat=(pd.DataFrame(d).groupby(["shopRaw","shopDisplay","category1","category2","category3"]).agg(
            gmv=("gmv","sum"),units=("units","sum"),orders=("orders","sum"),visitors=("visitors","sum"),
            addCartUsers=("addCartUsers","sum"),refundAmount=("refundAmount","sum"),skuCount=("sku","count")).reset_index().sort_values("gmv",ascending=False))
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
    expected_latest=(datetime.now().date()-timedelta(days=1)).isoformat()
    missing_dates=[]
    if dates and dates[-1] < expected_latest:
        check=datetime.fromisoformat(dates[-1]).date()
        while check < datetime.fromisoformat(expected_latest).date():
            check += timedelta(days=1); missing_dates.append(check.isoformat())
    q.update({"expectedCombinations":len(shops)*len(dates),"actualCombinations":len(pairs),"shopCount":len(shops),"dateCount":len(dates),
              "completeDateCount":len(complete),"latestCompleteDate":complete[-1],"latestAvailableDate":dates[-1],
              "missingCombinations":[{"shop":s,"date":d} for s in shops for d in dates if (s,d) not in pairs],
              "expectedLatestDate":expected_latest,"missingDates":missing_dates,"isFresh":not missing_dates})
    charts={"ALL":{"gmv":svg_gmv_chart(overall),"conversion":svg_conversion_chart(overall)}}
    for shop in shops:
        charts[shop]={"gmv":svg_gmv_chart(shop_rows[shop]),"conversion":svg_conversion_chart(shop_rows[shop])}
    recent_dates=dates[-RECENT_DAYS:]
    prior_dates=dates[-RESEARCH_DAYS:-RECENT_DAYS] if len(dates)>=RESEARCH_DAYS else dates[:max(0,len(dates)-RECENT_DAYS)]
    def window_rows(rows,window):
        return [next(x for x in rows if x["date"]==date) for date in window]
    def window_summary(rows,window):
        items=window_rows(rows,window)
        summary={field:sum(x[field] for x in items) for field in FIELDS}
        return calc(summary)
    def optimization_shop(shop):
        rows=shop_rows[shop]
        recent=window_summary(rows,recent_dates); prior=window_summary(rows,prior_dates)
        return {
            "shopRaw":shop,"shopDisplay":SHOPS[shop][0],
            "recentGmv":recent["gmv"],"priorGmv":prior["gmv"],
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
        shop_gmv=next(x["gmv"] for x in shop_rows[shop] if x["date"]==latest)
        ranked=sorted([x for x in tops[latest] if x["shopRaw"]==shop],key=lambda x:x["gmv"],reverse=True)
        concentration.append({
            "shopRaw":shop,"shopDisplay":SHOPS[shop][0],"gmv":shop_gmv,
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
    optimization={
        "latestDate":latest,"recentStart":recent_dates[0],"recentEnd":recent_dates[-1],
        "priorStart":prior_dates[0],"priorEnd":prior_dates[-1],
        "overallRecent":window_summary(overall,recent_dates),"overallPrior":window_summary(overall,prior_dates),
        "shops":optimization_shops,"concentration":concentration,
        "opportunities":recurring_opportunities[:OPPORTUNITIES_MAX],
        "averageAlertCount":sum(alert_counts)/len(alert_counts) if alert_counts else 0,
        "latestAlertCount":len(alerts.get(latest,[])),
    }
    return {"generatedAt":datetime.now().strftime("%Y-%m-%d %H:%M"),"sourceDir":str(INPUT),
            "shops":[{"raw":s,"display":SHOPS[s][0],"brand":SHOPS[s][1]} for s in shops],"dates":dates,"overall":overall,
            "shopDaily":shop_rows,"categories":cats,"topSkus":tops,"movers":movers,"alerts":alerts,"quality":q,"charts":charts,
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
        con.execute("CREATE TABLE shop_daily (date VARCHAR, shop VARCHAR, sku_count BIGINT, gmv DOUBLE, units BIGINT, orders BIGINT, buyers BIGINT, visitors BIGINT, conversion DOUBLE, aov DOUBLE, uv_value DOUBLE, refund_amount DOUBLE, refund_rate DOUBLE, baseline VARCHAR, week VARCHAR, PRIMARY KEY(date, shop))")
        con.execute("CREATE TABLE categories (date VARCHAR, path VARCHAR, l1 VARCHAR, l2 VARCHAR, l3 VARCHAR, gmv DOUBLE, units BIGINT, orders BIGINT, buyer_count BIGINT, visitors BIGINT, refund_amount DOUBLE)")
        con.execute("CREATE TABLE top_skus (date VARCHAR, shop VARCHAR, sku VARCHAR, name VARCHAR, gmv DOUBLE, units BIGINT, visitors BIGINT, conversion DOUBLE, uv_value DOUBLE, refund_amount DOUBLE)")
        con.execute("CREATE TABLE movers (date VARCHAR, type VARCHAR, shop VARCHAR, sku VARCHAR, name VARCHAR, previous_gmv DOUBLE, gmv DOUBLE, delta DOUBLE)")
        con.execute("CREATE TABLE alerts (date VARCHAR, level VARCHAR, scope VARCHAR, type VARCHAR, detail VARCHAR, current DOUBLE, previous DOUBLE, change DOUBLE)")
        con.execute("CREATE TABLE optimization (key VARCHAR PRIMARY KEY, value VARCHAR)")
        # meta
        con.execute(f"INSERT INTO meta VALUES ('generatedAt', '{data['generatedAt']}')")
        con.execute(f"INSERT INTO meta VALUES ('shops', '{json.dumps(data['shops'], ensure_ascii=False).replace(chr(39), chr(92)+chr(39))}')")
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
            con.execute(f"INSERT INTO overall VALUES ('{r['date']}', {r.get('shopCount',0)}, {r.get('skuCount',0)}, {r.get('gmv',0)}, {r.get('units',0)}, {r.get('orders',0)}, {r.get('buyers',0)}, {r.get('visitors',0)}, {r.get('conversion')}, {r.get('aov')}, {r.get('uvValue')}, {r.get('addCartUsers',0)}, {r.get('refundAmount',0)}, {r.get('refundRate')}, {bl_s}, {wk_s})")
        # shop_daily
        for shop, rows in data["shopDaily"].items():
            for r in rows:
                bl = json.dumps(r.get("baseline"), ensure_ascii=False) if r.get("baseline") else None
                wk = json.dumps(r.get("week"), ensure_ascii=False) if r.get("week") else None
                bl_s = f"'{bl.replace(chr(39), chr(92)+chr(39))}'" if bl else "NULL"
                wk_s = f"'{wk.replace(chr(39), chr(92)+chr(39))}'" if wk else "NULL"
                con.execute(f"INSERT INTO shop_daily VALUES ('{r['date']}', '{r['shopRaw']}', {r.get('skuCount',0)}, {r.get('gmv',0)}, {r.get('units',0)}, {r.get('orders',0)}, {r.get('buyers',0)}, {r.get('visitors',0)}, {r.get('conversion')}, {r.get('aov')}, {r.get('uvValue')}, {r.get('refundAmount',0)}, {r.get('refundRate')}, {bl_s}, {wk_s})")
        # categories
        for date, rows in data["categories"].items():
            for r in rows:
                p = r["shopDisplay"] + "/" + r["category3"]
                p_esc = p.replace(chr(39), chr(92)+chr(39))
                l1_esc = r["category1"].replace(chr(39), chr(92)+chr(39))
                l2_esc = r["category2"].replace(chr(39), chr(92)+chr(39))
                l3_esc = r["category3"].replace(chr(39), chr(92)+chr(39))
                visitors = int(r.get('visitors',0)) if r.get('visitors') is not None else 0
                gmv_val = r.get('gmv',0) if r.get('gmv') is not None else 0
                refund = r.get('refundAmount',0) if r.get('refundAmount') is not None else 0
                con.execute(f"INSERT INTO categories VALUES ('{date}', '{p_esc}', '{l1_esc}', '{l2_esc}', '{l3_esc}', {gmv_val}, {int(r.get('units',0))}, {int(r.get('orders',0))}, {int(r.get('skuCount',0))}, {visitors}, {refund})")
        # top_skus
        for date, rows in data["topSkus"].items():
            for r in rows:
                name_esc = r["name"].replace(chr(39), chr(92)+chr(39))
                conv = f"{r['conversion']}" if r.get('conversion') is not None else "NULL"
                uvv = f"{r['uvValue']}" if r.get('uvValue') is not None else "NULL"
                con.execute(f"INSERT INTO top_skus VALUES ('{date}', '{r['shopRaw']}', '{r['sku']}', '{name_esc}', {r['gmv']}, {int(r['units'])}, {int(r['visitors'])}, {conv}, {uvv}, {r['refundAmount']})")
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
