---
name: accel-mirror
description: >-
  解决中国大陆网络环境下的"下载慢 / 超时 / 连不上"问题。只要用户抱怨下载或安装慢、
  连不上、超时、断流，或需要配置任何国内镜像源，就用本技能——它内含一份持续实测打分的
  镜像源数据库，可以直接给出当前最优源和可执行命令，不用猜也不用搜。

  典型场景：Docker 拉镜像卡住、docker pull timeout、registry-1.docker.io 连接失败、
  需要配 daemon.json 的 registry-mirrors；git clone 慢、GitHub 打不开、release 资产下载失败、
  需要配 ghproxy 类加速；HuggingFace 模型下载断流、transformers 拉权重超时、
  需要 hf-mirror 或 ModelScope 替代；pip install 卡在下载、conda 装不上、PyTorch 下载太慢、
  需要换 pip / conda 源；ghcr.io、quay.io、registry.k8s.io、nvcr.io 拉不下来；
  npm install 卡住、go mod 拉不动、apt update 超时、Homebrew 慢、Maven/Gradle 依赖慢；
  下载哈希不一致、需要安装 aria2/axel 下载器。

  取数途径（任选，越靠前越省 token）：若已部署本仓库的只读接口，直接
  `GET /v1/best?service=<服务名>`（服务名 25 个：pip / pytorch / conda / huggingface /
  modelscope / docker / github / ghcr / k8s / npm / go / maven / apt / homebrew …）
  即可拿到最优源与可执行命令；否则读 references/mirrors.json 选 status=active 且 score 最高者。

  关键词：镜像加速、镜像源、docker 源、github 镜像、ghproxy、registry-mirrors、
  npm镜像、pip镜像、conda源、hf-mirror、modelscope、华为云 swr、ddn-k8s、
  下载慢、下载失败、下载器安装、aria2、axel、加速、镜像。
  即使用户只说了"docker 慢"、"github 打不开"、"装不上"、"下不动"，也立即使用本技能。
---

# Accelerated Mirror Manager (accel-mirror)

A self-evolving skill that manages a curated, dynamically sorted database of network acceleration mirrors for Docker Hub, GitHub, and related ecosystems (npm/pip/Go). Designed to grow smarter with every use.

## File Structure

```
accel-mirror/
├── SKILL.md                      # This file (main instructions)
├── AGENTS.md                     # Cross-tool agent entry (Cursor / Codex / Claude Code)
├── CLAUDE.md                     # Compact entry for Claude Code
├── README.md                     # Human-readable intro + tested rankings
├── llms.txt                      # Machine-readable entry point for AI agents
├── references/
│   ├── mirrors.json             # Live mirror database (scores, status, crowd metadata)
│   ├── recipes.json             # service name → category + command template (shared by server/ and mcp_server/)
│   ├── docker-mirrors-guide.md  # Docker acceleration detailed guide
│   ├── github-mirrors-guide.md  # GitHub acceleration detailed guide
│   ├── ai-models-guide.md       # HuggingFace / ModelScope / dataset download guide
│   └── package-managers-guide.md # npm/pip/apt/Homebrew/Rust/etc. mirror guide
├── scripts/
│   ├── test_mirrors.sh          # Speed testing (--deep throughput, --network-label crowd report)
│   ├── update_mirrors.py        # Scoring/sorting/deprecation + --aggregate crowd median
│   ├── accel-fetch.sh           # Auto-download with smart proxy selection + fallback
│   ├── build_dashboard.py       # Generates docs/index.html from mirrors.json
│   ├── ingest_report.py         # GitHub-Issue report -> canonical report (trust boundary)
│   └── selftest.py              # Dependency-free semantic self-check (129 assertions)
├── server/                      # Read-only HTTP API (zero-dependency) for clients without MCP
│   ├── accel_mirror_api.py      # GET /v1/best · /v1/list · /v1/services · /v1/health
│   ├── Dockerfile               # Non-root + healthcheck, no pip install needed
│   └── README.md                # Deploy / reverse-proxy / security notes
├── mcp_server/
│   ├── accel_mirror_mcp.py      # MCP server (zero-dependency) so any AI client can query the DB
│   └── README.md                # Per-client MCP setup
├── reports/                     # Archived crowd reports (<issue>.json) + safety model
├── .cursor/rules/
│   └── accel-mirror.mdc         # Cursor rule (routing + hard rules)
├── docs/
│   └── index.html               # Data dashboard (GitHub Pages, data inlined by build_dashboard.py)
└── .github/
    ├── ISSUE_TEMPLATE/
    │   └── network-report.yml   # "网络实测上报" form: the zero-friction contribution path
    └── workflows/
        ├── mirror-test.yml      # Weekly CI full-speed test (survival monitoring + selftest)
        ├── report-ingest.yml    # Ingest issue reports -> aggregate -> rebuild dashboard -> reply
        └── pages.yml            # Publish docs/ dashboard to GitHub Pages
```

