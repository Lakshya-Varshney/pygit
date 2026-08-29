"""Stash functionality for pygit.

Save and restore working tree state without creating commits.
"""

import json
import os
import time
from pathlib import Path

from .objects import hash_object, read_object, serialize_commit


class StashEntry:
    """Represents a stashed state."""

    def __init__(self, index_entries, working_files, ref=None):
        self.index_entries = index_entries
        self.working_files = working_files  # {path: content_bytes}
        self.ref = ref
        self.timestamp = int(time.time())


def stash_push(repo):
    """Save current index and working-tree diff as a stash entry.

    Args:
        repo: Repository instance
    """
    from .index import Index
    from .objects import serialize_tree

    index = Index(repo)
    index.load()

    # Capture working tree state
    working_files = {}
    index_entries = index.get_entries()

    for entry in index_entries:
        path = entry["path"]
        full = repo.root / path
        if full.exists():
            working_files[path] = full.read_bytes()

    # Create stash entry
    stash_data = {
        "index": index_entries,
        "working_files": {k: v.decode("latin-1") for k, v in working_files.items()},
        "timestamp": int(time.time()),
        "ref": repo.get_head(),
    }

    # Load existing stash
    stash_file = repo.git_dir / "stash"
    try:
        stash_list = json.loads(stash_file.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        stash_list = []

    stash_list.append(stash_data)
    stash_file.write_text(json.dumps(stash_list, indent=2) + "\n")

    # Reset working tree to HEAD (simple approach: remove all tracked files and re-checkout)
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()

        # Get tree from commit
        from .objects import read_object, deserialize_commit
        commit = deserialize_commit(read_object(head_sha, repo.root)[1])
        repo.checkout_tree(commit["tree"])
    except Exception:
        pass

    # Clear index
    index.clear()
    index.save()


def stash_pop(repo):
    """Restore the most recent stash entry.

    Args:
        repo: Repository instance
    """
    stash_file = repo.git_dir / "stash"
    if not stash_file.exists():
        print("No stash entries found.", file=__import__("sys").stderr)
        return

    try:
        stash_list = json.loads(stash_file.read_text())
    except json.JSONDecodeError:
        print("No stash entries found.", file=__import__("sys").stderr)
        return

    if not stash_list:
        print("No stash entries found.", file=__import__("sys").stderr)
        return

    entry = stash_list.pop(0)

    # Restore working files
    for path, content_str in entry.get("working_files", {}).items():
        full = repo.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content_str.encode("latin-1"))

    # Restore index
    from .index import Index
    index = Index(repo)
    index.clear()
    for ie in entry.get("index", []):
        index.add(ie["path"], ie["sha"], ie.get("mode", "100644"), ie.get("mtime", 0))
    index.save()

    # Save updated stash
    stash_file.write_text(json.dumps(stash_list, indent=2) + "\n")


def stash_list(repo):
    """List all stash entries.

    Args:
        repo: Repository instance
    """
    stash_file = repo.git_dir / "stash"
    if not stash_file.exists():
        return

    try:
        stash_list = json.loads(stash_file.read_text())
    except json.JSONDecodeError:
        return

    for i, entry in enumerate(stash_list):
        timestamp = entry.get("timestamp", 0)
        dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        print(f"stash@{{{i}}}: WIP on {entry.get('ref', 'HEAD')}:{dt}")
