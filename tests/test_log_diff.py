"""Tests for pygit remote list, log author filter, and diff stat."""
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from pygit.repository import Repository
from pygit.index import Index
from pygit.objects import hash_object, serialize_commit
from pygit.colors import YELLOW


class TestRemoteList(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="r12_remote_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Test")
        self.repo.set_config_value("user.email", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_remote_list_via_argparse(self):
        from pygit.__main__ import cmd_remote
        import argparse
        self.repo.add_remote("origin", "localhost:9418")
        self.repo.add_remote("upstream", "example.com:9418")
        args = argparse.Namespace(remote_action="list", name=None, address=None, verbose=False)
        cmd_remote(args)

    def test_remote_verbose_via_argparse(self):
        from pygit.__main__ import cmd_remote
        import argparse
        self.repo.add_remote("origin", "localhost:9418")
        args = argparse.Namespace(remote_action=None, name=None, address=None, verbose=True)
        cmd_remote(args)

    def test_remote_bare_via_argparse(self):
        from pygit.__main__ import cmd_remote
        import argparse
        self.repo.add_remote("origin", "localhost:9418")
        args = argparse.Namespace(remote_action=None, name=None, address=None, verbose=False)
        cmd_remote(args)


class TestLogAuthor(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="r12_log_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Alice")
        self.repo.set_config_value("user.email", "alice@test.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _commit(self, name, content, author_name="Alice", msg="commit"):
        full = Path(self.d) / name
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        index = Index(self.repo)
        index.load()
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
        author = f"{author_name} <{author_name.lower()}@test.com>"
        epoch = int(time.time())
        cd = serialize_commit(tree_sha, parents, author, author, epoch, msg)
        cs = hash_object(cd, "commit", self.repo.root)
        self.repo.set_ref("refs/heads/main", cs)
        return cs

    def test_author_filter(self):
        self._commit("a.txt", "v1", "Alice", "alice commit")
        self._commit("b.txt", "v2", "Bob", "bob commit")
        self._commit("c.txt", "v3", "Alice", "alice commit 2")

        from pygit.log_filter import walk_commits
        commits = list(walk_commits(self.repo, self.repo.get_ref("refs/heads/main")))
        alice_commits = [c for _, c in commits if "Alice" in c["author"]]
        self.assertEqual(len(alice_commits), 2)

    def test_author_case_insensitive(self):
        self._commit("a.txt", "v1", "Alice", "alice commit")
        self._commit("b.txt", "v2", "Bob", "bob commit")

        from pygit.log_filter import walk_commits
        commits = list(walk_commits(self.repo, self.repo.get_ref("refs/heads/main")))
        alice_commits = [c for _, c in commits if "alice" in c["author"].lower()]
        self.assertEqual(len(alice_commits), 1)


class TestDiffStat(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="r12_stat_")
        self.repo = Repository(self.d)
        self.repo.init()
        self.repo.set_config_value("user.name", "Test")
        self.repo.set_config_value("user.email", "t@t.com")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _commit(self, name, content, msg="commit"):
        full = Path(self.d) / name
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        index = Index(self.repo)
        index.load()
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

    def test_compute_stat(self):
        from pygit.__main__ import _compute_stat
        diff_lines = [
            "diff --git a/a.txt b/a.txt",
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -1,3 +1,5 @@",
            " line1",
            "+new line",
            "+another new",
            " line2",
            "-old line",
            " line3",
        ]
        file_stats, total_ins, total_del = _compute_stat(diff_lines)
        self.assertEqual(len(file_stats), 1)
        self.assertEqual(file_stats[0], ("a.txt", 2, 1))
        self.assertEqual(total_ins, 2)
        self.assertEqual(total_del, 1)

    def test_compute_stat_multi_file(self):
        from pygit.__main__ import _compute_stat
        diff_lines = [
            "diff --git a/a.txt b/a.txt",
            "--- a/a.txt",
            "+++ b/a.txt",
            "@@ -1,2 +1,3 @@",
            " line1",
            "+new a",
            "diff --git a/b.txt b/b.txt",
            "--- a/b.txt",
            "+++ b/b.txt",
            "@@ -1,2 +1,1 @@",
            " line1",
            "-deleted b",
        ]
        file_stats, total_ins, total_del = _compute_stat(diff_lines)
        self.assertEqual(len(file_stats), 2)
        self.assertEqual(total_ins, 1)
        self.assertEqual(total_del, 1)


if __name__ == "__main__":
    unittest.main()