## How to Use This Skill

### Phase 1 — Read the database

Always start by reading `references/mirrors.json`. This file contains:
- All known mirrors with scores (0–100, higher = better)
- Status flags (`active` / `deprecated`)
- Last test timestamps
- Usage examples and notes

Categories: `docker_community`, `docker_enterprise`, `github`, `tools`, `ai_models`, `python`, `dev_registry`.

### Phase 2 — Identify user need

| User says | Action |
|-----------|--------|
| "docker pull 慢" / "docker 拉不下来" | → Docker acceleration (Phase 3a) |
| "git clone 慢" / "github 打不开" | → GitHub acceleration (Phase 3b) |
| "配置 docker 源" / "daemon.json" | → Docker daemon.json config (Phase 3a) |
| "github 下载加速" / "release 下载慢" | → GitHub download acceleration (Phase 3b) |
| "npm 慢" / "pip 慢" / "go proxy" / "apt 超时" / "brew 慢" | → Package manager mirrors (Phase 3c) |
| "下载失败" / "哈希不一致" / "装下载器" | → Downloader self-check (Phase 3d) |
| "huggingface 模型下载断流" / "pip install torch 慢" / "conda 装不上" / "ghcr.io 拉不动" | → AI & registry mirrors (Phase 3e) |
| "测一下镜像源" / "哪个源最快" | → Run test scripts (Phase 4) |

### Phase 3a — Docker acceleration

1. Present top 5–8 scored `docker_community` mirrors (sorted by score descending)
2. Generate a ready-to-use `daemon.json` with the top 3–5 mirrors
3. Mention Huawei Cloud `ddn-k8s` as enterprise fallback (from `docker_enterprise`)
4. Read `references/docker-mirrors-guide.md` if user needs detailed explanation or troubleshooting

Quick template:
```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<-'EOF'
{
  "registry-mirrors": [
    "https://<best_mirror_1>",
    "https://<best_mirror_2>",
    "https://<best_mirror_3>"
  ]
}
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
# Verify:
docker info | grep -A 5 "Registry Mirrors"
```

Huawei Cloud fallback (when all community mirrors fail):
```bash
docker pull swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/<image>:<tag>
docker tag swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/<image>:<tag> <image>:<tag>
```

### Phase 3b — GitHub acceleration

1. Present top 5 scored `github` mirrors sorted by score
2. Provide clone / download commands using the best-scoring proxy
3. Offer global git config option for permanent acceleration
4. Read `references/github-mirrors-guide.md` if user needs alternatives or self-hosted options

Quick commands:
```bash
# Clone via proxy
git clone https://<best_proxy>/https://github.com/user/repo.git

# Download release file
wget https://<best_proxy>/https://github.com/user/repo/releases/download/v1.0/file.zip

# Global config (one-time, applies to all future clones)
git config --global url."https://<best_proxy>/https://".insteadOf "https://github.com/"
# To undo:
# git config --global --unset url."https://<best_proxy>/https://".insteadOf
```

For one-off file downloads (release assets / archive tarballs / raw files), prefer `scripts/accel-fetch.sh` — it auto-probes the top-scored prefix proxies, picks the fastest reachable one, and falls back on failure:

```bash
bash scripts/accel-fetch.sh https://github.com/user/repo/releases/download/v1.0/file.zip
bash scripts/accel-fetch.sh --list   # show currently available prefix proxies
bash scripts/accel-fetch.sh --doctor # check/downloader self-test
```

### Phase 3c — Package manager mirrors

