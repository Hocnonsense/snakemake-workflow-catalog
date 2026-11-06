"""The page shows the repo/ref from bootstrap.json and offers token login."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_webapp.github import GitHub  # noqa: E402
from snakelit.types import Ref  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app.py"


def _load(kind):
    if kind == "tag":
        return iter(
            [
                Ref(
                    "tag",
                    "v1.0",
                    "abc1234",
                    time=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
                )
            ]
        )
    return iter([])


@pytest.fixture
def app(tmp_path, monkeypatch):
    (tmp_path / "bootstrap.json").write_text(
        json.dumps({"repo": "owner/wf", "ref": "v1.0"}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(GitHub, "repo_ref_cache", lambda self, repo: _load)

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    return at


def test_shows_repo_and_ref(app):
    assert not app.exception, [str(error.value) for error in app.exception]

    title = "\n".join(item.value for item in app.title)
    captions = "\n".join(item.value for item in app.caption)
    assert "owner/wf" in title
    assert "v1.0" in captions

    labels = [item.label for item in app.button]
    assert any(
        label.startswith("v1.0 (2026-01-02 03:04 UTC)") and label.endswith("▾")
        for label in labels
    )
    keys = [item.key for item in app.button]
    for kind in ("tag", "branch", "commit"):
        assert f"ref-picker-owner/wf-anon-kind-{kind}" in keys


def test_ref_picker_shows_time_in_parentheses(app):
    tag_button = next(
        item for item in app.button if item.key == "ref-picker-owner/wf-anon-kind-tag"
    )
    tag_button.click()
    app.run()

    assert not app.exception, [str(error.value) for error in app.exception]
    assert "v1.0 (2026-01-02 03:04 UTC)" in app.radio[0].options


def test_sidebar_offers_token_login(app):
    assert not app.exception, [str(error.value) for error in app.exception]
    assert "Personal access token" in [item.label for item in app.text_input]
    assert "Create a token" in [
        item.label for item in app.get("link_button")
    ]
