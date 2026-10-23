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
    def end_headers(self):
        # 本地开发禁用缓存，避免改版后浏览器仍用旧 HTML/JS
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/data" or self.path == "/api/data.json":
            self._serve_api()
        elif self.path == "/api/budan" or self.path == "/budan.json":
            self._serve_budan()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/budan":
            self._save_budan()
        else:
            self._json_response(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    BUDAN_PATH = Path(__file__).parent / "budan.json"

    def _serve_budan(self):
        try:
            data = json.loads(self.BUDAN_PATH.read_text(encoding="utf-8")) if self.BUDAN_PATH.exists() else {}
            self._json_response(200, data)
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _save_budan(self):
        """本地直写 budan.json：{shopRaw, ym, amount}，amount=null 清除。
        线上 Vercel 由 api/budan.py 经 GitHub API 提交回仓库，两端口径一致。"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            self._json_response(400, {"error": "请求体不是合法 JSON"})
            return
        shop = str(body.get("shopRaw", "")).strip()
        date = str(body.get("date", body.get("ym", ""))).strip()  # 兼容按天 YYYY-MM-DD / 旧按月键
        amount = body.get("amount")
        ok_fmt = (len(date) == 10 and date[4] == "-" and date[7] == "-") or (len(date) == 7 and date[4] == "-")
        if not shop or not ok_fmt:
            self._json_response(400, {"error": "参数不合法：需要 shopRaw / ym(YYYY-MM) / amount"})
            return
        if amount is not None:
            try:
                amount = round(float(amount), 2)
                if amount < 0:
                    raise ValueError
            except (TypeError, ValueError):
                self._json_response(400, {"error": "amount 需为非负数字或 null"})
                return
        try:
            data = json.loads(self.BUDAN_PATH.read_text(encoding="utf-8")) if self.BUDAN_PATH.exists() else {}
            if amount is None:
                data.get(shop, {}).pop(date, None)
                if shop in data and not data[shop]:
                    del data[shop]
            else:
                data.setdefault(shop, {})[date] = amount
            self.BUDAN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._json_response(200, {"ok": True, "data": data})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def _serve_api(self):
        if not HAS_DUCKDB:
            self._json_response(500, {"error": "duckdb not installed"})
            return
        if not DB_PATH.exists():
            self._json_response(404, {"error": "report.duckdb not found, run build script first"})
            return
        try:
            con = duckdb.connect(str(DB_PATH), read_only=True)
            try:
                data = self._load_data(con)
            finally:
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
        shop_display = {s["raw"]: s["display"] for s in shops}

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
            rec = {"date": row[0], "shopRaw": row[1], "shopDisplay": shop_display.get(row[1], row[1]), "skuCount": row[2], "gmv": row[3],
                   "units": row[4], "orders": row[5], "buyers": row[6], "visitors": row[7],
                   "conversion": row[8], "aov": row[9], "uvValue": row[10],
                   "refundAmount": row[11], "refundRate": row[12],
                   "baseline": parse_json(row[13]), "week": parse_json(row[14]),
                   "gmvOutbound": row[15], "unitsOutbound": row[16],
                   "stockValue": row[17], "out30dValue": row[18], "outMtdValue": row[19]}
            shop_daily.setdefault(row[1], []).append(rec)

        categories = {}
        for row in con.sql("SELECT * FROM categories ORDER BY date").fetchall():
            categories.setdefault(row[0], []).append({
                "path": row[1], "shopRaw": row[1].split("/")[0], "l1": row[2], "l2": row[3], "l3": row[4],
                "category1": row[2], "category2": row[3], "category3": row[4],
                "gmv": row[5], "units": row[6], "orders": row[7],
                "skuCount": row[8], "visitors": row[9], "refundAmount": row[10], "gmvOutbound": row[11],
            })

        top_skus = {}
        for row in con.sql("SELECT * FROM top_skus ORDER BY date,gmv DESC").fetchall():
            top_skus.setdefault(row[0], []).append({
                "shopRaw": row[1], "shopDisplay": shop_display.get(row[1], row[1]), "sku": row[2], "name": row[3],
                "gmv": row[4], "units": row[5], "visitors": row[6],
                "conversion": row[7], "uvValue": row[8], "refundAmount": row[9], "gmvOutbound": row[10],
            })

        city_stock = {}
        for row in con.sql("SELECT date,shop,sku,name,city,stock,daily_avg,days_cover,out_yesterday,out_7d,nat_stock,nat_days_cover,price,nat_transit,nat_out_yesterday,nat_out_7d FROM city_stock ORDER BY date,shop,sku,city").fetchall():
            days=row[7]
            if days is None:
                level="unknown"
            elif days<1:
                level="critical"
            elif days<3:
                level="warn"
            else:
                level="ok"
            city_stock.setdefault(row[0], []).append({
                "shopRaw": row[1], "shopDisplay": shop_display.get(row[1], row[1]),
                "sku": row[2], "name": row[3], "city": row[4],
                "stock": row[5], "dailyAvg": row[6], "daysCover": days, "level": level,
                "outYesterday": row[8], "out7d": row[9], "natStock": row[10],
                "natDaysCover": row[11], "price": row[12], "natTransit": row[13],
                "natOutYesterday": row[14], "natOut7d": row[15]})

        movers = {}
        for row in con.sql("SELECT * FROM movers ORDER BY date").fetchall():
            key = row[1] + "s"
            movers.setdefault(row[0], {}).setdefault(key, []).append({
                "shopRaw": row[2], "shopDisplay": shop_display.get(row[2], row[2]), "sku": row[3], "name": row[4],
                "previousGmv": row[5], "gmv": row[6], "delta": row[7],
            })

        alerts = {}
        for row in con.sql("SELECT * FROM alerts ORDER BY date").fetchall():
            alerts.setdefault(row[0], []).append({
                "level": row[1], "scope": row[2], "type": row[3],
                "detail": row[4], "current": row[5], "previous": row[6], "change": row[7],
            })

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
            "sourceDir": meta.get("sourceDir", "多平台导出（京东商智 + 唯品会 + 拼多多）"),
            "shops": shops,
            "platforms": json.loads(meta.get("platforms", '{"jd":"京东","vip":"唯品会"}')),
            "dates": dates,
            "overall": overall, "shopDaily": shop_daily,
            "categories": categories, "topSkus": top_skus,
            "movers": movers, "alerts": alerts,
            "quality": quality, "cityStock": city_stock, "moduleFilters": json.loads(meta.get("moduleFilters", "{}")), "targets": json.loads(meta.get("targets", "{}")),
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
