"""MVC import rules (handoff section 3)."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _files(folder: str) -> list[Path]:
    return sorted((APP / folder).rglob("*.py"))


def test_controllers_do_not_import_database_vector_or_http_libraries():
    forbidden = ("sqlalchemy", "chromadb", "httpx")
    offenders = {
        str(path.relative_to(APP)): sorted(name for name in _imports(path)
                                           if name.split(".")[0] in forbidden)
        for path in _files("controllers")
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert offenders == {}


def test_models_never_import_controllers_or_views():
    offenders = {}
    for path in _files("models"):
        bad = sorted(name for name in _imports(path) if name.startswith(("app.controllers", "app.views")))
        if bad:
            offenders[str(path.relative_to(APP))] = bad
    assert offenders == {}


def test_views_do_not_import_models_or_controllers():
    offenders = {}
    for path in _files("views"):
        bad = sorted(name for name in _imports(path) if name.startswith(("app.models", "app.controllers")))
        if bad:
            offenders[str(path.relative_to(APP))] = bad
    assert offenders == {}


def test_templates_contain_no_python_logic():
    for template in (APP / "views" / "templates").glob("*.html"):
        text = template.read_text(encoding="utf-8")
        assert "{% set " not in text and "{% macro" not in text, template.name
