"""
Tests for pump-related functionality (pump status, treatments, profile).
"""
import json
import sys
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_devicestatus_response():
    """Mock device status response from Nightscout."""
    return [
        {
            "_id": "test123",
            "created_at": "2026-01-27T00:19:37Z",
            "loop": {
                "version": "3.8.1.57",
                "recommendedBolus": 0.35,
                "predicted": {
                    "startDate": "2026-01-27T00:19:28Z",
                    "values": [154, 140, 130, 120, 110, 100, 95, 92]
                },
                "cob": {"cob": 5.5, "timestamp": "2026-01-27T00:15:00Z"},
                "name": "Loop",
                "timestamp": "2026-01-27T00:19:37Z",
                "iob": {"iob": 1.85, "timestamp": "2026-01-27T00:20:00Z"},
                "enacted": {
                    "duration": 30,
                    "received": True,
                    "bolusVolume": 0.45,
                    "rate": 0,
                    "timestamp": "2026-01-27T00:19:35Z"
                }
            },
            "override": {"active": False, "timestamp": "2026-01-27T00:19:37Z"},
            "device": "loop://iPhone",
            "pump": {
                "model": "Dash",
                "suspended": False,
                "bolusing": True,
                "manufacturer": "Insulet",
                "pumpID": "1234ABCD",
                "clock": "2026-01-27T00:19:37Z"
            },
            "uploader": {
                "battery": 75,
                "timestamp": "2026-01-27T00:19:37Z",
                "name": "iPhone"
            }
        }
    ]


@pytest.fixture
def mock_treatments_response():
    """Mock treatments response from Nightscout."""
    return [
        {
            "_id": "t1",
            "eventType": "Correction Bolus",
            "insulin": 0.45,
            "insulinType": "Fiasp",
            "automatic": True,
            "created_at": "2026-01-27T00:19:36Z"
        },
        {
            "_id": "t2",
            "eventType": "Temp Basal",
            "rate": 0,
            "duration": 30,
            "automatic": True,
            "created_at": "2026-01-27T00:04:34Z"
        },
        {
            "_id": "t3",
            "eventType": "Carb Correction",
            "carbs": 45,
            "absorptionTime": 180,
            "created_at": "2026-01-26T21:05:09Z"
        },
        {
            "_id": "t4",
            "eventType": "Meal Bolus",
            "insulin": 5.5,
            "insulinType": "Fiasp",
            "automatic": False,
            "created_at": "2026-01-26T21:00:00Z"
        }
    ]


@pytest.fixture
def mock_profile_response():
    """Mock profile response from Nightscout."""
    return [
        {
            "_id": "p1",
            "store": {
                "Default": {
                    "sens": [
                        {"time": "00:00", "value": 44, "timeAsSeconds": 0},
                        {"time": "06:00", "value": 44, "timeAsSeconds": 21600},
                        {"time": "12:00", "value": 42, "timeAsSeconds": 43200}
                    ],
                    "basal": [
                        {"time": "00:00", "value": 1.2, "timeAsSeconds": 0},
                        {"time": "10:30", "value": 1.0, "timeAsSeconds": 37800},
                        {"time": "19:00", "value": 1.2, "timeAsSeconds": 68400}
                    ],
                    "carbratio": [
                        {"time": "00:00", "value": 8.2, "timeAsSeconds": 0},
                        {"time": "06:00", "value": 8.2, "timeAsSeconds": 21600},
                        {"time": "12:00", "value": 8.2, "timeAsSeconds": 43200}
                    ],
                    "target_low": [{"time": "00:00", "value": 95, "timeAsSeconds": 0}],
                    "target_high": [{"time": "00:00", "value": 100, "timeAsSeconds": 0}],
                    "dia": 6,
                    "units": "mg/dL"
                }
            },
            "units": "mg/dL",
            "loopSettings": {
                "maximumBolus": 7,
                "minimumBGGuard": 74,
                "dosingEnabled": True,
                "preMealTargetRange": [74, 79],
                "overridePresets": [
                    {
                        "name": "Workout",
                        "symbol": "🏃",
                        "duration": 7200,
                        "insulinNeedsScaleFactor": 0.2,
                        "targetRange": [120, 125]
                    }
                ]
            }
        }
    ]


@pytest.fixture
def mock_capabilities_with_pump():
    """Mock capabilities for a user with pump data."""
    return {
        "has_treatments": True,
        "has_devicestatus": True,
        "has_profile": True,
        "pump_info": {"manufacturer": "Insulet", "model": "Dash"},
        "loop_info": {"name": "Loop", "version": "3.8.1.57"},
        "_checked_at": "2026-01-27T00:00:00+00:00"
    }


