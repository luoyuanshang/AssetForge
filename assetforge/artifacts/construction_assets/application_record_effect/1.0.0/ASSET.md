# asset:application_record_effect@1.0.0

Modify the selected record among explicitly named target and non-target records, protecting the corresponding field on the non-target; for Gmail only label membership is promised, and for Slack only the topic.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: gmail, hubspot, mailchimp, salesforce, slack. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `gmail`:

```json
{
  "business_context": "Customer renewal",
  "application": "gmail",
  "records": [
    {
      "entity": "cedar",
      "fields": {
        "from_": "cedar@example.org",
        "subject": "cedar request",
        "body_plain": "Initial request",
        "to": [
          "operator@example.org"
        ],
        "label_ids": [
          "INBOX"
        ]
      }
    },
    {
      "entity": "birch",
      "fields": {
        "from_": "birch@example.org",
        "subject": "birch request",
        "body_plain": "Initial request",
        "to": [
          "operator@example.org"
        ],
        "label_ids": [
          "INBOX"
        ]
      }
    }
  ],
  "target_entity": "cedar",
  "value": "Renewal review outcome",
  "protected_fields": [],
  "scope_name": "Review 1709"
}
```

Explicit parameter example for adapter `hubspot`:

```json
{
  "business_context": "Customer renewal",
  "application": "hubspot",
  "records": [
    {
      "entity": "cedar",
      "fields": {
        "email": "cedar@example.org",
        "jobtitle": "Initial role"
      }
    },
    {
      "entity": "birch",
      "fields": {
        "email": "birch@example.org",
        "jobtitle": "Initial role"
      }
    }
  ],
  "target_entity": "cedar",
  "value": "Renewal review outcome",
  "protected_fields": [
    "email"
  ],
  "scope_name": "Review 1709"
}
```

Explicit parameter example for adapter `mailchimp`:

```json
{
  "business_context": "Customer renewal",
  "application": "mailchimp",
  "records": [
    {
      "entity": "cedar",
      "fields": {
        "email": "cedar@example.org",
        "status": "subscribed"
      }
    },
    {
      "entity": "birch",
      "fields": {
        "email": "birch@example.org",
        "status": "subscribed"
      }
    }
  ],
  "target_entity": "cedar",
  "value": "unsubscribed",
  "protected_fields": [
    "email"
  ],
  "scope_name": "Review 1709"
}
```

Explicit parameter example for adapter `salesforce`:

```json
{
  "business_context": "Customer renewal",
  "application": "salesforce",
  "records": [
    {
      "entity": "cedar",
      "fields": {
        "last_name": "cedar",
        "email": "cedar@example.org",
        "department": "Initial department"
      }
    },
    {
      "entity": "birch",
      "fields": {
        "last_name": "birch",
        "email": "birch@example.org",
        "department": "Initial department"
      }
    }
  ],
  "target_entity": "cedar",
  "value": "Renewal review outcome",
  "protected_fields": [
    "email"
  ],
  "scope_name": "Review 1709"
}
```

Explicit parameter example for adapter `slack`:

```json
{
  "business_context": "Customer renewal",
  "application": "slack",
  "records": [
    {
      "entity": "cedar",
      "fields": {
        "name": "cedar-team",
        "topic": "Initial topic"
      }
    },
    {
      "entity": "birch",
      "fields": {
        "name": "birch-team",
        "topic": "Initial topic"
      }
    }
  ],
  "target_entity": "cedar",
  "value": "Renewal review outcome",
  "protected_fields": [],
  "scope_name": "Review 1709"
}
```

