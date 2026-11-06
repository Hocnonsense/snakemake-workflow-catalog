"""Minimal stlite app: show the workflow and ref passed by the catalog button.

Deployment and configuration are intentionally not wired yet.  They are the
next phases in ``BROWSER_DEPLOY_PLAN.md``; the building blocks already live in
``catalog_webapp/`` (``auth.py``, ``deploy.py``, ``config_ui.py``) and will be
wired back in one step at a time.
"""

from __future__ import annotations

import json

import streamlit as st

from catalog_webapp.auth import render_auth
from catalog_webapp.github import GitHub
from snakelit.version_picker import version_picker

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
if ref:
    sha = f" (`{ref.sha[:7]}`)" if ref.sha else ""
    st.caption(f"Selected: `{ref.kind}={ref.name}`{sha}")
