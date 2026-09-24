# asset:app_google_calendar@1.1.0

Create a result from explicit business fields; the runtime decides the resulting entity ID, and this asset does not emit a fictional ID for later reference.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: google_calendar. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `google_calendar`:

```json
{
  "business_context": "Customer renewal",
  "application": "google_calendar",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "calendar_title": "Review meetings",
    "start": "2026-10-14T09:00:00Z",
    "end": "2026-10-14T10:00:00Z"
  }
}
```

