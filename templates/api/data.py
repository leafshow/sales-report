"""Vercel Serverless Function — 从 DuckDB 读取数据返回 JSON（Flask 入口）。

数据组装逻辑在 api/data_common.py（与本地 server.py 共用），本文件只是 Flask 壳。
"""
import sys
from pathlib import Path

from flask import Flask, Response, request

# Vercel 打包后 api/ 不一定是包；把函数目录加入 sys.path 保证能 import data_common
sys.path.insert(0, str(Path(__file__).parent))
from data_common import connect, find_db, load_data  # noqa: E402

app = Flask(__name__)


def _find_db():
    return find_db(Path(__file__).parent)


def _load_con():
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return None, "duckdb module not installed"
    db_path = _find_db()
    if not db_path.exists():
        return None, f"database not found at {db_path}"
    try:
        return connect(db_path), None
    except Exception:
        return None, "cannot open database (read-only fs)"


def _resp(code, obj):
    return Response(
        json.dumps(obj, ensure_ascii=False) if isinstance(obj, dict) else obj,
        status=code,
        mimetype="application/json",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


import json  # noqa: E402


@app.route("/api/data", methods=["GET", "OPTIONS"])
def handler():
    if request.method == "OPTIONS":
        return _resp(204, None)
    con, err = _load_con()
    if err:
        return _resp(404, {"error": err})
    try:
        return _resp(200, load_data(con))
    except Exception as e:
        return _resp(500, {"error": str(e)})
    finally:
        con.close()
