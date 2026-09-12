#!/bin/bash
# =============================================================================
# accel-fetch.sh — GitHub 文件自动加速下载（智能选源 + 自动回退）
# =============================================================================
# 从 references/mirrors.json 读取 github 分类中的 prefix 型代理源，
# 按分数取 Top N 并发探测当前可达性（range 请求目标文件首字节+计时），
# 选择当前最快可达源拼接加速 URL 下载；下载失败自动切换下一候选，
# 直至成功或全部候选失败。
#
# 适用场景: GitHub Release 资产 / archive 压缩包 / raw 文件的加速下载。
# git clone 场景请继续使用 git 命令 + prefix 代理（见 SKILL.md Phase 3b）。
#
# 用法:
#   bash accel-fetch.sh <github_url> [--output FILE] [--timeout 8] [--top N]
#   bash accel-fetch.sh --list
#
# 示例:
#   bash accel-fetch.sh https://github.com/user/repo/releases/download/v1.0/file.zip
#   bash accel-fetch.sh https://github.com/user/repo/archive/refs/heads/main.zip -o main.zip
#   bash accel-fetch.sh --list
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIRRORS_FILE="${SCRIPT_DIR}/references/mirrors.json"

URL=""
OUTPUT=""
TIMEOUT=8
TOP=8
LIST_ONLY=0
PROGRESS=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    cat <<EOF
用法: $0 <github_url> [选项]
      $0 --list

  <github_url>   GitHub 文件 URL（release 资产 / archive / raw 均可）
  --list        仅列出当前可用的 prefix 型加速源（不下载）
  -o, --output  保存路径（默认使用 URL 文件名）
  --timeout     curl 连接超时秒数（默认 8）
  --top N       探测候选源数量，按分数取前 N（默认 8）
  --progress    显示下载进度条（默认静默）
  --help, -h    显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --list)          LIST_ONLY=1; shift ;;
        -o|--output)     OUTPUT="$2"; shift 2 ;;
        --timeout)       TIMEOUT="$2"; shift 2 ;;
        --top)           TOP="$2"; shift 2 ;;
        --progress)      PROGRESS=1; shift ;;
        --help|-h)       usage; exit 0 ;;
        -*) echo "未知选项: $1" >&2; usage >&2; exit 1 ;;
        *)  [[ -z "$URL" ]] && URL="$1" || { echo "多余参数: $1" >&2; exit 1; }
            shift ;;
    esac
done

for cmd in curl python3; do
    command -v "$cmd" &>/dev/null || { echo "错误: 未找到 $cmd" >&2; exit 1; }
done
[[ -f "$MIRRORS_FILE" ]] || { echo "错误: 找不到 $MIRRORS_FILE" >&2; exit 1; }

# ---- 列出 prefix 型可用代理（按分数降序）----
# 输出每行: name|url|score
list_candidates() {
    python3 -c "
import json, sys
with open('$MIRRORS_FILE') as f:
    data = json.load(f)
mirrors = data.get('mirrors', {}).get('github', [])
seen = set()
for m in mirrors:
    if m.get('proxy_type') != 'prefix':
        continue
    if m.get('status') == 'deprecated':
        continue
    url = (m.get('url') or '').strip().rstrip('/')
    if not url:
        continue
    if url in seen:
        continue
    seen.add(url)
    print(f\"{m.get('name','')}|{url}|{m.get('score', 0)}\")
" 2>/dev/null
}

# ---------- 探测与下载 ----------

# 探测单个候选：对 <proxy>/<github_url> 发 range 请求首字节并计时
# 输出: url|time_ms|http_code
probe_one() {
    local proxy="$1"
    local target="$2"
    local accel_url="${proxy}/${target}"
    local result time_total http_code time_ms
    result=$(curl -o /dev/null -s -L \
        -r 0-1023 \
        -w '%{time_total}|%{http_code}' \
        --connect-timeout "$TIMEOUT" \
        --max-time "$((TIMEOUT * 3))" \
        "$accel_url" 2>/dev/null || echo '0.00|000')
    time_total="${result%%|*}"
    http_code="${result##*|}"
    case "$http_code" in
        200|206|301|302|307|308) time_ms=$(awk -v t="$time_total" 'BEGIN { printf "%.0f", t * 1000 }') ;;
        *) time_ms=999999 ;;
    esac
    printf '%s|%s|%s\n' "$accel_url" "$time_ms" "$http_code"
}
export -f probe_one
export TIMEOUT

