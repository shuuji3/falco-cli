import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

import cappa
import ruff_api
import tomlkit
from rich.progress import Progress, SpinnerColumn, TextColumn

ReturnType = TypeVar("ReturnType")

RICH_SUCCESS_MARKER = "[green]SUCCESS:"
RICH_ERROR_MARKER = "[red]ERROR:"
RICH_INFO_MARKER = "[blue]INFO:"


def clean_project_name(val: str) -> str:
    return val.strip().replace(" ", "_").replace("-", "_")


def get_username() -> str:
    try:
        return os.getlogin()
    except OSError:
        return os.getenv("USERNAME", "tobi")


def get_pyproject_file() -> Path:
    pyproject_path = Path("pyproject.toml")
    if pyproject_path.exists():
        return pyproject_path
    raise cappa.Exit(
        "Could not find a pyproject.toml file in the current directory.", code=1
    )


def get_project_name() -> str:
    pyproject = tomlkit.parse(get_pyproject_file().read_text())
    return pyproject["project"]["name"]


@contextmanager
def simple_progress(
    description: str, display_text="[progress.description]{task.description}"
):
    progress = Progress(SpinnerColumn(), TextColumn(display_text), transient=True)
    progress.add_task(description=description, total=None)
    try:
        yield progress.start()
    finally:
        progress.stop()


exec_path = Path(sys.executable).parent


def run_python_formatters(filepath: str | Path):
    def format_code(fpath: Path):
        code = fpath.read_text()
        code = ruff_api.format_string(fpath.name, code)
        code = ruff_api.isort_string(fpath.name, code)
        fpath.write_text(code)

    if filepath.is_dir():
        for f in filepath.rglob("*.py"):
            file_path = str(f)
            if file_path.startswith(".") or "venv" in file_path:
                continue
            format_code(f)
    else:
        format_code(filepath)


def run_html_formatters(filepath: str | Path):
    """
    The configuration I was using in the starter template directly
    https://github.com/falcopackages/starter-template/commit/32c026d8150aba73bed545d063b97b54e8bc1829
    """

    djlint = [
        exec_path / "djlint",
        "--custom-blocks",
        "partialdef",
        "--blank-line-after-tag",
        "endblock,endpartialdef,extends,load",
        "--blank-line-before-tag",
        "block,partialdef",
        "--close-void-tags",
        "--format-css",
        "--indent-css",
        "2",
        "--format-js",
        "--indent-js",
        "2",
        "--ignore",
        "H006,H030,H031,H021",
        "--include",
        "H017,H035",
        "--indent",
        "2",
        "--max-line-length",
        "120",
        "--profile",
        "django",
        filepath,
        "--reformat",
    ]
    subprocess.run(
        djlint, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
