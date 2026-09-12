# accel-mirror

> 让任何 AI 代理在处理下载任务时，自动命中当前最优加速镜像的自我进化技能。

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Mirrors: 102](https://img.shields.io/badge/mirrors-102-blue)
![Version: 1.2.0](https://img.shields.io/badge/version-1.2.0-orange)
[![CI](https://github.com/gitfox-enter/accel-mirror/actions/workflows/mirror-test.yml/badge.svg)](https://github.com/gitfox-enter/accel-mirror/actions/workflows/mirror-test.yml)

---

## 这是什么

国内直连 GitHub / Docker Hub 经常超时、断流、龟速。网络上散落着大量社区加速镜像，但它们的可用性**随时间剧烈波动**——今天快的，明天可能就是 403 / 超时。

`accel-mirror` 是一个 **「自我进化的加速镜像知识库」**：

1. **资产**：一份结构化的镜像数据库（`mirrors.json`），覆盖 4 大分类、102 个镜像源
2. **测速引擎**：`test_mirrors.sh` 并发实测每个镜像的真实响应（真实网络环境、真实延迟）
3. **评分进化**：`update_mirrors.py` 依据实测延迟自动重排、打分、累计失败并弃用死链
4. **AI 友好**：技能文件（`SKILL.md`）教会任何 AI 代理「下载前先查库，优先选高分源」

任何 AI 代理（或其他自动化工具）读取本库后，都能在下载任务中自动命中**当前网络下最快**的加速源，而不是盲目尝试。

---

## 核心卖点

| 特性 | 说明 |
|---|---|
| 🧬 自我进化 | 实测 → 打分 → 排序 → 弃用死链，全部自动化 |
| 🗂️ 四分类库 | Docker 社区 / Docker 企业 / GitHub / 常用工具 |
| 📈 动态评分 | `score = max(0, round(100 - 响应时间秒 × 2))` |
| ⚡ 并发测速 | Bash 脚本多源并发，102 源分钟级全量测速 |
| 🤖 CI 监控 | GitHub Actions 每周自动全量测速 + 健康摘要（存活率监控） |
| 🧠 AI 可读 | SKILL.md 结构化工作流，Agent 开箱即用 |
| 🔒 零隐私 | 纯通用知识库，无个人路径 / token / 部署信息 |

---

## 快速开始

### 手动测试某个分类

```bash
# 测试全部 GitHub 镜像源（约 1 分钟）
bash scripts/test_mirrors.sh --type github --output /tmp/gh_result.json --timeout 8

# 测试全部 Docker 社区镜像
bash scripts/test_mirrors.sh --type docker --output /tmp/docker_result.json --timeout 10

# 全部
bash scripts/test_mirrors.sh --type all --output /tmp/all_result.json --timeout 10
```

### 回写评分

```bash
python3 scripts/update_mirrors.py --input /tmp/gh_result.json
```

回写后 `mirrors.json` 自动完成：
- ✅ 按响应延迟重新打分（`score = 100 - t×2`，最低 0）
- ✅ 按分数降序重排
- ✅ 失败源累计 `consecutive_failures`，连续 3 次失败自动弃用
- ✅ 自动追加 `evolution_log`（可追溯的进化记录）
- ✅ 更新 `last_updated` / `last_full_test` 时间戳

### 自动化健康监控（CI）

仓库内置 GitHub Actions 工作流（`.github/workflows/mirror-test.yml`）：

- ⏰ 每周日 22:00 UTC（北京时间周一 06:00）自动跑一次全量测速，也可手动触发
- 📋 自动生成健康摘要（按分类统计 ✅ / ❌ / ⏭️），测速结果以 Artifact 存档
- 🧭 设计原则：**CI 只做存活率监控与报告，不回写分数**——CI 运行在 GitHub 数据中心网络，与国内用户网络不同，评分仍以本地 `test_mirrors.sh` 实测为准

---

## 直接下载加速文件（GitHub Release 等场景）

### 方式一：智能选源下载（推荐）

`scripts/accel-fetch.sh` 自动完成「查库 → 并发探测 → 选最快 → 失败回退」全流程，无需手工指定代理：

```bash
# 下载 GitHub Release 资产（自动选当前最快可达源，失败自动切换下一候选）
bash scripts/accel-fetch.sh https://github.com/user/repo/releases/download/v1.0.0/app.zip

# 指定保存路径 / 超时 / 候选源数量
bash scripts/accel-fetch.sh \
  https://github.com/user/repo/archive/refs/heads/main.zip \
  -o main.zip --timeout 8 --top 8

# 仅列出当前可用的 prefix 型加速源（不下载）
bash scripts/accel-fetch.sh --list
```

### 方式二：手工指定代理（查库选源）

```bash
# 示例：从 GitHub Release 下载大文件（假设库中最优源为 gh-proxy.com）
curl -L -o app.zip \
  "https://gh-proxy.com/https://github.com/user/repo/releases/download/v1.0.0/app.zip"
```

同理可应用于 Docker 镜像拉取场景（配合各 Docker Hub 镜像站），详见
[references/docker-mirrors-guide.md](references/docker-mirrors-guide.md) 与
[references/github-mirrors-guide.md](references/github-mirrors-guide.md)。

---

## 镜像库现状（2026-09-12 实测）

| 分类 | 数量 | 活跃 | 弃用 | 最优源（本次实测） |
|---|---|---|---|---|
| `docker_community` | 36 | 36 | 0 | docker.m.daocloud.io（99 分，480ms） |
| `docker_enterprise` | 2 | 2 | 0 | 华为云 SWR ddn-k8s（99 分，457ms） |
| `github` | 45 | 45 | 0 | gitclone.com（99 分，628ms） |
| `tools` | 19 | 19 | 0 | apt 阿里（99 分，488ms） |

**GitHub 加速源 Top 5（2026-09-12 国内网络实测）：**

```
 99 │ gitclone.com             628ms
 99 │ github.akams.cn          642ms
 99 │ toolwa.com/github        386ms
 99 │ gh.h233.eu.org           590ms
 98 │ bgithub.xyz             1195ms
```

> ⚠️ 镜像源存活率变化极快。以上排名仅为发布时刻快照，**请以最新实测为准**——这正是本项目存在的意义。

---

## 文件结构

```
accel-mirror/
├── SKILL.md                      # 技能主文件：AI 工作流 + 自我进化协议
├── references/
│   ├── mirrors.json              # 镜像数据库（版本化 + evolution_log）
│   ├── docker-mirrors-guide.md   # Docker 镜像使用指南
│   └── github-mirrors-guide.md   # GitHub 加速使用指南
├── scripts/
│   ├── test_mirrors.sh           # 并发测速脚本（curl 实测）
│   ├── update_mirrors.py         # 评分 / 排序 / 弃用 / 进化日志引擎
│   └── accel-fetch.sh            # GitHub 文件自动加速下载（智能选源 + 回退）
└── .github/
    └── workflows/
        └── mirror-test.yml       # 每周自动全量测速 CI（存活率监控）
```

---

## 贡献指南

欢迎补充新镜像源或提交实测数据。直接编辑 `references/mirrors.json`，或通过脚本添加：

```bash
python3 scripts/update_mirrors.py \
  --add \
  --name "my-new-mirror" \
  --url "https://example.com/" \
  --category github \
  --test-url "https://example.com/https://github.com/" \
  --notes "简短说明"
```

**JSON 条目模板：**

```json
{
  "name": "mirror-name",
  "url": "https://mirror.example.com/",
  "test_url": "https://mirror.example.com/test-path",
  "score": 50,
  "last_tested": null,
  "test_time_ms": null,
  "status": "active",
  "notes": "补充说明"
}
```

提交 PR 时请尽量附带一行实测数据（时间 / 延迟 / 状态），便于社区追溯。

---

## 致谢

- **Operit AI** —— 本项目诞生于 Operit 平台技能生态，感谢平台对 skill 开发的支持
- **jishuzhan.net** —— 早期 Docker 镜像社区测速数据的参考来源
- 所有维护社区加速镜像的开发者（来源见 `mirrors.json` 各条目 notes）

## LICENSE

[MIT](LICENSE) © 2026 gitfox-enter