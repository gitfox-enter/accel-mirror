#!/bin/bash
# =============================================================================
# test_mirrors.sh — Docker & GitHub Mirror Speed/Availability Tester
# =============================================================================
# Tests mirror availability and response time using curl.
# Outputs JSON results that can be consumed by update_mirrors.py.
#
# Requirements: curl, python3 (for JSON parsing), awk
# Usage:
#   bash test_mirrors.sh [--type docker|github|all] [--output FILE] [--timeout 10]
#
# Example:
#   bash test_mirrors.sh --type all --output /tmp/mirror_results.json
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIRRORS_FILE="${SCRIPT_DIR}/references/mirrors.json"
TIMEOUT=10
TEST_TYPE="all"
OUTPUT_FILE=""
GITHUB_TEST_FILE="https://raw.githubusercontent.com/octocat/Hello-World/master/README"

# ---- Color codes for pretty output ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- Parse arguments ----
while [[ $# -gt 0 ]]; do
    case $1 in
        --type)
            TEST_TYPE="$2"; shift 2 ;;
        --output)
            OUTPUT_FILE="$2"; shift 2 ;;
        --timeout)
            TIMEOUT="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--type docker|github|all] [--output FILE] [--timeout SECONDS]"
            echo ""
            echo "Options:"
            echo "  --type     Test category: docker (Docker mirrors), github (GitHub proxies), all (default)"
            echo "  --output   Write JSON results to FILE (default: stdout)"
            echo "  --timeout  Connection timeout in seconds (default: 10)"
            exit 0 ;;
        *)
            echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---- Check dependencies ----
if ! command -v curl &>/dev/null; then
    echo "Error: curl is required but not found." >&2
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is required but not found." >&2
    exit 1
fi

if [[ ! -f "$MIRRORS_FILE" ]]; then
    echo "Error: mirrors.json not found at $MIRRORS_FILE" >&2
    exit 1
fi

# ---- Helper: test a single URL ----
# Outputs: name|url|time_ms|http_code|status
test_single() {
    local name="$1"
    local url="$2"
    local test_url="$3"

    if [[ -z "$test_url" || "$test_url" == "null" ]]; then
        printf "%s|%s|0|0|skipped\n" "$name" "$url"
        return
    fi

    # Use curl's built-in timing
    local result
    result=$(curl -o /dev/null -s \
        -w "%{time_total}|%{http_code}" \
        --connect-timeout "$TIMEOUT" \
        --max-time "$((TIMEOUT * 3))" \
        "$test_url" 2>/dev/null || echo "0.00|000")

    local time_total="${result%%|*}"
    local http_code="${result##*|}"

    # Convert time_total (seconds, float) to milliseconds (integer)
    local time_ms
    time_ms=$(awk -v t="$time_total" 'BEGIN { printf "%.0f", t * 1000 }')

    # Determine status
    local status="ok"
    if [[ "$http_code" == "000" ]]; then
        status="failed"
    elif [[ "$http_code" == "404" ]]; then
        status="failed"
    elif [[ "$http_code" == "502" || "$http_code" == "503" ]]; then
        status="failed"
    fi

    printf "%s|%s|%s|%s|%s\n" "$name" "$url" "$time_ms" "$http_code" "$status"
}

# ---- Helper: get mirrors from JSON ----
get_mirrors() {
    local category="$1"
    python3 -c "
import json, sys
with open('$MIRRORS_FILE') as f:
    data = json.load(f)
for m in data.get('mirrors', {}).get('$category', []):
    name = m.get('name', '')
    url = m.get('url', '')
    test_url = m.get('test_url', '')
    if test_url is None:
        test_url = ''
    # Skip deprecated mirrors unless they have a test_url (to check revival)
    if m.get('status') == 'deprecated' and not test_url:
        continue
    print(f'{name}|{url}|{test_url}')
" 2>/dev/null
}

# ---- Main test runner ----
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   Mirror Speed & Availability Tester              ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Timeout: ${TIMEOUT}s  |  Type: ${TEST_TYPE}  |  Database: ${MIRRORS_FILE}"
echo ""

# Prepare JSON output
JSON_RESULT='{"test_time":"'$(date -Iseconds)'","results":{'
FIRST_CATEGORY=1

