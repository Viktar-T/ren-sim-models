"""Repository layout: three packages in one uv workspace. Spec 0009."""

import re
import subprocess
import sys
import tomllib
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = {"kiozesim": "kiozesim", "kiozesim-tool": "kiozesim_tool", "kiozesim-ui": "kiozesim_ui"}
APPS = ("kiozesim-tool", "kiozesim-ui")
SKIP_DIRS = {".git", ".venv", ".ruff_cache", ".mypy_cache", ".pytest_cache", "__pycache__"}
OLD_IMPORT = "kioze" + "_sim"  # split so this file does not match its own search
OLD_NAME = "kioze" + "-sim"


def toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text())


def repo_files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
    ]


@pytest.mark.spec("REPO-001")
def test_three_package_folders() -> None:
    folders = {p.parent.name for p in ROOT.glob("*/pyproject.toml")}
    assert folders == set(PACKAGES)


@pytest.mark.spec("REPO-002")
def test_root_is_virtual_workspace() -> None:
    root = toml(ROOT / "pyproject.toml")
    assert "project" not in root
    assert set(root["tool"]["uv"]["workspace"]["members"]) == set(PACKAGES)


@pytest.mark.spec("REPO-003")
@pytest.mark.parametrize(("folder", "module"), PACKAGES.items())
def test_names_and_src_layout(folder: str, module: str) -> None:
    assert toml(ROOT / folder / "pyproject.toml")["project"]["name"] == folder
    src = ROOT / folder / "src" / module
    assert (src / "__init__.py").is_file()
    assert Path(import_module(module).__file__ or "").parent == src


@pytest.mark.spec("REPO-004")
def test_library_moved() -> None:
    assert not (ROOT / "src").exists()
    assert (ROOT / "kiozesim" / "src" / "kiozesim" / "plants" / "base.py").is_file()


@pytest.mark.spec("REPO-005")
def test_library_dependencies() -> None:
    project = toml(ROOT / "kiozesim" / "pyproject.toml")["project"]
    assert set(project["optional-dependencies"]) == {"pv", "wind", "system", "fmu"}
    deps = project["dependencies"] + sum(project["optional-dependencies"].values(), [])
    assert not [d for d in deps if d.startswith(APPS)]


@pytest.mark.spec("REPO-006")
@pytest.mark.parametrize("app", APPS)
def test_apps_use_workspace_library(app: str) -> None:
    cfg = toml(ROOT / app / "pyproject.toml")
    assert "kiozesim" in cfg["project"]["dependencies"]
    assert cfg["tool"]["uv"]["sources"]["kiozesim"] == {"workspace": True}


@pytest.mark.spec("REPO-007")
@pytest.mark.parametrize("app", APPS)
def test_app_skeletons(app: str) -> None:
    module = PACKAGES[app]
    src = ROOT / app / "src" / module
    assert {p.name for p in src.iterdir() if p.name != "__pycache__"} == {"__init__.py"}
    import_module(module)


@pytest.mark.spec("REPO-008")
def test_root_tools_cover_all_packages() -> None:
    tool = toml(ROOT / "pyproject.toml")["tool"]
    for folder in PACKAGES:
        assert f"{folder}/tests" in tool["pytest"]["ini_options"]["testpaths"]
        assert f"{folder}/src" in tool["mypy"]["files"]
        assert f"{folder}/src" in tool["ruff"]["src"]


@pytest.mark.spec("REPO-009")
def test_specs_and_scripts_at_root() -> None:
    assert (ROOT / "specs" / "constitution.md").is_file()
    assert (ROOT / "scripts" / "spec_check.py").is_file()
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "spec_check.py")], capture_output=True, text=True
    )
    assert run.returncode == 0, run.stdout + run.stderr
    # this very file is found, so the scan reaches into package test folders
    assert "REPO-009" in (ROOT / "kiozesim" / "tests" / "test_layout.py").read_text()
    assert int(re.search(r"(\d+) covered", run.stdout).group(1)) > 0  # type: ignore[union-attr]


@pytest.mark.spec("REPO-010")
def test_tests_per_package() -> None:
    assert not (ROOT / "tests").exists()
    assert (ROOT / "kiozesim" / "tests" / "golden").is_dir()
    assert (ROOT / "kiozesim" / "tests" / "__init__.py").is_file()
    for app in APPS:
        assert not (ROOT / app / "tests" / "__init__.py").exists()


@pytest.mark.spec("REPO-011")
def test_examples_in_library() -> None:
    assert not (ROOT / "examples").exists()
    assert (ROOT / "kiozesim" / "examples" / "pv.py").is_file()


@pytest.mark.spec("REPO-012")
def test_old_names_gone() -> None:
    offenders = []
    for path in repo_files():
        if path.parent.name == "0009-monorepo-layout":  # describes the rename itself
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        in_changelog = False
        for n, line in enumerate(text.splitlines(), 1):
            if path.suffix == ".md" and line.startswith("## "):
                in_changelog = line.startswith("## Changelog")
            if in_changelog:
                continue
            if OLD_IMPORT in line or re.search(re.escape(OLD_NAME) + r"(?!-lib)", line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert offenders == []


@pytest.mark.spec("REPO-013")
def test_docs_describe_new_layout() -> None:
    install = "uv sync --all-packages --all-extras"
    for doc in ("CLAUDE.md", "README.md"):
        assert install in (ROOT / doc).read_text(), doc
    assert "kiozesim-tool/" in (ROOT / "README.md").read_text()
    assert "kiozesim-tool/" in (ROOT / "specs" / "constitution.md").read_text()
