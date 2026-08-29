"""Tests for packfiles and garbage collection."""

import os
import shutil
import tempfile
import unittest

from pygit.repository import Repository
from pygit.objects import hash_object, read_object, serialize_tree, serialize_commit
from pygit.pack import PackWriter, PackReader, gc, find_reachable_objects


class TestPackWriter(unittest.TestCase):
    """Test packfile writing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_write_and_read(self):
        # Create some objects
        sha1 = hash_object(b"content1", "blob", self.repo.root)
        sha2 = hash_object(b"content2", "blob", self.repo.root)

        # Pack them
        writer = PackWriter(self.repo)
        writer.add_object(sha1)
        writer.add_object(sha2)
        writer.write_pack()

        # Read them back
        reader = PackReader(self.repo)
        obj_type, data = reader.read_object(sha1)
        self.assertEqual(obj_type, "blob")
        self.assertEqual(data, b"content1")

        obj_type, data = reader.read_object(sha2)
        self.assertEqual(data, b"content2")


class TestGC(unittest.TestCase):
    """Test garbage collection."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_gc_packs_objects(self):
        # Create objects and a ref so they're reachable
        sha1 = hash_object(b"content1", "blob", self.repo.root)
        sha2 = hash_object(b"content2", "blob", self.repo.root)

        # Create a tree and commit so objects are reachable from a ref
        tree_entries = [("100644", "file1.txt", sha1), ("100644", "file2.txt", sha2)]
        tree_data = serialize_tree(tree_entries)
        tree_sha = hash_object(tree_data, "tree", self.repo.root)

        commit_data = serialize_commit(
            tree_sha, [], "Test <t@t.com>", "Test <t@t.com>", 1000, "test"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", commit_sha)

        # Verify loose objects exist
        loose_dir = self.repo.git_dir / "objects" / sha1[:2]
        self.assertTrue(loose_dir.exists())

        # Run gc
        gc(self.repo)

        # Verify packfile was created
        pack_dir = self.repo.git_dir / "objects" / "pack"
        pack_files = list(pack_dir.glob("*.pack"))
        self.assertTrue(len(pack_files) > 0)

    def test_find_reachable(self):
        # Create a commit
        tree_data = serialize_tree([])
        tree_sha = hash_object(tree_data, "tree", self.repo.root)
        commit_data = serialize_commit(
            tree_sha, [], "Test <t@t.com>", "Test <t@t.com>", 1000, "test"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)

        # Set ref
        self.repo.set_ref("refs/heads/main", commit_sha)

        # Find reachable
        reachable = find_reachable_objects(self.repo)
        self.assertIn(commit_sha, reachable)
        self.assertIn(tree_sha, reachable)


if __name__ == "__main__":
    unittest.main()