Present relevant entries from the `tools` category. One-liners:

- npm: `npm config set registry https://registry.npmmirror.com`
- pip: `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>`
- Go: `go env -w GOPROXY=https://goproxy.cn,direct`

For apt / Homebrew / Rust / Composer / RubyGems / Gradle / Maven and the full
configuration walkthrough, read `references/package-managers-guide.md` and use
the top-scored mirror for each tool from the `tools` category.

### Phase 3d — 下载器自检与安装（下载难题标准流程）

**当用户遇到下载慢/失败/哈希不一致时，AI 应按以下流程处理：**

1. **先自检**：`bash scripts/accel-fetch.sh --doctor`
   - 检查 aria2c（多线程引擎）/ curl（最稳）/ axel（备用）是否可用
   - 缺失的自动给出安装命令并执行（见下表）
2. **装齐三件套**（aria2 + curl + axel），按平台执行：

| 平台 | 安装命令 |
|------|---------|
| Debian/Ubuntu（含 proot 小电脑） | `sudo apt-get update && sudo apt-get install -y aria2 curl axel` |
| CentOS/RHEL/Fedora | `sudo yum install -y aria2 curl axel`（或 dnf） |
| Alpine | `apk add aria2 curl axel` |
| macOS (Homebrew) | `brew install aria2 axel` |
| Termux (Android) | `pkg install aria2 curl axel` |

3. **再用 `--doctor` 验证**，确认 3/3 后再下载
4. **下载**：`bash scripts/accel-fetch.sh <github_url> [-o 文件名] [--sha256 哈希]`
   - auto 模式自动用 aria2 多线程（16×16），失败回退 curl → axel
   - 每轮下载做【大小校验】（多数投票基准）与可选 SHA256 校验
   - 校验失败自动换下一候选源，直到成功

**已知教训（2026-09 实战）**：
- aria2 多线程经部分代理 Range 可能不完整 → 必须做大小/哈希校验，不能只看「下载完成」
- 部分加速源（如 gh.con.sh）响应快但返回错误页/小文件 → 期望大小用**多数投票**（可达源中出现最多的 size），防单一坏源带偏
- GitHub release 资产不提供 SHA256 字段，APK 类文件建议用签名校验作为最终权威验证

**安全硬规则**：prefix 型代理本质是第三方中间人。凡是**可执行文件 / 安装包 / 脚本**
（.exe .msi .apk .deb .dmg .pkg .sh .zip 内含可执行物等），下载后**必须**校验
SHA256（`--sha256`）或发布方签名，校验通过才允许执行——即使下载流程提示"成功"。
纯数据文件（文档、数据集）可放宽为可选校验。

**平台兼容性**：本 skill 的脚本基于 bash + GNU coreutils（curl/awk/stat/sha256sum）。
- Linux / macOS / Termux / proot：开箱即用
- **Windows**：必须在 Git Bash 或 WSL 内运行，不要用 cmd / PowerShell 直接调用
  （`stat -c%s`、`sha256sum` 等命令在原生 Windows 不存在）

### Phase 3e — AI 与容器仓库镜像（模型 / Python / 非 DockerHub 仓库）

这三类是**国内 AI 开发者最高频的痛点**，分别对应 `ai_models`、`python`、`dev_registry` 分类。

**1. HuggingFace 模型下载（`ai_models`）**

首选 hf-mirror，环境变量必须**在 import transformers 之前**设好：

```bash
# CLI
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download <org>/<model>

# 加 hf_transfer 多线程（大模型权重提速明显）
pip install hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1
```

```python
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"   # 必须写在 transformers 之前
from transformers import AutoModel
```

国内原生替代：**ModelScope 魔搭**（`modelscope.cn`）——热门模型官方同步，不依赖 HF：

```bash
pip install modelscope
modelscope download --model <org>/<name>
# 或直接 git clone https://www.modelscope.cn/<org>/<name>.git
```

选择建议：小文件 / 冷门模型走 hf-mirror；大权重、热门模型优先 ModelScope。

**2. pip / conda / PyTorch（`python`）**

```bash
# pip 永久换源
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# PyTorch CUDA 版（走清华 pytorch-wheels，避免从 download.pytorch.org 拉 2GB）
pip install torch --index-url https://mirrors.tuna.tsinghua.edu.cn/pytorch-wheels/cu121
```

