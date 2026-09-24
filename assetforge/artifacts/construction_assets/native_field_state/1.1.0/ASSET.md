# asset:native_field_state@1.1.0

Modify one named field of an existing entity while preserving a second, explicitly chosen field; the Author supplies the initial business fields.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: quickbooks, quickbooks_customers, xero, xero_contacts, zoom. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `quickbooks`:

```json
{
  "business_context": "Customer renewal",
  "application": "quickbooks",
  "field": "doc_number",
  "value": "Renewal review outcome",
  "protected_field": "note",
  "initial_fields": {
    "doc_number": "Initial invoice",
    "note": "Protected note"
  }
}
```

Explicit parameter example for adapter `quickbooks_customers`:

```json
{
  "business_context": "Customer renewal",
  "application": "quickbooks_customers",
  "field": "display_name",
  "value": "Renewal review outcome",
  "protected_field": "email",
  "initial_fields": {
    "display_name": "Initial customer",
    "email": "cedar@example.org"
  }
}
```

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

Explicit parameter example for adapter `xero_contacts`:

```json
{
  "business_context": "Customer renewal",
  "application": "xero_contacts",
  "field": "name",
  "value": "Renewal review outcome",
  "protected_field": "email_address",
  "initial_fields": {
    "name": "Initial customer",
    "email_address": "cedar@example.org"
  }
}
```

Explicit parameter example for adapter `zoom`:

```json
{
  "business_context": "Customer renewal",
  "application": "zoom",
  "field": "topic",
  "value": "Renewal review outcome",
  "protected_field": "agenda",
  "initial_fields": {
    "topic": "Initial meeting",
    "agenda": "Protected agenda"
  }
}
```

