"""Fetch a workflow ref and turn it into a deployed repository file set.

This is a transport-agnostic reimplementation of ``snakedeploy deploy-workflow``
for the browser app.  It deliberately does not import snakedeploy: the browser
cannot run its git path, and importing it would pull in PyGithub and pandas.

The output must stay compatible with snakedeploy 0.11.x, see
``BROWSER_DEPLOY_PLAN.md`` section 4.5 in the SRPtn repository.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

from snakelit.types import Ref

if TYPE_CHECKING:
    from .github import GitHub

SNAKEDEPLOY_COMPAT = "0.11.0"

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


class Deployment:
    """The downloaded upstream files and the files of the deployed repo."""

    def __init__(self, downloaded: Mapping[str, bytes]):
        if not downloaded:
            raise DeployError("The source tree is empty.")
        self.downloaded = downloaded
        self.overrides: dict[str, bytes] = {}

    def config_file(self):
        """Return the config path the generated Snakefile must point at."""
        for files in (self.overrides, self.downloaded):
            for ext in "yaml", "yml":
                config = f"config/config.{ext}"
                if config in files:
                    return config
        config = "config/config.yaml"
        self.overrides[config] = b""
        return config

    def set_snakefile(self, repo: str, ref: Ref, snakefile: str):
        snakefile = _SNAKEFILE_TEMPLATE.format(
            comment=_deployment_comment(repo, ref),
            config=self.config_file(),
            repo=repo,
            name=_module_name(repo),
            snakefile=_module_declaration(repo, ref, snakefile),
        )
        self.overrides["workflow/Snakefile"] = snakefile.encode("utf-8")

    def items(self):
        yield from self.overrides.items()
        for path, content in self.downloaded.items():
            if path not in self.overrides:
                yield path, content

    def get(self, path: str):
        if path in self.overrides:
            return self.overrides[path]
        return self.downloaded.get(path)

    def __getitem__(self, key):
        item = self.get(key)
        if item is None:
            raise KeyError(key)
        return item

    def __setitem__(self, key, value):
        self.overrides[key] = value

    def __contains__(self, key):
        return key in self.overrides or key in self.downloaded


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
        if path.startswith(("config/", "profiles/", "workflow/")):
            yield path
        elif "/" not in path:
            licen = path[:7]
            if licen.upper() in ("LICENCE", "LICENSE"):
                if licen in (licen.upper(), licen.capitalize(), licen.lower()):
                    yield path


def deploy(repo: str, ref: Ref, gh: "GitHub"):
    """Fetch ``ref`` and return the destination files of a deployment."""
    ref_name = ref.sha or ref.name
    tree = gh.get_tree(repo, ref_name)["tree"]
    files = Deployment(gh.fetch_files(repo, ref_name, _wanted(tree)))
    files.set_snakefile(repo, ref, _source_snakefile(tree))
    return files
