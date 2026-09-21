#!/usr/bin/env python3
"""
accel_mirror_api.py — 只读 HTTP 接口（零依赖，纯标准库）
================================================================
把 references/mirrors.json 变成任何 AI agent 都能直接调用的接口：
不需要装客户端、不需要装 MCP、不需要克隆仓库，一个 GET 就能拿到
「当前最快用哪个源 + 该敲什么命令」。

设计原则
--------
1. **只读**：不写文件、不改数据库、不发起任何出站请求。
2. **不做代理探测**：接口不提供「帮我测一下任意 URL」的能力，因为它会变成
   SSRF 跳板。存活数据由 CI 与本地 scripts/test_mirrors.sh 产出。
3. **答案优先**：返回体里 answer/commands 是可直接执行的命令，而不是让
   调用方自己拼 URL。

Endpoints
---------
    GET /                          接口索引（Accept: text/html 时返回 HTML 页面）
    GET /v1/health                 数据版本 / 新鲜度 / 各类源数量
    GET /v1/services               支持的服务名与别名
    GET /v1/best?service=pip       最优源 + 可执行命令（核心接口）
        可选参数: limit=3, include_deprecated=1, format=text
    GET /v1/list?category=github   按分类列出源（limit=20, include_deprecated=1）
    GET /v1/dataset                原始 mirrors.json（给需要全量数据的 agent）

用法
----
    python3 server/accel_mirror_api.py                    # 127.0.0.1:8787
    python3 server/accel_mirror_api.py --host 0.0.0.0 --port 8787
    python3 server/accel_mirror_api.py --self-test        # 不起服务，自检并打印结果
"""

import argparse
import io
import json
import os
import re
import sys
import threading
from datetime import datetime, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 保证中文输出在 Windows 控制台（cp936）下也不炸
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API_VERSION = "1.0.0"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "references", "mirrors.json")
DEFAULT_RECIPES = os.path.join(REPO_ROOT, "references", "recipes.json")

# 数据超过这个天数就提示「该重新实测了」
STALE_DAYS = 7


def _load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


class Dataset:
    """带 mtime 缓存的数据库读取器（改库后无需重启服务）。"""

    def __init__(self, db_path, recipes_path):
        self.db_path = db_path
        self.recipes_path = recipes_path
        self._lock = threading.Lock()
        self._db_mtime = None
        self._rc_mtime = None
        self.db = {}
        self.recipes = {}
        self._reload()

    def _reload(self):
        db_mtime = os.path.getmtime(self.db_path)
        rc_mtime = os.path.getmtime(self.recipes_path)
        if db_mtime != self._db_mtime:
            self.db = _load_json(self.db_path)
            self._db_mtime = db_mtime
        if rc_mtime != self._rc_mtime:
            self.recipes = _load_json(self.recipes_path)
            self._rc_mtime = rc_mtime

    def get(self):
        with self._lock:
            self._reload()
            return self.db, self.recipes


# ---------------------------------------------------------------- 服务名解析

def build_alias_index(recipes):
    """服务名/别名 → 规范服务名（大小写不敏感）。"""
    index = {}
    for name, spec in recipes.get("services", {}).items():
        index[name.lower()] = name
        for alias in spec.get("aliases", []) or []:
            index[alias.strip().lower()] = name
            index[alias.strip().lower().replace(" ", "")] = name
    return index


def resolve_service(recipes, raw):
    """把用户给的 service 解析成 (规范名, 定义)。找不到返回 (None, None)。"""
    if not raw:
        return None, None
    key = str(raw).strip().lower()
    index = build_alias_index(recipes)
    name = index.get(key) or index.get(key.replace(" ", ""))
    if name:
        return name, recipes["services"][name]
    return None, None


def _has_suffix(url, suffix):
    if not suffix:
        return True
    return url.rstrip("/").endswith(suffix.rstrip("/"))


