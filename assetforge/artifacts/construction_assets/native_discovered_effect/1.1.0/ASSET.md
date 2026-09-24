# asset:native_discovered_effect@1.1.0

Perform the terminal effect through an operation the runtime actually implements, with parameters the real predicate supports; a generic action predicate only proves that a matching action occurred and does not claim an exact terminal state.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: asana, bamboohr, basecamp3, buffer, canva, confluence, facebook_conversions, facebook_lead_ads, facebook_pages, google_ads, google_drive, helpcrunch, instagram, linkedin_ads, linkedin_conversions, monday, notion, pipefy, recruitee, trello, twitter. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `asana`:

```json
{
  "business_context": "Customer renewal",
  "application": "asana",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `bamboohr`:

```json
{
  "business_context": "Customer renewal",
  "application": "bamboohr",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `basecamp3`:

```json
{
  "business_context": "Customer renewal",
  "application": "basecamp3",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `buffer`:

```json
{
  "business_context": "Customer renewal",
  "application": "buffer",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `canva`:

```json
{
  "business_context": "Customer renewal",
  "application": "canva",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `confluence`:

```json
{
  "business_context": "Customer renewal",
  "application": "confluence",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `facebook_conversions`:

```json
{
  "business_context": "Customer renewal",
  "application": "facebook_conversions",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `facebook_lead_ads`:

```json
{
  "business_context": "Customer renewal",
  "application": "facebook_lead_ads",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "creative_name": "Event invitation",
    "message": "Register for the review event",
    "link": "https://promo.example.org/events/review",
    "form": "review-registration"
  }
}
```

Explicit parameter example for adapter `facebook_pages`:

```json
{
  "business_context": "Customer renewal",
  "application": "facebook_pages",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `google_ads`:

```json
{
  "business_context": "Customer renewal",
  "application": "google_ads",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `google_drive`:

```json
{
  "business_context": "Customer renewal",
  "application": "google_drive",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `helpcrunch`:

```json
{
  "business_context": "Customer renewal",
  "application": "helpcrunch",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `instagram`:

```json
{
  "business_context": "Customer renewal",
  "application": "instagram",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `linkedin_ads`:

```json
{
  "business_context": "Customer renewal",
  "application": "linkedin_ads",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `linkedin_conversions`:

```json
{
  "business_context": "Customer renewal",
  "application": "linkedin_conversions",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `monday`:

```json
{
  "business_context": "Customer renewal",
  "application": "monday",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `notion`:

```json
{
  "business_context": "Customer renewal",
  "application": "notion",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `pipefy`:

```json
{
  "business_context": "Customer renewal",
  "application": "pipefy",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `recruitee`:

```json
{
  "business_context": "Customer renewal",
  "application": "recruitee",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `trello`:

```json
{
  "business_context": "Customer renewal",
  "application": "trello",
  "business_value": "Renewal review outcome"
}
```

Explicit parameter example for adapter `twitter`:

```json
{
  "business_context": "Customer renewal",
  "application": "twitter",
  "business_value": "Renewal review outcome"
}
```

