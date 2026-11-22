#!/usr/bin/env python3
"""
Comprehensive Benchmark & Stress Test Suite for dev-context Core Engine.
Evaluates repository discovery, parallel git inspection, cache warming,
percentile latency distribution (Min, Mean, P50, P95, P99, Max),
timeout resilience against unresponsive / hanging git subprocesses,
and publishes complete hardware/runtime environment specifications.
"""

import os
import sys
import time
import math
import argparse
import tempfile
import platform
import subprocess
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dev_context import scan_repositories, find_git_repos, get_git_info


def get_hardware_environment():
    """Extract hardware, kernel, and runtime specifications for reproducibility."""
    cpu_model = "Unknown"
    if os.path.exists("/proc/cpuinfo"):
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "model name" in line:
                        cpu_model = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

    ram_gb = 0.0
    if os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if "MemTotal:" in line:
                        ram_gb = int(line.split()[1]) / (1024 * 1024)
                        break
        except Exception:
            pass

    fs_type = "Unknown"
    try:
        out = subprocess.check_output(["df", "-T", "."], text=True)
        fs_type = out.splitlines()[1].split()[1]
    except Exception:
        pass

    return {
        "cpu": f"{cpu_model} ({os.cpu_count()} logical cores)",
        "ram": f"{ram_gb:.1f} GB" if ram_gb else "Unknown",
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": platform.python_version(),
        "fs": fs_type,
    }


def create_repo(path, num_commits=1, num_untracked=0, num_modified=0):
    """
    Generate a mock repository with customizable commit count,
    modified files, and untracked files.
    """
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    author_args = ["-c", "user.name=Benchmarker", "-c", "user.email=bench@example.com"]

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

    for m in range(num_modified):
        target_f = f"tracked_{m % max(1, num_commits)}.txt"
        with open(os.path.join(path, target_f), "a", encoding="utf-8") as f:
            f.write(f"\nModified diff line for benchmark stress testing #{m}")

    for u in range(num_untracked):
        u_path = os.path.join(path, f"untracked_{u}.tmp")
        with open(u_path, "w", encoding="utf-8") as f:
            f.write(f"Untracked contents #{u}")


def create_worktree(main_repo_path, worktree_path, branch_name="feat-worktree"):
    """Create a git worktree referencing main_repo_path."""
    author_args = ["-c", "user.name=Benchmarker", "-c", "user.email=bench@example.com"]
    subprocess.run(
        ["git", "-C", main_repo_path, *author_args, "worktree", "add", "-q", "-b", branch_name, worktree_path],
        check=True,
    )


def generate_mock_environment(base_dir, total_repos):
    """
    Create a diverse, realistic workspace containing:
    - 75% standard repositories at depths 1, 2, and 3
    - 15% git worktrees pointing to base repositories
    - 10% repositories with large file footprints (50+ modified/untracked files)
    - Realistic skip directories (node_modules, target, .venv, .cache)
    """
    os.makedirs(base_dir, exist_ok=True)

    # Inject skip directories to test directory pruning
    for skip in ["node_modules", "target", ".venv", ".cache"]:
        skip_path = os.path.join(base_dir, skip)
        os.makedirs(skip_path, exist_ok=True)
        create_repo(os.path.join(skip_path, "nested-fake-repo"))

    wt_count = max(1, int(total_repos * 0.15)) if total_repos >= 10 else 0
    large_count = max(1, int(total_repos * 0.10)) if total_repos >= 10 else 0
    standard_count = total_repos - wt_count - large_count

    idx = 0
    primary_repos = []

    # Standard repos across varied depth
    for _ in range(standard_count):
        depth_mod = idx % 3
        if depth_mod == 0:
            repo_path = os.path.join(base_dir, f"repo_{idx}")
        elif depth_mod == 1:
            repo_path = os.path.join(base_dir, "group_a", f"subgroup_{idx % 4}", f"repo_{idx}")
        else:
            repo_path = os.path.join(base_dir, "apps", f"repo_{idx}")

        create_repo(repo_path, num_commits=(idx % 3) + 1, num_modified=(idx % 4), num_untracked=(idx % 2))
        primary_repos.append(repo_path)
        idx += 1

    # Large dirty repos (100 modified / untracked files)
    for _ in range(large_count):
        repo_path = os.path.join(base_dir, "heavy_workspaces", f"heavy_repo_{idx}")
        create_repo(repo_path, num_commits=5, num_modified=50, num_untracked=50)
        primary_repos.append(repo_path)
        idx += 1

    # Git worktrees
    for w_i in range(wt_count):
        parent_repo = primary_repos[w_i % len(primary_repos)]
        wt_path = os.path.join(base_dir, "worktrees", f"wt_{w_i}")
        create_worktree(parent_repo, wt_path, branch_name=f"wt-branch-{w_i}")
        idx += 1


