"""Delivery: zip download and submitting a deployment to GitHub."""

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_webapp.github import GitHub, GitHubError
from catalog_webapp.deploy import DeploymentFS  # noqa: E402
from catalog_webapp.publish import (  # noqa: E402
    PublishError,
    full_push,
    push_deployment,
    repo_name,
    valid_branch,
)
from snakelit.types import Ref  # noqa: E402
from snakelit.utils.zip import zipped  # noqa: E402

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

    def commit_files(self, owner_repo, branch, files, message):
        self.calls.append(("commit-files", owner_repo, branch, files, message))
        return "commit"

    def set_default_branch(self, owner_repo, branch):
        self.calls.append(("default", owner_repo, branch))


def test_zip_contains_deployed_files_with_overrides():
    fs = DeploymentFS({"a.txt": b"A", "gone.txt": b"G"}, schemas=None)  # type: ignore
    fs.write("b/c.txt", b"C")
    fs.rm("gone.txt")

    with zipfile.ZipFile(io.BytesIO(zipped(fs))) as archive:
        assert sorted(archive.namelist()) == ["a.txt", "b/c.txt"]
        assert archive.read("a.txt") == b"A"
        assert archive.read("b/c.txt") == b"C"


def test_publish_branch_updates_an_existing_branch():
    gh = FakeGitHub({"main": "old-sha"})

    sha = full_push(gh, "main", "message", {"a.txt": b"A"}, target_repo=TARGET)

    assert sha == "commit"
    entries = next(call[2] for call in gh.calls if call[0] == "tree")
    assert entries == [
        {"path": "a.txt", "mode": "100644", "type": "blob", "sha": "blob-A"}
    ]
    commit = next(call for call in gh.calls if call[0] == "commit")
    assert commit[3] == "tree"
    assert commit[4] == "old-sha"
    assert ("ref-update", "me/work-flow", "main", "commit") in gh.calls


def test_publish_branch_checks_the_sha_obtained_by_pull():
    gh = FakeGitHub({"main": "old-sha"})

    full_push(
        gh,
        "main",
        "message",
        {"a.txt": b"A"},
        target_repo=TARGET,
        expected_sha="old-sha",
    )
    assert ("ref-update", "me/work-flow", "main", "commit") in gh.calls

    with pytest.raises(PublishError, match="branch moved"):
        full_push(
            gh,
            "main",
            "message",
            {"a.txt": b"A"},
            target_repo=TARGET,
            expected_sha="other-sha",
        )


def test_publish_branch_makes_a_new_branch_a_root_commit():
    gh = FakeGitHub()

    full_push(gh, "feature", "message", {"a.txt": b"A"}, target_repo=TARGET)

    commit = next(call for call in gh.calls if call[0] == "commit")
    assert commit[4] is None
    assert ("ref-create", "me/work-flow", "feature", "commit") in gh.calls
    assert not [call for call in gh.calls if call[0] == "default"]


class EmptyFakeGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.empty = True

    def create_blob(self, owner_repo, content):
        if self.empty:
            raise GitHubError(409, "Git Repository is empty.")
        return super().create_blob(owner_repo, content)

    def commit_files(self, owner_repo, branch, files, message):
        self.empty = False
        return super().commit_files(owner_repo, branch, files, message)


def test_publish_branch_initializes_an_empty_repository_as_root():
    gh = EmptyFakeGitHub()

    full_push(gh, "feature", "message", {"a.txt": b"A"}, target_repo=TARGET)

    commit_files = next(call for call in gh.calls if call[0] == "commit-files")
    assert commit_files[2] == "main"
    commit = next(call for call in gh.calls if call[0] == "commit")
    assert commit[4] is None
    assert ("ref-create", "me/work-flow", "feature", "commit") in gh.calls
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
        full_push(gh, "main", "message", {"a": b"A"}, target_repo=TARGET)


def test_publish_branch_refuses_an_empty_deployment():
    with pytest.raises(PublishError, match="empty"):
        full_push(FakeGitHub(), "main", "message", {}, target_repo=TARGET)


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


def test_push_deployment_collects_files_and_pushes():
    fs = DeploymentFS({"a.txt": b"A"}, schemas=None)  # type: ignore
    gh = FakeGitHub({"main": "old-sha"})

    result = push_deployment(
        fs,
        gh,
        name="me/work-flow",
        target_repo=TARGET,
        branch="main",
        message="message",
        expected_sha="old-sha",
    )

    assert result == "commit"
    assert ("ref-update", "me/work-flow", "main", "commit") in gh.calls
