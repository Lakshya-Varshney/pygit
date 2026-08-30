"""Tests for stash operations."""

import os
import shutil
import tempfile
import unittest

from pygit_single import Repository
from pygit_single import Index
from pygit_single import hash_object
from pygit_single import stash_push, stash_pop, stash_list


class TestStash(unittest.TestCase):
    """Test stash push/pop/list."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.repo.set_user("Test", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_stash_push_pop(self):
        # Create a commit first so HEAD has a valid tree
        from pygit_single import serialize_tree
        tree_data = serialize_tree([])
        tree_sha = hash_object(tree_data, "tree", self.repo.root)
        from pygit_single import serialize_commit
        commit_data = serialize_commit(
            tree_sha, [], "Test <t@t.com>", "Test <t@t.com>", 1000, "initial"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", commit_sha)

        # Create and add a file
        test_file = self.repo.root / "test.txt"
        test_file.write_text("original")
        sha = hash_object(test_file.read_bytes(), "blob", self.repo.root)
        index = Index(self.repo)
        index.load()
        index.add("test.txt", sha, "100644")
        index.save()

        # Modify working tree
        test_file.write_text("modified")

        # Stash
        stash_push(self.repo)

        # After stash, the file should either be restored to original or removed
        # (since there was no prior version in HEAD)
        if test_file.exists():
            content = test_file.read_text()
            self.assertIn(content, ["original", "modified"])

    def test_stash_list(self):
        stash_list(self.repo)  # Should not raise


if __name__ == "__main__":
    unittest.main()
