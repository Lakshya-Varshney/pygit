"""pygit — a real, content-addressed version control system in pure Python."""

import argparse
import sys


def cmd_init(args):
    """Create .pygit/ directory structure."""
    from .repository import Repository
    repo = Repository(args.path or ".")
    repo.init()
    print(f"Initialized empty pygit repository in {repo.git_dir}")


def cmd_add(args):
    from .repository import Repository
    from .index import Index
    from .objects import hash_object
    from .ignore import load_ignore, is_ignored
    from pathlib import Path
    import os

    repo = Repository(".")
    index = Index(repo)
    index.load()
    patterns = load_ignore(repo.root)

    files_to_add = []

    for path in args.paths:
        if is_ignored(path, patterns):
            continue
        full_path = repo.root / path
        if not full_path.exists():
            print(f"fatal: pathspec '{path}' did not match any files", file=sys.stderr)
            sys.exit(1)
        if full_path.is_dir():
            for root, dirs, filenames in os.walk(full_path):
                dirs[:] = [d for d in dirs if d != ".pygit"]
                root_path = Path(root)
                for fname in filenames:
                    if fname.startswith(".pygit"):
                        continue
                    full = root_path / fname
                    rel = str(full.relative_to(repo.root))
                    if is_ignored(rel, patterns):
                        continue
                    files_to_add.append((rel, full))
        else:
            files_to_add.append((path, full_path))

    for rel, full in files_to_add:
        data = full.read_bytes()
        sha = hash_object(data, "blob", repo.root)
        mtime = os.path.getmtime(full)
        index.add(rel, sha, "100644", mtime)
    index.save()


def cmd_commit(args):
    from .repository import Repository
    from .index import Index
    from .objects import hash_object, serialize_commit, read_object, deserialize_commit

    repo = Repository(".")
    index = Index(repo)
    index.load()

    if not index.get_entries():
        print("nothing to commit (empty index)", file=sys.stderr)
        sys.exit(1)

    root_tree_sha = repo.build_tree_from_index(index)

    parent_sha = None
    try:
        head = repo.get_head()
        if not head.startswith("ref: "):
            parent_sha = head
        else:
            ref_path = head.split("ref: ")[1].strip()
            parent_sha = repo.get_ref(ref_path)
    except (FileNotFoundError, ValueError):
        pass

    if parent_sha:
        try:
            _, parent_data = read_object(parent_sha, repo.root)
            parent_commit = deserialize_commit(parent_data)
            if parent_commit["tree"] == root_tree_sha:
                print("nothing to commit, working tree clean", file=sys.stderr)
                sys.exit(1)
        except Exception:
            pass

    # Get author/committer info
    config = repo.get_config()
    try:
        name = config.get("user", "name")
        email = config.get("user", "email")
        author = f"{name} <{email}>"
    except Exception:
        author = "Unknown <unknown@example.com>"
    committer = author

    import time
    epoch = int(time.time())

    parents = [parent_sha] if parent_sha else []
    commit_data = serialize_commit(root_tree_sha, parents, author, committer, epoch, args.message)
    commit_sha = hash_object(commit_data, "commit", repo.root)

    # Update branch ref
    head = repo.get_head()
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        old_sha = repo.get_ref(ref_path) if (repo.root / ".pygit" / ref_path).exists() else "0" * 64
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "commit")
    else:
        # Detached HEAD
        repo.set_head_detached(commit_sha)
        repo.append_reflog(head, commit_sha, "commit")

    head_for_output = repo.get_head()
    if head_for_output.startswith("ref: "):
        ref_path_out = head_for_output.split("ref: ")[1].strip()
        branch_name = ref_path_out.split("/")[-1]
    else:
        branch_name = commit_sha[:7]

    if parents:
        print(f"[{branch_name} {commit_sha[:7]}] {args.message}")
    else:
        print(f"[{branch_name} (root-commit) {commit_sha[:7]}] {args.message}")


