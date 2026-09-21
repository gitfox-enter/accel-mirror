#!/usr/bin/env python3
"""
update_mirrors.py — Mirror Score Update & Database Evolution Tool
================================================================
Reads test results from test_mirrors.sh output and updates mirrors.json
with fresh scores. Also supports adding/deprecating mirrors manually.

Usage:
    # Update scores from test results file
    python3 update_mirrors.py --input /tmp/mirror_results.json

    # Crowd-sourced aggregation: merge many anonymised reports, score by median
    python3 update_mirrors.py --aggregate reports/*.json --min-samples 3

    # Add a new mirror
    python3 update_mirrors.py --add --name "new-mirror" \\
        --url "https://example.com" --category docker_community \\
        --test-url "https://example.com/v2/" --notes "User reported"

    # Deprecate a mirror
    python3 update_mirrors.py --deprecate --name "dead-mirror"

    # Revive a deprecated mirror
    python3 update_mirrors.py --revive --name "restored-mirror"

    # Sort mirrors by score (no test data needed, just reorders)
    python3 update_mirrors.py --sort-only
"""

import json
import argparse
import math
import statistics
import sys
import os
from datetime import datetime
from pathlib import Path

# ---- Constants ----
SCRIPT_DIR = Path(__file__).resolve().parent.parent
MIRRORS_FILE = SCRIPT_DIR / "references" / "mirrors.json"


def set_mirrors_file(path):
    """Override the database path (used by --db, and by tests on a copy)."""
    global MIRRORS_FILE
    MIRRORS_FILE = Path(path).resolve()

# Categories that should be sorted by score
SORTED_CATEGORIES = [
    "docker_community",
    "docker_enterprise",
    "github",
    "tools",
    "ai_models",
    "python",
    "dev_registry",
]

# Failure threshold: after N consecutive failures, deprecate
FAILURE_THRESHOLD = 3


