from typing import TYPE_CHECKING, Mapping

from snakelit.edit import edit_for
from snakelit.preview import preview_for
from snakelit.types import FileStore, Stat

if TYPE_CHECKING:
    from .deploy import Schemas


class DeploymentFS(FileStore):
    def __init__(self, downloaded: Mapping[str, bytes], schemas: "Schemas"):
        self.downloaded = downloaded
        self.schemas = schemas
        self.overrides: dict[str, bytes | None] = {}
        self.editors = {}

    def set_file_editors(self, edit_file=None):
        from .editor import select_schema_edit
        from snakelit.editor.config import schema_config
        from snakelit.editor.table import schema_table

        self.editors = {
            "yaml": select_schema_edit(
                self.schemas, schema_config, "yaml", edit_file=edit_file
            ),
            "json": select_schema_edit(
                self.schemas, schema_config, "json", edit_file=edit_file
            ),
            "csv": select_schema_edit(self.schemas, schema_table, "csv"),
            "tsv": select_schema_edit(self.schemas, schema_table, "tsv"),
            "parquet": select_schema_edit(self.schemas, schema_table, "parquet"),
            "xlsx": select_schema_edit(self.schemas, schema_table, "xlsx"),
        }
        self.editors["yml"] = self.editors["yaml"]

    def config_path(self):
        """Return where the workflow config lives, without creating it."""
        for files in (self.overrides, self.downloaded):
            for ext in "yaml", "yml":
                config = f"config/config.{ext}"
                if config in files:
                    return config
        return "config/config.yaml"

    def config_file(self):
        """Return the config path the generated Snakefile must point at."""
        config = self.config_path()
        if config not in self.overrides and config not in self.downloaded:
            self.overrides[config] = b""
        return config

    # region FileStore interface
    def paths(self, dir=""):
        for path, content in self.overrides.items():
            if path.startswith(dir) and content is not None:
                yield path
        for path in self.downloaded.keys() - self.overrides:
            if path.startswith(dir):
                yield path

    def stat(self, path):
        content = self.read(path)
        return None if content is None else Stat(len(content))

    def show(self, path, mode="Preview"):
        if path == self.config_path():
            # The app renders the config in a dedicated, always-visible editor.
            return None
        content = self.read(path)
        if content is None:
            if mode == "Preview":
                return None
            content = b""

        def render():
            if mode == "Edit":
                edit_for(path, self, key=f"{path}-preview", editors=self.editors)
            else:
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
