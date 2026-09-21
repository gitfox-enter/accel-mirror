# 变更日志

本文件记录对用户有影响的变化。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 `主版本.次版本.修订号`。

> **数据版本与项目版本同步**。`references/mirrors.json` 的 `version` 字段即当前版本号。
> 每次数据或能力变更都会在 `mirrors.json` 的 `evolution_log` 里追加一条可追溯记录。

---

## [1.7.0] — 2026-09-21

主题：**贡献者入口与项目可信度**。上一版（1.6.0）把众包飞轮做通了，但没有门——陌生人到了仓库
不知道该怎么贡献；这一版补上门，并把「文档与实际不一致」这类漂移变成会失败的测试。

### 新增

- 📥 **`CONTRIBUTING.md`**：三条贡献路径按门槛排序——「提 issue 上报（不需要 git / fork / PR）」
  放在最前，因为它把「一台机器的排名」变成「群体共识」；其次是「加/改镜像源」（含字段说明表与
  `evolution_log` 要求），最后是「改脚本与文档」。同时明确列出**五类会被拒的贡献**
  （未经实测的源、试图新增源的上报、推荐未知第三方模型代理站、广告式 notes、为"清理"删源）
- 📜 **`CHANGELOG.md`**（本文件）：此前"更新记录"挤在 README 尾部，随篇幅增长已影响阅读；
  抽成独立文件并补齐 1.2.0 → 1.7.0 的完整脉络
- 🔐 **`SECURITY.md`**：这个项目不运营镜像、只做**推荐**，所以威胁不在代码执行而在**推荐被污染**。
  文件写明威胁模型与对应防线：issue 上报投毒（最严重）、推荐被篡改导致安装恶意软件、
  只读接口的 SSRF 风险（刻意不提供任意 URL 探测）、隐私、数据陈旧。含私密报告渠道与响应时限承诺

### 变更

- 🧪 **自检新增第 9 节「文档一致性」，并加入一个元检查**：断言「各文档里声明的断言数
  必须等于实际断言数」。以后加了断言却忘了改文档，CI 会直接变红——文档漂移从此是**会失败的测试**，
  而不是靠人记得。该元检查刻意不计入断言总数，否则等式永远差一
- 🔗 **自检新增第 8 节「MCP 与 HTTP 行为一致性」**：逐一遍历全部 25 个服务名，
  要求两条通道给出**同一个源、同一条命令**，并覆盖中文别名解析、未知服务的提示质量、
  以及「docker 命令不能带 scheme」这条硬规则在两条通道上都成立
- 🧹 **清除 7 个文件里的 12 处文档漂移**（这是本项目第一次系统性清理，全部由新加的断言兜住）：
  - `README.md`：徽章版本 `1.6.0` → `1.7.0`；「覆盖 4 大分类、102 个镜像源」→「7 大分类、121 个
    镜像源」（v1.4.0 加了三类却忘了改这里）；两处「108 项断言」；「镜像库现状」标题里的版本号
  - `SKILL.md`（2 处）、`llms.txt`、`AGENTS.md`、`CLAUDE.md`、`.cursor/rules/accel-mirror.mdc`：
    断言数分别停留在 `108` / `65+` / `65+` / `65+`
  - `server/README.md`：示例响应里的 `dataset.version` 还写着 `1.5.0`
- 📄 **README 的「更新记录」改为指向本文件**，避免同一份历史在两个地方各维护一遍（这正是漂移的来源）
- 🔗 **README / AGENTS.md / llms.txt 增加贡献、变更、安全三个入口的链接**；文件结构树同步补充新文件

### 修复

- 🐛 **MCP Server 的 `best_mirror` 不认服务名，只认分类名**：`best_mirror(service="pip")`
  的参数被静默忽略、返回「未知分类 ''」；传 `category="pip"` 也不解析别名。而 README 与
  `SKILL.md` 都宣称「HTTP 接口与 MCP Server **共用同一份规则**，杜绝逻辑漂移」——
  **这句宣称当时是假的**：MCP 自己复制了一份更弱的实现（只做分类名匹配，且在 github 分类里
  不会像 HTTP 那样排除不可自动化的网页工具）。现在 MCP 直接 `import server/accel_mirror_api.py`，
  复用同一份解析、选源与命令生成；双出口不可能再分叉，并由新增的第 8 节断言锁住
- 🐛 MCP 的 `serverInfo.version` 硬编码为 `1.4.0`（此时数据库已到 1.7.0）。改为从
  `mirrors.json` 读取——少一个会腐烂的常量
- 🐛 `list_mirrors` 只接受分类名。现在同样接受服务名（`list_mirrors(service="ghcr")` 会解析到
  `dev_registry` 并列出全部 7 个容器仓库镜像）

