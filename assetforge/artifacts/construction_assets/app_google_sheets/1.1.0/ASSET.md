# asset:app_google_sheets@1.1.0

Write the named cell under an independent spreadsheet / worksheet / row identity while preserving the declared protected cells; a row number is never treated as a unique identity across worksheets.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: google_sheets. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `google_sheets`:

```json
{
  "business_context": "Customer renewal",
  "application": "google_sheets",
  "spreadsheet_title": "Review ledger",
  "worksheet_title": "Cases",
  "headers": [
    "row_key",
    "review_state",
    "locked_note"
  ],
  "row_key": "case-1709",
  "cells": {
    "review_state": "Renewal review outcome"
  },
  "protected_fields": [
    "locked_note"
  ],
  "protected_values": {
    "locked_note": "Original approval"
  }
}
```

