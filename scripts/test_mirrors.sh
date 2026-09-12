#!/bin/bash
# =============================================================================
# test_mirrors.sh — 并发测速脚本（Docker / GitHub / Tools 镜像源）
# =============================================================================
# 真并发：xargs -P 任务池（默认 8 并行，可用 --parallel 调整），
# 全量 90+ 源从串行约 1 分钟降至数秒。
# 输出 JSON 由 Python 统一组装（彻底消除手工字符串拼接的非法 JSON 风险），
# 可直接 `python3 update_mirrors.py --input result.json` 回写。
#
# 用法:
#   bash test_mirrors.sh [--type docker|github|tools|all] [--output FILE] [--timeout 10] [--parallel 8]
#
# 示例:
#   bash test_mirrors.sh --type all --output /tmp/all.json --timeout 8 --parallel 16
#   bash test_mirrors.sh --type tools
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIRRORS_FILE="${SCRIPT_DIR}/references/mirrors.json"
TIMEOUT=10
PARALLEL=8
TEST_TYPE="all"
OUTPUT_FILE=""

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
        --help|-h)
            cat <<EOF
用法: $0 [--type docker|github|tools|all] [--output FILE] [--timeout SECONDS] [--parallel N]

  --type      分类: docker(社区+企业) | github | tools | all(默认)
  --output    结果 JSON 输出文件（默认 stdout）
  --timeout   curl 连接超时秒数（默认 10）
  --parallel  并发任务数（默认 8）
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
# 输出: name|url|time_ms|http_code|status
test_single() {
    local name="$1"
    local url="$2"
    local test_url="$3"

    # 无 test_url 的源跳过（不参与测速，保留原分）
    if [[ -z "$test_url" || "$test_url" == "null" ]]; then
        printf '%s|%s|0|0|skipped\n' "$name" "$url"
        return
    fi

    local result time_total http_code time_ms status="ok"
    result=$(curl -o /dev/null -s \
        -w '%{time_total}|%{http_code}' \
        --connect-timeout "$TIMEOUT" \
        --max-time "$((TIMEOUT * 3))" \
        "$test_url" 2>/dev/null || echo '0.00|000')

    time_total="${result%%|*}"
    http_code="${result##*|}"
    time_ms=$(awk -v t="$time_total" 'BEGIN { printf "%.0f", t * 1000 }')

    # 失败判定：连接失败 / 明确错误码 / 限流
    case "$http_code" in
        000|404|502|503|403|429) status="failed" ;;
    esac

    printf '%s|%s|%s|%s|%s\n' "$name" "$url" "$time_ms" "$http_code" "$status"
}
export -f test_single
export TIMEOUT

# ---- 取指定分类镜像列表 ----
# 输出每行: name|url|test_url
get_mirrors() {
    local category="$1"
    python3 -c "
import json, sys
with open('$MIRRORS_FILE') as f:
    data = json.load(f)
for m in data.get('mirrors', {}).get('$category', []):
    name = m.get('name', '')
    url = m.get('url', '') or ''
    test_url = m.get('test_url', '') or ''
    # 跳过无 test_url 的已弃用源；有 test_url 的保留以检测复活
    if m.get('status') == 'deprecated' and not test_url:
        continue
    print(f'{name}|{url}|{test_url}')
" 2>/dev/null
}

# ---- 并发测试一个分类，输出 JSON 片段到 stdout ----
test_category() {
    local category="$1"
    local tmpdir="$2"
    local list_file="${tmpdir}/${category}.list"
    local out_file="${tmpdir}/${category}.out"

    get_mirrors "$category" > "$list_file" || true
    [[ -s "$list_file" ]] || { echo "[]"; return; }

    # xargs -P 并发执行 test_single，结果写每行 "name|url|time|code|status"
    cat "$list_file" | xargs -P "$PARALLEL" -I{} bash -c '
        IFS="|" read -r n u t <<< "$1"
        test_single "$n" "$u" "$t"
    ' _ {} > "$out_file" 2>/dev/null || true

    # 用 Python 组装合法 JSON 数组（避免字符串拼接转义问题）
    python3 -c "
import json, sys
entries = []
with open('$out_file') as f:
    for line in f:
        line = line.rstrip('\n')
        if not line:
            continue
        parts = line.split('|')
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
"
}

# ================= 主流程 =================
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  accel-mirror 并发测速引擎${NC}"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo "  并发: ${PARALLEL}  |  超时: ${TIMEOUT}s  |  类型: ${TEST_TYPE}"
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
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

for cat in "${CATEGORIES[@]}"; do
    echo -e "${YELLOW}━━━ Testing ${cat} ━━━${NC}"
    test_category "$cat" "$TMPDIR" > /dev/null
    count=$(wc -l < "${TMPDIR}/${cat}.out" 2>/dev/null || echo 0)
    echo -e "  ${GREEN}✓${NC} ${cat}: ${count} sources"
    echo ""
done

# Python 统一组装最终 JSON（直接读 .out 管道文件，完全规避字符串插值/转义问题）
FINAL_JSON="$(python3 - "$TMPDIR" <<'PY'
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
            parts = line.rstrip('\n').split('|')
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