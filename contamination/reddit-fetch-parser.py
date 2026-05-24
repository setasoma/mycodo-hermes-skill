#!/usr/bin/env python3
# MIT License
#
# Copyright (c) 2026 mycodo-hermes-skill contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Reddit Contamination Fetch + Parse Script
Fetches new.json from target subreddits, filters by recency/keywords,
writes a formatted markdown fetch file. Intended for automated pipeline gap-fills.

Usage:
  python reddit-fetch-parser.py [--out /path/to/contamination-fetch.md] [--days 7]

Behavior:
1. Fetches new.json from: ContamFam, MushroomGrowers, mycology, unclebens, mushroomgrowing
2. Reddit ContamFam: ALL posts in window (sub is contamination-dedicated)
   Other subs: keyword filter (contam/mold/trich/cobweb/bacter/bruise/wet rot/etc.)
3. Writes a single markdown file with the standard contamination-fetch header format.
4. User-Agent must look like a real browser (Reddit returns 403 otherwise).

Pitfalls:
- execute_code sandbox is NOT persistent across calls; you must do fetch+parse+write
  in a single script execution, or pass JSON between calls as arguments.
- Reddit rate-limits unauthenticated GETs. Space fetches; do not loop-aggressive.
- Gallery posts lack direct image URLs in JSON API — catalog as metadata-only.
"""
import json, os, subprocess, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:136.0) Gecko/20100101 Firefox/136.0"

# Default output path — override with --out
DEFAULT_OUT = os.path.join(
    os.environ.get("HOME", os.path.expanduser("~")),
    "mycodo", "contamination-data", "contamination-fetch.md"
)

# Subreddits to fetch: (display_name, endpoint_path, limit)
SUBS = [
    ("ContamFam",        "r/ContamFam/new.json?limit=30",        30),
    ("MushroomGrowers",  "r/MushroomGrowers/new.json?limit=25",  25),
    ("mycology",         "r/mycology/new.json?limit=25",         25),
    ("unclebens",        "r/unclebens/new.json?limit=15",        15),
    ("mushroomgrowing",  "r/mushroomgrowing/new.json?limit=15",  15),
]

# Keyword filter applied to non-ContamFam subs
KEYWORDS = [
    "contam", "mold", "trich", "cobweb", "bacter", "bruise", "wet rot", "yellow",
    "green", "infect", "toss", "safe to", "bad", "fucked",
    "dry rot", "sour", "slimy", "fuzzy", "white fuzz", "dust", "powdery",
    "smell", "odor", "stink", "gnat", "mite", "insect", "pest", "blue oyster",
    "grey", "gray", "black spot", "dark spot", "spikey",
    "discolor", "spot", "slime", "off", "weird", "odour", "metabolite",
    "overlay", "overlayed", "overlaying", "stalled", "stalled growth",
    "stalled pin", "stalled pins", "abort", "aborting", "aborted",
    "mycelium piss", "myc piss", "piss", "exudate", "ooze", "oozing",
    "slurry", "soup", "wet spot", "wet spots", "crust", "crusting",
    "hollow", "hollowing", "hollowed", "mushy", "mushiness", "watery",
    "saturated", "drenched", "soggy", "sopping", "pooling", "pooled",
    "standing water", "condensation", "drip", "dripping", "dripped",
]


def curl_json(url, out_path):
    cmd = ["curl", "-s", "-A", USER_AGENT, url, "-o", out_path]
    subprocess.run(cmd, capture_output=True)


def parse_posts(path, sub_name, include_all=False):
    posts = []
    with open(path) as f:
        data = json.load(f)
    for child in data.get('data', {}).get('children', []):
        p = child['data']
        posts.append({
            'subreddit': sub_name,
            'title': p['title'],
            'author': p['author'],
            'score': p['score'],
            'num_comments': p['num_comments'],
            'selftext': p.get('selftext', ''),
            'url': p.get('url', ''),
            'permalink': 'https://www.reddit.com' + p['permalink'],
            'created_utc': p['created_utc'],
            'is_gallery': p.get('is_gallery', False),
        })
    return posts


def fetch_all(tmp_dir):
    os.makedirs(tmp_dir, exist_ok=True)
    for name, endpoint, limit in SUBS:
        url = f"https://www.reddit.com/{endpoint}"
        curl_json(url, os.path.join(tmp_dir, f"{name}.json"))
    return tmp_dir


def build_report(tmp_dir, days=7):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []

    # ContamFam: include ALL posts (keyword filter not needed)
    cf_posts = parse_posts(os.path.join(tmp_dir, "ContamFam.json"), "ContamFam")
    for p in cf_posts:
        created = datetime.fromtimestamp(p['created_utc'], tz=timezone.utc)
        if created >= cutoff:
            all_posts.append(p)

    # Other subs: keyword filter
    for name, _, _ in SUBS[1:]:
        path = os.path.join(tmp_dir, f"{name}.json")
        if not os.path.exists(path):
            continue
        for p in parse_posts(path, name):
            created = datetime.fromtimestamp(p['created_utc'], tz=timezone.utc)
            if created < cutoff:
                continue
            combined = (p['title'] + ' ' + p['selftext']).lower()
            if any(kw in combined for kw in KEYWORDS):
                all_posts.append(p)

    # Deduplicate by permalink
    seen = {}
    unique = []
    for p in all_posts:
        if p['permalink'] not in seen:
            seen[p['permalink']] = True
            unique.append(p)

    unique.sort(key=lambda x: x['created_utc'], reverse=True)
    return unique


def render_markdown(posts, fetch_time_utc):
    lines = [
        f"# Contamination Reddit Fetch — {fetch_time_utc.strftime('%B %d, %Y')}",
        "# Sources: r/ContamFam (new), r/MushroomGrowers (new), r/mycology (new), r/unclebens (new), r/mushroomgrowing (new)",
        "",
        "---",
        "",
    ]

    for sub in ["ContamFam", "MushroomGrowers", "mycology", "unclebens", "mushroomgrowing"]:
        sub_posts = [p for p in posts if p['subreddit'] == sub]
        lines.append(f"## {sub} — new.json (last 7 days)")
        lines.append("")
        if not sub_posts:
            lines.append("No posts matching filter in last 7 days.")
            lines.append("")
            continue
        for i, p in enumerate(sub_posts, 1):
            lines.append(f"**{i}. \"{p['title'][:90]}{'...' if len(p['title']) > 90 else ''}\"**")
            lines.append(f"- Author: {p['author']} | Score: {p['score']} | Comments: {p['num_comments']}")
            lines.append(f"- {p['url']}")
            if p['selftext']:
                snip = p['selftext'].replace('\n', ' ').replace('\r', '')[:400]
                lines.append(f"- Selftext: {snip}{'...' if len(p['selftext']) > 400 else ''}")
            lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Reddit contamination fetch + parse")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output markdown path")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    args = parser.parse_args()

    tmp_dir = "/tmp/reddit_fetch_script_tmp"
    fetch_all(tmp_dir)
    posts = build_report(tmp_dir, days=args.days)
    md = render_markdown(posts, datetime.now(timezone.utc))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, 'w') as f:
        f.write(md)

    print(f"Wrote {len(posts)} posts to {args.out} ({len(md)} chars)")


if __name__ == "__main__":
    main()
