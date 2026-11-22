#!/usr/bin/env python3
"""
Unit and integration tests for dev-context Stable Task Identifiers,
Project Tagging & Scoping, Multi-State Tasks, and Markdown Round-tripping.
"""

import os
import sys
import tempfile
import unittest
import subprocess
import re
from io import StringIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

from dev_context import (
    generate_task_id,
    fallback_task_id,
    extract_project,
    format_state_badge,
    get_open_tasks,
    find_task,
    find_roadmap_file,
    cmd_add,
    cmd_done,
    cmd_start,
    cmd_block,
    cmd_rm,
    cmd_list,
    find_repo_root,
)


def init_git_repo(path, commit_msg="Initial commit"):
    """Helper to initialize a git repo with a commit."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "Test Runner"], check=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "test@example.com"], check=True)
    file_path = os.path.join(path, "README.md")
    with open(file_path, "w") as f:
        f.write("# Test Repo\n")
    subprocess.run(["git", "-C", path, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", commit_msg], check=True)


class TestStableTaskIdentifiers(unittest.TestCase):
    """Test 4-hex stable ID generation, deterministic fallbacks, and non-shifting behavior."""

    def test_generate_task_id_format(self):
        tid = generate_task_id("sample task")
        self.assertEqual(len(tid), 4)
        self.assertTrue(all(c in "0123456789abcdef" for c in tid))

    def test_generate_task_id_collision_resolution(self):
        # Force collision by pre-populating existing_ids with first generated hash
        tid1 = generate_task_id("sample task")
        existing = {tid1}
        tid2 = generate_task_id("sample task", existing_ids=existing)
        self.assertNotEqual(tid1, tid2)
        self.assertEqual(len(tid2), 4)

    def test_fallback_task_id_deterministic(self):
        text = "deterministic task text"
        f1 = fallback_task_id(text)
        f2 = fallback_task_id(text)
        self.assertEqual(f1, f2)
        self.assertEqual(len(f1), 4)
        self.assertTrue(all(c in "0123456789abcdef" for c in f1))

    def test_fallback_task_id_ignores_tags(self):
        f1 = fallback_task_id("task text")
        f2 = fallback_task_id("task text <!-- id:a1b2 -->")
        f3 = fallback_task_id("task text ^c3d4")
        self.assertEqual(f1, f2)
        self.assertEqual(f1, f3)

    def test_task_parsing_with_explicit_comment_id(self):
        content = "# Sprint\n\n- [ ] laya: folder preview <!-- id:a3f1 -->\n"
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 1)
            t = tasks[0]
            self.assertEqual(t["id"], "a3f1")
            self.assertEqual(t["display_text"], "laya: folder preview")
            self.assertEqual(t["state"], "open")
            self.assertEqual(t["project"], "laya")
        finally:
            os.remove(tmp_path)

    def test_task_parsing_with_caret_id(self):
        content = "- [ ] besynx: p2p sync ^c4d2\n"
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 1)
            t = tasks[0]
            self.assertEqual(t["id"], "c4d2")
            self.assertEqual(t["display_text"], "besynx: p2p sync")
            self.assertEqual(t["project"], "besynx")
        finally:
            os.remove(tmp_path)

    def test_task_parsing_without_id_has_stable_fallback(self):
        content = "- [ ] untagged task without id\n"
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 1)
            t = tasks[0]
            expected_id = fallback_task_id("untagged task without id")
            self.assertEqual(t["id"], expected_id)
        finally:
            os.remove(tmp_path)

    def test_find_task_by_id_and_numeric_index(self):
        tasks = [
            {"task_num": 1, "id": "a3f1", "state": "open"},
            {"task_num": 2, "id": "b4c2", "state": "in_progress"},
            {"task_num": 3, "id": "c5d3", "state": "blocked"},
        ]
        # Match by ID
        self.assertEqual(find_task(tasks, "a3f1"), tasks[0])
        # Case insensitive match
        self.assertEqual(find_task(tasks, "A3F1"), tasks[0])
        # Match by numeric index int
        self.assertEqual(find_task(tasks, 2), tasks[1])
        # Match by numeric index str
        self.assertEqual(find_task(tasks, "2"), tasks[1])
        # Match 3
        self.assertEqual(find_task(tasks, "c5d3"), tasks[2])
        # Non-existent
        self.assertIsNone(find_task(tasks, "9999"))
        self.assertIsNone(find_task(tasks, 99))
        self.assertIsNone(find_task(tasks, None))

    def test_deletion_without_id_shifting(self):
        content = (
            "## Active Sprint\n"
            "- [ ] Task Alpha <!-- id:1111 -->\n"
            "- [ ] Task Beta <!-- id:2222 -->\n"
            "- [ ] Task Gamma <!-- id:3333 -->\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Delete Task Alpha using numeric index 1
            cmd_done(task_id=1, remove=True, file_path=tmp_path)

            tasks, _ = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 2)

            # Task Beta's stable ID MUST still be 2222, Task Gamma MUST still be 3333
            self.assertEqual(tasks[0]["id"], "2222")
            self.assertEqual(tasks[0]["task_num"], 1)  # Numeric index shifted to 1
            self.assertEqual(tasks[1]["id"], "3333")
            self.assertEqual(tasks[1]["task_num"], 2)  # Numeric index shifted to 2

            # Now reference Task Gamma by its stable ID 3333
            found = find_task(tasks, "3333")
            self.assertIsNotNone(found)
            self.assertEqual(found["text"], "Task Gamma")

            # Complete Task Gamma via its stable ID
            cmd_done(task_id="3333", remove=False, file_path=tmp_path)

            # Check open tasks: only Task Beta remains open
            open_tasks, _ = get_open_tasks(tmp_path)
            self.assertEqual(len(open_tasks), 1)
            self.assertEqual(open_tasks[0]["id"], "2222")

            # Check all tasks (including completed): Gamma retains 3333
            all_tasks, _ = get_open_tasks(tmp_path, include_completed=True)
            self.assertEqual(len(all_tasks), 2)
            gamma = next(t for t in all_tasks if t["id"] == "3333")
            self.assertEqual(gamma["state"], "completed")
        finally:
            os.remove(tmp_path)

    def test_fallback_id_without_shifting_after_deletion(self):
        """Fallback IDs computed for untagged tasks must remain identical when earlier tasks are deleted."""
        content = (
            "## Active Sprint\n"
            "- [ ] First untagged task\n"
            "- [ ] Second untagged task\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            tasks_before, _ = get_open_tasks(tmp_path)
            id_first = tasks_before[0]["id"]
            id_second = tasks_before[1]["id"]

            # Delete first task
            cmd_done(task_id=id_first, remove=True, file_path=tmp_path)

            # Read again
            tasks_after, _ = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks_after), 1)
            # Second task's ID must be unchanged!
            self.assertEqual(tasks_after[0]["id"], id_second)
            self.assertEqual(tasks_after[0]["text"], "Second untagged task")
        finally:
            os.remove(tmp_path)


class TestProjectTaggingAndScoping(unittest.TestCase):
    """Test project tag extraction, explicit -p tagging, auto-scoping, and filtering."""

    def test_extract_project_patterns(self):
        self.assertEqual(extract_project("(dev-context) my task"), "dev-context")
        self.assertEqual(extract_project("[laya] folder preview"), "laya")
        self.assertEqual(extract_project("besynx: p2p sync"), "besynx")
        self.assertEqual(extract_project("add benchmark suite #codeweaver"), "codeweaver")
        # Ignore common pseudo-prefixes
        self.assertIsNone(extract_project("TODO: refactor auth"))
        self.assertIsNone(extract_project("FIXME: memory leak"))
        self.assertIsNone(extract_project("plain task without project tag"))

    def test_cmd_add_with_explicit_project(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write("# Roadmap\n\n## Active Sprint\n")
            tmp_path = tmp.name

        try:
            tid = cmd_add("folder preview", project="laya", file_path=tmp_path)
            self.assertIsNotNone(tid)

            tasks, _ = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["project"], "laya")
            self.assertEqual(tasks[0]["text"], "(laya) folder preview")
            self.assertEqual(tasks[0]["id"], tid)
        finally:
            os.remove(tmp_path)

    def test_cmd_add_explicit_project_avoids_duplicate_prefix(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write("# Roadmap\n\n## Active Sprint\n")
            tmp_path = tmp.name

        try:
            cmd_add("(laya) folder preview", project="laya", file_path=tmp_path)
            tasks, _ = get_open_tasks(tmp_path)
            self.assertEqual(tasks[0]["text"], "(laya) folder preview")
        finally:
            os.remove(tmp_path)

    def test_cmd_add_autoscoping_in_git_to_global_roadmap(self):
        temp_dir = tempfile.TemporaryDirectory()
        try:
            repo_path = os.path.realpath(os.path.join(temp_dir.name, "my-service"))
            init_git_repo(repo_path)
            global_roadmap = os.path.realpath(os.path.join(temp_dir.name, "global_ROADMAP.md"))
            with open(global_roadmap, "w") as f:
                f.write("# Global Roadmap\n\n## Active Sprint\n")

            with patch("os.getcwd", return_value=repo_path):
                # When inside git repo and writing to global roadmap (not inside repo_path)
                cmd_add("redis cache layer", file_path=global_roadmap)

                tasks, _ = get_open_tasks(global_roadmap)
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["project"], "my-service")
                self.assertEqual(tasks[0]["text"], "(my-service) redis cache layer")
        finally:
            try:
                temp_dir.cleanup()
            except Exception:
                pass

    def test_cmd_add_local_does_not_autoscope(self):
        temp_dir = tempfile.TemporaryDirectory()
        try:
            repo_path = os.path.realpath(os.path.join(temp_dir.name, "local-repo"))
            init_git_repo(repo_path)
            local_roadmap = os.path.realpath(os.path.join(repo_path, "ROADMAP.md"))
            with open(local_roadmap, "w") as f:
                f.write("# Local Roadmap\n\n## Active Sprint\n")

            with patch("os.getcwd", return_value=repo_path):
                # Writing to local roadmap should not prefix project unless explicit
                cmd_add("unit test", file_path=local_roadmap)

                tasks, _ = get_open_tasks(local_roadmap)
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["text"], "unit test")
                self.assertIsNone(tasks[0]["project"])
        finally:
            try:
                temp_dir.cleanup()
            except Exception:
                pass

    def test_cmd_list_project_filtering(self):
        content = (
            "## Active Sprint\n"
            "- [ ] (laya) folder preview <!-- id:1111 -->\n"
            "- [ ] (besynx) p2p sync <!-- id:2222 -->\n"
            "- [ ] (laya) dry-run preview <!-- id:3333 -->\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Filter for laya
            laya_tasks = cmd_list(project="laya", file_path=tmp_path)
            self.assertEqual(len(laya_tasks), 2)
            self.assertTrue(all(t["project"] == "laya" for t in laya_tasks))

            # Filter for besynx
            besynx_tasks = cmd_list(project="besynx", file_path=tmp_path)
            self.assertEqual(len(besynx_tasks), 1)
            self.assertEqual(besynx_tasks[0]["id"], "2222")

            # Filter for non-existent project
            empty_tasks = cmd_list(project="nonexistent", file_path=tmp_path)
            self.assertEqual(len(empty_tasks), 0)

            # List all
            all_open = cmd_list(file_path=tmp_path)
            self.assertEqual(len(all_open), 3)
        finally:
            os.remove(tmp_path)


class TestMultiStateTasks(unittest.TestCase):
    """Test Multi-state tasks: Open, In-Progress, Completed, Blocked."""

    def test_parse_multi_state_markers(self):
        content = (
            "- [ ] Open task <!-- id:0001 -->\n"
            "- [-] In progress task 1 <!-- id:0002 -->\n"
            "- [~] In progress task 2 <!-- id:0003 -->\n"
            "- [!] Blocked task <!-- id:0004 -->\n"
            "- [x] Done task 1 <!-- id:0005 -->\n"
            "- [X] Done task 2 <!-- id:0006 -->\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Open tasks only
            open_tasks, _ = get_open_tasks(tmp_path, include_completed=False)
            self.assertEqual(len(open_tasks), 4)
            states = [t["state"] for t in open_tasks]
            self.assertEqual(states, ["open", "in_progress", "in_progress", "blocked"])

            # Labels
            labels = [t["state_label"] for t in open_tasks]
            self.assertEqual(labels, ["[TODO]", "[IN-PROGRESS]", "[IN-PROGRESS]", "[BLOCKED]"])

            # Including completed
            all_tasks, _ = get_open_tasks(tmp_path, include_completed=True)
            self.assertEqual(len(all_tasks), 6)
            self.assertEqual(all_tasks[4]["state"], "completed")
            self.assertEqual(all_tasks[4]["state_label"], "[DONE]")
            self.assertEqual(all_tasks[5]["state"], "completed")
        finally:
            os.remove(tmp_path)

    def test_state_transitions_full_cycle(self):
        content = "## Active Sprint\n- [ ] Lifecycle task <!-- id:a1b2 -->\n"
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # 1. Start task -> in_progress (- [-])
            res = cmd_start(task_id="a1b2", file_path=tmp_path)
            self.assertTrue(res)
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(tasks[0]["state"], "in_progress")
            self.assertIn("- [-] Lifecycle task <!-- id:a1b2 -->", lines)

            # 2. Block task -> blocked (- [!])
            res = cmd_block(task_id="a1b2", file_path=tmp_path)
            self.assertTrue(res)
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(tasks[0]["state"], "blocked")
            self.assertIn("- [!] Lifecycle task <!-- id:a1b2 -->", lines)

            # 3. Done task -> completed (- [x])
            res = cmd_done(task_id="a1b2", remove=False, file_path=tmp_path)
            self.assertTrue(res)
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 0)  # No longer in open tasks
            self.assertIn("- [x] Lifecycle task <!-- id:a1b2 -->", lines)

            # 4. Re-open / start completed task
            res = cmd_start(task_id="a1b2", file_path=tmp_path)
            self.assertTrue(res)
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["state"], "in_progress")
            self.assertIn("- [-] Lifecycle task <!-- id:a1b2 -->", lines)
        finally:
            os.remove(tmp_path)

    def test_transition_untagged_task_persists_id(self):
        """When an untagged task transitions state, its deterministic fallback ID is persisted in the markdown."""
        content = "## Active Sprint\n- [ ] Untagged task\n"
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            tasks, _ = get_open_tasks(tmp_path)
            fallback_id = tasks[0]["id"]

            cmd_start(task_id=fallback_id, file_path=tmp_path)

            tasks_after, lines = get_open_tasks(tmp_path)
            self.assertEqual(tasks_after[0]["state"], "in_progress")
            self.assertEqual(tasks_after[0]["id"], fallback_id)
            # Verify file line now contains <!-- id:... -->
            self.assertTrue(any(f"<!-- id:{fallback_id} -->" in line for line in lines))
        finally:
            os.remove(tmp_path)

    def test_cmd_rm_deletes_line(self):
        content = (
            "## Active Sprint\n"
            "- [ ] Keep me <!-- id:1111 -->\n"
            "- [ ] Delete me <!-- id:2222 -->\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            res = cmd_rm(task_id="2222", file_path=tmp_path)
            self.assertTrue(res)
            tasks, lines = get_open_tasks(tmp_path)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["id"], "1111")
            self.assertFalse(any("Delete me" in l for l in lines))
        finally:
            os.remove(tmp_path)

    def test_state_badge_formatting(self):
        self.assertEqual(format_state_badge("open", color=False), "[TODO]")
        self.assertEqual(format_state_badge("in_progress", color=False), "[IN-PROGRESS]")
        self.assertEqual(format_state_badge("blocked", color=False), "[BLOCKED]")
        self.assertEqual(format_state_badge("completed", color=False), "[DONE]")


class TestMarkdownRoundTripping(unittest.TestCase):
    """Test markdown structure preservation, formatting, and round-tripping."""

    def test_complex_markdown_round_trip(self):
        initial_markdown = (
            "# Master Project Roadmap\n"
            "\n"
            "This roadmap outlines all major milestones and backlog items.\n"
            "\n"
            "## Active Sprint\n"
            "- [ ] Task One <!-- id:a101 -->\n"
            "- [-] Task Two <!-- id:a102 -->\n"
            "- [!] Task Three <!-- id:a103 -->\n"
            "- [x] Finished Task <!-- id:a104 -->\n"
            "\n"
            "## Ideas Backlog\n"
            "- [ ] Future Idea <!-- id:b201 -->\n"
            "\n"
            "## Notes\n"
            "- Keep tasks atomic\n"
            "- Review weekly\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".md") as tmp:
            tmp.write(initial_markdown)
            tmp_path = tmp.name

        try:
            # 1. Start Task One
            cmd_start(task_id="a101", file_path=tmp_path)
            # 2. Complete Task Three
            cmd_done(task_id="a103", file_path=tmp_path)
            # 3. Add a new task to sprint
            new_id = cmd_add("New Feature Task", section="## Active Sprint", file_path=tmp_path)

            with open(tmp_path, "r", encoding="utf-8") as f:
                updated_content = f.read()

            # Verify headings and non-task lines are preserved
            self.assertIn("# Master Project Roadmap", updated_content)
            self.assertIn("This roadmap outlines all major milestones and backlog items.", updated_content)
            self.assertIn("## Active Sprint", updated_content)
            self.assertIn("## Ideas Backlog", updated_content)
            self.assertIn("## Notes", updated_content)
            self.assertIn("- Keep tasks atomic", updated_content)

            # Verify state changes
            self.assertIn(f"- [-] Task One <!-- id:a101 -->", updated_content)
            self.assertIn(f"- [x] Task Three <!-- id:a103 -->", updated_content)
            self.assertIn(f"New Feature Task <!-- id:{new_id} -->", updated_content)

            # Verify re-parsing
            tasks, lines = get_open_tasks(tmp_path)
            open_ids = [t["id"] for t in tasks]
            self.assertIn("a101", open_ids)
            self.assertIn("a102", open_ids)
            self.assertIn("b201", open_ids)
            self.assertIn(new_id, open_ids)
            self.assertNotIn("a103", open_ids)  # Completed
        finally:
            os.remove(tmp_path)


class TestCLIExecution(unittest.TestCase):
    """End-to-end execution of CLI commands via subprocess."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.roadmap_file = os.path.join(self.temp_dir.name, "ROADMAP.md")
        with open(self.roadmap_file, "w") as f:
            f.write("# Roadmap\n\n## Active Sprint\n\n## Ideas Backlog\n")
        self.bin_path = str(PROJECT_ROOT / "bin" / "dev-context")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def run_cli(self, *args):
        env = dict(os.environ)
        env["DEV_CONTEXT_ROADMAP_FILE"] = self.roadmap_file
        res = subprocess.run(
            [sys.executable, self.bin_path, *args],
            capture_output=True,
            text=True,
            env=env,
        )
        return res

    def test_cli_add_list_start_block_done_rm_flow(self):
        # 1. Add task with project
        res = self.run_cli("add", "-p", "flight", "autopilot checks")
        self.assertEqual(res.returncode, 0)
        self.assertIn("autopilot checks", res.stdout)

        # Extract ID from list
        res_list = self.run_cli("list", "-p", "flight")
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("[TODO]", res_list.stdout)
        self.assertIn("(flight) autopilot checks", res_list.stdout)

        m = re.search(r'\[([0-9a-fA-F]{4})\]', res_list.stdout)
        self.assertIsNotNone(m, f"Could not find 4-hex ID in: {res_list.stdout}")
        task_id = m.group(1)

        # 2. Start task
        res_start = self.run_cli("start", task_id)
        self.assertEqual(res_start.returncode, 0)
        self.assertIn("Started task", res_start.stdout)

        # Verify state in list
        res_list2 = self.run_cli("list")
        self.assertIn("[IN-PROGRESS]", res_list2.stdout)

        # 3. Block task
        res_block = self.run_cli("block", task_id)
        self.assertEqual(res_block.returncode, 0)
        self.assertIn("Blocked task", res_block.stdout)

        res_list3 = self.run_cli("list")
        self.assertIn("[BLOCKED]", res_list3.stdout)

        # 4. Complete task
        res_done = self.run_cli("done", task_id)
        self.assertEqual(res_done.returncode, 0)
        self.assertIn("Completed task", res_done.stdout)

        # 5. List should now be empty of open tasks
        res_list4 = self.run_cli("list")
        self.assertIn("All caught up", res_list4.stdout)

    def test_cli_idea_adds_to_backlog(self):
        res = self.run_cli("idea", "-p", "satellite", "orbital decay calculation")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Ideas Backlog", res.stdout)
        self.assertIn("(satellite) orbital decay calculation", res.stdout)

        with open(self.roadmap_file, "r") as f:
            content = f.read()
        self.assertIn("## Ideas Backlog\n- [ ] (satellite) orbital decay calculation", content)

    def test_cli_numeric_index_done_and_rm(self):
        self.run_cli("add", "first task")
        self.run_cli("add", "second task")

        # Complete task 1
        res = self.run_cli("done", "1")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Completed task", res.stdout)

        # Now second task is task 1; delete it
        res_rm = self.run_cli("rm", "1")
        self.assertEqual(res_rm.returncode, 0)
        self.assertIn("Deleted task", res_rm.stdout)

        res_list = self.run_cli("list")
        self.assertIn("All caught up", res_list.stdout)


