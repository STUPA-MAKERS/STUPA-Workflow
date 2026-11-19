"""Application tools for CRUD, comments, PDF jobs, tasks and flow transitions."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ._chat_files import post_message
from ._common import ToolGroup, api, params
from .meetings import download_to

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
    archived: Literal["false", "true", "all"] | None = None,
) -> dict:
    """List applications, one page at a time.

    Each item carries `stateSince`, the time of the last status change.

    Args:
        state: Filter by flow state ids. Give one id or a list of ids; the result
            holds the applications in any of these states.
        gremium: Filter by the id of a Gremium.
        type: Filter by the id of an application type.
        q: Full-text search term.
        archived: `false` (default) lists the working list, `true` the archived
            applications, `all` both.
    """
    states = [state] if isinstance(state, str) else state
    return await api().get(
        "/applications",
        params=params(
            state=states or None, gremium=gremium, type=type, q=q,
            sort=sort, order=order, limit=limit, offset=offset, archived=archived,
        ),
    )


@group.tool
async def get_application(application_id: str) -> dict:
    """Get one application with its data, state, applicant and budget binding.

    `voteGremiumId` names the Gremium that decides the current vote. The server sets it
    when the application enters a vote state and clears it when the application leaves.

    `decision` is the valid decision (approval with deviations): `approvedAmount`,
    `requestedAmount`, `amountDeviates`, `conditions` and where it came from. It is
    null before a decision. `approvedAmount` on the application is the amount that the
    cost center binds; null means as requested.
    """
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
    application_id: str,
    body: str = "",
    visibility: Literal["public", "internal"] | None = None,
    file_paths: list[str] | None = None,
    mentions: list[str] | None = None,
) -> dict:
    """Add a comment to an application, optionally with files and mentions.

    An `internal` comment and its files stay hidden from the applicant. Without a
    `visibility`, a comment with `mentions` is `internal` and any other is `public`. Each file in
    `file_paths` (a local path on the machine of the MCP server, at most 5 per comment)
    goes up as a draft through `POST /apply/attachments`; the comment then binds the
    drafts. Allowed types and the 10 MB cap are those of `upload_attachment`. A comment
    file is not an application attachment: it is not in `list_attachments`, only in the
    `attachments` of the comment (`id`, `filename`, `mime`, `size`, `scanState`).
    Download a clean one with `download_attachment`. Files on an anonymized application
    give 422 `application_anonymized`. A failed upload or post deletes the drafts already uploaded.

    Args:
        body: Markdown, up to 10000 characters; empty only with at least one file.
            Write a mention as "@Display Name".
        file_paths: Local files to attach.
        mentions: Principal ids of the mentioned members (`GET
            /applications/{id}/mentionable`: the persons who read the internal
            comments); they get a mail. Another id, or a mention in a `public`
            comment (the applicant reads its body), gives 422 `mention_not_member`.
    """
    chosen = visibility or ("internal" if mentions else "public")
    payload: dict[str, object] = {
        "body": body,
        "visibility": chosen,
        **({"mentions": mentions} if mentions else {}),
    }
    return await post_message(f"/applications/{application_id}/comments", payload, file_paths)


@group.tool
async def list_comments(application_id: str) -> dict:
    """List the comments on an application, each with its `attachments`."""
    return await api().get(f"/applications/{application_id}/comments")


@group.tool
async def list_tasks() -> dict:
    """List the open tasks of the logged-in user.

    A task is an application that the user can read and act on now: an open vote that
    takes a ballot of the user, or a transition with `requiresAction` that the user may
    fire. An agent token never gets a ballot task, because voting stays human.
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
    approved_amount: str | None = None,
    conditions: list[str] | None = None,
) -> dict:
    """Decide on an application and fire a manual flow transition.

    A transition can approve the application, reject it, or move it in another way.
    Read the valid transition ids from `list_transitions`.

    A transition with `addsToAgenda` puts the application on the agenda of a meeting of
    `agendaGremiumId`. Give `meeting_id` to pick a `planned` meeting of that Gremium.
    The server then adds the agenda item in the same step and answers 422 when the
    meeting does not fit. `non_public` marks that agenda item as not public. Without
    `meeting_id` the server picks the next planned meeting after the step.

    A transition with `allowsDecision` (into an accepted state of the cost center)
    takes a decision: `approved_amount` (decimal string, at least 0 and not above
    the requested amount) and `conditions` (at most 20). A transition with
    `requiresAmount` needs `approved_amount` (422 `approved_amount_required`); confirm
    the amount with the user, the requested amount is the usual value. Any other
    transition answers 422 `decision_not_allowed` to a decision.
    """
    decision = (
        params(approvedAmount=approved_amount, conditions=conditions)
        if approved_amount is not None or conditions is not None
        else None
    )
    return await api().post(
        f"/applications/{application_id}/transition",
        json=params(
            transitionId=transition_id,
            note=note,
            meetingId=meeting_id,
            nonPublic=non_public,
            decision=decision,
        ),
    )


