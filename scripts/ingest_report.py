#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_report.py — 把一份 GitHub Issue 表单转成规范的众包上报文件
================================================================================

为什么需要它
------------
众包上报此前的链路是：用户跑 `test_mirrors.sh --network-label X` → 把 JSON 贴给你
→ 你手动复制进 `reports/`。这一层手工摩擦足以让数据飞轮停转。

本脚本把 **GitHub Issue 变成提交渠道**：陌生人跑一次本地测速，把 JSON 贴进 issue
表单，仓库自动入库。提交者不需要 fork、不需要 PR、不需要懂 git。

安全模型（这个脚本是信任边界）
------------------------------
上报来自陌生人，所以它**只能移动数据库里已有源的分数，永远不能引入新 URL**。

如果允许引入新 URL，任何人都能上报一个「延迟 5ms 的镜像」——它实际返回被篡改的
`aria2c` / `pip` / 模型权重，却因为排名第一而被推荐给本库的每一个用户。这是一条
由 issue 表单实现的供应链攻击路径。所以：

  1. 每一行都被压成 `{name, status, time_ms}` 三个字段，提交者写的 `url` **一律丢弃**；
  2. `name` 必须能在 `references/mirrors.json` 的「分类 + 名字」里查到，否则整行丢弃；
  3. 单份上报有条数上限（防灌水），样本太少的上报直接拒收（无统计意义）；
  4. 网络标签做白名单化清洗，疑似含 IP / 绝对路径时宁可丢标签也不写进仓库。

因此产物文件的隐私性是**构造性保证**，而不是靠正则扫描「大概没有」：它只可能包含
「已知源名 + 状态 + 毫秒数 + 清洗后的标签」。这一点在 `scripts/selftest.py` 里有断言。

用法:
    # 本地验证一份 issue body（不写文件）
    python3 scripts/ingest_report.py --body-file body.md --check

    # CI：直接从 GitHub event payload 取 issue 号与正文
    python3 scripts/ingest_report.py --event-file "$GITHUB_EVENT_PATH" --out-dir reports

退出码：0 成功 / 2 内容不合规（原因打印在 stderr，CI 用它决定怎么回复 issue）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "references" / "mirrors.json"
DEFAULT_OUT_DIR = ROOT / "reports"

# Issue 表单里植入了这个隐藏标记，workflow 靠它认出「这是实测上报」而不是普通 issue
MARKER = "<!-- accel-mirror-report -->"

SCHEMA = 1
MAX_ROWS_PER_CATEGORY = 400   # 单份上报规模上限，防灌水
MIN_ACCEPTED_ROWS = 5         # 少于这个数没有统计意义（一次全量测速会有上百行）
VALID_STATUS = {"ok", "failed"}
MAX_TIME_MS = 600000          # 10 分钟，超过视为垃圾数据

# 只匹配「在 JSON 载荷里出现就说明掺了个人信息」的模式。
# 注意：不能扫整个 issue 正文——模板里的示例命令本身带有 /tmp/ 之类的路径，会误伤。
_BAD_LABEL = re.compile(
    r"(?:\d{1,3}\.){3}\d{1,3}"           # IPv4
    r"|[A-Za-z]:[\\/]"                    # Windows 绝对路径
    r"|(?:^|[\s(])/(?:home|Users|root)/"  # POSIX 家目录
)

