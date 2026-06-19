---
name: python-strong-typing
description: "always write strongly-typed Python (>=3.13) — full annotations, no untyped/Any"
metadata: 
  node_type: memory
  type: feedback
---

When writing Python in this project, always write **strongly-typed** code targeting Python
>= 3.13. Full type annotations on every function signature, parameter, return, and
non-obvious local. Use modern syntax (`X | None`, builtin generics `list[...]`/`dict[...]`,
`type` statement aliases). Avoid bare `Any` and untyped escape hatches unless genuinely
unavoidable.

**Why:** User instruction ("ALWAYS WRITE STRONGLY TYPED CODE WHEN IN PYTHON (>=3.13)"). The
codebase is typed and tsc/mypy-style discipline is expected to stay green.

**How to apply:** Annotate as you write, not after. Prefer precise types (Literal, TypedDict,
Protocol, Enum) over loose ones. Match the surrounding module's typing idiom. See
[[work-autonomously]].