@group.tool
async def edit_application_comment(
    application_id: str, comment_id: str, body: str, mentions: list[str] | None = None
) -> dict:
    """Replace the text of a comment on an application.

    Only the author or a holder of `application.manage` may do this; the audit log
    records the change. `mentions` None keeps the stored mentions, a list replaces them
    (the persons of `list_application_mentionable`).
    """
    return await api().patch(
        f"/applications/{application_id}/comments/{comment_id}",
        json=params(body=body, mentions=mentions),
    )


@group.tool
async def delete_application_comment(application_id: str, comment_id: str) -> dict:
    """Delete a comment on an application and its files, for good.

    Only the author or a holder of `application.manage` may do this; the audit log
    records it. Ask the user before you call this.
    """
    await api().delete(f"/applications/{application_id}/comments/{comment_id}")
    return {"deleted": True}


@group.tool
async def list_application_mentionable(application_id: str) -> list:
    """List the persons whom a comment on this application may mention."""
    return await api().get(f"/applications/{application_id}/mentionable")


@group.tool
async def archive_application(application_id: str) -> dict:
    """Move an application out of the working list (reversible, nothing is deleted).

    This is not the privacy erasure. `unarchive_application` brings it back.
    """
    return await api().post(f"/applications/{application_id}/archive")


@group.tool
async def unarchive_application(application_id: str) -> dict:
    """Bring an archived application back into the working list."""
    return await api().delete(f"/applications/{application_id}/archive")


@group.tool
async def list_application_flow_states(application_id: str) -> list:
    """List all states of the flow of an application: the targets of `force_application_status`."""
    return await api().get(f"/applications/{application_id}/flow-states")


@group.tool
async def force_application_status(
    application_id: str,
    state_id: str,
    reason: Literal["outside_decision", "applicant_error", "error_correction", "other"],
    note: str | None = None,
    approved_amount: str | None = None,
    conditions: list[str] | None = None,
) -> dict:
    """Put an application directly into a state, past the transitions and their guards.

    Requires the right to force a status. `reason` (required) names why:
    `outside_decision` (a Gremium decided outside the platform), `applicant_error`,
    `error_correction` or `other`; `other` needs a `note` of at least 10 characters.
    The audit log records it. 409 when the application has no current state, already
    sits in the target state, or a concurrent change moved it first. Prefer
    `fire_transition` or `record_outside_decision`, and ask the user before you force
    a status.

    A move into an approved state (`isApproved` in `list_application_flow_states`) from
    one that is not approved needs `approved_amount` (decimal string; 422
    `approved_amount_required`); confirm it with the user. `conditions` are optional.
    Any other target ignores the decision.
    """
    decision = (
        params(approvedAmount=approved_amount, conditions=conditions)
        if approved_amount is not None or conditions is not None
        else None
    )
    return await api().post(
        f"/applications/{application_id}/force-status",
        json=params(stateId=state_id, reason=reason, note=note, decision=decision),
    )


@group.tool
async def record_outside_decision(
    application_id: str,
    result: Literal["passed", "failed"],
    meeting_date: str,
    gremium_id: str,
    yes: int | None = None,
    no: int | None = None,
    abstain: int | None = None,
    meeting_id: str | None = None,
    approved_amount: str | None = None,
    conditions: list[str] | None = None,
) -> dict:
    """Record a decision that a Gremium made in a meeting without a vote on the platform.

    Only for an application in a vote state. Requires the right to record decisions.
    `passed` fires the pass branch, `failed` the fail branch, with their actions and
    mails; open votes of the application are cancelled. `meeting_date` is an ISO date,
    not later than today. `yes`/`no`/`abstain` and `meeting_id` (a meeting of the
    platform) are optional. A pass into an approved state needs `approved_amount`
    (decimal string, not above the requested amount); `conditions` are optional.
    Ask the user before you record a decision.
    """
    decision = (
        params(approvedAmount=approved_amount, conditions=conditions)
        if approved_amount is not None or conditions is not None
        else None
    )
    return await api().post(
        f"/applications/{application_id}/outside-decision",
        json=params(
            result=result,
            meetingDate=meeting_date,
            gremiumId=gremium_id,
            yes=yes,
            no=no,
            abstain=abstain,
            meetingId=meeting_id,
            decision=decision,
        ),
    )