@pytest.fixture
def mock_capabilities_cgm_only():
    """Mock capabilities for a CGM-only user."""
    return {
        "has_treatments": False,
        "has_devicestatus": False,
        "has_profile": False,
        "pump_info": None,
        "loop_info": None,
        "_checked_at": "2026-01-27T00:00:00+00:00"
    }


# =============================================================================
# CAPABILITY DETECTION TESTS
# =============================================================================

class TestCapabilityDetection:
    """Tests for pump capability detection."""

    def test_detect_pump_capabilities_with_pump(self, cgm_module, mock_devicestatus_response, 
                                                  mock_treatments_response, mock_profile_response):
        """Should detect pump capabilities when data is available."""
        cgm_module._pump_capabilities = None  # Clear cache
        
        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if "devicestatus" in url:
                mock_resp.json.return_value = mock_devicestatus_response
            elif "treatments" in url:
                mock_resp.json.return_value = mock_treatments_response
            elif "profile" in url:
                mock_resp.json.return_value = mock_profile_response
            return mock_resp
        
        with patch("requests.get", side_effect=mock_get):
            with patch.object(cgm_module, "_load_config", return_value={}):
                with patch.object(cgm_module, "_save_config"):
                    caps = cgm_module.detect_pump_capabilities()
        
        assert caps["has_devicestatus"] is True
        assert caps["has_treatments"] is True
        assert caps["has_profile"] is True
        assert caps["pump_info"]["manufacturer"] == "Insulet"
        assert caps["loop_info"]["name"] == "Loop"

    def test_detect_pump_capabilities_cgm_only(self, cgm_module):
        """Should detect CGM-only when no pump data is available."""
        cgm_module._pump_capabilities = None  # Clear cache
        
        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = []  # Empty responses
            return mock_resp
        
        with patch("requests.get", side_effect=mock_get):
            with patch.object(cgm_module, "_load_config", return_value={}):
                with patch.object(cgm_module, "_save_config"):
                    caps = cgm_module.detect_pump_capabilities()
        
        assert caps["has_devicestatus"] is False
        assert caps["has_treatments"] is False
        assert caps["has_profile"] is False
        assert caps["pump_info"] is None
        assert caps["loop_info"] is None

    def test_detect_pump_capabilities_uses_cache(self, cgm_module, mock_capabilities_with_pump):
        """Should use cached capabilities instead of making API calls."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        with patch("requests.get") as mock_get:
            caps = cgm_module.detect_pump_capabilities()
        
        # Should not make any API calls
        mock_get.assert_not_called()
        assert caps["has_devicestatus"] is True

    def test_has_pump_data_helper(self, cgm_module, mock_capabilities_with_pump, mock_capabilities_cgm_only):
        """has_pump_data() should return correct boolean."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        assert cgm_module.has_pump_data() is True
        
        cgm_module._pump_capabilities = mock_capabilities_cgm_only
        assert cgm_module.has_pump_data() is False


# =============================================================================
# PUMP STATUS TESTS
# =============================================================================

