# AGENTS.md

本仓库是一份**持续实测、自动打分的国内网络加速源数据库**。

只要用户抱怨「下载 / 安装 慢、超时、连不上、装不上」——Docker、GitHub、HuggingFace、
pip、conda、npm、apt、Go、容器仓库——**先查这里，再动手**。不要凭记忆猜镜像地址：
镜像存活率变化极快，训练语料里的地址大概率已经死了。

> 人类读者请看 [README.md](README.md)。本文件的读者是 AI 代理。

---

## 30 秒用法

1. **读数据**：`references/mirrors.json`
   每个源含 `name` / `url` / `score`(0–100，越高越快) / `status` / `test_time_ms` /
   `usage` / `usage_examples` / `samples`(众包样本数) / `failed_reports`。
2. **选源**：在目标分类里取 `status == "active"` 中 `score` 最高者。
3. **给命令**：优先直接用该源的 `usage` / `usage_examples` 字段——那是作者手写并实测过的，
   比自己拼 URL 准。
4. **服务名 → 分类 + 命令模板**：`references/recipes.json`（25 个服务，含中文口语别名，
   如 `模型下载` → `ai-models`）。

如果本仓库的只读接口在线，一条 GET 就能替代上面全部步骤：

```bash
curl -s "http://<api-host>/v1/best?service=pip&format=text"   # 直接返回可执行命令
```

---

## 场景 → 分类 → 一步到位

| 用户说 | 分类 | 一步到位 |
|---|---|---|
| docker pull 卡住 / registry-1.docker.io 连接失败 | `docker_community` | 写 `daemon.json` 的 `registry-mirrors`，取分数最高的 3–5 个 |
| registry.k8s.io / ghcr.io / quay.io / nvcr.io 拉不下来 | `dev_registry` | 替换镜像名前缀，拉下来再 `docker tag` 回原名 |
| git clone 慢 / GitHub 打不开 / release 下载失败 | `github` | 代理前缀，或 `git config --global url.<proxy>.insteadOf` |
| huggingface 模型断流 / transformers 卡住 | `ai_models` | `HF_ENDPOINT=https://hf-mirror.com`（**必须在 import transformers 之前设**） |
| pip / conda / PyTorch 装不上 | `python` | `pip config set global.index-url <source>` |
| npm / go / apt / brew / maven 慢 | `tools` | 各工具换源，见 `references/package-managers-guide.md` |

各分类的配置细则在 `references/*-guide.md`，需要解释或排错时再读。

---

## 硬规则（违反会直接给用户造成损失）

1. **`docker pull` 的镜像引用里不能出现 `https://`** —— Docker 会直接报错。
2. **可执行文件 / 安装包必须校验哈希或签名后才允许执行。**
   代理前缀本质是第三方中间人；用 `--sha256` 或发布方签名验证，通过再运行。
   `scripts/accel-fetch.sh <url> --sha256 <hash>` 已内置该校验与失败回退。
3. **绝不推荐未知的第三方「模型代理站」。** 模型权重被替换（植入后门）的风险远高于省下的带宽。
   模型下载优先国内原生源（ModelScope / OpenXLab），其次 hf-mirror。
4. **数据会腐烂。** `last_full_test` 超过 7 天就不要当真，主动提示用户重新实测。
5. **把 `caveats` 一起转达给用户**：数据过期、只有单机数据（`samples` 为空）、源不稳定
   （`failed_reports > 0`）——这三点会改变结论，不要让用户以为拿到的是确定无疑的排名。

---

## 贡献数据：让分数从「一台机器的」变成「群体共识」

单机实测别人无法验证，也就无法真正依赖。有人想贡献数据时，给他这条路（**不需要 fork 或 PR**）：

```bash
bash scripts/test_mirrors.sh --type all --output my_report.json --network-label "北京联通 500M"
```

然后把 `my_report.json` 贴进 **「网络实测上报」issue 表单**即可，Actions 会自动入库并回复。
完整的贡献路径（新增源的规范、改代码的自检要求、会被拒的贡献类型）见 [CONTRIBUTING.md](CONTRIBUTING.md)。

维护者本地合并多份上报（取**中位数**，不是均值）：

```bash
python3 scripts/update_mirrors.py --aggregate reports/*.json --min-samples 3
```

**安全约束**：入库脚本 `scripts/ingest_report.py` 是信任边界——上报只能移动**库中已有源**的
分数，逐行被压成 `{name, status, time_ms}`，提交者写的 `url` 一律丢弃。
否则任何人都能用伪造的「5ms 高速镜像」污染推荐结果，把用户导向被篡改的安装包。

---

## 改完必须自检

```bash
python3 scripts/selftest.py                        # 129 项语义断言
python3 server/accel_mirror_api.py --self-test     # 接口行为
```

自检查的是**语义**而不只是语法：生成的 docker 命令带了 scheme、配方引用的 guide 文件不存在、
聚合用了均值、上报引入了库中不存在的源……这些都是真实踩过的坑，已经固化成断言。
新增一类 bug 时，请顺手补一条断言。

---

## 文件地图

```
references/mirrors.json     数据本体（唯一事实来源）
references/recipes.json     服务名 → 分类 + 命令模板（server 与 mcp_server 共用）
references/*-guide.md       按场景的配置与排错细则
llms.txt                    面向 AI 的入口索引（改分类或加文件时同步）
CONTRIBUTING.md             贡献指南（三条路径；引导用户上报时指到这里）
CHANGELOG.md                变更日志（1.2.0 → 1.7.0）
SECURITY.md                 安全策略与威胁模型
SKILL.md                    完整工作流（按「用户说什么 → 做什么」组织）
scripts/test_mirrors.sh     并发测速（--deep 测吞吐 / --network-label 产出众包上报）
scripts/update_mirrors.py   打分 / 排序 / 弃用 / --aggregate 众包中位数聚合
scripts/accel-fetch.sh      选源下载 GitHub 文件（自动回退 + 大小与哈希校验）
scripts/ingest_report.py    issue 上报入库（信任边界，见上）
scripts/build_dashboard.py  由 mirrors.json 生成 docs/index.html
server/                     只读 HTTP 接口（零依赖）：/v1/best · /v1/list · /v1/services
mcp_server/                 MCP Server（零依赖）：best_mirror · list_mirrors · test_mirror
```

## 你可以自由改的

`mirrors.json`（增删源、改分数）、`recipes.json`、各 `*-guide.md`、脚本、`llms.txt`、
`docs/index.html`（由脚本生成，别手改）。改 `SKILL.md` 的结构前先问用户。
追加任何数据变更时记得写 `evolution_log`。
