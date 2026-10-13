"""Explicit runtime adapters for task compilation."""
from __future__ import annotations

import copy
import importlib
import json


class DemoRuntime:
    """A small worksheet runtime for examples and integration tests.

    It validates task state and assertion bindings. It does not execute a solution.
    Production applications need an operator-supplied adapter.
    """

    name = "worksheet-demo"
    supported_applications = {"google_sheets"}

    def describe(self):
        return {
            "name": self.name, "applications": sorted(self.supported_applications),
            "assertion_types": ["google_sheets_worksheet_exists",
                                "google_sheets_row_cell_equals", "google_sheets_cell_equals"],
            "collections": ["spreadsheets", "worksheets", "rows"],
            "business_rules": "Cell writes preserve other cells; row identity is immutable.",
        }

    def compile(self, task):
        diagnostics = []

        def error(pointer, expected, actual):
            diagnostics.append({"gate": "runtime_contract", "pointer": pointer,
                                "expected": expected, "actual": actual})

        state = task["initial_state"]
        unknown = set(state) - self.supported_applications
        if unknown:
            error("/initial_state", "worksheet-demo supports google_sheets only", sorted(unknown))
        sheets = state.get("google_sheets") or {}
        if not isinstance(sheets, dict):
            return [{"gate": "runtime_contract", "pointer": "/initial_state/google_sheets",
                     "expected": "object", "actual": type(sheets).__name__}]
        collections = {}
        for collection in ("spreadsheets", "worksheets", "rows"):
            values = sheets.get(collection, [])
            if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
                error("/initial_state/google_sheets/" + collection, "list of records", type(values).__name__)
                values = []
            ids = [row.get("id") for row in values]
            if any(not isinstance(value, str) or not value for value in ids) or len(set(map(str, ids))) != len(ids):
                error("/initial_state/google_sheets/" + collection, "unique nonempty record ids", ids)
            collections[collection] = values
        spreadsheet_ids = {row.get("id") for row in collections["spreadsheets"]}
        worksheets = {row.get("id"): row for row in collections["worksheets"]}
        for position, worksheet in enumerate(collections["worksheets"]):
            if worksheet.get("spreadsheet_id") not in spreadsheet_ids:
                error(f"/initial_state/google_sheets/worksheets/{position}/spreadsheet_id",
                      "existing spreadsheet", worksheet.get("spreadsheet_id"))
        for position, row in enumerate(collections["rows"]):
            worksheet = worksheets.get(row.get("worksheet_id"))
            if not worksheet or row.get("spreadsheet_id") != worksheet.get("spreadsheet_id"):
                error(f"/initial_state/google_sheets/rows/{position}", "existing matching worksheet", row.get("worksheet_id"))
            if not isinstance(row.get("cells"), dict):
                error(f"/initial_state/google_sheets/rows/{position}/cells", "object", type(row.get("cells")).__name__)
        for position, assertion in enumerate(task["assertions"]):
            pointer = f"/assertions/{position}"
            kind = assertion.get("type")
            allowed = set(self.describe()["assertion_types"])
            if kind not in allowed:
                error(pointer + "/type", sorted(allowed), kind)
                continue
            worksheet = worksheets.get(assertion.get("worksheet_id"))
            if not worksheet or worksheet.get("spreadsheet_id") != assertion.get("spreadsheet_id"):
                error(pointer, "existing matching worksheet", assertion.get("worksheet_id"))
                continue
            if kind == "google_sheets_worksheet_exists":
                continue
            matching = [row for row in collections["rows"] if
                        row.get("worksheet_id") == assertion.get("worksheet_id") and
                        str(row.get("row_id")) == str(assertion.get("row_id"))]
            if len(matching) != 1:
                error(pointer + "/row_id", "one existing row", assertion.get("row_id"))
            if assertion.get("column") not in worksheet.get("headers", []):
                error(pointer + "/column", "declared worksheet header", assertion.get("column"))
            if "value" not in assertion:
                error(pointer + "/value", "explicit target value", None)
        return diagnostics


def load_runtime(spec):
    if spec == "demo":
        return DemoRuntime()
    if not spec or ":" not in spec:
        raise ValueError("runtime must be 'demo' or an importable module:factory")
    module, factory = spec.rsplit(":", 1)
    adapter = getattr(importlib.import_module(module), factory)()
    if not callable(getattr(adapter, "describe", None)) or not callable(getattr(adapter, "compile", None)):
        raise TypeError("runtime adapter must implement describe() and compile(task)")
    return adapter