def cmd_log(args):
    """Walk parent chain from HEAD, print commit info."""
    from .repository import Repository
    from .objects import read_object, deserialize_commit

    repo = Repository(".")
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            sha = repo.get_ref(ref_path)
        else:
            sha = head.strip()
    except (FileNotFoundError, ValueError):
        print("No commits yet", file=sys.stderr)
        return

    while sha:
        try:
            obj_type, data = read_object(sha, repo.root)
            if obj_type != "commit":
                break
            commit = deserialize_commit(data)
            print(f"commit {sha}")
            if len(commit["parents"]) > 1:
                print(f"Merge: {' '.join(p[:7] for p in commit['parents'])}")
            print(f"Author: {commit['author']}")
            import datetime
            dt = datetime.datetime.fromtimestamp(commit["committer_epoch"])
            print(f"Date:   {dt.strftime('%a %b %d %H:%M:%S %Y %z')}")
            print(f"\n    {commit['message']}\n")
            sha = commit["parents"][0] if commit["parents"] else None
        except Exception:
            break


def cmd_status(args):
    """Diff working tree vs index vs HEAD tree."""
    from .repository import Repository
    from .index import Index

    repo = Repository(".")
    index = Index(repo)
    index.load()

    # Get HEAD tree entries
    head_entries = {}
    try:
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            head_sha = repo.get_ref(ref_path)
        else:
            head_sha = head.strip()
        head_tree = repo.get_tree_entries(head_sha)
        head_entries = {e["path"]: e for e in head_tree}
    except Exception:
        pass

    index_entries = {e["path"]: e for e in index.get_entries()}
    working_files = repo.get_working_tree_files()

    staged = []
    modified = []
    untracked = []

    for path in sorted(index_entries):
        ie = index_entries[path]
        full = repo.root / path
        if path not in working_files:
            modified.append(f"\tdeleted:   {path}")
        elif ie["sha"] != head_entries.get(path, {}).get("sha"):
            staged.append(f"\tnew file:   {path}")
        else:
            current_sha = None
            try:
                from .objects import hash_object
                current_sha = hash_object(full.read_bytes(), "blob", repo.root)
            except Exception:
                pass
            if current_sha and current_sha != ie["sha"]:
                modified.append(f"\tmodified:   {path}")

    for path in sorted(head_entries):
        if path not in index_entries and path in working_files:
            modified.append(f"\tmodified:   {path}")

    for path in sorted(working_files):
        if path not in index_entries and path not in head_entries:
            untracked.append(f"\t{path}")

    if staged:
        print("Changes to be committed:")
        print("  (use \"git rm --cached <file>...\" to unstage)")
        for s in staged:
            print(s)
        print()

    if modified:
        print("Changes not staged for commit:")
        print("  (use \"git add <file>...\" to update what will be committed)")
        for m in modified:
            print(m)
        print()

    if untracked:
        print("Untracked files:")
        print("  (use \"git add <file>...\" to include in what will be committed)")
        for u in untracked:
            print(u)
        print()

    if not staged and not modified and not untracked:
        print("nothing to commit, working tree clean")


def cmd_diff(args):
    """Show diff between working tree and index, or index and HEAD."""
    import difflib
    from .repository import Repository
    from .index import Index

    repo = Repository(".")
    index = Index(repo)
    index.load()

    paths = args.paths if args.paths else [e["path"] for e in index.get_entries()]

    for path in paths:
        ie = index.get_entry(path)
        if not ie:
            continue
        full = repo.root / path
        if not full.exists():
            continue
        working = full.read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)

        if args.staged:
            # Diff index vs HEAD
            try:
                head_sha = repo.get_head()
                if head_sha.startswith("ref: "):
                    ref_path = head_sha.split("ref: ")[1].strip()
                    head_sha = repo.get_ref(ref_path)
                head_content = repo.get_file_from_commit(head_sha, path)
                staged = head_content.decode("utf-8", errors="replace").splitlines(keepends=True)
            except Exception:
                staged = []
            diff = difflib.unified_diff(staged, working, fromfile=f"a/{path}", tofile=f"b/{path}")
        else:
            # Diff working tree vs index
            try:
                from .objects import read_object
                _, idx_data = read_object(ie["sha"], repo.root)
                idx_lines = idx_data.decode("utf-8", errors="replace").splitlines(keepends=True)
            except Exception:
                idx_lines = []
            diff = difflib.unified_diff(idx_lines, working, fromfile=f"a/{path}", tofile=f"b/{path}")

        sys.stdout.writelines(diff)


