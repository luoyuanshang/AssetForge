# asset:readable_policy_exception@1.2.0

Place the Author's rule, precedence exception and scope into a readable carrier; the asset neither interprets the policy nor decides it for the Author. Gmail keeps the original message identity and labels, and the body is checked for semantic inclusion after runtime normalisation.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: slack_topic, gmail_message_body. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `slack_topic`:

```json
{
  "business_context": "Customer renewal",
  "readable_carrier": "slack_topic",
  "title": "Review policy",
  "scope": "Current customer accounts",
  "rule": "Enterprise accounts need a review outcome.",
  "exception": "Paused accounts remain unchanged.",
  "precedence": "exception_over_rule",
  "protected": true,
  "channel_name": "review-policies"
}
```

Explicit parameter example for adapter `gmail_message_body`:

```json
{
  "business_context": "Customer renewal",
  "readable_carrier": "gmail_message_body",
  "title": "Review policy",
  "scope": "Current customer accounts",
  "rule": "Enterprise accounts need a review outcome.",
  "exception": "Paused accounts remain unchanged.",
  "precedence": "exception_over_rule",
  "protected": true,
  "sender": "policy@example.org",
  "recipient": "operator@example.org",
  "subject": "Current review policy"
}
```

