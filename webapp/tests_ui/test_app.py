"""The page shows the repo/ref from bootstrap.json and offers token login."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

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


FILES = {
    "workflow/Snakefile": b"rule all:\n    pass\n",
    "config/config.yaml": b"samples: samples.tsv\nx: 1\n",
    "workflow/schemas/config.schema.yaml": (
        b"type: object\n"
        b"required: [samples]\n"
        b"properties:\n"
        b"  samples:\n"
        b"    type: string\n"
        b"  x:\n"
        b"    type: integer\n"
    ),
    "LICENSE": b"MIT\n",
}


def _start(tmp_path, monkeypatch, files):
    (tmp_path / "bootstrap.json").write_text(
        json.dumps({"repo": "owner/wf", "ref": "v1.0"}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(GitHub, "repo_ref_cache", lambda self, repo: _load)
    monkeypatch.setattr(
        GitHub,
        "get_tree",
        lambda self, repo, ref: {
            "tree": [{"path": path, "type": "blob"} for path in files]
        },
    )
    monkeypatch.setattr(
        GitHub,
        "fetch_files",
        lambda self, repo, ref, paths: {path: files[path] for path in paths},
    )

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    return at


@pytest.fixture
def app(tmp_path, monkeypatch):
    return _start(tmp_path, monkeypatch, FILES)


@pytest.fixture
def app_with_broken_config(tmp_path, monkeypatch):
    files = dict(FILES)
    files["config/config.yaml"] = b"samples: [\n"
    return _start(tmp_path, monkeypatch, files)


def test_shows_repo_and_ref(app):
    assert not app.exception, [str(error.value) for error in app.exception]

    title = "\n".join(item.value for item in app.title)
    assert "owner/wf" in title

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
    assert "Create a token" in [item.label for item in app.get("link_button")]


def test_deploy_lists_downloaded_files(app):
    deploy_button = next(item for item in app.button if item.label == "Deploy")
    deploy_button.click()
    app.run()

    assert not app.exception, [str(error.value) for error in app.exception]
    assert "Browse deployed files" in [item.label for item in app.button]
    next(item for item in app.button if item.label == "Browse deployed files").click()
    app.run()
    workflow_dir = next(
        key
        for key in (item.key for item in app.button)
        if key and key.endswith("-dir-workflow")
    )
    app.button(key=workflow_dir).click()
    app.run()
    assert "Snakefile" in [item.label for item in app.button]


def test_deploy_selects_the_upstream_schema(app):
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()

    selector = next(
        item for item in app.selectbox if item.key and item.key.endswith("-schema")
    )
    assert selector.value == "workflow/schemas/config.schema.yaml"


def test_editing_config_writes_an_override(app):
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()

    samples = next(
        item for item in app.text_input if item.key and item.key.endswith("-samples")
    )
    samples.set_value("other.tsv")
    app.run()

    deployment = app.session_state["deploy-result"]["explorer"].store
    assert (
        yaml.safe_load(deployment.read("config/config.yaml"))["samples"] == "other.tsv"
    )


def test_broken_config_is_reported(app_with_broken_config):
    next(
        item for item in app_with_broken_config.button if item.label == "Deploy"
    ).click()
    app_with_broken_config.run()

    assert not app_with_broken_config.exception
    assert app_with_broken_config.error


def test_create_file_from_a_config_value(app):
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()

    samples = next(
        item for item in app.text_input if item.key and item.key.endswith("-samples")
    )
    samples.set_value("notes.txt")
    app.run()

    create = next(
        item for item in app.button if item.key and item.key.endswith("-samples-file")
    )
    assert create.label == "Edit"
    create.click()
    app.run()

    assert not app.exception, [str(error.value) for error in app.exception]
    editor = next(
        item for item in app.text_area if item.key and "-preview-text" in item.key
    )
    editor.set_value("sample\tcondition\n")
    app.run()

    deployment = app.session_state["deploy-result"]["explorer"].store
    assert deployment.read("notes.txt") == b"sample\tcondition\n"
    next(item for item in app.button if item.label == "Browse deployed files").click()
    app.run()
    assert "notes.txt" in [item.label for item in app.button]
