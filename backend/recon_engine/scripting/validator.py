"""Static validation gate for generated transformation scripts.

Runs BEFORE any execution (sandbox preview *and* production — defense in
depth). The script is parsed to an AST and rejected unless it stays inside a
narrow dataframe-transformation dialect:

* must define exactly ``transform(df)`` returning a DataFrame
* imports only from the approved list (``math``, ``re``, ``datetime``) —
  ``pd`` / ``np`` are pre-injected by the sandbox and need no import
* no os / subprocess / socket / requests / urllib / open / eval / exec /
  compile / __import__ or any other system, network, or file access
* no underscore/dunder attribute access (blocks ``__class__``-style escapes)
* no dataframe I/O (``to_csv``, ``read_excel``, …) — file writes are banned

Deterministic: same script, same verdict.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Modules a script may import. pandas/numpy are injected as pd/np, so scripts
# never need to import them; the approved list is for tiny stdlib helpers.
ALLOWED_IMPORTS = frozenset({"math", "re", "datetime"})

# Identifiers that must never appear (as a bare name or attribute name).
BANNED_NAMES = frozenset({
    "os", "sys", "subprocess", "socket", "requests", "urllib", "urllib3",
    "http", "httpx", "ftplib", "smtplib", "shutil", "pathlib", "glob",
    "tempfile", "io", "importlib", "builtins", "ctypes", "pickle",
    "multiprocessing", "threading", "signal",
    "open", "eval", "exec", "compile", "__import__", "input", "breakpoint",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
    "type", "super", "memoryview", "exit", "quit", "help",
})

# DataFrame/pandas attributes that read or write external resources, or
# evaluate strings as code.
BANNED_ATTRIBUTES = frozenset({
    "to_csv", "to_excel", "to_pickle", "to_parquet", "to_sql", "to_hdf",
    "to_feather", "to_clipboard", "to_latex", "to_json", "to_stata", "to_gbq",
    "to_orc", "to_xml", "to_html", "to_markdown",
    "read_csv", "read_excel", "read_pickle", "read_sql", "read_sql_query",
    "read_sql_table", "read_parquet", "read_hdf", "read_feather", "read_html",
    "read_json", "read_xml", "read_clipboard", "read_fwf", "read_table",
    "read_orc", "read_stata", "read_gbq", "read_sas", "read_spss",
    "eval", "query", "pipe",
})

# Statement node types that have no place in a dataframe transformation.
_BANNED_NODE_TYPES: tuple[type[ast.AST], ...] = (
    ast.ClassDef,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.AsyncFor,
    ast.AsyncWith,
    ast.With,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
)

ENTRYPOINT = "transform"


@dataclass
class ScriptValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors)}


def validate_script(script_text: str) -> ScriptValidationReport:
    """Statically validate a transformation script. Never executes it."""
    errors: list[str] = []

    if not script_text or not script_text.strip():
        return ScriptValidationReport(ok=False, errors=["Script is empty."])

    try:
        tree = ast.parse(script_text)
    except SyntaxError as exc:
        return ScriptValidationReport(
            ok=False, errors=[f"Script is not valid Python: {exc.msg} (line {exc.lineno})."]
        )

    entrypoint: ast.FunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == ENTRYPOINT:
            entrypoint = node

    if entrypoint is None:
        errors.append(f"Script must define a `{ENTRYPOINT}(df)` function.")
    elif not entrypoint.args.args:
        errors.append(f"`{ENTRYPOINT}` must accept the dataframe as its first argument.")
    elif not any(isinstance(n, ast.Return) for n in ast.walk(entrypoint)):
        errors.append(f"`{ENTRYPOINT}` must return the transformed dataframe.")

    for node in ast.walk(tree):
        if isinstance(node, _BANNED_NODE_TYPES):
            errors.append(f"Disallowed statement: {type(node).__name__} (line {node.lineno}).")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    errors.append(
                        f"Disallowed import '{alias.name}' (line {node.lineno}); "
                        f"allowed: {sorted(ALLOWED_IMPORTS)}."
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                errors.append(
                    f"Disallowed import from '{node.module}' (line {node.lineno}); "
                    f"allowed: {sorted(ALLOWED_IMPORTS)}."
                )
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES:
                errors.append(f"Disallowed name '{node.id}' (line {node.lineno}).")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_NAMES or node.attr in BANNED_ATTRIBUTES:
                errors.append(f"Disallowed attribute '.{node.attr}' (line {node.lineno}).")
            elif node.attr.startswith("_"):
                errors.append(
                    f"Disallowed private/dunder attribute '.{node.attr}' (line {node.lineno})."
                )

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [e for e in errors if not (e in seen or seen.add(e))]
    return ScriptValidationReport(ok=not unique, errors=unique)
