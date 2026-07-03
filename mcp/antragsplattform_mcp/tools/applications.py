"""Application tools: CRUD, comments, PDF jobs, and flow decisions (tasks/transitions)."""

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
    """List applications (paged). Filters: state (id), gremium (id), type (id),
    q (full-text), sort, order."""
    return await api().get(
        "/applications",
        params=params(
            state=state, gremium=gremium, type=type, q=q,
            sort=sort, order=order, limit=limit, offset=offset,
        ),
    )


@group.tool
async def get_application(application_id: str) -> dict:
    """Fetch one application (data, state, applicant, budget binding)."""
    return await api().get(f"/applications/{application_id}")


@group.tool
async def get_application_timeline(application_id: str) -> dict:
    """Status/transition history of an application."""
    return await api().get(f"/applications/{application_id}/timeline")


@group.tool
async def list_application_versions(application_id: str) -> dict:
    """Version history of an application's form data (with diffs)."""
    return await api().get(f"/applications/{application_id}/versions")


@group.tool
async def get_application_form(application_id: str) -> dict:
    """The form version pinned to an application (fields as the applicant saw them)."""
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
    """Create an application of the given type. `data` = form-field values (validated
    against the type's effective form — see get_effective_form). For a logged-in user,
    email/name are derived from the account if omitted."""
    return await api().post(
        "/applications",
        json=params(
            typeId=type_id, data=data, applicantEmail=applicant_email,
            applicantName=applicant_name, lang=lang, budgetPotId=budget_pot_id,
        ),
    )


@group.tool
async def update_application(application_id: str, data: dict[str, Any]) -> dict:
    """Patch an application's form data (creates a new data version). Subject to edit
    permissions and the state's editAllowed flag."""
    return await api().patch(f"/applications/{application_id}", json={"data": data})


@group.tool
async def delete_application(application_id: str) -> dict:
    """Delete an application (admin-only, irreversible)."""
    return await api().delete(f"/applications/{application_id}")


@group.tool
async def comment_application(
    application_id: str, body: str, visibility: Literal["public", "internal"] = "public"
) -> dict:
    """Add a comment to an application. `internal` comments are hidden from the applicant."""
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
    """Enqueue PDF generation for an application — ASYNC, returns a job; poll with
    `get_job(job_id)` until done."""
    return await api().post(f"/applications/{application_id}/pdf")


@group.tool
async def get_job(job_id: str) -> dict:
    """Status of an async job (e.g. PDF generation)."""
    return await api().get(f"/jobs/{job_id}")


@group.tool
async def list_tasks() -> dict:
    """List the logged-in user's open tasks: applications in vote states of their
    committees, or with at least one firable transition that requires action."""
    return await api().get("/applications/tasks")


@group.tool
async def list_transitions(application_id: str) -> dict:
    """List the flow transitions currently firable on an application (for this user).
    Each carries `requiresAction` — false marks an optional action (no open task)."""
    return await api().get(f"/applications/{application_id}/transitions")


@group.tool
async def fire_transition(
    application_id: str, transition_id: str, note: str | None = None
) -> dict:
    """Decide on an application: fire a manual flow transition (approve/reject/etc).
    Get valid transition ids from `list_transitions`."""
    return await api().post(
        f"/applications/{application_id}/transition",
        json=params(transitionId=transition_id, note=note),
    )


def register(mcp: FastMCP) -> None:
    """Register the applications tool group."""
    group.register(mcp)
