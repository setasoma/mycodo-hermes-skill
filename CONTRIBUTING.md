# Contributing to Mycodo Hermes Skill

Thank you for your interest in contributing to the Mycodo Hermes Skill.

## How to Contribute

### Bug Reports

Open an issue with:

- Your hardware setup (Pi model, sensors, relay type)
- Mycodo version and InfluxDB version
- Hermes version
- Steps to reproduce the issue
- Relevant output from the decision engine (with `--json` flag)

### New Species Configs

Adding support for a new mushroom species is the easiest way to contribute. No code changes are needed.

1. Copy `docs/templates/species-config.yaml` to `species/your_species.yaml`
2. Fill in the phase thresholds based on the species' cultivation requirements
3. Test with a dry run: `python3 mycodo_skill/decision_engine.py --species your_species --phase fruiting`
4. Submit a pull request with your YAML file and a brief note on your sources for the threshold values

### Code Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Make your changes
4. Test with a dry run against at least one species config
5. Run a security scan: ensure no credentials, IPs, or personal paths are included
6. Submit a pull request with a clear description of what changed and why

### Documentation

Fixes, clarifications, and new examples are always welcome. If you've hit a pitfall that isn't documented in `docs/pitfalls.md`, please add it.

## Security

Before submitting any pull request, verify that your changes do not contain:

- IP addresses or hostnames
- API keys, tokens, or passwords
- Mycodo device IDs (UUIDs)
- File paths containing usernames
- Telegram bot tokens or chat IDs

Use the placeholder format documented in `docs/templates/sensor-creds.env.example` for any site-specific values.

## Code Style

- Python: PEP 8, practical line lengths
- Shell: POSIX-compatible where possible, `shellcheck` clean
- YAML: 2-space indentation, comments for non-obvious thresholds
- Commit messages: conventional commits (`fix:`, `feat:`, `docs:`)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
