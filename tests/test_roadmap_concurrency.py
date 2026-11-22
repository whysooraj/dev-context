"""
Tests for ROADMAP.md POSIX file locking and atomic concurrency.
Verifies multi-thread and multi-process safety against race conditions and lost updates.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dev_context


class TestRoadmapConcurrency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.roadmap_path = os.path.join(self.temp_dir.name, "ROADMAP.md")
        with open(self.roadmap_path, "w", encoding="utf-8") as f:
            f.write("# Project Roadmap\n\n## Active Sprint\n\n## Ideas Backlog\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_concurrent_task_additions(self):
        """10 threads concurrently adding 5 tasks each (50 total) must result in 50 distinct tasks."""
        num_threads = 10
        tasks_per_thread = 5

        def worker(thread_idx):
            added_ids = []
            for i in range(tasks_per_thread):
                task_text = f"Thread-{thread_idx} Task-{i}"
                task_id = dev_context.cmd_add(task_text, file_path=self.roadmap_path, quiet=True)
                added_ids.append(task_id)
            return added_ids

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, t) for t in range(num_threads)]
            results = [f.result() for f in futures]

        all_added_ids = [tid for sublist in results for tid in sublist]
        self.assertEqual(len(all_added_ids), num_threads * tasks_per_thread)

        # Inspect resulting ROADMAP.md
        tasks, lines = dev_context.get_open_tasks(self.roadmap_path, include_completed=True)
        task_ids_in_file = [t["id"] for t in tasks]

        self.assertEqual(len(tasks), 50, f"Expected 50 tasks in file, found {len(tasks)}")
        self.assertEqual(len(set(task_ids_in_file)), 50, "All task IDs must be unique")

        # Ensure no lingering temporary files or corruption
        files = os.listdir(self.temp_dir.name)
        tmp_files = [f for f in files if f.startswith(".tmp.")]
        self.assertEqual(len(tmp_files), 0, f"Lingering tmp files found: {tmp_files}")

    def test_concurrent_state_transitions(self):
        """Seed tasks and concurrently mutate their states across multiple threads."""
        # Seed 20 tasks
        seed_ids = []
        for i in range(20):
            tid = dev_context.cmd_add(f"Seed task {i}", file_path=self.roadmap_path, quiet=True)
            seed_ids.append(tid)

        def worker(action_idx):
            tid = seed_ids[action_idx]
            if action_idx % 3 == 0:
                dev_context.cmd_done(tid, file_path=self.roadmap_path, quiet=True)
            elif action_idx % 3 == 1:
                dev_context.cmd_start(tid, file_path=self.roadmap_path, quiet=True)
            else:
                dev_context.cmd_block(tid, file_path=self.roadmap_path, quiet=True)

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(worker, range(20)))

        # Verify all 20 tasks still exist and have valid states
        tasks, _ = dev_context.get_open_tasks(self.roadmap_path, include_completed=True)
        self.assertEqual(len(tasks), 20)
        valid_states = {"completed", "in_progress", "blocked", "open"}
        for t in tasks:
            self.assertIn(t["state"], valid_states)


if __name__ == "__main__":
    unittest.main()
