"""Merge engine for pygit.

Implements three-way merge, cherry-pick, rebase, and revert.
"""

import difflib
import sys
from pathlib import Path

from .objects import (
    read_object, deserialize_commit, deserialize_tree,
    hash_object, serialize_commit, serialize_tree
)
from .repository import Repository


def find_merge_base(repo, commit_a, commit_b):
    """Find the common ancestor of two commits.

    Uses a simple BFS approach: collect all ancestors of A,
    then walk B's ancestors until hitting one in A's set.

    Args:
        repo: Repository instance
        commit_a: SHA of first commit
        commit_b: SHA of second commit

    Returns:
        SHA of the merge base

    Raises:
        ValueError: If no common ancestor found
    """
    # Collect all ancestors of A
    ancestors_a = set()
    stack = [commit_a]
    while stack:
        sha = stack.pop()
        if sha in ancestors_a:
            continue
        ancestors_a.add(sha)
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                continue
            commit = deserialize_commit(data)
            for parent in commit["parents"]:
                stack.append(parent)
        except Exception:
            continue

    # Walk B's ancestors
    stack = [commit_b]
    visited = set()
    while stack:
        sha = stack.pop()
        if sha in visited:
            continue
        visited.add(sha)
        if sha in ancestors_a:
            return sha
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                continue
            commit = deserialize_commit(data)
            for parent in commit["parents"]:
                stack.append(parent)
        except Exception:
            continue

    raise ValueError("No common ancestor found (unrelated histories)")


