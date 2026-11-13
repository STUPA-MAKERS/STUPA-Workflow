"""Documents module: the PDF of an Antrag and the design of the rendered documents.

The module sits between the protocol layer and the domain layer. It reads an Antrag,
builds its Markdown and renders it with the typst service in the design (CD variant)
of its Gremium. The export route and the protocol Anlage use it. `cd_resolver` turns
the design variant of a Gremium into the logos of a render; the protocol and the
Antrag PDF share it.
"""
