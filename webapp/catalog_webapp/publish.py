"""Deliver a deployment: download it as a zip or submit it to GitHub."""

from __future__ import annotations

import re
import urllib.parse

from snakelit.types import Ref

from .deploy import DeploymentFS
from .github import GitHub, GitHubError

from .stlite import flush_spinner


class PublishError(Exception):
    """The deployment cannot be published."""


REPOSITORY = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
OWNER = re.compile(r"^[A-Za-z0-9-]{1,39}$")


def valid_branch(branch: str):
    """Whether ``branch`` is a usable git branch name."""
    if not branch or branch == "@" or branch.startswith(("-", "/", ".")):
        return False
    if branch.endswith(("/", ".")):
        return False
    if any(ch in branch for ch in " ~^:?*[\\") or ".." in branch or "@{" in branch:
        return False
    if any(ord(ch) < 32 for ch in branch) or "//" in branch:
        return False
    return all(part and not part.endswith(".lock") for part in branch.split("/"))


def repo_name(repo: str, user: str | None = None):
    """The default name of the user's copy of a workflow.

    ``wf`` becomes ``<user>/wf``; ``owner/name`` is kept when both parts are
    valid.  Returns ``None`` for an unusable name.
    """
    if "/" in repo:
        user, _, repo = repo.rpartition("/")
    elif not user:
        return None
    if not OWNER.fullmatch(user) or not REPOSITORY.fullmatch(repo):
        return None
    return f"{user}/{repo}"


def full_push(
    gh: GitHub,
    branch: str,
    message: str,
    files: dict[str, bytes],
    *,
    target_repo: dict,
    expected_sha: str | None = None,
) -> str:
    """Commit the deployment to ``branch`` of a repository in the user's account.

    The deployed tree is a thin wrapper around the upstream workflow (config,
    profiles, generated Snakefile), so it belongs in the user's own repository
    rather than in the upstream one.  A missing branch is created as a root
    commit containing only the deployment; an existing branch is replaced with
    the deployment.  With ``expected_sha``, the
    update only happens if the branch still points at the commit that was
    pulled, so a concurrent change is never overwritten.  Returns the new
    commit sha; the repository URL is derived from the repository name.
    """
    if not gh.token:
        raise PublishError("Publishing needs a GitHub token.")
    if not valid_branch(branch):
        raise PublishError(f"Invalid branch name: {branch!r}.")
    if not files:
        raise PublishError("Nothing to publish: the deployment is empty.")
    full_name = target_repo["full_name"]
    head = gh.get_ref_sha(full_name, branch)
    if expected_sha is not None and head != expected_sha:
        raise PublishError(
            "The branch moved since the pull; pull and merge again before pushing."
        )
    if head is None:
        try:
            tree = gh.create_tree(full_name, _entries(gh, full_name, files))
            # A new branch is a root commit: it does not inherit the default
            # branch's tree or history.
            commit = gh.create_commit(full_name, message, tree)
            gh.create_ref(full_name, branch, commit)
        except GitHubError as error:
            if error.status not in (404, 409, 422):
                raise
            # The Git Data API rejects an empty repository.  Initialize it
            # through the contents API, then replace the temporary commit with
            # a root commit that contains the complete deployment.  The
            # contents API may reject a branch that does not exist yet, so
            # initialize on the repository's current default first.
            # ``default_branch`` is only the configured name; an empty
            # repository has this field but no ref/commit yet.
            initial_branch = target_repo.get("default_branch") or branch
            gh.commit_files(full_name, initial_branch, files, message)
            tree = gh.create_tree(full_name, _entries(gh, full_name, files))
            commit = gh.create_commit(full_name, message, tree)
            if branch == initial_branch:
                gh.update_ref(full_name, branch, commit)
            else:
                gh.create_ref(full_name, branch, commit)
                gh.set_default_branch(full_name, branch)
    else:
        tree = gh.create_tree(full_name, _entries(gh, full_name, files))
        commit = gh.create_commit(full_name, message, tree, head)
        gh.update_ref(full_name, branch, commit)
    return commit


def push_deployment(
    fs: DeploymentFS,
    gh: GitHub,
    *,
    name: str,
    target_repo: dict | None,
    branch: str,
    message: str,
    expected_sha: str | None = None,
):
    """Push every current file.

    ``target_repo`` is ``None`` for a repository that still has to be created.
    """
    files = {
        path: content
        for path in sorted(fs.paths())
        if (content := fs.read(path)) is not None
    }
    if not files:
        raise PublishError("No files to publish.")
    current = target_repo
    if current is None:
        current = gh.create_repo(
            name.rpartition("/")[2],
            description=(
                "Create from Snakemake workflow catalog webapp to deploy a workflow."
            ),
        )
    return full_push(
        gh, branch, message, files, target_repo=current, expected_sha=expected_sha
    )


def _entries(gh: GitHub, full_name: str, files: dict):
    return [
        {
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": gh.create_blob(full_name, content),
        }
        for path, content in files.items()
    ]


def _restore_branch_select(
    branches: list[str], cached_branch: str | None, default_branch: str | None
):
    if cached_branch:
        if cached_branch not in branches:
            branches.append(cached_branch)
        return branches.index(cached_branch)
    default = default_branch or "main"
    if default in branches:
        return branches.index(default)
    if not branches:
        branches.append(default)
    return 0


