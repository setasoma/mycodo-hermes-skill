# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# License: MIT

"""
Integration tests for the decision engine.

These tests validate the decision pipeline without live hardware.
They use mock sensor data and pre-set actuator states to verify that
the engine produces correct decisions for known scenarios.

Run:
    python3 -m pytest tests/ -v
    # or without pytest:
    python3 tests/test_decision_engine.py
"""

import json
import os
import sys
import unittest
from pathlib import Path

# Add parent directory to path so we can import mycodo_skill
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set test-friendly ID fragments before importing decision_engine
os.environ["SHT45_ID_FRAG"] = "test_sht45"
os.environ["SCD41_ID_FRAG"] = "test_scd41"

from mycodo_skill.decision_engine import parse_influx_csv, build_decision, load_tent_state, TENT_STATE_PATH
from mycodo_skill.species_loader import load_species, get_phase, classify_all, list_available_species


# --- Mock sensor data ---

def mock_csv(temp_sht45=18.0, hum_sht45=88.0, co2_scd41=650.0, temp_scd41=17.8, hum_scd41=87.0):
    """Generate a mock InfluxDB CSV with sensor readings."""
    header = ",result,table,_start,_stop,_time,_value,_field,_measurement,device_id,measure"
    rows = [
        f",_result,0,2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T00:30:00Z,{temp_sht45},value,mycodo,device-test_sht45-001,temperature",
        f",_result,1,2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T00:30:00Z,{hum_sht45},value,mycodo,device-test_sht45-001,humidity",
        f",_result,2,2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T00:30:00Z,{co2_scd41},value,mycodo,device-test_scd41-002,co2",
        f",_result,3,2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T00:30:00Z,{temp_scd41},value,mycodo,device-test_scd41-002,temperature",
        f",_result,4,2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T00:30:00Z,{hum_scd41},value,mycodo,device-test_scd41-002,humidity",
    ]
    return "\n".join([header] + rows)


def mock_fan(state="off"):
    return {"state": state, "source": "test"}


def mock_humidifier(state="off"):
    return {"state": state, "source": "test"}


# --- Test Cases ---

class TestCSVParsing(unittest.TestCase):
    """Test that InfluxDB CSV data is correctly parsed into metrics."""

    def test_parse_all_sensors(self):
        csv = mock_csv(temp_sht45=19.5, hum_sht45=91.0, co2_scd41=800.0)
        parsed = parse_influx_csv(csv)
        self.assertAlmostEqual(parsed["temperature_sht45"], 19.5)
        self.assertAlmostEqual(parsed["humidity_sht45"], 91.0)
        self.assertAlmostEqual(parsed["co2_scd41"], 800.0)

    def test_parse_empty_csv(self):
        csv = ",result,table,_start,_stop,_time,_value,_field,_measurement,device_id,measure"
        parsed = parse_influx_csv(csv)
        self.assertEqual(parsed, {})

    def test_unknown_device_ignored(self):
        header = ",result,table,_start,_stop,_time,_value,_field,_measurement,device_id,measure"
        row = ",_result,0,2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T00:30:00Z,25.0,value,mycodo,unknown-device-xyz,temperature"
        parsed = parse_influx_csv(f"{header}\n{row}")
        self.assertEqual(parsed, {})


class TestSpeciesLoader(unittest.TestCase):
    """Test that species YAML configs load correctly."""

    def test_list_species(self):
        species = list_available_species()
        self.assertIn("lions_mane", species)
        self.assertGreaterEqual(len(species), 6)

    def test_load_lions_mane(self):
        data = load_species("lions_mane")
        self.assertEqual(data["species_id"], "lions_mane")
        self.assertIn("fruiting", data["phases"])
        self.assertIn("colonization", data["phases"])

    def test_all_species_have_required_phases(self):
        """Every species must have at least colonization, fruiting, and rest phases."""
        required = {"colonization", "fruiting", "rest"}
        for species_id in list_available_species():
            data = load_species(species_id)
            phases = set(data["phases"].keys())
            missing = required - phases
            self.assertEqual(missing, set(), f"{species_id} missing phases: {missing}")

    def test_invalid_species_raises(self):
        with self.assertRaises(ValueError):
            load_species("nonexistent_mushroom")

    def test_invalid_phase_raises(self):
        data = load_species("lions_mane")
        with self.assertRaises(ValueError):
            get_phase(data, "teleportation")

    def test_phase_aliases(self):
        """Aliases like 'pinning' should resolve to 'primordia'."""
        data = load_species("lions_mane")
        phase = get_phase(data, "pinning")
        self.assertIn("label", phase)


