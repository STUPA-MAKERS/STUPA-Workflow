"""Meeting service — lifecycle, timeline, RBAC scope, vote reads, WebSocket glue.

The package splits the service across modules.

``service_base`` holds the shared constructor and the lookup and serialization helpers.
``pubsub`` holds the ``meeting:{id}`` channel and the ``BrokerPublisher`` WebSocket glue.
``paging`` holds the timeline keyset and offset cursor helpers.
``permissions`` holds the RBAC checks, the visibility scope and the permission-flag
serializer.
``votes`` holds the meeting-bound vote reads: tally reload, reveal rule and quorum.
``listing`` holds the detail read, the list, the Gremium filter and the keyset and
search timeline.
``lifecycle`` holds create, patch, delete, the planned to live to closed rules and
the broadcast.
``service`` holds the ``MeetingService`` facade that combines the operations.

This module re-exports the facade, ``BrokerPublisher`` and ``meeting_channel``, so
``from app.modules.livevote.service import MeetingService`` keeps working.
"""

from app.modules.livevote.service.pubsub import BrokerPublisher, meeting_channel
from app.modules.livevote.service.service import MeetingService

__all__ = ["BrokerPublisher", "MeetingService", "meeting_channel"]
