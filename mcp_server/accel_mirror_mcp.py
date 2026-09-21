#!/usr/bin/env python3
"""accel-mirror MCP server.

Exposes the accel-mirror database (references/mirrors.json) to any MCP-capable
AI client over stdio, so the model can look up China-accessible mirrors as a
tool call instead of reading files or guessing URLs.

Zero dependencies: standard library only. Python 3.9+.

Tools
-----
best_mirror(service, limit, include_deprecated, types)
    Resolve a service / scenario name (English or Chinese colloquial alias) to
    the best currently-measured mirrors, with ready-to-run commands.
list_mirrors(service?, include_deprecated)
    Category overview, or every mirror behind one service / category.
test_mirror(url, timeout)
    Live-probe a single URL and report status + latency.

Design note — single source of truth
------------------------------------
Service-name resolution, mirror selection and command building live in
``server/accel_mirror_api.py``; this file *imports* that module rather than
reimplementing it. The HTTP endpoint and this MCP server therefore cannot
drift apart: the same request always produces the same answer. (An earlier
version duplicated a weaker subset here, and the two paths really did diverge
— `best_mirror(service="pip")` returned "unknown category". That is why the
logic now lives in exactly one place.)

The one deliberate difference: `test_mirror` probes a URL from this machine.
The public HTTP endpoint offers no equivalent, because "probe any URL" on a
public server is an SSRF pivot. Running locally, that risk does not exist.

Run it (the client usually starts it for you):
    python3 mcp_server/accel_mirror_mcp.py
"""
import importlib.util
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

SERVER_NAME = "accel-mirror"
FALLBACK_VERSION = "1.7.0"
PROTOCOL_DEFAULT = "2025-06-18"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "references", "mirrors.json")
RECIPES_PATH = os.path.join(ROOT, "references", "recipes.json")
API_PATH = os.path.join(ROOT, "server", "accel_mirror_api.py")

# 纯显示用（分类的中文名）。解析与选源逻辑一律不在这里实现。
CATEGORY_LABELS = {
    "docker_community": "Docker 社区镜像",
    "docker_enterprise": "Docker 企业镜像",
    "github": "GitHub 加速",
    "tools": "常用工具源",
    "ai_models": "AI 模型仓库",
    "python": "Python 包管理",
    "dev_registry": "容器仓库镜像",
}


def log(msg):
    """Diagnostics go to stderr — stdout is reserved for JSON-RPC."""
    sys.stderr.write("[accel-mirror] %s\n" % msg)
    sys.stderr.flush()


# --------------------------------------------------------------------------- #
# 复用 HTTP 层的实现（唯一事实来源）
# --------------------------------------------------------------------------- #

_API = None


