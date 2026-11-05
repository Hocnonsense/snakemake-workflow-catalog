"""Copy the stlite app into the Sphinx static tree.

``source/_static/*`` is gitignored, so the generated copy is never committed.
If ``build/html`` already exists, the copy there is refreshed too, so a local
static server picks up the change without a full ``sphinx-build``.

The list of Python files is written to ``files.json`` so the page does not have
to hard-code every module: adding a file under ``catalog_webapp/`` is enough.

Run by ``pixi run render-catalog``.
"""

from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "webapp"


def python_files():
    for path, dirs, files in SOURCE.walk():
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests", "tests_ui")]
        for file in files:
            if file.endswith(".py"):
                yield (path / file).relative_to(SOURCE).as_posix()


def copy_webapp(target: Path):
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(SOURCE / "index.html", target / "index.html")

    paths = sorted(python_files())
    for relative in paths:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / relative, destination)

    (target / "files.json").write_text(
        json.dumps(paths, indent=2) + "\n", encoding="utf-8"
    )


def main():
    copy_webapp(ROOT / "source" / "_static" / "webapp")
    build_root = ROOT / "build" / "html"
    if build_root.exists():
        # refresh the copy in build/html if it exists
        # for local development
        copy_webapp(build_root / "_static" / "webapp")


if __name__ == "__main__":
    main()
