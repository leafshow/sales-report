"""Vercel Serverless Function — 从 DuckDB 读取数据返回 JSON"""
from __future__ import annotations
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "report.duckdb"


def _load_con():
    try:
        import duckdb
    except ImportError:
        return None, "duckdb module not installed"
    if not DB_PATH.exists():
        return None, "database not found, run build script first"
    return duckdb.connect(str(DB_PATH)), None


def handler(event, context):
    con, err = _load_con()
    if err:
        return _resp(404, {"error": err})
    try:
        # meta
        meta_rows = {r[0]: r[1] for r in con.sql("SELECT key,value FROM meta").fetchall()}
        # quality
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

        # overall
        overall = []
        for row in con.sql("""SELECT date,shop_count,sku_count,gmv,units,orders,buyers,visitors,
                   conversion,aov,uv_value,add_cart_users,refund_amount,refund_rate,baseline,week
                   FROM overall ORDER BY date""").fetchall():
            rec = {"date": row[0], "shopCount": row[1], "skuCount": row[2], "gmv": row[3],
                   "units": row[4], "orders": row[5], "buyers": row[6], "visitors": row[7],
                   "conversion": row[8], "aov": row[9], "uvValue": row[10],
                   "addCartUsers": row[11], "refundAmount": row[12], "refundRate": row[13]}
            rec["baseline"] = json.loads(row[14]) if row[14] else None
            rec["week"] = json.loads(row[15]) if row[15] else None
            overall.append(rec)

        # shop_daily
        shop_daily = {}
        for row in con.sql("""SELECT date,shop,sku_count,gmv,units,orders,buyers,visitors,
                   conversion,aov,uv_value,refund_amount,refund_rate,baseline,week
                   FROM shop_daily ORDER BY date""").fetchall():
            rec = {"date": row[0], "shopRaw": row[1], "skuCount": row[2], "gmv": row[3],
                   "units": row[4], "orders": row[5], "buyers": row[6], "visitors": row[7],
                   "conversion": row[8], "aov": row[9], "uvValue": row[10],
                   "refundAmount": row[11], "refundRate": row[12]}
            rec["baseline"] = json.loads(row[13]) if row[13] else None
            rec["week"] = json.loads(row[14]) if row[14] else None
            shop_daily.setdefault(row[1], []).append(rec)

        # categories
        categories = {}
        for row in con.sql("""SELECT date,path,l1,l2,l3,gmv,units,orders,buyer_count,visitors,refund_amount
                   FROM categories ORDER BY date""").fetchall():
            categories.setdefault(row[0], []).append({
                "path": row[1], "l1": row[2], "l2": row[3], "l3": row[4],
                "gmv": row[5], "units": row[6], "orders": row[7],
                "buyerCount": row[8], "visitors": row[9], "refundAmount": row[10]})

        # top_skus
        top_skus = {}
        for row in con.sql("""SELECT date,shop,sku,name,gmv,units,visitors,conversion,uv_value,refund_amount
                   FROM top_skus ORDER BY date,gmv DESC""").fetchall():
            top_skus.setdefault(row[0], []).append({
                "shopRaw": row[1], "sku": row[2], "name": row[3],
                "gmv": row[4], "units": row[5], "visitors": row[6],
                "conversion": row[7], "uvValue": row[8], "refundAmount": row[9]})

        # movers
        movers = {}
        for row in con.sql("""SELECT date,type,shop,sku,name,previous_gmv,gmv,delta
                   FROM movers ORDER BY date""").fetchall():
            key = row[1] + "s" if row[1] in ("riser", "faller") else row[1]
            movers.setdefault(row[0], {}).setdefault(key, []).append({
                "shopRaw": row[2], "sku": row[3], "name": row[4],
                "previousGmv": row[5], "gmv": row[6], "delta": row[7]})

        # alerts
        alerts = {}
        for row in con.sql("""SELECT date,level,scope,type,detail,current,previous,change
                   FROM alerts ORDER BY date""").fetchall():
            alerts.setdefault(row[0], []).append({
                "level": row[1], "scope": row[2], "type": row[3],
                "detail": row[4], "current": row[5], "previous": row[6], "change": row[7]})

        # charts
        charts = {}
        for row in con.sql("SELECT schema_key,chart_type,svg_text FROM charts").fetchall():
            charts.setdefault(row[0], {})[row[1]] = row[2]

        # optimization
        opt_rows = {r[0]: r[1] for r in con.sql("SELECT key,value FROM optimization").fetchall()}
        optimization = {}
        for k, v in opt_rows.items():
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

        result = {
            "generatedAt": meta_rows.get("generatedAt", ""),
            "sourceDir": "京东商智导出",
            "shops": shops, "dates": dates,
            "overall": overall, "shopDaily": shop_daily,
            "categories": categories, "topSkus": top_skus,
            "movers": movers, "alerts": alerts,
            "quality": quality, "charts": charts,
            "optimization": optimization,
        }
        return _resp(200, result)
    finally:
        con.close()


def _resp(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