@group.tool
async def change_approved_amount(
    application_id: str,
    approved_amount: str,
    reason: str,
    decision_date: str,
    gremium_id: str,
) -> dict:
    """Change the approved amount of an approved application; the state stays.

    Requires the right to change approved amounts. `approved_amount` is a decimal
    string, at least 0; it may be above the requested amount (tell the user). `reason`
    holds 10 to 2000 characters. `decision_date` (ISO date, not later than today) and
    `gremium_id` name the decision that allows the change. The applicant gets a mail
    with the old and the new amount. 409 `application_not_approved` outside an
    approved state. Ask the user before you change an amount.
    """
    return await api().post(
        f"/applications/{application_id}/approved-amount",
        json={
            "approvedAmount": approved_amount,
            "reason": reason,
            "decisionDate": decision_date,
            "gremiumId": gremium_id,
        },
    )


@group.tool
async def request_application_erasure(application_id: str) -> dict:
    """File a privacy erasure request (Art. 17 GDPR) for an application.

    The request goes into the queue of `/admin/privacy` and the privacy officers get a
    mail. Nothing is erased until a privacy officer runs the request in the app.
    """
    return await api().post(f"/applications/{application_id}/erasure-request")


@group.tool
async def list_application_observers(application_id: str) -> list:
    """List the observers of an application (e-mail addresses), the oldest first."""
    return await api().get(f"/applications/{application_id}/observers")


@group.tool
async def add_application_observer(application_id: str, email: str) -> dict:
    """Add an observer by e-mail address; the address gets one mail with a read link.

    At most five observers (422 `observer_limit`), ten adds in an hour (429). The
    applicant address gives 422 `observer_is_applicant`, an address that observes
    already 409 `observer_exists`.
    """
    return await api().post(
        f"/applications/{application_id}/observers", json={"email": email}
    )


@group.tool
async def remove_application_observer(application_id: str, observer_id: str) -> dict:
    """Remove an observer; the next request of the observer gets 403."""
    await api().delete(f"/applications/{application_id}/observers/{observer_id}")
    return {"removed": True}


@group.tool
async def get_application_links(application_id: str) -> dict:
    """Read the Vorgänger, the Folgeanträge and the link history of an application."""
    return await api().get(f"/applications/{application_id}/links")


@group.tool
async def set_application_predecessor(
    application_id: str, predecessor_id: str | None
) -> dict:
    """Set, change or remove (`None`) the Vorgänger of an application.

    The caller needs the edit right on the application and on the Vorgänger. The
    Vorgänger must have the same application type and must not lead back to the
    application. Answers and versions stay as they are.
    """
    path = f"/applications/{application_id}/predecessor"
    if predecessor_id is None:
        await api().delete(path)
        return await api().get(f"/applications/{application_id}/links")
    return await api().put(path, json={"predecessorId": predecessor_id})


@group.tool
async def get_application_prefill(application_id: str) -> dict:
    """Return the answers of an application as the start of a Folgeantrag of the same type.

    The answers fit the current form of the type; pass them as `data` to
    `create_application` together with the predecessor.
    """
    return await api().get(f"/applications/{application_id}/prefill")


@group.tool
async def download_application_pdf(
    application_id: str, target_path: str, overwrite: bool = False
) -> dict:
    """Download the current version of an Antrag as PDF to a local file.

    The PDF holds the head data, the answers by section, the Kostenaufstellung, the
    names of the files and the valid decision. A field that the reader may not read
    prints as `(nicht sichtbar)`.
    """
    return await download_to(
        "GET",
        f"/applications/{application_id}/pdf",
        target_path,
        overwrite=overwrite,
        fallback=f"antrag-{application_id}.pdf",
    )


@group.tool
async def export_applications_xlsx(
    target_path: str,
    state: list[str] | str | None = None,
    gremium: str | None = None,
    type: str | None = None,
    q: str | None = None,
    archived: Literal["false", "true", "all"] | None = None,
    overwrite: bool = False,
) -> dict:
    """Export the application list as `.xlsx` to a local file.

    The filters work as in `list_applications`. The workbook holds no form answers.
    """
    states = [state] if isinstance(state, str) else state
    return await download_to(
        "GET",
        "/applications/export.xlsx",
        target_path,
        overwrite=overwrite,
        fallback="antraege.xlsx",
        query=params(state=states or None, gremium=gremium, type=type, q=q, archived=archived),
    )


def register(mcp: FastMCP) -> None:
    """Register the applications tool group."""
    group.register(mcp)
