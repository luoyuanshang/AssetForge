# asset:customer_link@1.3.0

Build a cross-application identity relation from a complete, unique business mailbox; the Author supplies the real business fields, and the asset handles only the native schema, stable IDs, read entry points and relation binding. It does not decide who the task selects.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: freshdesk_contacts, gmail_messages, helpscout_customers, hubspot_contacts, intercom_contacts, mailchimp_subscribers, salesforce_contacts, slack_users, xero_contacts, zendesk_users. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `freshdesk_contacts`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "freshdesk_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "name": "cedar"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "name": "birch"
        }
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `gmail_messages`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "gmail_messages",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "subject": "cedar request",
          "body_plain": "Account review request"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "subject": "birch request",
          "body_plain": "Account review request"
        }
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `helpscout_customers`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "helpscout_customers",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {}
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {}
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `hubspot_contacts`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  },
  "target": {
    "adapter": "slack_users",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "name": "cedar",
          "status_text": "Available",
          "status_emoji": "seedling"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "name": "birch",
          "status_text": "Available",
          "status_emoji": "seedling"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `intercom_contacts`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "intercom_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {}
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {}
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `mailchimp_subscribers`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "mailchimp_subscribers",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "status": "subscribed"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "status": "subscribed"
        }
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `salesforce_contacts`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "salesforce_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "last_name": "cedar",
          "department": "Enterprise"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "last_name": "birch",
          "department": "Enterprise"
        }
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `slack_users`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "slack_users",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "name": "cedar",
          "status_text": "Available",
          "status_emoji": "seedling"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "name": "birch",
          "status_text": "Available",
          "status_emoji": "seedling"
        }
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `xero_contacts`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "xero_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "name": "cedar"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "name": "birch"
        }
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

Explicit parameter example for adapter `zendesk_users`:

```json
{
  "business_context": "Customer renewal",
  "match_semantics": "exact_email_unique",
  "source": {
    "adapter": "zendesk_users",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "name": "cedar"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "name": "birch"
        }
      }
    ]
  },
  "target": {
    "adapter": "hubspot_contacts",
    "records": [
      {
        "entity": "cedar",
        "business_key": "cedar@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      },
      {
        "entity": "birch",
        "business_key": "birch@example.org",
        "fields": {
          "jobtitle": "Initial role",
          "phone": "+14155551234"
        }
      }
    ]
  }
}
```