def api():
    """惰性导入 server/accel_mirror_api.py，共享它的解析与命令生成逻辑。"""
    global _API
    if _API is None:
        spec = importlib.util.spec_from_file_location("accel_mirror_api", API_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _API = mod
    return _API


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def dataset():
    return load_json(DB_PATH), load_json(RECIPES_PATH)


def server_version():
    """版本号从数据库读，不硬编码——否则又是一个会腐烂的常量。"""
    try:
        return dataset()[0].get("version") or FALLBACK_VERSION
    except Exception:  # noqa: BLE001
        return FALLBACK_VERSION


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

def fmt_choice(item, mark=""):
    """渲染 HTTP 层返回的 mirror 对象（含 commands 列表）。"""
    head = "%s%s. %s  [score %s · %s%s%s]" % (
        mark, item["rank"], item.get("name"),
        item.get("score"),
        ("%s ms" % item["latency_ms"]) if item.get("latency_ms") else "延迟未知",
        (" · %s" % item["type"]) if item.get("type") else "",
        (" · samples %d" % item["samples"]) if item.get("samples") else "",
    )
    lines = [head, "    url: %s" % item.get("url", "")]
    cmds = item.get("commands") or []
    if cmds:
        lines.append("    执行: %s" % cmds[0])
        for extra in cmds[1:]:
            lines.append("    备选: %s" % extra)
    if item.get("failed_reports"):
        lines.append("    ⚠ 不稳定：众包上报中失败过 %d 次，建议同时准备备用源"
                     % item["failed_reports"])
    return "\n".join(lines)


def fmt_db_row(index, m):
    """渲染 mirrors.json 里的原始条目（list_mirrors 用）。"""
    lines = ["%d. %s  [score %s]" % (index, m.get("name"), m.get("score", 0))]
    lines.append("    url: %s" % m.get("url", ""))
    if m.get("test_time_ms"):
        lines.append("    实测延迟: %s ms" % m["test_time_ms"])
    if m.get("throughput_bps"):
        lines.append("    实测吞吐: %.1f MB/s" % (m["throughput_bps"] / 1024.0 / 1024.0))
    if m.get("status") == "deprecated":
        lines.append("    ⚠ 状态: deprecated（连续失败，勿用）")
    if m.get("usage"):
        lines.append("    用法: %s" % m["usage"])
    if m.get("notes"):
        lines.append("    说明: %s" % m["notes"])
    return "\n".join(lines)


def render_best(payload, service_raw):
    meta = payload["dataset"]
    best = payload["best"]
    cat = payload.get("category")
    head = "【%s】%s" % (CATEGORY_LABELS.get(cat, cat or "?"), service_raw)
    lines = [
        head,
        "数据版本 %s · 最后全量实测 %s（%s 天前）· 分类 %s"
        % (meta.get("version"), meta.get("last_full_test"),
           meta.get("age_days"), cat),
        "",
        "★ 当前最优：%s" % best.get("name"),
        "    url: %s" % best.get("url"),
        "    分数 %s · 实测延迟 %s ms%s" % (
            best.get("score"),
            best.get("latency_ms"),
            (" · 吞吐 %.1f MB/s" % (best["throughput_bps"] / 1024.0 / 1024.0))
            if best.get("throughput_bps") else ""),
    ]
    answer = payload.get("answer")
    if answer:
        lines.append("")
        lines.append("  可直接执行：")
        lines.append("    %s" % answer)
    if payload.get("persist"):
        lines.append("")
        lines.append("  持久化配置：")
        lines.append("    %s" % payload["persist"])
    cmds = best.get("commands") or []
    if len(cmds) > 1:
        lines.append("")
        lines.append("  同一源的其它写法：")
        for c in cmds[1:]:
            lines.append("    %s" % c)

    others = [m for m in payload.get("mirrors", []) if m["rank"] > 1]
    if others:
        lines.append("")
        lines.append("  降级备选（按分数降序）：")
        for m in others:
            lines.append(fmt_choice(m, mark="    "))

    if best.get("notes"):
        lines.append("")
        lines.append("  说明: %s" % best["notes"])
    if payload.get("guide"):
        lines.append("  详细文档: %s" % payload["guide"])

    caveats = payload.get("caveats") or []
    if caveats:
        lines.append("")
        lines.append("  ⚠ 注意：")
        for c in caveats:
            lines.append("    - %s" % c)
    return "\n".join(lines)


def render_unknown(payload, recipes, data):
    known = payload.get("known_services") or sorted(recipes.get("services", {}).keys())
    cats = ", ".join((data.get("mirrors") or {}).keys())
    return "%s\n\n可用服务名（%d 个）：\n  %s\n\n%s\n\n也可以直接传分类名：%s" % (
        payload.get("message") or "找不到该服务。",
        len(known), ", ".join(known),
        payload.get("hint") or "",
        cats,
    )


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #

def tool_best_mirror(args):
    data, recipes = dataset()
    raw = (args.get("service") or args.get("category") or "").strip()
    limit = int(args.get("limit") or 3)
    include_deprecated = bool(args.get("include_deprecated"))
    types = (args.get("types") or "").strip() or None

    code, payload = api().response_for_best(
        data, recipes, raw, limit, include_deprecated, types)
    if code != 200:
        if payload.get("error") == "unknown_service":
            return render_unknown(payload, recipes, data)
        return payload.get("message") or json.dumps(payload, ensure_ascii=False)
    return render_best(payload, raw)


def tool_list_mirrors(args):
    data, recipes = dataset()
    raw = (args.get("service") or args.get("category") or "").strip()
    include_deprecated = bool(args.get("include_deprecated"))
    cats = data.get("mirrors") or {}

    if not raw:
        lines = ["accel-mirror 镜像库总览（版本 %s，最后全量实测 %s）" % (
            data.get("version", "?"), data.get("last_full_test") or "未知"), ""]
        for cat, entries in cats.items():
            live = [m for m in entries if m.get("status") != "deprecated"]
            best = sorted(entries, key=lambda m: (-(m.get("score") or 0),))[:1]
            top = "%s (%s)" % (best[0].get("name"), best[0].get("score")) if best else "—"
            lines.append("- %-18s %-14s 活跃 %d/%d  最优: %s" % (
                cat, CATEGORY_LABELS.get(cat, ""), len(live), len(entries), top))
        lines.append("")
        lines.append("共 %d 个源 / %d 个分类。传 service（如 pip、模型下载）或 category 查看某类全部源。"
                     % (sum(len(v) for v in cats.values()), len(cats)))
        return "\n".join(lines)

    # 先按服务名解析（与 best_mirror 同一份规则），再退回分类名
    name, spec = api().resolve_service(recipes, raw)
    if spec:
        category = spec.get("category")
        title = "%s（服务 %s）" % (CATEGORY_LABELS.get(category, category), name)
    elif raw in cats:
        category, title = raw, CATEGORY_LABELS.get(raw, raw)
    else:
        return "未知服务或分类 '%s'。\n\n可用分类：%s\n可用服务名：%s" % (
            raw, ", ".join(cats), ", ".join(sorted(recipes.get("services", {}).keys())))

    entries = [m for m in cats.get(category, [])
               if include_deprecated or m.get("status") != "deprecated"]
    entries.sort(key=lambda m: (-(m.get("score") or 0), m.get("test_time_ms") or 1 << 30))
    body = "\n\n".join(fmt_db_row(i, m) for i, m in enumerate(entries, 1))
    return "【%s】共 %d 个源\n\n%s" % (title, len(entries), body)


def probe(url, timeout=8):
    req = urllib.request.Request(
        url, headers={"User-Agent": "%s/%s" % (SERVER_NAME, server_version()),
                      "Range": "bytes=0-1023"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(1024)
            code = resp.status
        return code, int((time.time() - t0) * 1000), None
    except urllib.error.HTTPError as e:
        # 4xx/5xx 说明服务是活的（容器仓库 /v2/ 正常返回 401）
        return e.code, int((time.time() - t0) * 1000), None
    except Exception as e:  # noqa: BLE001 - 网络层异常统一上报
        return None, int((time.time() - t0) * 1000), "%s: %s" % (type(e).__name__, e)


def tool_test_mirror(args):
    url = (args.get("url") or "").strip()
    if not url:
        return "缺少参数 url。"
    timeout = int(args.get("timeout") or 8)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    code, ms, err = probe(url, timeout)
    if err:
        return "❌ %s\n    连接失败: %s\n    耗时 %d ms" % (url, err, ms)
    verdict = "可用" if code and code < 400 else ("响应异常" if code and code < 500 else "不可用")
    return "✅ %s\n    HTTP %s（%s）\n    耗时 %d ms" % (url, code, verdict, ms)


SERVICE_DESC = (
    "场景 / 服务名，例如 pip、conda、pytorch、huggingface、modelscope、"
    "docker、github、ghcr、npm、go、apt、maven。也接受中文口语别名"
    "（模型下载 / 拉镜像 / 装python包 / 镜像加速）与分类名"
    "（ai_models / python / dev_registry 等）。"
)

TOOLS = [
    {
        "name": "best_mirror",
        "description": (
            "查询中国大陆网络环境下某个场景当前最优的加速镜像源。"
            "当用户抱怨下载慢、超时、连不上（Docker 拉镜像 / git clone / HuggingFace 模型下载 / "
            "pip 或 conda 装包 / ghcr.io 拉取等），调用此工具取得实测最快的源和可直接执行的命令。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": SERVICE_DESC},
                "category": {"type": "string",
                             "description": "分类名（service 的别名，留空时会用 service）"},
                "limit": {"type": "integer", "description": "返回条数，默认 3"},
                "include_deprecated": {
                    "type": "boolean",
                    "description": "是否包含已弃用源，默认 false",
                },
                "types": {
                    "type": "string",
                    "description": "按源类型过滤，逗号分隔，如 prefix,domain,web",
                },
            },
            "required": ["service"],
        },
    },
    {
        "name": "list_mirrors",
        "description": (
            "列出镜像库内容：不传参数返回各分类总览（含数量与最优源）；"
            "传 service（如 pip）或 category 时返回该类全部源的分数、延迟与用法。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": SERVICE_DESC + "留空则输出总览"},
                "category": {"type": "string", "description": "分类名（service 的别名）"},
                "include_deprecated": {
                    "type": "boolean",
                    "description": "是否包含已弃用源，默认 false",
                },
            },
        },
    },
    {
        "name": "test_mirror",
        "description": (
            "实时探测单个 URL 的可用性与延迟（HTTP 状态 + 毫秒数）。"
            "用于验证某个镜像源在当前网络下是否真的可用。"
            "注意：这是本机发起的探测；只读 HTTP 接口刻意不提供该能力（公网探测等于 SSRF 跳板）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要探测的 URL"},
                "timeout": {"type": "integer", "description": "超时秒数，默认 8"},
            },
            "required": ["url"],
        },
    },
]

