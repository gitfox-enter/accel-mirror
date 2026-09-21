#!/bin/bash
# =============================================================================
# test_mirrors.sh — 并发测速脚本（Docker / GitHub / Tools 镜像源）
# =============================================================================
# 真并发：xargs -P 任务池（默认 8 并行，可用 --parallel 调整），
# 全量 90+ 源从串行约 1 分钟降至数秒。
#
# 输出协议：字段间用 TAB 分隔（name/url 中出现 '|' 的边界情况不再破坏解析）；
# JSON 由 Python 统一组装（彻底消除手工字符串拼接的非法 JSON 风险），
# 可直接 `python3 update_mirrors.py --input result.json` 回写。
#
# 深度模式（--deep）：对 github 分类里的 prefix 型代理额外做一次吞吐实测
# （经代理 Range 拉取 1MB 真实文件，记录 speed_bps），弥补「只测 RTT 不测带宽」
# 的盲区。深度结果由 update_mirrors.py 写入 mirrors.json 的 throughput_bps 字段，
# 用于同分镜像间的二次排序参考。
#
# 用法:
#   bash test_mirrors.sh [--type docker|github|tools|all] [--output FILE]
#                        [--timeout 10] [--parallel 8] [--deep]
#
# 示例:
#   bash test_mirrors.sh --type all --output /tmp/all.json --timeout 8 --parallel 16
#   bash test_mirrors.sh --type github --deep --output /tmp/gh.json
#   bash test_mirrors.sh --type tools
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Git Bash / MSYS 兼容：把 /c/... 风格路径转成 C:/...，否则 Windows 版 python 无法读取
if command -v cygpath &>/dev/null; then
    SCRIPT_DIR="$(cygpath -m "$SCRIPT_DIR")"
fi
MIRRORS_FILE="${SCRIPT_DIR}/references/mirrors.json"
TIMEOUT=10
PARALLEL=8
TEST_TYPE="all"
OUTPUT_FILE=""
DEEP=0

# --deep 模式使用的固定大文件（稳定 tag 的 release 资产，只拉 1MB Range）
DEEP_TARGET="${ACCEL_DEEP_TARGET:-https://github.com/BurntSushi/ripgrep/releases/download/14.1.0/ripgrep-14.1.0-x86_64-pc-windows-msvc.zip}"
DEEP_BYTES=1048575

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ---- 参数解析 ----
while [[ $# -gt 0 ]]; do
    case $1 in
        --type)       TEST_TYPE="$2"; shift 2 ;;
        --output)     OUTPUT_FILE="$2"; shift 2 ;;
        --timeout)    TIMEOUT="$2"; shift 2 ;;
        --parallel)   PARALLEL="$2"; shift 2 ;;
        --deep)       DEEP=1 ;;
        --help|-h)
            cat <<EOF
用法: $0 [--type docker|github|tools|all] [--output FILE] [--timeout SECONDS] [--parallel N] [--deep]

  --type      分类: docker(社区+企业) | github | tools | all(默认)
  --output    结果 JSON 输出文件（默认 stdout）
  --timeout   curl 连接超时秒数（默认 10）
  --parallel  并发任务数（默认 8）
  --deep      深度模式: 额外对 github prefix 代理做 1MB 真实吞吐实测（较慢）
EOF
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---- 依赖检查 ----
for cmd in curl python3 awk; do
    command -v "$cmd" &>/dev/null || { echo "Error: $cmd 未安装" >&2; exit 1; }
done
[[ -f "$MIRRORS_FILE" ]] || { echo "Error: 找不到 $MIRRORS_FILE" >&2; exit 1; }

# ---- 测速单个源 ----
# 输出: name \t url \t time_ms \t http_code \t status （TAB 分隔）
test_single() {
    local name="$1"
    local url="$2"
    local test_url="$3"

    # 无 test_url 的源跳过（不参与测速，保留原分）
    if [[ -z "$test_url" || "$test_url" == "null" ]]; then
        printf '%s\t%s\t0\t0\tskipped\n' "$name" "$url"
        return
    fi

    local result time_total http_code time_ms status="ok"
    # 注意: 不用 `curl -o /dev/null`——MSYS/Git Bash 下写 /dev/null 会产生
    # exit 23 (write error) 假阴性。改为 body 走 stdout 由 shell 丢弃，
    # -w 指标用 %{stderr} 输出再捕获。
    result=$(curl -s \
        -w '%{stderr}%{time_total}|%{http_code}' \
        --connect-timeout "$TIMEOUT" \
        --max-time "$((TIMEOUT * 3))" \
        "$test_url" 2>&1 >/dev/null || echo '0.00|000')

    time_total="${result%%|*}"
    http_code="${result##*|}"
    time_ms=$(awk -v t="$time_total" 'BEGIN { printf "%.0f", t * 1000 }')

    # 失败判定：连接失败 / 明确错误码 / 限流
    case "$http_code" in
        000|404|502|503|403|429) status="failed" ;;
    esac

    printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$url" "$time_ms" "$http_code" "$status"
}
export -f test_single
export TIMEOUT

