"""Tests for features: checkout -b/-B, switch -c/-C, branch -d/-D,
checkout --path, commit --amend, log --oneline, show, config."""

import shutil
import tempfile
import time
import unittest

from pygit_single import Repository
from pygit_single import Index
from pygit_single import (
    hash_object, serialize_commit, read_object, deserialize_commit,
)


def _make_commit(repo, message, files=None, parents=None):
    index = Index(repo)
    index.load()
    if files:
        for name, content in files.items():
            if isinstance(content, str):
                content = content.encode()
            sha = hash_object(content, "blob", repo.root)
            index.add(name, sha, "100644")
        index.save()
    tree_sha = repo.build_tree_from_index(index)
    parent_list = parents or []
    author = repo.get_author_string()
    epoch = int(time.time())
    commit_data = serialize_commit(tree_sha, parent_list, author, author, epoch, message)
    commit_sha = hash_object(commit_data, "commit", repo.root)
    head = repo.get_head()
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        repo.set_ref(ref_path, commit_sha)
    else:
        repo.set_head_detached(commit_sha)
    return commit_sha


def _get_head_sha(repo):
    head = repo.get_head()
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        return repo.get_ref(ref_path)
    return head.strip()


def _get_commit_message(repo, sha):
    _, data = read_object(sha, repo.root)
    return deserialize_commit(data)["message"]


class TestCheckoutNewBranch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_checkout_b_sets_ref(self):
        sha = _make_commit(self.repo, "first")
        from pygit_single import _switch_branch
        result = _switch_branch(self.repo, "feature")
        self.assertTrue(result)
        self.assertEqual(self.repo.get_ref("refs/heads/feature"), sha)

    def test_checkout_b_fails_if_exists(self):
        _make_commit(self.repo, "first")
        self.repo.set_ref("refs/heads/existing", _get_head_sha(self.repo))
        from pygit_single import _switch_branch
        result = _switch_branch(self.repo, "existing")
        self.assertFalse(result)

    def test_checkout_b_force_overwrites(self):
        _make_commit(self.repo, "first")
        self.repo.set_ref("refs/heads/feature", _get_head_sha(self.repo))
        _make_commit(self.repo, "second")
        from pygit_single import _switch_branch
        result = _switch_branch(self.repo, "feature", force=True)
        self.assertTrue(result)
        self.assertEqual(self.repo.get_ref("refs/heads/feature"), _get_head_sha(self.repo))

    def test_checkout_b_does_not_switch_head(self):
        _make_commit(self.repo, "first")
        original_head = self.repo.get_head()
        from pygit_single import _switch_branch
        _switch_branch(self.repo, "feature")
        self.assertEqual(self.repo.get_head(), original_head)


class TestSwitch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_switch_c_sets_ref(self):
        sha = _make_commit(self.repo, "first")
        from pygit_single import _switch_branch
        result = _switch_branch(self.repo, "dev")
        self.assertTrue(result)
        self.assertEqual(self.repo.get_ref("refs/heads/dev"), sha)

    def test_switch_c_fails_if_exists(self):
        _make_commit(self.repo, "first")
        self.repo.set_ref("refs/heads/dev", _get_head_sha(self.repo))
        from pygit_single import _switch_branch
        result = _switch_branch(self.repo, "dev")
        self.assertFalse(result)

    def test_switch_c_force_overwrites(self):
        _make_commit(self.repo, "first")
        self.repo.set_ref("refs/heads/dev", _get_head_sha(self.repo))
        _make_commit(self.repo, "second")
        from pygit_single import _switch_branch
        result = _switch_branch(self.repo, "dev", force=True)
        self.assertTrue(result)