```yaml
# ~/.condarc —— conda 换清华源
channels:
  - defaults
default_channels:
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
```

注意：PyPI 的 simple 索引页体积很大，**首字节延迟高不代表装包慢**（见 Phase 4 的测速说明）。

**3. 非 DockerHub 容器仓库（`dev_registry`）**

| 原仓库 | 国内镜像 | 说明 |
|--------|---------|------|
| `ghcr.io` | `ghcr.m.daocloud.io` / `ghcr.nju.edu.cn` | GitHub Container Registry |
| `quay.io` | `quay.m.daocloud.io` / `quay.nju.edu.cn` | Red Hat Quay |
| `registry.k8s.io` | `k8s.m.daocloud.io` / `registry.aliyuncs.com/google_containers` | Kubernetes 官方镜像 |
| `nvcr.io` | `nvcr.m.daocloud.io` | NVIDIA NGC（AI 训练容器） |

用法就是**替换镜像名前缀**，拉下来再 tag 回原名：

```bash
docker pull ghcr.m.daocloud.io/<owner>/<image>:<tag>
docker tag  ghcr.m.daocloud.io/<owner>/<image>:<tag> ghcr.io/<owner>/<image>:<tag>
```

### Phase 4 — Dynamic testing & sorting

When the user asks to test mirrors, or when mirrors haven't been tested in 7+ days:

```bash
# Test all mirrors and save results
bash scripts/test_mirrors.sh --type all --output /tmp/mirror_test_results.json

# Update scores in mirrors.json
python3 scripts/update_mirrors.py --input /tmp/mirror_test_results.json

# Deep mode (slower): additionally measure real 1MB download throughput
# through each github prefix proxy (writes throughput_bps into mirrors.json)
bash scripts/test_mirrors.sh --type github --deep --output /tmp/gh_result.json
```

The test script uses `curl` to time each mirror's response. The update script recalculates scores using a **log scale**:
```
score = max(0, round(100 - 20 * log10(1 + response_time_seconds / 0.1)))
```
This spreads the useful range: 100ms → 94, 500ms → 84, 1s → 79, 3s → 70, 30s → 50 —
fast mirrors no longer all saturate at 99. Ties are broken by actual latency
(`test_time_ms` ascending), and by measured throughput when deep-mode data exists.

Mirrors that fail (timeout / connection error) get score 0 and status `deprecated` after 3 consecutive failures.

Other update-script modes:
- `--rescore` — recompute all scores from stored latency (e.g. after a formula change, no re-test needed)
- `--input results.json --record-alive` — record a CI survival snapshot (`last_ci_alive` field) without touching scores
- `--aggregate reports/*.json --min-samples N` — merge crowd-sourced reports and rescore by **median** (see Phase 5)
- `--db /path/to/copy.json` — operate on a copy instead of the live database (used by tests)

The repository also ships `.github/workflows/mirror-test.yml` — a weekly GitHub Actions run of the same full test that posts a health summary and stamps `last_ci_alive` on mirrors that responded. **CI never writes back scores**: GitHub's datacenter network differs from real user networks, so scoring must stay local (`test_mirrors.sh` → `update_mirrors.py`).

### Phase 5 — Serve the answer: HTTP API, or query one

Two directions, depending on whether you are the **provider** or the **consumer**.

**As a consumer (fastest path, no install):** if an accel-mirror API is reachable, one GET
replaces all the JSON reading above and returns a ready-to-run command:

```bash
curl -s "http://<api-host>/v1/best?service=pip&format=text"
# # pip → 用 pip 清华镜像
#   pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>

curl -s "http://<api-host>/v1/best?service=github&limit=3"   # JSON with fallbacks + caveats
curl -s "http://<api-host>/v1/services"                      # all 25 service names
```

Service names are resolved through `references/recipes.json` (aliases include colloquial
Chinese, e.g. `模型下载` → `ai-models`, `镜像加速` → `docker`). Always forward the `caveats`
array to the user: it flags stale data (`dataset.age_days > 7`), single-source scores
(`samples` null) and unstable mirrors (`failed_reports > 0`).

