# GitHub 加速完整指南

## 目录
1. [为什么 GitHub 在国内慢](#为什么-github-在国内慢)
2. [Clone 加速方案](#clone-加速方案)
3. [文件下载加速](#文件下载加速)
4. [全局配置方案](#全局配置方案)
5. [浏览器插件方案](#浏览器插件方案)
6. [Hosts 方案](#hosts-方案)
7. [自建 ghproxy 方案](#自建-ghproxy-方案)
8. [替代平台方案](#替代平台方案)
9. [策略推荐](#策略推荐)

## 为什么 GitHub 在国内慢

GitHub 的 CDN 域名（如 `assets-cdn.github.com`、`github.global.ssl.fastly.net`）在国内遭到 DNS 污染，导致：
- 域名解析到错误的 IP 或不可达的节点
- 即使能连上，也是走了远距离的海外节点
- 表现为：页面加载慢、clone 慢、release 下载超时

加速方案的核心思路：通过国内镜像站或代理中转，绕开被污染的 CDN。

## Clone 加速方案

### 方案 A：代理前缀（推荐）

在 `git clone` 命令的 GitHub URL 前加上代理地址：

```bash
# 使用 mirror.ghproxy.com
git clone https://mirror.ghproxy.com/https://github.com/user/repo.git

# 使用 ghproxy.net
git clone https://ghproxy.net/https://github.com/user/repo.git

# 使用 gh-proxy.com
git clone https://gh-proxy.com/https://github.com/user/repo.git
```

**注意**：不支持 SSH Key 方式 clone。只能用 HTTPS。

### 方案 B：域名替换

将 `github.com` 替换为镜像域名：

```bash
# 使用 bgithub.xyz
git clone https://bgithub.xyz/user/repo.git

# 使用 kkgithub.com
git clone https://kkgithub.com/user/repo.git

# 使用 gitclone.com
git clone https://gitclone.com/github.com/user/repo.git

# 使用 hub.fastgit.org
git clone https://hub.fastgit.org/user/repo.git
```

### 方案 C：Gitee 导入

1. 在 Gitee 注册账号
2. 新建仓库 → 选择"导入已有仓库"
3. 粘贴 GitHub 仓库 URL
4. 等待 Gitee 完成同步
5. 从 Gitee clone

优点：极其稳定。缺点：需要手动导入，同步有延迟，私有仓库需配置。

## 文件下载加速

### Release 文件下载

```bash
# 原始链接
wget https://github.com/user/repo/releases/download/v1.0/file.zip

# 通过代理加速
wget https://mirror.ghproxy.com/https://github.com/user/repo/releases/download/v1.0/file.zip

# 通过 ghproxy.net（支持断点续传）
wget -c https://ghproxy.net/https://github.com/user/repo/releases/download/v1.0/file.zip
```

### Archive (ZIP/TAR.GZ) 下载

```bash
# 分支源码
wget https://mirror.ghproxy.com/https://github.com/user/repo/archive/main.zip

# Tag 源码
wget https://mirror.ghproxy.com/https://github.com/user/repo/archive/refs/tags/v1.0.zip
```

### Raw 文件下载

```bash
# 原始
wget https://raw.githubusercontent.com/user/repo/main/file.txt

# 通过代理（注意路径格式）
wget https://mirror.ghproxy.com/https://raw.githubusercontent.com/user/repo/main/file.txt
```

### 批量下载脚本

```bash
#!/bin/bash
# 通过代理批量下载 GitHub Release 文件
PROXY="https://mirror.ghproxy.com"
DOWNLOADS=(
  "https://github.com/user/repo/releases/download/v1.0/file1.zip"
  "https://github.com/user/repo/releases/download/v1.0/file2.zip"
  "https://github.com/user/repo/releases/download/v1.0/file3.tar.gz"
)

for url in "${DOWNLOADS[@]}"; do
  echo "Downloading $url..."
  wget -c "${PROXY}/${url}" -P ./downloads/
done
echo "All downloads complete."
```

## 全局配置方案

### 方法 1：git config insteadOf（推荐）

一次配置，所有后续 `git clone` 自动加速：

```bash
# 设置全局代理（使用 mirror.ghproxy.com）
git config --global url."https://mirror.ghproxy.com/https://".insteadOf "https://github.com/"

# 验证
git config --global --get-regexp url

# 取消
git config --global --unset url."https://mirror.ghproxy.com/https://".insteadOf
```

配置后，正常使用 `git clone https://github.com/user/repo.git`，Git 会自动走代理。

### 方法 2：gitclone.com 全局镜像

```bash
git config --global url."https://gitclone.com".insteadOf https://

# 之后正常 clone 即可
git clone https://github.com/tensorflow/tensorflow.git
```

**注意**：`insteadOf https://` 会代理所有 HTTPS 仓库（不只是 GitHub），可能影响其他 Git 托管平台。建议用 `insteadOf "https://github.com/"` 更精确。

## 浏览器插件方案

### 油猴脚本

安装 Tampermonkey/Greasemonkey，搜索 "GitHub加速" 脚本，可在 GitHub 页面自动添加加速下载按钮。

### dev-sidecar

开源工具，安装后自动加速 GitHub 访问：
- 项目地址：https://github.com/docmirror/dev-sidecar
- 支持 Windows/Mac
- 自动处理 DNS 污染问题
- 不仅加速 GitHub，还加速 Stack Overflow 等

## Hosts 方案

### GitHub520

自动更新 GitHub hosts 文件，解决 DNS 污染：
- 项目地址：https://github.com/521xueweihan/GitHub520
- 自动获取最新 GitHub IP 地址
- 自动写入系统 hosts 文件

### 手动配置 hosts

1. 访问 https://ipaddress.com/website/github.com 查询 GitHub IP
2. 编辑 hosts 文件：
   - Windows: `C:\Windows\System32\drivers\etc\hosts`
   - Linux/Mac: `/etc/hosts`
3. 添加：
   ```
   20.205.243.166 github.com
   185.199.108.133 raw.githubusercontent.com
   ```
4. 刷新 DNS：
   - Windows: `ipconfig /flushdns`
   - Linux: `sudo systemctl restart nscd` 或 `sudo systemd-resolve --flush-caches`

**注意**：hosts 方案不太稳定，IP 可能随时变化。建议优先使用代理方案。

## 自建 ghproxy 方案

如果公共代理都不稳定，可以自建 ghproxy 服务。

### hunshcn/gh-proxy（Python）

```bash
# 部署到 Vercel
# 1. Fork https://github.com/hunshcn/gh-proxy
# 2. 导入到 Vercel
# 3. 部署后获得自己的 ghproxy 域名
```

### WJQSERVER-STUDIO/ghproxy（Go）

```bash
# Docker 部署
docker run -d \
  --name ghproxy \
  -p 8080:8080 \
  -v /data/ghproxy:/data \
  ghcr.io/wjqserver-studio/ghproxy:latest

# 使用自建代理
git clone http://your-server:8080/https://github.com/user/repo.git
```

优点：完全自主控制，不限速，支持 Docker Hub 和 GHCR 代理。

## 替代平台方案

### Gitee 镜像库

https://gitee.com/organizations/mirrors/projects

码云官方维护的热门开源项目镜像，稳定性最高。支持 `git clone`。

### 清华大学 GitHub Release 镜像

https://mirrors.tuna.tsinghua.edu.cn/github-release

按项目名检索 Release 文件，学术场景首选。

## 策略推荐

| 场景 | 推荐方案 |
|------|---------|
| 偶尔 clone 仓库 | 代理前缀（mirror.ghproxy.com） |
| 经常 clone 多个仓库 | `git config --global url.insteadOf` 全局配置 |
| 下载大体积 Release | ghproxy.net（支持断点续传）或 ghproxy.homeboyc.cn |
| 浏览 GitHub 网页 | bgithub.xyz 或 kkgithub.com 域名替换 |
| 需要最稳定方案 | Gitee 导入或清华镜像 |
| 完全自主可控 | 自建 ghproxy |
| 浏览器加速 | 安装 dev-sidecar 或油猴脚本 |

**多级降级策略**：
1. 先尝试全局 git config 代理
2. 代理不通 → 尝试域名替换镜像（bgithub.xyz）
3. 镜像不通 → Gitee 导入
4. 全部不通 → 自建 ghproxy 或 dev-sidecar

---

## 附录：operit.app 内置加速源（2026-09-11 收录）

Operit AI 官网（https://operit.app）下载页"自动选择加速"功能内置了一批 GitHub 加速镜像，已按技能的自我进化协议全部收录进 `mirrors.json` 的 `github` 分类（初始 score 50，未实测，待跑 `test_mirrors.sh` 打分）。

**收录来源**：operit.app 前端打包 JS `assets/index-DvFOZnjl.js` 中的镜像数组。

**收录清单**（新增 30 个，另有 4 个与数据库已有条目重合未重复添加）：

- ghfast.top（Ghfast）
- ghproxy.com（GhProxy，注意与 ghproxy.net 区分）
- github.abskoop.workers.dev（Cloudflare Workers 实现）
- gh.h233.eu.org
- ghproxy.1888866.xyz
- ghproxy.cfd
- github.boki.moe
- gh-proxy.net（与 ghproxy.net 不同域名）
- gh.jasonzeng.dev
- gh.monlor.com
- fastgit.cc（FastGit 新域名，domain 型）
- github.tbedu.top
- firewall.lxstd.org
- github.ednovas.xyz
- ghfile.geekertao.top
- gh.chjina.com
- ghpxy.hwinzniej.top
- cdn.crashmc.com
- git.yylx.win
- gitproxy.mrhjx.cn
- ghproxy.cxkpro.top
- gh.xxooo.cf
- github.limoruirui.com
- gh.llkk.cc
- down.npee.cn（官方 URL 结尾带 `?`，拼接时注意）
- gh.nxnow.top
- gh.zwy.one
- ghproxy.monkeyray.net
- gh.xx9527.cn

**已存在、未重复添加的**：ghproxy.net、mirror.ghproxy.com、gh-proxy.com、hub.gitmirror.com。

> 提示：这些源多为社区维护的 ghproxy 系加速站，可用性波动大，使用前建议先 `bash scripts/test_mirrors.sh --type github` 实测评分。
