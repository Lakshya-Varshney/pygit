"""Gitignore-style pattern matching for pygit.

Uses fnmatch (stdlib) to match patterns from .pygitignore files.
"""

import fnmatch
from pathlib import Path


def load_ignore(repo_root):
    """Load patterns from .pygitignore files.

    Args:
        repo_root: Repository root path

    Returns:
        List of pattern strings
    """
    repo_root = Path(repo_root)
    patterns = []

    # Root .pygitignore
    ignore_file = repo_root / ".pygitignore"
    if ignore_file.exists():
        for line in ignore_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)

    return patterns


def is_ignored(path, patterns):
    """Check if a path matches any ignore pattern.

    Args:
        path: File path relative to repo root
        patterns: List of glob patterns from .pygitignore

    Returns:
        True if the path should be ignored
    """
    for pattern in patterns:
        # Normalize path separators
        normalized_path = path.replace("\\", "/")
        normalized_pattern = pattern.replace("\\", "/")

        # Directory patterns (ending with /)
        if normalized_pattern.endswith("/"):
            dir_pattern = normalized_pattern.rstrip("/")
            # Check if any path component matches
            parts = normalized_path.split("/")
            for i in range(len(parts)):
                partial = "/".join(parts[:i + 1]) + "/"
                if fnmatch.fnmatch(partial, normalized_pattern):
                    return True
                # Also check just the directory name
                if fnmatch.fnmatch(parts[i] + "/", normalized_pattern):
                    return True
        else:
            # File pattern - match against the full path or just the filename
            if fnmatch.fnmatch(normalized_path, normalized_pattern):
                return True
            # Also match against just the basename
            basename = normalized_path.split("/")[-1]
            if fnmatch.fnmatch(basename, normalized_pattern):
                return True

    return False
