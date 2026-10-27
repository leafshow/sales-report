#!/usr/bin/env python3
"""万里牛 ERP 开放平台 API 客户端（沙箱/正式通用）。

凭证从 scripts/erp.local.json 读取（git-ignored，权限 600）：
{
  "appkey": "...",
  "secret": "...",
  "api_url": "https://erp-open.hupun.com/api"
}

用法：
    from hupun_client import hupun_api
    resp = hupun_api("erp/opentrade/query", {"page": 1, "limit": 10})

直接运行做连通性测试：
    python3 hupun_client.py
"""

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "erp.local.json"


def _load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"缺少配置文件 {CONFIG_PATH}，请按 README 说明创建（含 appkey/secret/api_url）"
        )
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("appkey", "secret", "api_url"):
        if not cfg.get(key):
            raise KeyError(f"erp.local.json 缺少必填字段: {key}")
    return cfg


def _sign(params, secret):
    """开放接口签名：key 升序 secret+k=quote(v)&...&secret，MD5 小写。"""
    s = secret
    for k, v in sorted(params.items()):
        s += f"{k}={_quote(str(v))}&"
    s = s.rstrip("&") + secret
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _quote(value):
    """与官方 CLI 一致的 quotePlus：encodeURIComponent + 保留字符转义 + 空格转 +。"""
    out = urllib.parse.quote(value, safe="")
    for ch in "!'()~":
        out = out.replace(f"%{ord(ch):02X}", f"%{ord(ch):02X}")
    return out.replace("%20", "+")


def hupun_api(path, params=None, method="post", timeout=30):
    """调用万里牛开放接口，返回解析后的 JSON。path 以 erp/ 开头。"""
    cfg = _load_config()
    path = path.lstrip("/")

    all_params = {}
    for k, v in (params or {}).items():
        all_params[k] = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    all_params["_app"] = cfg["appkey"]
    all_params["_t"] = str(int(time.time()))

    url = cfg["api_url"].rstrip("/")
    if "/api" not in url:
        url += "/api"
    url += "/" + path

    sign_src = {
        k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
        for k, v in all_params.items()
    }
    body = "&".join(f"{k}={_quote(v)}" for k, v in sorted(sign_src.items()))
    body += "&_sign=" + _sign(sign_src, cfg["secret"])

    if method == "get":
        req = urllib.request.Request(url, method="GET")
    else:
        data = body.encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    req.add_header("User-Agent", "sales-report-hupun-client/1.0")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


if __name__ == "__main__":
    # 沙箱限频 10 次/分钟，这里只发 1 次探测请求验证签名链路。
    result = hupun_api("erp/goods/catagorypage/query/v2", {"page": 1, "limit": 3})
    print(json.dumps(result, ensure_ascii=False, indent=2))
