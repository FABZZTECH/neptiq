# `lib/api` — GENERATED CODE, NEVER HAND-EDIT

ARCHITECTURE §5 marks this directory: **"GENERATED from OpenAPI — never
hand-edit"**.

The API service generates OpenAPI 3.1 from its Pydantic models
(`apps/api/src/neptiq_api`). The TypeScript client in this directory is
generated from that document by `make api-types`.

Why this is enforced rather than advised: the whole point of generating the
client is that a backend field rename becomes a **frontend compile error**
rather than an `undefined` at runtime. Hand-editing a generated file breaks
that guarantee silently — the next regeneration overwrites the edit, and until
then the types lie about what the API returns.

If you need behaviour the generated client does not provide, write it in a
sibling module (`apps/web/lib/` or a hook in `apps/web/components/`) that
*wraps* the generated client. Do not edit the generated output.

`tools/check_generated_untouched.py` verifies in CI that every file in this
directory carries the generator header.
