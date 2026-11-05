"""GitHub authentication for the browser app.

Until then the app uses a personal access token. It is kept in `st.session_state` only, which means it is gone after a page reload.
"""

from __future__ import annotations

import json
import urllib.request

import streamlit as st

_TOKEN_DESCRIPTION = "Snakemake%20workflow%20catalog%20deploy"
_USER_AGENT = "snakemake-workflow-catalog-webapp"


def _current_login(token: str) -> str:
    """Validate a token with a single ``GET /user`` call."""
    request = urllib.request.Request("https://api.github.com/user")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", _USER_AGENT)
    request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())["login"]


def _token_url(scope: str):
    return (
        "https://github.com/settings/tokens/new"
        f"?scopes={scope}&description={_TOKEN_DESCRIPTION}"
    )


def _private_repository():
    """Whether asked for a private target repository.

    Private repositories require a token with the `repo` scope,
    while public repositories only need `public_repo`.
    If the user made a choice in step 4, automatically use that choice.
    """
    return bool(st.session_state.get("target-private", False))


def token_instructions():
    """Numbered instructions with a single, scope-aware token button."""
    st.markdown("**1.** Click **Create a token** above.")
    st.caption(
        "Normally (public repositories), the `public_repo` scope is sufficient, "
        "creating a **private repository** requires the `repo` scope. "
    )
    st.markdown(
        "**2.** Choose an expiration, click **Generate token**, and copy it.\n\n"
        "**3.** Paste it above and click **Connect**."
    )
    st.caption("The token is stored in memory and disappears on reload.")


def _disconnect():
    st.session_state["gh-token-input"] = ""
    for key in ("gh-token", "gh-login", "gh-error"):
        st.session_state.pop(key, None)


def _connect():
    token = st.session_state.get("gh-token-input") or ""
    try:
        login = _current_login(token)
    except Exception as error:  # noqa: BLE001 - shown by the caller
        st.session_state["gh-error"] = str(error)
        st.session_state.pop("gh-token", None)
        st.session_state.pop("gh-login", None)
    else:
        st.session_state["gh-token"] = token
        st.session_state["gh-login"] = login
        st.session_state.pop("gh-error", None)


def render_auth():
    """Render the sidebar login and return the validated token, if any."""
    st.header("GitHub access")

    gh_token = st.session_state.get("gh-token")
    if gh_token:
        # ``gh-token`` is only written after `/user` accepted the token,
        # so its presence is the connection state.
        st.success(f"login as {st.session_state['gh-login']}")
        st.button("disconnect", key="disconnect", on_click=_disconnect)
        return gh_token

    token = st.text_input(
        "Personal access token",
        type="password",
        key="gh-token-input",
        help="Used only in this browser session. Sent only to api.github.com.",
    )

    url = _token_url("repo" if _private_repository() else "public_repo")
    col_create, col_connect = st.columns(2)
    col_create.link_button("Create a token", url)
    col_connect.button("Connect", key="connect", on_click=_connect, disabled=not token)

    token_instructions()

    if st.session_state.get("gh-error"):
        st.error(f"Could not use this token: {st.session_state['gh-error']}")
    else:
        st.caption(
            "GitHub strictly limits anonymous API requests per hour. "
            "Logging in with a personal access token allows for more requests."
        )
