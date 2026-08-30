"""pygit diff — commit-to-commit diff between arbitrary refs."""

import difflib
from .objects import read_object, deserialize_commit


def resolve_commit_ref(repo, name):
    """Resolve a name to a full sha.

    Tries: sha prefix → branch → tag. Returns full sha string.
    Raises ValueError on failure.
    """
    # Try as sha prefix (all hex chars)
    if all(c in "0123456789abcdef" for c in name.lower()):
        try:
            return repo.resolve_sha_prefix(name)
        except ValueError:
            pass

    # Try as branch
    try:
        return repo.get_ref(f"refs/heads/{name}")
    except FileNotFoundError:
        pass

    # Try as tag
    try:
        return repo.get_ref(f"refs/tags/{name}")
    except FileNotFoundError:
        pass

    raise ValueError(f"unknown revision '{name}'")


def _get_tree_files(repo, tree_sha):
    """Get {path: entry_dict} for a tree sha."""
    if not tree_sha:
        return {}
    try:
        return {e["path"]: e for e in repo.get_tree_entries_from_tree(tree_sha)}
    except Exception:
        return {}


def diff_two_commits(repo, sha1, sha2):
    """Compute unified diff between two commits' trees.

    Args:
        repo: Repository instance
        sha1: Full sha of first commit (old)
        sha2: Full sha of second commit (new)

    Returns:
        List of diff lines (strings)
    """
    _, data1 = read_object(sha1, repo.root)
    commit1 = deserialize_commit(data1)
    _, data2 = read_object(sha2, repo.root)
    commit2 = deserialize_commit(data2)

    files1 = _get_tree_files(repo, commit1["tree"])
    files2 = _get_tree_files(repo, commit2["tree"])

    all_paths = sorted(set(files1.keys()) | set(files2.keys()))
    diff_lines = []

    for path in all_paths:
        old_entry = files1.get(path)
        new_entry = files2.get(path)

        old_content = b""
        new_content = b""

        if old_entry:
            _, old_content = read_object(old_entry["sha"], repo.root)
        if new_entry:
            _, new_content = read_object(new_entry["sha"], repo.root)

        old_text = old_content.decode("utf-8", errors="replace").splitlines(keepends=True)
        new_text = new_content.decode("utf-8", errors="replace").splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_text, new_text,
            fromfile=f"a/{path}", tofile=f"b/{path}"
        ))
        diff_lines.extend(diff)

    return diff_lines
