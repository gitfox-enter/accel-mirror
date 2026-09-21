# accel-mirror MCP Server

把 accel-mirror 的镜像数据库接成一个 MCP 工具，任何支持 MCP 的 AI 客户端
（Claude Desktop、Trae、Cherry Studio、Cline、CodeBuddy 等）都能直接调用，
不必读文件、不必猜 URL。

**零依赖**：只用 Python 标准库，Python 3.9+ 即可，不需要 `pip install`。

## 工具

| 工具 | 参数 | 作用 |
|---|---|---|
| `best_mirror` | `service`（必填）、`limit`、`include_deprecated`、`types` | 给一个服务名或场景，返回当前最优的 N 个源（含实测延迟和可直接执行的命令） |
| `list_mirrors` | `service` / `category`（可留空）、`include_deprecated` | 留空返回各分类总览；传服务名或分类返回该类全部源 |
| `test_mirror` | `url`（必填）、`timeout` | 实时探测某个 URL 的可用性与延迟 |

**`service` 接受三种写法**，都大小写不敏感：

- 服务名：`pip` `conda` `pytorch` `huggingface` `modelscope` `docker` `github` `ghcr` `npm` `go` `apt` `maven` …
- **中文口语别名**：`模型下载` `拉镜像` `装python包` `镜像加速` …
- 分类名：`ai_models` `python` `dev_registry` `docker_community` `github` `tools`

完整列表见 `references/recipes.json`（25 个服务）或 HTTP 接口的 `/v1/services`。

## 只有一份规则，两个出口

服务名解析、选源和命令生成全部在 **`server/accel_mirror_api.py`** 里实现，
本 MCP Server 直接 `import` 它——所以 HTTP 接口和 MCP 永远给同一个答案，
不可能各自演化出不同结果。

> 早先的版本在这里复制了一份更弱的实现（只认分类名），结果
> `best_mirror(service="pip")` 返回「未知分类」，而文档却宣称两者共用规则。
> `scripts/selftest.py` 第 8 节现在会逐一对齐全部服务名，漂移会直接让 CI 变红。

**唯一的刻意差异**：`test_mirror` 会从**本机**发起探测。只读 HTTP 接口不提供该能力，
因为「公网服务器探测任意 URL」等于 SSRF 跳板；在本机运行则不存在这个风险。

## 接入配置

把 `<REPO>` 替换成本仓库的绝对路径。

### Claude Desktop / Claude Code

`claude_desktop_config.json`（或 `~/.claude.json`）：

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

### 通用 mcp.json（Trae / Cursor / Cline / Cherry Studio 等）

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

### Windows

`python3` 在原生 Windows 上通常不存在，改用完整路径或 `python`：

```json
{
  "mcpServers": {
    "accel-mirror": {
      "command": "python",
      "args": ["C:\\path\\to\\accel-mirror\\mcp_server\\accel_mirror_mcp.py"]
    }
  }
}
```

### 一行验证（不接客户端，直接手动跑）

```bash
cd <REPO>
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"best_mirror","arguments":{"service":"模型下载","limit":2}}}' \
  | python3 mcp_server/accel_mirror_mcp.py
```

应返回一段 JSON-RPC 响应，`result.content[0].text` 里是推荐结果。

## 说明

- 服务器只读 `references/mirrors.json` 与 `references/recipes.json`，不会修改任何文件。
- **零第三方依赖**，且 `serverInfo.version` 取自数据库版本，不硬编码（否则又是一个会腐烂的常量）。
- stdout 仅用于 JSON-RPC；诊断信息走 stderr，符合 MCP stdio 规范。
- 数据会腐烂：若 `last_full_test` 超过 7 天，建议先在仓库里跑一次
  `bash scripts/test_mirrors.sh --type all` 再让客户端查询。
- 返回文本尾部带 `caveats`（数据过期 / 只有单机样本 / 最优源不稳定），
  请把其中与你相关的部分转达给用户，不要让用户以为拿到的是确定无疑的排名。
