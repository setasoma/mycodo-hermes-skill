#!/bin/bash
# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# License: MIT
#
# mycodo-followup-wrapper.sh — Cron wrapper for adaptive follow-up checks
# Only runs mycodo-followup-check.py if a follow-up flag exists and wait time has passed.
# Exits silently if no follow-up needed.

MYCODO_SKILL_BASE="${MYCODO_SKILL_BASE:-$HOME/.mycodo}"
FLAG="$HOME/.mycodo-skill-followup"
LOG=/tmp/mycodo-skill-followup-log.jsonl
SCRIPT="${MYCODO_SKILL_BASE}/scripts/mycodo-followup-check.py"

if [ ! -f "$FLAG" ]; then
    exit 0
fi

# followup-check.py handles its own timing — just call it
python3 "$SCRIPT" --clear 2>&1
EXIT=$?

if [ $EXIT -ne 0 ]; then
    # Problem detected — let the agent handle the alert
    echo "Follow-up check detected issue (exit $EXIT). Latest log:"
    tail -1 "$LOG" 2>/dev/null || echo "(no log)"
    exit $EXIT
fi

exit 0
