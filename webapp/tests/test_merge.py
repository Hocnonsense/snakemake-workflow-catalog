"""Incoming-file comparison: Pull, zip upload and per-file status."""

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_webapp.fs import DeploymentFS  # noqa: E402
from catalog_webapp.merge import (  # noqa: E402
    MergeError,
    diff_files,
    file_status,
    zip_files,
)


def _deployment(files=None, overrides=None):
    fs = DeploymentFS(dict(files or {}), None)  # type: ignore
    fs.overrides.update(overrides or {})
    return fs


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def test_zip_files_extracts_files_and_skips_metadata():
    data = _zip(
        {
            "workflow/Snakefile": b"rule all:\n",
            "__MACOSX/._Snakefile": b"junk",
            ".DS_Store": b"junk",
        }
    )

    assert zip_files(data) == {"workflow/Snakefile": b"rule all:\n"}


def test_zip_files_rejects_path_traversal():
    data = _zip({"../outside.txt": b"x", "ok.txt": b"y"})

    assert zip_files(data) == {"ok.txt": b"y"}


def test_zip_files_rejects_an_invalid_archive():
    with pytest.raises(MergeError, match="valid zip"):
        zip_files(b"not a zip")


def test_diff_files_only_keeps_differing_paths():
    fs = _deployment(
        {"a.txt": b"A", "gone.txt": b"G"},
        {"b.txt": b"B", "gone.txt": None},
    )
    pending = diff_files(
        fs,
        {"a.txt": b"A", "b.txt": b"B", "new.txt": b"N", "gone.txt": b"G"},
    )

    assert pending == {"gone.txt": b"G", "new.txt": b"N"}


def test_file_status_distinguishes_local_incoming_and_conflicts():
    assert file_status(b"base", b"base", b"new") == "incoming changed"
    assert file_status(b"base", b"new", b"base") == "local changed"
    assert file_status(b"base", b"local", b"incoming") == "conflict"
    assert file_status(None, None, b"new") == "added in incoming"
    assert file_status(None, b"new", None) == "added locally"
    assert file_status(b"base", None, b"base") == "deleted locally"
    assert file_status(b"base", b"base", None) == "deleted in incoming"
    assert file_status(b"base", b"base", b"base") == "same"
