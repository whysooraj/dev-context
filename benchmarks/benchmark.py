#!/usr/bin/env python3
"""
Comprehensive Benchmark & Stress Test Suite for dev-context Core Engine.
Evaluates repository discovery, parallel git inspection, cache warming,
percentile latency distribution (Min, Mean, P50, P95, P99, Max),
and timeout resilience against unresponsive / hanging git subprocesses.
"""

import os
import sys
import time
import math
import argparse
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import scan_repositories, find_git_repos, get_git_info


def create_repo(path, num_commits=1, num_untracked=0, num_modified=0):
    """
    Generate a mock repository with customizable commit count,
    modified files, and untracked files.
    """
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    author_args = ["-c", "user.name=Benchmarker", "-c", "user.email=bench@example.com"]

    # Generate initial commit or multiple commits
    for c in range(max(1, num_commits)):
        fname = f"tracked_{c}.txt"
        fpath = os.path.join(path, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(f"Commit level {c} data for {os.path.basename(path)}\n")
        subprocess.run(["git", "-C", path, "add", fname], check=True)
        subprocess.run(
            ["git", "-C", path, *author_args, "commit", "-q", "-m", f"feat: commit #{c} in {os.path.basename(path)}"],
            check=True,
        )

    # Generate modified tracked files
    for m in range(num_modified):
        target_f = f"tracked_{m % max(1, num_commits)}.txt"
        target_path = os.path.join(path, target_f)
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(f"modified line {m}\n")

    # Generate untracked files in bulk
    for u in range(num_untracked):
        u_file = os.path.join(path, f"untracked_{u}.tmp")
        with open(u_file, "w", encoding="utf-8") as f:
            f.write(f"untracked payload {u}\n")


def generate_mock_environment(base_dir, total_repos):
    """
    Generate diverse mix of total_repos repositories in base_dir:
    - Depths 1, 2, and 3 nested hierarchies
    - Git worktrees (~15%)
    - Repos with large file changes (hundreds of modified/untracked files, ~10%)
    - Repos with multiple commits (2-5 commits, ~20%)
    - Dirty repos (~30%)
    - Realistic skip directories (node_modules, target, .venv, .cache)
    """
    # Reserve ~15% for worktrees
    wt_count = max(1, int(total_repos * 0.15)) if total_repos >= 10 else 0
    regular_count = total_repos - wt_count

    repo_specs = []
    for i in range(regular_count):
        # Vary directory depth: depth 1, 2, or 3
        depth_mod = i % 3
        if depth_mod == 0:
            rel_path = f"repo_{i}"
        elif depth_mod == 1:
            rel_path = os.path.join(f"group_{i % 8}", f"repo_{i}")
        else:
            rel_path = os.path.join("org", f"team_{i % 5}", f"repo_{i}")

        full_path = os.path.join(base_dir, rel_path)

        # Repos with large changes (~10%)
        if i % 10 == 0:
            num_commits = 3
            num_untracked = 120
            num_modified = 30
        # Multi-commit repos (~20%)
        elif i % 5 == 0:
            num_commits = 4
            num_untracked = 5
            num_modified = 2
        # Normal dirty repos (~30%)
        elif i % 3 == 0:
            num_commits = 1
            num_untracked = 2
            num_modified = 1
        # Clean repos
        else:
            num_commits = 1
            num_untracked = 0
            num_modified = 0

        repo_specs.append((full_path, num_commits, num_untracked, num_modified))

    # Parallel creation of regular repos
    workers = min(32, max(4, os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(create_repo, path, commits, untracked, modified)
            for path, commits, untracked, modified in repo_specs
        ]
        for f in futures:
            f.result()

    # Create Git Worktrees
    for idx in range(wt_count):
        source_repo = repo_specs[idx % len(repo_specs)][0]
        wt_rel = os.path.join("worktrees", f"wt_{idx}")
        wt_path = os.path.join(base_dir, wt_rel)
        branch = f"wt-branch-{idx}"
        try:
            subprocess.run(
                ["git", "-C", source_repo, "worktree", "add", "-q", wt_path, "-b", branch],
                check=True,
                capture_output=True,
            )
            # Add some dirty changes to half of the worktrees
            if idx % 2 == 0:
                with open(os.path.join(wt_path, "wt_wip.txt"), "w") as f:
                    f.write("worktree wip\n")
        except Exception:
            # Fallback if worktree creation cannot be completed
            create_repo(wt_path, num_commits=1, num_untracked=1, num_modified=0)

    # Populate realistic skip directories containing dummy files
    for skip in ["node_modules", ".cache", "build", "target", ".venv"]:
        skip_path = os.path.join(base_dir, skip, "sub_module")
        os.makedirs(skip_path, exist_ok=True)
        with open(os.path.join(skip_path, "package.json"), "w") as f:
            f.write('{"name": "skip-pkg", "version": "1.0.0"}\n')


def compute_percentile(values, p):
    """Compute p-th percentile using linear interpolation."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n == 1:
        return sorted_v[0]
    rank = (p / 100.0) * (n - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    weight = rank - lower
    return sorted_v[lower] * (1.0 - weight) + sorted_v[upper] * weight


def benchmark_scale(repo_count, iterations=5, max_workers=None):
    """
    Benchmark Cold and Warm scan latency for a specific repository count.
    - Cold run: scanned on a newly instantiated mock environment.
    - Warm runs: repeated scan iterations on the warmed filesystem.
    """
    print(f"[*] Generating {repo_count:>4} mock repositories (mix: nested, worktrees, large dirty sets)...", end="", flush=True)
    t_gen_0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as temp_dir:
        generate_mock_environment(temp_dir, repo_count)
        t_gen_1 = time.perf_counter()
        print(f" ready in {(t_gen_1 - t_gen_0):.2f}s.")

        # --- 1. Cold Run ---
        t_cold_0 = time.perf_counter()
        cold_results = scan_repositories(temp_dir, max_depth=3, max_workers=max_workers)
        t_cold_1 = time.perf_counter()
        cold_ms = (t_cold_1 - t_cold_0) * 1000.0
        discovered = len(cold_results)

        # --- 2. Warm Runs ---
        warm_latencies = []
        for _ in range(iterations):
            t_w0 = time.perf_counter()
            scan_repositories(temp_dir, max_depth=3, max_workers=max_workers)
            t_w1 = time.perf_counter()
            warm_latencies.append((t_w1 - t_w0) * 1000.0)

        cold_stat = {
            "count": repo_count,
            "mode": "Cold",
            "discovered": discovered,
            "min_ms": cold_ms,
            "mean_ms": cold_ms,
            "p50_ms": cold_ms,
            "p95_ms": cold_ms,
            "p99_ms": cold_ms,
            "max_ms": cold_ms,
            "iterations": 1,
        }

        warm_stat = {
            "count": repo_count,
            "mode": "Warm",
            "discovered": discovered,
            "min_ms": min(warm_latencies),
            "mean_ms": sum(warm_latencies) / len(warm_latencies),
            "p50_ms": compute_percentile(warm_latencies, 50),
            "p95_ms": compute_percentile(warm_latencies, 95),
            "p99_ms": compute_percentile(warm_latencies, 99),
            "max_ms": max(warm_latencies),
            "iterations": iterations,
        }

        return cold_stat, warm_stat


def benchmark_timeout_resilience(total_repos=50, hanging_pct=0.10, per_repo_timeout=1.0):
    """
    Stress test scanner resilience against unresponsive or hanging git processes.
    Injects synthetic timeout delays for hanging_pct of repositories.
    """
    print(f"\n[*] Running Timeout Resilience Test ({total_repos} repos, {int(hanging_pct*100)}% hanging git commands)...", end="", flush=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        generate_mock_environment(temp_dir, total_repos)
        all_repos = find_git_repos(temp_dir, max_depth=3)
        num_hanging = max(1, int(len(all_repos) * hanging_pct))
        hanging_set = set(all_repos[:num_hanging])

        real_check_output = subprocess.check_output

        def mock_hanging_git(cmd, *args, **kwargs):
            # Check if command belongs to a hanging repo
            for repo in hanging_set:
                if any(repo in str(arg) for arg in cmd):
                    # Trigger TimeoutExpired simulating a hung git process
                    raise subprocess.TimeoutExpired(cmd=cmd, timeout=per_repo_timeout)
            return real_check_output(cmd, *args, **kwargs)

        t0 = time.perf_counter()
        with patch("subprocess.check_output", side_effect=mock_hanging_git):
            results = scan_repositories(
                temp_dir,
                max_depth=3,
                per_repo_timeout=per_repo_timeout,
                total_timeout=30.0,
            )
        elapsed_s = time.perf_counter() - t0

        found_count = len(results)
        expected_found = len(all_repos) - num_hanging

        print(f" completed in {elapsed_s:.2f}s.")
        return {
            "total_repos": len(all_repos),
            "hanging_repos": num_hanging,
            "recovered_repos": found_count,
            "expected_repos": expected_found,
            "elapsed_s": elapsed_s,
            "resilient": found_count == expected_found,
        }


def print_main_table(records):
    """Print clean ASCII table of latency distribution metrics."""
    print("\n" + "=" * 99)
    print("dev-context Core Engine Latency & Scale Benchmark Suite")
    print("=" * 99)
    header = (
        f"{'Repos':>7} | {'Found':>6} | {'Mode':>5} | "
        f"{'Min (ms)':>9} | {'Mean (ms)':>9} | {'P50 (ms)':>9} | "
        f"{'P95 (ms)':>9} | {'P99 (ms)':>9} | {'Max (ms)':>9} | {'Runs':>5}"
    )
    print(header)
    print("-" * 99)
    for r in records:
        row = (
            f"{r['count']:>7} | "
            f"{r['discovered']:>6} | "
            f"{r['mode']:>5} | "
            f"{r['min_ms']:>9.2f} | "
            f"{r['mean_ms']:>9.2f} | "
            f"{r['p50_ms']:>9.2f} | "
            f"{r['p95_ms']:>9.2f} | "
            f"{r['p99_ms']:>9.2f} | "
            f"{r['max_ms']:>9.2f} | "
            f"{r['iterations']:>5}"
        )
        print(row)
    print("=" * 99)


def print_resilience_table(res):
    """Print timeout resilience test results table."""
    print("\n" + "=" * 75)
    print("Git Subprocess Timeout & Resilience Safeguard Results")
    print("=" * 75)
    print(f"Total Repositories Tested : {res['total_repos']}")
    print(f"Hanging Repositories (Mock): {res['hanging_repos']}")
    print(f"Resiliently Discovered     : {res['recovered_repos']} / {res['expected_repos']}")
    print(f"Total Elapsed Wall Time    : {res['elapsed_s']:.2f}s")
    status = "PASSED (Zero Crashes, Unresponsive Tasks Dropped)" if res["resilient"] else "FAILED"
    print(f"Resilience Status          : {status}")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Stress benchmark suite for dev-context engine.")
    parser.add_argument(
        "--scales",
        nargs="+",
        type=int,
        default=[10, 100, 500, 1000],
        help="Repository counts to benchmark (default: 10 100 500 1000)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of warm scan iterations per scale (default: 5)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker thread count (default: auto)",
    )
    parser.add_argument(
        "--skip-resilience",
        action="store_true",
        help="Skip subprocess timeout resilience test",
    )
    args = parser.parse_args()

    records = []
    for scale in args.scales:
        cold_stat, warm_stat = benchmark_scale(scale, iterations=args.iterations, max_workers=args.workers)
        records.append(cold_stat)
        records.append(warm_stat)

    print_main_table(records)

    if not args.skip_resilience:
        res = benchmark_timeout_resilience()
        print_resilience_table(res)


if __name__ == "__main__":
    main()
