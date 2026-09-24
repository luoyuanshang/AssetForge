# asset:app_asana@1.1.0

Perform the terminal effect through an operation the runtime actually implements, with parameters the real predicate supports; a generic action predicate only proves that a matching action occurred and does not claim an exact terminal state.

The asset requires the pinned native runtime; this number is the asset version. The parameter values below are standalone functional examples only: the Author chooses this task's own entities, business fields, rules and outcomes.

Supported adapters: asana. Scope and boundaries are those stated in this description, in the parameters, and in the native effects / protection obligations the call returns; other operations in the capability table are not admitted by association.

When composing assets you must use real bound identities. `unresolved_creation_output` is a logical effect marker and must never be treated as an existing native ID; if a later step needs to consume a creation result, read it through this task's independently verified response binding or a native unique key instead.

Explicit parameter example for adapter `asana`:

```json
{
  "business_context": "Customer renewal",
  "application": "asana",
  "business_value": "Renewal review outcome"
}
```

