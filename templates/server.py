"""本地开发服务器 — 同时提供静态文件和 /api/data、/api/budan 接口。

/api/data 的数据组装逻辑与 Vercel 线上函数共用 api/data_common.py，
保证本地预览与线上口径一致；本文件只是 HTTP 壳。
"""
import json
import sys
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "api"))
from data_common import connect, find_db, load_data  # noqa: E402

try:
    import duckdb  # noqa: F401
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
        """本地直写 budan.json：{shopRaw, date(或ym), amount}，amount=null 清除。
        线上 Vercel 由 api/budan.py 经 GitHub API 提交回仓库，两端口径一致。"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n)) if n else {}
            if not isinstance(body, dict):
                self._json_response(400, {"error": "body 需为 JSON 对象"})
                return
            shop = str(body.get("shopRaw", "")).strip()
            date = str(body.get("date", body.get("ym", ""))).strip()  # 兼容按天 YYYY-MM-DD / 旧按月键
            amount = body.get("amount")
            ok_fmt = (len(date) == 10 and date[4] == "-" and date[7] == "-") or (len(date) == 7 and date[4] == "-")
            if not shop or not ok_fmt:
                self._json_response(400, {"error": "参数不合法：需要 shopRaw / date(YYYY-MM-DD) / amount"})
                return
            if amount is not None:
                try:
                    amount = round(float(amount), 2)
                except (TypeError, ValueError):
                    self._json_response(400, {"error": "amount 需为数字或 null（正=线下补录，负=异常剔除）"})
                    return
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
        db_path = find_db(Path(__file__).parent / "api")
        if not db_path.exists():
            self._json_response(404, {"error": "report.duckdb not found, run build script first"})
            return
        try:
            con = connect(db_path)
            try:
                data = load_data(con)
            finally:
                con.close()
            self._json_response(200, data)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
            self._json_response(500, {"error": str(e)})

    def _json_response(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    import os
    os.chdir(Path(__file__).parent)  # 静态文件以 templates/ 为根
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"📊 京东销售日报 — 本地服务器")
    print(f"   HTML: http://127.0.0.1:{port}/index.html")
    print(f"   API:  http://127.0.0.1:{port}/api/data")
    print(f"   按 Ctrl+C 停止")
    server.serve_forever()
