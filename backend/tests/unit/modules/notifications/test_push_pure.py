"""The pure parts of web push.

§F/collaboration/notifications/002502: only the urgent kinds push by default.
§F/collaboration/notifications/002503: a push shows the kind and one short line.
§F/collaboration/notifications/002508: at most two buttons, a jump button opens a place.
§F/collaboration/notifications/002509: a background button carries a signed token.
§F/collaboration/notifications/002510: only https endpoints of known push services.
"""

from __future__ import annotations

import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from itsdangerous import URLSafeTimedSerializer

from app.modules.notifications import webpush
from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.push_kinds import (
    PUSH_DEFAULT_ON_KINDS,
    PUSH_TITLES,
    button_label,
    is_push_kind,
    push_default,
    push_title,
)
from app.modules.notifications.push_sender import outcome_of, vapid_subject
from app.modules.notifications.push_service import (
    PushButton,
    PushJob,
    PushNote,
    SubscriptionIn,
    _check_subscription,
    endpoint_allowed,
    notification_payload,
)
from app.modules.notifications.push_tokens import (
    PushActionClaim,
    PushTokenError,
    read_action,
    sign_action,
)
from app.settings import load_settings
from app.shared.errors import ValidationProblem

SECRET = "push-secret-for-the-unit-tests-01"

#: The example of RFC 8291, appendix A.
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
RFC_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS"
    "6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Q"
    "ulcy4a-fN"
)


def test_encrypt_matches_the_rfc_8291_example() -> None:
    sender = ec.derive_private_key(
        int.from_bytes(webpush.b64url_decode(RFC_AS_PRIVATE), "big"), ec.SECP256R1()
    )
    body = webpush.encrypt(
        RFC_PLAINTEXT,
        p256dh=RFC_UA_PUBLIC,
        auth=RFC_AUTH,
        salt=webpush.b64url_decode(RFC_SALT),
        sender_key=sender,
    )
    assert webpush.b64url(body) == RFC_BODY


def test_encrypt_uses_fresh_salt_and_key() -> None:
    a = webpush.encrypt(b"x", p256dh=RFC_UA_PUBLIC, auth=RFC_AUTH)
    b = webpush.encrypt(b"x", p256dh=RFC_UA_PUBLIC, auth=RFC_AUTH)
    assert a != b
    assert int.from_bytes(a[16:20], "big") == webpush.RECORD_SIZE


def test_encrypt_refuses_a_payload_above_one_record() -> None:
    with pytest.raises(ValueError, match="too large"):
        webpush.encrypt(b"x" * (webpush.MAX_PLAINTEXT + 1), p256dh=RFC_UA_PUBLIC, auth=RFC_AUTH)


