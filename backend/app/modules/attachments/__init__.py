"""The attachment routes and the rules that read the owner of a file.

A file belongs to an application, a ticket or a chat message. The routes check the read
rule of that owner, so this module imports `applications`, `tickets` and `todos`. The
module `files` holds the storage, the scan, the drafts and the operations on one
attachment, and it imports none of them (§S/backend/python/000651).
"""
