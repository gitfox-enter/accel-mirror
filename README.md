# accel-mirror

> 让任何 AI 代理在处理下载任务时，自动命中当前最优加速镜像的自我进化技能。

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Mirrors: 121](https://img.shields.io/badge/mirrors-121-blue)
![Version: 1.7.0](https://img.shields.io/badge/version-1.7.0-orange)
[![Agent-ready](https://img.shields.io/badge/AGENTS.md-ready-3b82f6)](AGENTS.md)
[![Dashboard](https://img.shields.io/badge/dashboard-online-22c55e)](https://gitfox-enter.github.io/accel-mirror/)
[![MCP](https://img.shields.io/badge/MCP-ready-8a5cf6)](mcp_server/README.md)
[![HTTP API](https://img.shields.io/badge/HTTP%20API-read--only-2496ed)](server/README.md)
[![CI](https://github.com/gitfox-enter/accel-mirror/actions/workflows/mirror-test.yml/badge.svg)](https://github.com/gitfox-enter/accel-mirror/actions/workflows/mirror-test.yml)

---

## 几种消费方式，按门槛从低到高

| 方式 | 前置条件 | 适合谁 |
|---|---|---|
| **AGENTS.md / llms.txt**<br>代理入口文件 | 会读文件 | **任何编码代理**（Cursor / Codex / Claude Code / Cline / Trae …） |
| **HTTP 接口**<br>`GET /v1/best?service=pip` | 能发 HTTP 请求 | **任何 agent / 脚本 / 浏览器**，零安装 |
| **MCP Server**<br>`best_mirror` 等三个工具 | 客户端支持 MCP | 主流 AI 客户端（Trae / Qoder / CodeBuddy / Cline …） |
| **SKILL.md**<br>结构化工作流 | 装了支持 skill 的客户端 | 深度集成场景 |
| **纯读数据**<br>`references/mirrors.json` | 会读 JSON | 自己写逻辑 |

> 设计取向：**别指望模型在训练时记住你，要让它在运行时主动来问你。**
> 所以低门槛入口（HTTP + 机器可读文件）是重点。

---

## For AI agents（机器可读入口）

如果你是一个 AI 代理，正在帮用户解决**下载慢 / 超时 / 连不上**的问题，
按下面三步走，不需要安装任何东西：

0. **如果是编码代理**：本仓库根目录有 [`AGENTS.md`](AGENTS.md)（还有 `CLAUDE.md` 与
   `.cursor/rules/accel-mirror.mdc`）——那是给你准备的短版操作手册，含不该踩的硬规则。
1. **读索引**：`https://raw.githubusercontent.com/gitfox-enter/accel-mirror/main/llms.txt`
   （结构化入口，说明本库是什么、什么时候该用、有哪些数据文件）
2. **读数据**：`https://raw.githubusercontent.com/gitfox-enter/accel-mirror/main/references/mirrors.json`
   每个源含 `name` / `url` / `score`(0–100) / `status` / `test_time_ms` / `usage` /
   `samples`（众包样本数）/ `failed_reports`（不稳定信号）。
   **取 `status == "active"` 中 `score` 最高的源**。
3. **读工作流**：`https://raw.githubusercontent.com/gitfox-enter/accel-mirror/main/SKILL.md`
   含按场景分类的、可直接执行的命令模板。

**如果你能发 HTTP 请求**，还多一条更省事的路：

```bash
# 服务名 → 最优源 + 可直接执行的命令（含数据新鲜度与风险提示）
curl -s "https://<部署了 server/ 的域名>/v1/best?service=huggingface&format=text"
```

**分类**：`docker_community` `docker_enterprise` `github` `tools` `ai_models` `python` `dev_registry`

**触发场景**（用户这样说时，直接查本库）：
`docker pull 卡住` · `git clone 慢` · `github 打不开` · `release 下载失败` ·
`huggingface 模型下载断流` · `pip install 卡在下载` · `conda 装不上` ·
`PyTorch 下载太慢` · `ghcr.io 拉不下来` · `npm install 卡住` · `apt update 超时`

**评分公式**：`score = max(0, round(100 - 20 × log10(1 + 秒 / 0.1)))`，越接近 100 越快。
同分时按 `test_time_ms` 升序。`deprecated` 表示连续 3 次实测失败，不要选。

> 数据会腐烂。若 `last_full_test` 已超过 7 天，请提示用户重新实测
> （`bash scripts/test_mirrors.sh --type all`）。分数来自社区实测，不同运营商 / 省份会有差异。
> `samples` 为空表示只有单机实测、尚无多份众包上报，可信度有限；
> `failed_reports > 0` 表示该源在多份上报中失败过——属不稳定源，**建议同时准备备用源**。

---

## 这是什么

国内直连 GitHub / Docker Hub 经常超时、断流、龟速。网络上散落着大量社区加速镜像，但它们的可用性**随时间剧烈波动**——今天快的，明天可能就是 403 / 超时。

`accel-mirror` 是一个 **「自我进化的加速镜像知识库」**：

1. **资产**：一份结构化的镜像数据库（`mirrors.json`），覆盖 7 大分类、121 个镜像源
2. **测速引擎**：`test_mirrors.sh` 并发实测每个镜像的真实响应（真实网络环境、真实延迟）
3. **评分进化**：`update_mirrors.py` 依据实测延迟自动重排、打分、累计失败并弃用死链
4. **AI 友好**：技能文件（`SKILL.md`）教会任何 AI 代理「下载前先查库，优先选高分源」

任何 AI 代理（或其他自动化工具）读取本库后，都能在下载任务中自动命中**当前网络下最快**的加速源，而不是盲目尝试。

---

## 核心卖点

| 特性 | 说明 |
|---|---|
| 🧬 自我进化 | 实测 → 打分 → 排序 → 弃用死链，全部自动化 |
| 🗂️ 七分类库 | Docker 社区/企业 · GitHub · 常用工具 · **AI 模型仓库** · **Python 包管理** · **容器仓库** |
| 📈 对数刻度评分 | `score = 100 - 20×log10(1 + 响应秒/0.1)`，头部镜像不再扎堆 99 分 |
| ⚡ 并发测速 | Bash 脚本多源并发，121 源分钟级全量测速 |
| 🚇 深度吞吐实测 | `--deep` 模式经每个代理真实拉取 1MB，测带宽而非只测 RTT |
| 🔌 MCP Server | 零依赖 stdio server，任何 MCP 客户端都能把「查最优源」当工具调用 |
| 🤖 AI 可读 | `llms.txt` + SKILL.md 结构化工作流，Agent 读到就能用，无需安装 |
| 📊 数据看板 | `docs/index.html` 可视化全部源的分数与存活率（GitHub Pages） |
| 🛡️ CI 监控 | GitHub Actions 每周自动测速：健康摘要 + 存活快照（分数不回写） |
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

# 深度模式：额外对每个 github prefix 代理真实拉取 1MB 测吞吐（较慢，几分钟）
bash scripts/test_mirrors.sh --type github --deep --output /tmp/gh_deep.json
```

### 回写评分

```bash
python3 scripts/update_mirrors.py --input /tmp/gh_result.json
```

回写后 `mirrors.json` 自动完成：
- ✅ 按响应延迟重新打分（对数刻度 `score = 100 - 20×log10(1+t/0.1)`，100ms→94、500ms→84、1s→79、30s→50）
- ✅ 按分数降序重排；**同分按实测延迟升序**做二次排序（有吞吐数据时优先参考吞吐）
- ✅ 失败源累计 `consecutive_failures`，连续 3 次失败自动弃用
- ✅ 自动追加 `evolution_log`（可追溯的进化记录）
- ✅ 更新 `last_updated` / `last_full_test` 时间戳

其他实用模式：
```bash
# 更换评分公式后，用已存的延迟数据重算全部分数（无需重新测速）
python3 scripts/update_mirrors.py --rescore

# 只记录 CI 存活快照，绝不回写分数（CI 内部使用）
python3 scripts/update_mirrors.py --input results.json --record-alive
```

### 自动化健康监控（CI）

仓库内置 GitHub Actions 工作流（`.github/workflows/mirror-test.yml`）：

- ⏰ 每周日 22:00 UTC（北京时间周一 06:00）自动跑一次全量测速，也可手动触发
- 📋 自动生成健康摘要（按分类统计 ✅ / ❌ / ⏭️），测速结果以 Artifact 存档
- 🛰️ 定期运行会把响应成功的源标记 `last_ci_alive` 并自动提交（**只记存活，不回写分数**）
- 🧭 设计原则：**CI 只做存活率监控与报告，不回写分数**——CI 运行在 GitHub 数据中心网络，与国内用户网络不同，评分仍以本地 `test_mirrors.sh` 实测为准

---

## 接入 MCP（让 AI 直接查库）

如果你的 AI 客户端支持 MCP，接上内置的零依赖 server，模型就能把「查当前最优源」当成一次工具调用：

```json
{
  "mcpServers": {
    "accel-mirror": {
      "command": "python3",
      "args": ["<REPO>/mcp_server/accel_mirror_mcp.py"]
    }
  }
}
```

提供三个工具：`best_mirror`（给**服务名或场景**返回最优源 + 可执行命令，如 `service=pip` / `service=模型下载`）、
`list_mirrors`（库总览，或某个服务 / 分类的全部源）、`test_mirror`（**本机**实时探测某个源）。详见 [mcp_server/README.md](mcp_server/README.md)。

> 服务名解析、选源与命令生成只有一份实现（`server/accel_mirror_api.py`），MCP Server 直接复用它，
> 所以两条通道给出的是同一个答案。自检第 8 节会逐一比对全部 25 个服务名，漂移会让 CI 变红。

---

## 部署只读 HTTP 接口（让不装 MCP 的 AI 也能用）

MCP 是「插座」，HTTP 是「电网」。要让「所有 AI」都能查到最优源，还得有一层
零安装的接口——`server/` 就是它，纯标准库、无第三方依赖、只读、不发起任何出站请求。

```bash
# 本地起一个（默认 127.0.0.1:8787）
python3 server/accel_mirror_api.py

# 或者 Docker（含健康检查、非 root 运行）
docker compose -f server/docker-compose.yml up -d --build

# 查询：服务名 → 最优源 + 可直接执行的命令
curl -s "http://127.0.0.1:8787/v1/best?service=pip&format=text"
# # pip → 用 pip 清华镜像
#   pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>

curl -s "http://127.0.0.1:8787/v1/best?service=github&limit=3"   # 返回 JSON，含降级候选
curl -s "http://127.0.0.1:8787/v1/health"                        # 数据版本与新鲜度
curl -s "http://127.0.0.1:8787/v1/services"                      # 25 个可用服务名
```

支持的服务名（含中文口语别名）：

```
docker  docker-enterprise  github  ghcr  quay  gcr  k8s  nvcr
pip  pytorch  conda  huggingface  modelscope  openxlab  ai-models
npm  go  rust  maven  gradle  apt  homebrew  rubygems  composer  git-proxy
```

服务名到源的映射规则放在 [`references/recipes.json`](references/recipes.json)——**数据驱动**，
HTTP 接口与 MCP Server 共用同一份规则，不会两处逻辑漂移（MCP 直接 `import` `server/` 的实现，
并由自检第 8 节逐一比对）。想加一个服务（比如 `nuget`），改这一个 JSON 即可。

响应里刻意带 `caveats` 与 `dataset.age_days`：数据过期时会明说，
而不是让调用方盲信一个陈旧排名。详见 [server/README.md](server/README.md)。

---

## 众包上报：把「一台机器的分」变成「群体共识」

单人实测有个天然弱点——**别人无法验证，也就无法真正依赖**。

### 路线 A：提一个 issue（推荐，不需要 fork / PR / 懂 git）

跑一次测速，把结果贴进 **「网络实测上报」issue 表单**即可：

```bash
bash scripts/test_mirrors.sh --type all --output my_report.json --network-label "北京联通 500M"
```

`.github/workflows/report-ingest.yml` 会自动入库、按中位数聚合、重建看板，并在 issue 里回复结果。

> 🔒 **为什么上报改不了「源列表」**：入库脚本 `scripts/ingest_report.py` 是信任边界——
> 每一行都被压成 `{name, status, time_ms}`，`name` 必须已存在于 `references/mirrors.json`，
> 提交者写的 `url` **一律丢弃**。否则任何人都能用伪造的「5ms 高速镜像」拿下榜首，
> 把用户导向被篡改的安装包。这是本项目最认真对待的一条约束。

### 路线 B：本地手动合并（维护者）

```bash
# 打上你的网络标签（如 "北京联通 500M"，纯自填，用于区分地域差异）
bash scripts/test_mirrors.sh --type all --output my_report.json --network-label "北京联通 500M"
```

上报文件里**只含延迟与状态**，`meta.privacy` 字段明确声明不含 IP / 路径 / 用户名 / 设备信息，
可以直接贴到 GitHub Issue。维护者把多份上报**取中位数**合并：

```bash
python3 scripts/update_mirrors.py --aggregate reports/*.json --min-samples 3
```

规则（都写进了 `scripts/selftest.py` 的断言里）：

| 规则 | 原因 |
|---|---|
| 取**中位数**而非均值 | 一份来自糟糕网络的上报不该拖偏整个排名 |
| `--min-samples N` 低于 N 份上报的源**不重算** | 避免单个样本就把分数定死 |
| 只有「**零成功 且 失败 ≥3 次**」才弃用 | 有过成功记录的源可能只是抖动，不能误杀 |
| 有过失败的源记录 `failed_reports` | 「既能成功又偶尔失败」= 不稳定，这是有价值的信号 |
| 聚合后写 `crowd` 元数据块 | 记录样本数、网络标签，让数据可信度可追溯 |

---

## 自检（改数据/改规则后跑一遍）

```bash
python3 scripts/selftest.py                            # 129 项断言，无依赖
python3 server/accel_mirror_api.py --self-test         # 接口行为自检
```

它检查的是**语义**而不只是语法——这些都是真实踩过的坑：

- `docker pull https://x/y` 带了协议头（Docker 镜像引用不允许）
- `github` 服务把「网页工具」当成最优源返回（不可自动化）
- 配方引用了 `references/xxx-guide.md`，但文件不存在
- 众包聚合把只有 1 份上报的源也算进了中位数
- **issue 上报试图引入库里不存在的源**（伪造「0ms 镜像」的供应链攻击路径）
- **issue 上报里的 `url` 字段漏进了产物**（字段最小化被破坏）
- 网络标签里混进了 IP / 家目录
- 产物用 CRLF 换行（跨平台哈希不一致）
- 自检过程是否意外改动了生产数据库（比对 SHA256）

CI 每次 push 都会跑这两个自检。

---

## AI 场景速查（模型 / Python / 容器仓库）

这三块是国内 AI 开发者最高频的痛点，也是 v1.4.0 新补的分类。

**HuggingFace 模型下载**（`ai_models`）——环境变量必须在 `import transformers` 之前设：

```bash
export HF_ENDPOINT=https://hf-mirror.com
pip install hf_transfer && export HF_HUB_ENABLE_HF_TRANSFER=1
```

```python
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"   # 必须写在 transformers 之前
from transformers import AutoModel
```

大权重、热门模型建议直接走国内原生源（**ModelScope 魔搭** / **OpenXLab 浦源**），不经代理：

```bash
pip install modelscope && modelscope download --model <org>/<name>
```

**pip / conda / PyTorch**（`python`）：

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip install torch --index-url https://mirrors.aliyun.com/pytorch-wheels/cu121
```

**非 DockerHub 容器仓库**（`dev_registry`）——把镜像名前缀换掉：

```bash
docker pull ghcr.m.daocloud.io/<owner>/<image>:<tag>      # 替代 ghcr.io
docker pull k8s.m.daocloud.io/<image>:<tag>               # 替代 registry.k8s.io
docker pull nvcr.m.daocloud.io/<org>/<image>:<tag>        # 替代 nvcr.io（NVIDIA NGC）
```

更多内容见 [SKILL.md](SKILL.md) 的 Phase 3e。

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

# 指定引擎（auto 默认：aria2 多线程 → curl → axel 自动回退）
bash scripts/accel-fetch.sh https://github.com/user/repo/archive/refs/heads/main.zip --engine aria2

# 下载后校验 SHA256（哈希不匹配自动清理文件并视为失败）
bash scripts/accel-fetch.sh https://github.com/.../app.zip --sha256 675782187ea46d3cbd6faf6c0ca7f9b47f1dd04545e22fa9106457efbef22803
```

### 下载器自检与安装（首次使用前）

`accel-fetch.sh` 依赖 `aria2`（多线程主力）、`curl`（单线程兜底）、`axel`（备用多线程）三件套。首次使用前先跑自检：

```bash
bash scripts/accel-fetch.sh --doctor
```

缺失时按平台安装：

| 平台 | 安装命令 |
|---|---|
| Debian / Ubuntu（含 proot 环境） | `sudo apt-get update && sudo apt-get install -y aria2 curl axel` |
| CentOS / RHEL / Fedora | `sudo yum install -y aria2 curl axel`（或 `dnf`） |
| Alpine | `apk add aria2 curl axel` |
| macOS | `brew install aria2 curl axel` |
| Termux | `pkg install aria2 curl axel` |
| Windows | 脚本需在 **Git Bash 或 WSL** 内运行；下载器可 `winget install aria2.aria2` + 系统自带 curl |

装完再跑一次 `bash scripts/accel-fetch.sh --doctor` 确认 3/3 全绿，即可正常下载。

> ⚠️ **安全提示**：prefix 型代理本质是第三方中间人。下载**可执行文件 / 安装包**时务必使用 `--sha256` 校验（或验证发布方签名）后再运行。

> 💡 **如何工作**：脚本优先用 aria2 16×16 多线程加速（经代理容易 Range 不完整，故每轮都做大小校验，失败自动换 curl/axel/下一候选源）；还会对多个可达源探测到的文件大小做**多数投票**，识破返回错误页的"假快"坏源。

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

## 镜像库现状（数据库 v1.7.0 · 121 源 · 7 分类）

| 分类 | 数量 | 活跃 | 最优源（实测） |
|---|---|---|---|
| `docker_community` | 36 | 36 | docker.m.daocloud.io（85 分，480ms） |
| `docker_enterprise` | 3 | 3 | 阿里云 ACR（90 分） |
| `github` | 45 | 45 | toolwa.com/github（86 分，386ms） |
| `tools` | 17 | 17 | Maven 腾讯（98 分） |
| `ai_models` | 6 | 6 | OpenXLab 浦源·上海AI Lab（94 分，102ms） |
| `python` | 7 | 7 | PyTorch wheels 上海交大（89 分，245ms） |
| `dev_registry` | 7 | 7 | ghcr 南京大学（94 分，101ms） |

**AI 开发者最常用的三类源（2026-09-21 国内网络实测，对数刻度）：**

```
AI 模型仓库          94 │ OpenXLab 浦源 (上海AI Lab)   102ms
                    91 │ ModelScope 魔搭              167ms
                    91 │ WiseModel 始智AI             187ms
                    87 │ BAAI 智源 (FlagOpen)         325ms
                    83 │ hf-mirror (HuggingFace 国内)  876ms

Python 包管理        89 │ PyTorch wheels (上海交大)     245ms
                    79 │ conda (清华)                 1026ms
                    72 │ PyTorch wheels (阿里)        2466ms

容器仓库镜像         94 │ ghcr (南京大学)               101ms
                    93 │ k8s (阿里云 google_containers) 130ms
                    92 │ quay / nvcr / ghcr (DaoCloud) 146~154ms
```

> 💡 读法：**AI 模型下载优先选国内原生源**（OpenXLab / ModelScope），它们没有代理中间层；
> hf-mirror 是 HF 的反代，作兜底。PyPI 索引页本身很大，首字节延迟高不代表装包慢。

**GitHub 加速源 Top 5：**

```
 86 │ toolwa.com/github        386ms
 83 │ gh.h233.eu.org           590ms
 83 │ gitclone.com             628ms
 83 │ github.akams.cn          642ms
 80 │ gh-proxy.com             901ms
```

> ⚠️ 镜像源存活率变化极快。以上排名仅为发布时刻快照，**请以最新实测为准**——这正是本项目存在的意义。
> 在线看板：`docs/index.html`（GitHub Pages），或本地 `python3 scripts/build_dashboard.py` 重新生成。

---

## 文件结构

```
accel-mirror/
├── SKILL.md                      # 技能主文件：AI 工作流 + 自我进化协议
├── AGENTS.md                     # 跨工具代理入口（Cursor / Codex / Claude Code 都认）
├── CLAUDE.md                     # Claude Code 的精简入口
├── llms.txt                      # 面向 AI 代理的机器可读入口索引
├── CONTRIBUTING.md               # 贡献指南（三条路径 + 会被拒的贡献）
├── CHANGELOG.md                  # 变更日志（1.2.0 → 1.7.0）
├── SECURITY.md                   # 安全策略与威胁模型（推荐被污染是最大风险）
├── references/
│   ├── mirrors.json              # 镜像数据库（版本化 + evolution_log + crowd 元数据）
│   ├── recipes.json              # 服务名 → 源 + 命令模板（HTTP API 与 MCP 共用）
│   ├── docker-mirrors-guide.md   # Docker 镜像使用指南
│   ├── github-mirrors-guide.md   # GitHub 加速使用指南
│   ├── ai-models-guide.md        # HuggingFace / ModelScope / 数据集下载指南
│   └── package-managers-guide.md # npm/pip/apt/Homebrew/Rust 等换源指南
├── scripts/
│   ├── test_mirrors.sh           # 并发测速（--deep 测吞吐、--network-label 众包上报）
│   ├── update_mirrors.py         # 评分 / 排序 / 弃用 / 进化日志 / --aggregate 众包聚合
│   ├── accel-fetch.sh            # GitHub 文件自动加速下载（智能选源 + 回退 + 校验）
│   ├── build_dashboard.py        # 由 mirrors.json 生成 docs/index.html 看板
│   ├── ingest_report.py          # issue 上报 → 规范上报文件（信任边界：白名单 + 字段最小化）
│   └── selftest.py               # 无依赖自检（129 项）：数据 / 配方 / API / 聚合 / 入库 / 分发 / 文档
├── server/                       # 只读 HTTP 接口（零依赖）
│   ├── accel_mirror_api.py       # GET /v1/best · /v1/list · /v1/services · /v1/health
│   ├── Dockerfile                # 非 root + 健康检查，无需 pip install
│   ├── docker-compose.yml        # 一条命令起服务
│   └── README.md                 # 部署、反向代理、systemd、安全说明
├── mcp_server/
│   ├── accel_mirror_mcp.py       # MCP Server（零依赖），供任意 AI 客户端接入
│   └── README.md                 # 各客户端接入配置
├── reports/
│   └── README.md                 # 众包上报存档（<issue 号>.json）+ 安全模型说明
├── .cursor/rules/
│   └── accel-mirror.mdc          # Cursor 规则
├── docs/
│   └── index.html                # 数据看板（GitHub Pages）
└── .github/
    ├── ISSUE_TEMPLATE/
    │   └── network-report.yml    # 「网络实测上报」issue 表单（零门槛贡献入口）
    └── workflows/
        ├── mirror-test.yml       # 每周自动全量测速 CI（存活率监控 + 自检）
        ├── report-ingest.yml     # issue 上报自动入库 + 聚合 + 重建看板 + 回复提交者
        └── pages.yml             # 把 docs/ 数据看板发布到 GitHub Pages
```

---

## 贡献

三条路径按门槛从低到高，详见 **[CONTRIBUTING.md](CONTRIBUTING.md)**：

| 想做的事 | 前置条件 | 怎么做 |
|---|---|---|
| **上报一次实测**<br>（最有价值：把单机分数变成群体共识） | **不需要 git** | 跑 `test_mirrors.sh --network-label "北京联通 500M"`，把 JSON 贴进「网络实测上报」issue，机器人自动入库并回复 |
| 新增 / 修订镜像源 | 需要 git 基础 | `update_mirrors.py --add …`，然后**实测一次**别手填分数，在 notes 里写明实测时间 |
| 改进脚本与文档 | 需要读代码 | 改完跑 `selftest.py`；新增一类 bug 就顺手补一条断言 |

**会被拒的贡献**：未经实测的源 · 试图新增源的上报 · 推荐未知第三方模型代理站 · 广告式 notes · 为「清理」删源。

```bash
# 添加一个源（记得随后实测一次回写分数）
python3 scripts/update_mirrors.py --add \
  --name "my-new-mirror" --url "https://example.com/" \
  --category github --test-url "https://example.com/https://github.com/" \
  --notes "实测 2026-09-21 北京联通 312ms"
```

安全模型与漏洞报告见 **[SECURITY.md](SECURITY.md)**；完整变更历史见 **[CHANGELOG.md](CHANGELOG.md)**。

---

## 致谢

- **Operit AI** —— 本项目诞生于 Operit 平台技能生态，感谢平台对 skill 开发的支持
- **jishuzhan.net** —— 早期 Docker 镜像社区测速数据的参考来源
- 所有维护社区加速镜像的开发者（来源见 `mirrors.json` 各条目 notes）

## LICENSE

[MIT](LICENSE) © 2026 gitfox-enter