HANDLERS = {
    "best_mirror": tool_best_mirror,
    "list_mirrors": tool_list_mirrors,
    "test_mirror": tool_test_mirror,
}


# --------------------------------------------------------------------------- #
# JSON-RPC over stdio
# --------------------------------------------------------------------------- #

def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result(msg_id, value):
    send({"jsonrpc": "2.0", "id": msg_id, "result": value})


def error(msg_id, code, message):
    send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def handle(msg):
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion") or PROTOCOL_DEFAULT
        result(msg_id, {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": server_version()},
        })
        return

    if method in ("notifications/initialized", "initialized"):
        return  # notification, no reply

    if method == "ping":
        result(msg_id, {})
        return

    if method == "tools/list":
        result(msg_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if not handler:
            error(msg_id, -32602, "未知工具: %s" % name)
            return
        try:
            text = handler(args)
            result(msg_id, {"content": [{"type": "text", "text": text}]})
        except Exception as e:  # noqa: BLE001
            log("tool %s failed: %s" % (name, e))
            result(msg_id, {
                "content": [{"type": "text", "text": "工具执行失败: %s" % e}],
                "isError": True,
            })
        return

    if msg_id is not None:
        error(msg_id, -32601, "未实现的方法: %s" % method)


def main():
    # Windows 下必须强制 UTF-8，否则中文源名会乱码 / 抛编码异常
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    except Exception:  # noqa: BLE001
        pass

    for p in (DB_PATH, RECIPES_PATH, API_PATH):
        if not os.path.exists(p):
            log("missing file: %s" % p)

    log("started (db=%s, version=%s)" % (DB_PATH, server_version()))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            log("skip non-JSON line")
            continue
        if isinstance(msg, list):
            for m in msg:
                handle(m)
        else:
            handle(msg)


if __name__ == "__main__":
    main()