def render_url(mirror, spec, strip_scheme=False):
    """把源的 url 渲染成模板里 {url} 该替换成的形式。

    strip_scheme: Docker 镜像引用不能带协议头（docker pull https://x 是错的，
    必须是 docker pull x），所以 docker 家族的模板要剥掉 scheme。
    """
    url = (mirror.get("url") or "").rstrip("/")
    suffix = spec.get("url_suffix")
    if suffix and not _has_suffix(url, suffix):
        url += suffix
    if strip_scheme:
        url = re.sub(r"^https?://", "", url)
    return url


def _render(tpl, mirror, spec):
    return tpl.replace("{url}", render_url(mirror, spec, bool(spec.get("strip_scheme"))))


def build_commands(mirror, spec):
    """给一个源生成可直接执行的命令列表（按可信度排序）。

    优先级：
      1. command_by_type —— 配方针对 proxy_type（prefix/domain/web）的精确模板，
         因为它能正确处理「前缀代理要拼完整 GitHub URL」这类差异；
      2. usage —— 源作者手写的完整命令，最权威；
      3. usage_examples —— 源作者给的示例（按 usage_prefer 挑最贴合本次意图的）；
      4. command —— 配方兜底模板，仅在以上都缺失时使用。
    """
    cmds = []

    by_type = (spec.get("command_by_type") or {}).get(mirror.get("proxy_type") or "")
    if by_type:
        cmds.append(_render(by_type, mirror, spec))

    if mirror.get("usage"):
        cmds.append(mirror["usage"])

    examples = mirror.get("usage_examples") or []
    if examples:
        prefer = spec.get("usage_prefer")
        if prefer:
            for ex in examples:
                if prefer.lower() in ex.lower():
                    cmds.append(ex)
                    break
        else:
            cmds.extend(examples[:2])

    if not cmds and spec.get("command"):
        cmds.append(_render(spec["command"], mirror, spec))

    out = []
    for c in cmds:
        if c and c not in out:
            out.append(c)
    return out[:3]


def build_persist(mirror, spec):
    """配置持久化的写法。注意：daemon.json / config 里需要完整 URL，不剥 scheme。"""
    tpl = spec.get("persist")
    if not tpl:
        return None
    return tpl.replace("{url}", render_url(mirror, spec, strip_scheme=False))


def sort_key(m):
    lat = m.get("test_time_ms")
    lat = lat if isinstance(lat, int) and lat > 0 else 10 ** 9
    return (-m.get("score", 0), lat)


def select_mirrors(data, spec, limit, include_deprecated, types=None):
    category = spec.get("category")
    mirrors = (data.get("mirrors", {}) or {}).get(category, []) or []
    pattern = spec.get("match")
    rx = re.compile(pattern, re.I) if pattern else None

    # 默认排除掉不可自动化的类型（如 github 分类里的 web 网页工具），
    # 调用方可用 ?types=prefix,web 显式覆盖
    allow = None
    if types:
        allow = {t.strip().lower() for t in types.split(",") if t.strip()}
    elif spec.get("exclude_types"):
        allow = None
        denied = {t.lower() for t in spec["exclude_types"]}
    else:
        denied = set()

    picked = []
    for m in mirrors:
        if rx and not rx.search(m.get("name", "")):
            continue
        if not include_deprecated and m.get("status") == "deprecated":
            continue
        mtype = (m.get("proxy_type") or "").lower()
        if allow is not None and mtype and mtype not in allow:
            continue
        if allow is None and mtype and mtype in denied:
            continue
        picked.append(m)
    picked.sort(key=sort_key)
    return picked[:limit] if limit and limit > 0 else picked


# ---------------------------------------------------------------- 响应组装

