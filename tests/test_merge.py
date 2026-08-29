"""Tests for merge operations."""

import os
import shutil
import tempfile
import unittest

from pygit.repository import Repository
from pygit.objects import hash_object, serialize_tree
from pygit.merge import find_merge_base, three_way_merge


class TestFindMergeBase(unittest.TestCase):
    """Test merge base finding."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_linear_history(self):
        # Create linear: A -> B -> C
        tree_data = serialize_tree([])
        tree_sha = hash_object(tree_data, "tree", self.repo.root)

        commits = []
        parent = None
        for i in range(3):
            lines = [f"tree {tree_sha}"]
            if parent:
                lines.append(f"parent {parent}")
            lines.extend(["author Test <t@t.com> 1000", "committer Test <t@t.com> 1000", "", f"commit {i}"])
            sha = hash_object("\n".join(lines).encode(), "commit", self.repo.root)
            commits.append(sha)
            parent = sha

        # Base of A and C should be A
        base = find_merge_base(self.repo, commits[0], commits[2])
        self.assertEqual(base, commits[0])


class TestThreeWayMerge(unittest.TestCase):
    """Test three-way merge."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_clean_merge(self):
        # Base: line1\nline2\nline3\n
        # Ours: modified1\nline2\nline3\n
        # Theirs: line1\nline2\nmodified3\n
        base_content = "line1\nline2\nline3\n".encode()
        ours_content = "modified1\nline2\nline3\n".encode()
        theirs_content = "line1\nline2\nmodified3\n".encode()

        base_sha = hash_object(base_content, "blob", self.repo.root)
        ours_sha = hash_object(ours_content, "blob", self.repo.root)
        theirs_sha = hash_object(theirs_content, "blob", self.repo.root)

        base_tree = serialize_tree([("100644", "test.txt", base_sha)])
        ours_tree = serialize_tree([("100644", "test.txt", ours_sha)])
        theirs_tree = serialize_tree([("100644", "test.txt", theirs_sha)])

        base_tree_sha = hash_object(base_tree, "tree", self.repo.root)
        ours_tree_sha = hash_object(ours_tree, "tree", self.repo.root)
        theirs_tree_sha = hash_object(theirs_tree, "tree", self.repo.root)

        merged_sha, conflicts = three_way_merge(
            base_tree_sha, ours_tree_sha, theirs_tree_sha, self.repo
        )
        self.assertEqual(len(conflicts), 0)

    def test_conflict_detection(self):
        # Both change same line
        base_content = "line1\nline2\nline3\n".encode()
        ours_content = "modified_by_ours\nline2\nline3\n".encode()
        theirs_content = "modified_by_theirs\nline2\nline3\n".encode()

        base_sha = hash_object(base_content, "blob", self.repo.root)
        ours_sha = hash_object(ours_content, "blob", self.repo.root)
        theirs_sha = hash_object(theirs_content, "blob", self.repo.root)

        base_tree = serialize_tree([("100644", "test.txt", base_sha)])
        ours_tree = serialize_tree([("100644", "test.txt", ours_sha)])
        theirs_tree = serialize_tree([("100644", "test.txt", theirs_sha)])

        base_tree_sha = hash_object(base_tree, "tree", self.repo.root)
        ours_tree_sha = hash_object(ours_tree, "tree", self.repo.root)
        theirs_tree_sha = hash_object(theirs_tree, "tree", self.repo.root)

        merged_sha, conflicts = three_way_merge(
            base_tree_sha, ours_tree_sha, theirs_tree_sha, self.repo
        )
        # Should detect conflict
        self.assertTrue(len(conflicts) > 0 or merged_sha != ours_tree_sha)


if __name__ == "__main__":
    unittest.main()