# ---- Test Docker mirrors ----
if [[ "$TEST_TYPE" == "docker" || "$TEST_TYPE" == "all" ]]; then
    echo -e "${YELLOW}━━━ Testing Docker Community Mirrors ━━━${NC}"

    if [[ $FIRST_CATEGORY -eq 0 ]]; then
        JSON_RESULT+=','
    fi
    FIRST_CATEGORY=0
    JSON_RESULT+='"docker_community":['

    first_entry=1
    while IFS='|' read -r name url test_url; do
        [[ -z "$name" ]] && continue

        result_line=$(test_single "$name" "$url" "$test_url")
        IFS='|' read -r r_name r_url r_time r_code r_status <<< "$result_line"

        # Pretty print
        if [[ "$r_status" == "ok" ]]; then
            printf "  ${GREEN}✓${NC} %-35s  %5sms  HTTP %s\n" "$r_name" "$r_time" "$r_code"
        elif [[ "$r_status" == "skipped" ]]; then
            printf "  ${YELLOW}⊘${NC} %-35s  (no test URL)\n" "$r_name"
        else
            printf "  ${RED}✗${NC} %-35s  FAILED  HTTP %s\n" "$r_name" "$r_code"
        fi

        # Build JSON
        if [[ $first_entry -eq 0 ]]; then
            JSON_RESULT+=','
        fi
        first_entry=0
        JSON_RESULT+="{\"name\":\"$r_name\",\"url\":\"$r_url\",\"time_ms\":$r_time,\"http_code\":\"$r_code\",\"status\":\"$r_status\"}"

    done < <(get_mirrors "docker_community")

    JSON_RESULT+=']'

    # Also test enterprise mirrors
    echo ""
    echo -e "${YELLOW}━━━ Testing Docker Enterprise Mirrors ━━━${NC}"
    JSON_RESULT+=',"docker_enterprise":['
    first_entry=1
    while IFS='|' read -r name url test_url; do
        [[ -z "$name" ]] && continue
        result_line=$(test_single "$name" "$url" "$test_url")
        IFS='|' read -r r_name r_url r_time r_code r_status <<< "$result_line"
        if [[ "$r_status" == "ok" ]]; then
            printf "  ${GREEN}✓${NC} %-35s  %5sms  HTTP %s\n" "$r_name" "$r_time" "$r_code"
        elif [[ "$r_status" == "skipped" ]]; then
            printf "  ${YELLOW}⊘${NC} %-35s  (no test URL)\n" "$r_name"
        else
            printf "  ${RED}✗${NC} %-35s  FAILED  HTTP %s\n" "$r_name" "$r_code"
        fi
        if [[ $first_entry -eq 0 ]]; then JSON_RESULT+=','; fi
        first_entry=0
        JSON_RESULT+="{\"name\":\"$r_name\",\"url\":\"$r_url\",\"time_ms\":$r_time,\"http_code\":\"$r_code\",\"status\":\"$r_status\"}"
    done < <(get_mirrors "docker_enterprise")
    JSON_RESULT+=']'
fi

# ---- Test GitHub mirrors ----
if [[ "$TEST_TYPE" == "github" || "$TEST_TYPE" == "all" ]]; then
    echo ""
    echo -e "${YELLOW}━━━ Testing GitHub Mirrors ━━━${NC}"

    if [[ $FIRST_CATEGORY -eq 0 ]]; then
        JSON_RESULT+=','
    fi
    FIRST_CATEGORY=0
    JSON_RESULT+='"github":['

    first_entry=1
    while IFS='|' read -r name url test_url; do
        [[ -z "$name" ]] && continue
        result_line=$(test_single "$name" "$url" "$test_url")
        IFS='|' read -r r_name r_url r_time r_code r_status <<< "$result_line"
        if [[ "$r_status" == "ok" ]]; then
            printf "  ${GREEN}✓${NC} %-35s  %5sms  HTTP %s\n" "$r_name" "$r_time" "$r_code"
        elif [[ "$r_status" == "skipped" ]]; then
            printf "  ${YELLOW}⊘${NC} %-35s  (no test URL)\n" "$r_name"
        else
            printf "  ${RED}✗${NC} %-35s  FAILED  HTTP %s\n" "$r_name" "$r_code"
        fi
        if [[ $first_entry -eq 0 ]]; then JSON_RESULT+=','; fi
        first_entry=0
        JSON_RESULT+="{\"name\":\"$r_name\",\"url\":\"$r_url\",\"time_ms\":$r_time,\"http_code\":\"$r_code\",\"status\":\"$r_status\"}"
    done < <(get_mirrors "github")
    JSON_RESULT+=']'
fi

JSON_RESULT+='}}'

# ---- Output results ----
echo ""
if [[ -n "$OUTPUT_FILE" ]]; then
    echo "$JSON_RESULT" | python3 -m json.tool > "$OUTPUT_FILE" 2>/dev/null || echo "$JSON_RESULT" > "$OUTPUT_FILE"
    echo -e "${GREEN}Results saved to: ${OUTPUT_FILE}${NC}"
else
    echo "$JSON_RESULT" | python3 -m json.tool 2>/dev/null || echo "$JSON_RESULT"
fi

echo -e "${CYAN}Test complete.${NC}"
