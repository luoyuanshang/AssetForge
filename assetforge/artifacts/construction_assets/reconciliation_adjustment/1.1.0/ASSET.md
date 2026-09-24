# asset:reconciliation_adjustment@1.1.0

Write the reconciliation outcome into an identity-bound Sheets row, keeping the explicitly named source fields and the ledger's protected cells; source fields that are not declared carry no blanket protection promise.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: xero, quickbooks. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `xero`:

```json
{
  "business_context": "Customer renewal",
  "source_application": "xero",
  "source_fields": {
    "reference": "Source invoice",
    "status": "DRAFT"
  },
  "preserved_source_fields": [
    "status"
  ],
  "spreadsheet_title": "Reconciliation ledger",
  "worksheet_title": "Adjustments",
  "headers": [
    "row_key",
    "adjustment",
    "prior_locked"
  ],
  "row_key": "review-1709",
  "adjustment_cells": {
    "adjustment": "Renewal review outcome"
  },
  "ledger_protected_values": {
    "prior_locked": "Original approval"
  }
}
```

Explicit parameter example for adapter `quickbooks`:

```json
{
  "business_context": "Customer renewal",
  "source_application": "quickbooks",
  "source_fields": {
    "doc_number": "Source invoice",
    "note": "Original note"
  },
  "preserved_source_fields": [
    "note"
  ],
  "spreadsheet_title": "Reconciliation ledger",
  "worksheet_title": "Adjustments",
  "headers": [
    "row_key",
    "adjustment",
    "prior_locked"
  ],
  "row_key": "review-1709",
  "adjustment_cells": {
    "adjustment": "Renewal review outcome"
  },
  "ledger_protected_values": {
    "prior_locked": "Original approval"
  }
}
```