def load_mirrors():
    """Load the mirrors.json database."""
    with open(MIRRORS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_mirrors(data):
    """Save mirrors.json with sorted entries and updated metadata."""
    # Sort each category: score descending, then latency ascending as tie-breaker
    # (log-scale scoring means many fast mirrors share the same score; latency
    #  ordering keeps the top of the list genuinely fastest)
    for cat in SORTED_CATEGORIES:
        if cat in data.get("mirrors", {}):
            data["mirrors"][cat].sort(
                key=lambda x: (
                    -x.get("score", 0),
                    x["test_time_ms"] if isinstance(x.get("test_time_ms"), int) and x.get("test_time_ms", 0) > 0 else 10**9,
                )
            )

    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    with open(MIRRORS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ mirrors.json updated: {MIRRORS_FILE}")


def log_evolution(data, action, details):
    """Append an entry to the evolution_log."""
    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "action": action,
        "details": details,
    }
    if "evolution_log" not in data:
        data["evolution_log"] = []
    data["evolution_log"].append(entry)
    # Keep log to last 200 entries
    if len(data["evolution_log"]) > 200:
        data["evolution_log"] = data["evolution_log"][-200:]


def calculate_score(time_ms):
    """Calculate score from response time in milliseconds.

    Log-scale formula (v1.3.0):
        score = max(0, round(100 - 20 * log10(1 + time_s / 0.1)))

    Rationale: the old linear formula (100 - s*2) saturated the top of the
    scale — anything under ~500ms scored 99, hiding real differences between
    fast mirrors. The log scale spreads the useful range:
        100ms -> 94 | 300ms -> 89 | 500ms -> 84 | 1s -> 79
        3s -> 70    | 10s -> 60    | 30s -> 50
    """
    if time_ms is None or time_ms <= 0:
        return 0
    time_s = time_ms / 1000.0
    score = max(0, round(100 - 20 * math.log10(1 + time_s / 0.1)))
    return score


def update_scores(data, test_results):
    """Update mirror scores based on test results."""
    results = test_results.get("results", {})
    updated_count = 0
    failed_count = 0

    for category_name, category_results in results.items():
        if category_name not in data.get("mirrors", {}):
            continue

        # Build a lookup: name -> result
        result_map = {r["name"]: r for r in category_results}

        for mirror in data["mirrors"][category_name]:
            name = mirror.get("name", "")
            if name not in result_map:
                continue

            result = result_map[name]
            status = result.get("status", "")
            time_ms = result.get("time_ms", 0)

            if status == "skipped":
                continue

            if status == "ok":
                new_score = calculate_score(time_ms)
                old_score = mirror.get("score", 0)
                mirror["score"] = new_score
                mirror["last_tested"] = datetime.now().strftime("%Y-%m-%d")
                mirror["test_time_ms"] = time_ms
                # Throughput (bytes/s) from --deep mode, if present
                speed = result.get("speed_bps")
                if isinstance(speed, (int, float)) and speed > 0:
                    mirror["throughput_bps"] = int(speed)
                if mirror.get("status") == "deprecated":
                    # Revive
                    mirror["status"] = "active"
                    print(f"  🔄 Revived: {name} (score: {old_score} → {new_score})")
                else:
                    score_change = new_score - old_score
                    arrow = "↑" if score_change > 0 else ("↓" if score_change < 0 else "=")
                    print(f"  {arrow} {name}: {old_score} → {new_score} ({time_ms}ms)")
                updated_count += 1

            elif status == "failed":
                # Track consecutive failures
                failures = mirror.get("consecutive_failures", 0) + 1
                mirror["consecutive_failures"] = failures

                if failures >= FAILURE_THRESHOLD and mirror.get("status") != "deprecated":
                    mirror["status"] = "deprecated"
                    mirror["score"] = 0
                    print(f"  🗑️ Deprecated: {name} (failed {failures} consecutive tests)")
                    log_evolution(data, "deprecated",
                                  f"Mirror '{name}' deprecated after {failures} consecutive failures")
                else:
                    print(f"  ⚠️ Failed: {name} (failure #{failures})")
                failed_count += 1

    # Update last_full_test timestamp
    data["last_full_test"] = datetime.now().strftime("%Y-%m-%d")

    log_evolution(data, "tested",
                  f"Updated scores: {updated_count} mirrors updated, {failed_count} failed")
    print(f"\n📊 Summary: {updated_count} updated, {failed_count} failed")
    return updated_count, failed_count


def add_mirror(data, name, url, category, test_url=None, notes="", score=50):
    """Add a new mirror to the database."""
    if category not in data.get("mirrors", {}):
        print(f"❌ Invalid category: {category}")
        print(f"   Valid categories: {', '.join(SORTED_CATEGORIES)}")
        return False

    # Check for duplicate
    for mirror in data["mirrors"][category]:
        if mirror.get("name") == name:
            print(f"⚠️ Mirror '{name}' already exists in {category}")
            return False

    new_entry = {
        "name": name,
        "url": url,
        "test_url": test_url if test_url else None,
        "score": score,
        "last_tested": None,
        "test_time_ms": None,
        "status": "active",
        "notes": notes,
    }

    data["mirrors"][category].append(new_entry)
    log_evolution(data, "added",
                  f"Added mirror '{name}' to {category} (url: {url}, initial score: {score})")
    print(f"✅ Added: {name} → {category} (score: {score})")
    return True


def deprecate_mirror(data, name):
    """Mark a mirror as deprecated."""
    for category in SORTED_CATEGORIES:
        for mirror in data["mirrors"].get(category, []):
            if mirror.get("name") == name:
                mirror["status"] = "deprecated"
                mirror["score"] = 0
                log_evolution(data, "deprecated",
                              f"Manually deprecated mirror '{name}'")
                print(f"🗑️ Deprecated: {name}")
                return True
    print(f"❌ Mirror '{name}' not found in any category")
    return False


def revive_mirror(data, name):
    """Restore a deprecated mirror to active status with neutral score."""
    for category in SORTED_CATEGORIES:
        for mirror in data["mirrors"].get(category, []):
            if mirror.get("name") == name:
                mirror["status"] = "active"
                mirror["score"] = 50  # Neutral, needs retesting
                mirror["consecutive_failures"] = 0
                log_evolution(data, "revived",
                              f"Manually revived mirror '{name}' (score reset to 50)")
                print(f"🔄 Revived: {name} (score: 50, needs retesting)")
                return True
    print(f"❌ Mirror '{name}' not found in any category")
    return False


def sort_only(data):
    """Just sort all categories by score and save."""
    log_evolution(data, "sort_only", "Re-sorted all mirrors by score")
    print("📊 Sorted all mirrors by score (descending)")


def record_alive(data, test_results):
    """Record a CI survival snapshot WITHOUT touching scores.

    CI runs on GitHub datacenter networks, which differ from real user
    networks — so CI results must never feed the score. But they are still
    a useful 'last confirmed alive' signal: each mirror that responded ok
    gets `last_ci_alive` stamped. Scores stay untouched.
    """
    results = test_results.get("results", {})
    alive = 0
    total = 0
    for category_name, category_results in results.items():
        if category_name not in data.get("mirrors", {}):
            continue
        result_map = {r["name"]: r for r in category_results}
        for mirror in data["mirrors"][category_name]:
            name = mirror.get("name", "")
            if name not in result_map:
                continue
            total += 1
            if result_map[name].get("status") == "ok":
                mirror["last_ci_alive"] = datetime.now().strftime("%Y-%m-%d")
                alive += 1

    data["last_ci_test"] = datetime.now().strftime("%Y-%m-%d")
    data["last_ci_alive_count"] = alive
    log_evolution(data, "ci_alive_check",
                  f"CI survival snapshot: {alive}/{total} mirrors responded ok "
                  f"(scores untouched, CI data never writes back scores)")
    print(f"🛰️ CI survival snapshot: {alive}/{total} alive (scores untouched)")
    return alive, total


def rescore(data):
    """Recompute all scores from stored test_time_ms using the current formula.

    Use this after changing the scoring formula so the database stays
    consistent without waiting for a full re-test.
    """
    updated = 0
    for cat in SORTED_CATEGORIES:
        for mirror in data.get("mirrors", {}).get(cat, []):
            t = mirror.get("test_time_ms")
            if isinstance(t, int) and t > 0 and mirror.get("status") == "active":
                new_score = calculate_score(t)
                if new_score != mirror.get("score"):
                    mirror["score"] = new_score
                    updated += 1
    log_evolution(data, "rescored",
                  f"Recomputed scores from stored latency with current formula "
                  f"({updated} mirrors changed)")
    print(f"🧮 Rescored: {updated} mirrors updated from stored test_time_ms")
    return updated


def aggregate_reports(data, report_paths, min_samples=1):
    """Merge many anonymised test reports and rescore by MEDIAN.

    Why median instead of mean: one report from a bad network (or a mirror that
    answered in 30s exactly once) would drag a mean; the median of N independent
    reports is the robust "group consensus" and is what makes the score
    meaningful to somebody who has never run the test themselves.

    Reports are `test_mirrors.sh --output X.json` outputs, ideally
    contributed via GitHub Issues. Only latency + status are read — those files
    contain no IP / path / user id (see their `meta.privacy` field).

    Mirrors that only ever failed are deprecated, but only when they failed in
    at least FAILURE_THRESHOLD reports AND never succeeded in any of them.
    """
    reports = []
    for p in report_paths:
        if not os.path.exists(p):
            print(f"  ⚠️ 跳过不存在的上报文件: {p}")
            continue
        with open(p, "r", encoding="utf-8") as f:
            reports.append((p, json.load(f)))
    if not reports:
        print("❌ 没有可读取的上报文件")
        return 0, 0, 0

    samples = {}    # (category, name) -> [ms, ...]
    failures = {}   # (category, name) -> 失败次数
    labels = []
    for _, rep in reports:
        label = str((rep.get("meta") or {}).get("network_label") or "").strip()
        if label and label not in labels:
            labels.append(label)
        for cat, rows in (rep.get("results") or {}).items():
            for row in rows or []:
                key = (cat, row.get("name"))
                t = row.get("time_ms")
                if row.get("status") == "ok" and isinstance(t, int) and t > 0:
                    samples.setdefault(key, []).append(t)
                elif row.get("status") == "failed":
                    failures[key] = failures.get(key, 0) + 1

    print(f"📥 读取上报: {len(reports)} 份"
          + (f"（网络标签: {', '.join(labels[:8])}{'…' if len(labels) > 8 else ''}）" if labels else ""))

    # ---- 1) 有成功样本的源：按中位数重算 ----
    updated = skipped = 0
    movers = []
    for cat in SORTED_CATEGORIES:
        for mirror in data.get("mirrors", {}).get(cat, []):
            key = (cat, mirror.get("name", ""))
            times = samples.get(key, [])
            if len(times) < min_samples:
                # 只在「有样本但不够」时计入 skipped；纯失败记录另算
                if key in samples:
                    skipped += 1
                continue
            median = int(statistics.median(times))
            old_score = mirror.get("score", 0)
            new_score = calculate_score(median)
            mirror["score"] = new_score
            mirror["test_time_ms"] = median
            mirror["samples"] = len(times)
            mirror["latency_min_ms"] = min(times)
            mirror["latency_max_ms"] = max(times)
            mirror["last_tested"] = datetime.now().strftime("%Y-%m-%d")
            if mirror.get("status") == "deprecated":
                mirror["status"] = "active"
                mirror["consecutive_failures"] = 0
                print(f"  🔄 复活: {key[1]}（{len(times)} 份上报中位数 {median}ms）")
            updated += 1
            if new_score != old_score:
                movers.append((old_score, new_score, key[1], median, len(times)))
            else:
                movers.append((old_score, new_score, key[1], median, len(times)))

    # ---- 2) 失败记录：有过成功就不弃用，但把失败次数照记下来 ----
    # 「既能成功又偶尔失败」说明源不稳定，这是有价值的信号，不能因为
    # 有成功样本就把失败次数丢掉。只有在「零成功 且 失败达到阈值」时才弃用。
    fail_deprecated = 0
    flaky = 0
    for cat in SORTED_CATEGORIES:
        for mirror in data.get("mirrors", {}).get(cat, []):
            key = (cat, mirror.get("name", ""))
            fails = failures.get(key, 0)
            if not fails:
                continue
            mirror["failed_reports"] = fails
            has_success = bool(samples.get(key))
            if has_success:
                if fails >= FAILURE_THRESHOLD:
                    flaky += 1
                continue
            if fails < FAILURE_THRESHOLD:
                flaky += 1
                continue
            if mirror.get("status") != "deprecated":
                mirror["status"] = "deprecated"
                mirror["score"] = 0
                mirror["consecutive_failures"] = fails
                print(f"  🗑️ 弃用: {key[1]}（{fails}/{len(reports)} 份上报全部失败，无任何成功记录）")
                log_evolution(
                    data, "deprecated",
                    f"'{key[1]}' deprecated: failed in {fails}/{len(reports)} crowd reports "
                    f"with zero successes")
                fail_deprecated += 1

    # ---- 3) 记录汇总，便于追溯数据可信度 ----
    data["last_full_test"] = datetime.now().strftime("%Y-%m-%d")
    data["crowd"] = {
        "reports": len(reports),
        "network_labels": labels[:20],
        "aggregated_at": datetime.now().strftime("%Y-%m-%d"),
        "min_samples": min_samples,
        "method": "median of per-report latency (robust to single-network outliers)",
        "updated_mirrors": updated,
        "skipped_mirrors": skipped,
        "deprecated_mirrors": fail_deprecated,
    }
    log_evolution(
        data, "crowd_aggregated",
        f"Merged {len(reports)} crowd report(s)"
        + (f" [labels: {', '.join(labels[:8])}]" if labels else "")
        + f": {updated} mirrors rescored by median (min_samples={min_samples}), "
          f"{skipped} skipped, {fail_deprecated} deprecated, {flaky} flaky-only")

    print(f"\n📊 聚合结果: {updated} 个源按中位数重算, {skipped} 个样本不足被跳过, "
          f"{fail_deprecated} 个被弃用"
          + (f", {flaky} 个在部分上报中失败但未达阈值（只记录不扣分）" if flaky else ""))
    if movers:
        print("\n  变化最大的 10 个（旧分 → 新分 | 中位延迟 | 样本数）:")
        for old, new, name, median, n in sorted(
                movers, key=lambda x: -abs(x[1] - x[0]))[:10]:
            print(f"    {old:3d} → {new:3d}  {name}  ({median}ms, {n} 份)")
    return updated, fail_deprecated, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Update mirror scores and manage the mirror database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --input /tmp/results.json
  %(prog)s --aggregate reports/*.json --min-samples 3
  %(prog)s --add --name "new-mirror" --url "https://example.com" --category docker_community
  %(prog)s --deprecate --name "dead-mirror"
  %(prog)s --revive --name "restored-mirror"
  %(prog)s --sort-only
        """,
    )

    parser.add_argument("--input", "-i", help="Path to test results JSON file")
    parser.add_argument("--aggregate", nargs="+", metavar="REPORT",
                        help="合并多份匿名上报（test_mirrors.sh 的输出）并取中位数重算分数")
    parser.add_argument("--min-samples", type=int, default=1,
                        help="配合 --aggregate: 一个源至少被几份上报覆盖才重算（默认 1）")
    parser.add_argument("--db", help="覆盖 mirrors.json 路径（默认 references/mirrors.json）")
    parser.add_argument("--add", action="store_true", help="Add a new mirror")
    parser.add_argument("--deprecate", action="store_true", help="Deprecate a mirror")
    parser.add_argument("--revive", action="store_true", help="Revive a deprecated mirror")
    parser.add_argument("--sort-only", action="store_true", help="Just sort by score and save")
    parser.add_argument("--record-alive", action="store_true",
                        help="With --input: record CI survival snapshot (last_ci_alive) only; scores untouched")
    parser.add_argument("--rescore", action="store_true",
                        help="Recompute all scores from stored test_time_ms with the current formula")
    parser.add_argument("--name", help="Mirror name (for --add/--deprecate/--revive)")
    parser.add_argument("--url", help="Mirror URL (for --add)")
    parser.add_argument("--category", help="Mirror category (for --add)")
    parser.add_argument("--test-url", help="Test URL for curl testing (for --add)")
    parser.add_argument("--notes", default="", help="Notes about the mirror (for --add)")
    parser.add_argument("--score", type=int, default=50, help="Initial score (for --add, default 50)")

    args = parser.parse_args()

    # 允许用 --db 指向别的数据库（测试时对副本操作，不动真库）
    if args.db:
        set_mirrors_file(args.db)

    # Load database
    if not MIRRORS_FILE.exists():
        print(f"❌ mirrors.json not found at {MIRRORS_FILE}")
        sys.exit(1)

    data = load_mirrors()

    # Handle different modes
    if args.aggregate:
        print(f"👥 众包聚合: {len(args.aggregate)} 份上报, min_samples={args.min_samples}\n")
        aggregate_reports(data, args.aggregate, args.min_samples)

    elif args.input:
        if not os.path.exists(args.input):
            print(f"❌ Test results file not found: {args.input}")
            sys.exit(1)
        with open(args.input, "r", encoding="utf-8") as f:
            test_results = json.load(f)
        if args.record_alive:
            print("🛰️ Recording CI survival snapshot (scores untouched)...\n")
            record_alive(data, test_results)
        else:
            print("📝 Updating mirror scores from test results...\n")
            update_scores(data, test_results)

    elif args.rescore:
        rescore(data)

    elif args.add:
        if not args.name or not args.url or not args.category:
            print("❌ --add requires --name, --url, and --category")
            sys.exit(1)
        add_mirror(data, args.name, args.url, args.category,
                   args.test_url, args.notes, args.score)

    elif args.deprecate:
        if not args.name:
            print("❌ --deprecate requires --name")
            sys.exit(1)
        deprecate_mirror(data, args.name)

    elif args.revive:
        if not args.name:
            print("❌ --revive requires --name")
            sys.exit(1)
        revive_mirror(data, args.name)

    elif args.sort_only:
        sort_only(data)

    else:
        parser.print_help()
        sys.exit(0)

    # Save
    save_mirrors(data)

    # Print top mirrors per category
    print("\n" + "=" * 60)
    print("📊 Top Mirrors by Category:")
    print("=" * 60)
    for cat in SORTED_CATEGORIES:
        mirrors = data.get("mirrors", {}).get(cat, [])
        if not mirrors:
            continue
        print(f"\n  [{cat}]")
        for m in mirrors[:5]:
            if m.get("status") == "deprecated":
                continue
            latency = m.get("test_time_ms")
            latency_str = f" ({latency}ms)" if isinstance(latency, int) and latency > 0 else ""
            print(f"    {m['score']:3d} │ {m['name']}{latency_str}")
    print()


if __name__ == "__main__":
    main()
