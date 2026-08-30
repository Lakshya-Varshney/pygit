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


def get_untracked_files(repo, include_ignored=False):
    """Return list of untracked file paths (relative to repo root).

    A file is untracked if it's not in the index AND not in HEAD's tree.
    Ignored files are excluded unless include_ignored=True.
    .pygit/ is always excluded.
    """
    index_paths = _get_index_paths(repo)
    head_paths = _get_head_tree_paths(repo)
    tracked = index_paths | head_paths

    patterns = load_ignore(repo.root) if not include_ignored else []
    untracked = []

    for root, dirs, filenames in os.walk(repo.root):
        # Skip .pygit directory entirely
        dirs[:] = [d for d in dirs if d != ".pygit"]

        root_path = Path(root)
        for fname in filenames:
            if fname.startswith(".pygit"):
                continue
            full = root_path / fname
            rel = str(full.relative_to(repo.root)).replace("\\", "/")

            if rel in tracked:
                continue

            if not include_ignored and is_ignored(rel, patterns):
                continue

            untracked.append(rel)

    return sorted(untracked)


def _get_untracked_dirs(repo, include_ignored=False):
    """Return list of untracked directory paths (relative to repo root).

    A directory is untracked if none of its files are in the index or HEAD tree.
    .pygit/ is always excluded.
    """
    index_paths = _get_index_paths(repo)
    head_paths = _get_head_tree_paths(repo)
    tracked = index_paths | head_paths

    patterns = load_ignore(repo.root) if not include_ignored else []
    untracked_dirs = set()

    for root, dirs, filenames in os.walk(repo.root):
        dirs[:] = [d for d in dirs if d != ".pygit"]

        root_path = Path(root)
        rel_dir = str(root_path.relative_to(repo.root)).replace("\\", "/")
        if rel_dir == ".":
            continue

        # Check if any file in this directory is tracked
        has_tracked = False
        for fname in filenames:
            if fname.startswith(".pygit"):
                continue
            full = root_path / fname
            rel = str(full.relative_to(repo.root)).replace("\\", "/")
            if rel in tracked:
                has_tracked = True
                break

        if not has_tracked:
            # Check if directory itself is ignored
            if not include_ignored and is_ignored(rel_dir + "/", patterns):
                continue
            untracked_dirs.add(rel_dir)

    return sorted(untracked_dirs)


def get_clean_targets(repo, include_ignored=False, include_dirs=False):
    """Return list of (path, is_dir) tuples for files that would be cleaned.

    Args:
        repo: Repository instance
        include_ignored: If True, include .pygitignore'd files
        include_dirs: If True, include untracked directories

    Returns:
        List of (relative_path, is_directory) tuples
    """
    targets = []
    for f in get_untracked_files(repo, include_ignored):
        targets.append((f, False))
    if include_dirs:
        for d in _get_untracked_dirs(repo, include_ignored):
            targets.append((d, True))
    return targets


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
