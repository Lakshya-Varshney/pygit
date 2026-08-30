"""pygit log — commit history walking with filtering."""

from .objects import read_object, deserialize_commit


def walk_commits(repo, sha, count=None):
    """Walk parent chain from sha, yielding (sha, commit_dict) tuples.

    Args:
        repo: Repository instance
        sha: Starting commit sha
        count: Maximum number of commits to yield (None for all)

    Yields:
        (sha_string, commit_dict) tuples, newest first
    """
    yielded = 0
    while sha:
        if count is not None and yielded >= count:
            return
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                break
            commit = deserialize_commit(data)
            yield (sha, commit)
            yielded += 1
            sha = commit["parents"][0] if commit["parents"] else None
        except Exception:
            break


def _get_blob_sha_for_path(repo, commit, path):
    """Get the blob sha for a given path in a commit's tree, or None."""
    try:
        entries = repo.get_tree_entries_from_tree(commit["tree"])
        for e in entries:
            if e["path"] == path:
                return e["sha"]
    except Exception:
        pass
    return None


def commits_that_touched_path(repo, sha, path):
    """Filter walk to only commits where the given path changed.

    A commit is included if:
    - Path exists in this commit but not in its first parent (added)
    - Path exists in parent but not in this commit (deleted)
    - Path exists in both but blob SHA differs (modified)
    - It's a root commit and path exists in it

    Args:
        repo: Repository instance
        sha: Starting commit sha
        path: File path to check

    Yields:
        (sha_string, commit_dict) tuples
    """
    for commit_sha, commit in walk_commits(repo, sha):
        # Get blob sha in this commit
        this_blob = _get_blob_sha_for_path(repo, commit, path)

        # Get blob sha in first parent
        parent_blob = None
        if commit["parents"]:
            try:
                _, parent_data = read_object(commit["parents"][0], repo.root)
                parent_commit = deserialize_commit(parent_data)
                parent_blob = _get_blob_sha_for_path(repo, parent_commit, path)
            except Exception:
                pass

        # Include if path changed between this commit and parent
        if this_blob != parent_blob:
            yield (commit_sha, commit)
