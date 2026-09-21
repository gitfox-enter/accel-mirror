#!/bin/bash
# =============================================================================
# accel-fetch.sh — GitHub 文件自动加速下载（智能选源 + 多下载器 + 自动校验回退）
# =============================================================================
# 从 references/mirrors.json 读取 github 分类中的 prefix 型代理源，
# 按分数取 Top N 并发探测当前可达性（range 请求目标文件首字节+计时+取 Content-Length），
# 选择当前最快可达源拼接加速 URL 下载。
#
# 下载引擎自动选择（--engine auto，默认）:
#   aria2c (多线程 16x16) > curl (单线程, 最稳) > axel (备用)
# 每个引擎下载后都会做【大小校验】（对比 Content-Length），
# 大小不符或失败自动切换下一候选源，直到成功或全部失败。
# 可选 --sha256 校验：下载后比对哈希，不符自动换源重下。
#
# 适用场景: GitHub Release 资产 / archive 压缩包 / raw 文件的加速下载。
# git clone 场景请继续使用 git 命令 + prefix 代理（见 SKILL.md Phase 3b）。
#
# 用法:
#   bash accel-fetch.sh <github_url> [--output FILE] [--timeout 8] [--top N]
#   bash accel-fetch.sh <github_url> --engine aria2|curl|axel
#   bash accel-fetch.sh <github_url> --sha256 <期望哈希>
#   bash accel-fetch.sh --list
#   bash accel-fetch.sh --doctor     # 下载器自检（AI 安装后验证用）
#
# 示例:
#   bash accel-fetch.sh https://github.com/user/repo/releases/download/v1.0/file.zip
#   bash accel-fetch.sh https://github.com/user/repo/archive/refs/heads/main.zip -o main.zip
#   bash accel-fetch.sh https://github.com/user/repo/releases/download/v1.0/app.apk --sha256 d54a71f4...
#   bash accel-fetch.sh --list
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Git Bash / MSYS 兼容：把 /c/... 风格路径转成 C:/...，否则 Windows 版 python 无法读取
if command -v cygpath &>/dev/null; then
    SCRIPT_DIR="$(cygpath -m "$SCRIPT_DIR")"
fi
MIRRORS_FILE="${SCRIPT_DIR}/references/mirrors.json"

URL=""
OUTPUT=""
TIMEOUT=8
TOP=8
LIST_ONLY=0
PROGRESS=0
ENGINE="auto"
SHA256_EXPECT=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    cat <<EOF
用法: $0 <github_url> [选项]
      $0 --list
      $0 --doctor

  <github_url>   GitHub 文件 URL（release 资产 / archive / raw 均可）
  --list        仅列出当前可用的 prefix 型加速源（不下载）
  --doctor      下载器自检：检查 aria2c/curl/axel 是否可用并给出安装建议
  -o, --output  保存路径（默认使用 URL 文件名）
  --timeout     curl 连接超时秒数（默认 8）
  --top N       探测候选源数量，按分数取前 N（默认 8）
  --engine      下载引擎: auto(默认, aria2→curl→axel) | aria2 | curl | axel
  --sha256      期望 SHA256（可选，下载后校验，不符自动换源重下）
  --progress    显示下载进度条（默认静默）
  --help, -h    显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --list)          LIST_ONLY=1; shift ;;
        --doctor)        DOCTOR=1; shift ;;
        -o|--output)     OUTPUT="$2"; shift 2 ;;
        --timeout)       TIMEOUT="$2"; shift 2 ;;
        --top)           TOP="$2"; shift 2 ;;
        --engine)        ENGINE="$2"; shift 2 ;;
        --sha256)        SHA256_EXPECT="$2"; shift 2 ;;
        --progress)      PROGRESS=1; shift ;;
        --help|-h)       usage; exit 0 ;;
        -*) echo "未知选项: $1" >&2; usage >&2; exit 1 ;;
        *)  [[ -z "$URL" ]] && URL="$1" || { echo "多余参数: $1" >&2; exit 1; }
            shift ;;
    esac
done

case "$ENGINE" in
    auto|aria2|curl|axel) ;;
    *) echo "错误: 未知引擎 $ENGINE（可选 auto/aria2/curl/axel）" >&2; exit 1 ;;
esac

for cmd in curl python3; do
    command -v "$cmd" &>/dev/null || { echo "错误: 未找到 $cmd" >&2; exit 1; }
