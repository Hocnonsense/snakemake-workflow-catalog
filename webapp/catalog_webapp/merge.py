"""Compare a pulled or uploaded file set with the current deployment."""

from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath
from typing import Mapping

import streamlit as st

from .fs import DeploymentFS

IGNORED_PATTERNS = [".DS_Store", "__MACOSX", "__pycache__"]


class MergeError(Exception):
    """The incoming files cannot be read or compared."""


def zip_files(data: bytes):
    """Read a zip archive into ``path -> bytes``, rejecting unsafe paths."""
    files: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                path = _zip_path(info.filename)
                if path:
                    files[path] = archive.read(info)
    except zipfile.BadZipFile as error:
        raise MergeError("The uploaded file is not a valid zip archive.") from error
    if not files:
        raise MergeError("The zip archive contains no files.")
    return files


def _zip_path(name: str):
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return
    parts = [part for part in path.parts if part not in ("", ".")]
    for pattern in IGNORED_PATTERNS:
        if any(part == pattern for part in parts):
            return
    return "/".join(parts)


def diff_files(
    fs: DeploymentFS, incoming: Mapping[str, bytes]
) -> dict[str, bytes | None]:
    """Map every differing path to its incoming bytes (``None`` = deleted)."""
    return {
        path: incoming.get(path)
        for path in sorted(set(fs.paths()) | set(incoming))
        if fs.read(path) != incoming.get(path)
    }


def source_label(head):
    """Label a repo ``(repo, branch, sha)`` or an upload name."""
    if isinstance(head, tuple) and len(head) == 3:
        repo, branch, sha = head
        return f"{repo}@{branch}" + (f" ({sha[:7]})" if sha else "")
    return f"upload {head}" if head else "upload"


def file_status(base: bytes | None, local: bytes | None, incoming: bytes | None):
    """Describe how ``local`` and ``incoming`` differ from their common ``base``."""
    if local == incoming:
        return "same"
    if local == base:
        if incoming is None:
            return "deleted in incoming"
        if base is None:
            return "added in incoming"
        return "incoming changed"
    if incoming == base:
        if local is None:
            return "deleted locally"
        if base is None:
            return "added locally"
        return "local changed"
    if local is None:
        return "deleted locally, incoming changed"
    if incoming is None:
        return "deleted in incoming, local changed"
    return "conflict"


def render_merge(
    fs: DeploymentFS,
    head,
    files: dict[str, bytes | None],
    *,
    key: str = "merge",
):
    """Render the per-file incoming/local comparison.

    ``files`` is the dict returned by :func:`diff_files`; resolving a row pops
    its key.  An empty dict means the merge is complete.
    """
    if not files:
        return

    title, cancel = st.columns([4, 1], vertical_alignment="bottom")
    title.subheader(f"Merge {source_label(head)}")
    if cancel.button("Cancel comparison", key=f"{key}-discard", width="stretch"):
        st.session_state.pop("merge", None)
        st.rerun()
    for path in sorted(files):
        empty = st.empty()
        if render_file(fs, path, files[path], empty.container(), key=key):
            files.pop(path, None)
            empty.empty()
            if not files:
                st.rerun()


def render_file(
    fs: DeploymentFS, path: str, remote: bytes | None, container, key="merge"
):
    local = fs.read(path)
    status = file_status(fs.downloaded.get(path), local, remote)
    apply_col, name_col, delete_col, finish_col = container.columns(
        [1, 4, 1, 1], vertical_alignment="center"
    )
    if apply_col.button(
        "Apply",
        key=f"{key}-apply-{path}",
        width="stretch",
        help="Accept incoming (theirs)",
    ):
        if remote is None:
            fs.rm(path)
        else:
            fs.write(path, remote)
        return True
    name_col.markdown(f"**`{path}`** · {status}")
    if local is not None and delete_col.button(
        "Delete",
        key=f"{key}-delete-{path}",
        width="stretch",
        help="Delete the local file and finish",
    ):
        fs.rm(path)
        return True
    if finish_col.button(
        "Finish",
        key=f"{key}-finish-{path}",
        width="stretch",
        help="Accept current (ours)",
    ):
        return True

    left, right = container.columns(2)
    widget_key = f"{key}-local-{path}"

    def save():
        value = st.session_state.get(widget_key)
        if value is not None:
            fs.write(path, value.encode("utf-8"))

    with left:
        _show_bytes(remote, path, widget_key, None)
    with right:
        _show_bytes(local, path, widget_key, save)


def _show_bytes(data: bytes | None, path: str, key: str, save, height=420):
    import streamlit as st

    from snakelit.preview import (
        IMAGE_SUFFIXES,
        BINARY_SUFFIXES,
        suffix,
        image_view,
        binary_view,
    )

    if data is None:
        st.caption("(not present)")
        return
    ext = suffix(path)
    if ext in IMAGE_SUFFIXES:
        return image_view(data)
    if ext in BINARY_SUFFIXES:
        return binary_view(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return binary_view(data)

    label = "Incoming" if save is None else "Local"
    st.text_area(
        label,
        value=text,
        key=f"{key}-preview" if save is None else key,
        height=height,
        on_change=save,
        disabled=save is None,
        label_visibility="collapsed",
    )
