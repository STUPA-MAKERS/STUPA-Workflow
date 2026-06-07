# T-32 — Voting FE screenshots (Light + Dark)

Headless harness capture (1440×900, `prefers-color-scheme` + `ap.theme` pinned),
mock WS/REST (`USE_MOCK_API`), DE locale.

| View | Route | Light | Dark |
|------|-------|-------|------|
| Mobile live-vote | `/voting` | `voting__light.png` | `voting__dark.png` |
| Vote-cast | `/voting/vote/:id` | `voting_vote_vote-demo__light.png` | `voting_vote_vote-demo__dark.png` |
| Beamer (read-only) | `/voting/beamer` | `voting_beamer__light.png` | `voting_beamer__dark.png` |

Beamer shows aggregate bars + vote count + quorum indicator only — **no voter
names** (consumes the beamer stream's aggregates per api.md §4).
