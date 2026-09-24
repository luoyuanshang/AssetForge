# asset:app_xero@1.1.0

Modify one named field of an existing entity while preserving a second, explicitly chosen field; the Author supplies the initial business fields.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: xero. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `xero`:

```json
{
  "business_context": "Customer renewal",
  "application": "xero",
  "field": "reference",
  "value": "Renewal review outcome",
  "protected_field": "status",
  "initial_fields": {
    "reference": "Initial reference",
    "status": "DRAFT"
  }
}
```

