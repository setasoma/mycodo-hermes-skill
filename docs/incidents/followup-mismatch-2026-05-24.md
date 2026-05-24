# Follow-Up Flag Path Mismatch Incident -- 2026-05-24

## Summary

The tent reached 99.91% humidity because the follow-up verification system was completely non-functional. The decision engine and the follow-up wrapper script used different file paths for the follow-up flag, meaning the wrapper never found the flag and the follow-up checker was never invoked.

---

## The Bug

| Component | Flag Path | Status |
|-----------|-----------|--------|
| `mycodo-decision.py` | `~/.mycodo-skill-followup` | Correct |
| `mycodo-followup-wrapper.sh` line 6 | `/tmp/mycodo-skill-followup` | **Wrong** |

The wrapper looked in `/tmp`, but the engine wrote to `$HOME`. The wrapper always found no flag, exited silently with exit code 0, and the follow-up checker was never reached.

---

## Timeline

| Time | Event |
|------|-------|
| 12:07 PM | Decision engine reads humidity 68.66%, turns humidifier ON (correct) |
| 12:08 PM | Engine writes flag to `~/.mycodo-skill-followup` |
| 12:10 PM | Follow-up cron runs, checks `/tmp/mycodo-skill-followup`, not found, exits 0 silently |
| 12:17 PM | Follow-up cron runs, checks `/tmp/...`, not found, exits 0 silently |
| 12:20 PM | Follow-up cron runs, checks `/tmp/...`, not found, exits 0 silently |
| 12:10-12:23 | Humidity climbs from 68.66% to 99.91%. Humidifier remains ON. Fan remains OFF. |
| 12:23 PM | Operator manually discovers tent fully saturated. Forces fan ON + humidifier OFF. |
| 12:24 PM | Follow-up wrapper path patched from `/tmp` to `$HOME` |

---

## Why Both Safety Layers Failed Simultaneously

The system has two layers of humidity safety:

| Layer | Trigger | Why It Failed |
|-------|---------|---------------|
| Decision engine guard | humidity >= 95% AND humidifier ON | Next scheduled run was 12:30 PM (23 min away). Overshoot reached 99% in 13 min. |
| Follow-up velocity warning | Humidity rose >25-30% since last action | Wrapper never found the flag, so the checker was never invoked. |

---

## Fix

Line 6 of `mycodo-followup-wrapper.sh`:

```bash
# BEFORE (broken)
FLAG=/tmp/mycodo-skill-followup

# AFTER (fixed)
FLAG="$HOME/.mycodo-skill-followup"
```

### Verification

Post-fix manual run:
```bash
bash mycodo-followup-wrapper.sh
# -> Detected $HOME/.mycodo-skill-followup
# -> Ran mycodo-followup-check.py
# -> Correctly reported: "GUARD: humidity 100.0% >= 93%"
# -> Exit code 2 (alert state)
```

---

## Why `$HOME` Is Correct

- The decision engine runs as the user and writes to `~/.mycodo-skill-followup`
- The wrapper runs under the same user account via cron
- `/tmp` is unreliable: it can be cleaned by `tmpwatch`, `systemd-tmpfiles`, or reboots
- `$HOME` is persistent, user-specific, and survives reboots

---

## Ignored Operator Signals

The operator had previously questioned whether the follow-up system was working. The agent incorrectly reassured from memory instead of investigating. When an operator expresses doubt about a safety mechanism, the agent must verify it empirically (read the code, run a test) rather than reassure from recall.

---

## Prevention

When a safety mechanism has two components communicating via a flag file, always audit both the writer and the reader:

1. Find the write line in the engine: `grep "followup-needed" mycodo-decision.py`
2. Find the read line in the wrapper: `grep "followup-needed" mycodo-followup-wrapper.sh`
3. Compare the paths character-for-character
4. If they differ, fix immediately and verify with a manual run

### General rule

If a cron job exits silently on "expected" no-op conditions, verify that the no-op trigger is actually correct. A silent exit is indistinguishable from a masked failure.
