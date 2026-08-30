"""Tests for pygit.colors — ANSI color output helpers."""

import io
import unittest
from pygit_single import (
    should_color, colorize, colorize_diff_line, colorize_status_item,
    RED, GREEN, CYAN, RESET
)


class TestShouldColor(unittest.TestCase):
    def test_always_returns_true(self):
        self.assertTrue(should_color("always", io.StringIO()))

    def test_never_returns_false(self):
        self.assertFalse(should_color("never", io.StringIO()))

    def test_auto_with_non_tty(self):
        # StringIO is not a tty
        self.assertFalse(should_color("auto", io.StringIO()))

    def test_auto_with_none_uses_isatty(self):
        self.assertFalse(should_color(None, io.StringIO()))

    def test_always_overrides_non_tty(self):
        self.assertTrue(should_color("always", io.StringIO()))


class TestColorize(unittest.TestCase):
    def test_wraps_in_color(self):
        result = colorize("hello", RED)
        self.assertEqual(result, f"{RED}hello{RESET}")

    def test_no_color_returns_plain(self):
        result = colorize("hello", "")
        self.assertEqual(result, "hello")

    def test_empty_string_color(self):
        result = colorize("test", "")
        self.assertNotIn("\033", result)


class TestColorizeDiffLine(unittest.TestCase):
    def test_added_line_is_green(self):
        result = colorize_diff_line("+added\n", True)
        self.assertIn(GREEN, result)
        self.assertIn("+added\n", result)

    def test_removed_line_is_red(self):
        result = colorize_diff_line("-removed\n", True)
        self.assertIn(RED, result)

    def test_hunk_header_is_cyan(self):
        result = colorize_diff_line("@@ -1,3 +1,4 @@\n", True)
        self.assertIn(CYAN, result)

    def test_context_line_no_color(self):
        result = colorize_diff_line(" unchanged\n", True)
        self.assertNotIn("\033", result)

    def test_triple_plus_no_color(self):
        result = colorize_diff_line("+++ a/file\n", True)
        self.assertNotIn("\033", result)

    def test_triple_minus_no_color(self):
        result = colorize_diff_line("--- a/file\n", True)
        self.assertNotIn("\033", result)

    def test_no_color_returns_plain(self):
        result = colorize_diff_line("+added\n", False)
        self.assertEqual(result, "+added\n")
        self.assertNotIn("\033", result)


class TestColorizeStatusItem(unittest.TestCase):
    def test_staged_is_green(self):
        result = colorize_status_item("\tnew file:   foo.py", "staged", True)
        self.assertIn(GREEN, result)

    def test_modified_is_red(self):
        result = colorize_status_item("\tmodified:   foo.py", "modified", True)
        self.assertIn(RED, result)

    def test_untracked_is_red(self):
        result = colorize_status_item("\tfoo.py", "untracked", True)
        self.assertIn(RED, result)

    def test_no_color_returns_plain(self):
        result = colorize_status_item("\tfoo.py", "untracked", False)
        self.assertEqual(result, "\tfoo.py")
        self.assertNotIn("\033", result)


if __name__ == "__main__":
    unittest.main()
