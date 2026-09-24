"""Bounded, read-only source context for one selected native assertion.

This is static assistance, not a completeness proof or a replacement scorer.
Only referenced functions/constants under the pinned rubric source are exposed.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import CodeType

ASSERTION_DEPENDENCY_CONTEXT_CONTRACT = "native-assertion-static-helper-context-v1"


def _names(code: CodeType) -> set[str]:
    names = set(code.co_names)
    for child in code.co_consts:
        if isinstance(child, CodeType):
            names.update(_names(child))
    return names


def _literal(value, depth=0):
    if depth > 8:
        raise ValueError("constant nesting exceeds bounded context")
    if type(value) in (str, int, float, bool, type(None)):
        return value
    if type(value) in (list, tuple) and len(value) <= 256:
        return [_literal(v, depth + 1) for v in value]
    if type(value) is dict and len(value) <= 256 and all(type(k) is str for k in value):
        return {k: _literal(v, depth + 1) for k, v in value.items()}
    raise ValueError("constant is not a bounded JSON literal")


def assertion_dependency_context(handler, *, package_root: Path, max_symbols=64, max_bytes=65536):
    root = package_root.resolve()
    allowed = root / "benchmark/rubric"
    functions, constants, bindings, omitted = {}, {}, {}, set()
    queue = [handler]

    def source_path(fn):
        filename = inspect.getsourcefile(fn)
        if not filename:
            return None
        path = Path(filename).resolve()
        return path if path.is_relative_to(allowed) else None

    def bind(path):
        relative = path.relative_to(root).as_posix()
        if relative not in bindings:
            bindings[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return relative

    if not inspect.isfunction(handler) or source_path(handler) is None:
        raise ValueError("assertion handler is outside the pinned rubric source")
    while queue:
        fn = queue.pop(0)
        path = source_path(fn)
        key = (fn.__module__, fn.__qualname__)
        if key in functions:
            continue
        functions[key] = {"name": fn.__name__, "qualified_name": fn.__qualname__,
                          "source_path": bind(path), "source": inspect.getsource(fn)}
        for name in sorted(_names(fn.__code__)):
            if name not in fn.__globals__:
                continue
            value = fn.__globals__[name]
            if inspect.isfunction(value):
                if source_path(value) is not None:
                    queue.append(value)
                else:
                    omitted.add(name)
            elif name.isupper():
                try:
                    literal = _literal(value)
                except ValueError:
                    omitted.add(name)
                    continue
                constants[(fn.__module__, name)] = {
                    "name": name, "source_path": bind(path), "value": literal}
        if len(functions) + len(constants) > max_symbols:
            raise ValueError("assertion dependency context exceeds symbol budget; no partial context returned")
    result = {
        "contract": ASSERTION_DEPENDENCY_CONTEXT_CONTRACT,
        "functions": [functions[k] for k in sorted(functions)],
        "constants": [constants[k] for k in sorted(constants)],
        "source_bindings": dict(sorted(bindings.items())),
        "omitted_static_dependencies": sorted(omitted),
        "whole_program_completeness_claimed": False,
        "limitations": "Static direct globals including nested comprehensions only; dynamic attributes, class methods and external libraries are not expanded. Native execution checks remain necessary.",
    }
    if len(json.dumps(result, ensure_ascii=False).encode()) > max_bytes:
        raise ValueError("assertion dependency context exceeds byte budget; no partial context returned")
    return result
