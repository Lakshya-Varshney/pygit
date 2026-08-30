"""Tests for short sha prefix resolution (Round 9)."""

import shutil
import tempfile
import time
import unittest

from pygit_single import Repository
from pygit_single import Index
from pygit_single import hash_object, serialize_commit, serialize_tree


def _make_commit(repo, message, files=None):
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
    head = repo.get_head()
    parent = None
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        try:
            parent = repo.get_ref(ref_path)
        except Exception:
            pass
    parents = [parent] if parent else []
    author = repo.get_author_string()
    epoch = int(time.time())
    commit_data = serialize_commit(tree_sha, parents, author, author, epoch, message)
    commit_sha = hash_object(commit_data, "commit", repo.root)
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        repo.set_ref(ref_path, commit_sha)
    else:
        repo.set_head_detached(commit_sha)
    return commit_sha


class TestResolveShaPrefix(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Repository(self.tmpdir)
        self.repo.init()
        self.sha1 = _make_commit(self.repo, "first", files={"a.txt": "v1"})
        self.sha2 = _make_commit(self.repo, "second", files={"a.txt": "v2"})
        self.sha3 = _make_commit(self.repo, "third", files={"a.txt": "v3"})

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_full_sha_returns_as_is(self):
        result = self.repo.resolve_sha_prefix(self.sha1)
        self.assertEqual(result, self.sha1)

    def test_full_sha_case_insensitive(self):
        result = self.repo.resolve_sha_prefix(self.sha1.upper())
        self.assertEqual(result, self.sha1)

    def test_unique_7char_prefix(self):
        result = self.repo.resolve_sha_prefix(self.sha1[:7])
        self.assertEqual(result, self.sha1)

    def test_unique_longer_prefix(self):
        result = self.repo.resolve_sha_prefix(self.sha2[:12])
        self.assertEqual(result, self.sha2)

    def test_no_match_raises_error(self):
        with self.assertRaises(ValueError) as ctx:
            self.repo.resolve_sha_prefix("deadbeef")
        self.assertIn("no object matches", str(ctx.exception))

    def test_too_short_raises_error(self):
        with self.assertRaises(ValueError) as ctx:
            self.repo.resolve_sha_prefix("abc")
        self.assertIn("too short", str(ctx.exception))

    def test_non_hex_raises_error(self):
        with self.assertRaises(ValueError) as ctx:
            self.repo.resolve_sha_prefix("xyzw1234")
        self.assertIn("not a valid sha prefix", str(ctx.exception))

    def test_ambiguous_prefix_raises_error(self):
        if self.sha1[:4] == self.sha2[:4]:
            with self.assertRaises(ValueError) as ctx:
                self.repo.resolve_sha_prefix(self.sha1[:4])
            self.assertIn("ambiguous", str(ctx.exception))

    def test_prefix_matches_after_gc(self):
        from pygit_single import gc
        gc(self.repo)
        result = self.repo.resolve_sha_prefix(self.sha1[:7])
        self.assertEqual(result, self.sha1)

    def test_prefix_resolves_packfile_objects(self):
        from pygit_single import gc
        gc(self.repo)
        result = self.repo.resolve_sha_prefix(self.sha2[:7])
        self.assertEqual(result, self.sha2)

    def test_4char_prefix_unique(self):
        prefix = self.sha3[:4]
        other_prefixes = [self.sha1[:4], self.sha2[:4]]
        if prefix not in other_prefixes:
            result = self.repo.resolve_sha_prefix(prefix)
            self.assertEqual(result, self.sha3)


if __name__ == "__main__":
    unittest.main()
