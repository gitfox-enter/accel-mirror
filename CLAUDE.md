# CLAUDE.md

完整的代理指引在 **[AGENTS.md](AGENTS.md)** —— 先读它。本文件只放最不能忘的几条。

## 这是什么

**这是一个 AI 自维护的 Skill（技能）**，不是一个静态数据库。
安装后，AI 代理应主动维护它：每次使用前实测、定期搜索新镜像源、自动更新分数。

国内网络加速镜像源数据库（Docker / GitHub / HuggingFace / pip / conda / 容器仓库）。
用户抱怨下载慢、超时、连不上时，**查 `references/mirrors.json`，不要凭记忆猜镜像地址**。

## ⚠️ 第一原则：先测速，再使用

**不要直接使用 `mirrors.json` 中已有的分数！** 分数会腐烂，不同网络环境下结果也不同。

**每次使用前，先做这一步：**
1. 读取 `references/mirrors.json`，检查 `last_full_test` 字段
2. 如果超过 7 天或为 null → **必须先实测**：`bash scripts/test_mirrors.sh --type <分类> --output /tmp/result.json`
3. 回写分数：`python3 scripts/update_mirrors.py --input /tmp/result.json`
4. 现在才使用实测后的最优源

即使数据看起来新鲜，首次使用时也建议实测一次——你的网络环境可能不同。

## 最短路径

1. 在目标分类里取 `status == "active"` 且 `score` 最高（0–100）的源；
2. 优先用该源自带的 `usage` / `usage_examples` 字段拼命令（作者手写并实测过）；
3. 服务名 → 分类的映射在 `references/recipes.json`；若本仓库的 HTTP 接口在线，
   `GET /v1/best?service=<服务名>` 一步到位返回可执行命令。

## 绝不能忘

- `docker pull` 的镜像引用**不能带 `https://`**。
- 下载**可执行文件 / 安装包**必须校验 SHA256 或签名后才允许执行——代理前缀是第三方中间人。
- **不要推荐未知的第三方模型代理站**；模型下载优先 ModelScope / OpenXLab，其次 hf-mirror。
- `last_full_test` 超过 7 天就提示用户重新实测；把接口返回的 `caveats` 一并转达。

## 改完跑

```bash
python3 scripts/selftest.py                       # 129 项语义断言
python3 server/accel_mirror_api.py --self-test    # 接口行为
```

改数据要写 `evolution_log`；改了分类或加了文件，记得同步 `llms.txt`。