_FENCE = re.compile(r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", re.S)


# --------------------------------------------------------------- 解析 issue 正文

def iter_json_objects(text):
    """按花括号配对，逐个吐出文本里的顶层 JSON 对象原文（字符串内的括号会跳过）。"""
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc = 0, False, False
        closed = False
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[i:j + 1]
                    i, closed = j, True
                    break
        if not closed:
            return
        i += 1


def looks_like_report(obj):
    return isinstance(obj, dict) and isinstance(obj.get("results"), dict)


def extract_payload(body):
    """从 issue 正文里找出上报 JSON。

    先看围栏代码块（issue 表单的 json 字段会渲染成 ```json），
    再退化为「整个正文就是一个 JSON 对象」。
    """
    candidates = [m.group(1).strip() for m in _FENCE.finditer(body)]
    candidates.append(body.strip())
    for txt in candidates:
        for raw in iter_json_objects(txt):
            try:
                obj = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if looks_like_report(obj):
                return obj, raw
        try:
            obj = json.loads(txt)
        except (ValueError, TypeError):
            continue
        if looks_like_report(obj):
            return obj, txt
    return None, None


def form_field(body, keywords):
    """从 issue 表单正文里取某个字段的值。

    GitHub issue form 渲染成 `### 字段标签` + 空行 + 值的结构，这里按标题切块。
    """
    fields = {}
    cur = None
    buf = []
    for ln in body.splitlines():
        if ln.startswith("### "):
            if cur is not None:
                fields[cur] = "\n".join(buf).strip()
            cur = ln[4:].strip()
            buf = []
            continue
        if cur is not None and not ln.strip().startswith("<!--"):
            buf.append(ln)
    if cur is not None:
        fields[cur] = "\n".join(buf).strip()
    for k, v in fields.items():
        if any(kw in k for kw in keywords):
            return v
    return ""


def sanitize_label(raw):
    """网络标签白名单化：折叠空白、限长、疑似含个人信息则丢弃。"""
    if not raw:
        return ""
    s = " ".join(str(raw).split()).strip()
    if not s or _BAD_LABEL.search(s):
        return ""
    return s[:40]


# --------------------------------------------------------------- 规范化（信任边界）

def canonicalize(payload, known):
    """把不受信任的上报压成可信的最小结构。

    known: {(category, name)} —— 数据库里已存在的源。
    返回 (results, accepted, dropped_unknown, dropped_malformed)
    """
    results = {}
    accepted = 0
    dropped_unknown = []
    dropped_malformed = 0

    for cat, rows in (payload.get("results") or {}).items():
        if not isinstance(rows, list):
            dropped_malformed += 1
            continue
        keep = []
        for row in rows:
            if not isinstance(row, dict):
                dropped_malformed += 1
                continue
            name = row.get("name")
            status = row.get("status")
            # 白名单：源必须已在库中 —— 上报能改分数，不能造源
            if not isinstance(name, str) or (cat, name) not in known:
                dropped_unknown.append("%s/%s" % (cat, name))
                continue
            if status not in VALID_STATUS:
                dropped_malformed += 1
                continue
            t = row.get("time_ms")
            if isinstance(t, bool) or not isinstance(t, int) or t < 0 or t > MAX_TIME_MS:
                t = 0
            # 只保留这三个字段；上报者写的 url 故意不复制（见文件头「安全模型」）
            keep.append({"name": name, "status": status, "time_ms": t})
        if keep:
            keep = keep[:MAX_ROWS_PER_CATEGORY]
            results[cat] = keep
            accepted += len(keep)

    return results, accepted, dropped_unknown, dropped_malformed


def build_report(results, accepted, label, source, issue=None,
                 submitted_at=None, dropped_unknown=None, dropped_malformed=0):
    return {
        "meta": {
            "schema": SCHEMA,
            "source": source,
            "issue": issue,
            "network_label": label,
            "submitted_at": submitted_at,
            "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "privacy": (
                "by construction holds only mirror name + status + latency for mirrors "
                "already present in references/mirrors.json; the submitter's url field, "
                "IP, file paths, user id and device info are dropped at ingest time"
            ),
            "accepted_rows": accepted,
            "categories": sorted(results.keys()),
            "dropped_unknown": (dropped_unknown or [])[:20],
            "dropped_malformed": dropped_malformed,
        },
        "results": results,
    }


# --------------------------------------------------------------- 输出

def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    # newline='\n' 是必须的：Windows 上默认会把 \n 变成 \r\n，
    # 与 CI（Linux）产出的同一份文件哈希不一致，会让下面的 report 计数与 diff 变脏
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def set_output(key, value):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write("%s=%s\n" % (key, value))


def append_step_summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(text)


def load_known(db_path):
    with open(db_path, "r", encoding="utf-8") as f:
        db = json.load(f)
    known = set()
    for cat, rows in (db.get("mirrors") or {}).items():
        for m in rows or []:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                known.add((cat, m["name"]))
    return known


def count_reports(out_dir, exclude=None):
    if not out_dir.is_dir():
        return 0
    n = 0
    for p in out_dir.glob("*.json"):
        if exclude and p.name == exclude:
            continue
        n += 1
    return n


# --------------------------------------------------------------- CLI

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="把 GitHub Issue 表单转成规范众包上报")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--event-file", help="GitHub event payload JSON（CI 用）")
    src.add_argument("--body-file", help="issue 正文 markdown 文件")
    src.add_argument("--text", help="直接给出 issue 正文")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="数据库路径（白名单来源）")
    ap.add_argument("--out", help="输出到的单个文件")
    ap.add_argument("--out-dir", default=None, help="输出目录（文件名取 <issue>.json）")
    ap.add_argument("--summary-file", help="把 Markdown 摘要写到这个文件")
    ap.add_argument("--check", action="store_true", help="只校验不写文件")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的上报文件")
    return ap.parse_args(argv)


