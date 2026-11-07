"""Deployment output contract tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_webapp.deploy import DeployError, deploy  # noqa: E402
from catalog_webapp.github import GitHub  # noqa: E402
from snakelit.types import Ref  # noqa: E402

BASE_FILES = {
    "workflow/Snakefile": b'rule all:\n    output:\n        touch("all")\n',
    "config/config.yaml": b"samples: samples.tsv\n",
    "config/README.md": b"# config\n",
}


class FakeGitHub(GitHub):
    """Return a fixed file set for a ref, like the real client would."""

    def __init__(self, files):
        self.files = files

    def get_tree(self, owner_repo, ref):
        return {"tree": [{"path": path, "type": "blob"} for path in self.files]}

    def fetch_files(self, owner_repo, ref, files):
        return {path: self.files[path] for path in files}


def _deploy(files, ref=None):
    return deploy("a/b", ref or Ref("tag", "v1", "sha1"), FakeGitHub(files))


def test_missing_config_creates_empty_file():
    deployment = _deploy({"workflow/Snakefile": b""})
    assert deployment.config_file() == "config/config.yaml"
    assert deployment.overrides["config/config.yaml"] == b""


def test_overrides_win():
    files = dict(BASE_FILES)
    deployment = _deploy(files)
    deployment.overrides["config/config.yaml"] = b"edited: true\n"

    assert deployment["config/config.yaml"] == b"edited: true\n"


def test_downloaded_and_overrides():
    files = dict(BASE_FILES)
    files["profiles/default/config.yaml"] = b"cores: 1\n"
    files["LICENSE"] = b"MIT\n"
    files["README.md"] = b"upstream readme\n"

    deployment = _deploy(files)

    assert deployment.get("config/config.yaml") == b"samples: samples.tsv\n"
    assert deployment.get("profiles/default/config.yaml") == b"cores: 1\n"
    assert deployment.get("LICENSE") == b"MIT\n"
    assert "workflow/Snakefile" in deployment.overrides
    assert "README.md" not in deployment.downloaded
    assert dict(deployment.items())["config/config.yaml"] == b"samples: samples.tsv\n"


def test_existing_yml_is_used():
    deployment = _deploy({"workflow/Snakefile": b"", "config/config.yml": b"x: 1\n"})

    assert deployment.config_file() == "config/config.yml"
    assert (
        'configfile: "config/config.yml"'
        in deployment.overrides["workflow/Snakefile"].decode()
    )


def test_empty_tree():
    with pytest.raises(DeployError):
        _deploy({})


def test_snakefile_records_ref_and_commit():
    deployment = _deploy(BASE_FILES)
    snakefile = deployment["workflow/Snakefile"].decode()

    assert 'github("a/b", path="workflow/Snakefile", tag="v1")' in snakefile
    assert "# deployed from a/b at tag v1 (commit sha1)" in snakefile
    assert "module b:" in snakefile


def test_schemas_are_kept_for_the_editor_only():
    files = dict(BASE_FILES)
    files["workflow/schemas/config.schema.yaml"] = b"type: object\n"
    files["workflow/schemas/samples.schema.json"] = b"{}\n"
    files["workflow/schemas/README.md"] = b"not a schema\n"

    deployment = _deploy(files)

    assert deployment.schemas == {
        "workflow/schemas/config.schema.yaml": b"type: object\n",
        "workflow/schemas/samples.schema.json": b"{}\n",
    }
    assert deployment.schema_path("config") == "workflow/schemas/config.schema.yaml"
    assert deployment.schema_path("samples") == "workflow/schemas/samples.schema.json"
    assert deployment.schema_path("units") is None
    assert "workflow/schemas/config.schema.yaml" not in dict(deployment.items())


def test_config_schemas_alternative_layout():
    files = dict(BASE_FILES)
    files["config/schemas/config.schema.yaml"] = b"type: object\n"
    files["workflow/schemas/config.schema.yaml"] = b"type: object\n"

    deployment = _deploy(files)

    assert deployment.schema_path("config") == "workflow/schemas/config.schema.yaml"
