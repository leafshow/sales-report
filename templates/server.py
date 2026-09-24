"""本地开发服务器 — 同时提供静态文件和 /api/data JSON 接口"""
import json, os, sys, traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

DB_PATH = Path(__file__).parent / "api" / "data" / "report.duckdb"

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/data" or self.path == "/api/data.json":
            self._serve_api()
        else:
            super().do_GET()

    def _serve_api(self):
        if not HAS_DUCKDB:
            self._json_response(500, {"error": "duckdb not installed"})
            return
        if not DB_PATH.exists():
            self._json_response(404, {"error": "report.duckdb not found, run build script first"})
            return
        try:
            con = duckdb.connect(str(DB_PATH))
            data = self._load_data(con)
            con.close()
            self._json_response(200, data)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
            self._json_response(500, {"error": str(e)})

    def _load_data(self, con):
        meta = {r[0]: r[1] for r in con.sql("SELECT key,value FROM meta").fetchall()}
        qual = {r[0]: r[1] for r in con.sql("SELECT key,value FROM quality").fetchall()}
        quality = {}
        for k, v in qual.items():
            if v in ("true", "false"): quality[k] = v == "true"
            elif v in ("True", "False"): quality[k] = v == "True"
            else:
                try: quality[k] = json.loads(v)
                except:
                    try: quality[k] = float(v)
                    except: quality[k] = v
        shops = json.loads(meta.get("shops", "[]"))
        dates = json.loads(meta.get("dates", "[]"))

        def parse_json(v):
            try: return json.loads(v) if v else None
            except: return v

        overall = []
        for row in con.sql("SELECT * FROM overall ORDER BY date").fetchall():
            overall.append({
                "date": row[0], "shopCount": row[1], "skuCount": row[2], "gmv": row[3],
                "units": row[4], "orders": row[5], "buyers": row[6], "visitors": row[7],
                "conversion": row[8], "aov": row[9], "uvValue": row[10],
                "addCartUsers": row[11], "refundAmount": row[12], "refundRate": row[13],
                "baseline": parse_json(row[14]), "week": parse_json(row[15]),
            })

        shop_daily = {}
        for row in con.sql("SELECT * FROM shop_daily ORDER BY date").fetchall():
            rec = {"date": row[0], "shopRaw": row[1], "skuCount": row[2], "gmv": row[3],
                   "units": row[4], "orders": row[5], "buyers": row[6], "visitors": row[7],
                   "conversion": row[8], "aov": row[9], "uvValue": row[10],
                   "refundAmount": row[11], "refundRate": row[12],
                   "baseline": parse_json(row[13]), "week": parse_json(row[14])}
            shop_daily.setdefault(row[1], []).append(rec)

        categories = {}
        for row in con.sql("SELECT * FROM categories ORDER BY date").fetchall():
            categories.setdefault(row[0], []).append({
                "path": row[1], "l1": row[2], "l2": row[3], "l3": row[4],
                "gmv": row[5], "units": row[6], "orders": row[7],
                "buyerCount": row[8], "visitors": row[9], "refundAmount": row[10],
            })

        top_skus = {}
        for row in con.sql("SELECT * FROM top_skus ORDER BY date,gmv DESC").fetchall():
            top_skus.setdefault(row[0], []).append({
                "shopRaw": row[1], "sku": row[2], "name": row[3],
                "gmv": row[4], "units": row[5], "visitors": row[6],
                "conversion": row[7], "uvValue": row[8], "refundAmount": row[9],
            })

        movers = {}
        for row in con.sql("SELECT * FROM movers ORDER BY date").fetchall():
            key = row[1] + "s"
            movers.setdefault(row[0], {}).setdefault(key, []).append({
                "shopRaw": row[2], "sku": row[3], "name": row[4],
                "previousGmv": row[5], "gmv": row[6], "delta": row[7],
            })

        alerts = {}
        for row in con.sql("SELECT * FROM alerts ORDER BY date").fetchall():
            alerts.setdefault(row[0], []).append({
                "level": row[1], "scope": row[2], "type": row[3],
                "detail": row[4], "current": row[5], "previous": row[6], "change": row[7],
            })

        charts = {}
        for row in con.sql("SELECT * FROM charts").fetchall():
            charts.setdefault(row[0], {})[row[1]] = row[2]

        opt = {}
        for k, v in {r[0]: r[1] for r in con.sql("SELECT * FROM optimization").fetchall()}.items():
            parts = k.split(".")
            d = opt
            for p in parts[:-1]: d = d.setdefault(p, {})
            try: d[parts[-1]] = json.loads(v) if isinstance(v, str) and v not in ("true","false") else v
            except:
                try: d[parts[-1]] = float(v)
                except: d[parts[-1]] = v

        return {
            "generatedAt": meta.get("generatedAt", ""),
            "sourceDir": "京东商智导出",
            "shops": shops, "dates": dates,
            "overall": overall, "shopDaily": shop_daily,
            "categories": categories, "topSkus": top_skus,
            "movers": movers, "alerts": alerts,
            "quality": quality, "charts": charts,
            "optimization": opt,
        }

    def _json_response(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass  # 客户端已断开，忽略

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    os.chdir(Path(__file__).parent)
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"📊 京东销售日报 — 本地服务器")
    print(f"   HTML: http://127.0.0.1:{port}/index.html")
    print(f"   API:  http://127.0.0.1:{port}/api/data")
    print(f"   按 Ctrl+C 停止")
    server.serve_forever()
