# Contamination Database Index — Example Schema

This file shows the catalog format for the contamination image database.
Your own index will grow as the fetch pipeline runs.

| Date | Source | Author | Category | Description | Image | Status |
|------|--------|--------|----------|-------------|-------|--------|
| 2026-01-15 | r/ContamFam | example_user_1 | Cobweb vs. fuzzy feet | Mycelium — community split on cobweb vs. high humidity/low FAE | Gallery (no direct link) | Unresolved |
| 2026-01-15 | r/ContamFam | example_user_2 | Trich | Bottom-left green on fruiting block | Gallery | Suspected contam |
| 2026-01-15 | r/ContamFam | example_user_3 | Trich + thermal remediation | Burn protocol with butane lighter on trich spots | Gallery | Documented success |
| 2026-01-15 | r/ContamFam | example_user_4 | Bruising vs. contam | Bluish-green spots after B&S — time-lapse showed bruising | Gallery | Resolved: bruising |
| 2026-01-15 | r/ContamFam | example_user_5 | Bacteria vs. metabolites | Yellow fluid pooling — asking if bacteria or myc-piss | JPEG | Unresolved |
| 2026-01-15 | r/ContamFam | example_user_6 | Sour smell / bacterial | No visible contam but sour smell today | JPEG | Suspected bacterial |
| 2026-01-15 | r/ContamFam | example_user_7 | Early trich | Suspected early trich image | JPEG | Suspected |
| 2026-01-15 | r/ContamFam | example_user_8 | Fuzzy corners | Second attempt — fuzziness in all corners | Gallery | Likely low FAE |
| 2026-01-15 | r/MushroomGrowers | example_user_9 | Bruising vs. contam | Post-B&S patch, slightly green — first timer | JPEG + Video | Unresolved |
| 2026-01-15 | r/unclebens | example_user_10 | Wet rot (UB bags) | Multiple UB bags failing with wet rot | JPEG | Confirmed wet rot |

---

**Schema notes:**
- **Date**: ISO date of the Reddit post (not the fetch date)
- **Source**: Subreddit where the post originated
- **Author**: Reddit username (for tracing back to original post)
- **Category**: Contamination type or differential diagnosis category
- **Description**: Brief summary of the case and community response
- **Image**: Image format/availability (Gallery = Reddit gallery, no direct URL via JSON API)
- **Status**: Resolution — Unresolved, Suspected [type], Confirmed [type], Resolved: [not contamination], Monitoring

*Future fetches append below the separator line. Total entries grow over time.*
