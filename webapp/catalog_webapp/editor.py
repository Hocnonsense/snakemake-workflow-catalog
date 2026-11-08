"""Config editing glue for the stlite app.

``snakelit.editors.schema_dict`` edits one file; this module adds the
app-specific parts: locating the file, offering the upstream schemas, and
writing the result back into the deployment.
"""

from __future__ import annotations

import streamlit as st

from snakelit.utils.yaml import load

from .deploy import Schemas


def select_schema_edit(
    schemas: Schemas,
    schema_edit: Callable,
    language: str,
    default_schema: str | None = None,
    edit_file=None,
):
    def config_edit(path: str, data: bytes, key: str):
        errors: list[str] = []
        header = f"Editing `{path}`"
        schema = None
        if schemas:
            content = _choose_schema(schemas, path, default_schema, key)
            if content:
                schema, error = _parse_schema(content)
                if error is not None:
                    errors.append(error)
            if schema:
                header += " with schema"
            else:
                header += " without schema"
        updated = schema_edit(
            data.decode("utf-8"),
            errors,
            schema,
            header=header,
            key=key,
            edit_file=edit_file,
            format=language,
        )
        for message in errors:
            st.error(message)
        return data if updated is None else updated.encode("utf-8")

    return config_edit


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
