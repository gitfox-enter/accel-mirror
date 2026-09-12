---
name: accel-mirror
description: Manage and apply network acceleration mirrors for Docker Hub images and GitHub access. Use this skill whenever the user needs to pull Docker images, configure Docker daemon.json with registry mirrors, clone or download from GitHub, set up GitHub proxy/acceleration, or encounters slow/blocked access to Docker Hub or GitHub. Also triggers on: docker mirror, 镜像加速, ghproxy, git clone slow, registry-mirrors, docker pull timeout, github 加速, 镜像源, 华为云 swr, ddn-k8s, docker源, github镜像, npm镜像, pip镜像, or any similar acceleration/proxy concept. Even if the user just mentions "docker慢", "github打不开", "镜像", or "加速", use this skill immediately.
---

# Accelerated Mirror Manager (accel-mirror)

A self-evolving skill that manages a curated, dynamically sorted database of network acceleration mirrors for Docker Hub, GitHub, and related ecosystems (npm/pip/Go). Designed to grow smarter with every use.

## File Structure

```
accel-mirror/
├── SKILL.md                      # This file (main instructions)
├── references/
│   ├── mirrors.json             # Live mirror database (scores, status, metadata)
│   ├── docker-mirrors-guide.md  # Docker acceleration detailed guide
│   └── github-mirrors-guide.md  # GitHub acceleration detailed guide
└── scripts/
    ├── test_mirrors.sh          # Speed/availability testing (curl-based)
    └── update_mirrors.py         # Score update & sorting (Python3)
```

## How to Use This Skill

### Phase 1 — Read the database

Always start by reading `references/mirrors.json`. This file contains:
- All known mirrors with scores (0–100, higher = better)
- Status flags (`active` / `deprecated`)
- Last test timestamps
- Usage examples and notes

The mirrors are grouped into four categories: `docker_community`, `docker_enterprise`, `github`, `tools`.

### Phase 2 — Identify user need

| User says | Action |
|-----------|--------|
| "docker pull 慢" / "docker 拉不下来" | → Docker acceleration (Phase 3a) |
| "git clone 慢" / "github 打不开" | → GitHub acceleration (Phase 3b) |
| "配置 docker 源" / "daemon.json" | → Docker daemon.json config (Phase 3a) |
| "github 下载加速" / "release 下载慢" | → GitHub download acceleration (Phase 3b) |
| "npm 慢" / "pip 慢" / "go proxy" | → Package manager mirrors (Phase 3c) |
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

### Phase 3c — Package manager mirrors

Present relevant entries from the `tools` category:
- npm: `npm config set registry https://registry.npmmirror.com`
- pip: `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>`
- Go: `go env -w GOPROXY=https://goproxy.cn,direct`

### Phase 4 — Dynamic testing & sorting

When the user asks to test mirrors, or when mirrors haven't been tested in 7+ days:

```bash
# Test all mirrors and save results
bash scripts/test_mirrors.sh --type all --output /tmp/mirror_test_results.json

# Update scores in mirrors.json
python3 scripts/update_mirrors.py --input /tmp/mirror_test_results.json
```

The test script uses `curl` to time each mirror's response. The update script recalculates scores using:
```
score = max(0, round(100 - response_time_seconds * 2))
```
Mirrors that fail (timeout / connection error) get score 0 and status `deprecated` after 3 consecutive failures.

## Self-Evolution Protocol

This skill is designed to evolve indefinitely. The AI agent using this skill has **full authority** to modify the following files to keep the skill current and useful:

### Files the AI CAN and SHOULD modify freely:

- **`references/mirrors.json`** — Add new mirrors, update scores, change status, append to `evolution_log`
- **`references/docker-mirrors-guide.md`** — Update with new findings, configurations, or tips
- **`references/github-mirrors-guide.md`** — Update with new findings, configurations, or tips
- **`scripts/test_mirrors.sh`** — Improve testing logic or add new test types
- **`scripts/update_mirrors.py`** — Improve scoring algorithm or add features

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
{"date": "2026-09-09", "action": "added|updated_score|deprecated|revived|tested|strategy_change", "details": "Human-readable description of what changed"}
```

### Adding a new mirror

When discovering a new mirror (via search, user input, or testing):
1. Determine its category (`docker_community`, `docker_enterprise`, `github`, `tools`)
2. Set initial `score: 50` if untested, or calculate from test data
3. Set `status: "active"`, `last_tested: null`
4. Include `test_url` for curl-based testing
5. Add usage examples where applicable
6. Log the addition in `evolution_log`

## Scoring System

| Range | Rating | Meaning |
|-------|--------|---------|
| 90–100 | 极速 | Response < 7s, enterprise-grade or top community |
| 80–89 | 优秀 | Response 7–10s, reliable |
| 70–79 | 良好 | Response 10–15s, usable |
| 50–69 | 一般 | Response 15–30s or untested-but-known |
| 30–49 | 慢 | Response > 30s, use as last resort |
| 0–29 | 不可用 | Failed/timeout/deprecated |

Initial scores are based on 2025-06-15 community testing data from jishuzhan.net. Scores are refreshed by running the test scripts.

## Strategy Guidelines

1. **Docker**: Use 3–5 top-scored community mirrors in `daemon.json` + Huawei Cloud `ddn-k8s` as manual fallback. Docker tries mirrors in list order, so put the best first.
2. **GitHub**: Use proxy prefix for one-off clones/downloads, or `git config --global url.insteadOf` for permanent acceleration. Always have 2–3 proxies ready as alternatives.
3. **Enterprise vs Community**: Enterprise mirrors (Huawei Cloud) are stable but require manual path construction. Community mirrors are transparent (once configured) but can disappear overnight.
4. **Always test before relying**: When setting up a new environment, run `test_mirrors.sh` first.
5. **The landscape changes fast**: 2024年6月 policy changes killed many mirrors. 2026年6月 上海交大 and 中科大 mirrors were forced offline. Always have fallbacks.

## Important Notes

- Mirror availability changes frequently — what works today may die tomorrow
- The `mirrors.json` database is the single source of truth — always read it first, always update it after use
- The self-evolution mechanism is what makes this skill valuable long-term — use it every time
- If all mirrors fail, suggest the user self-host a ghproxy instance (see `references/github-mirrors-guide.md`)
- For Docker, `docker.m.daocloud.io` and `docker.xuanyuan.me` have been among the most resilient community mirrors
- For GitHub, Gitee mirror and Tsinghua mirror are the most stable long-term options
