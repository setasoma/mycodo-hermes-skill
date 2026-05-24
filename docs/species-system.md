# Mycodo Hermes Skill Species Configuration System

The decision engine is species-agnostic. Species-specific phase thresholds and fruiting parameters are defined as self-contained YAML files under `species/`. No code changes are needed to add a new species.

---

## Available Species

| Species ID | Name | Notes |
|---|---|---|
| `lions_mane` | Lion's Mane (Hericium erinaceus) | Culinary + neuroprotective research |
| `oyster` | Pearl Oyster (Pleurotus ostreatus) | Fast, aggressive, beginner-friendly |
| `shiitake` | Shiitake (Lentinula edodes) | Browning phase, cold shock, flavor complexity |
| `reishi` | Reishi (Ganoderma lucidum) | Medicinal; CO2-driven morphology (antler vs conk) |
| `turkey_tail` | Turkey Tail (Trametes versicolor) | Lower humidity, aggressive colonization |
| `maitake` | Maitake / Hen of the Woods (Grifola frondosa) | Cold shock required, dense clusters |

Each YAML defines the same 5 standard grow phases with species-specific thresholds: `colonization`, `primordia`, `fruiting`, `late-stage-fruiting`, `rest`. Some species add extra phases (see Species-Specific Oddities below).

---

## Usage

### Decision engine with species

```bash
# Evaluate against oyster thresholds instead of lion's mane
python3 scripts/mycodo-decision.py --species oyster --phase fruiting --execute --camera --html

# Auto-detect phase from state file + sensor trends
python3 scripts/mycodo-decision.py --species lions_mane --auto-phase --execute

# Without --species: defaults to lions_mane (backward compatible)
python3 scripts/mycodo-decision.py --phase fruiting --execute

# List available species
python3 -c "from species_loader import list_available_species; print(list_available_species())"

# Load and inspect a species
python3 -c "from species_loader import load_species, get_phase; d = load_species('shiitake'); p = get_phase(d, 'fruiting'); print(p['targets']['temperature'])"
```

### Adding a new species

1. Copy any existing YAML from `species/`
2. Edit thresholds to match the species' published grow parameters
3. Ensure all 5 standard phases are defined
4. Drop the file in `species/<species_id>.yaml`
5. No code changes needed -- the loader auto-discovers it

---

## YAML Structure (v1.0)

Each species file contains:

```yaml
schema_version: "1.0"
species_id: lions_mane
common_name: Lion's Mane
scientific_name: Hericium erinaceus

phases:
  colonization:
    label: Colonization
    description: Mycelium growing through substrate.
    duration_estimate: 14-21        # days, used for transition timing
    transition_trigger: manual      # auto | manual
    targets:
      temperature:
        ideal_min: 21
        ideal_max: 24
        accept_min: 18
        accept_max: 26
        alert_min: 16
        alert_max: 28
      humidity:
        ideal_min: 85
        ideal_max: 95
        accept_min: 80
        accept_max: 95
        alert_min: 75
        alert_max: 98
      co2:
        ideal_min: 2000
        ideal_max: 5000
        accept_min: 0
        accept_max: 8000
        alert_min: 0
        alert_max: 10000
    fan_rules:
      authority: false
      mode: off                     # off | burst | continuous | monitor
      burst_duration: 360
      humidity_floor: 80
      co2_trigger: 10000
      co2_critical: 15000
    humidifier_rules:
      active: true
      humidity_target: 90
      deadband_low: 85
      deadband_high: 95
    notes: Fan OFF by default during colonization.

  # ... primordia, fruiting, late-stage-fruiting, rest phases follow same structure

sensor_authority:
  temperature: sht45
  humidity: sht45
  co2: scd41

safety:
  oversaturation_guard_rh: 98
  max_temp: 28
  min_temp: 10
  sensor_offline_minutes: 30
```

### Key fields

- `duration_estimate` -- days, can be a range string like `"7-14"` (loader averages internally)
- `transition_trigger` -- `"auto"` allows phase auto-transition; `"manual"` requires operator action
- `targets` -- each metric has `ideal_min/max`, `accept_min/max`, `alert_min/max`
- `fan_rules.authority` -- whether the engine can control the fan in this phase
- `humidifier_rules.active` -- whether humidifier logic runs in this phase

---

## Phase Key Normalization

The loader normalizes all phase names to `snake_case` internally. You can use any of these input formats in YAML:

- `fruiting` -> `fruiting`
- `late-stage-fruiting` -> `late_stage_fruiting`
- `Late Stage Fruiting` -> `late_stage_fruiting`
- `Fruiting` -> `fruiting`