def fail(msg, code=2):
    print("REJECTED: %s" % msg, file=sys.stderr)
    return code


def main(argv=None):
    args = parse_args(argv)

    body = ""
    issue = None
    source = "local"
    if args.event_file:
        with open(args.event_file, "r", encoding="utf-8") as f:
            event = json.load(f)
        issue_obj = event.get("issue") or {}
        body = issue_obj.get("body") or ""
        issue = issue_obj.get("number")
        source = "github-issue"
    elif args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as f:
            body = f.read()
    else:
        body = args.text or ""

    if not body.strip():
        return fail("issue 正文为空")

    payload, _raw = extract_payload(body)
    if payload is None:
        return fail("正文里找不到包含 `results` 字段的 JSON（请确认粘贴完整）")

    db_path = Path(args.db)
    if not db_path.exists():
        return fail("找不到数据库: %s" % db_path)
    known = load_known(db_path)

    results, accepted, dropped_unknown, dropped_malformed = canonicalize(payload, known)

    if not results:
        detail = ("；被丢弃的未知源: %s" % ", ".join(dropped_unknown[:5])) if dropped_unknown else ""
        return fail("没有任何一行匹配库中已有的源%s" % detail)

    if accepted < MIN_ACCEPTED_ROWS:
        return fail("有效样本只有 %d 条，少于最低要求 %d 条（请用 --type all 跑一次完整测速）"
                    % (accepted, MIN_ACCEPTED_ROWS))

    # 标签优先取 JSON 里的 meta.network_label（由 test_mirrors.sh --network-label 写入），
    # 为空时回退到 issue 表单里那个独立的输入框。两条路都必须过白名单清洗。
    raw_label = (payload.get("meta") or {}).get("network_label")
    label = sanitize_label(raw_label)
    if not label:
        label = sanitize_label(form_field(body, ("网络标签", "network label", "network_label")))
    submitted_at = (payload.get("meta") or {}).get("generated_at")

    report = build_report(
        results, accepted, label, source, issue=issue,
        submitted_at=submitted_at if isinstance(submitted_at, str) else None,
        dropped_unknown=dropped_unknown, dropped_malformed=dropped_malformed,
    )

    # ---- 决定落到哪个文件 ----
    out_dir = Path(args.out_dir) if args.out_dir else None
    out_path = Path(args.out) if args.out else None
    if out_path is None:
        if out_dir is None:
            out_dir = DEFAULT_OUT_DIR
        if issue is None and not args.check:
            return fail("未提供 issue 号，无法生成文件名（用 --out 指定完整路径）")
        out_path = out_dir / ("%s.json" % (issue if issue is not None else "local"))

    if args.check:
        print("OK: 可入库 %d 条样本（%d 个分类）" % (accepted, len(results)))
        print("  网络标签: %s" % (label or "(空)"))
        print("  丢弃未知源: %d 条  丢弃畸形行: %d 条" % (len(dropped_unknown), dropped_malformed))
        set_output("written", "false")
        return 0

    if out_path.exists() and not args.force:
        # 幂等：同一 issue 被编辑时重复触发，不该报错
        print("已存在，跳过写入: %s（用 --force 覆盖）" % out_path)
        set_output("written", "false")
        return 0

    write_json(out_path, report)
    total = count_reports(out_path.parent, exclude=None)

    lines = [
        "## ✅ 实测上报已入库",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 网络标签 | %s |" % (label or "（未填写）"),
        "| 接受样本 | %d 条，覆盖 %d 个分类 |" % (accepted, len(results)),
        "| 丢弃的未知源 | %d 条 |" % len(dropped_unknown),
        "| 累计上报份数 | %d |" % total,
        "",
    ]
    if dropped_unknown:
        lines += [
            "> 丢弃的未知源不会被写入数据库——上报只能移动**已知源**的分数，",
            "> 永远不能新增 URL（防止用伪造的「高速镜像」污染推荐结果）。",
            "",
        ]
    lines += [
        "分数需要累计 **3 份以上**上报才会按中位数重算（`--min-samples 3`），"
        "所以前几份上报不会立刻改变排名，这是有意为之：单个样本不该把分数定死。",
        "",
        "感谢你让这个库的分数更接近真实网络！",
        "",
    ]
    summary = "\n".join(lines)

    if args.summary_file:
        Path(args.summary_file).parent.mkdir(parents=True, exist_ok=True)
        with open(args.summary_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(summary)

    print(summary)
    print("写入: %s" % out_path)
    set_output("written", "true")
    set_output("summary_path", str(args.summary_file or ""))
    set_output("report_path", str(out_path))
    append_step_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
