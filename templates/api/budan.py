"""Vercel Serverless Function — 补单金额写入接口

店长在前端填写补单金额 → POST /api/budan → 本函数用 GitHub Contents API
把 templates/budan.json 提交回仓库（覆盖更新），push 自动触发 Vercel 重新部署，
所有访问者随即看到最新值。

需在 Vercel 项目环境变量配置：
  GITHUB_TOKEN  — Fine-grained PAT，仅授权本仓库 Contents: Read and write
  GITHUB_REPO   — 如 leafshow/sales-report（未配置时默认）
"""
import base64
import json
import os
from pathlib import Path

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

REPO = os.environ.get("GITHUB_REPO", "leafshow/sales-report")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")
FILE_PATH = "templates/budan.json"
API = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
# requests 在 Vercel Python runtime 内置；缺失时回退 urllib（本地无 requests 环境也能 GET）
try:
    import requests as _rq
except ImportError:  # pragma: no cover
    _rq = None


def _resp(code, obj):
    return Response(
        json.dumps(obj, ensure_ascii=False),
        status=code,
        mimetype="application/json",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


def _auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@app.route("/api/budan", methods=["GET", "POST", "OPTIONS"])
def handler():
    if request.method == "OPTIONS":
        return _resp(204, None)

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return _resp(500, {
            "error": "保存服务未配置（管理员未设置 GITHUB_TOKEN 环境变量）。本地填写不受影响；请联系管理员在 Vercel 配置后再试。"
        })

    if request.method == "GET":
        # 读取当前值（优先本地打包文件，避免函数冷启动多一次 API 调用）
        local = Path(__file__).parent / "budan.json"
        try:
            if local.exists():
                return _resp(200, json.loads(local.read_text(encoding="utf-8")))
        except Exception:
            pass
        try:
            r = _rq.get(API, headers=_auth_headers(token), timeout=15)
            r.raise_for_status()
            return _resp(200, json.loads(base64.b64decode(r.json()["content"])))
        except Exception as e:
            return _resp(502, {"error": f"读取失败: {e}"})

    # POST：{shopRaw, date(YYYY-MM-DD 或兼容 ym YYYY-MM), amount}  amount=null 表示清除
    body = request.get_json(silent=True) or {}
    shop = str(body.get("shopRaw", "")).strip()
    date = str(body.get("date", body.get("ym", ""))).strip()
    amount = body.get("amount")
    ok_fmt = (len(date) == 10 and date[4] == "-" and date[7] == "-") or (len(date) == 7 and date[4] == "-")
    if not shop or not ok_fmt:
        return _resp(400, {"error": "参数不合法：需要 shopRaw / date(YYYY-MM-DD) / amount"})
    if amount is not None:
        try:
            amount = round(float(amount), 2)
            if amount < 0:
                raise ValueError
        except (TypeError, ValueError):
            return _resp(400, {"error": "amount 需为非负数字或 null"})

    try:
        # 取远端当前文件（sha 用于覆盖提交）
        r = _rq.get(API, headers=_auth_headers(token),
                         params={"ref": BRANCH}, timeout=15)
        r.raise_for_status()
        info = r.json()
        data = json.loads(base64.b64decode(info["content"]))
        # 覆盖更新：以本次填入数为该店铺该月的最新值
        # 0 元为无效值：等同于删除该条目（不写入 budan.json，也不产生 0 元提交记录）
        if amount is None or amount == 0:
            data.get(shop, {}).pop(date, None)
            if shop in data and not data[shop]:
                del data[shop]
        else:
            data.setdefault(shop, {})[date] = amount
        # 数据与远端一致（如对不存在的条目提交 0 元）时不再产生空提交
        if data == json.loads(base64.b64decode(info["content"])):
            return _resp(200, {"ok": True, "data": data, "unchanged": True})
        payload = {
            "message": f"chore(budan): 更新补单金额 {shop} {date} -> {amount}",
            "content": base64.b64encode(
                json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            ).decode("ascii"),
            "sha": info["sha"],
            "branch": BRANCH,
        }
        w = _rq.put(API, headers=_auth_headers(token),
                         data=json.dumps(payload), timeout=20)
        w.raise_for_status()
        return _resp(200, {"ok": True, "data": data})
    except _rq.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", "")
        except Exception:
            pass
        return _resp(e.response.status_code if e.response is not None else 502,
                     {"error": f"GitHub 提交失败: {e} {detail}"})
    except Exception as e:
        return _resp(502, {"error": str(e)})
