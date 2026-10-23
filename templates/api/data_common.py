"""DuckDB → 报表 JSON 的统一读取逻辑（本地 server.py 与 Vercel api/data.py 共用）。

两入口必须复用本模块：任何字段增删只改这里，避免本地/线上数据口径漂移。
仅依赖标准库 + duckdb，Vercel 与本地环境均可运行。
"""
import json
from pathlib import Path


def find_db(here):
    """Vercel 打包位置可能与本地不同，逐个候选路径探测。"""
    here = Path(here)
    for p in [here / "data" / "report.duckdb", here / "report.duckdb",
              here.parent / "data" / "report.duckdb"]:
        if p.exists():
            return p
    return here / "data" / "report.duckdb"


def connect(db_path):
    import duckdb
    return duckdb.connect(str(db_path), read_only=True)


def load_data(con):
    """读全部报表数据并组装为 API JSON 结构（唯一权威实现）。"""
    meta_rows = {r[0]: r[1] for r in con.sql("SELECT key,value FROM meta").fetchall()}
    qual_rows = {r[0]: r[1] for r in con.sql("SELECT key,value FROM quality").fetchall()}
    quality = {}
    for k, v in qual_rows.items():
        if v in ("true", "false"):
            quality[k] = v == "true"
        elif v in ("True", "False"):
            quality[k] = v == "True"
        else:
            try:
                quality[k] = json.loads(v) if isinstance(v, str) else v
            except (json.JSONDecodeError, ValueError):
                try:
                    quality[k] = float(v)
                except (ValueError, TypeError):
                    quality[k] = v
    shops = json.loads(meta_rows.get("shops", "[]"))
    dates = json.loads(meta_rows.get("dates", "[]"))
    shop_display = {s["raw"]: s["display"] for s in shops}

    def parse_json(v):
        try:
            return json.loads(v) if v else None
        except (json.JSONDecodeError, ValueError):
            return v

    overall = []
    for row in con.sql("""SELECT date,shop_count,sku_count,gmv,units,orders,buyers,visitors,
               conversion,aov,uv_value,add_cart_users,refund_amount,refund_rate,baseline,week
               FROM overall ORDER BY date""").fetchall():
        overall.append({
            "date": row[0], "shopCount": row[1], "skuCount": row[2], "gmv": row[3],
            "units": row[4], "orders": row[5], "buyers": row[6], "visitors": row[7],
            "conversion": row[8], "aov": row[9], "uvValue": row[10],
            "addCartUsers": row[11], "refundAmount": row[12], "refundRate": row[13],
            "baseline": parse_json(row[14]), "week": parse_json(row[15]),
        })

    shop_daily = {}
    for row in con.sql("""SELECT date,shop,sku_count,gmv,units,orders,buyers,visitors,
               conversion,aov,uv_value,refund_amount,refund_rate,baseline,week,
               gmv_outbound,units_outbound,stock_value,out30d_value,out_mtd_value
               FROM shop_daily ORDER BY date""").fetchall():
        shop_daily.setdefault(row[1], []).append({
            "date": row[0], "shopRaw": row[1], "shopDisplay": shop_display.get(row[1], row[1]),
            "skuCount": row[2], "gmv": row[3], "units": row[4], "orders": row[5],
            "buyers": row[6], "visitors": row[7], "conversion": row[8], "aov": row[9],
            "uvValue": row[10], "refundAmount": row[11], "refundRate": row[12],
            "baseline": parse_json(row[13]), "week": parse_json(row[14]),
            "gmvOutbound": row[15], "unitsOutbound": row[16], "stockValue": row[17],
            "out30dValue": row[18], "outMtdValue": row[19],
        })

    categories = {}
    for row in con.sql("""SELECT date,path,l1,l2,l3,gmv,units,orders,sku_count,visitors,refund_amount,gmv_outbound
               FROM categories ORDER BY date""").fetchall():
        categories.setdefault(row[0], []).append({
            "path": row[1], "shopRaw": row[1].split("/")[0], "l1": row[2], "l2": row[3], "l3": row[4],
            "category1": row[2], "category2": row[3], "category3": row[4],
            "gmv": row[5], "units": row[6], "orders": row[7],
            "skuCount": row[8], "visitors": row[9], "refundAmount": row[10], "gmvOutbound": row[11]})

    top_skus = {}
    for row in con.sql("""SELECT date,shop,sku,name,gmv,units,visitors,conversion,uv_value,refund_amount,gmv_outbound
               FROM top_skus ORDER BY date,gmv DESC""").fetchall():
        top_skus.setdefault(row[0], []).append({
            "shopRaw": row[1], "shopDisplay": shop_display.get(row[1], row[1]), "sku": row[2], "name": row[3],
            "gmv": row[4], "units": row[5], "visitors": row[6],
            "conversion": row[7], "uvValue": row[8], "refundAmount": row[9], "gmvOutbound": row[10]})

    city_stock = {}
    for row in con.sql("""SELECT date,shop,sku,name,city,stock,daily_avg,days_cover,out_yesterday,out_7d,
               nat_stock,nat_days_cover,nat_transit,nat_out_yesterday,nat_out_7d,price
               FROM city_stock ORDER BY date,shop,sku,city""").fetchall():
        days = row[7]
        if days is None:
            level = "unknown"
        elif days < 1:
            level = "critical"
        elif days < 3:
            level = "warn"
        else:
            level = "ok"
        city_stock.setdefault(row[0], []).append({
            "shopRaw": row[1], "shopDisplay": shop_display.get(row[1], row[1]),
            "sku": row[2], "name": row[3], "city": row[4],
            "stock": row[5], "dailyAvg": row[6], "daysCover": days, "level": level,
            "outYesterday": row[8], "out7d": row[9], "natStock": row[10],
            "natDaysCover": row[11], "natTransit": row[12],
            "natOutYesterday": row[13], "natOut7d": row[14], "price": row[15]})

    movers = {}
    for row in con.sql("""SELECT date,type,shop,sku,name,previous_gmv,gmv,delta
               FROM movers ORDER BY date""").fetchall():
        key = row[1] + "s" if row[1] in ("riser", "faller") else row[1]
        movers.setdefault(row[0], {}).setdefault(key, []).append({
            "shopRaw": row[2], "shopDisplay": shop_display.get(row[2], row[2]), "sku": row[3], "name": row[4],
            "previousGmv": row[5], "gmv": row[6], "delta": row[7]})

    alerts = {}
    for row in con.sql("""SELECT date,level,scope,type,detail,current,previous,change
               FROM alerts ORDER BY date""").fetchall():
        alerts.setdefault(row[0], []).append({
            "level": row[1], "scope": row[2], "type": row[3],
            "detail": row[4], "current": row[5], "previous": row[6], "change": row[7]})

    optimization = {}
    for k, v in {r[0]: r[1] for r in con.sql("SELECT key,value FROM optimization").fetchall()}.items():
        parts = k.split(".")
        d = optimization
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        try:
            d[parts[-1]] = json.loads(v) if isinstance(v, str) and v not in ("true", "false") else v
        except (json.JSONDecodeError, ValueError):
            try:
                d[parts[-1]] = float(v)
            except (ValueError, TypeError):
                d[parts[-1]] = v

    def meta_json(key, default):
        v = meta_rows.get(key, default)
        try:
            return json.loads(v) if isinstance(v, str) else (v or default)
        except (json.JSONDecodeError, ValueError):
            return default

    return {
        "generatedAt": meta_rows.get("generatedAt", ""),
        "sourceDir": meta_rows.get("sourceDir", "多平台导出（京东商智 + 唯品会 + 拼多多）"),
        "shops": shops,
        "platforms": meta_json("platforms", {"jd": "京东", "vip": "唯品会"}),
        "dates": dates,
        "overall": overall, "shopDaily": shop_daily,
        "categories": categories, "topSkus": top_skus,
        "movers": movers, "alerts": alerts,
        "quality": quality, "cityStock": city_stock,
        "moduleFilters": meta_json("moduleFilters", {}),
        "targets": meta_json("targets", {}),
        "optimization": optimization,
    }