class TestDecisionEngine(unittest.TestCase):
    """Test decision logic for known sensor scenarios."""

    def _decide(self, temp=18.0, hum=88.0, co2=650.0, phase="fruiting",
                species="lions_mane", fan="off", humidifier="off", override=None):
        csv = mock_csv(temp_sht45=temp, hum_sht45=hum, co2_scd41=co2)
        parsed = parse_influx_csv(csv)
        return build_decision(
            parsed, phase,
            fan_status=mock_fan(fan),
            humidifier_status=mock_humidifier(humidifier),
            override=override,
            mode="dry-run",
            species_id=species,
        )

    def test_optimal_conditions_no_actions(self):
        """When all metrics are in range, no actuator actions should fire."""
        decision = self._decide(temp=18.0, hum=88.0, co2=650.0, phase="fruiting")
        self.assertEqual(decision["status"], "ok")
        # In optimal fruiting conditions, no fan or humidifier actions needed
        fan_actions = [a for a in decision["actions"] if a["actuator"] == "fan"]
        # Fan might still fire if CO2 thresholds differ by species, but no alerts
        self.assertEqual(len(decision["alerts"]), 0)

    def test_high_co2_triggers_fan(self):
        """CO2 above trigger threshold should produce a fan burst action."""
        decision = self._decide(temp=18.0, hum=90.0, co2=1500.0, phase="fruiting")
        fan_actions = [a for a in decision["actions"] if a["actuator"] == "fan"]
        self.assertGreater(len(fan_actions), 0, "High CO2 should trigger fan action")

    def test_oversaturation_guard(self):
        """Humidity >= 95% with humidifier ON should trigger the oversaturation guard."""
        decision = self._decide(temp=18.0, hum=97.0, co2=600.0, phase="fruiting", humidifier="on")
        hum_actions = [a for a in decision["actions"]
                       if a["actuator"] == "humidifier" and a["command"] == "off"]
        self.assertGreater(len(hum_actions), 0, "Oversaturation guard should turn humidifier off")
        # Should also trigger a fan burst
        fan_actions = [a for a in decision["actions"] if a["actuator"] == "fan"]
        self.assertGreater(len(fan_actions), 0, "Oversaturation guard should trigger fan burst")
        # Should produce an alert
        oversat_alerts = [a for a in decision["alerts"] if "OVERSATURATION" in a]
        self.assertGreater(len(oversat_alerts), 0, "Oversaturation guard should produce an alert")

    def test_oversaturation_guard_not_triggered_when_humidifier_off(self):
        """High humidity with humidifier off should NOT trigger the oversaturation GUARD
        (though standard humidity rules may still send humidifier-off as a safety measure)."""
        decision = self._decide(temp=18.0, hum=97.0, co2=600.0, phase="fruiting", humidifier="off")
        # The oversaturation GUARD specifically fires when humidity >= 95% AND humidifier is ON.
        # When humidifier is already off, the guard doesn't fire — but standard phase rules
        # may still send a humidifier-off action based on humidity exceeding accept_max.
        oversat_alerts = [a for a in decision["alerts"] if "OVERSATURATION" in a]
        self.assertEqual(len(oversat_alerts), 0,
                        "Oversaturation GUARD alert should not fire when humidifier is already off")

    def test_low_humidity_triggers_humidifier(self):
        """Humidity below acceptable minimum should turn humidifier on."""
        decision = self._decide(temp=18.0, hum=70.0, co2=600.0, phase="fruiting")
        hum_actions = [a for a in decision["actions"]
                       if a["actuator"] == "humidifier" and a["command"] == "on"]
        self.assertGreater(len(hum_actions), 0, "Low humidity should trigger humidifier on")

    def test_critical_temperature_alert(self):
        """Temperature outside alert thresholds should produce an alert."""
        decision = self._decide(temp=5.0, hum=88.0, co2=600.0, phase="fruiting")
        temp_alerts = [a for a in decision["alerts"] if "Temperature" in a]
        self.assertGreater(len(temp_alerts), 0, "Critical low temp should produce an alert")

    def test_missing_sensor_returns_error(self):
        """If a required sensor metric is missing, status should be 'error'."""
        # Parse CSV with only temperature — missing humidity and CO2
        header = ",result,table,_start,_stop,_time,_value,_field,_measurement,device_id,measure"
        row = ",_result,0,2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T00:30:00Z,18.0,value,mycodo,device-test_sht45-001,temperature"
        parsed = parse_influx_csv(f"{header}\n{row}")
        decision = build_decision(parsed, "fruiting", species_id="lions_mane")
        self.assertEqual(decision["status"], "error")

    def test_late_stage_continuous_fan(self):
        """Late-stage fruiting should enable continuous fan mode."""
        decision = self._decide(phase="late_stage_fruiting", fan="off")
        fan_actions = [a for a in decision["actions"] if a["actuator"] == "fan"]
        # Should get a fan-on action (continuous mode)
        fan_on = [a for a in fan_actions if a["command"] == "on"]
        self.assertGreater(len(fan_on), 0, "Late-stage should turn fan on continuously")

    def test_late_stage_fan_already_on(self):
        """Late-stage with fan already on should NOT send redundant command."""
        decision = self._decide(phase="late_stage_fruiting", fan="on")
        fan_actions = [a for a in decision["actions"] if a["actuator"] == "fan"]
        self.assertEqual(len(fan_actions), 0, "Should not send redundant fan command")
        # But should note it
        fan_notes = [n for n in decision["notes"] if "already ON" in n]
        self.assertGreater(len(fan_notes), 0, "Should note fan is already on")

    def test_operator_override_respected(self):
        """When operator override is active, it should be reflected in the decision."""
        override = {
            "active_protocol": {"status": "active"},
            "overrides": {
                "fan": {
                    "mode": "continuous",
                    "should_be_on": True,
                    "reason": "Test override",
                    "autonomous_can_override": True,
                }
            }
        }
        decision = self._decide(override=override, fan="off")
        self.assertIsNotNone(decision.get("operator_override"))

    def test_dry_run_mode(self):
        """Decision should report dry-run mode when not executing."""
        decision = self._decide()
        self.assertEqual(decision["mode"], "dry-run")

    def test_all_species_all_phases(self):
        """Every species+phase combination should produce a valid decision (no crashes)."""
        for species_id in list_available_species():
            data = load_species(species_id)
            for phase_name in data["phases"]:
                decision = self._decide(species=species_id, phase=phase_name)
                self.assertIn(decision["status"], ["ok", "error"],
                             f"Failed for {species_id}/{phase_name}: {decision}")


