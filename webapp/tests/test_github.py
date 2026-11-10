"""GitHub client tests (no network)."""

import sys

import pytest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_webapp.github import GitHub, GitHubError, _next_link  # noqa: E402
from snakelit.types import Ref  # noqa: E402


class RecordingGitHub(GitHub):
    """GitHub client whose JSON calls are recorded instead of sent."""

    def __init__(self):
        super().__init__("token")
        self.calls = []

    def _json(self, method, url, payload=None):
        self.calls.append((method, url, payload))
        if "/contents/" in url:
            return {"commit": {"sha": "init-sha", "tree": {"sha": "init-tree"}}}
        if url.endswith("/git/blobs"):
            return {"sha": "blob-sha"}
        if url.endswith("/git/trees"):
            return {"sha": "tree-sha"}
        if url.endswith("/git/commits"):
            return {"sha": "commit-sha"}
        if url.endswith("/git/refs") and payload:
            return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
        if "/git/refs/heads/" in url and payload:
            return {"object": {"sha": payload["sha"]}}
        if url.endswith("/user/repos"):
            return {"full_name": "me/target", "default_branch": "main"}
        raise AssertionError(f"unexpected URL: {url}")


def test_commit_files_initializes_an_empty_repository_through_the_contents_api():
    gh = RecordingGitHub()
    sha = gh.commit_files("me/target", "main", {"a.txt": b"hi"}, "msg")

    assert sha == "init-sha"
    assert gh.calls == [
        (
            "PUT",
            "https://api.github.com/repos/me/target/contents/a.txt",
            {"message": "msg", "content": "aGk=", "branch": "main"},
        )
    ]


def test_commit_files_adds_remaining_files_on_top_of_the_initial_commit():
    gh = RecordingGitHub()
    sha = gh.commit_files("me/target", "main", {"a.txt": b"hi", "b.txt": b"bye"}, "msg")

    assert sha == "commit-sha"
    assert gh.calls[0][0] == "PUT"
    assert gh.calls[0][1].endswith("/contents/a.txt")

    blob_payload = gh.calls[1][2]
    assert blob_payload["encoding"] == "base64"
    assert blob_payload["content"] == "Ynll"
    assert gh.calls[1][1].endswith("/git/blobs")

    tree_payload = gh.calls[2][2]
    assert tree_payload["base_tree"] == "init-tree"
    assert tree_payload["tree"] == [
        {"path": "b.txt", "mode": "100644", "type": "blob", "sha": "blob-sha"}
    ]

    commit_payload = gh.calls[3][2]
    assert commit_payload["parents"] == ["init-sha"]
    assert commit_payload["tree"] == "tree-sha"

    ref = gh.calls[4]
    assert ref[0] == "PATCH"
    assert ref[1].endswith("/git/refs/heads/main")
    assert ref[2] == {"sha": "commit-sha"}


def test_commit_files_initializes_on_the_requested_branch():
    gh = RecordingGitHub()
    sha = gh.commit_files("me/target", "feature", {"a.txt": b"hi"}, "msg")

    assert sha == "init-sha"
    assert gh.calls == [
        (
            "PUT",
            "https://api.github.com/repos/me/target/contents/a.txt",
            {"message": "msg", "content": "aGk=", "branch": "feature"},
        )
    ]


def test_create_repo_payload():
    gh = RecordingGitHub()
    created = gh.create_repo("target", private=True, description="d")

    assert created["full_name"] == "me/target"
    payload = gh.calls[0][2]
    assert payload["name"] == "target"
    assert payload["private"] is True
    assert payload["auto_init"] is False


def test_fetch_files_reads_given_paths():
    gh = GitHub()
    fetched = []

    def fake_raw(owner_repo, ref, path):
        fetched.append(path)
        return path.encode()

    gh.get_raw_file = fake_raw
    files = gh.fetch_files("a/b", "v1", ["config/config.yaml"])

    assert files == {"config/config.yaml": b"config/config.yaml"}
    assert fetched == ["config/config.yaml"]


def test_next_link_extracts_next():
    header = (
        '<https://api.github.com/x?page=2>; rel="next", '
        '<https://api.github.com/x?page=9>; rel="last"'
    )
    assert _next_link(header) == "https://api.github.com/x?page=2"


def test_next_link_without_next():
    assert _next_link(None) is None
    assert _next_link('<https://api.github.com/x?page=1>; rel="first"') is None


class FakeIterPageGithub(GitHub):
    pages = []

    def _iter_pages(self, url):
        yield from self.pages