---

## The Inactive Phase

When the tent is empty after harvest, cleaning, or waiting for a new grow cycle, use the `inactive` phase:

```yaml
  inactive:
    label: Inactive / No Blocks
    description: Tent cleaned, blocks removed. No active grow. All actuators OFF.
    duration_estimate: null
    transition_trigger: manual
    targets:
      temperature:
        ideal_min: null
        ideal_max: null
        accept_min: null
        accept_max: null
        alert_min: null
        alert_max: null
      humidity:
        # ... all null
      co2:
        # ... all null
    fan_rules:
      authority: false
      mode: nil
      reason: No blocks -- operator manual control only
    humidifier_rules:
      authority: false
      mode: nil
      reason: No blocks -- operator manual control only
    notes:
      - ALL ACTUATORS are MANUAL. Decision engine will never touch relays.
      - Use for cleaning, drying, waiting for next grow cycle.
      - Auto-phase will NOT transition out of inactive.
```

### Cron deployment

After harvest:
```bash
python3 scripts/mycodo-decision.py --species lions_mane --phase inactive --camera --html --html-dir ~/reports/
```

No `--execute` is needed (relays will not fire anyway), but include it for consistency.

### Resuming a new grow

1. Reset phase tracker: `python3 scripts/transition_detector.py --init <species> colonization`
2. Update cron to `--phase colonization --species <name> --auto-phase --execute --camera`

---

## Null Threshold Handling

Phases like `inactive` set all thresholds to `null`. This requires null-safety guards at three levels:

1. **`species_loader.assess()`** -- returns `"unmonitored"` when all thresholds are `None`, instead of attempting float comparisons
2. **`species_loader.load_species()`** -- builds target dicts with `None` keys for missing metrics
3. **`mycodo-decision.py`** -- guards every threshold comparison with `is not None` checks before comparing

The Python pitfall: `.get(key, default)` returns `None` (the stored value) rather than the default when the key exists but has value `None`. Always check explicitly:

```python
if t_rules.get("alert_min") is not None and temp < t_rules["alert_min"]:
    alerts.append(f"Temperature {temp}C below threshold")
```

### Default injection for missing keys

The loader injects defaults for missing (not null-valued) dictionary keys:

| Key | Default |
|-----|---------|
| `fan_rules.co2_trigger` | 1200 |
| `fan_rules.co2_critical` | 2000 |
| `fan_rules.humidity_floor` | 88 |
| `fan_rules.burst_duration` | 30 |
| `humidifier_rules.humidity_target` | 92 |
| `humidifier_rules.deadband_low` | 85 |
| `humidifier_rules.deadband_high` | 98 |

---

## Species-Specific Oddities

- **Shiitake** has a 6th phase: `browning` -- brown metabolites form on block surface before primordia. Also requires a cold water soak for pinning.
- **Reishi** has `antler_development` -- CO2 > 2000 ppm produces antler form; low CO2 produces shelf conks. Extremely long cycle.
- **Maitake** requires cold shock (drop 5-10C) for pinning. Auto-transition handles the timing but the operator must trigger the physical temperature change.
- **Turkey Tail** tolerates much lower humidity during colonization than Lion's Mane.
- **Oyster** has higher colonization temps (24-28C), shorter fruiting window, and continuous fan in late stage to manage spore load.

---

## Key Differences by Species

| Parameter | lions_mane | oyster | shiitake | reishi |
|-----------|-----------|--------|----------|--------|
| Colonization temp | 21-24C | 24-28C | 20-24C | 24-28C |
| Fruiting temp | 17-19C | 15-20C | 12-18C | 20-26C |
| Extra phases | none | none | browning, shocking | antler_development |
| Auto-transition support | primordia->fruiting, fruiting->late-stage | same | fruiting->late-stage only | primordia->fruiting, fruiting->late-stage |

---

## Backward Compatibility

If `--species` is omitted or the species YAML is not found, the engine falls back to legacy `phase_config.py` with a stderr warning. No existing cron job needs updating unless you want a different species.

### Transition triggers by species

| Phase | lions_mane | oyster | shiitake | reishi |
|-------|-----------|--------|----------|--------|
| colonization | manual | manual | manual | manual |
| primordia | manual | manual | manual | manual |
| fruiting | auto | auto | auto | auto |
| late-stage | auto | auto | manual | auto |
| rest | manual | manual | manual | manual |

Manual transitions require physical operator action (bag cutting, shocking, rehydration). Auto transitions depend on time-in-phase plus sensor patterns.