class TestGetPumpStatus:
    """Tests for get_pump_status() function."""

    def test_get_pump_status_success(self, cgm_module, mock_devicestatus_response, mock_capabilities_with_pump):
        """Should return pump status with IOB, COB, and predictions."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_devicestatus_response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_pump_status()
        
        assert "error" not in result
        assert result["pump"]["manufacturer"] == "Insulet"
        assert result["pump"]["model"] == "Dash"
        assert result["iob"]["value"] == 1.85
        assert result["cob"]["value"] == 5.5
        assert result["predicted"]["current"] == 154
        assert result["predicted"]["eventual"] == 92
        assert result["recommended_bolus"]["value"] == 0.35
        assert result["uploader"]["battery"] == 75

    def test_get_pump_status_cgm_only(self, cgm_module, mock_capabilities_cgm_only):
        """Should return helpful error for CGM-only users."""
        cgm_module._pump_capabilities = mock_capabilities_cgm_only
        
        result = cgm_module.get_pump_status()
        
        assert "error" in result
        assert result["cgm_only"] is True
        assert "pump" in result["message"].lower()

    def test_get_pump_status_empty_response(self, cgm_module, mock_capabilities_with_pump):
        """Should handle empty device status response."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_pump_status()
        
        assert "error" in result

    def test_get_pump_status_network_error(self, cgm_module, mock_capabilities_with_pump):
        """Should handle network errors gracefully."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        import requests
        with patch("requests.get", side_effect=requests.RequestException("Network error")):
            result = cgm_module.get_pump_status()
        
        assert "error" in result
        assert "Network error" in result["error"]


# =============================================================================
# TREATMENTS TESTS
# =============================================================================

class TestGetTreatments:
    """Tests for get_treatments() function."""

    def test_get_treatments_success(self, cgm_module, mock_treatments_response, mock_capabilities_with_pump):
        """Should return categorized treatments with summary."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_treatments_response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_treatments(hours=24)
        
        assert "error" not in result
        assert result["period_hours"] == 24
        assert len(result["boluses"]) == 2  # Correction Bolus and Meal Bolus
        assert len(result["temp_basals"]) == 1
        assert len(result["carbs"]) == 1
        assert result["summary"]["total_insulin"] == 5.95  # 0.45 + 5.5
        assert result["summary"]["total_carbs"] == 45

    def test_get_treatments_cgm_only(self, cgm_module, mock_capabilities_cgm_only):
        """Should return helpful error for CGM-only users."""
        cgm_module._pump_capabilities = mock_capabilities_cgm_only
        
        result = cgm_module.get_treatments()
        
        assert "error" in result
        assert result["cgm_only"] is True

    def test_get_treatments_empty_response(self, cgm_module, mock_capabilities_with_pump):
        """Should handle empty treatments response."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_treatments()
        
        assert "error" not in result
        assert result["treatments"] == []
        assert result["summary"]["total"] == 0

    def test_get_treatments_custom_hours(self, cgm_module, mock_capabilities_with_pump):
        """Should respect custom hours parameter."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp) as mock_get:
            cgm_module.get_treatments(hours=6)
        
        # Check that the time filter was applied
        call_args = mock_get.call_args
        assert "find[created_at][$gte]" in str(call_args)


# =============================================================================
# PROFILE TESTS
# =============================================================================

class TestGetProfile:
    """Tests for get_profile() function."""

    def test_get_profile_success(self, cgm_module, mock_profile_response, mock_capabilities_with_pump):
        """Should return full profile with basal, ISF, carb ratios."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_profile_response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_profile()
        
        assert "error" not in result
        assert result["dia"] == 6
        assert len(result["basal_rates"]) == 3
        assert result["basal_rates"][0]["rate"] == 1.2
        assert len(result["isf"]) == 3
        assert result["isf"][0]["value"] == 44
        assert len(result["carb_ratios"]) == 3
        assert result["carb_ratios"][0]["value"] == 8.2
        assert result["targets"][0]["low"] == 95
        assert result["targets"][0]["high"] == 100

    def test_get_profile_total_daily_basal(self, cgm_module, mock_profile_response, mock_capabilities_with_pump):
        """Should calculate total daily basal correctly."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_profile_response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_profile()
        
        # Should calculate: 10.5 hrs * 1.2 + 8.5 hrs * 1.0 + 5 hrs * 1.2
        assert "total_daily_basal" in result
        assert result["total_daily_basal"] > 0

    def test_get_profile_loop_settings(self, cgm_module, mock_profile_response, mock_capabilities_with_pump):
        """Should include Loop settings when available."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_profile_response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_profile()
        
        assert result["loop_settings"]["maximum_bolus"] == 7
        assert result["loop_settings"]["dosing_enabled"] is True
        assert result["loop_settings"]["pre_meal_target"]["low"] == 74

    def test_get_profile_override_presets(self, cgm_module, mock_profile_response, mock_capabilities_with_pump):
        """Should include override presets."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_profile_response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_profile()
        
        assert len(result["override_presets"]) == 1
        assert result["override_presets"][0]["name"] == "Workout"
        assert result["override_presets"][0]["insulin_needs_scale"] == 0.2

    def test_get_profile_cgm_only(self, cgm_module, mock_capabilities_cgm_only):
        """Should return helpful error for CGM-only users."""
        cgm_module._pump_capabilities = mock_capabilities_cgm_only
        
        result = cgm_module.get_profile()
        
        assert "error" in result
        assert result["cgm_only"] is True


# =============================================================================
# CLI TESTS
# =============================================================================

