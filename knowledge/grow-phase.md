# Grow Phase — Lion's Mane (Hericium erinaceus)

**CURRENT_PHASE: fruiting**
**Species: Lion's Mane**
**Substrate: Sawdust block (hardwood)**

---

## How to change phase

Tell the agent: "Update grow-phase.md — change CURRENT_PHASE to [phase name]"
Or edit this file directly — change the CURRENT_PHASE line above.

Valid phases: `colonization` | `primordia` | `fruiting`

---

## Phase 1: COLONIZATION (current)

Mycelium is growing through the substrate. High CO2 is normal and beneficial — the mycelium thrives in CO2-rich, low-oxygen environments. Do NOT panic about high CO2.

| Parameter | Ideal | Acceptable | Alert (act) |
|-----------|-------|------------|-------------|
| Temp | 21-24°C | 18-26°C | <16°C or >28°C |
| Humidity | 85-95% | 80-95% | <75% |
| CO2 | 2000-5000 ppm (normal) | up to 8000 ppm | >10000 ppm |

**Fan rules — colonization:**
- Fan is OFF by default. High CO2 is expected and beneficial.
- Fire fan_burst 360 ONLY if CO2 exceeds 10000 ppm (anaerobic risk) or humidity exceeds 98% (condensation/contamination risk).
- Humidity floor still applies: do NOT fire fan if humidity < 80%.
- Purpose of fan during colonization: prevent anaerobic conditions and extreme condensation ONLY. Not for CO2 management.

**What to watch for:**
- Contamination (green/black/orange discoloration on camera)
- Temp swings >5°C within 6 hours
- Humidity consistently below 80% (substrate drying)

---

## Phase 2: PRIMORDIA (pinning initiation)

Transition phase. Environmental shock triggers pin formation. Temperature drop + fresh air + light signal the mycelium to fruit.

| Parameter | Ideal | Acceptable | Alert (act) |
|-----------|-------|------------|-------------|
| Temp | 15-18°C | 13-20°C | <10°C or >22°C |
| Humidity | 90-95% | 85-97% | <85% |
| CO2 | 500-800 ppm | <1000 ppm | >1200 ppm |

**Fan rules — primordia:**
- Fan authority is ACTIVE. Fresh air exchange is critical to trigger pinning.
- Fire fan_burst 360 if CO2 > 800 ppm.
- Fire fan_burst 360 if CO2 > 1000 ppm and note "repeat burst likely needed."
- Humidity floor: do NOT fire fan if humidity < 85%.
- After fan burst, monitor humidity recovery. If humidity drops below 87% post-burst, note for the operator.

**What to watch for:**
- Small white bumps forming on substrate surface (primordia — good!)
- Yellowing or browning of early pins (too dry or too much airflow)
- No pins after 7 days at primordia conditions (may need stronger cold shock)

---

## Phase 3: FRUITING

Active mushroom growth. Requires high humidity, cool temps, and very low CO2. Fresh air exchange is the #1 priority after humidity.

### LATE-STAGE FRUITING EXCEPTION (days to 1 week remaining, large fruiting bodies)

**CO2 control is THE priority. Humidity is secondary.**

This exception supersedes all standard fruiting fan rules below during late-stage fruiting.

| Parameter | Late-Stage Priority | Why |
|-----------|---------------------|-----|
| CO2 | **CRITICAL** — keep <800 ppm, vent continuously | Too much CO2 stops growth entirely, cannot recover |
| Humidity | **Secondary** — manually rehumidified by operator | Low humidity just dries out, is fixable with misting |

**Fan rules — late-stage fruiting:**
- Fan stays ON continuously unless operator explicitly directs OFF.
- NEVER autonomously turn fan OFF for humidity during this phase.
- Operator manually rehumidifies on the regular.
- Standard humidity floor rules ("do NOT fire fan if humidity <88%") are SUSPENDED.
- Rationale: Lack of humidity = dries out a bit (fixable). Too much CO2 = growth aborts (not fixable).

### Standard Fruiting Rules (early-to-mid fruiting, does NOT apply to late-stage)

| Parameter | Ideal | Acceptable | Alert (act) |
|-----------|-------|------------|-------------|
| Temp | 16-18°C | 15-21°C | <12°C or >24°C |
| Humidity | 90-95% | 85-95% | <85% |
| CO2 | 400-600 ppm | <800 ppm | >1000 ppm |

**Fan rules — fruiting:**
- Fan authority is ACTIVE. CO2 management is critical — Lion's Mane is very sensitive to CO2 during fruiting.
- Fire fan_burst 360 if CO2 > 800 ppm.
- Fire fan_burst 360 if CO2 > 1000 ppm and note "critical — repeat burst needed."
- If humidity > 98%, fire a burst to vent excess (condensation/contamination risk).
- Humidity floor: do NOT fire fan if humidity < 88%. Preserving humidity is priority.
- After burst, expect 3-5% humidity drop. Monitor recovery.

**What to watch for:**
- Coral-like branching growth (healthy Lion's Mane development)
- Yellowing tips (too dry or too warm)
- Short, stubby spines that stop elongating (CO2 too high — need more FAE)
- Pink/brown discoloration (bacterial contamination)

---

## Notes

- The operator is manually humidifying this round. The agent does NOT have humidifier control yet.
- Fan is the only actuator the agent controls (exhaust fan via Mycodo relay).
- Always use fan_burst over fan_on — auto-off prevents orphaned fan states.
- When in doubt about phase, ASK the operator. Do not assume phase transitions.
