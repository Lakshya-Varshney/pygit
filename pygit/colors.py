"""ANSI color helpers for pygit terminal output.

Pure stdlib, zero dependencies. Respects non-terminal output by default.
"""

import sys

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
CYAN = "\033[36m"


def should_color(args_color=None, stream=None):
    """Determine whether to emit ANSI color codes.

    Args:
        args_color: Value from --color flag ("always", "never", "auto", or None)
        stream: Output stream to check isatty() on (defaults to sys.stdout)

    Returns:
        True if colors should be emitted
    """
    if stream is None:
        stream = sys.stdout
    if args_color == "always":
        return True
    if args_color == "never":
        return False
    # Default: auto — respect isatty()
    return stream.isatty()


def colorize(text, color):
    """Wrap text in ANSI color codes.

    Args:
        text: String to colorize
        color: Color constant (e.g. RED, GREEN) or empty string for no color

    Returns:
        Colorized string, or plain string if color is empty
    """
    if not color:
        return text
    return f"{color}{text}{RESET}"


def colorize_diff_line(line, use_color):
    """Colorize a single diff output line.

    Args:
        line: A line from unified_diff output
        use_color: True to emit colors, False for plain text

    Returns:
        The line, optionally wrapped in ANSI codes
    """
    if not use_color:
        return line
    if line.startswith("+") and not line.startswith("+++"):
        return colorize(line, GREEN)
    if line.startswith("-") and not line.startswith("---"):
        return colorize(line, RED)
    if line.startswith("@@"):
        return colorize(line, CYAN)
    return line


def colorize_status_item(text, color_type, use_color):
    """Colorize a status output item.

    Args:
        text: The status line text (e.g. "\tmodified:   foo.py")
        color_type: "staged" for green, "modified" or "untracked" for red
        use_color: True to emit colors, False for plain text

    Returns:
        The text, optionally wrapped in ANSI codes
    """
    if not use_color:
        return text
    if color_type == "staged":
        return colorize(text, GREEN)
    # modified and untracked are both red (matching real git)
    return colorize(text, RED)