def publish_form(
    fs: DeploymentFS, gh: GitHub, repo: str, ref: Ref, slot, *, diff_files
):
    import streamlit as st
    from snakelit.utils.ui_components import persistent_text_input

    user: str | None = st.session_state.get("gh-login")
    # # noqa: "gh-login" set in auth; user depending gh.token checked in toggle_button
    # if user is None:
    #    user = gh.current_user()["login"]
    if not user or not gh.token:
        st.session_state.pop("publish-form-open", None)
        return
    slot.empty()
    push_col, pull_col, close = slot.columns([1, 1, 1])
    if close.button("Close", key="publish-close", width="stretch"):
        st.session_state.pop("publish-form-open", None)
        st.rerun()

    repo_col, branch_col = st.columns([2, 2], vertical_alignment="bottom")
    with repo_col:
        default_name = repo_name(repo.rsplit("/", 1)[-1], user) or ""
        raw_name = (
            persistent_text_input("Repository", "publish-repo", default_name)
            or default_name
        )
        name = repo_name(raw_name, user)
        if not name:
            st.error("Invalid repository name.")
            return
        checked = st.session_state.get("publish-check")
        if not checked or checked[:2] != (user, name):
            st.session_state.pop("publish-branch", None)
            try:
                target = gh.get_repo(name)
                heads = {ref.name: ref.sha for ref in gh.iter_branches(name)}
                checked = (user, name, target, heads)
            except GitHubError as error:
                if error.status != 404:
                    return st.error(f"Could not check {name} on GitHub: {error}.")
                checked = (user, name, None, {})
            st.session_state["publish-check"] = checked
        _, _, target, heads = checked
    if target is None:
        if not name.lower().startswith(f"{user.lower()}/"):
            return st.error(
                f"Repository {name} does not exist. "
                "Could not create a new repository in another user's account."
            )
        caption = f"will create a new repo {name}"
    else:
        repo_url = target.get("html_url") or f"https://github.com/{name}"
        caption = f"will push to [{name}]({repo_url})"

    with branch_col:
        branches = sorted(heads)
        index = _restore_branch_select(
            branches,
            st.session_state.get("publish-branch"),
            (target or {}).get("default_branch"),
        )
        branch = st.selectbox(
            "Branch",
            branches,
            index=index,
            key=f"publish-branch-{user}",
            accept_new_options=True,
        )
    if not branch:
        st.caption(caption + ".")
        return st.error("Please provide or specify a branch name.")
    if not valid_branch(branch):
        st.caption(caption + ".")
        return st.error(f"Invalid branch name: {branch!r}.")
    if st.session_state.get("publish-branch") != branch:
        st.session_state["publish-branch"] = branch
        st.session_state.pop("publish-error", None)

    merge = st.session_state.get("merge")
    help = None
    if branch in heads:
        if not (
            isinstance(merge, tuple)
            and merge[0][:3] == (name, branch, heads.get(branch))
        ):
            help = (
                "Pull this branch to compare it "
                "with the current deployment before pushing."
            )
        elif merge[1]:
            help = "Finish the merge below before pushing."
        st.caption(
            f"{caption} and overwrite existing content of branch"
            f" [`{branch}`]({repo_url}/tree/{urllib.parse.quote(branch, safe='/')})."
        )
    else:
        st.caption(caption + f" and create new branch `{branch}`.")

    push_clicked = push_col.button(
        "Push", key="publish", width="stretch", disabled=bool(help), help=help
    )
    pull_clicked = pull_col.button(
        "Pull",
        key="pull",
        width="stretch",
        disabled=target is None,
        help="Fetch this branch and compare it with the current deployment.",
    )

    if push_clicked:
        message = f"Deploy {repo}@{ref.name} with the Snakemake workflow catalog"
        try:
            with st.spinner("Publishing to GitHub...", width="stretch"):
                flush_spinner()
                commit = push_deployment(
                    fs,
                    gh,
                    name=name,
                    target_repo=target,
                    branch=branch,
                    message=message,
                    expected_sha=heads.get(branch),
                )
            st.info(f"Published to {name}@{branch} as commit {commit}.")
        except (GitHubError, PublishError) as error:
            st.session_state["publish-error"] = str(error)
        else:
            st.session_state.pop("publish-error", None)
            if merge:
                st.session_state.pop("merge", None)
        st.session_state.pop("publish-check", None)  # refresh repo and heads

    elif pull_clicked:
        if target is None:
            st.session_state["publish-error"] = (
                "Push this deployment to a repository before pulling."
            )
        else:
            try:
                with st.spinner("Pulling from GitHub...", width="stretch"):
                    flush_spinner()
                    sha, incoming = gh.pull_files(target["full_name"], branch)
                    st.session_state["merge"] = (
                        (target["full_name"], branch, sha),
                        diff_files(fs, incoming),
                    )
            except GitHubError as error:
                st.session_state["publish-error"] = f"Could not pull: {error}"
            else:
                st.session_state.pop("publish-error", None)

    if st.session_state.get("publish-error"):
        st.error(st.session_state["publish-error"])
