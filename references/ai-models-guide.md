# AI 模型与数据集下载加速（国内网络）

面向「模型权重下载慢 / 断流 / 卡在 99%」这类问题。这类下载的特点是**文件极大**
（几 GB 到几百 GB）、**单个连接容易断**，所以换源只能解决一半问题，另一半靠
断点续传与多线程。

数据源见 `references/mirrors.json` 的 `ai_models` 分类；查询接口：

```bash
curl -s "http://<你的API地址>/v1/best?service=huggingface&limit=3"
curl -s "http://<你的API地址>/v1/best?service=ai-models&limit=5"
```

## 一、HuggingFace → hf-mirror

官方 `huggingface.co` 在国内经常连不上或龟速。hf-mirror 是完整的只读镜像，
**换一个环境变量即可**，无需改代码：

```bash
export HF_ENDPOINT=https://hf-mirror.com

# 之后所有工具都自动走镜像
huggingface-cli download Qwen/Qwen2.5-7B-Instruct --local-dir ./Qwen2.5-7B
python -c "from transformers import AutoModel; AutoModel.from_pretrained('Qwen/Qwen2.5-7B-Instruct')"
```

持久化（写进 shell 配置，避免每次都要 export）：

```bash
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc && source ~/.bashrc
```

Windows PowerShell：

```powershell
setx HF_ENDPOINT "https://hf-mirror.com"   # 新开终端生效
```

### 大文件断流怎么办

| 现象 | 处理 |
|---|---|
| 下到一半断流，重跑又从 0 开始 | 加 `--resume-download`（或直接重跑，新版 CLI 默认续传） |
| 单线程太慢 | `pip install hf_transfer` 并设 `HF_HUB_ENABLE_HF_TRANSFER=1`；**若镜像不支持多连接反而更慢/报错，就关掉它** |
| 磁盘被 cache 占满 | 设 `HF_HOME` 到数据盘：`export HF_HOME=/data/hf` |
| 只想下某几个文件 | `huggingface-cli download <repo> --include "*.safetensors" --exclude "*.bin"` |
| 要下 gated 模型（需授权） | 需在 HF 官网接受协议后 `huggingface-cli login`，镜像不支持 gated 仓库授权，此时只能想别的办法获取 |

> ⚠️ hf-mirror 是社区镜像，**大文件建议校验哈希**。仓库里每个文件的 SHA256 在
> HuggingFace 页面可见；`huggingface-cli` 也会校验 LFS 对象的 etag。

## 二、模型国内原生源（首选：不经任何代理）

国内平台是**原生托管**，速度快且不需要代理中间层，热门模型基本都有官方同步。

### ModelScope 魔搭（阿里）

```bash
pip install modelscope
modelscope download --model Qwen/Qwen2.5-7B-Instruct --local_dir ./Qwen2.5-7B

# 数据集
modelscope download --dataset <org>/<dataset> --local_dir ./data
```

### OpenXLab 浦源（上海人工智能实验室）

```bash
pip install openxlab
openxlab model download --model-repo OpenGVLab/InternVL2-8B -r ./models
```

### 其他国内原生平台

| 平台 | 地址 | 特点 |
|---|---|---|
| OpenI 启智 | `openi.pcl.ac.cn` | 国家级算力平台，模型 + 数据集 |
| BAAI 智源 FlagOpen | `hub.baai.ac.cn` | 悟道 / Aquila 系列，配套数据集（如 WuDaoCorpora） |
| WiseModel 始智 | `www.wisemodel.cn` | 社区型，国产开源权重较全 |

**策略建议**：先看 ModelScope 有没有（有就直接用，最快）；没有再退到 hf-mirror
（HuggingFace 生态最全）；落盘路径尽量放在数据盘而非系统盘。

## 三、为什么不用「一键 ollama 拉模型」的镜像

`ollama pull` 走的是 ollama 官方 registry，国内多数网络可直连，**不要**去套
第三方未知代理（历史上有过中间人替换模型文件的事）。要加速可以走官方原生路径：

```bash
# 从 ModelScope 拉 GGUF，再用 Modelfile 导入
modelscope download --model <org>/<repo>-GGUF --local_dir ./gguf
printf 'FROM ./gguf/<file>.gguf\n' > Modelfile
ollama create mymodel -f Modelfile
```

## 四、通用排错

| 症状 | 先查什么 |
|---|---|
| `ConnectionError` / `Read timed out` | 是否忘了设 `HF_ENDPOINT`；DNS 是否被污染（`nslookup hf-mirror.com`） |
| 速度只有几百 KB/s | 是否走了代理软件（代理反而拖慢国内原生源）；换 ModelScope 试 |
| 校验失败 / 文件损坏 | 删掉 cache 里对应 blob 重下；务必核对 SHA256 |
| 磁盘 inode 占满 | 大模型仓库有很多小文件，`HF_HUB_ENABLE_HF_TRANSFER` 下临时文件更多 |
| 公司网络拦 GitHub | 见 `references/github-mirrors-guide.md` |

## 五、给 AI agent 的决策规则

1. 用户说「模型下不动 / hf 连不上 / transformers 卡住」→ 先给 `export HF_ENDPOINT=https://hf-mirror.com`。
2. 用户在国内且模型是热门国产模型（Qwen / InternLM / GLM / DeepSeek / Baichuan 等）
   → **优先 ModelScope**，因为它是原生源，比走镜像更快。
3. 用户要的是数据集而非模型 → OpenI / BAAI 覆盖更全。
4. 任何情况下都不要推荐「未知的第三方模型代理站」——模型文件被替换的风险高于收益。
