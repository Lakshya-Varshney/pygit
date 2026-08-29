"""Tests for pygit object model.

Covers: hash_object, read_object, serialize/deserialize for blob, tree, commit, tag.
"""

import os
import tempfile
import unittest
from pathlib import Path

from pygit.objects import (
    hash_object, read_object,
    serialize_blob, deserialize_blob,
    serialize_tree, deserialize_tree,
    serialize_commit, deserialize_commit,
    serialize_tag, deserialize_tag,
)


class TestHashReadObject(unittest.TestCase):
    """Test hash_object and read_object round-trip."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, ".pygit", "objects"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_blob_round_trip(self):
        sha = hash_object(b"hello world", "blob", self.tmpdir)
        self.assertEqual(len(sha), 64)
        obj_type, data = read_object(sha, self.tmpdir)
        self.assertEqual(obj_type, "blob")
        self.assertEqual(data, b"hello world")

    def test_empty_blob(self):
        sha = hash_object(b"", "blob", self.tmpdir)
        obj_type, data = read_object(sha, self.tmpdir)
        self.assertEqual(data, b"")

    def test_binary_blob(self):
        content = bytes(range(256))
        sha = hash_object(content, "blob", self.tmpdir)
        obj_type, data = read_object(sha, self.tmpdir)
        self.assertEqual(data, content)

    def test_nonexistent_object(self):
        with self.assertRaises(FileNotFoundError):
            read_object("0" * 64, self.tmpdir)


class TestBlobSerialization(unittest.TestCase):
    """Test blob serialize/deserialize."""

    def test_round_trip(self):
        data = b"test content"
        raw = serialize_blob(data)
        obj_type, result = deserialize_blob(raw)
        self.assertEqual(obj_type, "blob")
        self.assertEqual(result, data)

    def test_empty(self):
        raw = serialize_blob(b"")
        _, result = deserialize_blob(raw)
        self.assertEqual(result, b"")

    def test_unicode(self):
        text = "unicode text"
        raw = serialize_blob(text.encode("utf-8"))
        _, result = deserialize_blob(raw)
        self.assertEqual(result.decode("utf-8"), text)


class TestTreeSerialization(unittest.TestCase):
    """Test tree serialize/deserialize."""

    def test_round_trip(self):
        entries = [
            ("100644", "file.txt", "a" * 64),
            ("40000", "subdir", "b" * 64),
        ]
        raw = serialize_tree(entries)
        result = deserialize_tree(raw)
        self.assertEqual(len(result), 2)
        # Should be sorted by name (file.txt < subdir)
        self.assertEqual(result[0], ("100644", "file.txt", "a" * 64))
        self.assertEqual(result[1], ("40000", "subdir", "b" * 64))

    def test_single_entry(self):
        entries = [("100644", "only.txt", "c" * 64)]
        raw = serialize_tree(entries)
        result = deserialize_tree(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "100644")
        self.assertEqual(result[0][1], "only.txt")


class TestCommitSerialization(unittest.TestCase):
    """Test commit serialize/deserialize."""

    def test_root_commit(self):
        raw = serialize_commit(
            "a" * 64, [], "Author <a@b.com>", "Committer <c@d.com>",
            1234567890, "Initial commit"
        )
        result = deserialize_commit(raw)
        self.assertEqual(result["tree"], "a" * 64)
        self.assertEqual(result["parents"], [])
        self.assertEqual(result["author"], "Author <a@b.com>")
        self.assertEqual(result["message"], "Initial commit")

    def test_single_parent(self):
        raw = serialize_commit(
            "a" * 64, ["b" * 64], "Author <a@b.com>", "Committer <c@d.com>",
            1234567890, "Second commit"
        )
        result = deserialize_commit(raw)
        self.assertEqual(result["parents"], ["b" * 64])

    def test_merge_commit(self):
        raw = serialize_commit(
            "a" * 64, ["b" * 64, "c" * 64], "Author <a@b.com>", "Committer <c@d.com>",
            1234567890, "Merge commit"
        )
        result = deserialize_commit(raw)
        self.assertEqual(len(result["parents"]), 2)


class TestTagSerialization(unittest.TestCase):
    """Test tag serialize/deserialize."""

    def test_round_trip(self):
        raw = serialize_tag(
            "a" * 64, "commit", "Tagger <t@b.com>", "v1.0",
            1234567890, "Release 1.0"
        )
        result = deserialize_tag(raw)
        self.assertEqual(result["object"], "a" * 64)
        self.assertEqual(result["type"], "commit")
        self.assertEqual(result["tag"], "v1.0")
        self.assertEqual(result["tagger"], "Tagger <t@b.com>")
        self.assertEqual(result["message"], "Release 1.0")


if __name__ == "__main__":
    unittest.main()