# 并发探测 Top N 候选，输出按耗时升序（最快在前）
# 输出每行: url|time_ms|http_code（仅保留可达源）
probe_candidates() {
    local target="$1"
    local tmpdir
    tmpdir="$(mktemp -d)"
    local candidates
    candidates="$(list_candidates | head -n "$TOP")"
    if [[ -z "$candidates" ]]; then
        rm -rf "$tmpdir"
        return 1
    fi
    # 并发探测（最多 8 路，避免 TCP 突发拥塞）
    local p=$(( TOP > 8 ? 8 : TOP ))
    printf '%s\n' "$candidates" | awk -F'|' '{print $2}' \
        | xargs -P "$p" -I{} bash -c 'probe_one "$@"' _ '{}' "$target" \
        > "$tmpdir/probe.out" 2>/dev/null || true
    # Python 排序：过滤失败(999999)后按 time_ms 升序
    python3 -c "
import sys
lines = []
with open('$tmpdir/probe.out', encoding='utf-8') as f:
    for line in f:
        parts = line.rstrip('\n').split('|')
        if len(parts) < 3:
            continue
        url, t, code = parts[0], parts[1], parts[2]
        try:
            t = int(t)
        except ValueError:
            continue
        if t == 999999:
            continue
        lines.append((t, url, code))
lines.sort(key=lambda x: x[0])
for t, url, code in lines:
    print(f'{url}|{t}|{code}')
" 2>/dev/null
    rm -rf "$tmpdir"
}

# 用指定加速 URL 下载文件
# 返回: 0=成功 1=失败
download_via() {
    local accel_url="$1"
    local out="$2"
    local args=(-L --fail --connect-timeout "$TIMEOUT" --max-time "$((TIMEOUT * 60))")
    if [[ "$PROGRESS" -eq 1 ]]; then
        curl "${args[@]}" -o "$out" "$accel_url"
    else
        curl "${args[@]}" -sS -o "$out" "$accel_url"
    fi
}

# ================= 主流程 =================
# ---- --list 模式：仅展示可用 prefix 源 ----
if [[ "$LIST_ONLY" -eq 1 ]]; then
    echo -e "${CYAN}可用 prefix 型 GitHub 加速源（按分数降序）:${NC}"
    echo ""
    list_candidates | awk -F'|' '{printf "  %-28s %-40s (score %s)\n", $1, $2, $3}'
    echo ""
    echo "下载示例:"
    echo "  bash accel-fetch.sh https://github.com/user/repo/releases/download/v1.0/file.zip"
    exit 0
fi

# ---- 下载模式 ----
[[ -z "$URL" ]] && { echo "错误: 缺少 GitHub URL（用 --help 查看用法）" >&2; exit 1; }

# URL 校验：必须是 github.com 系域名
if ! grep -qE '^https?://(www\.)?github\.com/' <<<"$URL"; then
    echo "错误: 仅支持 github.com 的 URL（当前: $URL）" >&2
    exit 1
fi

# 默认输出文件名
if [[ -z "$OUTPUT" ]]; then
    OUTPUT="$(basename "$URL")"
    [[ -n "$OUTPUT" ]] || { echo "错误: 无法从 URL 推断文件名，请用 -o 指定" >&2; exit 1; }
fi

echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  accel-mirror 自动加速下载${NC}"
echo -e "${CYAN}════════════════════════════════════════════════${NC}"
echo "  目标: ${URL}"
echo "  保存: ${OUTPUT}"
echo ""

# 并发探测候选，按最快排序
ranked="$(probe_candidates "$URL" || true)"
TMPLIST="$(mktemp)"
trap 'rm -f "$TMPLIST"' EXIT
printf '%s\n' "$ranked" | grep -v '^$' > "$TMPLIST"

if [[ ! -s "$TMPLIST" ]]; then
    echo -e "${RED}✗ 全部 ${TOP} 个候选源当前均不可达，换网络或稍后重试（或改用 --top 扩大候选）${NC}" >&2
    exit 1
fi

echo -e "${YELLOW}探测到 $(wc -l < "$TMPLIST" | tr -d ' ') 个可达加速源（按响应耗时排序）:${NC}"
i=0
while IFS='|' read -r u t c; do
    i=$((i + 1))
    printf '  %d. %s  (%dms, HTTP %s)\n' "$i" "$u" "$t" "$c"
done < "$TMPLIST"
echo ""

# 依次尝试下载，失败自动回退下一候选
attempt=0
while IFS='|' read -r u t c; do
    attempt=$((attempt + 1))
    echo -e "${YELLOW}[$attempt] 尝试: ${u}${NC}"
    if download_via "$u" "$OUTPUT"; then
        size="$(stat -c%s "$OUTPUT" 2>/dev/null || echo 0)"
        echo -e "${GREEN}✔ 下载成功: ${OUTPUT} (${size} bytes)${NC}"
        echo "  加速源: ${u}"
        exit 0
    fi
    rm -f "$OUTPUT"  # 失败残留清掉，避免半截文件
    echo -e "${RED}  ✗ 失败，切换下一个候选...${NC}"
done < "$TMPLIST"

echo -e "${RED}✗ 所有可达源下载均失败，请检查网络或换时段重试${NC}" >&2
exit 1