# ---- 深度吞吐实测单个 prefix 代理 ----
# 经代理对固定文件发 Range 请求拉 1MB，记录 speed_download（bytes/s）。
# 输出: name \t url \t speed_bps \t http_code \t status
deep_single() {
    local name="$1"
    local url="$2"
    local accel_url="${url%/}/${DEEP_TARGET}"

    local result speed code
    # 同 test_single: 避免 `-o /dev/null` 在 MSYS 下的 exit 23 假阴性
    result=$(curl -s -L \
        -r "0-${DEEP_BYTES}" \
        -w '%{stderr}%{speed_download}|%{http_code}' \
        --connect-timeout "$TIMEOUT" \
        --max-time "$((TIMEOUT * 12))" \
        "$accel_url" 2>&1 >/dev/null || echo '0|000')

    speed="${result%%|*}"
    code="${result##*|}"
    local status="ok"
    case "$code" in
        000|404|502|503|403|429) status="failed" ;;
    esac
    [[ "$speed" =~ ^[0-9]+([.][0-9]+)?$ ]] || speed=0
    # curl 返回的是浮点，取整
    speed=$(awk -v s="$speed" 'BEGIN { printf "%.0f", s }')

    printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$url" "$speed" "$code" "$status"
}
export -f deep_single
export TIMEOUT DEEP_TARGET DEEP_BYTES

# ---- 取指定分类镜像列表 ----
# 输出每行: name \t url \t test_url
# MIRRORS_FILE / category 通过 argv 传入，避免字符串插值注入风险
get_mirrors() {
    local category="$1"
    # newline='\n': 禁止 Windows 版 python 把 \n 转成 \r\n（否则 URL 尾部带 \r，curl 报 exit 3 URL malformed）
    python3 - "$MIRRORS_FILE" "$category" <<'PY'
import json, sys
sys.stdout.reconfigure(newline='\n')
mirrors_file, category = sys.argv[1], sys.argv[2]
with open(mirrors_file, encoding='utf-8') as f:
    data = json.load(f)
for m in data.get('mirrors', {}).get(category, []):
    name = m.get('name', '')
    url = m.get('url', '') or ''
    test_url = m.get('test_url', '') or ''
    # 跳过无 test_url 的已弃用源；有 test_url 的保留以检测复活
    if m.get('status') == 'deprecated' and not test_url:
        continue
    print(f'{name}\t{url}\t{test_url}')
PY
}

# 取 github 分类里的 prefix 型代理（--deep 用）
# 输出每行: name \t url
get_prefix_proxies() {
    # newline='\n': 同 get_mirrors，防 Windows python 输出 \r\n
    python3 - "$MIRRORS_FILE" <<'PY'
import json, sys
sys.stdout.reconfigure(newline='\n')
mirrors_file = sys.argv[1]
with open(mirrors_file, encoding='utf-8') as f:
    data = json.load(f)
for m in data.get('mirrors', {}).get('github', []):
    if m.get('proxy_type') != 'prefix' or m.get('status') == 'deprecated':
        continue
    url = (m.get('url') or '').strip().rstrip('/')
    if not url:
        continue
    print(f"{m.get('name','')}\t{url}")
PY
}

# ---- 并发测试一个分类，输出 JSON 片段到 stdout ----
test_category() {
    local category="$1"
    local tmpdir="$2"
    local list_file="${tmpdir}/${category}.list"
    local out_file="${tmpdir}/${category}.out"

    get_mirrors "$category" > "$list_file" || true
    [[ -s "$list_file" ]] || { echo "[]"; return; }

    # xargs -P 并发执行 test_single，结果写每行 "name \t url \t time \t code \t status"
    # ${t%$'\r'}: 防御性去掉行尾 \r（Windows python 输出 CRLF 时 URL 会 malformed）
    cat "$list_file" | xargs -P "$PARALLEL" -I{} bash -c '
        IFS=$'"'"'\t'"'"' read -r n u t <<< "$1"
        test_single "$n" "$u" "${t%$'"'"'\r'"'"'}"
    ' _ {} > "$out_file" 2>/dev/null || true

    # out_file 路径转成 Windows 形式供 python 读取
    local out_file_py="$out_file"
    if command -v cygpath &>/dev/null; then
        out_file_py="$(cygpath -m "$out_file")"
    fi

    # 用 Python 组装合法 JSON 数组（避免字符串拼接转义问题）
    python3 - "$out_file_py" <<'PY'
import json, sys
entries = []
with open(sys.argv[1], encoding='utf-8') as f:
    for line in f:
        line = line.rstrip('\n')
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) < 5:
            continue
        name, url, time_ms, code, status = parts[0], parts[1], parts[2], parts[3], parts[4]
        entries.append({
            'name': name,
            'url': url,
            'time_ms': int(time_ms) if time_ms.isdigit() else 0,
            'http_code': code,
            'status': status,
        })
print(json.dumps(entries, ensure_ascii=False))
PY
}

