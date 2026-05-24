# Contamination Monitoring Pipeline

This document covers the Reddit-based contamination data collection pipeline: fetch structure, parsing, image extraction, and pipeline health diagnostics.

---

## Overview

The contamination monitoring pipeline collects posts from mushroom cultivation subreddits, classifies them by contamination type, downloads images for vision model training, and catalogs entries in a searchable index.

### Data flow

```
Reddit JSON API -> reddit-fetch-parser.py -> contamination-fetch.md (text)
                                          -> contamination-db/images/ (JPEGs)
                                          -> contamination-db/index.md (catalog)
```

---

## Reddit Fetch Structure

### File naming convention

| File | Schedule | Content |
|------|----------|---------|
| `reddit-feeds/raw/contamination-fetch.md` | AM (morning) | r/contamfam hot posts + keyword search across growing subs |
| `reddit-feeds/raw/contamination-fetch-pm.md` | PM (evening) | Same subs, sorted by new |

### Subreddit priority

| Priority | Subreddit | Yield | Notes |
|----------|-----------|-------|-------|
| 1 | r/ContamFam | High | Contamination-dedicated; use `new.json` not search |
| 2 | r/MushroomGrowers | Medium | Often 0 contamination posts -- expected variance |
| 3 | r/mycology | Low for contam | Mostly wild ID requests |

### Search query

```
"contamination OR trich OR cobweb OR mold OR bacteria"
```

Subs searched: r/mushroomgrowing, r/MushroomGrowers, r/unclebens, r/mycology.

r/contamfam is fetched via hot posts (not search) because it is contamination-dedicated.

---

## Fetching Posts

### Preferred: bundled parser script

```bash
python3 scripts/reddit-fetch-parser.py --out ~/reddit-feeds/raw/contamination-fetch.md --days 7
```

### Manual single-sub fetch

```bash
curl -s -A "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0" \
  "https://www.reddit.com/r/ContamFam/new.json?limit=25" \
  -o /tmp/reddit_cf.json
```

**Endpoint preference:** Use `new.json` as the default. Contamination posts are transient -- recency matters. `hot.json` can surface posts that are days old. Only fall back to `hot.json` if a sub has low posting frequency.

**User-Agent:** Must look like a real browser. Generic "curl" or "Bot" strings get 403.

**Rate limits:** Reddit rate-limits unauthenticated JSON GETs generously but not infinitely. Space calls across subs.

### Parsing posts (Python)

```python
import json
from datetime import datetime, timezone

def parse_posts(path, subreddit_name):
    with open(path) as f:
        data = json.load(f)
    posts = []
    for child in data.get('data', {}).get('children', []):
        p = child['data']
        posts.append({
            'subreddit': subreddit_name,
            'title': p['title'],
            'author': p['author'],
            'score': p['score'],
            'num_comments': p['num_comments'],
            'selftext': p.get('selftext', '')[:500],
            'url': p['url'],
            'permalink': 'https://www.reddit.com' + p['permalink'],
            'created_utc': datetime.fromtimestamp(
                p['created_utc'], tz=timezone.utc
            ).isoformat(),
        })
    return posts
```

### Crosspost filtering

The Reddit search endpoint returns many crossposts from unrelated subs. Always filter on `subreddit == target` after parsing.

---

## Fetching Comments

Use comments when the post selftext is ambiguous, grower diagnosis is uncertain, or community consensus is needed.

```bash
curl -s -A "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0" \
  "https://www.reddit.com/comments/<POST_ID>.json" \
  -o /tmp/reddit_cmts_<POST_ID>.json
```

Response is a 2-element array:
- `data[0]` -- post data
- `data[1]` -- comments list

```python
comments = data[1]['data']['children']
for cmt in comments:
    if cmt['kind'] == 't1':
        author = cmt['data']['author']
        body = cmt['data']['body']
```

Most contamination posts resolve in the top 3 comments. Deep threading is rarely needed.

---

## Gallery Image Extraction

Gallery posts expose no direct image URL in the standard `url` field. Use the `/comments/<post_id>.json` endpoint:

```python
import json, html

def extract_gallery_urls(post_data):
    urls = []
    if post_data.get("is_gallery"):
        meta = post_data.get("media_metadata", {})
        for img_id, info in meta.items():
            src = info.get("s", {}).get("u", "")
            if src:
                # CRITICAL: unescape HTML entities
                src = html.unescape(src)
                urls.append(src)
    else:
        urls = [post_data.get("url", "")]
    return urls
```

### Critical pitfall: HTML-escaped URLs

Reddit's JSON returns gallery preview URLs with `&amp;` instead of `&` in query parameters. Passing the raw JSON URL to download tools produces 403/404 because the URL contains literal `&amp;`.

**Always `html.unescape()` before using gallery URLs.**

---

## Pipeline Health Diagnostics

### Symptoms and checks

**Fetch file exists but contains only old data:**
- Check file mtime: `ls -la reddit-feeds/raw/contamination-fetch*.md`
- The AM fetch typically runs around 10:00 UTC

**Fetch file is recent but no new images downloaded:**
- Check for image URLs in fetch: `grep -c "i.redd.it" fetch.md`
- If URLs exist but no images, the image-download phase failed silently

**Both fetch and images are stale (>48h):**
- Check cron job last run time
- Bridge manually (see below)

### Known failure patterns

| Pattern | Cause | Fix |
|---------|-------|-----|
| Text fetch runs, images don't | Image download phase fails silently or rate-limited | Re-run parser manually |
| Fetch was manual but cron didn't fire | Cron disabled during migration | Re-enable or recreate cron |
| Files written to stale path | Parser `--out` hardcoded to old path | Update parser default |
| `read_file` fails on existing file | Agent cwd mismatch | Use absolute paths |
| Image directory permanently empty | Downloader is completely broken | Manual curl fallback for `i.redd.it` posts |
| Duplicate PM entries in index | Same batch appended twice | Check section headers before appending |

---

## Manual Fallback When Pipeline Stalls

If the automated pipeline is stalled (newest fetch file is older than 48 hours):

1. Fetch raw JSON directly using the parser script or manual curl commands
2. Parse with Python, filter by `created_utc` (last 7 days)
3. Fetch comment threads for novel or ambiguous posts
4. Filter out crossposts
5. Save to `reddit-feeds/raw/contamination-fetch.md` with a staleness note:
   ```
   # Contamination Reddit Fetch -- <DATE>
   # Manual fetch: pipeline stalled, last automated file <LAST_DATE>
   ```
6. Download images manually for posts with `i.redd.it` or gallery URLs
7. Create the directory structure if missing: `mkdir -p ~/reddit-feeds/raw/`

**This fallback is a bridge, not a replacement.** Flag the pipeline stall so the root cause can be fixed.

---

## Post Classification (Keyword Buckets)

For broader mycology fetches beyond contamination monitoring:

| Bucket | Keywords / Signals |
|--------|-------------------|
| Ecology | Wild find, burn zone, habitat, foraging |
| Technique | "tek", "hack", "DIY", "clone", "monotub" |
| Strain behavior | Specific species or strain names |
| Citizen science | DNA sequencing, ID request with location |
| Slime mold | Physarum, Lycogala, Fuligo, myxomycete |
| Phenotypic variation | "yellow pins", "weird cap", "albino" |
| Misidentification | "mold?", "contam?", "is this bad?" |

Posts matching the misidentification bucket are the highest-value training data for vision model development.

---

## Deep-Dive Criteria

Fetch full comment threads when:
- Score >20 AND comments >5 (high community signal)
- Contains novel technique
- Expert-level differential diagnosis in comments
- Cross-disciplinary content
