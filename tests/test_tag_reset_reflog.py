"""Tests for tag, reset, and reflog."""

import os
import shutil
import tempfile
import unittest

from pygit.repository import Repository
from pygit.objects import hash_object, serialize_commit, serialize_tree


class TestTag(unittest.TestCase):
    """Test tag creation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_lightweight_tag(self):
        # Create a commit
        tree_data = serialize_tree([])
        tree_sha = hash_object(tree_data, "tree", self.repo.root)
        commit_data = serialize_commit(
            tree_sha, [], "Test <t@t.com>", "Test <t@t.com>", 1000, "init"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)

        # Create tag
        self.repo.set_ref("refs/tags/v1.0", commit_sha)
        tag_sha = self.repo.get_ref("refs/tags/v1.0")
        self.assertEqual(tag_sha, commit_sha)


class TestReset(unittest.TestCase):
    """Test reset modes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_reset_moves_ref(self):
        # Create commits
        tree_data = serialize_tree([])
        tree_sha = hash_object(tree_data, "tree", self.repo.root)

        shas = []
        parent = None
        for i in range(3):
            data = serialize_commit(
                tree_sha, [parent] if parent else [],
                "Test <t@t.com>", "Test <t@t.com>", 1000 + i, f"commit {i}"
            )
            sha = hash_object(data, "commit", self.repo.root)
            shas.append(sha)
            parent = sha

        # Set ref to last commit
        self.repo.set_ref("refs/heads/main", shas[2])

        # Reset to first commit
        self.repo.set_ref("refs/heads/main", shas[0])
        current = self.repo.get_ref("refs/heads/main")
        self.assertEqual(current, shas[0])


class TestReflog(unittest.TestCase):
    """Test reflog recording."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_reflog_records_entries(self):
        self.repo.append_reflog("0" * 64, "a" * 64, "commit")
        self.repo.append_reflog("a" * 64, "b" * 64, "checkout")

        reflog_file = self.repo.git_dir / "logs" / "HEAD"
        content = reflog_file.read_text()
        lines = content.strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertIn("commit", lines[0])
        self.assertIn("checkout", lines[1])


if __name__ == "__main__":
    unittest.main()
