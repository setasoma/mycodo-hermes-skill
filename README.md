# Mycodo Hermes Skill

Autonomous mushroom cultivation management for AI agents. This is a [Hermes](https://github.com/NousResearch/hermes-agent) agent skill that monitors environmental sensors and controls actuators on a Raspberry Pi running [Mycodo](https://github.com/kizniche/Mycodo) and InfluxDB. It operates on a 30-minute decision cycle: read sensors, evaluate against species-specific thresholds, fire relays, and verify results.

Built and tested over two complete Lion's Mane grow cycles (colonization through harvest).

## Features

- **30-minute autonomous decision cycle** -- sensor fetch, threshold evaluation, actuator control, verification, and HTML reporting in a single pass
- **Species-agnostic** -- six gourmet species included (Lion's Mane, Oyster, Shiitake, Reishi, Turkey Tail, Maitake) with per-phase YAML configs; add new species with zero code changes
- **Six cultivation phases per species** -- colonization, primordia, fruiting, late-stage-fruiting, rest, inactive
- **Auto-phase transitions** with confidence scoring based on sensor trend analysis
- **Safety systems** -- oversaturation guard, 10-minute follow-up verification, operator override, dry-run mode
- **HTML reports** with embedded camera snapshots, delivered via Telegram screenshots
- **Contamination intelligence** (optional) -- Reddit-sourced pattern database with 180+ cataloged entries

## Hardware Requirements

| Component | Details |
|---|---|
| Raspberry Pi 4 | 8 GB recommended, running Mycodo + InfluxDB 2.x |
| SHT45 sensor | Temperature + humidity (±0.1°C, ±1% RH) |
| SCD41 sensor | CO2 monitoring |
| Exhaust fan | Relay-controlled via GPIO17 |
| Humidifier | Relay-controlled via GPIO5 (DLI IoT Power Relay v2) |
| USB webcam | Optional, for visual monitoring (e.g., Logitech C920x) |
| Network | Tailscale mesh or any IP connectivity between agent host and Pi |

## Software Requirements

- [Hermes agent framework](https://github.com/NousResearch/hermes-agent)
- Python 3.9+
- PyYAML
- `curl`, `jq` (optional, for manual sensor queries)
- Firefox (optional, for HTML report screenshots)

## Repository Structure

```
mycodo-hermes-skill/
├── SKILL.md                    # Hermes skill definition
├── LICENSE                     # MIT
├── CONTRIBUTING.md
├── requirements.txt
├── mycodo_skill/               # Python modules
│   ├── decision_engine.py      # Core decision engine
│   ├── species_loader.py       # YAML species config loader
│   ├── transition_detector.py  # Auto-phase transitions
│   ├── phase_detector.py       # Phase classification from sensors
│   ├── phase_config.py         # Legacy Lion's Mane fallback
│   ├── followup_checker.py     # 10-min follow-up verifier
│   └── verify_actuator.py      # Testing utility
├── scripts/                    # Shell scripts
│   ├── sensor-query.sh         # Mycodo/InfluxDB/camera gateway
│   ├── mycodo-followup-wrapper.sh
│   └── archive-grow-cycle.sh
├── species/                    # Species threshold configs (YAML)
│   ├── lions_mane.yaml
│   ├── oyster.yaml
│   ├── shiitake.yaml
│   ├── reishi.yaml
│   ├── turkey_tail.yaml
│   └── maitake.yaml
├── knowledge/                  # Grow knowledge base
├── docs/                       # Reference documentation
│   ├── architecture.md
│   ├── pitfalls.md
│   ├── incidents/
│   └── templates/
│       ├── sensor-creds.env.example
│       ├── mycodo-skill-override.json.example
│       ├── species-config.yaml
│       └── tent-status-report.html
├── contamination/              # Optional module
│   ├── README.md
│   └── reddit-fetch-parser.py
└── examples/
    ├── crontab.example
    └── hermes-cron.example
```

## Quick Start

1. **Install the Hermes agent framework** following the instructions at [github.com/NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

2. **Clone this repo into the Hermes skills directory:**
   ```bash
   cd /path/to/hermes/skills
   git clone https://github.com/YOUR_USERNAME/mycodo-hermes-skill.git
   ```

3. **Install the Python dependency:**
   ```bash
   pip install PyYAML
   ```

4. **Configure sensor credentials.** Copy the template and fill in your Mycodo/InfluxDB connection details:
   ```bash
   mkdir -p ~/.mycodo
   cp docs/templates/sensor-creds.env.example ~/.mycodo/sensor-creds.env
   ```
   Edit `~/.mycodo/sensor-creds.env` with your Pi's IP address, InfluxDB token, and Mycodo API key.

5. **Test sensor connectivity:**
   ```bash
   bash scripts/sensor-query.sh quick
   ```

6. **Run a dry-run decision** to verify the full pipeline without firing actuators:
   ```bash
   python3 mycodo_skill/decision_engine.py --species lions_mane --phase fruiting
   ```

7. **Set up cron jobs in Hermes.** See `examples/hermes-cron.example` for the recommended 30-minute cycle and 10-minute follow-up schedule.

## Architecture

Each 30-minute cycle executes a 10-stage pipeline:

```
1. SENSOR FETCH        Queries Mycodo API and InfluxDB for current readings
        │
2. CSV PARSE           Normalizes sensor data into a standard format
        │
3. SPECIES LOAD        Loads the active species YAML config
        │
4. PHASE RESOLUTION    Determines the current cultivation phase
        │
5. SAFETY GUARDS       Checks oversaturation limits and boundary conditions
        │
6. OVERRIDE CHECK      Looks for operator overrides (mycodo-skill-override.json)
        │
7. DECISION BUILD      Compares readings against phase thresholds
        │
8. EXECUTION           Fires relay commands (fan, humidifier) via Mycodo GPIO
        │
9. HTML REPORT         Generates a status report with embedded camera snapshot
        │
10. FOLLOW-UP          Separate 10-min cron verifies actuator results
```

The decision engine evaluates temperature, humidity, and CO2 against species- and phase-specific thresholds defined in the YAML configs. When readings fall outside acceptable ranges, it determines the appropriate actuator response, applies safety guards, and executes relay commands through the Mycodo API.

The follow-up checker (`followup_checker.py`) runs on a separate 10-minute cron schedule. It re-reads sensors to confirm that actuator actions produced the expected environmental change. If conditions have not improved, it logs a warning for the next decision cycle.

## Adding a New Species

Create a new YAML file in `species/` using the provided template:

```bash
cp docs/templates/species-config.yaml species/your_species.yaml
```

Each YAML file defines thresholds for all six cultivation phases (temperature, humidity, CO2, fan duration, misting duration). No code changes are required. The species loader discovers configs by filename at runtime.

See `species/lions_mane.yaml` for a complete working example.

## Operator Override

To temporarily override automated decisions, create a JSON file at the path specified in your configuration:

```bash
cp docs/templates/mycodo-skill-override.json.example ~/.mycodo/mycodo-skill-override.json
```

The override file supports forcing specific actuator states, skipping the current cycle, or locking a particular phase. The decision engine checks for an active override at stage 6 of every cycle and respects it until the file is removed or its expiration time passes.

## Contamination Intelligence (Optional)

The `contamination/` directory contains tooling for building a contamination pattern database from Reddit grow communities. This module is entirely optional and operates independently from the core decision engine. See `contamination/README.md` for setup instructions.

## Acknowledgments

This project builds on [Mycodo](https://github.com/kizniche/Mycodo), an open-source environmental monitoring and regulation system created by [Kyle Gabriel](https://github.com/kizniche). Mycodo provides the sensor input infrastructure, relay control, and REST API that this skill depends on. The project name is a direct reference to it.

Mycodo is licensed under the Gnu General Public License v3.0. This skill does not include or redistribute any Mycodo code — it communicates with a running Mycodo instance via its HTTP API.

Thanks also to [Nous Research](https://github.com/NousResearch) for the Hermes agent framework.

## License

MIT. See [LICENSE](LICENSE) for details.

## Links

- [Hermes Agent Framework](https://github.com/NousResearch/hermes-agent)
- [Mycodo](https://github.com/kizniche/Mycodo)
- [agentskills.io](https://agentskills.io)
