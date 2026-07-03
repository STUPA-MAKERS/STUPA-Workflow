"""Meeting service — lifecycle, timeline, RBAC scope, vote reads, WS pub/sub glue.

Layout:

* :mod:`.service_base` — shared constructor + lookup/serialization helpers.
* :mod:`.pubsub`       — ``meeting:{id}`` channel + :class:`~.pubsub.BrokerPublisher` WS glue.
* :mod:`.paging`       — timeline keyset/offset cursor helpers.
* :mod:`.permissions`  — RBAC checks, visibility scope, permission-flag serializer.
* :mod:`.votes`        — meeting-bound vote reads: tally reload, reveal rule, quorum.
* :mod:`.listing`      — detail read, list, filter gremien, keyset/search timeline.
* :mod:`.lifecycle`    — create/patch/delete, planned→live→closed rules, broadcast.
* :mod:`.service`      — :class:`~.service.MeetingService` facade combining the ops.

The facade (plus ``BrokerPublisher``/``meeting_channel``) is re-exported here so
``from app.modules.livevote.service import MeetingService`` keeps working.
"""

from app.modules.livevote.service.pubsub import BrokerPublisher, meeting_channel
from app.modules.livevote.service.service import MeetingService

__all__ = ["BrokerPublisher", "MeetingService", "meeting_channel"]
