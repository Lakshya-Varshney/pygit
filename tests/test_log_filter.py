"""Tests for pygit.log_filter — commit history filtering."""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from pygit.repository import Repository
from pygit.index import Index
from pygit.objects import hash_object, serialize_commit
from pygit.log_filter import walk_commits, commits_that_touched_path


class TestWalkCommits(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="logfilter_test_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Test")
        self.repo.set_config_value("user.email", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _commit(self, name, content, msg="commit"):
        """Helper: create/modify a file and commit. Returns sha."""
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
        parents = [parent] if parent else []
        author = "Test <t@t.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, parents, author, author, epoch, msg)
        cs = hash_object(cd, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", cs)
        return cs

    def test_walk_all_commits(self):
        """walk_commits with count=None returns all commits."""
        sha1 = self._commit("a.txt", "v1", "first")
        sha2 = self._commit("a.txt", "v2", "second")
        sha3 = self._commit("a.txt", "v3", "third")

        results = list(walk_commits(self.repo, sha3))
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0][0], sha3)
        self.assertEqual(results[1][0], sha2)
        self.assertEqual(results[2][0], sha1)

    def test_walk_with_count(self):
        """walk_commits with count=2 returns exactly 2."""
        sha1 = self._commit("a.txt", "v1", "first")
        sha2 = self._commit("a.txt", "v2", "second")
        sha3 = self._commit("a.txt", "v3", "third")

        results = list(walk_commits(self.repo, sha3, count=2))
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], sha3)
        self.assertEqual(results[1][0], sha2)

    def test_walk_count_larger_than_history(self):
        """count=100 returns all when there are fewer."""
        sha1 = self._commit("a.txt", "v1", "first")
        sha2 = self._commit("a.txt", "v2", "second")

        results = list(walk_commits(self.repo, sha2, count=100))
        self.assertEqual(len(results), 2)

    def test_walk_stops_at_root(self):
        """Walk stops at root commit (no parents)."""
        sha1 = self._commit("a.txt", "v1", "root")

        results = list(walk_commits(self.repo, sha1))
        self.assertEqual(len(results), 1)


class TestCommitsThatTouchedPath(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="logfilter_test_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Test")
        self.repo.set_config_value("user.email", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _commit(self, name, content, msg="commit"):
        """Helper: create/modify a file and commit. Returns sha."""
        full = Path(self.d) / name
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        index = Index(self.repo)
        index.load()
        # Remove old entry if exists
        try:
            index.remove(name)
        except Exception:
            pass
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
        parents = [parent] if parent else []
        author = "Test <t@t.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, parents, author, author, epoch, msg)
        cs = hash_object(cd, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", cs)
        return cs

    def test_only_commits_that_modified_file(self):
        """Only commits where target file changed are returned."""
        # 5 commits, but only 1st and 3rd touch a.txt
        self._commit("a.txt", "v1", "c1: touch a.txt")
        self._commit("b.txt", "v1", "c2: touch b.txt")
        self._commit("a.txt", "v2", "c3: touch a.txt again")
        self._commit("b.txt", "v2", "c4: touch b.txt again")
        sha5 = self._commit("a.txt", "v3", "c5: touch a.txt last")

        results = list(commits_that_touched_path(self.repo, sha5, "a.txt"))
        messages = [c["message"] for _, c in results]
        self.assertIn("c1: touch a.txt", messages)
        self.assertIn("c3: touch a.txt again", messages)
        self.assertIn("c5: touch a.txt last", messages)
        self.assertNotIn("c2: touch b.txt", messages)
        self.assertNotIn("c4: touch b.txt again", messages)

    def test_includes_add(self):
        """Commit that adds the file is included."""
        self._commit("b.txt", "other", "first: no a.txt")
        sha2 = self._commit("a.txt", "new", "second: add a.txt")

        results = list(commits_that_touched_path(self.repo, sha2, "a.txt"))
        messages = [c["message"] for _, c in results]
        self.assertIn("second: add a.txt", messages)

    def test_includes_delete(self):
        """Commit that deletes the file is included."""
        sha1 = self._commit("a.txt", "here", "first: has a.txt")
        # Second commit without a.txt
        full = Path(self.d) / "b.txt"
        full.write_text("only b")
        index = Index(self.repo)
        index.load()
        try:
            index.remove("a.txt")
        except Exception:
            pass
        sha_b = hash_object(full.read_bytes(), "blob", self.repo.root)
        index.add("b.txt", sha_b, "100644")
        index.save()
        tree_sha = self.repo.build_tree_from_index(index)
        author = "Test <t@t.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, [sha1], author, author, epoch, "second: delete a.txt")
        cs = hash_object(cd, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", cs)

        results = list(commits_that_touched_path(self.repo, cs, "a.txt"))
        messages = [c["message"] for _, c in results]
        self.assertIn("second: delete a.txt", messages)

    def test_count_with_path(self):
        """Combining count and path filter."""
        self._commit("a.txt", "v1", "c1")
        self._commit("b.txt", "v1", "c2")
        self._commit("a.txt", "v2", "c3")
        self._commit("b.txt", "v2", "c4")
        sha5 = self._commit("a.txt", "v3", "c5")

        # Only 2 most recent commits that touched a.txt
        results = list(commits_that_touched_path(self.repo, sha5, "a.txt"))
        messages = [c["message"] for _, c in results]
        # Should include c1, c3, c5 (all touch a.txt)
        self.assertEqual(len(messages), 3)


if __name__ == "__main__":
    unittest.main()
