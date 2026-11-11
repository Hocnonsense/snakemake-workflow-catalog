"""The page shows the repo/ref from bootstrap.json and offers token login."""

import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_webapp.github import GitHub, GitHubError  # noqa: E402
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


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


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
    monkeypatch.setattr(
        GitHub,
        "get_repo",
        lambda self, owner_repo: (_ for _ in ()).throw(GitHubError(404, "Not Found")),
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


def test_prepare_download_builds_the_zip_on_click(app):
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()
    next(item for item in app.button if item.label == "Prepare download").click()
    app.run()

    assert [item.label for item in app.get("download_button")] == ["Download zip"]
    assert not [item for item in app.button if item.label == "Prepare download"]


def test_submit_form_appears_once_a_token_is_connected(app):
    app.session_state["gh-token"] = "token"
    app.session_state["gh-login"] = "me"
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()

    next(item for item in app.button if item.label == "Submit to GitHub").click()
    app.run()

    assert app.text_input(key="publish-repo").value == ""
    assert app.selectbox(key="publish-branch-me").options == ["main"]
    push = next(item for item in app.button if item.label == "Push")
    assert not push.disabled
    assert any(
        "will create a new repo" in item.value and "me/wf" in item.value
        for item in app.caption
    )


def test_submit_refuses_another_owners_missing_repository(app):
    app.session_state["gh-token"] = "token"
    app.session_state["gh-login"] = "me"
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()
    next(item for item in app.button if item.label == "Submit to GitHub").click()
    app.run()

    app.text_input(key="publish-repo").set_value("org/wf")
    app.run()

    assert any("does not exist" in item.value for item in app.error)
    assert not [item for item in app.button if item.label == "Push"]


def test_push_creates_the_repository_and_reports_it(app, monkeypatch):
    monkeypatch.setattr(
        GitHub,
        "create_repo",
        lambda self, name, **kwargs: {
            "full_name": f"me/{name}",
            "default_branch": "main",
            "html_url": "https://github.com/me/wf",
        },
    )
    monkeypatch.setattr(
        "catalog_webapp.publish.full_push",
        lambda *args, **kwargs: "https://github.com/me/wf",
    )
    app.session_state["gh-token"] = "token"
    app.session_state["gh-login"] = "me"
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()
    next(item for item in app.button if item.label == "Submit to GitHub").click()
    app.run()

    next(item for item in app.button if item.label == "Push").click()
    app.run()

    assert not app.exception


def test_pull_compares_incoming_files(app, monkeypatch):
    monkeypatch.setattr(
        GitHub,
        "get_repo",
        lambda self, name: {
            "full_name": "me/wf",
            "default_branch": "main",
            "html_url": "https://github.com/me/wf",
        },
    )
    monkeypatch.setattr(
        GitHub,
        "iter_branches",
        lambda self, name: [Ref("branch", "main", "old-sha")],
    )
    app.session_state["gh-token"] = "token"
    app.session_state["gh-login"] = "me"
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()
    next(item for item in app.button if item.label == "Submit to GitHub").click()
    app.run()

    fs = app.session_state["deploy-result"]["explorer"].store
    incoming = {path: fs.read(path) for path in fs.paths()}
    incoming["config/config.yaml"] = b"samples: pulled.tsv\n"
    monkeypatch.setattr(
        "catalog_webapp.github.GitHub.pull_files",
        lambda self, full_name, branch: ("old-sha", incoming),
    )

    next(item for item in app.button if item.label == "Pull").click()
    app.run()

    assert not app.exception
    head, pending = app.session_state["merge"]
    assert head == ("me/wf", "main", "old-sha")
    assert pending == {"config/config.yaml": b"samples: pulled.tsv\n"}
    assert any("Merge me/wf@main (old-sha)" in item.value for item in app.subheader)
    labels = [item.label for item in app.button]
    assert "Apply" in labels
    assert "Finish" in labels


def test_merge_done_pushes_the_pulled_sha(app, monkeypatch):
    monkeypatch.setattr(
        GitHub,
        "get_repo",
        lambda self, name: {
            "full_name": "me/wf",
            "default_branch": "main",
            "html_url": "https://github.com/me/wf",
        },
    )
    monkeypatch.setattr(
        GitHub,
        "iter_branches",
        lambda self, name: [Ref("branch", "main", "old-sha")],
    )
    app.session_state["gh-token"] = "token"
    app.session_state["gh-login"] = "me"
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()

    app.session_state["merge"] = (
        ("me/wf", "main", "old-sha"),
        {"config/config.yaml": b"samples: pulled.tsv\n"},
    )
    app.run()

    next(item for item in app.button if item.label == "Finish").click()
    app.run()
    assert app.session_state["merge"][1] == {}

    calls = {}

    def fake_push(*args, **kwargs):
        calls.update(kwargs)
        return "commit"

    monkeypatch.setattr("catalog_webapp.publish.full_push", fake_push)
    next(item for item in app.button if item.label == "Submit to GitHub").click()
    app.run()
    next(item for item in app.button if item.label == "Push").click()
    app.run()

    assert calls["expected_sha"] == "old-sha"
    assert app.session_state.get("merge") is None


def test_upload_zip_starts_a_merge(app):
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()

    deployment = app.session_state["deploy-result"]["explorer"].store
    incoming = {path: deployment.read(path) for path in deployment.paths()}
    incoming["config/config.yaml"] = b"samples: uploaded.tsv\n"

    uploader = next(
        item
        for item in app.file_uploader
        if item.key and item.key.endswith("-upload-files")
    )
    uploader.upload("uploaded.zip", _zip(incoming))
    app.run()

    upload = next(
        item
        for item in app.button
        if item.key and item.key.endswith("-upload-zip-merge")
    )
    upload.click()
    app.run()

    assert not app.exception, [str(error.value) for error in app.exception]
    head, pending = app.session_state["merge"]
    assert head == "uploaded.zip"
    assert pending == {"config/config.yaml": b"samples: uploaded.tsv\n"}
    assert "uploaded.zip" not in deployment.paths()
    assert any("Merge upload uploaded.zip" in item.value for item in app.subheader)


def test_upload_invalid_zip_reports_an_error(app):
    next(item for item in app.button if item.label == "Deploy").click()
    app.run()

    uploader = next(
        item
        for item in app.file_uploader
        if item.key and item.key.endswith("-upload-files")
    )
    uploader.upload("broken.zip", b"not a zip")
    app.run()

    upload = next(
        item
        for item in app.button
        if item.key and item.key.endswith("-upload-zip-merge")
    )
    upload.click()
    app.run()

    assert not app.exception, [str(error.value) for error in app.exception]
    assert [item.value for item in app.error] == [
        "The uploaded file is not a valid zip archive."
    ]
    assert "merge" not in app.session_state