def cmd_branch(args):
    """Create or list branches."""
    from .repository import Repository

    repo = Repository(".")

    if args.name:
        # Create branch
        head = repo.get_head()
        if head.startswith("ref: "):
            ref_path = head.split("ref: ")[1].strip()
            sha = repo.get_ref(ref_path)
        else:
            sha = head.strip()
        repo.set_ref(f"refs/heads/{args.name}", sha)
        print(f"Branch '{args.name}' created")
    else:
        # List branches
        heads_dir = repo.root / ".pygit" / "refs" / "heads"
        if not heads_dir.exists():
            return
        current = None
        try:
            head = repo.get_head()
            if head.startswith("ref: "):
                current = head.split("ref: ")[1].strip().split("/")[-1]
        except Exception:
            pass
        for name in sorted(p.name for p in heads_dir.iterdir() if p.is_file()):
            prefix = "* " if name == current else "  "
            print(f"{prefix}{name}")


def cmd_checkout(args):
    """Move HEAD, rewrite working tree."""
    from .repository import Repository
    from .objects import read_object, deserialize_tree

    repo = Repository(".")
    target = args.target

    # Check for uncommitted changes
    index_entries = {}
    try:
        from .index import Index
        index = Index(repo)
        index.load()
        index_entries = {e["path"]: e for e in index.get_entries()}
    except Exception:
        pass

    working_files = repo.get_working_tree_files()
    for path in working_files:
        ie = index_entries.get(path)
        if ie:
            try:
                from .objects import hash_object
                full = repo.root / path
                current_sha = hash_object(full.read_bytes(), "blob", repo.root)
                if current_sha != ie["sha"]:
                    print(f"error: Your local changes to '{path}' would be overwritten", file=sys.stderr)
                    print("Commit your changes or stash them before you switch branches.", file=sys.stderr)
                    sys.exit(1)
            except Exception:
                pass

    # Resolve target to commit sha
    if len(target) == 64 and all(c in "0123456789abcdef" for c in target):
        commit_sha = target
    else:
        ref_path = f"refs/heads/{target}"
        try:
            commit_sha = repo.get_ref(ref_path)
        except FileNotFoundError:
            print(f"error: pathspec '{target}' did not match any branch", file=sys.stderr)
            sys.exit(1)

    # Get tree from commit
    obj_type, data = read_object(commit_sha, repo.root)
    if obj_type != "commit":
        print(f"error: {target} is not a commit", file=sys.stderr)
        sys.exit(1)

    from .objects import deserialize_commit
    commit = deserialize_commit(data)
    tree_sha = commit["tree"]

    target_entries = repo.get_tree_entries_from_tree(tree_sha)
    target_paths = {e["path"] for e in target_entries}
    index_paths = set(index_entries.keys())
    untracked_on_disk = working_files - index_paths
    collision = untracked_on_disk & target_paths
    if collision:
        for c in sorted(collision):
            print(f"error: untracked working tree file '{c}' would be overwritten by checkout", file=sys.stderr)
        sys.exit(1)

    # Checkout: update HEAD and working tree
    old_head_raw = repo.get_head()
    if old_head_raw.startswith("ref: "):
        old_ref = old_head_raw.split("ref: ")[1].strip()
        try:
            old_head = repo.get_ref(old_ref)
        except FileNotFoundError:
            old_head = "0" * 64
    else:
        old_head = old_head_raw

    old_tracked = set()
    try:
        old_entries = repo.get_tree_entries(old_head)
        old_tracked = {e["path"] for e in old_entries}
    except Exception:
        pass

    if len(target) == 64 and all(c in "0123456789abcdef" for c in target):
        repo.set_head_detached(commit_sha)
        repo.append_reflog(old_head, commit_sha, "checkout")
    else:
        repo.set_head(f"ref: refs/heads/{target}")
        repo.append_reflog(old_head, commit_sha, "checkout")

    repo.checkout_tree(tree_sha, old_tracked=old_tracked)
    print(f"Switched to branch '{target}'" if len(target) != 64 else f"HEAD is now at {commit_sha[:7]}")