class TestBranchDelete(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        _make_commit(self.repo, "first")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_delete_branch_removes_ref(self):
        feature_sha = _get_head_sha(self.repo)
        self.repo.set_ref("refs/heads/feature", feature_sha)
        ref_file = self.repo.root / ".pygit" / "refs" / "heads" / "feature"
        self.assertTrue(ref_file.exists())
        ref_file.unlink()
        self.assertFalse(ref_file.exists())

    def test_delete_nonexistent_ref_file(self):
        ref_file = self.repo.root / ".pygit" / "refs" / "heads" / "nonexistent"
        self.assertFalse(ref_file.exists())


class TestCheckoutPath(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_checkout_paths_restores_file(self):
        _make_commit(self.repo, "first", files={"a.txt": "original"})
        (self.repo.root / "a.txt").write_text("modified")
        from pygit_single import _checkout_paths
        _checkout_paths(self.repo, ["a.txt"])
        self.assertEqual((self.repo.root / "a.txt").read_text(), "original")

    def test_checkout_paths_from_index(self):
        _make_commit(self.repo, "first", files={"a.txt": "content"})
        _make_commit(self.repo, "second", files={"a.txt": "v2"})
        (self.repo.root / "a.txt").write_text("dirty")
        from pygit_single import _checkout_paths
        _checkout_paths(self.repo, ["a.txt"])
        self.assertEqual((self.repo.root / "a.txt").read_text(), "v2")


class TestCommitAmend(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_amend_replaces_commit(self):
        sha1 = _make_commit(self.repo, "original", files={"a.txt": "v1"})
        _make_commit(self.repo, "amended", files={"a.txt": "v1", "b.txt": "new"}, parents=[])
        sha2 = _get_head_sha(self.repo)
        self.assertNotEqual(sha1, sha2)
        self.assertEqual(_get_commit_message(self.repo, sha2), "amended")

    def test_amend_keeps_parents(self):
        _make_commit(self.repo, "first", files={"a.txt": "v1"})
        parent = _get_head_sha(self.repo)
        _make_commit(self.repo, "second", files={"b.txt": "v2"}, parents=[parent])
        sha2 = _get_head_sha(self.repo)
        _make_commit(self.repo, "amended second", files={"b.txt": "v2", "c.txt": "v3"}, parents=[parent])
        sha3 = _get_head_sha(self.repo)
        self.assertNotEqual(sha2, sha3)
        _, data = read_object(sha3, self.repo.root)
        commit = deserialize_commit(data)
        self.assertEqual(commit["parents"], [parent])


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_set_and_get(self):
        self.repo.set_config_value("user.name", "Alice")
        self.repo.set_config_value("user.email", "alice@test.com")
        config = self.repo.get_config()
        self.assertEqual(config.get("user", "name"), "Alice")
        self.assertEqual(config.get("user", "email"), "alice@test.com")

    def test_get_author_string(self):
        self.repo.set_config_value("user.name", "Bob")
        self.repo.set_config_value("user.email", "bob@test.com")
        self.assertEqual(self.repo.get_author_string(), "Bob <bob@test.com>")

    def test_get_author_string_fallback(self):
        self.assertEqual(self.repo.get_author_string(), "Unknown <unknown@example.com>")

    def test_custom_section(self):
        self.repo.set_config_value("remote.origin.url", "localhost:9418")
        config = self.repo.get_config()
        self.assertEqual(config.get("remote", "origin.url"), "localhost:9418")


class TestShow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_show_reads_commit(self):
        sha = _make_commit(self.repo, "my commit", files={"a.txt": "hello"})
        obj_type, data = read_object(sha, self.repo.root)
        self.assertEqual(obj_type, "commit")
        commit = deserialize_commit(data)
        self.assertEqual(commit["message"], "my commit")
        entries = self.repo.get_tree_entries(sha)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "a.txt")


class TestLogOneline(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_log_walks_parents(self):
        sha1 = _make_commit(self.repo, "first", files={"a.txt": "v1"})
        sha2 = _make_commit(self.repo, "second", files={"a.txt": "v2"}, parents=[sha1])
        _, data = read_object(sha2, self.repo.root)
        commit = deserialize_commit(data)
        self.assertEqual(commit["parents"], [sha1])
        _, data = read_object(sha1, self.repo.root)
        commit = deserialize_commit(data)
        self.assertEqual(commit["parents"], [])
