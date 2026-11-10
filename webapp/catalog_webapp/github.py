"""Minimal GitHub REST client for the browser app.

Uses ``urllib.request`` on purpose: stlite patches it through
``koenvo/pyodide-http``, so the same code runs in CPython and in the WASM
runtime.  Only ``api.github.com`` and ``raw.githubusercontent.com`` are used;
both send CORS headers, unlike the git smart-HTTP endpoints.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Iterable, Mapping

from snakelit.types import Ref

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = "snakemake-workflow-catalog-webapp"

_REFS_QUERY = """
query($owner: String!, $name: String!, $prefix: String!, $cursor: String, $order: RefOrder) {
  repository(owner: $owner, name: $name) {
    refs(refPrefix: $prefix, first: 100, after: $cursor, orderBy: $order) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        target {
          __typename
          ... on Commit { oid committedDate messageHeadline }
          ... on Tag {
            target { ... on Commit { oid committedDate messageHeadline } }
          }
        }
      }
    }
  }
}
"""


def _next_link(header: str | None):
    """Extract the ``rel="next"`` URL from a GitHub ``Link`` header."""
    if header:
        for part in header.split(","):
            url, _, relation = part.partition(";")
            if 'rel="next"' in relation:
                return url.strip().strip("<>")


def _parse_time(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _commit_fields(payload: Mapping):
    """Return the committer date and first message line of a commit payload."""
    commit = payload.get("commit") or {}
    committer = commit.get("committer") or commit.get("author") or {}
    message = str(commit.get("message") or "")
    subject = message.splitlines()[0] if message else None
    return _parse_time(committer.get("date")), subject


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    def __str__(self):
        return f"GitHub error {self.status}: {self.message}"


class GitHub:
    def __init__(self, token: str | None = None):
        self.token = token or None

    # -- low level ---------------------------------------------------------

    def _urlopen(
        self,
        method: str,
        url: str,
        payload: Mapping | None = None,
        accept="application/vnd.github+json",
        api: bool = True,
    ):
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", accept)
        if api:
            request.add_header("X-GitHub-Api-Version", "2022-11-28")
            request.add_header("User-Agent", USER_AGENT)
            if data is not None:
                request.add_header("Content-Type", "application/json")
            if self.token:
                request.add_header("Authorization", f"Bearer {self.token}")
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(body).get("message", body)
            except (json.JSONDecodeError, AttributeError):
                message = body
            raise GitHubError(error.code, message) from error
        except Exception as error:  # pyodide-http raises JsException on network errors
            raise GitHubError(0, str(error)) from error
        status = getattr(response, "status", None) or getattr(response, "code", None)
        if status and status >= 400:
            body = response.read().decode("utf-8", errors="replace")
            response.close()
            try:
                message = json.loads(body).get("message", body)
            except (json.JSONDecodeError, AttributeError):
                message = body
            raise GitHubError(status, message)
        return response

    def _request(
        self,
        method: str,
        url: str,
        payload: Mapping | None = None,
        accept="application/vnd.github+json",
        api: bool = True,
    ):
        with self._urlopen(method, url, payload, accept, api) as response:
            return response.read()

    def _request_page(self, url: str):
        """GET one page and return ``(items, next_url)`` from the Link header."""
        with self._urlopen("GET", url) as response:
            body = response.read()
            headers = getattr(response, "headers", None)
            link = headers.get("Link") if headers is not None else None
        data = json.loads(body) if body else []
        if not isinstance(data, list):
            message = data.get("message") if isinstance(data, dict) else str(data)
            raise GitHubError(0, message or "Unexpected GitHub response")
        return data, _next_link(link)

    def _iter_pages(self, url: str | None):
        while url:
            items, url = self._request_page(url)
            yield from items

    def _json(self, method: str, url: str, payload: Mapping | None = None) -> Any:
        body = self._request(method, url, payload)
        return json.loads(body) if body else {}

    # -- reads -------------------------------------------------------------

    def current_user(self) -> dict:
        return self._json("GET", f"{API}/user")

    def get_repo(self, owner_repo: str) -> dict:
        return self._json("GET", f"{API}/repos/{owner_repo}")

    def _iter_refs_graphql(self, owner_repo: str, prefix: str, kind: str, order=None):
        """Yield refs with commit time/subject in pages of 100 (needs a token)."""
        owner, name = owner_repo.split("/", 1)
        cursor = None
        while True:
            data = self._json(
                "POST",
                f"{API}/graphql",
                {
                    "query": _REFS_QUERY,
                    "variables": {
                        "owner": owner,
                        "name": name,
                        "prefix": prefix,
                        "cursor": cursor,
                        "order": order,
                    },
                },
            )
            if data.get("errors"):
                raise GitHubError(
                    0, "; ".join(str(item.get("message")) for item in data["errors"])
                )
            repository = (data.get("data") or {}).get("repository") or {}
            refs = repository.get("refs") or {}
            for node in refs.get("nodes") or []:
                target = node.get("target") or {}
                if target.get("__typename") == "Tag":
                    target = target.get("target") or {}
                oid = target.get("oid")
                if not oid:
                    continue
                yield Ref(
                    kind,
                    node["name"],
                    oid,
                    time=_parse_time(target.get("committedDate")),
                    subject=target.get("messageHeadline"),
                )
            page = refs.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")

    def iter_tags(self, owner_repo: str):
        """Yield tags; GraphQL (with time/subject) when a token is available."""
        if self.token:
            yield from self._iter_refs_graphql(
                owner_repo,
                "refs/tags/",
                "tag",
                {"field": "TAG_COMMIT_DATE", "direction": "DESC"},
            )
            return
        seen: set[str] = set()
        url = f"{API}/repos/{owner_repo}/tags?per_page=100"
        for tag in self._iter_pages(url):
            name = tag["name"]
            if name in seen:
                continue
            seen.add(name)
            yield Ref("tag", name, tag["commit"]["sha"])

    def iter_branches(self, owner_repo: str):
        """Yield branches; GraphQL (with time/subject) when a token is available."""
        if self.token:
            yield from self._iter_refs_graphql(owner_repo, "refs/heads/", "branch")
            return
        seen: set[str] = set()
        url = f"{API}/repos/{owner_repo}/branches?per_page=100"
        for branch in self._iter_pages(url):
            name = branch["name"]
            if name in seen:
                continue
            seen.add(name)
            yield Ref("branch", name, branch["commit"]["sha"])

    def iter_commits(self, owner_repo: str):
        """Yield every commit on a branch, following the ``Link`` header."""
        url = f"{API}/repos/{owner_repo}/commits?per_page=100"
        for commit in self._iter_pages(url):
            when, subject = _commit_fields(commit)
            yield Ref(
                "commit",
                commit["sha"],
                commit["sha"],
                time=when,
                subject=subject,
            )

    def repo_ref_cache(self, owner_repo: str):
        def load(kind: str):
            if kind == "tag":
                return self.iter_tags(owner_repo)
            if kind == "branch":
                return self.iter_branches(owner_repo)
            if kind == "commit":
                return self.iter_commits(owner_repo)
            raise ValueError(f"Unknown ref kind: {kind}")

        return load

    def get_tree(self, owner_repo: str, ref: str) -> dict:
        quoted = urllib.parse.quote(ref, safe="")
        data = self._json(
            "GET", f"{API}/repos/{owner_repo}/git/trees/{quoted}?recursive=1"
        )
        if data.get("truncated"):
            raise GitHubError(
                0,
                f"The file tree of {owner_repo}@{ref} is truncated by GitHub; "
                "this repository is too large for the browser deployment.",
            )
        return data

    def get_raw_file(self, owner_repo: str, ref: str, path: str):
        """Read one file. Public repositories go through the raw CDN."""
        url = (
            f"{RAW}/{owner_repo}/{urllib.parse.quote(ref, safe='')}/"
            f"{urllib.parse.quote(path, safe='/')}"
        )
        try:
            return self._request("GET", url, accept="*/*", api=False)
        except GitHubError as error:
            if self.token is None or error.status not in (403, 404):
                raise
        # Private repositories: fall back to the contents API with a raw body.
        url = (
            f"{API}/repos/{owner_repo}/contents/"
            f"{urllib.parse.quote(path, safe='/')}"
            f"?ref={urllib.parse.quote(ref, safe='')}"
        )
        return self._request("GET", url, accept="application/vnd.github.raw")

    def fetch_files(self, owner_repo: str, ref: str, files: Iterable[str]):
        return {path: self.get_raw_file(owner_repo, ref, path) for path in files}

    def pull_files(self, owner_repo: str, branch: str):
        """Return ``(head sha, every blob)`` for ``branch``."""
        sha = self.get_ref_sha(owner_repo, branch)
        if sha is None:
            raise GitHubError(404, f"Branch {branch!r} does not exist on {owner_repo}.")
        tree = self.get_tree(owner_repo, sha)
        if tree.get("truncated"):
            raise GitHubError(409, "The repository tree is truncated.")
        paths = [
            entry["path"]
            for entry in tree.get("tree", [])
            if entry.get("type") == "blob"
        ]
        return sha, self.fetch_files(owner_repo, sha, paths)

    # -- writes ------------------------------------------------------------

    def create_repo(
        self, name: str, *, private: bool = False, description: str = ""
    ) -> dict:
        return self._json(
            "POST",
            f"{API}/user/repos",
            {
                "name": name,
                "private": private,
                "description": description,
                "auto_init": False,
            },
        )

    def create_file(
        self,
        owner_repo: str,
        path: str,
        content: bytes,
        message: str,
        branch: str | None = None,
    ) -> dict:
        """Create one file through the contents API.

        Unlike the git database API, this endpoint also works on an empty
        repository and initializes it with a first commit.
        """
        quoted = urllib.parse.quote(path, safe="/")
        payload: dict = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
        }
        if branch:
            payload["branch"] = branch
        return self._json("PUT", f"{API}/repos/{owner_repo}/contents/{quoted}", payload)

    def commit_files(
        self,
        owner_repo: str,
        branch: str,
        files: Mapping[str, bytes],
        message: str,
    ) -> str:
        """Create the first commit of an empty repository and return its sha.

        The git database API answers 409 (``Git Repository is empty``) until
        the repository has a commit, so the first file is written through the
        contents API on ``branch`` to initialize it; the remaining files are
        added on top.
        """
        paths = sorted(files)
        initialized = self.create_file(
            owner_repo, paths[0], files[paths[0]], message, branch=branch
        )
        head = initialized["commit"]["sha"]
        if len(paths) > 1:
            entries = [
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": self.create_blob(owner_repo, files[path]),
                }
                for path in paths[1:]
            ]
            tree = self.create_tree(
                owner_repo, entries, initialized["commit"]["tree"]["sha"]
            )
            head = self.create_commit(owner_repo, message, tree, head)
            self.update_ref(owner_repo, branch, head)
        return head

    def get_ref_sha(self, owner_repo: str, branch: str):
        """The commit a branch points at, or ``None`` when it does not exist.

        An empty repository has no refs at all and GitHub answers 409
        (``Git Repository is empty``) instead of 404 for the git data API.
        """
        quoted = urllib.parse.quote(f"heads/{branch}", safe="/")
        try:
            data = self._json("GET", f"{API}/repos/{owner_repo}/git/ref/{quoted}")
        except GitHubError as error:
            if error.status in (404, 409):
                return None
            raise
        return data["object"]["sha"]

    def create_blob(self, owner_repo: str, content: bytes) -> str:
        data = self._json(
            "POST",
            f"{API}/repos/{owner_repo}/git/blobs",
            {
                "content": base64.b64encode(content).decode("ascii"),
                "encoding": "base64",
            },
        )
        return data["sha"]

    def create_tree(
        self, owner_repo: str, entries: list, base_tree: str | None = None
    ) -> str:
        payload: dict = {"tree": entries}
        if base_tree:
            payload["base_tree"] = base_tree
        data = self._json("POST", f"{API}/repos/{owner_repo}/git/trees", payload)
        return data["sha"]

    def create_commit(
        self, owner_repo: str, message: str, tree: str, parent: str | None = None
    ) -> str:
        data = self._json(
            "POST",
            f"{API}/repos/{owner_repo}/git/commits",
            {
                "message": message,
                "tree": tree,
                "parents": [parent] if parent else [],
            },
        )
        return data["sha"]

    def create_ref(self, owner_repo: str, branch: str, sha: str):
        self._json(
            "POST",
            f"{API}/repos/{owner_repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": sha},
        )

    def update_ref(self, owner_repo: str, branch: str, sha: str):
        quoted = urllib.parse.quote(f"heads/{branch}", safe="/")
        self._json(
            "PATCH",
            f"{API}/repos/{owner_repo}/git/refs/{quoted}",
            {"sha": sha},
        )

    def set_default_branch(self, owner_repo: str, branch: str):
        self._json("PATCH", f"{API}/repos/{owner_repo}", {"default_branch": branch})
