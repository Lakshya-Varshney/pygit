"""Diff engine for pygit.

Uses difflib (stdlib) for unified diff output.
"""

import difflib
import sys
from pathlib import Path

from .objects import read_object, deserialize_commit


def diff_files(file_a, file_b, from_label="a", to_label="b"):
    """Compute unified diff between two files.

    Args:
        file_a: Path to first file (or content string)
        file_b: Path to second file (or content string)
        from_label: Label for file_a in diff output
        to_label: Label for file_b in diff output

    Returns:
        Unified diff string
    """
    if isinstance(file_a, (str, Path)):
        if Path(file_a).exists():
            content_a = Path(file_a).read_text(errors="replace").splitlines(keepends=True)
        else:
            content_a = []
    else:
        content_a = file_a.splitlines(keepends=True) if isinstance(file_a, str) else file_a

    if isinstance(file_b, (str, Path)):
        if Path(file_b).exists():
            content_b = Path(file_b).read_text(errors="replace").splitlines(keepends=True)
        else:
            content_b = []
    else:
        content_b = file_b.splitlines(keepends=True) if isinstance(file_b, str) else file_b

    diff = difflib.unified_diff(
        content_a, content_b,
        fromfile=from_label, tofile=to_label,
        lineterm=""
    )
    return "\n".join(diff)


def diff_index_vs_working(repo, path):
    """Diff between index and working tree for a file."""
    from .index import Index

    index = Index(repo)
    index.load()
    entry = index.get_entry(path)
    if not entry:
        return ""

    full_path = repo.root / path
    if not full_path.exists():
        return f"deleted file\n--- a/{path}\n+++ /dev/null\n"

    working = full_path.read_text(errors="replace").splitlines(keepends=True)

    try:
        _, idx_data = read_object(entry["sha"], repo.root)
        idx_lines = idx_data.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        idx_lines = []

    return "\n".join(difflib.unified_diff(
        idx_lines, working,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm=""
    ))


def diff_head_vs_index(repo, path):
    """Diff between HEAD and index for a file."""
    from .index import Index

    index = Index(repo)
    index.load()
    entry = index.get_entry(path)
    if not entry:
        return ""

    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
        head_content = repo.get_file_from_commit(head_sha, path)
        head_lines = head_content.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        head_lines = []

    try:
        _, idx_data = read_object(entry["sha"], repo.root)
        idx_lines = idx_data.decode("utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        idx_lines = []

    return "\n".join(difflib.unified_diff(
        head_lines, idx_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm=""
    ))


def blame(repo, file_path):
    """Show per-line commit attribution for a file.

    For each line, walks commit history to find the most recent commit
    that introduced or last changed that line.
    """
    # Get current file content
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
    except (FileNotFoundError, ValueError):
        print("No commits yet", file=sys.stderr)
        return

    try:
        current_content = repo.get_file_from_commit(head_sha, file_path)
        current_lines = current_content.decode("utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        print(f"fatal: path '{file_path}' does not exist in the working tree", file=sys.stderr)
        return

    # Walk commits and track line changes
    # For simplicity, blame each line to the most recent commit that touched it
    commit_history = []
    visited = set()
    stack = [head_sha]

    while stack:
        sha = stack.pop()
        if sha in visited:
            continue
        visited.add(sha)

        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                continue
            commit = deserialize_commit(data)
            commit_history.append((sha, commit))
            for parent_sha in commit["parents"]:
                stack.append(parent_sha)
        except Exception:
            continue

    # For each line, find the most recent commit that has this line
    line_authors = []
    for line in current_lines:
        found = False
        for sha, commit in commit_history:
            try:
                file_content = repo.get_file_from_commit(sha, file_path)
                file_lines = file_content.decode("utf-8", errors="replace").splitlines()
                if line in file_lines:
                    author = commit.get("author", "Unknown")
                    # Extract just name before <
                    author_name = author.split("<")[0].strip() if "<" in author else author
                    line_authors.append((sha[:7], author_name, line))
                    found = True
                    break
            except Exception:
                continue
        if not found:
            line_authors.append(("???????", "Unknown", line))

    # Print blame output
    for sha, author, line in line_authors:
        print(f"{sha} ({author:>20s}) {line}")
