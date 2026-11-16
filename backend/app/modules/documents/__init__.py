"""Documents module: the PDF of an Antrag.

The module sits between the protocol layer and the domain layer. It reads an Antrag,
builds its Markdown and renders it with the typst service. The PDF carries the export
logo of the branding (spec 000891, `site_config.export_logo`), never the design of a
Gremium. The export route and the protocol Anlage use it.
"""