class TestDashboardFocusQueue(unittest.TestCase):
    """Test dashboard rendering with multi-state tasks and stable IDs."""

    def test_dashboard_focus_queue_states_and_ids(self):
        from dev_context import print_dashboard
        temp_dir = tempfile.TemporaryDirectory()
        try:
            roadmap = os.path.join(temp_dir.name, "ROADMAP.md")
            with open(roadmap, "w") as f:
                f.write(
                    "## Active Sprint\n"
                    "- [ ] (laya) file preview <!-- id:fa01 -->\n"
                    "- [-] (besynx) sync engine <!-- id:fa02 -->\n"
                    "- [!] (codeweaver) rate limit <!-- id:fa03 -->\n"
                )

            with patch.dict(os.environ, {"DEV_CONTEXT_ROADMAP_FILE": roadmap, "DEV_CONTEXT_SKIP": "1"}):
                with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                    print_dashboard(projects_dir_override=temp_dir.name)
                    output = strip_ansi(mock_stdout.getvalue())

            self.assertIn("FOCUS QUEUE", output)
            self.assertIn("[fa01] [TODO]", output)
            self.assertIn("file preview", output)
            self.assertIn("[fa02] [IN-PROGRESS]", output)
            self.assertIn("sync engine", output)
            self.assertIn("[fa03] [BLOCKED]", output)
            self.assertIn("rate limit", output)
        finally:
            try:
                temp_dir.cleanup()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
