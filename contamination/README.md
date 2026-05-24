# Contamination Module

**Status: Experimental**

An optional module for building a contamination pattern database from public Reddit community data.

## Overview

This module scrapes contamination-related posts from mushroom cultivation subreddits and catalogs them into a structured database. Over time, this builds a searchable reference of contamination signatures, misidentification patterns, and community-validated diagnoses.

## Data Sources

- **r/ContamFam** — dedicated contamination identification subreddit (all posts included)
- **r/MushroomGrowers** — keyword-filtered for contamination-related content
- **r/mycology** — keyword-filtered
- **r/unclebens** — keyword-filtered
- **r/mushroomgrowing** — keyword-filtered

## How It Works

1. **No OAuth needed** — uses Reddit's public `.json` endpoints (e.g., `reddit.com/r/ContamFam/new.json`)
2. The fetch script (`reddit-fetch-parser.py`) pulls recent posts, filters by keywords, and outputs structured markdown
3. Results are cataloged into the contamination database with date, source, category, and resolution status
4. The agent cross-references new entries against `knowledge/contamination-signatures.md` for pattern matching

## Contents

| File | Description |
|------|-------------|
| `reddit-fetch-parser.py` | Python script to fetch and parse Reddit contamination posts |
| `db-schema.md` | Database structure and labeling conventions |
| `index-example.md` | Example index entries showing the catalog format |

## Database Schema

Users build their own image collection and index. The schema is provided in `db-schema.md`. The index tracks:

- Date, source subreddit, author
- Contamination category (trich, cobweb, bacterial, bruising, etc.)
- Description and differential diagnosis
- Image reference (URL or local filename)
- Resolution status (confirmed, unresolved, resolved: not contamination, etc.)

## Future: Vision Model Integration

A planned future enhancement is automated contamination detection using vision models:

- The decision engine (`mycodo_skill/decision_engine.py`) includes a stub for image analysis in the contamination assessment pipeline
- When a vision-capable model is available, the agent could analyze grow-tent camera images against the contamination signature database
- This would enable proactive contamination alerts before the operator notices visual changes
- **Current status:** Stub only. No vision model is integrated. The agent relies on sensor data and operator reports for contamination detection.

## Setup

```bash
# Install dependencies (just standard library — no pip packages needed)
python3 contamination/reddit-fetch-parser.py --out ./contamination-data/fetch.md --days 7
```

The script uses `curl` for HTTP requests to avoid Python dependency on `requests`. Ensure `curl` is available on your system.

## Cron Integration

To automate fetches, add to your crontab:

```cron
# Fetch contamination posts daily at 6 AM
0 6 * * * python3 /path/to/contamination/reddit-fetch-parser.py --out /path/to/contamination-data/fetch.md --days 7
```

## Rate Limiting

Reddit rate-limits unauthenticated GET requests. The script spaces fetches across subreddits. Do not run more than once per hour to avoid 429 errors.

## Known Limitations

- Gallery posts lack direct image URLs in the Reddit JSON API — cataloged as metadata-only
- Image downloading requires separate tooling (not included)
- No authentication means lower rate limits than the official Reddit API
- Reddit may change their public JSON endpoint behavior without notice
