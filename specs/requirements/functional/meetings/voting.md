# Voting

Kind: Requirement
Status: Draft
Scope: backend/app/modules/voting, frontend/src/app/features/voting
Updated: 2026-11-05

## F-meetings-voting-0001 Every vote is secret

Every motion, election and poll must be secret. The API must refuse `secret: false` with 422
`open_vote_unavailable`. The UI must not show a switch for open votes.

Reason: An open ballot shows how each member voted.

Test: `backend/tests/unit/modules/voting/`

## F-meetings-voting-0002 A cast ballot does not change

A voter must not change or withdraw a ballot after the cast. The UI must not offer
"Stimme nach Abgabe änderbar".

Reason: A changed ballot rewrites a decision after the fact.

## F-meetings-voting-0003 A tie rejects a motion

A tie in a motion must give the result `rejected`. There is no result "Stimmengleichheit".

## F-meetings-voting-0004 A tie in an election is decided by lot

A tie at the seat limit of a personnel election must be decided by lot. The platform draws
the lot. There is no runoff.

## F-meetings-voting-0005 Only the protokollant opens and closes a meeting vote

Only the protokollant opens and closes a vote in a meeting. The meeting lead can prepare,
cancel and delete a vote.

## F-meetings-voting-0006 A vote can be deleted only as draft or cancelled

A vote in the state `draft` or `cancelled` can be deleted. An open or closed vote must answer
409 `vote_not_deletable`. The UI shows "Beschlussfrage löschen" only for a draft or cancelled
vote.

Reason: An open or closed vote is part of the meeting record.

## F-meetings-voting-0007 A vote on an Antrag belongs to the Gremium of the Antrag

A vote on an Antrag must belong to the Gremium of that Antrag.

## F-meetings-voting-0008 A poll shows only counts

A poll shows the count per option and "n Antworten". It must not show a disclaimer such as
"Meinungsbild, kein Beschluss". A poll has no quorum, no majority and no lot, and it does not
change an Antrag.
