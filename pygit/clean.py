"""pygit clean — list or delete untracked files.

Respects .pygitignore unless -x is passed. Never touches .pygit/ or tracked files.
"""

import os
import shutil
from pathlib import Path

from .ignore import load_ignore, is_ignored


def _get_index_paths(repo):
    """Get set of paths currently in the index."""
    from .index import Index
    index = Index(repo)
    index.load()
    return {e["path"] for e in index.get_entries()}


def _get_head_tree_paths(repo):
    """Get set of paths in the HEAD commit's tree."""
    head_paths = set()
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
        entries = repo.get_tree_entries(head_sha)
        head_paths = {e["path"] for e in entries}
    except Exception:
        pass
    return head_paths


def _dir_has_tracked_files(dir_path, tracked):
    """Check if any file at any depth inside dir_path is tracked."""
    for root, dirs, filenames in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d != ".pygit"]
        for fname in filenames:
            if fname.startswith(".pygit"):
                continue
            rel = str(Path(root).joinpath(fname).relative_to(dir_path.parent)).replace("\\", "/")
            if rel in tracked:
                return True
    return False


def get_untracked_files(repo, include_ignored=False, include_dirs=False):
    """Return list of untracked file paths (relative to repo root).

    When include_dirs=False (default): entirely-untracked directories are
    treated as atomic units — their contents are NOT listed individually.
    Only files in mixed directories (containing both tracked and untracked)
    are listed by path.

    When include_dirs=True: entirely-untracked directories appear as single
    directory entries; files inside mixed directories also appear individually.
    """
    index_paths = _get_index_paths(repo)
    head_paths = _get_head_tree_paths(repo)
    tracked = index_paths | head_paths

    patterns = load_ignore(repo.root) if not include_ignored else []
    result = []

    for root, dirs, filenames in os.walk(repo.root):
        dirs[:] = [d for d in dirs if d != ".pygit"]

        root_path = Path(root)
        rel_dir = str(root_path.relative_to(repo.root)).replace("\\", "/")

        # Check if this directory is entirely untracked (no tracked files at any depth)
        if rel_dir != ".":
            has_tracked = _dir_has_tracked_files(root_path, tracked)
            if not has_tracked:
                if not include_ignored and is_ignored(rel_dir + "/", patterns):
                    continue
                if include_dirs:
                    result.append((rel_dir, True))
                dirs.clear()
                continue

        for fname in filenames:
            if fname.startswith(".pygit"):
                continue
            full = root_path / fname
            rel = str(full.relative_to(repo.root)).replace("\\", "/")

            if rel in tracked:
                continue

            if not include_ignored and is_ignored(rel, patterns):
                continue

            result.append((rel, False))

    return sorted(result)



def get_clean_targets(repo, include_ignored=False, include_dirs=False):
    """Return list of (path, is_dir) tuples for files that would be cleaned.

    Args:
        repo: Repository instance
        include_ignored: If True, include .pygitignore'd files
        include_dirs: If True, include untracked directories

    Returns:
        List of (relative_path, is_directory) tuples
    """
    return get_untracked_files(repo, include_ignored, include_dirs)


def clean_repo(repo, dry_run=False, include_ignored=False, include_dirs=False):
    """Clean untracked files from the working tree.

    Args:
        repo: Repository instance
        dry_run: If True, only print what would be removed
        include_ignored: If True, also remove .pygitignore'd files
        include_dirs: If True, also remove untracked directories

    Returns:
        List of removed paths
    """
    targets = get_clean_targets(repo, include_ignored, include_dirs)
    removed = []

    for path, is_dir in targets:
        if dry_run:
            print(f"Would remove {path}")
            removed.append(path)
        else:
            full = repo.root / path
            if is_dir:
                if full.exists():
                    shutil.rmtree(full)
                    removed.append(path)
            else:
                if full.exists():
                    os.unlink(full)
                    removed.append(path)

    return removed