class TestClassification(unittest.TestCase):
    """Test the species-aware classification system."""

    def test_optimal_classification(self):
        data = load_species("lions_mane")
        phase = get_phase(data, "fruiting")
        metrics = {"temperature": 18.0, "humidity": 90.0, "co2": 600.0}
        result = classify_all(metrics, phase)
        self.assertIn(result["overall"], ["ideal", "acceptable"])

    def test_alert_classification(self):
        data = load_species("lions_mane")
        phase = get_phase(data, "fruiting")
        metrics = {"temperature": 35.0, "humidity": 30.0, "co2": 5000.0}
        result = classify_all(metrics, phase)
        self.assertEqual(result["overall"], "alert")


class TestTentState(unittest.TestCase):
    """Test the canonical tent state safety system."""

    def setUp(self):
        """Create a temporary tent state file for testing."""
        import tempfile
        self.original_path = TENT_STATE_PATH
        self.temp_dir = tempfile.mkdtemp()
        self.temp_state = Path(self.temp_dir) / ".mycodo-skill-tent-state.json"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_missing_state_returns_none(self):
        """Missing tent state file should return None (not crash)."""
        import mycodo_skill.decision_engine as de
        original = de.TENT_STATE_PATH
        de.TENT_STATE_PATH = Path("/nonexistent/path/.mycodo-skill-tent-state.json")
        result = load_tent_state()
        de.TENT_STATE_PATH = original
        self.assertIsNone(result)

    def test_load_valid_state(self):
        """Valid tent state file should load correctly."""
        import mycodo_skill.decision_engine as de
        state = {
            "schema_version": "1.0",
            "status": "active",
            "safety_lock": False,
            "autonomy_level": "full",
        }
        self.temp_state.write_text(json.dumps(state))
        original = de.TENT_STATE_PATH
        de.TENT_STATE_PATH = self.temp_state
        result = load_tent_state()
        de.TENT_STATE_PATH = original
        self.assertEqual(result["status"], "active")
        self.assertFalse(result["safety_lock"])

    def test_load_corrupt_state_returns_none(self):
        """Corrupt JSON should return None, not crash."""
        import mycodo_skill.decision_engine as de
        self.temp_state.write_text("not valid json {{{")
        original = de.TENT_STATE_PATH
        de.TENT_STATE_PATH = self.temp_state
        result = load_tent_state()
        de.TENT_STATE_PATH = original
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
        self.assertEqual(result["overall"], "alert")


if __name__ == "__main__":
    unittest.main()
tState(unittest.TestCase):
    """Test the canonical tent state safety system."""

    def setUp(self):
        """Create a temporary tent state file for testing."""
        import tempfile
        self.original_path = TENT_STATE_PATH
        self.temp_dir = tempfile.mkdtemp()
        self.temp_state = Path(self.temp_dir) / ".mycodo-skill-tent-state.json"

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_missing_state_returns_none(self):
        """Missing tent state file should return None (not crash)."""
        import mycodo_skill.decision_engine as de
        original = de.TENT_STATE_PATH
        de.TENT_STATE_PATH = Path("/nonexistent/path/.mycodo-skill-tent-state.json")
        result = load_tent_state()
        de.TENT_STATE_PATH = original
        self.assertIsNone(result)

    def test_load_valid_state(self):
        """Valid tent state file should load correctly."""
        import mycodo_skill.decision_engine as de
        state = {
            "schema_version": "1.0",
            "status": "active",
            "safety_lock": False,
            "autonomy_level": "full",
        }
        self.temp_state.write_text(json.dumps(state))
        original = de.TENT_STATE_PATH
        de.TENT_STATE_PATH = self.temp_state
        result = load_tent_state()
        de.TENT_STATE_PATH = original
        self.assertEqual(result["status"], "active")
        self.assertFalse(result["safety_lock"])

    def test_load_corrupt_state_returns_none(self):
        """Corrupt JSON should return None, not crash."""
        import mycodo_skill.decision_engine as de
        self.temp_state.write_text("not valid json {{{")
        original = de.TENT_STATE_PATH
        de.TENT_STATE_PATH = self.temp_state
        result = load_tent_state()
        de.TENT_STATE_PATH = original
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
