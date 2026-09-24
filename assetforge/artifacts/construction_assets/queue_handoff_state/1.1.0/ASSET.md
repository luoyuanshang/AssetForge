# asset:queue_handoff_state@1.1.0

Require both a queue-ownership change and a hand-off trail while protecting the request subject. Zendesk and Freshdesk use `group_id`, HelpScout uses `mailbox_id`, Reamaze uses `category`, and Gorgias uses an explicit queue label; none of these is a team assignment.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: zendesk, freshdesk, helpscout, reamaze, gorgias. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `zendesk`:

```json
{
  "business_context": "Customer renewal",
  "application": "zendesk",
  "initial_queue": "Initial queue",
  "target_queue": "Review team",
  "trace_value": "Renewal review outcome",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `freshdesk`:

```json
{
  "business_context": "Customer renewal",
  "application": "freshdesk",
  "initial_queue": "Initial queue",
  "target_queue": "Review team",
  "trace_value": "Renewal review outcome",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `helpscout`:

```json
{
  "business_context": "Customer renewal",
  "application": "helpscout",
  "initial_queue": "Initial queue",
  "target_queue": "Review team",
  "trace_value": "Renewal review outcome",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `reamaze`:

```json
{
  "business_context": "Customer renewal",
  "application": "reamaze",
  "initial_queue": "Initial queue",
  "target_queue": "Review team",
  "trace_value": "Renewal review outcome",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

Explicit parameter example for adapter `gorgias`:

```json
{
  "business_context": "Customer renewal",
  "application": "gorgias",
  "initial_queue": "Initial queue",
  "target_queue": "Review team",
  "trace_value": "Renewal review outcome",
  "protected_field": "subject",
  "protected_value": "Original review request"
}
```