# ---- 深度吞吐实测 github prefix 代理，把 speed_bps 合并进结果 ----
deep_category() {
    local tmpdir="$1"
    local list_file="${tmpdir}/deep.list"
    local out_file="${tmpdir}/deep.out"

    get_prefix_proxies > "$list_file" || true
    [[ -s "$list_file" ]] || return 0

    echo -e "${YELLOW}━━━ Deep throughput test (1MB via each prefix proxy) ━━━${NC}"
    cat "$list_file" | xargs -P "$PARALLEL" -I{} bash -c '
        IFS=$'"'"'\t'"'"' read -r n u <<< "$1"
        deep_single "$n" "$u"
    ' _ {} > "$out_file" 2>/dev/null || true

    # 合并: 给 ${tmpdir}/github.out 中对应条目追加 speed_bps 字段
    python3 - "$tmpdir" <<'PY'
import sys
tmpdir = sys.argv[1]

speeds = {}
try:
    with open(f'{tmpdir}/deep.out', encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 5:
                continue
            name, url, speed, code, status = parts
            if status == 'ok':
                try:
                    speeds[name] = int(float(speed))
                except ValueError:
                    pass
except FileNotFoundError:
    pass

lines = []
with open(f'{tmpdir}/github.out', encoding='utf-8') as f:
    raw = f.read()
for line in raw.splitlines():
    if not line:
        continue
    parts = line.split('\t')
    if len(parts) == 5:
        name, url, time_ms, code, status = parts
        if name in speeds:
            parts.append(str(speeds[name]))
        lines.append('\t'.join(parts))
with open(f'{tmpdir}/github.out', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + ('\n' if lines else ''))
PY
}

# ================= 主流程 =================
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  accel-mirror 并发测速引擎${NC}"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo "  并发: ${PARALLEL}  |  超时: ${TIMEOUT}s  |  类型: ${TEST_TYPE}  |  深度: $([[ $DEEP -eq 1 ]] && echo on || echo off)"
echo "  数据库: ${MIRRORS_FILE}"
echo ""

# 解析要测的分类
CATEGORIES=()
case "$TEST_TYPE" in
    all)     CATEGORIES=(docker_community docker_enterprise github tools) ;;
    docker)  CATEGORIES=(docker_community docker_enterprise) ;;
    github)  CATEGORIES=(github) ;;
    tools)   CATEGORIES=(tools) ;;
    *) echo "Error: 未知分类 '$TEST_TYPE'（可用: docker|github|tools|all）" >&2; exit 1 ;;
esac

# 临时目录（mktemp 保证唯一且可写）
# 注意: Windows 下 TEMP 环境变量是反斜杠路径，mktemp 会输出
# "C:\...\Temp/tmp.XXX" 混合形式，bash/python 对它的解释不一致，必须归一化:
#   - TMPDIR    -> POSIX 风格 (bash 内部使用)
#   - TMPDIR_PY -> Windows 风格 (传给 python 的 argv)
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
TMPDIR_PY="$TMPDIR"
if command -v cygpath &>/dev/null; then
    TMPDIR="$(cygpath -u "$TMPDIR")"
    TMPDIR_PY="$(cygpath -m "$TMPDIR")"
fi

for cat in "${CATEGORIES[@]}"; do
    echo -e "${YELLOW}━━━ Testing ${cat} ━━━${NC}"
    test_category "$cat" "$TMPDIR" > /dev/null
    count=$(wc -l < "${TMPDIR}/${cat}.out" 2>/dev/null || echo 0)
    echo -e "  ${GREEN}✓${NC} ${cat}: ${count} sources"
    echo ""
done

# 深度吞吐实测（仅 github 分类）
if [[ "$DEEP" -eq 1 ]]; then
    deep_category "$TMPDIR_PY"
    echo ""
fi

# Python 统一组装最终 JSON（直接读 .out 管道文件，完全规避字符串插值/转义问题）
FINAL_JSON="$(python3 - "$TMPDIR_PY" <<'PY'
import json, os, sys
from datetime import datetime

tmpdir = sys.argv[1]
result = {}
for f in sorted(os.listdir(tmpdir)):
    if not f.endswith('.out'):
        continue
    cat = f[:-4]
    entries = []
    with open(os.path.join(tmpdir, f), encoding='utf-8') as fh:
        for line in fh:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 5:
                continue
            name, url, time_ms, code, status = parts[0], parts[1], parts[2], parts[3], parts[4]
            entry = {
                'name': name,
                'url': url,
                'time_ms': int(time_ms) if time_ms.isdigit() else 0,
                'http_code': code,
                'status': status,
            }
            if len(parts) >= 6 and parts[5].isdigit() and int(parts[5]) > 0:
                entry['speed_bps'] = int(parts[5])
            entries.append(entry)
    result[cat] = entries

print(json.dumps({'test_time': datetime.now().isoformat(), 'results': result}, ensure_ascii=False))
PY
)"

# 输出
if [[ -n "$OUTPUT_FILE" ]]; then
    echo "$FINAL_JSON" | python3 -m json.tool > "$OUTPUT_FILE"
    echo -e "${GREEN}✅ Results saved to: ${OUTPUT_FILE}${NC}"
else
    echo "$FINAL_JSON" | python3 -m json.tool
fi

echo -e "${CYAN}Test complete.${NC}"
