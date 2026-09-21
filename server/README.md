# accel-mirror API（只读 HTTP 接口）

把 `references/mirrors.json` 变成一个**任何 AI agent 都能直接调用的接口**。

不需要装客户端、不需要装 MCP、不需要克隆仓库——一个 `GET` 就能拿到
「当前该用哪个源 + 该敲什么命令」。

```bash
curl -s "https://你的域名/v1/best?service=pip&format=text"
# # pip → 用 pip 清华镜像
#   pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>
```

## 为什么单独做一层 HTTP

| 消费方式 | 前置条件 | 谁用得上 |
|---|---|---|
| SKILL.md | 装了支持 skill 的客户端 | 少数客户端 |
| MCP Server | 装了支持 MCP 的客户端 | 主流 AI 客户端 |
| **HTTP 接口** | **能发 HTTP 请求** | **几乎任何 agent / 脚本 / 浏览器** |

MCP 是「插座」，HTTP 是「电网」。要做成基础设施，两种都要有。

## 设计原则

1. **只读**：不写数据库、不改文件，容器可以 `read_only: true` 跑。
2. **不做出站请求**：接口没有「帮我测一下任意 URL」这类能力——那等于给公网开了
   一个 SSRF 跳板。存活数据由 CI 与本地 `scripts/test_mirrors.sh` 产出后进库。
3. **答案优先**：返回体里的 `answer` / `commands` 是可直接执行的命令，
   而不是让调用方自己去拼 URL。
4. **零依赖**：纯 Python 标准库，`python:3.12-alpine` 直接跑，不需要 `pip install`。

## 接口

| 路径 | 说明 |
|---|---|
| `GET /` | 接口索引（带 `Accept: text/html` 时返回 HTML 页面） |
| `GET /v1/health` | 数据版本、新鲜度、各分类源数量 |
| `GET /v1/services` | 支持的服务名与别名（25 个） |
| `GET /v1/best?service=<名>` | **核心接口**：最优源 + 可执行命令 |
| `GET /v1/list?category=<分类>` | 按分类列出源 |
| `GET /v1/dataset` | 原始 `mirrors.json`（给要全量数据的 agent） |

### `/v1/best` 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `service` | `docker` | 服务名或别名，大小写不敏感；也可直接传分类名（如 `python`） |
| `limit` | `3` | 返回几个候选 |
| `include_deprecated` | `0` | 是否包含已弃用源 |
| `types` | 配方默认 | 只保留指定代理类型，逗号分隔：`prefix,domain,web` |
| `format` | `json` | 传 `text` 返回一行式纯文本（方便直接贴进终端） |

支持的 `service` 名（`GET /v1/services` 是权威来源）：

```
docker  docker-enterprise  github  ghcr  quay  gcr  k8s  nvcr
pip  pytorch  conda  huggingface  modelscope  openxlab  ai-models
npm  go  rust  maven  gradle  apt  homebrew  rubygems  composer  git-proxy
```

### 响应示例（截断）

```json
{
  "service": "pip",
  "answer": "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>",
  "best": {
    "rank": 1,
    "name": "pip 清华镜像",
    "url": "https://pypi.tuna.tsinghua.edu.cn",
    "score": 57,
    "latency_ms": 13803,
    "samples": null,
    "commands": ["pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>"],
    "persist": "pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple"
  },
  "mirrors": [ "…同结构，按 score 降序…" ],
  "persist": "…",
  "guide": "references/package-managers-guide.md",
  "dataset": { "version": "1.7.0", "last_full_test": "2026-09-21", "age_days": 0, "mirror_count": 121 },
  "caveats": ["分数来自社区实测，不同运营商/省份结果有差异，属正常现象。"]
}
```

`caveats` 是刻意设计的：数据超过 7 天未整体实测时会明确提示，
并出现 `"dataset": {"stale": true}` 之类的信号——AI 读到就知道该提醒用户重测，
而不是盲信一个过期排名。

## 本地运行

```bash
# 默认 127.0.0.1:8787（只本机可访问）
python3 server/accel_mirror_api.py

# 自检（不起服务，直接打印 9 个服务的解析结果 + 断言）
python3 server/accel_mirror_api.py --self-test

# 对外提供（注意：请务必放在反向代理后面并加 HTTPS）
python3 server/accel_mirror_api.py --host 0.0.0.0 --port 8787
```

## Docker 部署

```bash
# 方式一：compose（推荐）
docker compose -f server/docker-compose.yml up -d --build

# 方式二：手写 docker
docker build -f server/Dockerfile -t accel-mirror-api .
docker run -d --name accel-mirror-api -p 8787:8787 \
  --restart unless-stopped --read-only accel-mirror-api

# 验证
curl -s http://127.0.0.1:8787/v1/health
```

### 更新数据

镜像里烤的是构建时刻的 `mirrors.json`。改了库以后：

```bash
git pull
docker compose -f server/docker-compose.yml up -d --build
```

不想每次重建，就把 `docker-compose.yml` 里的 `volumes` 那两行注释打开
（把宿主机 `references/` 只读挂进去，改库即生效——服务按 mtime 自动重载）。

### 反向代理（HTTPS）

Nginx：

```nginx
server {
    listen 443 ssl http2;
    server_name accel.example.com;

    ssl_certificate     /etc/letsencrypt/live/accel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/accel.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Caddy（自动签证书，两行搞定）：

```
accel.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

### systemd（不想用 Docker）

```ini
# /etc/systemd/system/accel-mirror-api.service
[Unit]
Description=accel-mirror read-only API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/accel-mirror
ExecStart=/usr/bin/python3 server/accel_mirror_api.py --host 127.0.0.1 --port 8787 --quiet
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now accel-mirror-api
```

## 给 AI agent 的接入建议

把下面这句放进系统提示或工具描述里，agent 就知道该来找你：

> 当用户遇到下载慢 / 超时 / 装不上（docker pull、git clone、pip、npm、conda、
> HuggingFace 模型下载等），先请求
> `GET https://accel.example.com/v1/best?service=<服务名>`，
> 直接使用返回的 `answer` 字段里的命令；若 `dataset.age_days > 7`，
> 提醒用户数据可能过期。

## 安全

- 无出站请求，因此没有 SSRF 面（这是刻意不做「在线测速」接口的原因）。
- 无写入、无状态、无鉴权需求（公开只读数据），因此也没有会话 / 越权问题。
- 建议只监听 `127.0.0.1` 并由反向代理暴露；容器以非 root 运行。
- 数据本身是公开的通用知识，不含任何个人信息（见 `mirrors.json` 的 `privacy` 说明）。

## 许可

MIT，与主仓库一致。