---

## [1.6.0] — 2026-09-21

主题：**分发与自动化**。上一版解决了「门槛」与「可信度」，这一版解决「让数据能被人拿到、
被人喂进来」——尤其是让**不需要懂 git 的人**也能贡献数据。

### 新增

- 📥 **零门槛贡献数据的完整链路**：「网络实测上报」issue 表单 + `scripts/ingest_report.py` +
  `.github/workflows/report-ingest.yml`。陌生人跑一条命令、把 JSON 贴进 issue，机器人自动入库、
  按中位数聚合、重建看板并在 issue 里回复结果——**不需要 fork，不需要 PR，不需要懂 git**
- 🔒 **入库脚本是信任边界（抗投毒）**：上报逐行被压成 `{name, status, time_ms}`，
  `name` 必须已存在于 `mirrors.json`，提交者写的 `url` **一律丢弃**。否则任何人都能用伪造的
  「5ms 镜像」拿下榜首，把用户导向被篡改的安装包——这是**由 issue 表单实现的供应链攻击路径**，
  必须从设计上堵死。产物文件的隐私性因此是**构造性保证**，而非正则扫描
- 🤖 **新增代理入口文件** `AGENTS.md` / `CLAUDE.md` / `.cursor/rules/accel-mirror.mdc`：
  任何编码代理打开仓库即被路由到数据库与硬规则（docker 命令不能带 scheme、可执行文件必须
  校验哈希、不推荐未知模型代理站）
- 🌐 **新增 `.github/workflows/pages.yml`**：把 `docs/index.html` 发布到 GitHub Pages，
  页面永远由 `mirrors.json` 现场重建，并**先过自检才允许上线**——脏数据不会出现在线上
- 📁 **新增 `reports/README.md`**：众包上报存档说明与安全模型
- 🧪 **自检从 65 项扩到 108 项**：新增抗投毒、字段最小化、标签清洗、拒收路径退出码、产物换行符、
  以及「AGENTS.md 引用的文件真实存在」的**文档防漂移**断言

### 修复

- 🐛 issue 表单里那个独立的「网络标签」输入框原本被**完全忽略**（脚本只读 JSON 里的
  `meta.network_label`），现已补上回退路径，且两条路都要过白名单清洗
- 🐛 自检第 4 节曾假设「某个源还没有 `samples`」而依赖数据库历史状态——一旦真实聚合过一次
  上报，CI 就会红。已改为**先清空库里的众包字段再断言**，结论不依赖历史

---

## [1.5.0] — 2026-09-21

主题：**门槛与可信度**。上一版解决了「形态」，这一版让**不装 MCP 的 AI 也能用**，
并回答「凭什么相信你的分数」。

### 新增

- 🌐 **只读 HTTP 接口**（`server/`，零依赖纯标准库）：`GET /v1/best?service=pip` 直接返回
  **可执行命令**而非 URL；含 `/v1/list`、`/v1/services`、`/v1/health`、`/v1/dataset`。
  附 Dockerfile（非 root + 健康检查）、compose、Nginx/Caddy/systemd 部署示例
- 🗺️ **`references/recipes.json` 服务名映射**：25 个服务名（含中文口语别名，如 `模型下载`、
  `镜像加速`）→ 分类 + 过滤 + 命令模板。HTTP 接口与 MCP Server **共用同一份规则**，
  杜绝两处逻辑漂移；加一个服务只需改这一个 JSON
- 👥 **众包上报与中位数聚合**：`test_mirrors.sh --network-label "北京联通"` 产出匿名上报
  （无 IP / 路径 / 用户名 / 设备信息，`meta.privacy` 明示）；
  `update_mirrors.py --aggregate reports/*.json --min-samples 3` 取**中位数**合并。
  规则：低于 min-samples 不重算；只有「零成功且失败 ≥3 次」才弃用；有过失败记录
  `failed_reports` 保留为不稳定信号
- 🧠 **`references/ai-models-guide.md`**：HuggingFace 换源、断流续传、ModelScope / OpenXLab /
  OpenI / BAAI 原生源选择策略，以及「不要用未知第三方模型代理（有被替换文件的风险）」的硬建议
- 🧪 **无依赖自检 `scripts/selftest.py`**（65 项断言）+ `server/accel_mirror_api.py --self-test`，
  并接入 CI。查的是**语义**：docker 命令不能带 scheme、github 不能返回不可自动化的网页工具、
  配方引用的 guide 文件必须存在、聚合必须取中位数、自检不得改动生产库

### 变更

- 📈 **答案带风险提示**：接口响应里含 `dataset.age_days`、`samples`、`latency_spread_ms`、
  `failed_reports` 与 `caveats`——数据超过 7 天未实测、只有单机数据、或最优源不稳定时都会明说，
  而不是让 AI 盲信一个过期排名