def calculate_percentiles(latencies):
    """Compute min, mean, p50, p95, p99, and max from a list of latencies in ms."""
    sorted_l = sorted(latencies)
    n = len(sorted_l)

    def p(pct):
        if n == 1:
            return sorted_l[0]
        k = (n - 1) * (pct / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_l[int(k)]
        d0 = sorted_l[int(f)] * (c - k)
        d1 = sorted_l[int(c)] * (k - f)
        return d0 + d1

    return {
        "min": sorted_l[0],
        "mean": sum(sorted_l) / n,
        "p50": p(50),
        "p95": p(95),
        "p99": p(99),
        "max": sorted_l[-1],
    }


def benchmark_scale(repo_count, cold_runs=3, warm_runs=25, max_workers=None):
    """
    Benchmark Cold and Warm scan latency for a specific repository count.
    - Cold runs: multiple iterations, each executed on a brand new isolated directory tree.
    - Warm runs: repeated scan iterations on a primed filesystem.
    """
    print(f"[*] Benchmarking {repo_count:>4} repos: running {cold_runs} cold runs on fresh trees...", end="", flush=True)

    cold_latencies = []
    cold_discovered = 0
    for _ in range(cold_runs):
        with tempfile.TemporaryDirectory() as fresh_dir:
            generate_mock_environment(fresh_dir, repo_count)
            t0 = time.perf_counter()
            cold_results = scan_repositories(fresh_dir, max_depth=3, max_workers=max_workers)
            cold_latencies.append((time.perf_counter() - t0) * 1000.0)
            cold_discovered = len(cold_results)

    cold_stats = calculate_percentiles(cold_latencies)
    print(f" done (Mean cold: {cold_stats['mean']:.2f}ms).")

    print(f"    Running {warm_runs} warm iterations...", end="", flush=True)
    with tempfile.TemporaryDirectory() as warm_dir:
        generate_mock_environment(warm_dir, repo_count)
        # Prime once
        scan_repositories(warm_dir, max_depth=3, max_workers=max_workers)

        warm_latencies = []
        warm_discovered = 0
        for _ in range(warm_runs):
            t_start = time.perf_counter()
            res = scan_repositories(warm_dir, max_depth=3, max_workers=max_workers)
            warm_latencies.append((time.perf_counter() - t_start) * 1000.0)
            warm_discovered = len(res)

    warm_stats = calculate_percentiles(warm_latencies)
    print(f" done (Mean warm: {warm_stats['mean']:.2f}ms).")

    return {
        "count": repo_count,
        "cold": {
            "discovered": cold_discovered,
            "min_ms": cold_stats["min"],
            "mean_ms": cold_stats["mean"],
            "p50_ms": cold_stats["p50"],
            "max_ms": cold_stats["max"],
            "runs": cold_runs,
        },
        "warm": {
            "discovered": warm_discovered,
            "min_ms": warm_stats["min"],
            "mean_ms": warm_stats["mean"],
            "p50_ms": warm_stats["p50"],
            "p95_ms": warm_stats["p95"],
            "p99_ms": warm_stats["p99"],
            "max_ms": warm_stats["max"],
            "runs": warm_runs,
        },
    }


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
        hanging_candidates = [r for r in all_repos if "worktrees" in r or "heavy_workspaces" in r]
        hanging_set = set(hanging_candidates[:num_hanging]) if len(hanging_candidates) >= num_hanging else set(all_repos[:num_hanging])

        real_check_output = subprocess.check_output

        def mock_hanging_git(cmd, *args, **kwargs):
            for repo in hanging_set:
                if any(repo in str(arg) for arg in cmd):
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


def print_env_table(env):
    """Print hardware and runtime environment table."""
    print("\n" + "=" * 80)
    print("Benchmark Environment & Reproducibility Specifications")
    print("=" * 80)
    print(f"CPU Model    : {env['cpu']}")
    print(f"Total RAM    : {env['ram']}")
    print(f"OS / Kernel  : {env['os']}")
    print(f"Python       : {env['python']}")
    print(f"Filesystem   : {env['fs']}")
    print(f"Repositories : Synthetic multi-commit Git trees with 15% worktrees & 10% heavy dirty sets")
    print(f"Isolation    : Each Cold run executes on a newly created, unprimed directory tree")
    print("=" * 80)


def print_tables(records):
    """Print clean separated ASCII tables for Cold and Warm metrics."""
    # 1. Cold Runs Table
    print("\n" + "=" * 70)
    print("Cold Discovery Latency (Fresh Uncached Directory Trees)")
    print("=" * 70)
    h_cold = f"{'Repos':>7} | {'Found':>6} | {'Min (ms)':>9} | {'Mean (ms)':>9} | {'P50 (ms)':>9} | {'Max (ms)':>9} | {'Runs':>5}"
    print(h_cold)
    print("-" * 70)
    for r in records:
        c = r["cold"]
        print(f"{r['count']:>7} | {c['discovered']:>6} | {c['min_ms']:>9.2f} | {c['mean_ms']:>9.2f} | {c['p50_ms']:>9.2f} | {c['max_ms']:>9.2f} | {c['runs']:>5}")
    print("=" * 70)

    # 2. Warm Runs Table
    print("\n" + "=" * 90)
    print("Warm Discovery Latency (Repeated Scans over Primed Tree)")
    print("=" * 90)
    h_warm = f"{'Repos':>7} | {'Found':>6} | {'Min (ms)':>9} | {'Mean (ms)':>9} | {'P50 (ms)':>9} | {'P95 (ms)':>9} | {'P99 (ms)':>9} | {'Max (ms)':>9} | {'Runs':>5}"
    print(h_warm)
    print("-" * 90)
    for r in records:
        w = r["warm"]
        print(f"{r['count']:>7} | {w['discovered']:>6} | {w['min_ms']:>9.2f} | {w['mean_ms']:>9.2f} | {w['p50_ms']:>9.2f} | {w['p95_ms']:>9.2f} | {w['p99_ms']:>9.2f} | {w['max_ms']:>9.2f} | {w['runs']:>5}")
    print("=" * 90)


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
        "--cold-runs",
        type=int,
        default=3,
        help="Number of cold runs on fresh trees (default: 3)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=25,
        help="Number of warm scan iterations per scale (default: 25)",
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

    env = get_hardware_environment()
    print_env_table(env)

    records = []
    for count in args.scales:
        rec = benchmark_scale(
            count,
            cold_runs=args.cold_runs,
            warm_runs=args.iterations,
            max_workers=args.workers,
        )
        records.append(rec)

    print_tables(records)

    if not args.skip_resilience:
        res = benchmark_timeout_resilience()
        print_resilience_table(res)


if __name__ == "__main__":
    main()