def test_vapid_header_signs_the_origin_with_the_key() -> None:
    keys = webpush.generate_vapid_keys()
    now = time.time()
    header = webpush.vapid_authorization(
        "https://fcm.googleapis.com/fcm/send/abc", keys, "mailto:a@example.org", now=now
    )
    token = header.removeprefix("vapid t=").split(",")[0]
    assert header.endswith(f", k={keys.public_key}")
    public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), webpush.b64url_decode(keys.public_key)
    )
    claims = jwt.decode(token, public, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"] == "mailto:a@example.org"
    assert claims["exp"] == int(now) + webpush.VAPID_TTL_SECONDS


def test_vapid_key_rejects_a_non_ec_key() -> None:
    from cryptography.hazmat.primitives.asymmetric import ed25519

    pem = (
        ed25519.Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    with pytest.raises(ValueError, match="not an EC key"):
        webpush.vapid_authorization(
            "https://fcm.googleapis.com/x",
            webpush.VapidKeys(private_pem=pem, public_key="k"),
            "mailto:a@example.org",
            now=0,
        )


def test_now_seconds_is_the_clock() -> None:
    assert abs(webpush.now_seconds() - time.time()) < 5


def test_urgent_kinds_push_by_default_and_the_rest_not() -> None:
    assert {k for k in NOTIFICATION_KINDS if push_default(k)} == set(PUSH_DEFAULT_ON_KINDS)
    assert not push_default("status_update")


def test_every_kind_has_a_push_title_in_both_languages() -> None:
    assert all(is_push_kind(k) for k in NOTIFICATION_KINDS)
    assert all(set(PUSH_TITLES[k]) == {"de", "en"} for k in NOTIFICATION_KINDS)
    assert push_title("mention", "en", "P") == "New mention"
    assert push_title("mention", "fr", "P") == "Neue Erwähnung"
    assert push_title("unknown", "de", "Plattform") == "Plattform"
    assert button_label("todo_done", "en") == "Done"
    assert button_label("todo_done", "fr") == "Erledigt"
    assert not is_push_kind("magic_link")


@pytest.mark.parametrize(
    ("endpoint", "allowed"),
    [
        ("https://fcm.googleapis.com/fcm/send/abc", True),
        ("https://web.push.apple.com/QG", True),
        ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
        ("https://wns2-par02p.notify.windows.com/w/?token=x", True),
        ("http://fcm.googleapis.com/fcm/send/abc", False),
        ("https://evil.example.org/fcm.googleapis.com", False),
        ("https://fcm.googleapis.com.evil.org/x", False),
        ("https://127.0.0.1/x", False),
    ],
)
def test_endpoint_must_be_https_on_a_known_push_service(endpoint: str, allowed: bool) -> None:
    assert endpoint_allowed(endpoint) is allowed


def test_subscription_check_names_each_bad_field() -> None:
    with pytest.raises(ValidationProblem) as caught:
        _check_subscription(
            SubscriptionIn(endpoint="https://evil.example.org/", p256dh="", auth="a", label="")
        )
    fields = {e.field for e in caught.value.errors or ()}
    assert fields == {"endpoint", "keys"}
    _check_subscription(
        SubscriptionIn(endpoint="https://fcm.googleapis.com/x", p256dh="k", auth="a", label="")
    )


def _payload(note: PushNote, principal: uuid.UUID) -> dict[str, object]:
    return notification_payload(
        note,
        title="Titel",
        icon="/icons/icon-192x192.png",
        base="https://app.example.org",
        secret=SECRET,
        principal_id=principal,
    )["notification"]


def test_payload_shows_kind_line_and_opens_the_link() -> None:
    note = PushNote(kind="mention", line="Max in A-1", lang="de", url="https://x/a", tag="t")
    shown = _payload(note, uuid.uuid4())
    assert shown["title"] == "Titel"
    assert shown["body"] == "Max in A-1"
    assert shown["tag"] == "t"
    assert shown["actions"] == []
    assert shown["data"] == {
        "onActionClick": {
            "default": {"operation": "navigateLastFocusedOrOpen", "url": "https://x/a"}
        }
    }


def test_payload_without_link_has_no_default_action() -> None:
    note = PushNote(kind="privacy", line="x", lang="de", url=None, tag="t")
    assert _payload(note, uuid.uuid4())["data"] == {"onActionClick": {}}


def test_payload_buttons_jump_and_act_with_a_signed_token() -> None:
    person, termin = uuid.uuid4(), uuid.uuid4()
    note = PushNote(
        kind="appointment",
        line="Termin",
        lang="en",
        url="https://x/t",
        tag="t",
        buttons=(
            PushButton("appointment_accept", target_id=termin),
            PushButton("appointment_decline", target_id=termin),
            PushButton("open_poll", url="https://x/p"),
        ),
    )
    shown = _payload(note, person)
    assert shown["actions"] == [
        {"action": "appointment_accept", "title": "Accept"},
        {"action": "appointment_decline", "title": "Decline"},
    ]
    clicks = shown["data"]["onActionClick"]  # type: ignore[index]
    accept = clicks["appointment_accept"]
    assert accept["operation"] == "sendRequest"
    token = accept["url"].removeprefix("https://app.example.org/api/push/actions/")
    assert read_action(SECRET, token) == PushActionClaim(person, "appointment_accept", termin)


def test_payload_drops_a_button_without_its_data() -> None:
    note = PushNote(
        kind="poll_started",
        line="x",
        lang="de",
        url=None,
        tag="t",
        buttons=(PushButton("open_poll"), PushButton("todo_done")),
    )
    assert _payload(note, uuid.uuid4())["actions"] == []
    jump = PushNote(
        kind="poll_started",
        line="x",
        lang="de",
        url=None,
        tag="t",
        buttons=(PushButton("open_poll", url="https://x/p"),),
    )
    shown = _payload(jump, uuid.uuid4())
    assert shown["actions"] == [{"action": "open_poll", "title": "Zur Abstimmung"}]
    assert shown["data"]["onActionClick"]["open_poll"] == {  # type: ignore[index]
        "operation": "navigateLastFocusedOrOpen",
        "url": "https://x/p",
    }


def test_job_round_trips_through_the_queue_form() -> None:
    job = PushJob(subscription_id="s", payload="{}", urgency="high", ttl=60, job_id="j")
    back = PushJob.from_payload(job.to_payload())
    assert (back.subscription_id, back.payload, back.urgency, back.ttl) == ("s", "{}", "high", 60)
    assert PushJob.from_payload({"subscriptionId": "s", "payload": "{}"}).urgency == "normal"


def test_token_round_trip_and_refusals() -> None:
    claim = PushActionClaim(uuid.uuid4(), "todo_done", uuid.uuid4())
    token = sign_action(SECRET, claim)
    assert read_action(SECRET, token) == claim
    with pytest.raises(PushTokenError):
        read_action("another-secret-of-thirty-chars-0", token)
    with pytest.raises(PushTokenError):
        read_action(SECRET, token, max_age=-1)
    forge = URLSafeTimedSerializer(SECRET, salt="push-action")
    with pytest.raises(PushTokenError):
        read_action(SECRET, str(forge.dumps(["list"])))
    with pytest.raises(PushTokenError):
        read_action(SECRET, str(forge.dumps({"p": "x", "a": "todo_done", "t": "y"})))
    with pytest.raises(PushTokenError):
        read_action(
            SECRET,
            str(forge.dumps({"p": str(uuid.uuid4()), "a": "vote", "t": str(uuid.uuid4())})),
        )


@pytest.mark.parametrize(
    ("status", "outcome"),
    [(201, "sent"), (404, "gone"), (410, "gone"), (429, "retry"), (503, "retry"), (400, "refused")],
)
def test_outcome_of_the_push_service_status(status: int, outcome: str) -> None:
    assert outcome_of(status) == outcome


def test_vapid_subject_prefers_the_https_base() -> None:
    base = {"session_secret": SECRET, "magic_link_secret": SECRET}
    https = load_settings(**base, public_base_url="https://app.example.org/")
    plain = load_settings(**base, public_base_url="http://localhost", mail_from="n@example.org")
    assert vapid_subject(https) == "https://app.example.org"
    assert vapid_subject(plain) == "mailto:n@example.org"


def test_payload_is_json_serialisable() -> None:
    note = PushNote(kind="mention", line="ä", lang="de", url="https://x", tag="t")
    assert json.loads(json.dumps(_payload(note, uuid.uuid4())))["body"] == "ä"


async def test_http_poster_posts_to_the_pinned_ip_without_redirects() -> None:
    import httpx

    from app.modules.notifications.push_sender import HttpPushPoster

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    poster = HttpPushPoster(
        resolver=lambda _host: ["2001:4860:4860::8888", "142.250.0.1"],
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    status = await poster.post("https://fcm.googleapis.com/fcm/send/x", {"TTL": "60"}, b"body")
    assert status == 201
    [request] = seen
    assert request.url.host == "142.250.0.1"
    assert request.headers["Host"] == "fcm.googleapis.com"
    assert request.content == b"body"


async def test_http_poster_refuses_a_private_target() -> None:
    from app.modules.notifications.push_sender import HttpPushPoster
    from app.shared.ssrf import SsrfError

    poster = HttpPushPoster(resolver=lambda _host: ["10.0.0.1"])
    with pytest.raises(SsrfError):
        await poster.post("https://fcm.googleapis.com/fcm/send/x", {}, b"")