done
[[ -f "$MIRRORS_FILE" ]] || { echo "错误: 找不到 $MIRRORS_FILE" >&2; exit 1; }

# ---------------- 下载器自检 ----------------
check_engine() {
    local name="$1" bin="$2"
    if command -v "$bin" &>/dev/null; then
        local ver
        case "$name" in
            aria2) ver="$("$bin" --version 2>/dev/null | head -1 | awk '{print $3}')" ;;
            curl)  ver="$("$bin" --version 2>/dev/null | head -1 | awk '{print $2}')" ;;
            axel)  ver="$("$bin" --version 2>/dev/null | head -1 | awk '{print $3}')" ;;
            *)     ver="" ;;
        esac
        printf '%s|1|%s\n' "$name" "$ver"
    else
        printf '%s|0|\n' "$name"
    fi
}

install_hint() {
    cat <<EOF

${YELLOW}下载器安装建议（AI 可直接执行）:${NC}
  Debian/Ubuntu (含 proot 小电脑):  sudo apt-get update && sudo apt-get install -y aria2 curl axel
  CentOS/RHEL/Fedora:               sudo yum install -y aria2 curl axel   # 或 dnf
  Alpine:                           apk add aria2 curl axel
  macOS (Homebrew):                 brew install aria2 axel
  Termux (Android):                 pkg install aria2 curl axel
安装后可用 'bash accel-fetch.sh --doctor' 验证。
EOF
}

if [[ "${DOCTOR:-0}" -eq 1 ]]; then
    echo -e "${CYAN}════ accel-mirror 下载器自检 ════${NC}"
    echo ""
    ok=0
    while IFS='|' read -r n inst ver; do
        if [[ "$inst" == "1" ]]; then
            echo -e "  ${GREEN}✔${NC} $n  (${ver})"
            ok=$((ok + 1))
        else
            echo -e "  ${RED}✗${NC} $n  未安装"
        fi
    done < <(check_engine aria2 aria2c; check_engine curl curl; check_engine axel axel)
    echo ""
    echo "可用引擎: $ok/3"
    if [[ "$ok" -lt 3 ]]; then
        install_hint
    else
        echo -e "${GREEN}✔ 全齐，auto 模式将使用 aria2(多线程) 优先。${NC}"
    fi
    exit 0
fi

# ---------------- 列出 prefix 型可用代理（按分数降序） ----------------
# MIRRORS_FILE 通过 argv 传入（避免路径插值注入风险）
list_candidates() {
    python3 - "$MIRRORS_FILE" <<'PY' 2>/dev/null
import json, sys
sys.stdout.reconfigure(newline='\n')  # 防 Windows python 输出 \r\n
with open(sys.argv[1]) as f:
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
    print(f"{m.get('name','')}|{url}|{m.get('score', 0)}")
PY
}

# ---------------- 探测与下载 ----------------

# 探测单个候选：对 <proxy>/<github_url> 发 range 请求首字节并计时
# 通过响应头解析文件真实大小（Content-Range 总数，range 请求下最可靠），
# 避免源返回错误页/部分内容时用错大小。
# 输出: url|time_ms|http_code|total_size
probe_one() {
    local proxy="$1"
    local target="$2"
    local accel_url="${proxy}/${target}"
    local hdrfile result time_total http_code time_ms total size
    hdrfile="$(mktemp)"
    # 避免 `-o /dev/null` 在 MSYS/Git Bash 下的 exit 23 假阴性:
    # 响应头写临时文件，body 由 shell 丢弃，-w 指标经 %{stderr} 输出后捕获
    result=$(curl -s -L \
        -r 0-1023 \
        -D "$hdrfile" \
        -w '%{stderr}%{time_total}|%{http_code}|%{size_download}' \
        --connect-timeout "$TIMEOUT" \
        --max-time "$((TIMEOUT * 3))" \
        "$accel_url" 2>&1 >/dev/null || echo '0.00|000|0')
    hdr="$(cat "$hdrfile" 2>/dev/null || true)"
    rm -f "$hdrfile"
    # 最后一行是 -w 输出，前面是响应头
    result="$(printf '%s\n' "$hdr" | tail -1)"
    time_total="${result%%|*}"
    http_code="$(echo "$result" | cut -d'|' -f2)"
    size="$(echo "$result" | cut -d'|' -f3)"
    # 从响应头解析真实文件总大小
    total="$(printf '%s\n' "$hdr" | grep -i '^Content-Range:' | tail -1 | sed -E 's/.*bytes [0-9]+-[0-9]+\/([0-9]+).*/\1/' | tr -d '\r')"
    # 无 Content-Range 时回退 Content-Length
    if [[ -z "$total" ]]; then
        total="$(printf '%s\n' "$hdr" | grep -i '^Content-Length:' | tail -1 | awk '{print $2}' | tr -d '\r')"
    fi
    # 再回退实际下载字节数（仅当明确拿到完整内容时可靠）
    [[ -z "$total" ]] && total="$size"
    case "$http_code" in
        200|206|301|302|307|308) time_ms=$(awk -v t="$time_total" 'BEGIN { printf "%.0f", t * 1000 }') ;;
        *) time_ms=999999 ;;
    esac
    printf '%s|%s|%s|%s\n' "$accel_url" "$time_ms" "$http_code" "$total"
}
export -f probe_one
export TIMEOUT

