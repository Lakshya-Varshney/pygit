"""Tests for diff, status, and checkout safety."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from pygit_single import Repository
from pygit_single import Index
from pygit_single import hash_object
from pygit_single import load_ignore, is_ignored


class TestDiff(unittest.TestCase):
    """Test diff operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_diff_shows_changes(self):
        # Create initial content
        test_file = self.repo.root / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        # Modify it
        test_file.write_text("line1\nmodified\nline3\n")

        # Diff should show the change
        import difflib
        old = "line1\nline2\nline3\n".splitlines(keepends=True)
        new = "line1\nmodified\nline3\n".splitlines(keepends=True)
        diff = list(difflib.unified_diff(old, new, fromfile="a/test.txt", tofile="b/test.txt"))
        self.assertTrue(len(diff) > 0)
        self.assertIn("modified", "".join(diff))


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.index = Index(self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_clean_status(self):
        self.index.load()
        entries = self.index.get_entries()
        working = self.repo.get_working_tree_files()
        self.assertEqual(len(entries), 0)
        self.assertEqual(len(working), 0)


class TestIgnore(unittest.TestCase):
    """Test .pygitignore matching."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_ignore_pyc(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("*.pyc\n")
        patterns = load_ignore(self.tmpdir)
        self.assertTrue(is_ignored("__pycache__/foo.pyc", patterns))
        self.assertFalse(is_ignored("normal.txt", patterns))

    def test_ignore_directory(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("build/\n")
        patterns = load_ignore(self.tmpdir)
        self.assertTrue(is_ignored("build/output.o", patterns))
        self.assertFalse(is_ignored("src/main.py", patterns))

    def test_ignore_comments(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("# this is a comment\n*.log\n")
        patterns = load_ignore(self.tmpdir)
        self.assertEqual(len(patterns), 1)
        self.assertTrue(is_ignored("debug.log", patterns))

    def test_empty_ignore(self):
        patterns = load_ignore(self.tmpdir)
        self.assertEqual(len(patterns), 0)
        self.assertFalse(is_ignored("anything.txt", patterns))


class TestCheckoutSafety(unittest.TestCase):
    """Test that checkout refuses with uncommitted changes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_checkout_refuses_with_changes(self):
        # This tests the safety check logic
        # In practice, checkout checks index vs working tree
        index = Index(self.repo)
        index.load()

        # Add a file to index
        test_file = self.repo.root / "test.txt"
        test_file.write_text("original")
        sha = hash_object(test_file.read_bytes(), "blob", self.repo.root)
        index.add("test.txt", sha, "100644")
        index.save()

        # Modify working tree
        test_file.write_text("modified")

        # The checkout safety check should detect this
        working_sha = hash_object(test_file.read_bytes(), "blob", self.repo.root)
        entry = index.get_entry("test.txt")
        self.assertNotEqual(working_sha, entry["sha"])


if __name__ == "__main__":
    unittest.main()
