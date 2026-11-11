"""stlite app: pick a workflow ref, deploy it, edit its configuration."""

from __future__ import annotations

import json
from functools import partial

import streamlit as st

from snakelit.types import Ref
from snakelit.version_picker import version_picker
from snakelit.edit import edit_for
from snakelit.file_explorer import FileExplorer
from snakelit.merge import diff_files, render_merge
from snakelit.utils.zip import ArchiveError, unzip, zipped
from catalog_webapp.auth import render_auth
from catalog_webapp.deploy import DeployError, deploy
from catalog_webapp.fs import DeploymentFS
from catalog_webapp.github import GitHub, GitHubError
from catalog_webapp.publish import publish_form
from catalog_webapp.stlite import flush_spinner

st.set_page_config(page_title="Deploy a Snakemake workflow", layout="wide")


def _bootstrap() -> dict:
    """Read the parameters that index.html mounted from the page URL."""
    try:
        with open("bootstrap.json", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


bootstrap = _bootstrap()
repo: str = bootstrap.get("repo", "")
ref = bootstrap.get("ref", "")

if repo:
    st.title(f"Deploy workflow: [`{repo}`](https://github.com/{repo})")
else:
    st.error(
        "No workflow repository was passed in the URL (?repo=owner/name). "
        "Please access the app through the "
        "[catalog](https://snakemake.github.io/snakemake-workflow-catalog/)"
    )
    st.stop()


with st.sidebar:
    gh = GitHub(render_auth())


auth = "auth" if gh.token else "anon"
ref = version_picker(ref, gh.repo_ref_cache(repo), key=f"ref-picker-{repo}-{auth}")
if ref is None:
    st.stop()
    raise NotImplementedError("Should stop by st")


def start_zip_merge(fs: DeploymentFS, name: str, data: bytes):
    """Compare an uploaded zip with ``fs``; return whether to rerun the page."""
    try:
        incoming = unzip(data)
    except ArchiveError as error:
        st.error(str(error))
        return False
    st.session_state["merge"] = (name, diff_files(fs, incoming))
    return True


def _run_deploy(gh: GitHub, repo: str, ref: Ref):
    """Deploy inside the click callback so the app is busy while fetching."""
    with st.spinner("Deploying workflow..."):
        flush_spinner()
        try:
            deployment = deploy(repo, ref, gh)
        except (GitHubError, DeployError) as error:
            st.session_state["deploy-error"] = str(error)
            st.session_state.pop("deploy-result", None)
        else:
            result_key = f"{repo}@{ref.sha}"
            explorer = FileExplorer(
                key=f"file-view-{result_key}",
                store=deployment,
                on_zip=partial(start_zip_merge, deployment),
            )
            deployment.set_file_editors(
                partial(explorer.change_preview, args=("edit",))
            )
            st.session_state["deploy-result"] = {
                "key": result_key,
                "explorer": explorer,
            }
            st.session_state.pop("merge", None)
            st.session_state.pop("publish-branch", None)
            st.session_state.pop("publish-form-open", None)
            st.session_state.pop("deploy-error", None)


st.button(
    "Deploy",
    key="deploy",
    disabled=not ref.sha,
    on_click=_run_deploy,
    args=(gh, repo, ref),
)
if st.session_state.get("deploy-error"):
    st.error(st.session_state["deploy-error"])
result = st.session_state.get("deploy-result")
if not result:
    st.stop()
key: str = result["key"]
if key != f"{repo}@{ref.sha}":
    last_ref = key.split("@", 1)[-1]
    st.info(
        "The workflow ref has changed. "
        "Click the **Deploy** button to fetch the new version. "
        f"Or Select the ref {last_ref} again to continue"
    )
    st.stop()

explorer = result["explorer"]
fs: DeploymentFS = explorer.store
explorer.render(header="Browse deployed files")

edit_for(fs.config_file(), fs, key=f"config-{key}", editors=fs.editors)

st.divider()
download_col, publish_col = [i.empty() for i in st.columns(2)]

file_name = (
    f"{repo.replace('/', '-')}-{(ref.sha[:7] or ref.name).replace('/', '-')}.zip"
)
if download_col.button(
    "Prepare download",
    key="prepare-download",
    width="stretch",
    help="Build the archive and replace this button with the download.",
):
    download_col.empty()
    download_col.download_button(
        "Download zip",
        data=zipped(fs),
        file_name=file_name,
        mime="application/zip",
        width="stretch",
    )
if not st.session_state.get("publish-form-open"):
    if publish_col.button(
        "Submit to GitHub",
        key="github-publish",
        width="stretch",
        disabled=not gh.token,
        help="Connect with a personal access token in the sidebar.",
    ):
        st.session_state["publish-form-open"] = True
if st.session_state.get("publish-form-open"):
    publish_form(fs, gh, repo, ref, publish_col, diff_files=diff_files)

head, files = st.session_state.get("merge", (None, {}))
if files:
    if isinstance(head, tuple) and len(head) == 3:
        repo, branch, sha = head
        label = f"{repo}@{branch}" + (f" ({sha[:7]})" if sha else "")
    else:
        label = f"upload {head}" if head else "upload"
    if render_merge(fs, f"Merge {label}", files) is None:
        st.session_state.pop("merge", None)
        st.rerun()