def three_way_merge(base_tree_sha, ours_tree_sha, theirs_tree_sha, repo):
    """Perform a three-way merge of two trees against a common base.

    Args:
        base_tree_sha: SHA of the common ancestor tree
        ours_tree_sha: SHA of our tree
        theirs_tree_sha: SHA of their tree
        repo: Repository instance

    Returns:
        Tuple of (merged_tree_sha, conflicts_list)
    """
    # Get file entries from each tree
    def get_tree_files(tree_sha):
        if not tree_sha:
            return {}
        try:
            entries = repo.get_tree_entries_from_tree(tree_sha)
            return {e["path"]: e for e in entries}
        except Exception:
            return {}

    base_files = get_tree_files(base_tree_sha)
    ours_files = get_tree_files(ours_tree_sha)
    theirs_files = get_tree_files(theirs_tree_sha)

    all_paths = set(base_files.keys()) | set(ours_files.keys()) | set(theirs_files.keys())

    merged_entries = []
    conflicts = []

    for path in sorted(all_paths):
        base_entry = base_files.get(path)
        ours_entry = ours_files.get(path)
        theirs_entry = theirs_files.get(path)

        base_sha = base_entry["sha"] if base_entry else None
        ours_sha = ours_entry["sha"] if ours_entry else None
        theirs_sha = theirs_entry["sha"] if theirs_entry else None

        if ours_sha == theirs_sha:
            # Same on both sides - use it
            if ours_sha:
                merged_entries.append({
                    "path": path,
                    "sha": ours_sha,
                    "mode": ours_entry["mode"] if ours_entry else "100644",
                })
            # If both deleted, skip
            continue

        if ours_sha == base_sha:
            # Only theirs changed
            if theirs_sha:
                merged_entries.append({
                    "path": path,
                    "sha": theirs_sha,
                    "mode": theirs_entry["mode"] if theirs_entry else "100644",
                })
            continue

        if theirs_sha == base_sha:
            # Only ours changed
            if ours_sha:
                merged_entries.append({
                    "path": path,
                    "sha": ours_sha,
                    "mode": ours_entry["mode"] if ours_entry else "100644",
                })
            continue

        # Both changed - try line-level merge
        try:
            base_content = b""
            ours_content = b""
            theirs_content = b""

            if base_sha:
                _, base_content = read_object(base_sha, repo.root)
            if ours_sha:
                _, ours_content = read_object(ours_sha, repo.root)
            if theirs_sha:
                _, theirs_content = read_object(theirs_sha, repo.root)

            base_lines = base_content.decode("utf-8", errors="replace").splitlines(keepends=True)
            ours_lines = ours_content.decode("utf-8", errors="replace").splitlines(keepends=True)
            theirs_lines = theirs_content.decode("utf-8", errors="replace").splitlines(keepends=True)

            # Use SequenceMatcher to merge
            sm_ours = difflib.SequenceMatcher(None, base_lines, ours_lines)
            sm_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines)

            # Simple merge: if both changed different parts, combine
            # For conflicts, write conflict markers
            merged_lines = []
            has_conflict = False

            # Use a simpler approach: check if changes overlap
            ours_ops = [(op, i1, i2, j1, j2) for op, i1, i2, j1, j2 in sm_ours.get_opcodes() if op != 'equal']
            theirs_ops = [(op, i1, i2, j1, j2) for op, i1, i2, j1, j2 in sm_theirs.get_opcodes() if op != 'equal']

            # Check for overlapping changes
            conflict = False
            for o_op in ours_ops:
                for t_op in theirs_ops:
                    o_start, o_end = o_op[1], o_op[2]
                    t_start, t_end = t_op[1], t_op[2]
                    if o_start < t_end and t_start < o_end:
                        conflict = True
                        break
                if conflict:
                    break

            if conflict:
                # Write conflict markers
                merged_lines = []
                merged_lines.append(f"<<<<<<< HEAD\n")
                merged_lines.extend(ours_lines)
                merged_lines.append(f"=======\n")
                merged_lines.extend(theirs_lines)
                merged_lines.append(f">>>>>>> {theirs_sha[:7] if theirs_sha else 'theirs'}\n")
                has_conflict = True
            else:
                # Non-overlapping changes - apply both
                # Start with base, apply ours changes, then theirs
                result = list(base_lines)
                # Apply ours changes in reverse order
                for op, i1, i2, j1, j2 in reversed(sm_ours.get_opcodes()):
                    if op == 'replace':
                        result[i1:i2] = ours_lines[j1:j2]
                    elif op == 'delete':
                        result[i1:i2] = []
                    elif op == 'insert':
                        result[i1:i1] = ours_lines[j1:j2]

                # Apply theirs changes
                sm_result = difflib.SequenceMatcher(None, base_lines, result)
                for op, i1, i2, j1, j2 in sm_result.get_opcodes():
                    if op == 'replace':
                        result[i1:i2] = theirs_lines[j1:j2]
                    elif op == 'delete':
                        result[i1:i2] = []
                    elif op == 'insert':
                        result[i1:i1] = theirs_lines[j1:j2]

                merged_lines = result

            merged_content = "".join(merged_lines).encode("utf-8")
            merged_sha = hash_object(merged_content, "blob", repo.root)
            mode = ours_entry["mode"] if ours_entry else (theirs_entry["mode"] if theirs_entry else "100644")
            merged_entries.append({"path": path, "sha": merged_sha, "mode": mode})

            if has_conflict:
                conflicts.append(path)

        except Exception as e:
            # If we can't merge, mark as conflict
            conflicts.append(path)
            if ours_sha:
                merged_entries.append({"path": path, "sha": ours_sha, "mode": ours_entry["mode"] if ours_entry else "100644"})

    # Build merged tree
    tree_entries = [(e["mode"], e["path"], e["sha"]) for e in merged_entries]
    tree_data = serialize_tree(tree_entries)
    merged_tree_sha = hash_object(tree_data, "tree", repo.root)

    return merged_tree_sha, conflicts


