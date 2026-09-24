# asset:bounded_contact_batch@1.1.0

Consume an already-bound HubSpot contact or Slack user identity, perform a bounded field update and protect the declared fields. HubSpot updates `jobtitle` and protects `phone`; Slack updates `status_text` and protects `status_emoji`.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: hubspot_contacts, slack_users. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `hubspot_contacts`:

```json
{
  "business_context": "Customer renewal",
  "entity_refs": [
    "join.target.cedar"
  ],
  "updates": {
    "jobtitle": "Renewal review outcome"
  },
  "protected_fields": [
    "phone"
  ],
  "public_scope": "Only the counterpart matched by the complete business email"
}
```

Explicit parameter example for adapter `slack_users`:

```json
{
  "business_context": "Customer renewal",
  "entity_refs": [
    "join.target.cedar"
  ],
  "updates": {
    "status_text": "Renewal review outcome"
  },
  "protected_fields": [
    "status_emoji"
  ],
  "public_scope": "Only the counterpart matched by the complete business email"
}
```

