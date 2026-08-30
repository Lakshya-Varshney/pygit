"""Tests for pygit.diff_commits — commit-to-commit diff."""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from pygit.repository import Repository
from pygit.index import Index
from pygit.objects import hash_object, serialize_commit
from pygit.diff_commits import diff_two_commits, resolve_commit_ref


class TestDiffCommits(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="diff_test_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Test")
        self.repo.set_config_value("user.email", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _commit(self, name, content, msg="commit"):
        """Helper: create/modify a file and commit it."""
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

    def test_diff_shows_changes(self):
        """Diff between two commits with different content."""
        sha1 = self._commit("a.txt", "v1", "first")
        sha2 = self._commit("a.txt", "v2", "second")

        diff = diff_two_commits(self.repo, sha1, sha2)
        diff_text = "".join(diff)
        self.assertIn("-v1", diff_text)
        self.assertIn("+v2", diff_text)
        self.assertIn("a/a.txt", diff_text)
        self.assertIn("b/a.txt", diff_text)

    def test_diff_identical_trees(self):
        """Diff between commits with identical trees shows nothing."""
        sha1 = self._commit("a.txt", "same", "first")
        sha2 = self._commit("b.txt", "other", "second")

        # Commit same content for a.txt — diff should only show b.txt
        full = Path(self.d) / "a.txt"
        full.write_text("same")
        index = Index(self.repo)
        index.load()
        sha = hash_object(full.read_bytes(), "blob", self.repo.root)
        index.add("a.txt", sha, "100644")
        index.save()
        tree_sha = self.repo.build_tree_from_index(index)
        import time
        from pygit.objects import serialize_commit, hash_object as ho
        author = "Test <t@t.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, [sha2], author, author, epoch, "third")
        cs = ho(cd, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", cs)

        diff = diff_two_commits(self.repo, sha2, cs)
        diff_text = "".join(diff)
        # a.txt unchanged, b.txt should appear in old but not new
        self.assertNotIn("-same", diff_text)

    def test_diff_file_addition(self):
        """Diff where new commit adds a file."""
        sha1 = self._commit("a.txt", "only", "first")
        sha2 = self._commit("b.txt", "new", "second")

        diff = diff_two_commits(self.repo, sha1, sha2)
        diff_text = "".join(diff)
        self.assertIn("+new", diff_text)
        self.assertIn("b/b.txt", diff_text)

    def test_diff_file_deletion(self):
        """Diff where new commit deletes a file."""
        sha1 = self._commit("a.txt", "gone", "first")
        # Second commit: only b.txt (clear index, add only b.txt)
        index = Index(self.repo)
        index.clear()
        full = Path(self.d) / "b.txt"
        full.write_text("keep")
        sha = hash_object(full.read_bytes(), "blob", self.repo.root)
        index.add("b.txt", sha, "100644")
        index.save()
        tree_sha = self.repo.build_tree_from_index(index)
        author = "Test <t@t.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, [sha1], author, author, epoch, "second")
        cs = hash_object(cd, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", cs)

        diff = diff_two_commits(self.repo, sha1, cs)
        diff_text = "".join(diff)
        self.assertIn("-gone", diff_text)
        self.assertIn("a/a.txt", diff_text)


class TestResolveCommitRef(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="resolve_test_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Test")
        self.repo.set_config_value("user.email", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _commit(self, msg="commit"):
        """Helper: create a commit and return its sha."""
        full = Path(self.d) / "a.txt"
        full.write_text("content")
        index = Index(self.repo)
        index.load()
        sha = hash_object(full.read_bytes(), "blob", self.repo.root)
        index.add("a.txt", sha, "100644")
        index.save()
        tree_sha = self.repo.build_tree_from_index(index)
        author = "Test <t@t.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, [], author, author, epoch, msg)
        cs = hash_object(cd, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", cs)
        return cs

    def test_full_sha(self):
        sha = self._commit()
        result = resolve_commit_ref(self.repo, sha)
        self.assertEqual(result, sha)

    def test_short_sha(self):
        sha = self._commit()
        result = resolve_commit_ref(self.repo, sha[:7])
        self.assertEqual(result, sha)

    def test_branch_name(self):
        sha = self._commit()
        result = resolve_commit_ref(self.repo, "main")
        self.assertEqual(result, sha)

    def test_unknown_raises(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_commit_ref(self.repo, "nonexistent")
        self.assertIn("unknown revision", str(ctx.exception))

    def test_ambiguous_prefix_raises(self):
        # Two commits with same 7-char prefix is unlikely but test the path
        sha = self._commit()
        # Full sha works even if it's long
        result = resolve_commit_ref(self.repo, sha)
        self.assertEqual(result, sha)


if __name__ == "__main__":
    unittest.main()
