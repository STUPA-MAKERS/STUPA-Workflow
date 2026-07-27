---
name: python-strong-typing
description: "always write strongly-typed Python (>=3.13) — full annotations, no untyped/Any"
metadata: 
  node_type: memory
  type: feedback
---

When you write Python in this project, always write **strongly-typed** code for Python
>= 3.13. Put full type annotations on every function signature, parameter, return, and
non-obvious local. Use modern syntax (`X | None`, builtin generics `list[...]`/`dict[...]`,
`type` statement aliases). Avoid bare `Any` and untyped escape hatches unless you really
cannot avoid them.

**Why:** user instruction ("ALWAYS WRITE STRONGLY TYPED CODE WHEN IN PYTHON (>=3.13)"). The
codebase is typed, and the tsc/mypy-style discipline must stay green.

**How to apply:** annotate as you write, not after. Prefer precise types (Literal, TypedDict,
Protocol, Enum) over loose ones. Match the typing idiom of the surrounding module. See
[[work-autonomously]].
