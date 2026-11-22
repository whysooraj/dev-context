#!/usr/bin/env python3
"""
Benchmark suite for dev-context core engine.
Generates temporary mock git repositories (10, 50, 100 repos with commits and dirty states)
and benchmarks scan latency, reporting statistical metrics (min, max, mean, p95).
"""

import os
import sys
import time
import math
import argparse
import tempfile
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import scan_repositories


def create_single_repo(path, num_commits=1, dirty=False):
    """Create a single mock repository with commit history and dirty status."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "Bench User"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "bench@example.com"], check=True)

    for i in range(num_commits):
        fname = f"file_{i}.txt"
        with open(os.path.join(path, fname), "w") as f:
            f.write(f"Commit contents {i}\n")
        subprocess.run(["git", "-C", path, "add", fname], check=True)
        subprocess.run(["git", "-C", path, "commit", "-q", "-m", f"Commit {i} in {os.path.basename(path)}"], check=True)

    if dirty:
        # Create uncommitted dirty file
        with open(os.path.join(path, "uncommitted.txt"), "w") as f:
            f.write("uncommitted work in progress\n")


def generate_mock_environment(base_dir, total_repos):
    """
    Generate total_repos mock repositories inside base_dir.
    Distributes repos across depths 1, 2, and 3, creates worktrees,
    sets dirty states, and populates skip directories (e.g. node_modules).
    """
    repo_configs = []
    # Reserve ~15% for worktrees from regular repos
    wt_count = max(1, int(total_repos * 0.15)) if total_repos >= 10 else 0
    regular_count = total_repos - wt_count

    for i in range(regular_count):
        depth_mod = i % 3
        if depth_mod == 0:
            rel_path = f"repo_{i}"
        elif depth_mod == 1:
            rel_path = os.path.join(f"group_{i % 4}", f"repo_{i}")
        else:
            rel_path = os.path.join("org", f"team_{i % 3}", f"repo_{i}")

        full_path = os.path.join(base_dir, rel_path)
        dirty = (i % 3 == 0)  # ~33% dirty
        repo_configs.append((full_path, dirty))

    # Create regular repos in parallel
    workers = min(32, max(4, os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(create_single_repo, path, num_commits=1, dirty=dirty)
            for path, dirty in repo_configs
        ]
        for f in futures:
            f.result()

    # Create worktrees linked to existing repos
    created_wt = 0
    for idx in range(wt_count):
        source_repo = repo_configs[idx % len(repo_configs)][0]
        wt_rel = os.path.join("worktrees", f"wt_{idx}")
        wt_path = os.path.join(base_dir, wt_rel)
        branch_name = f"feat-wt-{idx}"
        try:
            subprocess.run(
                ["git", "-C", source_repo, "worktree", "add", "-q", wt_path, "-b", branch_name],
                check=True,
                capture_output=True
            )
            # Make half of worktrees dirty
            if idx % 2 == 0:
                with open(os.path.join(wt_path, "wt_dirty.txt"), "w") as f:
                    f.write("dirty worktree file\n")
            created_wt += 1
        except Exception:
            # Fallback to standard repo if worktree creation fails
            create_single_repo(wt_path, num_commits=1, dirty=(idx % 2 == 0))
            created_wt += 1

    # Add realistic skip directories with files to test skipping efficiency
    for skip_dir_name in ["node_modules", ".cache", "build", "target"]:
        skip_path = os.path.join(base_dir, skip_dir_name)
        os.makedirs(os.path.join(skip_path, "sub_pkg"), exist_ok=True)
        with open(os.path.join(skip_path, "dummy.json"), "w") as f:
            f.write("{}\n")


def compute_p95(values):
    """Compute 95th percentile using linear interpolation."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n == 1:
        return sorted_v[0]
    rank = 0.95 * (n - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    weight = rank - lower
    return sorted_v[lower] * (1.0 - weight) + sorted_v[upper] * weight


def benchmark_scale(repo_count, iterations=10, max_workers=None):
    """Benchmark scan latency for a specific repository count."""
    print(f"Generating {repo_count} mock repositories...", end="", flush=True)
    t_gen_start = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_dir:
        generate_mock_environment(temp_dir, repo_count)
        t_gen_end = time.perf_counter()
        print(f" done in {(t_gen_end - t_gen_start):.2f}s.")

        # Warm-up run
        scan_repositories(temp_dir, max_depth=3, max_workers=max_workers)

        latencies_ms = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            results = scan_repositories(temp_dir, max_depth=3, max_workers=max_workers)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000.0)

        min_ms = min(latencies_ms)
        max_ms = max(latencies_ms)
        mean_ms = sum(latencies_ms) / len(latencies_ms)
        p95_ms = compute_p95(latencies_ms)
        discovered = len(results)

        return {
            "count": repo_count,
            "discovered": discovered,
            "iterations": iterations,
            "min_ms": min_ms,
            "max_ms": max_ms,
            "mean_ms": mean_ms,
            "p95_ms": p95_ms,
        }


def print_table(results):
    """Format and print benchmark statistics in a clean ASCII table."""
    print("\n" + "=" * 74)
    print("dev-context Core Engine Scan Latency Benchmark")
    print("=" * 74)
    header = f"{'Repos':>7} | {'Found':>6} | {'Min (ms)':>10} | {'Mean (ms)':>10} | {'p95 (ms)':>10} | {'Max (ms)':>10} | {'Runs':>5}"
    print(header)
    print("-" * 74)
    for r in results:
        row = (
            f"{r['count']:>7} | "
            f"{r['discovered']:>6} | "
            f"{r['min_ms']:>10.2f} | "
            f"{r['mean_ms']:>10.2f} | "
            f"{r['p95_ms']:>10.2f} | "
            f"{r['max_ms']:>10.2f} | "
            f"{r['iterations']:>5}"
        )
        print(row)
    print("=" * 74 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Benchmark dev-context scan engine latency.")
    parser.add_argument(
        "--scales",
        nargs="+",
        type=int,
        default=[10, 50, 100],
        help="List of repository counts to benchmark (default: 10 50 100)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of scan iterations per scale (default: 10)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Maximum thread pool workers (default: auto)",
    )
    args = parser.parse_args()

    results = []
    for count in args.scales:
        stat = benchmark_scale(count, iterations=args.iterations, max_workers=args.workers)
        results.append(stat)

    print_table(results)


if __name__ == "__main__":
    main()
