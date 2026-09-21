# Package Manager Mirrors Guide (tools 分类)

国内常用包管理器换源速查。具体镜像 URL 以 `mirrors.json` 中 `tools` 分类
**当前最高分**条目为准——下面给出的只是常见默认值。

## npm

```bash
npm config set registry https://registry.npmmirror.com
# 验证
npm config get registry
# 临时使用（不改全局配置）
npm install --registry=https://registry.npmmirror.com <package>
```

## pip

```bash
# 单次使用
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <package>

# 永久配置（写入 pip.conf / pip.ini）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

可选源：清华 TUNA / 阿里云 / 中科大 / 豆瓣。

## Go

```bash
go env -w GOPROXY=https://goproxy.cn,direct
# 验证
go env GOPROXY
```

## apt (Ubuntu / Debian)

```bash
# 备份后替换 sources.list 中的 archive.ubuntu.com 为镜像站
sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak
# Ubuntu 22.04+ (jammy) 示例，用阿里源：
sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g; s|http://security.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list
sudo apt-get update
```

注意：Ubuntu 24.04 起改用 `/etc/apt/sources.list.d/ubuntu.sources`（DEB822 格式），
sed 目标文件不同。换源前先确认发行版与默认源文件路径。

## Homebrew

```bash
export HOMEBREW_API_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles/api"
export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.tuna.tsinghua.edu.cn/homebrew-bottles"
export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.tuna.tsinghua.edu.cn/git/homebrew/brew.git"
# 写入 ~/.zshrc 或 ~/.bashrc 永久生效
```

## Rust (crates.io)

```bash
# 使用字节跳动 rsproxy（稀疏索引）
cat >> ~/.cargo/config.toml <<'EOF'
[source.crates-io]
replace-with = 'rsproxy-sparse'
[source.rsproxy-sparse]
registry = "sparse+https://rsproxy.cn/index/"
[registries.rsproxy]
index = "sparse+https://rsproxy.cn/index/"
EOF
```

## Composer (PHP)

```bash
composer config -g repos.packagist composer https://mirrors.aliyun.com/composer/
```

## RubyGems

```bash
gem sources --add https://mirrors.tuna.tsinghua.edu.cn/rubygems/ --remove https://rubygems.org/
gem sources -l
```

## Gradle

`~/.gradle/init.gradle`（Groovy DSL）:

```groovy
allprojects {
    repositories {
        maven { url 'https://mirrors.cloud.tencent.com/gradle/' }
        maven { url 'https://maven.aliyun.com/repository/public' }
        mavenCentral()
    }
}
```

## Maven

`~/.m2/settings.xml`:

```xml
<mirrors>
  <mirror>
    <id>aliyun</id>
    <mirrorOf>central</mirrorOf>
    <url>https://maven.aliyun.com/repository/public</url>
  </mirror>
</mirrors>
```

---

> 维护提示：新增包管理器或镜像源时，同时在 `mirrors.json` 的 `tools` 分类
> 加条目（含 `test_url`），并按自我进化协议记录 `evolution_log`。
