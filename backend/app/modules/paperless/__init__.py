"""Paperless integration: the connection, the client and the record of each filing.

The module holds the single connection to one Paperless-ngx instance with its four
switches (`paperless_settings`), the HTTP client that speaks to that instance with the
token of the connection, and one row per file that the platform files
(`paperless_filing`). The module `paperless_filing` finds the files and runs the
filings; this module sits below it, so the privacy module can read the filed documents.
"""