**As a provider (if the user wants to run it):**

```bash
python3 server/accel_mirror_api.py                      # 127.0.0.1:8787
docker compose -f server/docker-compose.yml up -d --build
```

The API is **read-only and makes no outbound requests** — deliberately no
"probe this URL for me" endpoint, because that would be a public SSRF pivot.
Liveness data comes from CI and local `test_mirrors.sh` runs only.

### Phase 6 — Crowd-sourced data (make the scores trustworthy)

A single machine's measurement cannot be verified by anyone else. When the user wants
the numbers to carry weight beyond their own box:

```bash
# 1) Produce an anonymised report (no IP / path / user id / device info)
bash scripts/test_mirrors.sh --type all --output my_report.json --network-label "北京联通 500M"

# 2) Maintainer: merge reports, score by median
python3 scripts/update_mirrors.py --aggregate reports/*.json --min-samples 3
```

**Route A — an issue is the submission channel (no fork, no PR, no git knowledge):**

Anyone can run the test locally and paste the JSON into the
[「网络实测上报」issue form](../.github/ISSUE_TEMPLATE/network-report.yml). Then
`scripts/ingest_report.py` + `.github/workflows/report-ingest.yml` ingest it, aggregate,
rebuild the dashboard and reply in the issue.

The ingest script is the **trust boundary**, and it is deliberately whitelist-shaped:

| Guarantee | Why it matters |
|---|---|
| every row is reduced to `{name, status, time_ms}` | the submitter's `url` never reaches the database |
| `name` must already exist in `references/mirrors.json` | a report can move a **known** mirror's score but can never **introduce** a mirror |

That second rule is not pedantry. If reports could add sources, anyone could submit a
"0ms mirror" that actually serves tampered `aria2c` / `pip` / model-weight payloads, win the
ranking, and be recommended to every user of this library — a supply-chain attack delivered by
an issue form. Because of the whitelist, the privacy of the produced file is a
**constructive** property, not a regex scan that "probably" finds nothing.

**Route B — the maintainer merges reports locally:**

```bash
python3 scripts/update_mirrors.py --aggregate reports/*.json --min-samples 3
```

Rules the merger enforces (also asserted in `scripts/selftest.py`):

| Rule | Why |
|---|---|
| **median**, not mean | one bad-network report must not skew the ranking |
| `--min-samples N` skips thin coverage | a single sample shouldn't lock in a score |
| deprecate only if **zero successes and ≥3 failures** | a mirror that sometimes works is flaky, not dead |
| record `failed_reports` even when it also succeeded | flakiness is real signal worth surfacing |
| write a `crowd` metadata block | makes data provenance auditable |

### Phase 7 — Verify before trusting any change

After editing data, recipes, or scoring rules:

```bash
python3 scripts/selftest.py                       # 129 semantic assertions, no dependencies
python3 server/accel_mirror_api.py --self-test    # API behaviour self-check
```

These catch what syntax checks cannot: a generated `docker pull https://x` (scheme is
invalid in image references), a `github` answer pointing at a non-automatable web tool,
a recipe referencing a guide file that does not exist, an aggregate that used the mean,
an ingested issue report that smuggled in an unknown source, or an `AGENTS.md` that points
at a file which no longer exists. CI runs both on every push.

### Phase 8 — Distribution: get the answer in front of the agent

Data and endpoints are useless if no agent ever reads them. Three layers, cheapest first:

| Layer | Artifact | Who picks it up |
|---|---|---|
| Agent convention | `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/accel-mirror.mdc` | any coding agent that opens the repo |
| Retrieval entry | `llms.txt`, README `## For AI agents` | agents that search / read raw URLs |
| Standard interface | `mcp_server/` (MCP), `server/` (HTTP) | agents that can call a tool or a URL |

When adding a file or a category, keep `llms.txt` and `AGENTS.md` in sync — the selftest
asserts that every path referenced by `AGENTS.md` still exists, so a stale link fails CI.

## Self-Evolution Protocol

This skill is designed to evolve indefinitely. The AI agent using this skill has **full authority** to modify the following files to keep the skill current and useful:

### Files the AI CAN and SHOULD modify freely:

