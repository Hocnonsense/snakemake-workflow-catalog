from typing import TYPE_CHECKING, Mapping

import streamlit as st

from snakelit.file_view import preview_for, edit_for
from snakelit.types import FileStore, Stat

if TYPE_CHECKING:
    from .deploy import Schemas


class DeploymentFS(FileStore):
    def __init__(self, downloaded: Mapping[str, bytes], schemas: "Schemas"):
        self.downloaded = downloaded
        self.schemas = schemas
        self.overrides: dict[str, bytes | None] = {}

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

    # region FileStore interface
    def paths(self):
        for path, content in self.overrides.items():
            if content is not None:
                yield path
        for path in self.downloaded:
            if path not in self.overrides:
                yield path

    def stat(self, path):
        content = self.read(path)
        return None if content is None else Stat(len(content))

    def show(self, path, mode="Preview"):
        content = self.read(path)
        if content is None:
            if mode == "Preview":
                return None
            content = b""

        def render():
            if mode == "Edit":
                edited = edit_for(path, content, key=f"{path}-preview")
                if edited is not None:
                    if edited != content:
                        self.write(path, edited)
                        st.rerun()
                    return
            preview_for(path, content)

        return render

    def read(self, path):
        if path in self.overrides:
            return self.overrides[path]
        return self.downloaded.get(path)

    def write(self, path, data: bytes):
        self.overrides[path] = data

    def rm(self, path):
        if path in self.downloaded:
            self.overrides[path] = None  # mask
        else:
            self.overrides.pop(path, None)
