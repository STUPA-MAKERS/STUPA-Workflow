"""The meeting core: the part of a meeting that `voting`, `flow` and `applications` read.

The module holds the models of a meeting and of its protocol record, the agenda order, the
read and vote rules, and the publisher of the meeting channel (§S/backend/python/000650).
The live part (routes, WebSocket, lifecycle, live vote) is in `livevote`.
"""
