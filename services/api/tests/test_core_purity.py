"""Guards CLAUDE.md rule 3: ax.core is pure — stdlib only, no SQLAlchemy,
no FastAPI, no I/O. Walks the AST of every module in ax.core rather than
trusting review, because a single stray `import` here silently reintroduces
DB/HTTP coupling into code that's supposed to be testable without either.
"""

import ast
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent / "src" / "ax" / "core"
API_ROOT = CORE_DIR.parent.parent.parent
STDLIB = sys.stdlib_module_names


def _package_of(path: Path) -> list[str]:
    """Dotted package (as parts) containing `path`, e.g. ax/core/sub/foo.py
    and ax/core/sub/__init__.py both live in the package ["ax", "core", "sub"]."""
    return ["ax", "core", *path.relative_to(CORE_DIR).parts[:-1]]


def _imported_modules(tree: ast.Module, package: list[str]) -> list[str]:
    """Full dotted module paths this file imports, e.g. "ax.db.session".

    Relative imports are resolved against the importing module's own
    package rather than assumed in-bounds: `from .. import db` from a
    module in ax.core resolves to ax.db, which must be caught, not skipped.
    """
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    modules.append(node.module)
                continue
            base = package[: len(package) - (node.level - 1)]
            if node.module:
                modules.append(".".join([*base, *node.module.split(".")]))
            else:
                modules.extend(".".join([*base, alias.name]) for alias in node.names)
    return modules


def _is_pure(module: str) -> bool:
    root = module.split(".")[0]
    if root == "ax":
        return module == "ax.core" or module.startswith("ax.core.")
    return root in STDLIB


def test_core_has_no_impure_imports() -> None:
    violations = [
        f"{path.relative_to(API_ROOT)}: imports {module!r}"
        for path in sorted(CORE_DIR.rglob("*.py"))
        for module in _imported_modules(
            ast.parse(path.read_text(), filename=str(path)), _package_of(path)
        )
        if not _is_pure(module)
    ]
    assert not violations, "ax.core must be pure (stdlib + ax.core only):\n" + "\n".join(violations)
