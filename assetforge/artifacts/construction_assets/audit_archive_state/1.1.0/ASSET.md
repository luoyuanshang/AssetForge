# asset:audit_archive_state@1.1.0

Write the source identity and audit information into Airtable while protecting the `subject` and `status` of the same source record. The archive result is a terminal creation and does not emit an unbound result ID.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: zendesk, freshdesk, helpscout. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `zendesk`:

```json
{
  "business_context": "Customer renewal",
  "source_application": "zendesk",
  "audit_reference": "Renewal review outcome",
  "archived_status": "closed",
  "source_subject": "Original review",
  "source_status": "open",
  "base_name": "Audit archive",
  "table_name": "Reviewed cases"
}
```

Explicit parameter example for adapter `freshdesk`:

```json
{
  "business_context": "Customer renewal",
  "source_application": "freshdesk",
  "audit_reference": "Renewal review outcome",
  "archived_status": "closed",
  "source_subject": "Original review",
  "source_status": 2,
  "base_name": "Audit archive",
  "table_name": "Reviewed cases"
}
```

Explicit parameter example for adapter `helpscout`:

```json
{
  "business_context": "Customer renewal",
  "source_application": "helpscout",
  "audit_reference": "Renewal review outcome",
  "archived_status": "closed",
  "source_subject": "Original review",
  "source_status": "active",
  "base_name": "Audit archive",
  "table_name": "Reviewed cases"
}
```