- **`references/mirrors.json`** — Add new mirrors, update scores, change status, append to `evolution_log`
- **`references/recipes.json`** — Add a new service name / alias / command template (data-driven; `server/` and `mcp_server/` both read it, so one edit covers both)
- **`references/docker-mirrors-guide.md`** — Update with new findings, configurations, or tips
- **`references/github-mirrors-guide.md`** — Update with new findings, configurations, or tips
- **`references/ai-models-guide.md`** — Update with new findings, configurations, or tips
- **`references/package-managers-guide.md`** — Update with new findings, configurations, or tips
- **`scripts/test_mirrors.sh`** — Improve testing logic or add new test types
- **`scripts/update_mirrors.py`** — Improve scoring algorithm or add features
- **`scripts/selftest.py`** — Add an assertion whenever you fix a class of bug (this is what keeps regressions out)
- **`llms.txt`** — Keep the AI-facing index in sync when categories/files change (this is the entry point AI agents read first)
- **`mcp_server/accel_mirror_mcp.py`** — Add or improve MCP tools
- **`server/accel_mirror_api.py`** — Add or improve HTTP endpoints (keep it read-only and dependency-free)
- **`docs/index.html`** — Generated by `python3 scripts/build_dashboard.py` (data inlined from mirrors.json). Regenerate after DB changes.

### Files that require user confirmation for structural changes:
- **`SKILL.md`** — The workflow structure and sections should remain stable. Minor content updates (e.g., adding a new quick command) are OK.

### Evolution triggers (do these whenever applicable):

1. **After each use**: If the user reported a mirror as fast/slow/broken, update its score and log the change in `evolution_log`
2. **Periodic testing**: If `last_full_test` in mirrors.json is >7 days old or null, suggest running the test scripts
3. **New discovery**: When the AI discovers a new mirror via search or user input, add it to mirrors.json with `score: 50` (neutral default for untested) and log it
4. **Failure pattern**: If a mirror fails 3+ consecutive tests, set `status: "deprecated"` and `score: 0`
5. **Revival**: If a deprecated mirror passes testing, restore `status: "active"` and assign a real score
6. **Strategy shift**: If the mirror landscape changes significantly (e.g., a major policy change), update the strategy guidelines in SKILL.md and the reference files

### Evolution log format

Every change to mirrors.json must be logged in the `evolution_log` array:
```json
{"date": "2026-09-09", "action": "added|updated_score|deprecated|revived|tested|strategy_change|capability_added", "details": "Human-readable description of what changed"}
```

### Adding a new mirror

When discovering a new mirror (via search, user input, or testing):
1. Determine its category (`docker_community`, `docker_enterprise`, `github`, `tools`, `ai_models`, `python`, `dev_registry`)
2. Set initial `score: 50` if untested, or calculate from test data
3. Set `status: "active"`, `last_tested: null`
4. Include `test_url` for curl-based testing
5. Add usage examples where applicable
6. Log the addition in `evolution_log`
7. If the new mirror serves a service that already has a recipe (`references/recipes.json`),
   check whether the existing `match` regex covers its name; if not, widen the regex
8. If the category set itself changed, update the category lists in `scripts/update_mirrors.py`
   (`SORTED_CATEGORIES`), `scripts/test_mirrors.sh` (`CATEGORIES`) and `llms.txt`
9. Run `python3 scripts/selftest.py` before finishing — it validates data shape, recipe
   references and API answers, so a typo cannot slip through

## Scoring System

Log-scale formula (v1.3.0): `score = max(0, round(100 - 20 * log10(1 + t_s / 0.1)))`

| Range | Rating | Response time |
|-------|--------|---------------|
| 95–100 | 极速 | < 100ms |
| 90–94 | 优秀 | 100–220ms |
| 80–89 | 良好 | 220ms–0.9s |
| 70–79 | 可用 | 0.9–3s |
| 50–69 | 慢 | 3–30s (or untested default) |
| 0–49 | 不可用 | > 30s / failed / deprecated |

Untested mirrors default to score 50. When several mirrors share a score,
rank by stored latency (`test_time_ms`) and, if available, throughput
(`throughput_bps` from deep mode).

Initial scores are based on 2025-06-15 community testing data from jishuzhan.net
(rescaled to the current formula). Scores are refreshed by running the test scripts.