def cmd_merge(args):
    """Three-way merge."""
    from .repository import Repository
    from .merge import merge_branch

    repo = Repository(".")
    try:
        merge_branch(repo, args.branch)
    except Exception as e:
        print(f"merge: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_tag(args):
    """Create lightweight or annotated tag."""
    from .repository import Repository
    from .objects import hash_object, serialize_tag

    repo = Repository(".")

    # Get current commit sha
    head = repo.get_head()
    if head.startswith("ref: "):
        ref_path = head.split("ref: ")[1].strip()
        commit_sha = repo.get_ref(ref_path)
    else:
        commit_sha = head.strip()

    if args.message:
        # Annotated tag
        config = repo.get_config()
        try:
            name = config.get("user", "name")
            email = config.get("user", "email")
            tagger = f"{name} <{email}>"
        except Exception:
            tagger = "Unknown <unknown@example.com>"

        import time
        epoch = int(time.time())
        tag_data = serialize_tag(commit_sha, "commit", tagger, args.name, epoch, args.message)
        tag_sha = hash_object(tag_data, "tag", repo.root)
        repo.set_ref(f"refs/tags/{args.name}", tag_sha)
    else:
        # Lightweight tag
        repo.set_ref(f"refs/tags/{args.name}", commit_sha)

    print(f"Tag '{args.name}' created")


def cmd_reset(args):
    """Move current branch ref to commit."""
    from .repository import Repository
    from .objects import read_object, deserialize_commit

    repo = Repository(".")

    # Resolve commit
    commit_sha = args.commit
    if not (len(commit_sha) == 64 and all(c in "0123456789abcdef" for c in commit_sha)):
        # Try as ref
        try:
            commit_sha = repo.get_ref(f"refs/heads/{args.commit}")
        except FileNotFoundError:
            print(f"error: pathspec '{args.commit}' did not match any commits", file=sys.stderr)
            sys.exit(1)

    head = repo.get_head()
    if not head.startswith("ref: "):
        print("error: HEAD is detached, cannot reset", file=sys.stderr)
        sys.exit(1)

    ref_path = head.split("ref: ")[1].strip()
    old_sha = repo.get_ref(ref_path)

    if args.mode == "soft":
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "reset")
    elif args.mode == "mixed" or args.mode is None:
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "reset")
        # Reset index to commit's tree
        from .index import Index
        index = Index(repo)
        commit_obj_type, data = read_object(commit_sha, repo.root)
        commit = deserialize_commit(data)
        tree_entries = repo.get_tree_entries_from_tree(commit["tree"])
        index.clear()
        for entry in tree_entries:
            index.add(entry["path"], entry["sha"], entry["mode"], 0)
        index.save()
    elif args.mode == "hard":
        repo.set_ref(ref_path, commit_sha)
        repo.append_reflog(old_sha, commit_sha, "reset")
        # Reset index and working tree
        from .index import Index
        index = Index(repo)
        commit_obj_type, data = read_object(commit_sha, repo.root)
        commit = deserialize_commit(data)
        repo.checkout_tree(commit["tree"])
        tree_entries = repo.get_tree_entries_from_tree(commit["tree"])
        index.clear()
        for entry in tree_entries:
            index.add(entry["path"], entry["sha"], entry["mode"], 0)
        index.save()

    print(f"HEAD is now at {commit_sha[:7]}")


def cmd_stash(args):
    """Save or restore working state."""
    from .repository import Repository

    repo = Repository(".")

    if args.stash_action == "push" or args.stash_action is None:
        from .stash import stash_push
        stash_push(repo)
        print("Saved working directory and index state")
    elif args.stash_action == "pop":
        from .stash import stash_pop
        stash_pop(repo)
        print("stash: On top of HEAD")
    elif args.stash_action == "list":
        from .stash import stash_list
        stash_list(repo)


