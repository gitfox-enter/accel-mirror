#!/usr/bin/env python3
"""
selftest.py — 无依赖自检（数据完整性 + 配方正确性 + API 行为 + 众包聚合规则）
================================================================================
为什么需要它：这个仓库的核心是「数据 + 规则 → 拼出答案」。`py_compile` 和
`bash -n` 只能证明语法没坏，证明不了语义没坏——比如：

  - 生成的命令是 `docker pull https://x/y`（Docker 镜像引用不允许带协议头）
  - `github` 服务把「网页工具」当成最优源返回（不可自动化）
  - 配方里引用了 `references/xxx-guide.md`，但那个文件根本不存在
  - 众包聚合把「只有 1 份上报」的源也算进了中位数

这些都是真实发生过的问题，所以用测试固化下来。

用法:
    python3 scripts/selftest.py          # 全部通过退出码 0，有失败退出码 1
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIRRORS = ROOT / "references" / "mirrors.json"
RECIPES = ROOT / "references" / "recipes.json"
API_PY = ROOT / "server" / "accel_mirror_api.py"
UPDATE_PY = ROOT / "scripts" / "update_mirrors.py"
INGEST_PY = ROOT / "scripts" / "ingest_report.py"
ISSUE_FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "network-report.yml"
INGEST_WF = ROOT / ".github" / "workflows" / "report-ingest.yml"
PAGES_WF = ROOT / ".github" / "workflows" / "pages.yml"
AGENTS_MD = ROOT / "AGENTS.md"
README_MD = ROOT / "README.md"
SKILL_MD = ROOT / "SKILL.md"
LLMS_TXT = ROOT / "llms.txt"
CLAUDE_MD = ROOT / "CLAUDE.md"
CURSOR_RULE = ROOT / ".cursor" / "rules" / "accel-mirror.mdc"
CONTRIBUTING_MD = ROOT / "CONTRIBUTING.md"
CHANGELOG_MD = ROOT / "CHANGELOG.md"
SECURITY_MD = ROOT / "SECURITY.md"
SERVER_README = ROOT / "server" / "README.md"
MCP_PY = ROOT / "mcp_server" / "accel_mirror_mcp.py"
MCP_README = ROOT / "mcp_server" / "README.md"

# 「当前状态」类文档：里面的版本号、源数量、断言数必须彼此一致。
# CHANGELOG.md 刻意不在此列——它的职责就是记录历史数字，天然含多个值。
CURRENT_DOCS = {
    "README.md": README_MD,
    "SKILL.md": SKILL_MD,
    "AGENTS.md": AGENTS_MD,
    "CLAUDE.md": CLAUDE_MD,
    ".cursor/rules/accel-mirror.mdc": CURSOR_RULE,
    "llms.txt": LLMS_TXT,
}

ASSERTION_PATTERNS = (
    r"(\d+)\s*项(?:语义)?断言",
    r"(\d+)\s+(?:semantic\s+)?assertions",
)

FAILURES = []
PASSED = 0


def check(label, cond, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        print("  \u2705 %s%s" % (label, ("  " + detail) if detail else ""))
    else:
        FAILURES.append(label)
        print("  \u274c %s%s" % (label, ("  " + detail) if detail else ""))
    return bool(cond)


def check_meta(label, cond, detail=""):
    """元检查：会判定成败，但**不计入断言总数**。

    专用于「文档里声明的断言数 == 实际断言数」这类自指断言——
    如果它把自己也算进去，等式永远差一，所以必须不增加 PASSED。
    """
    print(("  \u2705 " if cond else "  \u274c ") + label + (("  " + detail) if (detail and not cond) else ""))
    if not cond:
        FAILURES.append(label)
    return bool(cond)


def stated_assertion_counts():
    """扫描「当前状态」文档里声明的断言数，返回 (全部取值集合, 自相矛盾的文件)。"""
    found_all = set()
    inconsistent = {}
    for name, path in CURRENT_DOCS.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        found = set()
        for pat in ASSERTION_PATTERNS:
            found |= {int(m) for m in re.findall(pat, text)}
        found_all |= found
        if len(found) > 1:
            inconsistent[name] = sorted(found)
    return found_all, inconsistent


def section(title):
    print("\n" + title)
    print("-" * len(title))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------- 检查项

def test_mirrors_json(data):
    section("1. mirrors.json 数据完整性")
    check("有 version 字段", bool(data.get("version")), str(data.get("version")))
    cats = data.get("mirrors") or {}
    check("至少有 5 个分类", len(cats) >= 5, "分类: %d 个" % len(cats))
    total = sum(len(v) for v in cats.values())
    check("源总数 > 50", total > 50, "共 %d 个源" % total)

    bad_status = bad_score = bad_url = dup = 0
    for cat, rows in cats.items():
        seen = set()
        for m in rows:
            name = m.get("name", "")
            if name in seen:
                dup += 1
            seen.add(name)
            if m.get("status") not in ("active", "deprecated"):
                bad_status += 1
            s = m.get("score")
            if not isinstance(s, int) or not (0 <= s <= 100):
                bad_score += 1
            for field in ("url", "test_url"):
                u = m.get(field)
                if u and not re.match(r"^https?://", str(u)):
                    bad_url += 1
    check("每个源的 status 合法", bad_status == 0, "异常 %d" % bad_status)
    check("每个源的 score 在 0..100", bad_score == 0, "异常 %d" % bad_score)
    check("url/test_url 都是 http(s)", bad_url == 0, "异常 %d" % bad_url)
    check("分类内无重名源", dup == 0, "重复 %d" % dup)
    check("有 evolution_log（可追溯）", len(data.get("evolution_log") or []) > 0,
          "%d 条记录" % len(data.get("evolution_log") or []))
    return total


def test_recipes(data, recipes):
    section("2. recipes.json 配方正确性")
    services = recipes.get("services") or {}
    check("有 version 字段", bool(recipes.get("version")))
    check("服务数 >= 20", len(services) >= 20, "%d 个" % len(services))

    cats = set((data.get("mirrors") or {}).keys())
    bad_cat, bad_alias, missing_guide, no_action = [], [], [], []
    # 别名冲突检查：同一个别名不能指向两个不同服务
    alias_owner = {}
    collisions = []
    for name, spec in services.items():
        if spec.get("category") not in cats:
            bad_cat.append("%s -> %s" % (name, spec.get("category")))
        aliases = spec.get("aliases") or []
        if not aliases:
            bad_alias.append(name)
        for a in aliases:
            key = a.strip().lower()
            if key in alias_owner and alias_owner[key] != name:
                collisions.append("%s: %s vs %s" % (key, alias_owner[key], name))
            alias_owner[key] = name
        guide = spec.get("guide")
        if guide and not (ROOT / guide).exists():
            missing_guide.append("%s -> %s" % (name, guide))
        # 至少要有一种能产出命令的途径：模板 / 类型模板，或该分类的源自带 usage
        has_tpl = bool(spec.get("command") or spec.get("command_by_type"))
        cat_has_usage = any(
            m.get("usage") or m.get("usage_examples")
            for m in (data.get("mirrors", {}).get(spec.get("category"), []) or [])
        )
        if not has_tpl and not cat_has_usage:
            no_action.append(name)

    check("所有配方的 category 都存在", not bad_cat, "; ".join(bad_cat))
    check("每个服务都有 aliases", not bad_alias, ", ".join(bad_alias))
    check("别名无跨服务冲突", not collisions, "; ".join(collisions))
    check("guide 指向的文件都存在", not missing_guide, "; ".join(missing_guide))
    check("每个服务都能产出命令", not no_action, ", ".join(no_action))


def test_api(data, recipes, api):
    section("3. API 行为（含语义断言）")
    code, health = api.response_for_health(data, recipes)
    check("health 返回 200", code == 200, "dataset v%s, %d 源"
          % (health["dataset"]["version"], health["dataset"]["mirror_count"]))
    code, svc = api.response_for_services(recipes)
    check("services 数量与配方一致", svc["count"] == len(recipes["services"]),
          "%d 个" % svc["count"])

    docker_family = ("docker", "docker-enterprise", "ghcr", "quay", "gcr", "k8s", "nvcr")
    services = ["pip", "pytorch", "huggingface", "modelscope", "docker", "github",
                "ghcr", "npm", "go", "conda", "apt", "maven"]
    for s in services:
        code, payload = api.response_for_best(data, recipes, s, 3, False)
        ok = code == 200 and payload.get("answer")
        check("best(%-12s) 有可执行答案" % s, ok,
              "%s | %s" % (payload.get("best", {}).get("name", "-"), payload.get("answer", "")))
        if not ok:
            continue
        answer = payload["answer"]
        tail = answer.split()[-1]
        if s in docker_family:
            # Docker 镜像引用不能带协议头
            check("  └ %s 命令不含 scheme" % s, "://" not in tail.split("/")[0], tail)
        if s == "github":
            check("  └ github 答案是可自动化的 git clone", "git clone" in answer, answer)
        if payload.get("dataset", {}).get("age_days") is not None:
            check("  └ 带数据新鲜度", isinstance(payload["dataset"]["age_days"], int),
                  "age_days=%s" % payload["dataset"]["age_days"])

    code, bad = api.response_for_best(data, recipes, "no-such-service", 1, False)
    check("未知服务返回 404", code == 404 and bad["error"] == "unknown_service")
    check("404 里带上可用服务列表", len(bad.get("known_services", [])) > 10)

    first_cat = sorted((data.get("mirrors") or {}).keys())[0]
    code, bycat = api.response_for_best(data, recipes, first_cat, 2, False)
    check("可直接传分类名（%s）" % first_cat, code == 200)

    code, lst = api.response_for_list(data, recipes, "github", 10, False)
    scores = [m["score"] for m in lst["mirrors"]]
    check("list 按分数降序", scores == sorted(scores, reverse=True), str(scores))
    code, nf = api.response_for_list(data, recipes, "nope", 5, False)
    check("未知分类返回 404", code == 404)


def test_aggregate(data, update, tmpdir):
    section("4. 众包聚合规则（中位数 / min-samples / 仅全失败才弃用）")

    def report(label, rows):
        res = {}
        for cat, items in rows.items():
            res[cat] = [{"name": n, "url": "http://x", "time_ms": t,
                         "http_code": "200" if s == "ok" else "000", "status": s}
                        for n, t, s in items]
        return {"meta": {"schema": 1, "network_label": label}, "results": res}

    # 关键：先清掉库里已有的众包字段再断言。
    # 否则本节的结论会依赖「这个库历史上有没有被聚合过」——CI 在真实上报入库后
    # 紧接着跑自检，那时 samples 早已存在，断言会假失败。测试必须对数据历史免疫。
    CROWD_FIELDS = ("samples", "latency_min_ms", "latency_max_ms", "failed_reports")

    def pristine(copy_of):
        for rows in copy_of["mirrors"].values():
            for m in rows:
                for f in CROWD_FIELDS:
                    m.pop(f, None)
        copy_of.pop("crowd", None)
        return copy_of

    db = pristine(copy.deepcopy(data))
    check("自检先把库里的众包字段清空（结论不依赖数据库历史）",
          all(f not in m for rows in db["mirrors"].values() for m in rows
              for f in CROWD_FIELDS))

    # 取真实存在的三个源做实验
    dname = db["mirrors"]["docker_community"][0]["name"]
    pname = db["mirrors"]["python"][0]["name"]
    tname = db["mirrors"]["tools"][0]["name"]
    spread_name = None
    for m in db["mirrors"]["docker_community"][1:]:
        if m["name"] != dname:
            spread_name = m["name"]
            break

    reports = [
        report("A", {"docker_community": [(dname, 400, "ok"), (spread_name, 700, "ok")],
                     "python": [(pname, 12000, "ok")],
                     "tools": [(tname, 300, "ok")]}),
        report("B", {"docker_community": [(dname, 600, "ok")],
                     "python": [(pname, 14000, "ok")],
                     "tools": [(tname, 0, "failed")]}),
        report("C", {"docker_community": [(dname, 500, "ok")],
                     "python": [(pname, 13000, "ok")],
                     "tools": [(tname, 400, "ok")]}),
    ]
    paths = []
    for i, r in enumerate(reports):
        p = os.path.join(tmpdir, "report%d.json" % i)
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False)
        paths.append(p)

    def find(root, name):
        for cat, rows in root["mirrors"].items():
            for m in rows:
                if m["name"] == name:
                    return m
        return None

    before = copy.deepcopy(find(db, dname))

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        updated, deprecated, skipped = update.aggregate_reports(db, paths, min_samples=2)

    d = find(db, dname)
    check("中位数生效（400/600/500 -> 500ms, 84 分）",
          d["test_time_ms"] == 500 and d["score"] == 84,
          "time=%s score=%s" % (d["test_time_ms"], d["score"]))
    check("记录样本数与延迟区间",
          d.get("samples") == 3 and d.get("latency_min_ms") == 400 and d.get("latency_max_ms") == 600)
    check("只被 1 份上报覆盖的源被跳过（min_samples=2）",
          find(db, spread_name).get("samples") is None)
    check("有成功记录但失败 1 次的源不被弃用，只记 failed_reports",
          find(db, tname)["status"] != "deprecated"
          and find(db, tname).get("failed_reports") == 1,
          "status=%s failed_reports=%s" % (find(db, tname)["status"],
                                           find(db, tname).get("failed_reports")))
    check("中位数来自 300/400 -> 350ms 而非均值", find(db, tname)["test_time_ms"] == 350,
          "time=%s" % find(db, tname)["test_time_ms"])

    # 幂等：CI 每次收到新上报都会把 reports/ 里的全量上报重新聚合一次，
    # 所以「重复聚合同一批上报」必须得到完全相同的分数，否则数据会自己漂移。
    def snapshot(root):
        return {m["name"]: (m.get("score"), m.get("test_time_ms"), m.get("samples"))
                for rows in root["mirrors"].values() for m in rows}

    snap_before = snapshot(db)
    with contextlib.redirect_stdout(buf):
        update.aggregate_reports(db, paths, min_samples=2)
    check("聚合幂等（重复聚合同一批上报结果不变）", snapshot(db) == snap_before)

    # 全失败 3 次、零成功 -> 弃用
    db2 = pristine(copy.deepcopy(data))
    allfail = db2["mirrors"]["docker_community"][2]["name"]
    reports2 = [report(lbl, {"docker_community": [(allfail, 0, "failed")]}) for lbl in "ABC"]
    paths2 = []
    for i, r in enumerate(reports2):
        p = os.path.join(tmpdir, "fail%d.json" % i)
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False)
        paths2.append(p)
    with contextlib.redirect_stdout(buf):
        update.aggregate_reports(db2, paths2, min_samples=1)
    check("3/3 上报全失败且零成功 -> 弃用",
          find(db2, allfail)["status"] == "deprecated" and find(db2, allfail)["score"] == 0)

    check("未出现在上报里的源保持原样", find(db, dname)["name"] == before["name"])
    check("crowd 元数据写入（含网络标签）",
          db.get("crowd", {}).get("reports") == 3
          and db["crowd"].get("network_labels") == ["A", "B", "C"])
    check("crowd 元数据不含隐私字段",
          "privacy" not in json.dumps(db.get("crowd", {}), ensure_ascii=False))
    check("evolution_log 追加聚合记录",
          any(e["action"] == "crowd_aggregated" for e in db.get("evolution_log", [])))
    return updated, deprecated, skipped


def test_report_meta(tmpdir):
    section("5. 上报文件的隐私与结构（test_mirrors.sh 的 meta 契约）")
    src = (ROOT / "scripts" / "test_mirrors.sh").read_text(encoding="utf-8", errors="replace")
    check("脚本声明了隐私字段说明", "privacy" in src and "no IP" in src)
    check("脚本支持 --network-label", "--network-label" in src)
    check("脚本接受 ACCEL_NETWORK_LABEL 环境变量", "ACCEL_NETWORK_LABEL" in src)
    check("输出带 schema 版本", "'schema': 1" in src or "\"schema\": 1" in src)
    check("工具版本号随脚本更新", "TOOL_VERSION" in src)


def test_issue_ingest(data, ingest, tmpdir):
    section("6. Issue 众包入库（白名单 / 抗投毒 / 字段最小化）")

    real = [(cat, [(m["name"], m["url"]) for m in rows[:5]])
            for cat, rows in sorted((data.get("mirrors") or {}).items())]
    known = set()
    for cat, rows in (data.get("mirrors") or {}).items():
        for m in rows:
            known.add((cat, m["name"]))

    def make_report(extra=None, label="北京联通 500M"):
        results = {}
        for cat, items in real:
            rows = [{"name": n, "url": u, "time_ms": 300, "http_code": "200", "status": "ok"}
                    for n, u in items]
            for name, url, t, status in (extra or {}).get(cat, []):
                rows.insert(0, {"name": name, "url": url, "time_ms": t,
                                "http_code": "200", "status": status})
            results[cat] = rows
        meta = {"schema": 1, "tool_version": "1.6.0", "generated_at": "2026-09-21T13:00:00"}
        if label is not None:
            meta["network_label"] = label
        return {"meta": meta, "results": results}

    def wrap(rep, form_label=""):
        return ("<!-- accel-mirror-report -->\n\n### 网络标签\n\n" + form_label
                + "\n\n### 实测结果 JSON\n\n```json\n"
                + json.dumps(rep, ensure_ascii=False) + "\n```\n\n### 提交前确认\n\n- [X] 是\n")

    # ---- 1) 抗投毒：不能新增源，且提交者的 url 绝不进产物 ----
    POISON_URL = "https://totally-fake-mirror.invalid/payload-that-must-never-be-stored"
    victim = data["mirrors"]["github"][0]["name"]
    poisoned = make_report(extra={
        "github": [("evil-0ms-mirror", POISON_URL, 5, "ok"),
                   (victim, POISON_URL, 5, "ok")],
        "docker_community": [("evil-0ms-mirror", POISON_URL, 5, "ok")],
    })
    results, accepted, unknown, malformed = ingest.canonicalize(poisoned, known)
    flat = [r for rows in results.values() for r in rows]
    check("库中不存在的源被整行丢弃（上报不能新增源）",
          len(unknown) == 2 and all(r["name"] != "evil-0ms-mirror" for r in flat),
          "丢弃 %d 行" % len(unknown))
    check("每行只保留 name/status/time_ms 三个字段（提交者的 url 被丢弃）",
          bool(flat) and all(set(r) == {"name", "status", "time_ms"} for r in flat))
    check("提交者写的 url 完全不出现在入库结果中",
          POISON_URL not in json.dumps(results, ensure_ascii=False))
    check("库中已有的源即使被篡改延迟也仍然按最小字段入库",
          any(r["name"] == victim for r in flat))

    ok = make_report()
    results, accepted, unknown, malformed = ingest.canonicalize(ok, known)
    check("合法上报全部被接受",
          accepted == sum(len(v) for v in ok["results"].values()) and not unknown
          and malformed == 0, "%d 条" % accepted)

    # ---- 2) 解析 issue 表单正文 ----
    body = wrap(ok, "北京联通 500M")
    payload, raw = ingest.extract_payload(body)
    check("能从 issue 表单正文里抽出上报 JSON（围栏代码块）",
          payload is not None and "results" in payload)
    check("裸正文（无围栏、前后有散文）也能抽出 JSON",
          ingest.extract_payload("说明文字\n" + json.dumps(ok) + "\n结尾")[0] is not None)
    check("围栏里不是 JSON 时不会误判",
          ingest.extract_payload("```\n我不是 JSON\n```")[0] is None)

    # ---- 3) 标签清洗与回退 ----
    check("标签含 IPv4 时丢弃", ingest.sanitize_label("10.0.0.5") == "")
    check("标签含 Windows 盘符路径时丢弃", ingest.sanitize_label("C:\\Users\\bob") == "")
    check("标签含 POSIX 家目录时丢弃", ingest.sanitize_label("我 /home/bob 的机器") == "")
    check("正常标签折白并保留", ingest.sanitize_label("  北京联通   500M ") == "北京联通 500M")
    check("标签超长被截断", len(ingest.sanitize_label("x" * 200)) == 40)
    check("表单字段可作标签回退", ingest.form_field(body, ("网络标签",)) == "北京联通 500M")

    # ---- 4) 拒收路径（走真实 CLI，验证退出码） ----
    def run_cli(content):
        p = os.path.join(tmpdir, "body_cli.md")
        with io.open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        r = subprocess.run([sys.executable, str(INGEST_PY), "--body-file", p,
                            "--check", "--db", str(MIRRORS)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    rc, out = run_cli(body)
    check("合法上报 CLI 退出码 0", rc == 0, out.strip().splitlines()[0] if out.strip() else "")
    rc, out = run_cli("### 网络标签\n\n北京\n\n### 实测结果 JSON\n\n我忘了粘贴\n")
    check("正文无 JSON 时拒收（退出码 2）", rc == 2 and "REJECTED" in out)
    rc, out = run_cli(wrap({"meta": {"schema": 1},
                            "results": {"github": [{"name": "not-a-real-mirror",
                                                    "url": "https://x.invalid/",
                                                    "time_ms": 1, "status": "ok"}]}}))
    check("全是未知源时拒收（退出码 2）", rc == 2 and "REJECTED" in out)
    rc, out = run_cli(wrap({"meta": {"schema": 1},
                            "results": {"github": [{"name": data["mirrors"]["github"][0]["name"],
                                                    "url": "https://x/",
                                                    "time_ms": 1, "status": "ok"}]}}))
    check("有效样本过少时拒收（退出码 2）", rc == 2 and "REJECTED" in out)

    # ---- 5) 产物契约 ----
    out_path = os.path.join(tmpdir, "1.json")
    with io.open(os.path.join(tmpdir, "body_ok.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    r = subprocess.run([sys.executable, str(INGEST_PY), "--body-file",
                        os.path.join(tmpdir, "body_ok.md"), "--out", out_path,
                        "--db", str(MIRRORS), "--force"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    produced = json.loads(Path(out_path).read_text(encoding="utf-8")) if os.path.exists(out_path) else {}
    check("能写出上报文件", r.returncode == 0 and bool(produced.get("results")))
    check("产物 meta 声明了隐私边界", "privacy" in (produced.get("meta") or {}))
    check("产物 meta 记录了被丢弃的未知源",
          (produced.get("meta") or {}).get("dropped_unknown") == [])
    check("产物文件用 LF 换行（跨平台哈希一致）",
          b"\r\n" not in Path(out_path).read_bytes())


def test_agent_entrypoints(ingest):
    section("7. 代理入口与自动化管线（分发层）")

    check("AGENTS.md 存在（跨工具代理入口）", AGENTS_MD.exists())
    check("CLAUDE.md 存在", (ROOT / "CLAUDE.md").exists())
    check("Cursor 规则存在", (ROOT / ".cursor" / "rules" / "accel-mirror.mdc").exists())
    check("docs/index.html 存在（Pages 页面）", (ROOT / "docs" / "index.html").exists())
    check("reports/ 有说明文档", (ROOT / "reports" / "README.md").exists())

    # 入口文件必须指向真实存在的文件，否则文档会随重构悄悄腐烂
    txt = AGENTS_MD.read_text(encoding="utf-8") if AGENTS_MD.exists() else ""
    refs = set(re.findall(r"`((?:references|scripts|server|mcp_server|docs)/[A-Za-z0-9._/*-]+)`", txt))
    refs |= set(re.findall(r"`(llms\.txt|SKILL\.md|README\.md)`", txt))
    missing = sorted(r for r in refs if "*" not in r and not (ROOT / r.rstrip("/")).exists())
    check("AGENTS.md 引用的文件都真实存在（防文档漂移）", not missing, ", ".join(missing))
    check("AGENTS.md 写明了抗投毒约束", "不能" in txt and "url" in txt.lower())

    # Issue 表单
    form = ISSUE_FORM.read_text(encoding="utf-8") if ISSUE_FORM.exists() else ""
    check("Issue 表单含隐藏标记（workflow 靠它识别上报）", ingest.MARKER in form)
    check("Issue 表单把 JSON 字段标为必填", "required: true" in form)
    check("Issue 表单声明了隐私说明", "不含 IP" in form or "不含" in form)

    # 入库 workflow
    wf = INGEST_WF.read_text(encoding="utf-8") if INGEST_WF.exists() else ""
    check("入库 workflow 存在", bool(wf))
    check("入库 workflow 声明 contents: write（要回写仓库）", "contents: write" in wf)
    check("入库 workflow 用 --event-file 取正文（不从表达式插值）", "--event-file" in wf)
    check("入库 workflow 只处理带标记的 issue（不影响普通 issue）",
          "accel-mirror-report" in wf and "issues:" in wf)
    check("入库 workflow 用 --min-samples 3 聚合", "--min-samples 3" in wf)
    check("入库 workflow 入库后会跑自检", "selftest.py" in wf)
    check("入库 workflow 会回复提交者", "issue comment" in wf)

    # Pages workflow
    pw = PAGES_WF.read_text(encoding="utf-8") if PAGES_WF.exists() else ""
    check("Pages workflow 存在", bool(pw))
    check("Pages workflow 上传 docs/ 为站点产物",
          "upload-pages-artifact" in pw and "path: docs" in pw)
    check("Pages workflow 部署前重建看板 + 自检",
          "build_dashboard.py" in pw and "selftest.py" in pw)
    check("Pages workflow 申请了 pages/id-token 权限",
          "pages: write" in pw and "id-token: write" in pw)


def test_transport_parity(data, recipes, api, mcp):
    """MCP 与 HTTP 必须是同一份规则的两个出口，不能各写一套。

    真实事故：MCP 曾自己复制了一份更弱的实现（只认分类名、并把版本号硬编码成
    1.4.0），于是 best_mirror(service="pip") 返回「未知分类」。而 README/SKILL
    都宣称两者「共用同一份规则，杜绝逻辑漂移」——宣称与事实不符。
    现在 MCP 直接 import server/accel_mirror_api.py，并由本节断言锁住。
    """
    section("8. MCP 与 HTTP 行为一致性（同一份规则的两个出口）")

    src = MCP_PY.read_text(encoding="utf-8") if MCP_PY.exists() else ""
    check("MCP 复用 HTTP 层的实现（而不是自己再实现一套）",
          "accel_mirror_api" in src and "response_for_best" in src)
    check("MCP 报告的版本号来自 mirrors.json（不再硬编码）",
          mcp.server_version() == data.get("version"),
          "MCP 报 %s / 库 %s" % (mcp.server_version(), data.get("version")))

    # 逐一对齐：同一服务名在两条通道上必须给出同一个源和同一条命令
    mism = []
    for svc in sorted(recipes.get("services", {})):
        code, payload = api.response_for_best(data, recipes, svc, 1, False, None)
        if code != 200:
            continue
        text = mcp.tool_best_mirror({"service": svc, "limit": 1})
        if payload["best"]["name"] not in text:
            mism.append("%s: 源不一致" % svc)
        elif (payload.get("answer") or "") and payload["answer"] not in text:
            mism.append("%s: 命令不一致" % svc)
    check("全部服务名在 MCP 与 HTTP 上给出同一答案", not mism, "; ".join(mism[:4]))

    # 中文口语别名（从 recipes.json 里取真实数据，而不是硬编码几个词）
    cn = []
    for _svc, spec in (recipes.get("services") or {}).items():
        for a in spec.get("aliases", []) or []:
            if any("\u4e00" <= ch <= "\u9fff" for ch in a):
                cn.append(a)
                break
    bad_cn = [a for a in cn[:6]
              if "url:" not in mcp.tool_best_mirror({"service": a, "limit": 1})]
    check("中文口语别名在 MCP 上同样可解析", cn and not bad_cn,
          "候选 %d 个，失败 %s" % (len(cn), ", ".join(bad_cn) or "无"))

    unknown = mcp.tool_best_mirror({"service": "no-such-service", "limit": 1})
    check("MCP 未知服务时给出可用服务清单（而非只说未知分类）",
          "pip" in unknown and "github" in unknown and "未知分类" not in unknown)

    # docker 命令不能带 scheme 是硬规则，必须两条通道都成立
    docker_txt = mcp.tool_best_mirror({"service": "docker", "limit": 1})
    check("MCP 给出的 docker 命令同样不含 scheme",
          "docker pull " in docker_txt and "docker pull https://" not in docker_txt)

    mcp_doc = MCP_README.read_text(encoding="utf-8") if MCP_README.exists() else ""
    check("MCP 文档说明了它复用 server/ 的同一份规则",
          "accel_mirror_api" in mcp_doc or "同一份" in mcp_doc)


def test_doc_consistency(data):
    section("9. 文档一致性（防止版本 / 数量漂移）")

    check("贡献 / 变更 / 安全三份文档都存在",
          CONTRIBUTING_MD.exists() and CHANGELOG_MD.exists() and SECURITY_MD.exists(),
          "缺失: %s" % ", ".join(
              n for n, p in (("CONTRIBUTING.md", CONTRIBUTING_MD),
                             ("CHANGELOG.md", CHANGELOG_MD),
                             ("SECURITY.md", SECURITY_MD)) if not p.exists()) or "无")

    version = str(data.get("version"))
    total = sum(len(v) for v in (data.get("mirrors") or {}).values())
    ncats = len(data.get("mirrors") or {})

    readme = README_MD.read_text(encoding="utf-8") if README_MD.exists() else ""

    # 徽章与「镜像库现状」标题：版本号 / 源数 / 分类数一处都不能漏改
    check("README 徽章版本号与 mirrors.json 一致",
          "badge/version-%s-" % version in readme, "version=%s" % version)
    check("README 徽章源数量与数据库一致",
          "badge/mirrors-%d-" % total in readme, "总数=%d" % total)
    check("README「镜像库现状」标题三处数字都对",
          ("（数据库 v%s · %d 源 · %d 分类）" % (version, total, ncats)) in readme,
          "期望 v%s · %d 源 · %d 分类" % (version, total, ncats))

    # 断言数：各文档必须先自洽，再彼此一致（与实际值的一致性由元检查兜底）
    stated, inconsistent = stated_assertion_counts()
    check("每份文档只声明一个断言数（不自相矛盾）", not inconsistent, str(inconsistent))
    check("各文档声明的断言数彼此一致",
          len(stated) == 1, "声明的取值: %s" % sorted(stated))
    check("声明的断言数不是过期旧值（>= 100）",
          bool(stated) and min(stated) >= 100, "声明的取值: %s" % sorted(stated))

    # 更新记录只应有一份，避免同一份历史在两个地方各维护一遍（漂移的源头）
    changelog = CHANGELOG_MD.read_text(encoding="utf-8") if CHANGELOG_MD.exists() else ""
    check("CHANGELOG 顶部记录了当前版本", "## [%s]" % version in changelog, "v%s" % version)
    check("README 不再内嵌更新记录（已抽到 CHANGELOG.md）",
          "## 更新记录" not in readme and "CHANGELOG.md" in readme)
    check("server/README 的示例响应版本号不是旧值",
          ('"version": "%s"' % version) in
          (SERVER_README.read_text(encoding="utf-8") if SERVER_README.exists() else ""),
          "样例应写 v%s" % version)

    # 贡献入口要能被找到，否则飞轮建好了也没人进来
    agents = AGENTS_MD.read_text(encoding="utf-8") if AGENTS_MD.exists() else ""
    check("AGENTS.md 指向贡献指南（代理会据此引导用户上报）",
          "CONTRIBUTING.md" in agents)
    check("llms.txt 指向贡献与变更入口",
          "CONTRIBUTING.md" in (LLMS_TXT.read_text(encoding="utf-8")
                                if LLMS_TXT.exists() else ""))


def main():
    print("=" * 68)
    print("  accel-mirror 自检（数据 + 配方 + API + 聚合 + 众包入库 + 分发 + 文档）")
    print("=" * 68)

    for p in (MIRRORS, RECIPES, API_PY, UPDATE_PY, INGEST_PY, MCP_PY):
        if not p.exists():
            print("\u274c 缺少文件: %s" % p)
            sys.exit(1)

    mirrors_hash = sha256(MIRRORS)
    data = json.loads(MIRRORS.read_text(encoding="utf-8"))
    recipes = json.loads(RECIPES.read_text(encoding="utf-8"))
    api = load_module("accel_api", API_PY)
    update = load_module("accel_update", UPDATE_PY)
    ingest = load_module("accel_ingest", INGEST_PY)
    mcp = load_module("accel_mcp", MCP_PY)

    test_mirrors_json(data)
    test_recipes(data, recipes)
    test_api(data, recipes, api)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_aggregate(data, update, tmpdir)
        test_report_meta(tmpdir)
        test_issue_ingest(data, ingest, tmpdir)
    test_agent_entrypoints(ingest)
    test_transport_parity(data, recipes, api, mcp)
    test_doc_consistency(data)

    section("10. 副作用检查")
    check("自检没有改动生产数据库 mirrors.json", sha256(MIRRORS) == mirrors_hash)

    # 必须放在最后：此时全部断言已执行完毕，且元检查自己不增加计数，
    # 所以「文档声明的断言数」有一个唯一正确的答案。
    # 比的是**断言总数**（PASSED + FAILURES），而不是通过数——
    # 否则一旦有断言失败，文档里的数字反而要跟着变小，那就荒谬了。
    total_checks = PASSED + len(FAILURES)
    stated, _ = stated_assertion_counts()
    print("")
    check_meta("文档声明的断言数 == 实际断言数（%d）" % total_checks,
               stated == {total_checks},
               "文档声明 %s；请把文档里的断言数统一改为 %d" % (
                   sorted(stated) or "无", total_checks))

    print("\n" + "=" * 68)
    if FAILURES:
        print("  \u274c 失败 %d 项 / 通过 %d 项" % (len(FAILURES), PASSED))
        for f in FAILURES:
            print("     - %s" % f)
        print("=" * 68)
        return 1
    print("  \u2705 全部通过（%d 项）" % PASSED)
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
