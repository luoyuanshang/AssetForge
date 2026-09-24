# asset:approval_decision_state@1.1.0

The Author supplies the business decision plus explicit initial and terminal statuses; the asset constructs both the status change and the reason trail while protecting the request subject. This task's policy defines whether decision and status are business-consistent.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: helpscout, freshdesk, reamaze, gorgias, zoho_desk. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `helpscout`:

```json
{
  "business_context": "Customer renewal",
  "application": "helpscout",
  "decision": "Approved",
  "reason": "Renewal review outcome",
  "initial_status": "active",
  "target_status": "closed",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `freshdesk`:

```json
{
  "business_context": "Customer renewal",
  "application": "freshdesk",
  "decision": "Approved",
  "reason": "Renewal review outcome",
  "initial_status": 2,
  "target_status": 5,
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `reamaze`:

```json
{
  "business_context": "Customer renewal",
  "application": "reamaze",
  "decision": "Approved",
  "reason": "Renewal review outcome",
  "initial_status": "unresolved",
  "target_status": "resolved",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `gorgias`:

```json
{
  "business_context": "Customer renewal",
  "application": "gorgias",
  "decision": "Approved",
  "reason": "Renewal review outcome",
  "initial_status": "open",
  "target_status": "closed",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `zoho_desk`:

```json
{
  "business_context": "Customer renewal",
  "application": "zoho_desk",
  "decision": "Approved",
  "reason": "Renewal review outcome",
  "initial_status": "Open",
  "target_status": "Closed",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

