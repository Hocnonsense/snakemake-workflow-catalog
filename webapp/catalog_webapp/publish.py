"""Deliver a deployment: download it as a zip or submit it to GitHub."""

from __future__ import annotations

import io
import re
import zipfile


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


def zip_bytes(deployment: DeploymentFS):
    """A zip of every deployed file; overrides win over the downloaded tree."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(deployment.paths()):
            content = deployment.read(path)
            if content is not None:
                archive.writestr(path, content)
    return buffer.getvalue()


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
    deploy_from: str,
    ref: Ref,
    files: dict[str, bytes],
    *,
    target_repo: dict,
) -> str:
    """Commit the deployment to ``branch`` of a repository in the user's account.

    The deployed tree is a thin wrapper around the upstream workflow (config,
    profiles, generated Snakefile), so it belongs in the user's own repository
    rather than in the upstream one.  The branch is created when missing (from
    the repository's default branch, or as the root of an empty repository) and
    replaced with the deployment when it exists.  Returns the repository URL.
    """
    if not gh.token:
        raise PublishError("Publishing needs a GitHub token.")
    if not valid_branch(branch):
        raise PublishError(f"Invalid branch name: {branch!r}.")
    if not files:
        raise PublishError("Nothing to publish: the deployment is empty.")
    full_name = target_repo["full_name"]
    message = f"Deploy {deploy_from}@{ref.name} with the Snakemake workflow catalog"
    default = target_repo.get("default_branch") or "main"
    head = gh.get_ref_sha(full_name, branch)
    if head is None:
        parent = gh.get_ref_sha(full_name, default)
        if parent is None:
            gh.commit_files(full_name, branch, files, message, default_branch=default)
            if branch != default:
                gh.set_default_branch(full_name, branch)
        else:
            tree = gh.create_tree(full_name, _entries(gh, full_name, files))
            commit = gh.create_commit(full_name, message, tree, parent)
            gh.create_ref(full_name, branch, commit)
    else:
        tree = gh.create_tree(full_name, _entries(gh, full_name, files))
        commit = gh.create_commit(full_name, message, tree, head)
        gh.update_ref(full_name, branch, commit)
    return target_repo["html_url"]


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


def publish_form(fs: DeploymentFS, gh: GitHub, repo: str, ref: Ref, slot):
    import streamlit as st
    from snakelit.utils.ui_components import persistent_text_input

    user: str | None = st.session_state.get("gh-login")
    # # noqa: "gh-login" set in auth; user depending gh.token checked in toggle_button
    # if user is None:
    #    user = gh.current_user()["login"]
    if not user or not gh.token:
        return
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
            try:
                target = gh.get_repo(name)
                branches = sorted({ref.name for ref in gh.iter_branches(name)})
                if not branches:
                    default_branch = target.get("default_branch")
                    if default_branch:
                        branches.append(default_branch)
                checked = (user, name, target, branches)
            except GitHubError as error:
                if error.status != 404:
                    return st.error(f"Could not check {name} on GitHub: {error}.")
                checked = (user, name, None, [])
            st.session_state["publish-check"] = checked
        _, _, target, branches = checked
    if target is None:
        if not name.lower().startswith(f"{user.lower()}/"):
            return st.error(
                f"Repository {name} does not exist. "
                "Could not create a new repository in another user's account."
            )
        caption = f"will create a new repo {name}"
    else:
        caption = f"will push to {name}"

    with branch_col:
        if branches:
            default = (target or {}).get("default_branch", "")
            index = branches.index(default) if default in branches else 0
        else:
            default = "main"
            index = 0
        branch = st.selectbox(
            "Branch",
            branches or [default],
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
    if branch in branches:
        st.caption(
            caption + " and overwrite existing content of branch " + branch + "."
        )
    else:
        st.caption(caption + " and create new branch " + branch + ".")

    slot.empty()
    push_col, pull_col = slot.columns([1, 1])
    with push_col:
        if st.session_state.get("publish-target") != (user, name, branch):
            st.session_state["publish-target"] = (user, name, branch)
            st.session_state.pop("publish-error", None)
            st.session_state.pop("publish-url", None)
        if st.button("Push", key="publish", width="stretch"):
            files: dict[str, bytes] = {}
            for path in sorted(fs.paths()):
                content = fs.read(path)
                if content is not None:
                    files[path] = content
            if not files:
                return st.error("No files to publish.")
            try:
                with st.spinner("Publishing to GitHub..."):
                    flush_spinner()
                    if target is None:
                        target = gh.create_repo(
                            name.rpartition("/")[2],
                            description=(
                                "Create from Snakemake workflow catalog"
                                " webapp to deploy a workflow."
                            ),
                        )
                    url = full_push(gh, branch, repo, ref, files, target_repo=target)
            except (GitHubError, PublishError) as error:
                st.session_state["publish-error"] = str(error)
                st.session_state.pop("publish-url", None)
            else:
                st.session_state["publish-url"] = url
                st.session_state.pop("publish-error", None)
            st.session_state.pop("publish-check", None)  # to refresh repo and branches
        if st.session_state.get("publish-error"):
            st.error(st.session_state["publish-error"])
        if st.session_state.get("publish-url"):
            st.link_button("Open repository", st.session_state["publish-url"])