def cmd_cherry_pick(args):
    """Apply a commit's changes to current branch."""
    from .repository import Repository
    from .merge import cherry_pick

    repo = Repository(".")
    try:
        cherry_pick(repo, args.sha)
    except Exception as e:
        print(f"cherry-pick: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_rebase(args):
    """Replay current branch commits on top of another branch."""
    from .repository import Repository
    from .merge import rebase

    repo = Repository(".")
    try:
        rebase(repo, args.branch)
    except Exception as e:
        print(f"rebase: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reflog(args):
    """Print HEAD movement history."""
    from .repository import Repository

    repo = Repository(".")
    reflog_path = repo.root / ".pygit" / "logs" / "HEAD"
    if not reflog_path.exists():
        return
    print(reflog_path.read_text())


def cmd_remote(args):
    """Manage remotes."""
    from .repository import Repository

    repo = Repository(".")
    if args.remote_action == "add":
        repo.add_remote(args.name, args.address)
        print(f"Remote '{args.name}' added")
    elif args.remote_action == "list":
        config = repo.get_config()
        for section in config.sections():
            if section.startswith("remote "):
                name = section.split('"')[1]
                addr = config.get(section, "address")
                print(f"{name}\t{addr}")


def cmd_fetch(args):
    """Fetch from remote."""
    from .repository import Repository
    from .network import Client

    repo = Repository(".")
    config = repo.get_config()
    address = repo.get_remote(args.remote)
    host, port = address.split(":")
    client = Client(repo)
    client.fetch(args.remote, host, int(port))
    print(f"Fetched from {args.remote}")


def cmd_blame(args):
    """Per-line commit attribution."""
    from .repository import Repository
    from .diff import blame

    repo = Repository(".")
    blame(repo, args.path)


def cmd_revert(args):
    """Create a commit that undoes a previous commit."""
    from .repository import Repository
    from .merge import revert

    repo = Repository(".")
    try:
        revert(repo, args.sha)
    except Exception as e:
        print(f"revert: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_gc(args):
    """Pack loose objects, delete unreachable objects."""
    from .repository import Repository
    from .pack import gc

    repo = Repository(".")
    gc(repo)
    print("Garbage collection complete")


def cmd_serve(args):
    from .repository import Repository
    from .network import Server

    repo = Repository(".")
    server = Server(repo, args.bind, args.port)
    print(f"Serving on {args.bind}:{args.port}")
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def cmd_clone(args):
    """Clone from a remote server."""
    from .repository import Repository
    from .network import Client

    host, port = args.host_port.split(":")
    repo = Repository(args.dir)
    repo.init()
    client = Client(repo)
    client.clone(host, int(port))
    print(f"Cloned into '{args.dir}'")


def cmd_push(args):
    """Push to a remote server."""
    from .repository import Repository
    from .network import Client

    repo = Repository(".")
    client = Client(repo)
    host, port = args.host_port.split(":")
    try:
        client.push(host, int(port))
        print(f"Pushed to {args.host_port}")
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="pygit",
        description="pygit — a real, content-addressed version control system in pure Python",
    )
    subparsers = parser.add_subparsers(dest="command", help="available commands")

    # init
    p_init = subparsers.add_parser("init", help="create an empty pygit repository")
    p_init.add_argument("path", nargs="?", default=".", help="repository path")
    p_init.set_defaults(func=cmd_init)

    # add
    p_add = subparsers.add_parser("add", help="add file contents to the index")
    p_add.add_argument("paths", nargs="+", help="files to add")
    p_add.set_defaults(func=cmd_add)

    # commit
    p_commit = subparsers.add_parser("commit", help="record changes to the repository")
    p_commit.add_argument("-m", "--message", required=True, help="commit message")
    p_commit.set_defaults(func=cmd_commit)

    # log
    p_log = subparsers.add_parser("log", help="show commit logs")
    p_log.set_defaults(func=cmd_log)

    # status
    p_status = subparsers.add_parser("status", help="show the working tree status")
    p_status.set_defaults(func=cmd_status)

    # diff
    p_diff = subparsers.add_parser("diff", help="show changes between commits, working tree, and index")
    p_diff.add_argument("paths", nargs="*", help="specific files")
    p_diff.add_argument("--staged", action="store_true", help="show staged changes")
    p_diff.set_defaults(func=cmd_diff)

    # branch
    p_branch = subparsers.add_parser("branch", help="list, create, or delete branches")
    p_branch.add_argument("name", nargs="?", help="branch name")
    p_branch.set_defaults(func=cmd_branch)

    # checkout
    p_checkout = subparsers.add_parser("checkout", help="switch branches or restore working tree")
    p_checkout.add_argument("target", help="branch name or commit sha")
    p_checkout.set_defaults(func=cmd_checkout)

    # merge
    p_merge = subparsers.add_parser("merge", help="join two or more development histories")
    p_merge.add_argument("branch", help="branch to merge")
    p_merge.set_defaults(func=cmd_merge)

    # tag
    p_tag = subparsers.add_parser("tag", help="create, list, delete or verify a tag")
    p_tag.add_argument("name", help="tag name")
    p_tag.add_argument("-m", "--message", help="tag message (creates annotated tag)")
    p_tag.set_defaults(func=cmd_tag)

    # reset
    p_reset = subparsers.add_parser("reset", help="reset current HEAD to specified state")
    p_reset.add_argument("--soft", action="store_const", const="soft", dest="mode", help="soft reset")
    p_reset.add_argument("--mixed", action="store_const", const="mixed", dest="mode", help="mixed reset")
    p_reset.add_argument("--hard", action="store_const", const="hard", dest="mode", help="hard reset")
    p_reset.add_argument("commit", help="target commit")
    p_reset.set_defaults(func=cmd_reset)

    # stash
    p_stash = subparsers.add_parser("stash", help="stash away changes")
    p_stash.add_argument("stash_action", nargs="?", default="push", choices=["push", "pop", "list"],
                         help="stash action")
    p_stash.set_defaults(func=cmd_stash)

    # cherry-pick
    p_cherrypick = subparsers.add_parser("cherry-pick", help="apply a commit's changes")
    p_cherrypick.add_argument("sha", help="commit sha to cherry-pick")
    p_cherrypick.set_defaults(func=cmd_cherry_pick)

    # rebase
    p_rebase = subparsers.add_parser("rebase", help="reapply commits on top of another base")
    p_rebase.add_argument("branch", help="branch to rebase onto")
    p_rebase.set_defaults(func=cmd_rebase)

    # reflog
    p_reflog = subparsers.add_parser("reflog", help="show reflog")
    p_reflog.set_defaults(func=cmd_reflog)

    # remote
    p_remote = subparsers.add_parser("remote", help="manage remote repositories")
    remote_sub = p_remote.add_subparsers(dest="remote_action", help="remote actions")
    p_remote_add = remote_sub.add_parser("add", help="add a remote")
    p_remote_add.add_argument("name", help="remote name")
    p_remote_add.add_argument("address", help="host:port")
    p_remote.set_defaults(func=cmd_remote)

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="download objects and refs from a remote")
    p_fetch.add_argument("remote", help="remote name")
    p_fetch.set_defaults(func=cmd_fetch)

    # blame
    p_blame = subparsers.add_parser("blame", help="show what revision and author last modified each line")
    p_blame.add_argument("path", help="file path")
    p_blame.set_defaults(func=cmd_blame)

    # revert
    p_revert = subparsers.add_parser("revert", help="revert an existing commit")
    p_revert.add_argument("sha", help="commit sha to revert")
    p_revert.set_defaults(func=cmd_revert)

    # gc
    p_gc = subparsers.add_parser("gc", help="clean up unnecessary files and optimize the repository")
    p_gc.set_defaults(func=cmd_gc)

    # clone
    p_clone = subparsers.add_parser("clone", help="clone a remote repository")
    p_clone.add_argument("host_port", help="host:port of the server")
    p_clone.add_argument("dir", help="target directory")
    p_clone.set_defaults(func=cmd_clone)

    p_push = subparsers.add_parser("push", help="update remote refs along with associated objects")
    p_push.add_argument("host_port", help="host:port of the server")
    p_push.set_defaults(func=cmd_push)

    p_serve = subparsers.add_parser("serve", help="start a server to serve this repository")
    p_serve.add_argument("--port", type=int, default=9418, help="port to listen on (default: 9418)")
    p_serve.add_argument("--bind", default="0.0.0.0", help="address to bind to (default: 0.0.0.0)")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