### 修复

- 🐛 `urlparse()` 漏取 `.path` 导致 HTTP 层全部返回 500
- 🐛 `set -e` 下 `[[ ]] && echo` 在条件为假时会直接终止脚本
- 🐛 聚合时「有成功也有失败」的源会丢失失败次数记录

### 安全

- 🔒 HTTP 接口**不提供任意 URL 探测**（那等于公网 SSRF 跳板）；存活数据只来自 CI 与本地实测；
  容器以非 root 运行且可 `read_only`

---

## [1.4.0] — 2026-09-21

主题：**从「一个技能文件」扩成「可被任意 AI 消费的基础设施」**。

### 新增

- 🗂️ **三个 AI 痛点分类**（共 19 个源，镜像源总数 102 → **121**）：
  - `ai_models`：hf-mirror / ModelScope 魔搭 / WiseModel / OpenI 启智 / OpenXLab 浦源 / BAAI 智源
  - `python`：pip 清华·阿里·腾讯·中科大、conda 清华、PyTorch wheels 阿里·上海交大
  - `dev_registry`：ghcr / quay / gcr / k8s / nvcr 的 DaoCloud 与南大镜像、阿里云 google_containers
- 🔌 **MCP Server**（`mcp_server/`，零依赖）：暴露 `best_mirror` / `list_mirrors` / `test_mirror`，
  任何 MCP 客户端都能把「查当前最优源」变成一次工具调用——不再依赖特定客户端的 skill 机制
- 🤖 **`llms.txt`** 与 README 的 `For AI agents` 区块：给检索 / 训练语料一个明确的机器可读入口
- 📊 **数据看板**（`docs/index.html`）：由 `scripts/build_dashboard.py` 从数据库生成，
  数据内联成单文件，可视化全部分类的分数与存活率

### 变更

- ✍️ **触发词重写为场景句**：SKILL.md 的 description 从关键词堆砌改为「用户说什么 → 该做什么」
  的自然语言场景，提高被 AI 正确调用的概率

### 修复

- 🐛 **新分类首轮实测校正**：ModelScope API 路径 404 → 改站点首页；OpenI 原域名不可达 →
  改 `openi.pcl.ac.cn`；清华 pytorch-wheels 已 404 → 替换为阿里源 + 上海交大备用；
  移除对 curl 默认 UA 恒返 429 的华为云 PyPI

---

## [1.3.0] — 2026-09-21

### 变更

- 📈 **评分公式改用对数刻度**：`score = max(0, round(100 - 20×log10(1 + t_s / 0.1)))`，
  解决旧线性公式下头部镜像扎堆 99 分、区分度不足的问题；存量分数已通过 `--rescore`
  从实测延迟重算
- 🥈 **同分二次排序**：分数相同按实测延迟升序排列，Top 榜反映真实快慢
- 🚇 **`--deep` 深度吞吐实测**：经每个 github prefix 代理真实拉取 1MB 测带宽，
  弥补「只测 RTT 不测带宽」的盲区，结果写入 `throughput_bps`
- 🛰️ **CI 存活快照**：定期运行把响应成功的源标记 `last_ci_alive` 并自动提交，
  **分数仍然绝不回写**
- 🔒 **哈希校验升级为硬规则**：可执行文件 / 安装包必须 SHA256 或签名校验通过才允许执行

### 修复

- 🔧 测速输出改用 TAB 分隔（源名含 `|` 不再破坏解析）
- 🔧 Python 调用改为 argv 传参（消除路径插值注入风险）
- 🔧 `SKILL.md` 的 Phase 编号排序修正；包管理器换源命令下沉至
  `references/package-managers-guide.md`
- 🐧 明确脚本需在 Git Bash / WSL 运行，平台安装表补 Windows 条目

---

## [1.2.0] — 2026-09-12

### 新增

- 新增 `scripts/accel-fetch.sh` 智能选源下载（代理探测 + 多引擎回退 + 大小多数投票校验）
- 新增每周 CI 测速工作流

### 变更

- `tools` 分类扩至 19 项

---

[1.7.0]: https://github.com/gitfox-enter/accel-mirror/releases/tag/v1.7.0
[1.6.0]: https://github.com/gitfox-enter/accel-mirror/releases/tag/v1.6.0
[1.5.0]: https://github.com/gitfox-enter/accel-mirror/releases/tag/v1.5.0
[1.4.0]: https://github.com/gitfox-enter/accel-mirror/releases/tag/v1.4.0
[1.3.0]: https://github.com/gitfox-enter/accel-mirror/releases/tag/v1.3.0
[1.2.0]: https://github.com/gitfox-enter/accel-mirror/releases/tag/v1.2.0
