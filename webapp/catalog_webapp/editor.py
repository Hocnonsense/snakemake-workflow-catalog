"""Config editing glue for the stlite app.

``snakelit.editors.schema_dict`` edits one file; this module adds the
app-specific parts: locating the file, offering the upstream schemas, and
writing the result back into the deployment.
"""

from __future__ import annotations

import streamlit as st

from snakelit.editors import schema_dict as _schema_dict

from snakelit.utils.yaml import load

from .deploy import Schemas
from .fs import DeploymentFS


def schema_dict(
    store: DeploymentFS,
    file: str,
    default_schema: str | None = None,
    key: str = "config-schema",
    *,
    edit_file=None,
):
    """Edit ``file``, write the result into ``deployment``, return errors.

    ``snakelit`` decides how the content is edited; a file that does not parse
    is still opened as text so it can be repaired.  Nothing is written when
    the text is unchanged or invalid.
    """
    text = (store.read(file) or b"").decode("utf-8")
    errors: list[str] = []

    header = f"Editing `{file}`"
    schema = None
    if store.schemas:
        content = _choose_schema(store.schemas, file, default_schema, key)
        if content:
            schema, error = _parse_schema(content)
            if error is not None:
                errors.append(error)
        if schema:
            header += f" with schema"
        else:
            header += f" without schema"

    updated = _schema_dict(
        text, errors, schema, header=header, key=key, edit_file=edit_file
    )
    if updated is not None:
        store.write(file, updated.encode("utf-8"))
        # the file list above was rendered before the edit; rerun shows it
        st.rerun()
    return errors


def _parse_schema(content: bytes):
    """Parse a schema file, returning ``(schema, error)``."""
    errors: list[str] = []
    schema = load(content.decode("utf-8"), errors)
    if errors:
        return None, f"Invalid schema: {errors[0]}"
    if schema is None:
        return {}, None
    if not isinstance(schema, dict):
        return None, "The schema must be a YAML mapping."
    return schema, None


def _choose_schema(
    schemas: Schemas,
    file: str,
    default_schema: str | None,
    key: str,
):
    """Render the read-only schema selector; return the raw schema content.

    ``default_schema`` is the schema path that should be selected by default,
    or ``None`` to try to pick the schema by file name.
    """
    paths = sorted(schemas.schemas)
    if not paths:  # noqa
        return

    if default_schema is None:
        item = file.rsplit("/", 1)[-1].split(".", 1)[0]
        default_schema = schemas.find(item)
    index = 1 + paths.index(default_schema) if default_schema in paths else 0

    choice = st.selectbox(
        "Schema",
        ["(none)", *paths],
        index=index,
        key=f"{key}-schema",
        help=(
            "Read-only upstream schema. Pick another file when the workflow "
            "keeps its schema elsewhere, or none for raw YAML."
        ),
    )
    if choice == "(none)":
        return

    return schemas.get(choice)
