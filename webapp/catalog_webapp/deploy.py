"""Fetch a workflow ref and turn it into a deployed repository file set.

This is a transport-agnostic reimplementation of ``snakedeploy deploy-workflow``
for the browser app.  It deliberately does not import snakedeploy: the browser
cannot run its git path, and importing it would pull in PyGithub and pandas.

The output must stay compatible with snakedeploy 0.11.x.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from snakelit.types import Ref
from .fs import DeploymentFS

if TYPE_CHECKING:
    from .github import GitHub


# The catalog documents both layouts, ``workflow/schemas/`` first.
_SCHEMA_PREFIXES = ("workflow/schemas/", "config/schemas/")

_SNAKEFILE_TEMPLATE = """{comment}
from snakemake.utils import min_version


min_version("6.10.0")


configfile: "{config}"


# declare {repo} as a module
module {name}:
    snakefile:
        {snakefile}
    config:
        config


# use all rules from {repo}
use rule * from {name}
"""


class DeployError(Exception):
    """The fetched tree cannot be deployed."""


def _set_snakefile(files: DeploymentFS, repo: str, ref: Ref, snakefile: str):
    snakefile = _SNAKEFILE_TEMPLATE.format(
        comment=_deployment_comment(repo, ref),
        config=files.config_file(),
        repo=repo,
        name=_module_name(repo),
        snakefile=_module_declaration(repo, ref, snakefile),
    )
    files.write("workflow/Snakefile", snakefile.encode("utf-8"))


def _module_name(owner_repo: str):
    """snakedeploy uses the repository name with dashes replaced by underscores."""
    return owner_repo.split("/")[-1].replace("-", "_")


def _source_snakefile(tree):
    """Return the upstream Snakefile path, preferring ``workflow/Snakefile``."""
    candidates = None
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path: str = entry["path"]
        if path == "workflow/Snakefile":
            return path
        if path == "Snakefile":
            candidates = path
    if candidates:
        return candidates
    raise DeployError("No Snakefile was found at root or in workflow directory.")


def _module_declaration(owner_repo: str, ref: Ref, snakefile: str):
    if ref.kind not in ("tag", "branch", "commit"):
        raise DeployError(f"Unsupported ref kind: {ref.kind!r}")
    value = ref.sha if ref.kind == "commit" else ref.name
    if not value:
        raise DeployError("A tag, branch or commit is required.")
    return f'github("{owner_repo}", path="{snakefile}", {ref.kind}="{value}")'


def _deployment_comment(owner_repo: str, ref: Ref):
    if ref.kind == "commit":
        return f"# deployed from {owner_repo} at commit {ref.sha or ref.name}"
    comment = f"# deployed from {owner_repo} at {ref.kind} {ref.name}"
    if ref.sha:
        comment += f" (commit {ref.sha})"
    return comment


def _wanted(tree):
    """Only the files snakedeploy reads: config, profiles, workflow, license."""
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path: str = entry["path"]
        if path.startswith(("config/", "profiles/")):
            yield path
        elif path in ("workflow/Snakefile", "Snakefile"):
            yield path
        elif "/" not in path:
            licen = path[:7]
            if licen.upper() in ("LICENCE", "LICENSE"):
                if licen in (licen.upper(), licen.capitalize(), licen.lower()):
                    yield path


def _schemas(tree):
    """The upstream JSON schemas; they feed the editor, not the deployment."""
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path: str = entry["path"]
        if path.startswith(_SCHEMA_PREFIXES):
            base, _, ext = path.rpartition(".schema.")
            if not base or base.endswith("/") or ext not in ("yaml", "yml", "json"):
                continue
            yield path


class Schemas:
    def __init__(self, schemas: Mapping[str, bytes]):
        self.schemas = schemas

    def find(self, item: str = "config"):
        """Return the schema registered for ``item``, following the catalog rules."""
        if item in self.schemas:
            return item
        for prefix in _SCHEMA_PREFIXES:
            for ext in ("yaml", "yml", "json"):
                path = f"{prefix}{item}.schema.{ext}"
                if path in self.schemas:
                    return path

    def get(self, path: str):
        """Return the schema for a file, matched by its stem."""
        return self.schemas[path]


def deploy(repo: str, ref: Ref, gh: "GitHub"):
    """Fetch ``ref`` and return the destination files of a deployment."""
    ref_name = ref.sha or ref.name
    tree = gh.get_tree(repo, ref_name)["tree"]
    # later wins, so prefer workflow/schemas/
    schemas = Schemas(gh.fetch_files(repo, ref_name, sorted(_schemas(tree))))
    files = DeploymentFS(gh.fetch_files(repo, ref_name, _wanted(tree)), schemas)
    _set_snakefile(files, repo, ref, _source_snakefile(tree))
    return files