## Strategy Guidelines

1. **Docker**: Use 3–5 top-scored community mirrors in `daemon.json` + Huawei Cloud `ddn-k8s` as manual fallback. Docker tries mirrors in list order, so put the best first.
2. **GitHub**: Use proxy prefix for one-off clones/downloads, or `git config --global url.insteadOf` for permanent acceleration. Always have 2–3 proxies ready as alternatives.
3. **Enterprise vs Community**: Enterprise mirrors (Huawei Cloud) are stable but require manual path construction. Community mirrors are transparent (once configured) but can disappear overnight.
4. **Always test before relying**: When setting up a new environment, run `test_mirrors.sh` first.
5. **The landscape changes fast**: 2024年6月 policy changes killed many mirrors. 2026年6月 上海交大 and 中科大 mirrors were forced offline. Always have fallbacks.
6. **AI 场景优先走国内原生源**: 能用 ModelScope / 清华 PyTorch wheels 解决的，就不要绕 hf-mirror。原生源没有代理中间层，稳定性和速度都更好。
7. **测速要看指标匹配场景**: PyPI simple 索引、HF 仓库页这类「索引页」本身很大，首字节延迟高不代表装包 / 拉模型慢。判断模型下载源优劣时应以 `--deep` 的真实吞吐为准，而不是首页 RTT。

## Important Notes

- Mirror availability changes frequently — what works today may die tomorrow
- The `mirrors.json` database is the single source of truth — always read it first, always update it after use
- The self-evolution mechanism is what makes this skill valuable long-term — use it every time
- If all mirrors fail, suggest the user self-host a ghproxy instance (see `references/github-mirrors-guide.md`)
- For Docker, `docker.m.daocloud.io` and `docker.xuanyuan.me` have been among the most resilient community mirrors
- For GitHub, Gitee mirror and Tsinghua mirror are the most stable long-term options
- 若你的客户端支持 MCP（Claude Desktop / Trae / Cherry Studio / Cline 等），可直接接入
  `mcp_server/accel_mirror_mcp.py`，把查库变成工具调用（`best_mirror` / `list_mirrors` / `test_mirror`），
  比读文件更省 token。`best_mirror` 的 `service` 参数接受服务名（`pip`）、中文口语别名（`模型下载`）
  与分类名（`python`）；解析与选源逻辑与只读 HTTP 接口共用同一份实现
- 人类可读的实测榜单与存活率看板在 `docs/index.html`（GitHub Pages）；它由
  `python3 scripts/build_dashboard.py` 从 `references/mirrors.json` 生成（数据内联，单文件可离线打开），
  改库后记得重新生成
- 面向 AI 代理的入口索引是 `llms.txt`——改分类或加文件时同步更新它；
  `AGENTS.md`（跨工具代理手册）、`CLAUDE.md`（Claude Code 精简版）与
  `.cursor/rules/accel-mirror.mdc`（Cursor 规则）是分发给「打开仓库的编码代理」的入口，
  改动文件结构时一并维护，自检会校验 `AGENTS.md` 里引用的路径是否真实存在
- 数据看板由 `.github/workflows/pages.yml` 发布到 GitHub Pages：每次数据或看板变更都会
  **先重建页面再跑自检**，自检不过就不部署——线上不会出现脏数据
- 众包上报的零门槛入口是 GitHub Issue 表单（`.github/ISSUE_TEMPLATE/network-report.yml`），
  由 `.github/workflows/report-ingest.yml` 自动入库；**上报只能移动已知源的分数，
  不能新增源**，这条约束由 `scripts/ingest_report.py` 强制并已固化成断言
- **绝不推荐未知的第三方「模型代理站」**：模型权重被替换（植入后门）的风险远高于省下的那点带宽。
  模型下载优先给国内原生源（ModelScope / OpenXLab），其次 hf-mirror
- 生成任何 `docker pull` 命令时，**镜像引用里不能出现 `https://`**——Docker 会直接报错。
  `server/` 的配方已内置该规则（`strip_scheme`），手工拼命令时同样要遵守
- 转发 API 结果时，把 `caveats` 一起转给用户：数据过期、只有单机数据、源不稳定这三点
  都会影响结论，不要让用户以为拿到的是一份确定无疑的排名
