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

st.title("Deploy a Snakemake workflow")

with st.sidebar:
    gh_token = render_auth()

if repo:
    st.markdown(f"**Workflow:** [`{repo}`](https://github.com/{repo})")
else:
    st.warning("No workflow repository was passed in the URL (?repo=owner/name).")

if ref:
    st.markdown(f"**Tag / ref:** `{ref}`")
else:
    st.info("No tag was passed in the URL (?ref=...).")

st.divider()
st.caption("Minimal build: deployment and configuration are not wired yet.")
