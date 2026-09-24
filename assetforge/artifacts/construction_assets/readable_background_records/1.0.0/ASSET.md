# asset:readable_background_records@1.0.0

Build a non-target record with real business content that can be read back natively; it may be combined with a same-application or cross-application target. A structural read-back is not semantic distraction, and it never carries a required effect that cannot be scored.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: hiver.conversations, hiver.shared_mailboxes, hiver.users, slack.channels. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

A structural background obligation uses empty `assertion_indices` and `case_ids`; separate native read-back evidence checks that record's identity, business content and read-only status. Whether it constitutes meaningful distraction is still judged against this task's goal and exclusion basis.

Explicit parameter example for adapter `hiver.conversations`:

```json
{
  "business_context": "Past renewal",
  "application": "hiver",
  "collection": "conversations",
  "records": [
    {
      "entity": "archive",
      "fields": {
        "subject": "expired application exception attachment",
        "customer_email": "archive@example.org",
        "status": "closed"
      }
    }
  ],
  "read_paths": [
    {
      "method": "GET",
      "url": "https://<native-endpoint>"
    }
  ],
  "exclusion_basis": "These expired records are outside the current request"
}
```

Explicit parameter example for adapter `hiver.shared_mailboxes`:

```json
{
  "business_context": "Past renewal",
  "application": "hiver",
  "collection": "shared_mailboxes",
  "records": [
    {
      "entity": "archive",
      "fields": {
        "name": "expired business mailbox",
        "email": "archive@example.org"
      }
    }
  ],
  "read_paths": [
    {
      "method": "GET",
      "url": "https://<native-endpoint>"
    }
  ],
  "exclusion_basis": "These expired records are outside the current request"
}
```

Explicit parameter example for adapter `hiver.users`:

```json
{
  "business_context": "Past renewal",
  "application": "hiver",
  "collection": "users",
  "records": [
    {
      "entity": "archive",
      "fields": {
        "name": "former approval owner",
        "email": "archive@example.org"
      }
    }
  ],
  "read_paths": [
    {
      "method": "GET",
      "url": "https://<native-endpoint>"
    }
  ],
  "exclusion_basis": "These expired records are outside the current request"
}
```

Explicit parameter example for adapter `slack.channels`:

```json
{
  "business_context": "Past renewal",
  "application": "slack",
  "collection": "channels",
  "records": [
    {
      "entity": "archive",
      "fields": {
        "name": "archived-requests",
        "topic": "Expired policy"
      }
    }
  ],
  "read_paths": [
    {
      "method": "GET",
      "url": "slack/conversations.list"
    }
  ],
  "exclusion_basis": "These expired records are outside the current request"
}
```