def merge_branch(repo, branch_name):
    """Merge a branch into the current branch.

    Args:
        repo: Repository instance
        branch_name: Name of branch to merge

    Raises:
        ValueError: On merge conflicts or other errors
    """
    # Get current branch and its tip
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot merge")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    # Get target branch tip
    try:
        target_sha = repo.get_ref(f"refs/heads/{branch_name}")
    except FileNotFoundError:
        raise ValueError(f"branch '{branch_name}' not found")

    if current_sha == target_sha:
        print("Already up to date.")
        return

    # Find merge base
    try:
        base_sha = find_merge_base(repo, current_sha, target_sha)
    except ValueError as e:
        raise ValueError(str(e))

    if base_sha == current_sha:
        # Fast-forward merge
        repo.set_ref(current_ref, target_sha)
        repo.append_reflog(current_sha, target_sha, "merge")
        print(f"Fast-forward to {target_sha[:7]}")
        return

    if base_sha == target_sha:
        print("Already up to date.")
        return

    # Three-way merge
    base_commit = deserialize_commit(read_object(base_sha, repo.root)[1])
    ours_commit = deserialize_commit(read_object(current_sha, repo.root)[1])
    theirs_commit = deserialize_commit(read_object(target_sha, repo.root)[1])

    merged_tree_sha, conflicts = three_way_merge(
        base_commit["tree"], ours_commit["tree"], theirs_commit["tree"], repo
    )

    if conflicts:
        # Write conflict markers to working tree
        for path in conflicts:
            try:
                entries = repo.get_tree_entries_from_tree(merged_tree_sha)
                for entry in entries:
                    if entry["path"] == path:
                        full = repo.root / path
                        full.parent.mkdir(parents=True, exist_ok=True)
                        _, content = read_object(entry["sha"], repo.root)
                        full.write_bytes(content)
            except Exception:
                pass
        print(f"CONFLICT: Merge conflict in {', '.join(conflicts)}")
        print("Automatic merge failed; fix conflicts and then commit the result.")
        sys.exit(1)

    # Create merge commit
    author = repo.get_author_string()

    import time
    epoch = int(time.time())

    commit_data = serialize_commit(
        merged_tree_sha, [current_sha, target_sha],
        author, author, epoch,
        f"Merge branch '{branch_name}'"
    )
    merge_sha = hash_object(commit_data, "commit", repo.root)

    repo.set_ref(current_ref, merge_sha)
    repo.append_reflog(current_sha, merge_sha, "merge")
    print(f"Merge made by the 'ort' strategy.")


def cherry_pick(repo, commit_sha):
    """Apply a commit's changes to the current branch.

    Args:
        repo: Repository instance
        commit_sha: SHA of commit to cherry-pick
    """
    # Get current state
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot cherry-pick")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    # Get the commit to cherry-pick
    obj_type, data = read_object(commit_sha, repo.root)
    if obj_type != "commit":
        raise ValueError(f"Object {commit_sha} is not a commit")
    target_commit = deserialize_commit(data)

    # Get parent commit (for diff)
    if target_commit["parents"]:
        parent_sha = target_commit["parents"][0]
        parent_commit = deserialize_commit(read_object(parent_sha, repo.root)[1])
        base_tree = parent_commit["tree"]
    else:
        # Root commit - base is empty tree
        base_tree = hash_object(serialize_tree([]), "tree", repo.root)

    # Get current tree
    current_commit = deserialize_commit(read_object(current_sha, repo.root)[1])
    current_tree = current_commit["tree"]

    # Apply changes: current tree + target changes
    merged_sha, conflicts = three_way_merge(
        base_tree, current_tree, target_commit["tree"], repo
    )

    if conflicts:
        raise ValueError(f"Conflicts in: {', '.join(conflicts)}")

    # Create new commit
    author = repo.get_author_string()

    import time
    epoch = int(time.time())

    commit_data = serialize_commit(
        merged_sha, [current_sha],
        author, author, epoch,
        f"cherry-pick: {target_commit['message']}"
    )
    new_sha = hash_object(commit_data, "commit", repo.root)

    repo.set_ref(current_ref, new_sha)
    repo.append_reflog(current_sha, new_sha, "cherry-pick")
    repo.checkout_tree(merged_sha)
    print(f"[main {new_sha[:7]}] {target_commit['message']}")