# 并发探测 Top N 候选，输出按耗时升序（最快在前）
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
    local p=$(( TOP > 8 ? 8 : TOP ))
    printf '%s\n' "$candidates" | awk -F'|' '{print $2}' \
        | xargs -P "$p" -I{} bash -c 'probe_one "$@"' _ '{}' "$target" \
        > "$tmpdir/probe.out" 2>/dev/null || true
    python3 -c "
import sys
from collections import Counter
lines = []
with open('$tmpdir/probe.out', encoding='utf-8') as f:
    for line in f:
        parts = line.rstrip('\n').split('|')
        if len(parts) < 4:
            continue
        url, t, code, size = parts[0], parts[1], parts[2], parts[3]
        try:
            t = int(t)
        except ValueError:
            continue
        if t == 999999:
            continue
        lines.append((t, url, code, size))
lines.sort(key=lambda x: x[0])
# 多数投票：期望大小取可达源中出现最多的值（避免单一坏源带偏）
sizes = [s for _, _, _, s in lines if s and s != '0']
expect = Counter(sizes).most_common(1)[0][0] if sizes else ''
print(f'EXPECT_SIZE={expect}')
for t, url, code, size in lines:
    print(f'{url}|{t}|{code}|{size}')
" 2>/dev/null
    rm -rf "$tmpdir"
}

# 大小校验：下载后对比 Content-Length（探测时拿到的最快源的大小）
size_ok() {
    local file="$1" expect="$2"
    [[ -z "$expect" || "$expect" == "0" ]] && return 0
    local actual
    actual="$(stat -c%s "$file" 2>/dev/null || echo 0)"
    [[ "$actual" == "$expect" ]]
}

# SHA256 校验：可选
sha_ok() {
    local file="$1"
    [[ -z "$SHA256_EXPECT" ]] && return 0
    local actual
    actual="$(sha256sum "$file" 2>/dev/null | awk '{print $1}')"
    [[ "$actual" == "$SHA256_EXPECT" ]]
}

# 用 aria2c 多线程下载（16 线程）。返回 0=成功
dl_aria2() {
    local accel_url="$1" out="$2"
    local dir tmpf
    dir="$(dirname "$(realpath -m "$out")")"
    tmpf="$(basename "$out").aria2.tmp"
    local args=(-x16 -s16 --max-tries=3 --retry-wait=2 \
        --timeout="$TIMEOUT" --connect-timeout="$TIMEOUT" \
        --allow-overwrite=true --auto-file-renaming=false \
        --file-allocation=none -d "$dir" -o "$tmpf" "$accel_url")
    if [[ "$PROGRESS" -eq 1 ]]; then
        aria2c "${args[@]}"
    else
        aria2c --quiet=true "${args[@]}"
    fi
    if [[ -f "$dir/$tmpf" ]]; then
        mv -f "$dir/$tmpf" "$out"
        return 0
    fi
    return 1
}

# 用 curl 单线程下载（最稳）。返回 0=成功
dl_curl() {
    local accel_url="$1" out="$2"
    local args=(-L --fail --connect-timeout "$TIMEOUT" --max-time "$((TIMEOUT * 120))")
    if [[ "$PROGRESS" -eq 1 ]]; then
        curl "${args[@]}" -o "$out" "$accel_url"
    else
        curl "${args[@]}" -sS -o "$out" "$accel_url"
    fi
}

