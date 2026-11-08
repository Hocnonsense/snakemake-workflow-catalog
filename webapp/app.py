"""stlite app: pick a workflow ref, deploy it, edit its configuration."""

from __future__ import annotations

import json
from functools import partial

import streamlit as st

from snakelit.types import Ref
from snakelit.version_picker import version_picker
from snakelit.file_view import FileExplorer
from catalog_webapp.auth import render_auth
from catalog_webapp.deploy import DeployError, deploy
from catalog_webapp.fs import DeploymentFS
from catalog_webapp.github import GitHub, GitHubError

st.set_page_config(page_title="Deploy a Snakemake workflow", layout="wide")


def _bootstrap() -> dict:
    """Read the parameters that index.html mounted from the page URL."""
    try:
        with open("bootstrap.json", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


bootstrap = _bootstrap()
repo = bootstrap.get("repo", "")
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


def _run_deploy(gh: GitHub, repo: str, ref: Ref):
    """Deploy inside the click callback so the app is busy while fetching."""
    try:
        deployment = deploy(repo, ref, gh)
    except (GitHubError, DeployError) as error:
        st.session_state["deploy-error"] = str(error)
        st.session_state.pop("deploy-result", None)
    else:
        result_key = f"{repo}@{ref.sha}"
        explorer = FileExplorer(key=f"file-view-{result_key}", store=deployment)
        deployment.set_file_editors(
            partial(explorer.change_preview, args=("edit",))
        )
        st.session_state["deploy-result"] = {
            "key": result_key,
            "explorer": explorer,
        }
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
if result["key"] != f"{repo}@{ref.sha}":
    last_ref = result["key"].split("@", 1)[-1]
    st.info(
        "The workflow ref has changed. "
        "Click the **Deploy** button to fetch the new version. "
        f"Or Select the ref {last_ref} again to continue"
    )
    st.stop()

explorer = result["explorer"]
deployment: DeploymentFS = explorer.store
explorer.render(header="Browse deployed files")

config_editor = deployment.show(deployment.config_file(), "Edit")
if config_editor is not None:
    config_editor()
