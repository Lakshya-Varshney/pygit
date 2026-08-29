"""Tests for blame functionality."""

import os
import shutil
import tempfile
import unittest

from pygit.repository import Repository
from pygit.objects import hash_object, serialize_tree, serialize_commit
from pygit.diff import blame


class TestBlame(unittest.TestCase):
    """Test blame command."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.repo.set_user("Test", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_blame_attributes_lines(self):
        # Create a commit with a file
        content = b"line1\nline2\nline3\n"
        blob_sha = hash_object(content, "blob", self.repo.root)
        tree_entries = [("100644", "test.txt", blob_sha)]
        tree_data = serialize_tree(tree_entries)
        tree_sha = hash_object(tree_data, "tree", self.repo.root)

        commit_data = serialize_commit(
            tree_sha, [], "Test <t@t.com>", "Test <t@t.com>", 1000, "initial"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", commit_sha)

        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            blame(self.repo, "test.txt")
        output = f.getvalue()
        self.assertIn("line1", output)
        self.assertIn("line2", output)
        self.assertIn("line3", output)


if __name__ == "__main__":
    unittest.main()