# 用 axel 下载（备用）。返回 0=成功
dl_axel() {
    local accel_url="$1" out="$2"
    local dir tmpf
    dir="$(dirname "$(realpath -m "$out")")"
    tmpf="$(basename "$out").axel.tmp"
    mkdir -p "$dir"
    if [[ "$PROGRESS" -eq 1 ]]; then
        (cd "$dir" && axel -n 8 -a -o "$tmpf" "$accel_url") 2>&1 || true
    else
        (cd "$dir" && axel -n 8 -a -q -o "$tmpf" "$accel_url") >/dev/null 2>&1 || true
    fi
    if [[ -f "$dir/$tmpf" ]]; then
        mv -f "$dir/$tmpf" "$out"
        return 0
    fi
    return 1
}

# 主下载分发：按 engine 顺序尝试，每次下载后做大小+SHA256 校验
download_via() {
    local accel_url="$1" out="$2" expect_size="$3"
    local engines=()
    case "$ENGINE" in
        auto)   command -v aria2c &>/dev/null && engines+=(aria2); engines+=(curl); command -v axel &>/dev/null && engines+=(axel) ;;
        aria2)  engines=(aria2) ;;
        curl)   engines=(curl) ;;
        axel)   engines=(axel) ;;
    esac
    local e
    for e in "${engines[@]}"; do
        rm -f "$out"
        echo -e "  ${CYAN}[引擎 $e]${NC} 开始下载..."
        local ok=0
        case "$e" in
            aria2) dl_aria2 "$accel_url" "$out" && ok=1 ;;
            curl)  dl_curl  "$accel_url" "$out" && ok=1 ;;
            axel)  dl_axel  "$accel_url" "$out" && ok=1 ;;
        esac
        if [[ "$ok" -eq 1 ]] && size_ok "$out" "$expect_size" && sha_ok "$out"; then
            return 0
        fi
        rm -f "$out"
        echo -e "  ${RED}  ✗ 引擎 $e 校验失败（大小不符或哈希不符），切换...${NC}"
    done
    return 1
}

# ================= 主流程 =================
# ---- --list 模式 ----
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

# URL 校验
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
echo "  引擎: ${ENGINE} (auto = aria2→curl→axel)"
[[ -n "$SHA256_EXPECT" ]] && echo "  SHA256 校验: 启用"
echo ""

# 并发探测候选
ranked="$(probe_candidates "$URL" || true)"
TMPLIST="$(mktemp)"
trap 'rm -f "$TMPLIST"' EXIT
# 解析多数投票期望大小（第一行 EXPECT_SIZE=xxx）
EXPECT_SIZE="$(printf '%s\n' "$ranked" | grep '^EXPECT_SIZE=' | head -1 | cut -d= -f2)"
printf '%s\n' "$ranked" | grep -v '^$' | grep -v '^EXPECT_SIZE=' > "$TMPLIST"

if [[ ! -s "$TMPLIST" ]]; then
    echo -e "${RED}✗ 全部 ${TOP} 个候选源当前均不可达，换网络或稍后重试（或改用 --top 扩大候选）${NC}" >&2
    exit 1
fi

echo -e "${YELLOW}探测到 $(wc -l < "$TMPLIST" | tr -d ' ') 个可达加速源（按响应耗时排序）:${NC}"
i=0
while IFS='|' read -r u t c s; do
    i=$((i + 1))
    printf '  %d. %s  (%dms, HTTP %s%s)\n' "$i" "$u" "$t" "$c" "${s:+ size=$s}"
done < "$TMPLIST"
echo ""

# 依次尝试候选源，每个源内部引擎自动回退
attempt=0
while IFS='|' read -r u t c s; do
    attempt=$((attempt + 1))
    echo -e "${YELLOW}[候选 $attempt] ${u}${NC}"
    # 用多数投票期望大小做校验基准（防止坏源返回错误页仍被误判成功）
    if download_via "$u" "$OUTPUT" "$EXPECT_SIZE"; then
        size="$(stat -c%s "$OUTPUT" 2>/dev/null || echo 0)"
        echo -e "${GREEN}✔ 下载成功: ${OUTPUT} (${size} bytes)${NC}"
        echo "  加速源: ${u}"
        [[ -n "$SHA256_EXPECT" ]] && echo -e "${GREEN}✔ SHA256 校验通过${NC}"
        exit 0
    fi
    rm -f "$OUTPUT"
    echo -e "${RED}  ✗ 该源所有引擎均失败，切换下一候选...${NC}"
done < "$TMPLIST"

echo -e "${RED}✗ 所有可达源下载均失败，请检查网络或换时段重试${NC}" >&2
exit 1
