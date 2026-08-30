"""Tests for pygit.clean — untracked file management."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from pygit.repository import Repository
from pygit.index import Index
from pygit.objects import hash_object
from pygit.clean import get_untracked_files, get_clean_targets, clean_repo


class TestClean(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="clean_test_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Test")
        self.repo.set_config_value("user.email", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _commit_file(self, name, content):
        """Helper: add and commit a file."""
        full = Path(self.d) / name
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        index = Index(self.repo)
        index.load()
        sha = hash_object(full.read_bytes(), "blob", self.repo.root)
        index.add(name, sha, "100644")
        index.save()
        tree_sha = self.repo.build_tree_from_index(index)
        head = self.repo.get_head()
        parent = None
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            try:
                parent = self.repo.get_ref(ref_path)
            except Exception:
                pass
        import time
        from pygit.objects import serialize_commit, hash_object as ho
        parents = [parent] if parent else []
        author = "Test <t@t.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, parents, author, author, epoch, "commit")
        cs = ho(cd, "commit", self.repo.root)
        # Write to the ref that HEAD currently points to
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            self.repo.set_ref(ref_path, cs)
        else:
            self.repo.set_ref("refs/heads/main", cs)

    def test_get_untracked_files(self):
        """Untracked files are returned, tracked files are not."""
        self._commit_file("tracked.txt", "hello")
        untracked = Path(self.d) / "untracked.txt"
        untracked.write_text("world")

        result = get_untracked_files(self.repo)
        paths = [p for p, _ in result]
        self.assertIn("untracked.txt", paths)
        self.assertNotIn("tracked.txt", paths)

    def test_ignored_files_excluded_by_default(self):
        """Files matching .pygitignore are excluded."""
        self._commit_file("tracked.txt", "hello")
        ignore = Path(self.d) / ".pygitignore"
        ignore.write_text("*.log\n")
        log_file = Path(self.d) / "debug.log"
        log_file.write_text("log content")

        result = get_untracked_files(self.repo)
        paths = [p for p, _ in result]
        self.assertNotIn("debug.log", paths)
        self.assertEqual(result, [])

    def test_ignored_files_included_with_flag(self):
        """include_ignored=True returns ignored files."""
        self._commit_file("tracked.txt", "hello")
        ignore = Path(self.d) / ".pygitignore"
        ignore.write_text("*.log\n")
        log_file = Path(self.d) / "debug.log"
        log_file.write_text("log content")

        result = get_untracked_files(self.repo, include_ignored=True)
        paths = [p for p, _ in result]
        self.assertIn("debug.log", paths)

    def test_pygit_dir_excluded(self):
        """Nothing under .pygit/ is ever returned."""
        untracked = Path(self.d) / "normal.txt"
        untracked.write_text("content")

        result = get_untracked_files(self.repo)
        for p, _ in result:
            self.assertFalse(p.startswith(".pygit"), f".pygit path leaked: {p}")

    def test_dry_run_does_not_delete(self):
        """dry_run prints but doesn't delete."""
        untracked = Path(self.d) / "temp.txt"
        untracked.write_text("temp")

        import io
        old_stdout = __import__("sys").stdout
        __import__("sys").stdout = buf = io.StringIO()
        try:
            removed = clean_repo(self.repo, dry_run=True)
        finally:
            __import__("sys").stdout = old_stdout

        self.assertTrue(untracked.exists(), "File should still exist after dry run")
        self.assertIn("temp.txt", "\n".join(removed))

    def test_force_delete_removes_files(self):
        """clean -f actually deletes untracked files."""
        untracked = Path(self.d) / "temp.txt"
        untracked.write_text("temp")

        removed = clean_repo(self.repo, dry_run=False)
        self.assertFalse(untracked.exists(), "File should be deleted")
        self.assertIn("temp.txt", removed)

    def test_tracked_files_never_deleted(self):
        """Tracked files are never touched."""
        self._commit_file("safe.txt", "important")
        untracked = Path(self.d) / "temp.txt"
        untracked.write_text("temp")

        clean_repo(self.repo, dry_run=False)
        self.assertTrue((Path(self.d) / "safe.txt").exists())

    def test_dirs_excluded_by_default(self):
        """Untracked directories are left alone without -d."""
        self._commit_file("tracked.txt", "hello")
        untracked_dir = Path(self.d) / "mydir"
        untracked_dir.mkdir()
        (untracked_dir / "file.txt").write_text("content")

        targets = get_clean_targets(self.repo, include_dirs=False)
        dir_targets = [p for p, is_dir in targets if is_dir]
        self.assertNotIn("mydir", dir_targets)

    def test_dirs_included_with_d(self):
        """Untracked directories are included with -d."""
        self._commit_file("tracked.txt", "hello")
        untracked_dir = Path(self.d) / "mydir"
        untracked_dir.mkdir()
        (untracked_dir / "file.txt").write_text("content")

        targets = get_clean_targets(self.repo, include_dirs=True)
        dir_targets = [p for p, is_dir in targets if is_dir]
        self.assertIn("mydir", dir_targets)

    def test_fx_includes_ignored(self):
        """-x flag includes .pygitignore'd files."""
        ignore = Path(self.d) / ".pygitignore"
        ignore.write_text("*.log\n")
        log_file = Path(self.d) / "debug.log"
        log_file.write_text("log")

        targets = get_clean_targets(self.repo, include_ignored=True)
        target_paths = [p for p, _ in targets]
        self.assertIn("debug.log", target_paths)

    def test_pygit_dir_never_touched(self):
        """The .pygit directory is never cleaned."""
        untracked = Path(self.d) / "temp.txt"
        untracked.write_text("temp")

        clean_repo(self.repo, dry_run=False)
        import subprocess, sys, os
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        result = subprocess.run(
            [sys.executable, "-m", "pygit", "log"],
            cwd=self.d, capture_output=True, text=True, env=env
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

    def test_untracked_dir_contents_not_listed_without_d(self):
        """Without -d, files inside an entirely untracked dir are not listed."""
        self._commit_file("tracked.txt", "hello")
        untracked_dir = Path(self.d) / "untracked_dir"
        untracked_dir.mkdir()
        (untracked_dir / "f.txt").write_text("x")

        result = get_clean_targets(self.repo, include_dirs=False)
        paths = [p for p, _ in result]
        self.assertNotIn("untracked_dir", paths)
        self.assertNotIn("untracked_dir/f.txt", paths)

    def test_untracked_dir_contents_not_deleted_without_d(self):
        """Without -d, clean -f leaves files inside an untracked dir untouched."""
        self._commit_file("tracked.txt", "hello")
        untracked_dir = Path(self.d) / "untracked_dir"
        untracked_dir.mkdir()
        (untracked_dir / "f.txt").write_text("x")

        clean_repo(self.repo, dry_run=False, include_dirs=False)
        self.assertTrue((untracked_dir / "f.txt").exists())

    def test_untracked_dir_removed_with_d(self):
        """With -d, clean -fd removes the whole untracked directory."""
        self._commit_file("tracked.txt", "hello")
        untracked_dir = Path(self.d) / "untracked_dir"
        untracked_dir.mkdir()
        (untracked_dir / "f.txt").write_text("x")

        clean_repo(self.repo, dry_run=False, include_dirs=True)
        self.assertFalse(untracked_dir.exists())

    def test_mixed_dir_only_untracked_files_listed(self):
        """In a mixed dir (tracked + untracked), only untracked files are listed."""
        self._commit_file("tracked.txt", "hello")
        mixed_dir = Path(self.d) / "mixed"
        mixed_dir.mkdir()
        (mixed_dir / "tracked_in_dir.txt").write_text("tracked")
        (mixed_dir / "untracked_in_dir.txt").write_text("untracked")

        index = Index(self.repo)
        index.load()
        full = mixed_dir / "tracked_in_dir.txt"
        sha = hash_object(full.read_bytes(), "blob", self.repo.root)
        index.add("mixed/tracked_in_dir.txt", sha, "100644")
        index.save()

        result = get_clean_targets(self.repo, include_dirs=False)
        paths = [p for p, _ in result]
        self.assertIn("mixed/untracked_in_dir.txt", paths)
        self.assertNotIn("mixed/tracked_in_dir.txt", paths)
        self.assertNotIn("mixed", paths)

    def test_mixed_dir_only_untracked_deleted(self):
        """In a mixed dir, clean -f removes only the untracked file."""
        self._commit_file("tracked.txt", "hello")
        mixed_dir = Path(self.d) / "mixed"
        mixed_dir.mkdir()
        (mixed_dir / "tracked_in_dir.txt").write_text("tracked")
        (mixed_dir / "untracked_in_dir.txt").write_text("untracked")

        index = Index(self.repo)
        index.load()
        full = mixed_dir / "tracked_in_dir.txt"
        sha = hash_object(full.read_bytes(), "blob", self.repo.root)
        index.add("mixed/tracked_in_dir.txt", sha, "100644")
        index.save()

        clean_repo(self.repo, dry_run=False, include_dirs=False)
        self.assertTrue((mixed_dir / "tracked_in_dir.txt").exists())
        self.assertFalse((mixed_dir / "untracked_in_dir.txt").exists())
        self.assertTrue(mixed_dir.exists())


if __name__ == "__main__":
    unittest.main()
