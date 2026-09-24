# asset:app_linkedin@1.2.0

Create a result from explicit business fields; the runtime decides the resulting entity ID, and this asset does not emit a fictional ID for later reference.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: linkedin. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

The runtime's current UGC post path supports only `visibility=PUBLIC`. Private or connections-only posting is unavailable on this pinned runtime and must be rejected before construction; do not downgrade visibility and do not drop the visibility assertion.

Explicit parameter example for adapter `linkedin`:

```json
{
  "business_context": "Customer renewal",
  "application": "linkedin",
  "business_value": "Renewal review outcome",
  "operation_fields": {
    "visibility": "PUBLIC"
  }
}
```