def test_iter_commits_parses_committer_date_and_message():
    gh = FakeIterPageGithub()
    gh.pages = [
        {
            "sha": "abc123",
            "commit": {
                "message": "Release 1.0\n\nDetails",
                "committer": {"date": "2026-03-04T05:06:07Z"},
            },
        }
    ]

    refs = list(gh.iter_commits("o/r"))

    assert len(refs) == 1
    assert refs[0].kind == "commit"
    assert refs[0].name == "abc123"
    assert refs[0].time == datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    assert refs[0].subject == "Release 1.0"


def test_repo_ref_cache_does_not_fetch_commits_per_ref():
    class FakeGitHub(GitHub):
        def __init__(self):
            super().__init__("token")
            self.fetched = []

        def iter_tags(self, owner_repo):
            yield Ref("tag", "v1", "sha1")

        def iter_branches(self, owner_repo):
            yield Ref("branch", "main", "sha1")
            yield Ref("branch", "dev", "sha2")

        def _json(self, method, url, payload=None):
            self.fetched.append(url)
            raise AssertionError("repo_ref_cache must not fetch commits")

    gh = FakeGitHub()
    load = gh.repo_ref_cache("o/r")

    assert [ref.name for ref in load("tag")] == ["v1"]
    assert [ref.name for ref in load("branch")] == ["main", "dev"]
    assert gh.fetched == []


def test_graphql_tags_include_time_and_paginate():
    gh = GitHub("token")
    pages = [
        {
            "data": {
                "repository": {
                    "refs": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                        "nodes": [
                            {
                                "name": "v1",
                                "target": {
                                    "__typename": "Commit",
                                    "oid": "a",
                                    "committedDate": "2026-01-02T03:04:05Z",
                                    "messageHeadline": "first",
                                },
                            },
                            {
                                "name": "v2",
                                "target": {
                                    "__typename": "Tag",
                                    "target": {
                                        "__typename": "Commit",
                                        "oid": "b",
                                        "committedDate": "2026-01-03T00:00:00Z",
                                        "messageHeadline": "second",
                                    },
                                },
                            },
                        ],
                    }
                }
            }
        },
        {
            "data": {
                "repository": {
                    "refs": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "name": "v3",
                                "target": {
                                    "__typename": "Commit",
                                    "oid": "c",
                                    "committedDate": "2026-01-04T00:00:00Z",
                                    "messageHeadline": "third",
                                },
                            }
                        ],
                    }
                }
            }
        },
    ]
    calls = []

    def fake_json(method, url, payload=None):
        calls.append(payload)
        return pages.pop(0)

    gh._json = fake_json
    refs = list(gh.iter_tags("o/r"))

    assert [ref.name for ref in refs] == ["v1", "v2", "v3"]
    assert [ref.sha for ref in refs] == ["a", "b", "c"]
    assert refs[0].subject == "first"
    assert refs[1].time and refs[1].time.year == 2026
    assert calls[0]["variables"]["cursor"] is None
    assert calls[0]["variables"]["order"] == {
        "field": "TAG_COMMIT_DATE",
        "direction": "DESC",
    }
    assert calls[1]["variables"]["cursor"] == "c1"


def test_raw_file_uses_a_simple_request():
    """raw.githubusercontent.com rejects preflight, so no GitHub API headers."""
    gh = GitHub("token")
    calls = []

    def fake_request(method, url, payload=None, accept=None, api=True):
        calls.append((method, url, api))
        return b"data"

    gh._request = fake_request
    assert gh.get_raw_file("o/r", "sha1", "LICENSE") == b"data"
    assert calls == [
        (
            "GET",
            "https://raw.githubusercontent.com/o/r/sha1/LICENSE",
            False,
        )
    ]


def test_network_errors_are_wrapped(monkeypatch):
    gh = GitHub()

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("catalog_webapp.github.urllib.request.urlopen", boom)

    with pytest.raises(GitHubError):
        gh.current_user()


class BranchGitHub(GitHub):
    def __init__(self, *, missing=False, truncated=False):
        super().__init__("token")
        self.missing = missing
        self.truncated = truncated

    def get_ref_sha(self, owner_repo, branch):
        return None if self.missing else "sha1"

    def get_tree(self, owner_repo, ref):
        if self.truncated:
            return {"truncated": True, "tree": []}
        return {"tree": [{"path": "a.txt", "type": "blob"}]}

    def fetch_files(self, owner_repo, ref, files):
        return {path: b"data" for path in files}


def test_pull_files_returns_the_branch_head_and_blobs():
    assert BranchGitHub().pull_files("me/wf", "main") == (
        "sha1",
        {"a.txt": b"data"},
    )


def test_pull_files_rejects_a_missing_branch_and_truncated_tree():
    with pytest.raises(GitHubError, match="does not exist"):
        BranchGitHub(missing=True).pull_files("me/wf", "main")

    with pytest.raises(GitHubError, match="truncated"):
        BranchGitHub(truncated=True).pull_files("me/wf", "main")