class TestPumpCLI:
    """Tests for pump-related CLI commands."""

    def test_pump_command(self, cgm_module):
        """'pump' command should call get_pump_status."""
        with patch.object(cgm_module, "get_pump_status") as mock_func:
            mock_func.return_value = {"iob": {"value": 1.5}}
            with patch.object(sys, "argv", ["cgm.py", "pump"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_func.assert_called_once()

    def test_treatments_command(self, cgm_module):
        """'treatments' command should call get_treatments."""
        with patch.object(cgm_module, "get_treatments") as mock_func:
            mock_func.return_value = {"boluses": []}
            with patch.object(sys, "argv", ["cgm.py", "treatments"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_func.assert_called_once()

    def test_treatments_command_with_hours(self, cgm_module):
        """'treatments --hours N' should pass hours parameter."""
        with patch.object(cgm_module, "get_treatments") as mock_func:
            mock_func.return_value = {"boluses": []}
            with patch.object(sys, "argv", ["cgm.py", "treatments", "--hours", "6"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_func.assert_called_once_with(hours=6)

    def test_profile_command(self, cgm_module):
        """'profile' command should call get_profile."""
        with patch.object(cgm_module, "get_profile") as mock_func:
            mock_func.return_value = {"basal_rates": []}
            with patch.object(sys, "argv", ["cgm.py", "profile"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_func.assert_called_once()


# =============================================================================
# CONFIG FILE TESTS
# =============================================================================

class TestConfigFile:
    """Tests for config file loading and saving."""

    def test_load_config_missing_file(self, cgm_module, tmp_path):
        """Should return empty dict when config file doesn't exist."""
        with patch.object(cgm_module, "CONFIG_PATH", tmp_path / "nonexistent.json"):
            result = cgm_module._load_config()
        assert result == {}

    def test_load_config_invalid_json(self, cgm_module, tmp_path):
        """Should return empty dict when config file has invalid JSON."""
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json {{{")
        
        with patch.object(cgm_module, "CONFIG_PATH", config_file):
            result = cgm_module._load_config()
        assert result == {}

    def test_save_and_load_config(self, cgm_module, tmp_path):
        """Should save and load config correctly."""
        config_file = tmp_path / "config.json"
        test_config = {"pump_capabilities": {"has_pump": True}}
        
        with patch.object(cgm_module, "CONFIG_PATH", config_file):
            cgm_module._save_config(test_config)
            result = cgm_module._load_config()
        
        assert result == test_config


# =============================================================================
# EDGE CASES
# =============================================================================

class TestPumpEdgeCases:
    """Edge case tests for pump functionality."""

    def test_devicestatus_missing_loop(self, cgm_module, mock_capabilities_with_pump):
        """Should handle devicestatus without loop data."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        response = [{
            "created_at": "2026-01-27T00:00:00Z",
            "pump": {"manufacturer": "Medtronic", "model": "770G"},
            "uploader": {"battery": 50}
        }]
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_pump_status()
        
        assert "error" not in result
        assert result["pump"]["manufacturer"] == "Medtronic"
        assert "iob" not in result  # No loop data

    def test_profile_missing_optional_fields(self, cgm_module, mock_capabilities_with_pump):
        """Should handle profile with missing optional fields."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        response = [{
            "store": {
                "Default": {
                    "basal": [{"time": "00:00", "value": 1.0, "timeAsSeconds": 0}],
                    "dia": 5
                }
            }
        }]
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_profile()
        
        assert "error" not in result
        assert result["dia"] == 5
        assert "isf" not in result  # Missing
        assert "carb_ratios" not in result  # Missing

    def test_treatments_mixed_types(self, cgm_module, mock_capabilities_with_pump):
        """Should categorize various treatment types correctly."""
        cgm_module._pump_capabilities = mock_capabilities_with_pump
        
        response = [
            {"eventType": "Correction Bolus", "insulin": 1.0, "created_at": "2026-01-27T00:00:00Z"},
            {"eventType": "Meal Bolus", "insulin": 5.0, "created_at": "2026-01-27T00:00:00Z"},
            {"eventType": "Temp Basal", "rate": 0.5, "duration": 30, "created_at": "2026-01-27T00:00:00Z"},
            {"eventType": "Carb Correction", "carbs": 15, "created_at": "2026-01-27T00:00:00Z"},
            {"eventType": "Note", "notes": "Site change", "created_at": "2026-01-27T00:00:00Z"},
        ]
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = response
        mock_resp.raise_for_status = MagicMock()
        
        with patch("requests.get", return_value=mock_resp):
            result = cgm_module.get_treatments()
        
        assert len(result["boluses"]) == 2
        assert len(result["temp_basals"]) == 1
        assert len(result["carbs"]) == 1
        assert len(result["other"]) == 1
