# asset:native_create_effect@1.2.0

Create a result from explicit business fields; the runtime decides the resulting entity ID, and this asset does not emit a fictional ID for later reference.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: airtable, calendly, chatgpt, docusign, google_calendar, gorgias, jira, linkedin, reamaze, twilio, wave, zoho_desk. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

The runtime's current UGC post path supports only `visibility=PUBLIC`. Private or connections-only posting is unavailable on this pinned runtime and must be rejected before construction; do not downgrade visibility and do not drop the visibility assertion.

Explicit parameter example for adapter `airtable`:

```json
{
  "business_context": "Customer renewal",
  "application": "airtable",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "base_name": "Review ledger",
    "table_name": "Decisions",
    "field": "Outcome"
  }
}
```

Explicit parameter example for adapter `calendly`:

```json
{
  "business_context": "Customer renewal",
  "application": "calendly",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "duration_minutes": 45
  }
}
```

Explicit parameter example for adapter `chatgpt`:

```json
{
  "business_context": "Customer renewal",
  "application": "chatgpt",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "model": "business-assistant"
  }
}
```

Explicit parameter example for adapter `docusign`:

```json
{
  "business_context": "Customer renewal",
  "application": "docusign",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "status": "sent"
  }
}
```

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

Explicit parameter example for adapter `gorgias`:

```json
{
  "business_context": "Customer renewal",
  "application": "gorgias",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "channel": "email"
  }
}
```

Explicit parameter example for adapter `jira`:

```json
{
  "business_context": "Customer renewal",
  "application": "jira",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "project_key": "OPS"
  }
}
```

Explicit parameter example for adapter `linkedin`:

```json
{
  "business_context": "Customer renewal",
  "application": "linkedin",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "visibility": "PUBLIC"
  }
}
```

Explicit parameter example for adapter `reamaze`:

```json
{
  "business_context": "Customer renewal",
  "application": "reamaze",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "category": "priority"
  }
}
```

Explicit parameter example for adapter `twilio`:

```json
{
  "business_context": "Customer renewal",
  "application": "twilio",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "to_number": "+14155551234",
    "from_number": "+14155559876"
  }
}
```

Explicit parameter example for adapter `wave`:

```json
{
  "business_context": "Customer renewal",
  "application": "wave",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "email": "cedar@example.org"
  }
}
```

Explicit parameter example for adapter `zoho_desk`:

```json
{
  "business_context": "Customer renewal",
  "application": "zoho_desk",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "department": "Service desk"
  }
}
```

