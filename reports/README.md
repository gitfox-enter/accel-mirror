# reports/ —— 众包实测上报

本目录存放各用户提交的**匿名实测结果**，由 `scripts/update_mirrors.py --aggregate`
取中位数合并进 `references/mirrors.json`。

## 怎么提交

**不需要 fork、不需要 PR、不需要懂 git。** 跑一条命令，把输出贴进 issue 表单即可：

```bash
bash scripts/test_mirrors.sh --type all --output my_report.json --network-label "北京联通 500M"
```

然后打开仓库的 **Issues → 新建 → 「网络实测上报」**，把 `my_report.json` 整段粘贴进去。
`.github/workflows/report-ingest.yml` 会自动入库并在 issue 里回复结果。

## 文件命名与格式

`reports/<issue 号>.json`，由 `scripts/ingest_report.py` 生成，结构：

```json
{
  "meta": {
    "schema": 1,
    "source": "github-issue",
    "issue": 12,
    "network_label": "北京联通 500M",
    "privacy": "by construction holds only mirror name + status + latency ...",
    "accepted_rows": 121
  },
  "results": {
    "github": [ { "name": "gh-proxy.com", "status": "ok", "time_ms": 901 } ]
  }
}
```

## 安全模型（这个目录的信任边界）

上报来自陌生人，所以入库脚本刻意做成了**白名单式**的：

1. 每行被压成 `{name, status, time_ms}` 三个字段——**提交者写的 `url` 一律丢弃**；
2. `name` 必须已存在于 `references/mirrors.json`，否则整行丢弃。

也就是说，**上报只能移动已知源的分数，永远不能新增源**。这不是洁癖：若允许新增 URL，
任何人都能上报一个「5ms 的镜像」，它实际返回被篡改的 `aria2c` / `pip` / 模型权重，却因为
排名第一而被推荐给本库的每个用户。那是一条由 issue 表单实现的供应链攻击路径。

因此产物文件的隐私性是**构造性保证**，而不是靠正则扫描「大概没有」：见 `scripts/selftest.py`
第 7 节的断言。

## 聚合规则

| 规则 | 原因 |
|---|---|
| 取**中位数**而非均值 | 一份来自糟糕网络的上报不该拖偏整个排名 |
| `--min-samples 3`：少于 3 份上报的源**不重算** | 避免单个样本就把分数定死 |
| 只有「**零成功 且 失败 ≥3 次**」才弃用 | 有过成功记录的源可能只是抖动，不能误杀 |
| 有过失败的源记录 `failed_reports` | 「既能成功又偶尔失败」= 不稳定，是有价值的信号 |

维护者手动聚合：

```bash
python3 scripts/update_mirrors.py --aggregate reports/*.json --min-samples 3
```
