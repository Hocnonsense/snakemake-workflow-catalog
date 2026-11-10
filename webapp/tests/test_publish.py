"""Delivery: zip download and submitting a deployment to GitHub."""

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_webapp.github import GitHub
from catalog_webapp.deploy import DeploymentFS  # noqa: E402
from catalog_webapp.publish import (  # noqa: E402
    PublishError,
    full_push,
    repo_name,
    valid_branch,
    zip_bytes,
)
from snakelit.types import Ref  # noqa: E402

REF = Ref("tag", "v1.0", "abc1234def")
TARGET = {
    "full_name": "me/work-flow",
    "default_branch": "main",
    "html_url": "https://github.com/me/work-flow",
}


class FakeGitHub(GitHub):
    def __init__(self, refs=None):
        self.refs = dict(refs or {})
        self.calls = []
        self.token: str | None = "token"

    def get_ref_sha(self, owner_repo, branch):
        self.calls.append(("ref-get", owner_repo, branch))
        return self.refs.get(branch)

    def create_blob(self, owner_repo, content):
        self.calls.append(("blob", owner_repo, content))
        return f"blob-{content.decode()}"

    def create_tree(self, owner_repo, entries, base_tree=None):
        self.calls.append(("tree", owner_repo, entries, base_tree))
        return "tree"

    def create_commit(self, owner_repo, message, tree, parent=None):
        self.calls.append(("commit", owner_repo, message, tree, parent))
        return "commit"

    def create_ref(self, owner_repo, branch, sha):
        self.calls.append(("ref-create", owner_repo, branch, sha))

    def update_ref(self, owner_repo, branch, sha):
        self.calls.append(("ref-update", owner_repo, branch, sha))

    def commit_files(
        self, owner_repo, branch, files, message, *, default_branch="main"
    ):
        self.calls.append(
            ("commit-files", owner_repo, branch, files, message, default_branch)
        )
        return "commit"

    def set_default_branch(self, owner_repo, branch):
        self.calls.append(("default", owner_repo, branch))


def test_zip_contains_deployed_files_with_overrides():
    fs = DeploymentFS({"a.txt": b"A", "gone.txt": b"G"}, schemas=None)  # type: ignore
    fs.write("b/c.txt", b"C")
    fs.rm("gone.txt")

    with zipfile.ZipFile(io.BytesIO(zip_bytes(fs))) as archive:
        assert sorted(archive.namelist()) == ["a.txt", "b/c.txt"]
        assert archive.read("a.txt") == b"A"
        assert archive.read("b/c.txt") == b"C"


def test_publish_branch_updates_an_existing_branch():
    gh = FakeGitHub({"main": "old-sha"})

    url = full_push(
        gh, "main", "owner/work-flow", REF, {"a.txt": b"A"}, target_repo=TARGET
    )

    assert url == "https://github.com/me/work-flow"
    entries = next(call[2] for call in gh.calls if call[0] == "tree")
    assert entries == [
        {"path": "a.txt", "mode": "100644", "type": "blob", "sha": "blob-A"}
    ]
    commit = next(call for call in gh.calls if call[0] == "commit")
    assert commit[3] == "tree"
    assert commit[4] == "old-sha"
    assert ("ref-update", "me/work-flow", "main", "commit") in gh.calls


def test_publish_branch_makes_a_new_branch_the_default_of_an_empty_repository():
    gh = FakeGitHub()

    full_push(
        gh, "feature", "owner/work-flow", REF, {"a.txt": b"A"}, target_repo=TARGET
    )

    commit = next(call for call in gh.calls if call[0] == "commit-files")
    assert commit[1] == "me/work-flow"
    assert commit[2] == "feature"
    assert commit[3] == {"a.txt": b"A"}
    assert commit[5] == "main"
    assert ("default", "me/work-flow", "feature") in gh.calls


def test_repo_name_requires_a_user_or_an_owner():
    assert repo_name("wf", "me") == "me/wf"
    assert repo_name("org/wf", "me") == "org/wf"
    assert repo_name("wf") is None
    assert repo_name("bad name", "me") is None


def test_publish_branch_requires_a_token():
    gh = FakeGitHub()
    gh.token = None

    with pytest.raises(PublishError, match="token"):
        full_push(gh, "main", "owner/wf", REF, {"a": b"A"}, target_repo=TARGET)


def test_publish_branch_refuses_an_empty_deployment():
    with pytest.raises(PublishError, match="empty"):
        full_push(FakeGitHub(), "main", "owner/wf", REF, {}, target_repo=TARGET)


def test_valid_branch_follows_git_rules():
    assert valid_branch("main")
    assert valid_branch("feature/x")
    for bad in (
        "",
        "@",
        "bad branch",
        "a..b",
        "-x",
        "/x",
        "x/",
        "x.lock",
        "a@{b",
        "x//y",
    ):
        assert not valid_branch(bad)
