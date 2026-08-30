"""Tests for init, add, commit, and log commands."""

import os
import shutil
import tempfile
import unittest

from pygit_single import Repository
from pygit_single import hash_object, read_object, deserialize_commit
from pygit_single import Index


class TestInit(unittest.TestCase):
    """Test repository initialization."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_init_creates_structure(self):
        self.repo.init()
        self.assertTrue((self.repo.git_dir / "HEAD").exists())
        self.assertTrue((self.repo.git_dir / "config").exists())
        self.assertTrue((self.repo.git_dir / "objects").exists())
        self.assertTrue((self.repo.git_dir / "refs" / "heads").exists())
        self.assertTrue((self.repo.git_dir / "refs" / "tags").exists())
        self.assertTrue((self.repo.git_dir / "logs").exists())

    def test_init_head_content(self):
        self.repo.init()
        head = self.repo.get_head()
        self.assertEqual(head, "ref: refs/heads/main")

    def test_init_idempotent(self):
        self.repo.init()
        self.repo.init()  # Should not raise


class TestAdd(unittest.TestCase):
    """Test adding files to index."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.index = Index(self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_add_file(self):
        # Create a file
        test_file = self.repo.root / "hello.txt"
        test_file.write_text("hello world")

        # Add it
        data = test_file.read_bytes()
        sha = hash_object(data, "blob", self.repo.root)
        self.index.load()
        self.index.add("hello.txt", sha, "100644")
        self.index.save()

        # Verify
        self.index.load()
        entry = self.index.get_entry("hello.txt")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["sha"], sha)

    def test_add_multiple_files(self):
        for name in ["a.txt", "b.txt", "c.txt"]:
            (self.repo.root / name).write_text(f"content of {name}")
            data = (self.repo.root / name).read_bytes()
            sha = hash_object(data, "blob", self.repo.root)
            self.index.load()
            self.index.add(name, sha, "100644")
            self.index.save()

        self.index.load()
        self.assertEqual(len(self.index.get_entries()), 3)


class TestCommit(unittest.TestCase):
    """Test committing changes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.repo.set_user("Test User", "test@example.com")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_commit_creates_objects(self):
        # Create and add a file
        test_file = self.repo.root / "test.txt"
        test_file.write_text("test content")
        data = test_file.read_bytes()
        sha = hash_object(data, "blob", self.repo.root)

        index = Index(self.repo)
        index.load()
        index.add("test.txt", sha, "100644")
        index.save()

        # Build tree
        root_tree_sha = self.repo.build_tree_from_index(index)

        # Create commit
        import time
        commit_data = serialize_commit(
            root_tree_sha, [], "Test User <test@example.com>",
            "Test User <test@example.com>", int(time.time()), "Initial commit"
        )
        commit_sha = hash_object(commit_data, "commit", self.repo.root)

        # Verify
        obj_type, data = read_object(commit_sha, self.repo.root)
        self.assertEqual(obj_type, "commit")
        commit = deserialize_commit(data)
        self.assertEqual(commit["tree"], root_tree_sha)
        self.assertEqual(commit["message"], "Initial commit")


def serialize_commit(tree_sha, parents, author, committer, epoch, message):
    """Helper for test - same as objects.serialize_commit."""
    lines = []
    lines.append(f"tree {tree_sha}")
    for parent in parents:
        lines.append(f"parent {parent}")
    lines.append(f"author {author} {epoch}")
    lines.append(f"committer {committer} {epoch}")
    lines.append("")
    lines.append(message)
    return "\n".join(lines).encode("utf-8")


class TestLog(unittest.TestCase):
    """Test commit log."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.repo.set_user("Test User", "test@example.com")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_log_walks_parents(self):
        # Create multiple commits
        commits = []
        parent_sha = None

        for i in range(3):
            from pygit_single import serialize_tree
            tree_data = serialize_tree([])
            tree_sha = hash_object(tree_data, "tree", self.repo.root)

            import time
            parents = [parent_sha] if parent_sha else []
            commit_data = serialize_commit(
                tree_sha, parents, "Test User <test@example.com>",
                "Test User <test@example.com>", int(time.time()), f"Commit {i}"
            )
            sha = hash_object(commit_data, "commit", self.repo.root)
            commits.append(sha)
            parent_sha = sha

        # Verify chain
        for i, sha in enumerate(commits):
            obj_type, data = read_object(sha, self.repo.root)
            commit = deserialize_commit(data)
            if i > 0:
                self.assertEqual(commit["parents"], [commits[i - 1]])
            else:
                self.assertEqual(commit["parents"], [])


if __name__ == "__main__":
    unittest.main()