def rebase(repo, target_branch):
    """Replay current branch commits on top of another branch.

    Args:
        repo: Repository instance
        target_branch: Branch to rebase onto
    """
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot rebase")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    try:
        target_sha = repo.get_ref(f"refs/heads/{target_branch}")
    except FileNotFoundError:
        raise ValueError(f"branch '{target_branch}' not found")

    # Find merge base
    try:
        base_sha = find_merge_base(repo, current_sha, target_sha)
    except ValueError:
        raise ValueError("No common ancestor found")

    if base_sha == current_sha:
        print("Already on top of the target branch.")
        return

    # Collect commits to replay (from current back to base)
    commits_to_replay = []
    stack = [current_sha]
    visited = set()
    while stack:
        sha = stack.pop()
        if sha in visited or sha == base_sha:
            continue
        visited.add(sha)
        commits_to_replay.append(sha)
        try:
            commit = deserialize_commit(read_object(sha, repo.root)[1])
            for parent in commit["parents"]:
                stack.append(parent)
        except Exception:
            continue

    # Replay in chronological order (oldest first)
    commits_to_replay.reverse()

    new_base = target_sha
    for old_sha in commits_to_replay:
        old_commit = deserialize_commit(read_object(old_sha, repo.root)[1])

        # Get base tree (parent of this commit)
        if old_commit["parents"]:
            parent_commit = deserialize_commit(read_object(old_commit["parents"][0], repo.root)[1])
            base_tree = parent_commit["tree"]
        else:
            base_tree = hash_object(serialize_tree([]), "tree", repo.root)

        # Get new base tree
        new_base_commit = deserialize_commit(read_object(new_base, repo.root)[1])

        # Apply changes
        merged_sha, conflicts = three_way_merge(
            base_tree, new_base_commit["tree"], old_commit["tree"], repo
        )

        if conflicts:
            raise ValueError(f"Conflict replaying {old_sha[:7]}: {', '.join(conflicts)}")

        # Create new commit
        author = repo.get_author_string()

        import time
        epoch = int(time.time())

        commit_data = serialize_commit(
            merged_sha, [new_base],
            author, author, epoch,
            old_commit["message"]
        )
        new_sha = hash_object(commit_data, "commit", repo.root)
        new_base = new_sha

    # Update branch ref
    repo.set_ref(current_ref, new_base)
    repo.append_reflog(current_sha, new_base, "rebase")
    new_base_commit = deserialize_commit(read_object(new_base, repo.root)[1])
    repo.checkout_tree(new_base_commit["tree"])
    print(f"Successfully rebased and updated refs/heads/{current_ref.split('/')[-1]}.")


def revert(repo, commit_sha):
    """Create a commit that undoes a previous commit.

    Args:
        repo: Repository instance
        commit_sha: SHA of commit to revert
    """
    head = repo.get_head()
    if not head.startswith("ref: "):
        raise ValueError("HEAD is detached, cannot revert")
    current_ref = head.split("ref: ")[1].strip()
    current_sha = repo.get_ref(current_ref)

    # Get the commit to revert
    obj_type, data = read_object(commit_sha, repo.root)
    if obj_type != "commit":
        raise ValueError(f"Object {commit_sha} is not a commit")
    target_commit = deserialize_commit(data)

    # Get parent tree (what the file looked like before)
    if target_commit["parents"]:
        parent_commit = deserialize_commit(read_object(target_commit["parents"][0], repo.root)[1])
        revert_tree = parent_commit["tree"]
    else:
        # Reverting root commit = empty tree
        revert_tree = hash_object(serialize_tree([]), "tree", repo.root)

    # Create revert commit
    author = repo.get_author_string()

    import time
    epoch = int(time.time())

    commit_data = serialize_commit(
        revert_tree, [current_sha],
        author, author, epoch,
        f"Revert \"{target_commit['message']}\""
    )
    new_sha = hash_object(commit_data, "commit", repo.root)

    repo.set_ref(current_ref, new_sha)
    repo.append_reflog(current_sha, new_sha, "revert")
    repo.checkout_tree(revert_tree)
    print(f"[main {new_sha[:7]}] Revert \"{target_commit['message']}\"")
