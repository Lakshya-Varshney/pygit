"""Staging area (index) for pygit.

JSON-based index mapping working-tree paths to object SHAs.
"""

import json
import os
from pathlib import Path


class Index:
    """Manages the staging area (index file)."""

    def __init__(self, repo):
        """Initialize with a Repository instance."""
        self.repo = repo
        self.index_path = repo.git_dir / "index"
        self._entries = []

    def load(self):
        """Load index from disk."""
        if self.index_path.exists():
            try:
                self._entries = json.loads(self.index_path.read_text())
            except json.JSONDecodeError:
                self._entries = []
        else:
            self._entries = []

    def save(self):
        """Save index to disk."""
        self.index_path.write_text(json.dumps(self._entries, indent=2) + "\n")

    def add(self, path, sha, mode="100644", mtime=0):
        """Add or update an entry in the index."""
        # Remove existing entry for this path
        self._entries = [e for e in self._entries if e["path"] != path]
        self._entries.append({
            "path": path,
            "sha": sha,
            "mode": mode,
            "mtime": mtime,
        })

    def remove(self, path):
        """Remove an entry from the index."""
        self._entries = [e for e in self._entries if e["path"] != path]

    def get_entries(self):
        """Get all index entries."""
        return list(self._entries)

    def get_entry(self, path):
        """Get a specific entry by path."""
        for entry in self._entries:
            if entry["path"] == path:
                return entry
        return None

    def clear(self):
        """Clear all entries."""
        self._entries = []
