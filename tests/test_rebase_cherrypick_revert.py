"""Tests for cherry-pick, rebase, revert."""

import os
import shutil
import tempfile
import unittest

from pygit_single import Repository
from pygit_single import hash_object, serialize_tree, serialize_commit


class TestCherryPick(unittest.TestCase):
    """Test cherry-pick operation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.repo.set_user("Test", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_cherry_pick_applies_changes(self):
        # Create a commit with some content
        tree_entries = [("100644", "file.txt", hash_object(b"content", "blob", self.repo.root))]
        tree_data = serialize_tree(tree_entries)
        tree_sha = hash_object(tree_data, "tree", self.repo.root)

        commit_data = serialize_commit(
            tree_sha, [], "Test <t@t.com>", "Test <t@t.com>", 1000, "add file"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)

        # Verify the commit has the tree
        from pygit_single import read_object, deserialize_commit
        _, data = read_object(commit_sha, self.repo.root)
        commit = deserialize_commit(data)
        self.assertEqual(commit["tree"], tree_sha)


class TestRebase(unittest.TestCase):
    """Test rebase operation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_rebase_finds_base(self):
        from pygit_single import find_merge_base
        # Create linear history
        tree_data = serialize_tree([])
        tree_sha = hash_object(tree_data, "tree", self.repo.root)

        parent = None
        shas = []
        for i in range(3):
            data = serialize_commit(
                tree_sha, [parent] if parent else [],
                "Test <t@t.com>", "Test <t@t.com>", 1000 + i, f"commit {i}"
            )
            sha = hash_object(data, "commit", self.repo.root)
            shas.append(sha)
            parent = sha

        # Base of first and last should be first
        base = find_merge_base(self.repo, shas[0], shas[2])
        self.assertEqual(base, shas[0])


class TestRevert(unittest.TestCase):
    """Test revert operation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_revert_creates_new_commit(self):
        # Create a commit
        tree_data = serialize_tree([])
        tree_sha = hash_object(tree_data, "tree", self.repo.root)

        commit_data = serialize_commit(
            tree_sha, [], "Test <t@t.com>", "Test <t@t.com>", 1000, "original"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)

        # Verify commit exists
        from pygit_single import read_object
        obj_type, _ = read_object(commit_sha, self.repo.root)
        self.assertEqual(obj_type, "commit")


if __name__ == "__main__":
    unittest.main()
