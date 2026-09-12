# Docker 镜像加速完整指南

## 目录
1. [加速原理](#加速原理)
2. [daemon.json 配置（各平台）](#daemonjson-配置)
3. [华为云 SWR ddn-k8s 详解](#华为云-swr-ddn-k8s-详解)
4. [社区源 vs 企业源对比](#社区源-vs-企业源)
5. [推荐组合策略](#推荐组合策略)
6. [常见问题与排错](#常见问题与排错)

## 加速原理

Docker 客户端在执行 `docker pull` 时，默认从 `registry-1.docker.io` 拉取镜像。在国内，该地址经常被墙或速度极慢。

**registry-mirrors 机制**：在 `daemon.json` 中配置 `registry-mirrors` 数组后，Docker 会按顺序尝试从镜像源拉取。如果第一个失败，自动切换到下一个。这是一种透明加速——用户无需修改镜像名。

**前缀拼接机制**（华为云等企业源）：不配置 `registry-mirrors`，而是手动在镜像名前拼接企业仓库的完整路径。适合作为社区源全部失效时的保底方案。

## daemon.json 配置

### Linux

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<-'EOF'
{
  "registry-mirrors": [
    "https://docker.1panel.live",
    "https://hub.rat.dev",
    "https://docker.1ms.run"
  ]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
```

### Docker Desktop (Windows/Mac)

1. 打开 Docker Desktop → Settings → Docker Engine
2. 在 JSON 编辑器中添加 `registry-mirrors` 字段
3. 点击 "Apply & Restart"

```json
{
  "registry-mirrors": [
    "https://docker.1panel.live",
    "https://hub.rat.dev",
    "https://docker.1ms.run"
  ]
}
```

### Containerd (K8s 场景)

K8s 节点使用 containerd 而非 Docker，不读 `daemon.json`。需配置 containerd：

```bash
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml
# 编辑 config.toml，在 [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"] 下添加 endpoint
```

示例 config.toml 片段：
```toml
[plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
  endpoint = [
    "https://docker.1panel.live",
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io"
  ]
```

```bash
sudo systemctl restart containerd
```

### 验证配置生效

```bash
docker info | grep -A 5 "Registry Mirrors"
# 应输出配置的镜像源地址
```

## 华为云 SWR ddn-k8s 详解

### 本质

华为云 SWR（容器镜像服务）中维护了一个名为 `ddn-k8s` 的公开命名空间，预同步了 Docker Hub 上的常用镜像。通过在原始镜像名前拼接华为云路径，可绕过 Docker Hub 直接从华为云拉取。

### 使用方法

```bash
# 原始命令（会走 daemon.json 中的镜像源）
docker pull postgres:15-alpine

# 华为云保底拉取（不走镜像源，直接从华为云）
docker pull swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/postgres:15-alpine

# 重命名为短名，方便后续使用
docker tag swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/postgres:15-alpine postgres:15-alpine
```

### 路径规则

| 原始镜像 | 华为云完整路径 |
|---------|---------------|
| `nginx:latest` | `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:latest` |
| `langgenius/dify-api:1.13.2` | `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/langgenius/dify-api:1.13.2` |
| `postgres:15-alpine` | `swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/postgres:15-alpine` |

### 批量拉取脚本

```bash
#!/bin/bash
# 从华为云批量拉取并重命名镜像
HUAWEI_PREFIX="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io"

IMAGES=(
  "postgres:15-alpine"
  "redis:7-alpine"
  "nginx:latest"
  "langgenius/dify-api:1.13.2"
)

for img in "${IMAGES[@]}"; do
  echo "Pulling $img via Huawei Cloud..."
  docker pull "${HUAWEI_PREFIX}/${img}" && docker tag "${HUAWEI_PREFIX}/${img}" "${img}"
  if [ $? -eq 0 ]; then
    echo "✅ $img - success"
  else
    echo "❌ $img - failed (may not be in ddn-k8s namespace)"
  fi
done
```

### 注意事项

- 镜像覆盖取决于 `ddn-k8s` 命名空间的同步范围，不是所有 Docker Hub 镜像都有
- 免费使用，无需登录华为云账号
- 走国内骨干网，速度极快
- 不支持配置为 `registry-mirrors`（需要手动拼路径）

## 社区源 vs 企业源

| 特性 | 社区源 | 企业源（华为云） |
|------|--------|----------------|
| 配置方式 | daemon.json registry-mirrors | 手动拼路径 |
| 透明度 | 透明（docker pull 自动加速） | 非透明（需手动改镜像名） |
| 稳定性 | 低（个人维护，随时可能关停） | 高（企业级，官方维护） |
| 速度 | 快（有 CDN），但不稳定 | 极快（国内骨干网） |
| 覆盖范围 | 全部 Docker Hub 镜像 | 取决于同步范围 |
| 费用 | 免费 | 免费 |
| 2024年6月政策影响 | 大批失效 | 不受影响 |

## 推荐组合策略

**双轨方案**：
1. **日常**：在 `daemon.json` 配置 3 个高分社区源（如 `docker.1panel.live`、`hub.rat.dev`、`docker.1ms.run`）
2. **保底**：社区源失效时，使用华为云 `ddn-k8s` 手动拉取 + `docker tag` 重命名
3. **监控**：定期运行 `test_mirrors.sh` 检测社区源状态

**选源原则**：
- 优先选有企业背景的（`docker.m.daocloud.io` = DaoCloud，`docker.xuanyuan.me` = 轩辕）
- 优先选有多域名备用的（1panel 系列有 `.live`/`.dev`/`.top`）
- 避免只配单一源——社区源随时可能关停

## 常见问题与排错

### Q: 配置后 docker pull 仍然很慢

```bash
# 检查配置是否生效
docker info | grep -A 5 "Registry Mirrors"

# 手动测试某个源
time curl -sI https://docker.1panel.live/v2/ | head -5

# 查看 docker daemon 日志
sudo journalctl -u docker --since "5 min ago" | grep -i mirror
```

### Q: `manifest unknown` 或 `429 Too Many Requests`

这通常是镜像源被限流。切换到其他源，或使用华为云手动拉取。

### Q: 已失效的知名镜像源

截至 2026 年，以下老牌源已确认失效：
- `docker.mirrors.sjtug.sjtu.edu.cn`（上海交大，2026年6月因监管下架）
- `docker.mirrors.ustc.edu.cn`（中科大）
- `registry.docker-cn.com`（Docker 官方中国区）
- `hub-mirror.c.163.com`（网易）
- `mirrors.ccs.tencentyun.com`（腾讯云，不稳定）
- `dockerhub.icu`（2026年9月测试不可用）

### Q: 如何贡献新的镜像源

当发现新的可用镜像源时，使用 `update_mirrors.py --add` 添加到数据库，或直接编辑 `mirrors.json`，并在 `evolution_log` 中记录。
