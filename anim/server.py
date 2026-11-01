#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
双均线 + 趋势过滤「安检门」动画 · 轻量后端
================================================
零额外依赖（仅用 Python 标准库 http.server + 已安装的 akshare/pandas）。

它复用父项目 ashare_quant 的 src/data_utils.get_price —— 即：
  - 多源回退（东财→新浪→腾讯）
  - 本地缓存 data/raw/*.csv（与 Streamlit 网页、回测共用同一份数据）
  - qfq/hfq 复权端到端透传

启动：  python server.py            # 默认 http://localhost:8765
        python server.py --port 9000
然后浏览器打开 http://localhost:8765

接口：
  GET /                      返回 index.html（动画网页）
  GET /api/quote?code=600519&start=20200101&end=20261101&adjust=qfq&source=auto
        -> {"ok":true, "code","name","n","start","end","dates":[...],"price":[...]}
        -> {"ok":false, "msg":"..."}
"""
import os
import sys
import json
import argparse
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---- 把父项目的 src 加入路径，复用 data_utils（数据层）----
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT_SRC = os.path.join(os.path.dirname(HERE), "src")
if PARENT_SRC not in sys.path:
    sys.path.insert(0, PARENT_SRC)
import data_utils  # noqa: E402

PORT = 8765
_NAME_CACHE = {}  # code -> 名称（进程内缓存，避免重复查询/限流）


def get_name(code):
    """尽力获取股票/ETF 简称；失败则回退为代码本身。"""
    if code in _NAME_CACHE:
        return _NAME_CACHE[code]
    name = code
    try:
        import akshare as ak
        info = ak.stock_individual_info_em(symbol=code)
        for row in info.itertuples():
            key = str(row[0])
            if key in ("股票简称", "股票名称"):
                name = str(row[1])
                break
    except Exception:
        name = code
    _NAME_CACHE[code] = name
    return name
INDEX_PATH = os.path.join(HERE, "index.html")

with open(INDEX_PATH, encoding="utf-8") as _f:
    INDEX_HTML = _f.read()


def _to_str(x):
    """把日期/数值统一转成可 JSON 序列化的字符串/数字。"""
    try:
        return str(x)[:10] if hasattr(x, "strftime") else str(x)
    except Exception:
        return str(x)


class Handler(BaseHTTPRequestHandler):
    # 安静日志
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
            return

        if u.path == "/api/quote":
            q = urllib.parse.parse_qs(u.query)
            code = (q.get("code", ["600519"])[0]).strip()
            start = (q.get("start", ["20200101"])[0]).strip()
            end = (q.get("end", ["20261101"])[0]).strip()
            adjust = (q.get("adjust", ["qfq"])[0]).strip()
            source = (q.get("source", ["auto"])[0]).strip()
            try:
                df = data_utils.get_price(
                    code, start, end, adjust=adjust, source=source
                )
                dates = [_to_str(d) for d in df["日期"].tolist()]
                price = [round(float(p), 2) for p in df["收盘"].tolist()]
                name = get_name(code)
                if not price:
                    self._send(200, json.dumps(
                        {"ok": False, "msg": "该代码未返回数据，请检查代码或日期区间"},
                        ensure_ascii=False))
                    return
                self._send(200, json.dumps({
                    "ok": True, "code": code, "name": name,
                    "n": len(price), "start": dates[0], "end": dates[-1],
                    "dates": dates, "price": price,
                }, ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps(
                    {"ok": False, "msg": f"拉取失败：{e}"}, ensure_ascii=False))
            return

        self._send(404, json.dumps({"ok": False, "msg": "not found"},
                                   ensure_ascii=False))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()


def main():
    ap = argparse.ArgumentParser(description="双均线趋势过滤动画后端")
    ap.add_argument("--port", type=int, default=PORT, help="监听端口")
    ap.add_argument("--host", default="0.0.0.0", help="监听地址")
    args = ap.parse_args()
    srv = HTTPServer((args.host, args.port), Handler)
    print("=" * 56)
    print(" 双均线 + 240 趋势过滤「安检门」动画已启动")
    print(f" 在浏览器打开：  http://localhost:{args.port}")
    print(" 数据来源：父项目 ashare_quant/src/data_utils（多源回退 + 本地缓存）")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
