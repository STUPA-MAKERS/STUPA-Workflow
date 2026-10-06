"""Application tools for CRUD, comments, PDF jobs, tasks and flow transitions."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def list_applications(
    state: list[str] | str | None = None,
    gremium: str | None = None,
    type: str | None = None,
    q: str | None = None,
    sort: Literal["createdAt", "amount", "stateSince"] | None = None,
    order: Literal["asc", "desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List applications, one page at a time.

    Each item carries `stateSince`, the time of the last status change.

    Args:
        state: Filter by flow state ids. Give one id or a list of ids; the result
            holds the applications in any of these states.
        gremium: Filter by the id of a Gremium.
        type: Filter by the id of an application type.
        q: Full-text search term.
    """
    states = [state] if isinstance(state, str) else state
    return await api().get(
        "/applications",
        params=params(
            state=states or None, gremium=gremium, type=type, q=q,
            sort=sort, order=order, limit=limit, offset=offset,
        ),
    )


@group.tool
async def get_application(application_id: str) -> dict:
    """Get one application with its data, state, applicant and budget binding."""
    return await api().get(f"/applications/{application_id}")


@group.tool
async def get_application_timeline(application_id: str) -> dict:
    """Get the status and transition history of an application.

    Each event names the state, the label of the fired transition, the actor and the
    time.
    """
    return await api().get(f"/applications/{application_id}/timeline")


@group.tool
async def list_application_versions(application_id: str) -> dict:
    """Get the version history of the form data of an application, with diffs.

    Each version lists its `changedKeys`. Without `application.read` the fields
    marked as personal data (isPII) are left out of `data` and `diff`.
    """
    return await api().get(f"/applications/{application_id}/versions")


@group.tool
async def get_application_form(application_id: str) -> dict:
    """Get the form version that is pinned to an application.

    The fields come back as the applicant saw them.
    """
    return await api().get(f"/applications/{application_id}/form")


@group.tool
async def create_application(
    type_id: str,
    data: dict[str, Any],
    applicant_email: str | None = None,
    applicant_name: str | None = None,
    lang: str | None = None,
) -> dict:
    """Create an application of the given type.

    For a logged-in user, the server takes the email and the name from the account
    when you omit them.

    Args:
        data: The form-field values. The server validates them against the effective
            form of the type. Read that form with `get_effective_form`.
    """
    return await api().post(
        "/applications",
        json=params(
            typeId=type_id, data=data, applicantEmail=applicant_email,
            applicantName=applicant_name, lang=lang,
        ),
    )


@group.tool
async def search_on_behalf_applicants(q: str) -> list[dict[str, Any]]:
    """Search the accounts that can be the applicant of `create_application_on_behalf`.

    The search matches the name and the e-mail of the active accounts. It needs at
    least two characters and returns at most 20 accounts (`id`, `displayName`,
    `email`). It needs the permission `application.create_on_behalf`.
    """
    return await api().get("/applications/on-behalf/applicants", params=params(q=q))


@group.tool
async def create_application_on_behalf(
    type_id: str,
    data: dict[str, Any],
    applicant_principal_id: str | None = None,
    applicant_name: str | None = None,
    applicant_email: str | None = None,
    received_on: str | None = None,
    intake: str | None = None,
    lang: str | None = None,
) -> dict:
    """Capture and submit an application on behalf of an applicant.

    Use this for an application that reached the Gremium another way, for example as
    a PDF or a mail. The application belongs to the applicant, as if the applicant had
    submitted it, and enters the normal flow at once. You show only in the history and
    in the audit log. The applicant gets a mail with a link (an account: the normal
    link; a guest: a personal access link). It needs the permission
    `application.create_on_behalf`.

    Args:
        data: The form-field values. The server validates them against the effective
            form of the type, as for a normal submission (`get_effective_form`).
        applicant_principal_id: The id of an applicant account
            (`search_on_behalf_applicants`). Give EITHER this OR a guest.
        applicant_name: The name of a guest applicant without an account.
        applicant_email: The e-mail of a guest applicant without an account.
        received_on: The date on which the application came in (`YYYY-MM-DD`). The
            default is today. A date in the future gives 422.
        intake: How the application came in, for example "per PDF" (max. 500 chars).
    """
    return await api().post(
        "/applications/on-behalf",
        json=params(
            typeId=type_id, data=data, applicantPrincipalId=applicant_principal_id,
            applicantName=applicant_name, applicantEmail=applicant_email,
            receivedOn=received_on, intake=intake, lang=lang,
        ),
    )


@group.tool
async def update_application(application_id: str, data: dict[str, Any]) -> dict:
    """Patch the form data of an application.

    The call creates a new data version. It obeys the edit permissions and the
    `editAllowed` flag of the state.
    """
    return await api().patch(f"/applications/{application_id}", json={"data": data})


@group.tool
async def delete_application(application_id: str) -> dict:
    """Delete an application. Admin only. You cannot undo this."""
    return await api().delete(f"/applications/{application_id}")


@group.tool
async def comment_application(
    application_id: str, body: str, visibility: Literal["public", "internal"] = "public"
) -> dict:
    """Add a comment to an application.

    An `internal` comment stays hidden from the applicant.
    """
    return await api().post(
        f"/applications/{application_id}/comments",
        json={"body": body, "visibility": visibility},
    )


@group.tool
async def list_comments(application_id: str) -> dict:
    """List the comments on an application."""
    return await api().get(f"/applications/{application_id}/comments")


@group.tool
async def list_tasks() -> dict:
    """List the open tasks of the logged-in user.

    A task is an application in a vote state of one of the Gremien of the user. A task
    is also an application with at least one firable transition that requires action.
    """
    return await api().get("/applications/tasks")


@group.tool
async def list_transitions(application_id: str) -> dict:
    """List the flow transitions that this user can fire on an application.

    Each transition carries `requiresAction`. A value of false marks an optional
    action that creates no open task.
    """
    return await api().get(f"/applications/{application_id}/transitions")


@group.tool
async def fire_transition(
    application_id: str,
    transition_id: str,
    note: str | None = None,
    meeting_id: str | None = None,
    non_public: bool | None = None,
) -> dict:
    """Decide on an application and fire a manual flow transition.

    A transition can approve the application, reject it, or move it in another way.
    Read the valid transition ids from `list_transitions`.

    A transition with `addsToAgenda` puts the application on the agenda of a meeting of
    `agendaGremiumId`. Give `meeting_id` to pick a `planned` meeting of that Gremium.
    The server then adds the agenda item in the same step and answers 422 when the
    meeting does not fit. `non_public` marks that agenda item as not public. Without
    `meeting_id` the server picks the next planned meeting after the step.
    """
    return await api().post(
        f"/applications/{application_id}/transition",
        json=params(
            transitionId=transition_id,
            note=note,
            meetingId=meeting_id,
            nonPublic=non_public,
        ),
    )


def register(mcp: FastMCP) -> None:
    """Register the applications tool group."""
    group.register(mcp)
