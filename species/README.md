# Mycodo Hermes Skill Species Directory

Each species has its own YAML config with complete phase definitions.
These are machine-readable sources consumed by the agnostic phase config loader.

## Naming Convention
Files: `<species_id>.yaml`
- `lions_mane` — Hericium erinaceus
- `oyster` — Pleurotus ostreatus
- `shiitake` — Lentinula edodes
- `reishi` — Ganoderma lucidum
- `turkey_tail` — Trametes versicolor
- `maitake` — Grifola frondosa

## Species ID Guidelines
- Lowercase, underscore-separated
- Use latin species name common name mapping
- Keep stable — changing IDs breaks old state files