def dataset_meta(data):
    last_test = data.get("last_full_test") or data.get("last_updated")
    age = None
    if last_test:
        try:
            age = (date.today() - datetime.strptime(last_test, "%Y-%m-%d").date()).days
        except ValueError:
            age = None
    return {
        "version": data.get("version"),
        "last_full_test": last_test,
        "age_days": age,
        "mirror_count": sum(len(v) for v in (data.get("mirrors", {}) or {}).values()),
        "categories": {k: len(v) for k, v in (data.get("mirrors", {}) or {}).items()},
    }


def response_for_best(data, recipes, service_raw, limit, include_deprecated, types=None):
    name, spec = resolve_service(recipes, service_raw)
    if not spec:
        # 退路：允许直接传分类名（如 service=python、service=docker_community）
        raw = str(service_raw or "").strip()
        if raw in (data.get("mirrors", {}) or {}):
            name, spec = raw, {"category": raw, "aliases": []}
    if not spec:
        known = sorted(recipes.get("services", {}).keys())
        return 404, {
            "error": "unknown_service",
            "message": "不支持的服务名 '%s'。GET /v1/services 可查看全部可用名。" % service_raw,
            "known_services": known,
            "hint": "也可以直接传分类名，例如 service=python / service=docker_community（GET /v1/health 里有分类列表）",
        }

    picked = select_mirrors(data, spec, limit, include_deprecated, types)
    if not picked:
        return 404, {
            "error": "no_mirror",
            "message": "服务 '%s' 在分类 %s 下没有匹配的活跃源。" % (name, spec.get("category")),
            "service": name,
        }

    items = []
    for i, m in enumerate(picked, 1):
        items.append({
            "rank": i,
            "name": m.get("name"),
            "url": m.get("url"),
            "type": m.get("proxy_type"),
            "score": m.get("score"),
            "latency_ms": m.get("test_time_ms"),
            "throughput_bps": m.get("throughput_bps"),
            "samples": m.get("samples"),
            "latency_spread_ms": ([m.get("latency_min_ms"), m.get("latency_max_ms")]
                                  if m.get("latency_min_ms") is not None else None),
            "failed_reports": m.get("failed_reports"),
            "status": m.get("status"),
            "last_tested": m.get("last_tested"),
            "last_ci_alive": m.get("last_ci_alive"),
            "commands": build_commands(m, spec),
            "persist": build_persist(m, spec),
            "notes": m.get("notes"),
        })

    best = items[0]
    meta = dataset_meta(data)
    caveats = []
    if meta["age_days"] is None:
        caveats.append("数据库没有实测日期，分数可能已过期。")
    elif meta["age_days"] > STALE_DAYS:
        caveats.append("数据库已 %d 天未整体实测，建议先运行 scripts/test_mirrors.sh 再采信排名。"
                       % meta["age_days"])
    if spec.get("exclude_types"):
        caveats.append("已按配方排除不可自动化的类型 %s（如需包含，加 ?types= 参数显式指定）。"
                       % ",".join(spec["exclude_types"]))
    if best.get("failed_reports"):
        caveats.append("最优源在众包上报中失败过 %d 次（既能成功也会失败），属不稳定源，"
                       "建议同时准备 mirrors 里的备用源。" % best["failed_reports"])
    if best.get("samples") is None:
        caveats.append("该源只有单机实测数据，尚无多份众包上报（samples 为空），可信度有限。")
    caveats.append("分数来自社区实测，不同运营商/省份结果有差异，属正常现象。")

    return 200, {
        "service": name,
        "category": spec.get("category"),
        "query": service_raw,
        "answer": best["commands"][0] if best["commands"] else None,
        "best": best,
        "mirrors": items,
        "persist": best.get("persist"),
        "guide": spec.get("guide"),
        "dataset": meta,
        "caveats": caveats,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def response_for_list(data, recipes, category, limit, include_deprecated, types=None):
    cats = (data.get("mirrors", {}) or {})
    if category not in cats:
        return 404, {"error": "unknown_category",
                     "message": "未知分类 '%s'" % category,
                     "known_categories": sorted(cats.keys())}
    allow = None
    if types:
        allow = {t.strip().lower() for t in types.split(",") if t.strip()}
    mirrors = []
    for m in cats[category]:
        if not include_deprecated and m.get("status") == "deprecated":
            continue
        if allow is not None and (m.get("proxy_type") or "").lower() not in allow:
            continue
        mirrors.append(m)
    mirrors.sort(key=sort_key)
    if limit and limit > 0:
        mirrors = mirrors[:limit]
    return 200, {
        "category": category,
        "count": len(mirrors),
        "mirrors": [{
            "name": m.get("name"),
            "url": m.get("url"),
            "type": m.get("proxy_type"),
            "score": m.get("score"),
            "latency_ms": m.get("test_time_ms"),
            "samples": m.get("samples"),
            "status": m.get("status"),
            "last_tested": m.get("last_tested"),
            "commands": build_commands(m, {"category": category}),
            "notes": m.get("notes"),
        } for m in mirrors],
        "dataset": dataset_meta(data),
    }


def response_for_health(data, recipes):
    meta = dataset_meta(data)
    active = deprecated = 0
    for cat_mirrors in (data.get("mirrors", {}) or {}).values():
        for m in cat_mirrors:
            if m.get("status") == "deprecated":
                deprecated += 1
            else:
                active += 1
    return 200, {
        "status": "ok",
        "api_version": API_VERSION,
        "dataset": meta,
        "active": active,
        "deprecated": deprecated,
        "services": len(recipes.get("services", {})),
        "last_ci_test": data.get("last_ci_test"),
        "stale": bool(meta["age_days"] is not None and meta["age_days"] > STALE_DAYS),
    }


def response_for_services(recipes):
    services = []
    for name, spec in sorted(recipes.get("services", {}).items()):
        services.append({
            "service": name,
            "aliases": spec.get("aliases", []),
            "category": spec.get("category"),
            "guide": spec.get("guide"),
        })
    return 200, {"count": len(services), "services": services}


# ---------------------------------------------------------------- HTML 首页

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>accel-mirror API</title>
<style>
 body{font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
      max-width:820px;margin:40px auto;padding:0 20px;color:#1f2328;line-height:1.65}
 h1{font-size:1.5rem;margin-bottom:.2em} .sub{color:#656d76;margin-top:0}
 code{background:#f6f8fa;padding:.15em .4em;border-radius:5px;font-size:.9em}
 pre{background:#f6f8fa;padding:12px 14px;border-radius:8px;overflow-x:auto;border:1px solid #d8dee4}
 table{border-collapse:collapse;width:100%;margin:1em 0}
 th,td{border:1px solid #d8dee4;padding:8px 10px;text-align:left;font-size:.94em}
 th{background:#f6f8fa}
 .stale{color:#9a6700;background:#fff8c5;border:1px solid #d4a72c;padding:8px 12px;border-radius:8px}
</style></head><body>
<h1>accel-mirror API</h1>
<p class="sub">只读接口 · 数据版本 __VERSION__ · 上次整体实测 __LAST_TEST__</p>
__STALE__
<h2>接口</h2>
<table>
<tr><th>路径</th><th>说明</th></tr>
<tr><td><code>GET /v1/best?service=pip</code></td><td>最优源 + 可直接执行的命令（核心）</td></tr>
<tr><td><code>GET /v1/list?category=github&amp;limit=10</code></td><td>按分类列出源</td></tr>
<tr><td><code>GET /v1/services</code></td><td>支持的服务名与别名</td></tr>
<tr><td><code>GET /v1/health</code></td><td>数据版本与新鲜度</td></tr>
<tr><td><code>GET /v1/dataset</code></td><td>原始数据库</td></tr>
</table>
<h2>试试</h2>
<pre>curl -s "http://HOST/v1/best?service=pip" | head -40</pre>
<pre>curl -s "http://HOST/v1/best?service=huggingface&amp;limit=3"</pre>
<p class="sub">数据源：<code>references/mirrors.json</code> · 源码仓库
<a href="https://github.com/gitfox-enter/accel-mirror">gitfox-enter/accel-mirror</a></p>
</body></html>
"""


def index_html(data, host):
    meta = dataset_meta(data)
    stale = ""
    if meta["age_days"] is not None and meta["age_days"] > STALE_DAYS:
        stale = ('<p class="stale">⚠️ 数据库已 %d 天未整体实测，排名可能已过期。'
                 '建议先在本地运行 <code>bash scripts/test_mirrors.sh</code>。</p>' % meta["age_days"])
    return (INDEX_HTML
            .replace("__VERSION__", str(meta["version"]))
            .replace("__LAST_TEST__", str(meta["last_full_test"]))
            .replace("__STALE__", stale)
            .replace("HOST", host))


# ---------------------------------------------------------------- HTTP 层

class Handler(BaseHTTPRequestHandler):
    server_version = "accel-mirror-api/" + API_VERSION
    protocol_version = "HTTP/1.1"
    quiet = False

    # ---- 工具 ----
    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if not Handler.quiet:
            sys.stderr.write("[api] %s - %s\n" % (self.address_string(), fmt % args))

    def _q(self):
        return parse_qs(urlparse(self.path).query, keep_blank_values=True)

    def _int(self, q, key, default):
        try:
            return int(q.get(key, [default])[0])
        except (TypeError, ValueError):
            return default

    def _bool(self, q, key):
        return str(q.get(key, ["0"])[0]).lower() in ("1", "true", "yes", "on")

    # ---- 路由 ----
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        q = self._q()
        data, recipes = self.server.dataset.get()

        try:
            if path in ("/", ""):
                if "text/html" in (self.headers.get("Accept") or ""):
                    host = self.headers.get("Host") or "127.0.0.1"
                    return self._send(200, index_html(data, host).encode("utf-8"),
                                      "text/html; charset=utf-8")
                return self._send(200, {
                    "name": "accel-mirror API",
                    "api_version": API_VERSION,
                    "read_only": True,
                    "dataset": dataset_meta(data),
                    "endpoints": {
                        "/v1/best?service=<name>": "最优源 + 可执行命令",
                        "/v1/list?category=<cat>&limit=<n>": "按分类列源",
                        "/v1/services": "支持的服务名",
                        "/v1/health": "健康与新鲜度",
                        "/v1/dataset": "原始 mirrors.json",
                    },
                    "docs": "https://github.com/gitfox-enter/accel-mirror",
                })

            if path == "/v1/health":
                return self._send(*response_for_health(data, recipes))

            if path == "/v1/services":
                return self._send(*response_for_services(recipes))

            if path == "/v1/dataset":
                return self._send(200, data)

            if path == "/v1/best":
                service = q.get("service", q.get("type", ["docker"]))[0]
                code, payload = response_for_best(
                    data, recipes, service,
                    self._int(q, "limit", 3), self._bool(q, "include_deprecated"),
                    q.get("types", [None])[0])
                if code == 200 and q.get("format", [""])[0] == "text":
                    lines = ["# %s → 用 %s" % (payload["service"], payload["best"]["name"])]
                    lines += ["  " + c for c in payload["best"]["commands"]]
                    return self._send(code, ("\n".join(lines) + "\n").encode("utf-8"),
                                      "text/plain; charset=utf-8")
                return self._send(code, payload)

            if path == "/v1/list":
                category = q.get("category", [""])[0]
                return self._send(*response_for_list(
                    data, recipes, category,
                    self._int(q, "limit", 20), self._bool(q, "include_deprecated"),
                    q.get("types", [None])[0]))

            return self._send(404, {"error": "not_found", "path": self.path,
                                    "hint": "GET / 查看接口索引"})
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001 — 服务不能因为单个请求崩掉
            self._send(500, {"error": "internal_error", "message": str(exc)})

    def do_HEAD(self):
        self.do_GET()


# ---------------------------------------------------------------- 自检 / 启动

def self_test(db_path, recipes_path):
    data = _load_json(db_path)
    recipes = _load_json(recipes_path)
    print("== accel-mirror API 自检 ==")
    code, health = response_for_health(data, recipes)
    print("health      -> %s %s" % (code, json.dumps(health["dataset"], ensure_ascii=False)))
    code, svc = response_for_services(recipes)
    print("services    -> %s %d 个服务" % (code, svc["count"]))
    ok = 0
    problems = []
    for s in ["pip", "pytorch", "huggingface", "docker", "github", "ghcr", "npm", "conda", "apt"]:
        code, payload = response_for_best(data, recipes, s, 2, False)
        if code == 200:
            ok += 1
            answer = payload["answer"] or ""
            print("best(%-12s) -> %-28s %s" % (s, payload["best"]["name"], answer))
            # 断言：Docker 家族的命令不能带协议头（docker pull https://x 是错的）
            if s in ("docker", "docker-enterprise", "ghcr", "quay", "gcr", "k8s", "nvcr"):
                if "://" in answer.split()[-1]:
                    problems.append("%s 的 docker 命令带了 scheme: %s" % (s, answer))
            # 断言：github 的答案应是可执行的 git clone，而不是网页工具
            if s == "github" and "git clone" not in answer:
                problems.append("github 的答案不可自动化: %s" % answer)
        else:
            print("best(%-12s) -> ERROR %s" % (s, payload.get("message")))
    code, bad = response_for_best(data, recipes, "no-such-service", 1, False)
    print("unknown     -> %s %s" % (code, bad["error"]))
    code, cat = response_for_list(data, recipes, "github", 3, False)
    print("list(github)-> %s 前 3: %s" % (code, [m["name"] for m in cat["mirrors"]]))
    code, cat2 = response_for_best(data, recipes, "python", 2, False)
    print("category名   -> %s 直接传分类名可用: %s" % (code, code == 200))
    if problems:
        print("❌ 断言失败:")
        for p in problems:
            print("   - " + p)
    print("结论: %d/9 服务解析成功, %d 个断言失败" % (ok, len(problems)))
    return 0 if ok >= 8 and not problems else 1


def main():
    ap = argparse.ArgumentParser(
        description="accel-mirror 只读 HTTP 接口（零依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python3 server/accel_mirror_api.py --port 8787\n"
               "  python3 server/accel_mirror_api.py --self-test")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1，对外请显式设 0.0.0.0）")
    ap.add_argument("--port", type=int, default=8787, help="监听端口（默认 8787）")
    ap.add_argument("--db", default=DEFAULT_DB, help="mirrors.json 路径")
    ap.add_argument("--recipes", default=DEFAULT_RECIPES, help="recipes.json 路径")
    ap.add_argument("--quiet", action="store_true", help="不打印每个请求的访问日志")
    ap.add_argument("--self-test", action="store_true", help="不起服务，跑自检并退出")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test(args.db, args.recipes))

    for p in (args.db, args.recipes):
        if not os.path.exists(p):
            print("❌ 找不到文件: %s" % p, file=sys.stderr)
            sys.exit(1)

    Handler.quiet = args.quiet
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.dataset = Dataset(args.db, args.recipes)
    data, recipes = httpd.dataset.get()
    meta = dataset_meta(data)

    print("accel-mirror API v%s" % API_VERSION)
    print("  监听   : http://%s:%d" % (args.host, args.port))
    print("  数据   : %s (v%s, %d 源, 上次实测 %s)"
          % (args.db, meta["version"], meta["mirror_count"], meta["last_full_test"]))
    print("  服务   : %d 个（/v1/services 查看）" % len(recipes.get("services", {})))
    print("  只读   : 不写库、不发起出站请求（无 SSRF 面）")
    print("  退出   : Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
