# 参与贡献

感谢你愿意花时间。这个库的价值**全部来自「别人验证过的数据」**——单人实测别人无法复核，
也就无法真正依赖。所以这里把「让陌生人贡献数据」当成第一优先级来设计。

---

## 三条路径，按门槛从低到高

### 路径 1 · 上报一次实测（约 5 分钟，**不需要 git / fork / PR**）

这是最有价值的贡献，因为它把「一台机器的排名」变成「一群人的共识」。

```bash
# 1) 在你自己的网络环境里跑一次全量实测（约 1–3 分钟）
bash scripts/test_mirrors.sh --type all --output my_report.json --network-label "北京联通 500M"

# 2) 打开「网络实测上报」issue 表单，把 my_report.json 的内容贴进去
```

然后就可以关掉页面了。`.github/workflows/report-ingest.yml` 会自动：

1. 校验并入库（`scripts/ingest_report.py`）
2. 按**中位数**聚合全部上报（`--min-samples 3`）
3. 重建数据看板
4. 在你的 issue 里回复一份入库报告（接受 / 丢弃了多少条、当前累计份数）

**关于 `--network-label`**：完全自填，用于区分地域与运营商差异（如 `北京联通 500M`）。
不要写 IP、主机名、用户名、真实姓名或任何能定位到你的信息——脚本会主动丢弃含这类内容的标签，
但少写一句比靠过滤更省事。

**为什么只有 1 份上报时分数没变？** 这是**有意为之**：单个样本不该把分数定死。
累计满 3 份（`--min-samples 3`）后才会按中位数重算。

**上报文件里有什么？** 只有每个源的延迟与成功/失败状态。`meta.privacy` 字段里写明了边界：

```json
"privacy": "no IP / no filesystem paths / no usernames / no device info are collected"
```

上报文件不含 IP、不含路径、不含用户名、不含设备信息。你可以自己打开 JSON 核对——这是构造性的
保证（脚本只往文件里写这两个字段），不是靠正则扫描事后过滤。

---

### 路径 2 · 新增或修订一个镜像源（需要一点 git）

**硬性要求：提交的源必须是你刚刚实测过的。** 我们只接受「真实网络下测到的延迟」，
不接受从别的文章里抄来的地址、也不接受凭印象填的分数。镜像存活率变化极快，
一篇三个月前的博文里的地址大概率已经死了——这正是本库存在的理由。

用脚本添加（会同时写好 `test_url` 与备注）：

```bash
python3 scripts/update_mirrors.py \
  --add \
  --name "my-new-mirror" \
  --url "https://example.com/" \
  --category github \
  --test-url "https://example.com/https://github.com/" \
  --notes "实测 2026-09-21 北京联通 312ms"
```

然后**务必**实测一次，让分数来自真实延迟而不是手填：

```bash
bash scripts/test_mirrors.sh --type github --output /tmp/gh.json
python3 scripts/update_mirrors.py --input /tmp/gh.json
```

**字段说明**（`references/mirrors.json` 里的每条源）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 唯一标识，分类内不可重名 |
| `url` | ✅ | 源地址。注意：**Docker 类源的 `usage` 里不能带 `https://`** |
| `test_url` | ✅ | 测速时实际请求的 URL（通常是 `url` + 一个真实路径，否则会把首页延迟当性能） |
| `score` | ✅ | 0–100，由脚本按延迟算出，**不要手填** |
| `status` | ✅ | `active` / `deprecated` |
| `usage` / `usage_examples` | 建议 | 手写并实测过的可直接执行命令，优先级高于程序拼的模板 |
| `notes` | 建议 | 一句话说明 + 实测时间，便于追溯 |

**废弃一个源**：不要直接删。连续 3 次实测失败后脚本会自动标 `deprecated`；
若是地址整体变化（如域名迁移），改 `url` 并在 `notes` 里写明原因。

**改动数据后必须追加 `evolution_log`**，否则追溯链就断了：

