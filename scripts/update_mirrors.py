#!/usr/bin/env python3
"""
update_mirrors.py — Mirror Score Update & Database Evolution Tool
================================================================
Reads test results from test_mirrors.sh output and updates mirrors.json
with fresh scores. Also supports adding/deprecating mirrors manually.

Usage:
    # Update scores from test results file
    python3 update_mirrors.py --input /tmp/mirror_results.json

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
import sys
import os
from datetime import datetime
from pathlib import Path

# ---- Constants ----
SCRIPT_DIR = Path(__file__).resolve().parent.parent
MIRRORS_FILE = SCRIPT_DIR / "references" / "mirrors.json"

# Categories that should be sorted by score
SORTED_CATEGORIES = ["docker_community", "docker_enterprise", "github", "tools"]

# Failure threshold: after N consecutive failures, deprecate
FAILURE_THRESHOLD = 3


def load_mirrors():
    """Load the mirrors.json database."""
    with open(MIRRORS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_mirrors(data):
    """Save mirrors.json with sorted entries and updated metadata."""
    # Sort each category by score (descending)
    for cat in SORTED_CATEGORIES:
        if cat in data.get("mirrors", {}):
            data["mirrors"][cat].sort(key=lambda x: x.get("score", 0), reverse=True)

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
    Formula: score = max(0, round(100 - (time_ms / 1000) * 2))
    """
    if time_ms is None or time_ms == 0:
        return 0
    time_s = time_ms / 1000.0
    score = max(0, round(100 - time_s * 2))
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


def main():
    parser = argparse.ArgumentParser(
        description="Update mirror scores and manage the mirror database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --input /tmp/results.json
  %(prog)s --add --name "new-mirror" --url "https://example.com" --category docker_community
  %(prog)s --deprecate --name "dead-mirror"
  %(prog)s --revive --name "restored-mirror"
  %(prog)s --sort-only
        """,
    )

    parser.add_argument("--input", "-i", help="Path to test results JSON file")
    parser.add_argument("--add", action="store_true", help="Add a new mirror")
    parser.add_argument("--deprecate", action="store_true", help="Deprecate a mirror")
    parser.add_argument("--revive", action="store_true", help="Revive a deprecated mirror")
    parser.add_argument("--sort-only", action="store_true", help="Just sort by score and save")
    parser.add_argument("--name", help="Mirror name (for --add/--deprecate/--revive)")
    parser.add_argument("--url", help="Mirror URL (for --add)")
    parser.add_argument("--category", help="Mirror category (for --add)")
    parser.add_argument("--test-url", help="Test URL for curl testing (for --add)")
    parser.add_argument("--notes", default="", help="Notes about the mirror (for --add)")
    parser.add_argument("--score", type=int, default=50, help="Initial score (for --add, default 50)")

    args = parser.parse_args()

    # Load database
    if not MIRRORS_FILE.exists():
        print(f"❌ mirrors.json not found at {MIRRORS_FILE}")
        sys.exit(1)

    data = load_mirrors()

    # Handle different modes
    if args.input:
        # Update from test results
        if not os.path.exists(args.input):
            print(f"❌ Test results file not found: {args.input}")
            sys.exit(1)
        with open(args.input, "r", encoding="utf-8") as f:
            test_results = json.load(f)
        print("📝 Updating mirror scores from test results...\n")
        update_scores(data, test_results)

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
            print(f"    {m['score']:3d} │ {m['name']}")
    print()


if __name__ == "__main__":
    main()
