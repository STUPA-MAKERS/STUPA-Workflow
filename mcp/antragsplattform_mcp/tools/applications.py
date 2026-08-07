"""Application tools for CRUD, comments, PDF jobs, tasks and flow transitions."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def list_applications(
    state: str | None = None,
    gremium: str | None = None,
    type: str | None = None,
    q: str | None = None,
    sort: Literal["createdAt", "amount"] | None = None,
    order: Literal["asc", "desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List applications, one page at a time.

    Args:
        state: Filter by the id of a flow state.
        gremium: Filter by the id of a Gremium.
        type: Filter by the id of an application type.
        q: Full-text search term.
    """
    return await api().get(
        "/applications",
        params=params(
            state=state, gremium=gremium, type=type, q=q,
            sort=sort, order=order, limit=limit, offset=offset,
        ),
    )


@group.tool
async def get_application(application_id: str) -> dict:
    """Get one application with its data, state, applicant and budget binding."""
    return await api().get(f"/applications/{application_id}")


@group.tool
async def get_application_timeline(application_id: str) -> dict:
    """Get the status and transition history of an application."""
    return await api().get(f"/applications/{application_id}/timeline")


@group.tool
async def list_application_versions(application_id: str) -> dict:
    """Get the version history of the form data of an application, with diffs."""
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
    budget_pot_id: str | None = None,
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
            applicantName=applicant_name, lang=lang, budgetPotId=budget_pot_id,
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
    """Delete an application. Admin only. You cannot undo this.

    An agent token can never call this: an irreversible delete sits in no OAuth
    scope, so it needs a browser session.
    """
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
async def create_application_pdf(application_id: str) -> dict:
    """Queue the PDF generation for an application.

    The call runs asynchronously and returns a job. Poll `get_job(job_id)` until the
    job is done.
    """
    return await api().post(f"/applications/{application_id}/pdf")


@group.tool
async def get_job(job_id: str) -> dict:
    """Get the status of an async job, for example a PDF generation."""
    return await api().get(f"/jobs/{job_id}")


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
    application_id: str, transition_id: str, note: str | None = None
) -> dict:
    """Decide on an application and fire a manual flow transition.

    A transition can approve the application, reject it, or move it in another way.
    Read the valid transition ids from `list_transitions`.
    """
    return await api().post(
        f"/applications/{application_id}/transition",
        json=params(transitionId=transition_id, note=note),
    )


def register(mcp: FastMCP) -> None:
    """Register the applications tool group."""
    group.register(mcp)