```json
{ "date": "2026-09-21", "action": "added", "details": "新增 x 个源（分类 / 原因）" }
```

---

### 路径 3 · 改进脚本与文档

本仓库**零第三方依赖**，在 POSIX shell 环境里跑自检不需要 `pip install` 任何东西
（Windows 请在 Git Bash 或 WSL 内运行脚本）。

```bash
python3 scripts/selftest.py                        # 语义自检，必须全绿
python3 server/accel_mirror_api.py --self-test     # 只读接口行为
bash -n scripts/test_mirrors.sh                    # shell 语法
```

**改脚本前请先读 `scripts/selftest.py`**——它检查的是**语义**而不只是语法，
每一条断言都对应一个真实踩过的坑（docker 命令带了 scheme、聚合用了均值而不是中位数、
上报引入了库里不存在的源……）。**新增一类 bug 时，请顺手补一条断言**——
这个库靠这条纪律活着。

---

## 我们认真对待的约束（这类 PR 会被拒）

1. **不接受未经实测的源**。没有真实延迟数据的源只会污染排名。
2. **上报永远不能新增源**。入库脚本 `scripts/ingest_report.py` 是信任边界：每行被压成
   `{name, status, time_ms}`，`name` 必须已存在于 `mirrors.json`，提交者写的 `url` 一律丢弃。
   否则任何人都能用伪造的「5ms 镜像」拿下榜首，把用户导向被篡改的安装包——这是本库最严重
   的供应链攻击面，从设计上堵死。详见 [SECURITY.md](SECURITY.md)。
3. **不接受推荐未知的第三方「模型代理站」**。模型权重被替换（植入后门）的风险远高于省下的带宽。
   模型下载优先国内原生源（ModelScope / OpenXLab），其次 hf-mirror。
4. **不接受广告式 `notes`**（带推广链接、邀请码、"全网最快"这类无实测支撑的表述）。
5. **不接受删源来"清理"**。死链请交给评分机制处理，保留它的历史。

## 隐私契约

- 上报文件只含延迟与状态，不含 IP / 路径 / 用户名 / 设备信息。
- 网络标签里混入 IPv4、Windows 盘符路径、POSIX 家目录时会被**整条丢弃**（有断言覆盖）。
- 本仓库不含任何个人部署信息、token 或私有路径。**提交 PR 前请自查一遍**——
   尤其别把本地 `~/.kube/config`、代理凭据、内网地址贴进 issue 或 notes。

## PR 检查清单

- [ ] `python3 scripts/selftest.py` 全绿
- [ ] 改了数据 → 追加了 `evolution_log`
- [ ] 改了版本号 / 源数量 / 断言数 → **四份文档同步**（`README.md`、`SKILL.md`、
      `AGENTS.md`、`llms.txt`，以及 `CLAUDE.md` 与 `.cursor/rules/`）。自检会校验
      「文档里声明的断言数 == 实际断言数」，漏改会直接让 CI 变红
- [ ] 新增源 → 填了 `test_url`，且自己实测过、在 `notes` 里写了实测时间
- [ ] 改了 `SKILL.md` 的结构 → 先开 issue 讨论
- [ ] 没在提交内容里留下任何个人信息

## 提交信息风格

尽量写清**改了什么、为什么**：

```
feat(data): 新增 ghcr 南京大学镜像（实测 101ms）
fix(score): 聚合时保留失败次数，避免误杀抖动源
docs: 同步断言数至 110 → 120
ci: issue 入库后自动回复提交者
```

## 有问题？

- 不确定某个源该归到哪个分类 → 开 issue 问，或看 `references/recipes.json` 的分类定义
- 想加一个**新的场景**（比如 `nuget`、`cargo` 的镜像）→ 只改
  `references/recipes.json` 一个文件即可，`server/` 与 `mcp_server/` 共用同一份规则

再次感谢——**你上报的每一条延迟，都会让下一个人的下载快一点。**
