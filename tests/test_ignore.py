"""Tests for .pygitignore matching."""

import shutil
import tempfile
import unittest
from pathlib import Path

from pygit.ignore import load_ignore, is_ignored


class TestIgnore(unittest.TestCase):
    """Test .pygitignore pattern matching."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_glob_pattern(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("*.pyc\n")
        patterns = load_ignore(self.tmpdir)
        self.assertTrue(is_ignored("foo.pyc", patterns))
        self.assertTrue(is_ignored("dir/bar.pyc", patterns))
        self.assertFalse(is_ignored("foo.py", patterns))

    def test_directory_pattern(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("build/\n")
        patterns = load_ignore(self.tmpdir)
        self.assertTrue(is_ignored("build/output.o", patterns))
        self.assertFalse(is_ignored("src/main.py", patterns))

    def test_exact_filename(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("secret.txt\n")
        patterns = load_ignore(self.tmpdir)
        self.assertTrue(is_ignored("secret.txt", patterns))
        self.assertTrue(is_ignored("dir/secret.txt", patterns))
        self.assertFalse(is_ignored("notsecret.txt", patterns))

    def test_comments_ignored(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("# comment\n*.log\n")
        patterns = load_ignore(self.tmpdir)
        self.assertEqual(len(patterns), 1)

    def test_blank_lines_ignored(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("*.log\n\n\n*.tmp\n")
        patterns = load_ignore(self.tmpdir)
        self.assertEqual(len(patterns), 2)

    def test_empty_file(self):
        patterns = load_ignore(self.tmpdir)
        self.assertEqual(len(patterns), 0)

    def test_multiple_patterns(self):
        ignore_file = self.tmpdir / ".pygitignore"
        ignore_file.write_text("*.pyc\n*.pyo\n__pycache__/\n")
        patterns = load_ignore(self.tmpdir)
        self.assertTrue(is_ignored("foo.pyc", patterns))
        self.assertTrue(is_ignored("foo.pyo", patterns))
        self.assertTrue(is_ignored("__pycache__/cache", patterns))


if __name__ == "__main__":
    unittest.main()
