"""
Tests for FreeStyle Libre 3 / LibreLinkUp integration.

Tests the LibreLinkUp API client, authentication, data fetching,
trend mapping, timestamp parsing, and end-to-end data flow.
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def llu_env(monkeypatch):
    """Set up environment for LibreLinkUp mode."""
    monkeypatch.delenv("NIGHTSCOUT_URL", raising=False)
    monkeypatch.setenv("LIBRELINKUP_EMAIL", "test@example.com")
    monkeypatch.setenv("LIBRELINKUP_PASSWORD", "testpassword")
    monkeypatch.setenv("LIBRELINKUP_REGION", "US")


@pytest.fixture
def llu_module(monkeypatch, tmp_path):
    """Import cgm module in LibreLinkUp mode."""
    monkeypatch.setenv("LIBRELINKUP_EMAIL", "test@example.com")
    monkeypatch.setenv("LIBRELINKUP_PASSWORD", "testpassword")
    monkeypatch.setenv("LIBRELINKUP_REGION", "US")
    monkeypatch.delenv("NIGHTSCOUT_URL", raising=False)

    if "cgm" in sys.modules:
        del sys.modules["cgm"]

    with patch.dict("os.environ", {
        "LIBRELINKUP_EMAIL": "test@example.com",
        "LIBRELINKUP_PASSWORD": "testpassword",
        "LIBRELINKUP_REGION": "US",
    }):
        # Remove NIGHTSCOUT_URL from environ copy
        import os
        env = os.environ.copy()
        env.pop("NIGHTSCOUT_URL", None)
        with patch.dict("os.environ", env, clear=True):
            import cgm
            db_path = tmp_path / "test_cgm_data.db"
            monkeypatch.setattr(cgm, "DB_PATH", db_path)
            monkeypatch.setattr(cgm, "CONFIG_PATH", tmp_path / "config.json")
            monkeypatch.setattr(cgm, "_cached_settings", None)
            monkeypatch.setattr(cgm, "_llu_auth", None)
            monkeypatch.setattr(cgm, "_pump_capabilities", None)
            yield cgm


@pytest.fixture
def ns_module(monkeypatch, tmp_path):
    """Import cgm module in Nightscout mode (for comparison tests)."""
    monkeypatch.setenv("NIGHTSCOUT_URL", "https://test.example.com/api/v1/entries.json")
    monkeypatch.delenv("LIBRELINKUP_EMAIL", raising=False)
    monkeypatch.delenv("LIBRELINKUP_PASSWORD", raising=False)

    if "cgm" in sys.modules:
        del sys.modules["cgm"]

    with patch.dict("os.environ", {
        "NIGHTSCOUT_URL": "https://test.example.com/api/v1/entries.json",
    }):
        import cgm
        db_path = tmp_path / "test_cgm_data.db"
        monkeypatch.setattr(cgm, "DB_PATH", db_path)
        monkeypatch.setattr(cgm, "CONFIG_PATH", tmp_path / "config.json")
        monkeypatch.setattr(cgm, "_cached_settings", None)
        monkeypatch.setattr(cgm, "_pump_capabilities", None)
        yield cgm


@pytest.fixture
def mock_llu_login_response():
    """Mock successful LibreLinkUp login response."""
    return {
        "status": 0,
        "data": {
            "user": {
                "id": "user-123",
                "email": "test@example.com",
            },
            "authTicket": {
                "token": "mock-jwt-token-abc123",
                "expires": 1800000,
            },
        },
    }


@pytest.fixture
def mock_llu_connections_response():
    """Mock LibreLinkUp connections response."""
    return {
        "status": 0,
        "data": [
            {
                "patientId": "patient-456",
                "firstName": "Test",
                "lastName": "User",
                "glucoseMeasurement": {
                    "Value": 125,
                    "TrendArrow": 3,
                    "Timestamp": "1/15/2026 2:30:00 PM",
                    "isHigh": False,
                    "isLow": False,
                    "MeasurementColor": 1,
                },
            }
        ],
    }


@pytest.fixture
def mock_llu_graph_response():
    """Mock LibreLinkUp graph data response."""
    now = datetime.now(timezone.utc)
    graph_data = []
    for i in range(48):  # 12 hours of 15-min readings
        ts = now - timedelta(minutes=i * 15)
        graph_data.append({
            "Value": 100 + (i % 10) * 8,
            "TrendArrow": 3,
            "Timestamp": ts.strftime("%m/%d/%Y %I:%M:%S %p"),
            "isHigh": False,
            "isLow": False,
        })

    return {
        "status": 0,
        "data": {
            "connection": {
                "glucoseMeasurement": {
                    "Value": 118,
                    "TrendArrow": 4,
                    "Timestamp": now.strftime("%m/%d/%Y %I:%M:%S %p"),
                    "isHigh": False,
                    "isLow": False,
                },
            },
            "graphData": graph_data,
        },
    }


@pytest.fixture
def mock_llu_redirect_response():
    """Mock LibreLinkUp login redirect response."""
    return {
        "status": 0,
        "data": {
            "redirect": True,
            "region": "EU",
        },
    }


# ============================================================================
# Trend Mapping Tests
# ============================================================================

class TestTrendMapping:
    """Test LibreLinkUp trend arrow to Nightscout direction/code mapping."""

    def test_trend_arrow_1_is_single_down(self, llu_module):
        assert llu_module._llu_trend_to_direction(1) == "SingleDown"
        assert llu_module._llu_trend_to_code(1) == 6

    def test_trend_arrow_2_is_fortyfive_down(self, llu_module):
        assert llu_module._llu_trend_to_direction(2) == "FortyFiveDown"
        assert llu_module._llu_trend_to_code(2) == 5

    def test_trend_arrow_3_is_flat(self, llu_module):
        assert llu_module._llu_trend_to_direction(3) == "Flat"
        assert llu_module._llu_trend_to_code(3) == 4

    def test_trend_arrow_4_is_fortyfive_up(self, llu_module):
        assert llu_module._llu_trend_to_direction(4) == "FortyFiveUp"
        assert llu_module._llu_trend_to_code(4) == 3

    def test_trend_arrow_5_is_single_up(self, llu_module):
        assert llu_module._llu_trend_to_direction(5) == "SingleUp"
        assert llu_module._llu_trend_to_code(5) == 2

    def test_unknown_trend_arrow_returns_not_computable(self, llu_module):
        assert llu_module._llu_trend_to_direction(0) == "NOT COMPUTABLE"
        assert llu_module._llu_trend_to_direction(99) == "NOT COMPUTABLE"

    def test_unknown_trend_code_returns_zero(self, llu_module):
        assert llu_module._llu_trend_to_code(0) == 0
        assert llu_module._llu_trend_to_code(99) == 0


# ============================================================================
# Timestamp Parsing Tests
# ============================================================================

class TestTimestampParsing:
    """Test parsing of LibreLinkUp timestamp formats."""

    def test_us_format(self, llu_module):
        ms = llu_module._llu_parse_timestamp("1/15/2026 2:30:00 PM")
        assert ms is not None
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        assert dt.month == 1
        assert dt.day == 15
        assert dt.year == 2026
        assert dt.hour == 14
        assert dt.minute == 30

    def test_iso_format(self, llu_module):
        ms = llu_module._llu_parse_timestamp("2026-01-15T14:30:00")
        assert ms is not None
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        assert dt.hour == 14
        assert dt.minute == 30

    def test_simple_format(self, llu_module):
        ms = llu_module._llu_parse_timestamp("2026-01-15 14:30:00")
        assert ms is not None

    def test_invalid_format_returns_none(self, llu_module):
        assert llu_module._llu_parse_timestamp("not-a-date") is None
        assert llu_module._llu_parse_timestamp("") is None

    def test_am_pm_handling(self, llu_module):
        am_ms = llu_module._llu_parse_timestamp("1/15/2026 8:00:00 AM")
        pm_ms = llu_module._llu_parse_timestamp("1/15/2026 8:00:00 PM")
        assert am_ms is not None
        assert pm_ms is not None
        # PM should be 12 hours later
        assert (pm_ms - am_ms) == 12 * 60 * 60 * 1000


# ============================================================================
# Region URL Tests
# ============================================================================

class TestRegionURLs:
    """Test LibreLinkUp regional endpoint selection."""

    def test_us_region(self, llu_module):
        assert "api-us" in llu_module._llu_base_url()

    def test_eu_region(self, llu_module, monkeypatch):
        monkeypatch.setattr(llu_module, "_llu_region", "EU")
        assert "api-eu" in llu_module._llu_base_url()

    def test_de_region(self, llu_module, monkeypatch):
        monkeypatch.setattr(llu_module, "_llu_region", "DE")
        assert "api-de" in llu_module._llu_base_url()

    def test_unknown_region_falls_back_to_us(self, llu_module, monkeypatch):
        monkeypatch.setattr(llu_module, "_llu_region", "XX")
        assert "api-us" in llu_module._llu_base_url()


# ============================================================================
# Headers Tests
# ============================================================================

class TestHeaders:
    """Test LibreLinkUp API headers."""

    def test_headers_without_token(self, llu_module):
        headers = llu_module._llu_headers()
        assert headers["product"] == "llu.android"
        assert headers["version"] == "4.7.0"
        assert headers["Content-Type"] == "application/json"
        assert "Authorization" not in headers

    def test_headers_with_token(self, llu_module):
        headers = llu_module._llu_headers("my-token")
        assert headers["Authorization"] == "Bearer my-token"
        assert headers["product"] == "llu.android"


# ============================================================================
# Authentication Tests
# ============================================================================

class TestLLULogin:
    """Test LibreLinkUp login flow."""

    def test_successful_login(self, llu_module, mock_llu_login_response, mock_llu_connections_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_connections_response),
                raise_for_status=MagicMock(),
            )

            result = llu_module.llu_login()

            assert "error" not in result
            assert result["token"] == "mock-jwt-token-abc123"
            assert result["patient_id"] == "patient-456"

    def test_login_caches_result(self, llu_module, mock_llu_login_response, mock_llu_connections_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_connections_response),
                raise_for_status=MagicMock(),
            )

            result1 = llu_module.llu_login()
            result2 = llu_module.llu_login()

            # Should only call API once (second call uses cache)
            assert mock_post.call_count == 1
            assert result1["token"] == result2["token"]

    def test_login_handles_region_redirect(self, llu_module, mock_llu_redirect_response,
                                            mock_llu_login_response, mock_llu_connections_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            # First call returns redirect, second returns token
            mock_post.return_value = MagicMock(
                json=MagicMock(side_effect=[mock_llu_redirect_response, mock_llu_login_response]),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_connections_response),
                raise_for_status=MagicMock(),
            )

            result = llu_module.llu_login()

            assert "error" not in result
            assert result["token"] == "mock-jwt-token-abc123"
            # Should have made 2 POST calls (initial + redirect)
            assert mock_post.call_count == 2

    def test_login_network_error(self, llu_module):
        import requests as req
        with patch("requests.post") as mock_post:
            mock_post.side_effect = req.RequestException("Connection refused")

            result = llu_module.llu_login()

            assert "error" in result

    def test_login_no_token_in_response(self, llu_module):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value={"status": 0, "data": {}}),
                raise_for_status=MagicMock(),
            )

            result = llu_module.llu_login()

            assert "error" in result
            assert "no token" in result["error"].lower() or "Check credentials" in result["error"]

    def test_login_no_connections(self, llu_module, mock_llu_login_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(return_value={"status": 0, "data": []}),
                raise_for_status=MagicMock(),
            )

            result = llu_module.llu_login()

            assert "error" in result
            assert "no connected patients" in result["error"].lower()


# ============================================================================
# Data Fetching Tests
# ============================================================================

class TestFetchFromLibreLinkUp:
    """Test fetching and storing glucose data from LibreLinkUp."""

    def test_fetch_stores_graph_data(self, llu_module, mock_llu_login_response,
                                      mock_llu_connections_response, mock_llu_graph_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            # First GET = connections (for login), second GET = graph
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[mock_llu_connections_response, mock_llu_graph_response]),
                raise_for_status=MagicMock(),
            )

            result = llu_module.fetch_from_librelinkup()

            assert "error" not in result
            assert result["status"] == "success"
            assert result["source"] == "librelinkup"
            assert result["new_readings"] > 0
            assert result["total_readings"] > 0

    def test_fetch_stores_correct_fields(self, llu_module, mock_llu_login_response,
                                          mock_llu_connections_response, mock_llu_graph_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[mock_llu_connections_response, mock_llu_graph_response]),
                raise_for_status=MagicMock(),
            )

            llu_module.fetch_from_librelinkup()

            # Read back from database
            conn = sqlite3.connect(llu_module.DB_PATH)
            rows = conn.execute("SELECT * FROM readings ORDER BY date_ms DESC LIMIT 1").fetchall()
            conn.close()

            assert len(rows) == 1
            row = rows[0]
            assert row[0].startswith("libre-")  # id
            assert isinstance(row[1], int)       # sgv
            assert isinstance(row[2], int)       # date_ms
            assert isinstance(row[3], str)       # date_string
            assert isinstance(row[4], int)       # trend
            assert isinstance(row[5], str)       # direction
            assert row[6] == "libre3-librelinkup"  # device

    def test_fetch_includes_current_measurement(self, llu_module, mock_llu_login_response,
                                                  mock_llu_connections_response, mock_llu_graph_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[mock_llu_connections_response, mock_llu_graph_response]),
                raise_for_status=MagicMock(),
            )

            result = llu_module.fetch_from_librelinkup()

            # Current measurement (118) + 48 graph points
            assert result["new_readings"] >= 48

    def test_fetch_deduplicates_readings(self, llu_module, mock_llu_login_response,
                                          mock_llu_connections_response, mock_llu_graph_response):
        """Fetching the same data twice should not create duplicate readings."""
        import copy

        # First fetch
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=copy.deepcopy(mock_llu_login_response)),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                raise_for_status=MagicMock(),
            )
            mock_get.return_value.json = MagicMock(
                side_effect=[copy.deepcopy(mock_llu_connections_response),
                             copy.deepcopy(mock_llu_graph_response)]
            )

            result1 = llu_module.fetch_from_librelinkup()
            first_count = result1["new_readings"]
            assert first_count > 0

        # Reset in-memory auth cache. File cache still has the token,
        # so llu_login() will skip API calls on second fetch.
        llu_module._llu_auth = None

        # Second fetch with identical data. Since login uses file cache,
        # only the graph GET is made (no connections GET for login).
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=copy.deepcopy(mock_llu_login_response)),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                raise_for_status=MagicMock(),
            )
            # Only graph response needed (login is satisfied by file cache)
            mock_get.return_value.json = MagicMock(
                return_value=copy.deepcopy(mock_llu_graph_response)
            )

            result2 = llu_module.fetch_from_librelinkup()

            # Second fetch should add 0 new readings (all duplicates)
            assert result2["new_readings"] == 0
            assert result2["total_readings"] == first_count

    def test_fetch_handles_login_error(self, llu_module):
        import requests as req
        with patch("requests.post") as mock_post:
            mock_post.side_effect = req.RequestException("Network error")

            result = llu_module.fetch_from_librelinkup()

            assert "error" in result

    def test_fetch_handles_empty_graph_data(self, llu_module, mock_llu_login_response,
                                             mock_llu_connections_response):
        empty_graph = {"status": 0, "data": {"connection": {}, "graphData": []}}

        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[mock_llu_connections_response, empty_graph]),
                raise_for_status=MagicMock(),
            )

            result = llu_module.fetch_from_librelinkup()

            assert "error" not in result
            assert result["new_readings"] == 0


# ============================================================================
# Current Glucose Tests
# ============================================================================

class TestGetCurrentGlucoseLibreLinkUp:
    """Test getting current glucose from LibreLinkUp."""

    def test_returns_current_reading(self, llu_module, mock_llu_login_response,
                                      mock_llu_connections_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[
                    mock_llu_connections_response,  # login connections
                    mock_llu_connections_response,  # current glucose connections
                ]),
                raise_for_status=MagicMock(),
            )

            result = llu_module.get_current_glucose_librelinkup()

            assert "error" not in result
            assert result["glucose"] == 125
            assert result["trend"] == "Flat"
            assert result["status"] == "in range"
            assert result["source"] == "librelinkup"

    def test_returns_correct_status_for_low(self, llu_module, mock_llu_login_response):
        low_connections = {
            "status": 0,
            "data": [{
                "patientId": "patient-456",
                "glucoseMeasurement": {
                    "Value": 60,
                    "TrendArrow": 2,
                    "Timestamp": "1/15/2026 2:30:00 PM",
                },
            }],
        }

        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[
                    low_connections,  # login connections
                    low_connections,  # current glucose
                ]),
                raise_for_status=MagicMock(),
            )

            result = llu_module.get_current_glucose_librelinkup()

            assert result["status"] == "low"
            assert result["trend"] == "FortyFiveDown"

    def test_returns_correct_status_for_high(self, llu_module, mock_llu_login_response):
        high_connections = {
            "status": 0,
            "data": [{
                "patientId": "patient-456",
                "glucoseMeasurement": {
                    "Value": 220,
                    "TrendArrow": 5,
                    "Timestamp": "1/15/2026 2:30:00 PM",
                },
            }],
        }

        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[
                    high_connections,
                    high_connections,
                ]),
                raise_for_status=MagicMock(),
            )

            result = llu_module.get_current_glucose_librelinkup()

            assert result["status"] == "high"
            assert result["trend"] == "SingleUp"

    def test_handles_no_connections(self, llu_module, mock_llu_login_response):
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            empty_conn = {"status": 0, "data": [{"patientId": "p1"}]}
            no_conn = {"status": 0, "data": []}
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[empty_conn, no_conn]),
                raise_for_status=MagicMock(),
            )

            result = llu_module.get_current_glucose_librelinkup()

            assert "error" in result


# ============================================================================
# Data Source Dispatch Tests
# ============================================================================

class TestDataSourceDispatch:
    """Test that the correct data source is used based on configuration."""

    def test_librelinkup_mode_detected(self, llu_module):
        assert llu_module.DATA_SOURCE == llu_module.DATA_SOURCE_LIBRELINKUP

    def test_nightscout_mode_detected(self, ns_module):
        assert ns_module.DATA_SOURCE == ns_module.DATA_SOURCE_NIGHTSCOUT

    def test_fetch_and_store_dispatches_to_librelinkup(self, llu_module):
        with patch.object(llu_module, "fetch_from_librelinkup") as mock_fetch:
            mock_fetch.return_value = {"status": "success", "new_readings": 5}
            result = llu_module.fetch_and_store(days=90)
            mock_fetch.assert_called_once()
            assert result["status"] == "success"

    def test_get_current_glucose_dispatches_to_librelinkup(self, llu_module):
        with patch.object(llu_module, "get_current_glucose_librelinkup") as mock_current:
            mock_current.return_value = {"glucose": 120, "source": "librelinkup"}
            result = llu_module.get_current_glucose()
            mock_current.assert_called_once()
            assert result["source"] == "librelinkup"


# ============================================================================
# Pump Capabilities Tests
# ============================================================================

class TestPumpCapabilitiesLibreLinkUp:
    """Test that pump capabilities correctly report unavailable in LLU mode."""

    def test_pump_not_available(self, llu_module):
        caps = llu_module.detect_pump_capabilities()
        assert caps["has_treatments"] is False
        assert caps["has_devicestatus"] is False
        assert caps["has_profile"] is False
        assert caps["pump_info"] is None
        assert caps["loop_info"] is None

    def test_has_pump_data_returns_false(self, llu_module):
        assert llu_module.has_pump_data() is False


# ============================================================================
# Settings Tests
# ============================================================================

class TestSettingsLibreLinkUp:
    """Test settings/thresholds work correctly without Nightscout."""

    def test_default_thresholds(self, llu_module):
        settings = llu_module.get_nightscout_settings()
        thresholds = settings.get("thresholds", {})
        assert thresholds["bgLow"] == 55
        assert thresholds["bgTargetBottom"] == 70
        assert thresholds["bgTargetTop"] == 180
        assert thresholds["bgHigh"] == 250

    def test_default_units_mgdl(self, llu_module):
        settings = llu_module.get_nightscout_settings()
        assert settings.get("units", "mg/dl") == "mg/dl"

    def test_custom_thresholds_via_env(self, llu_module, monkeypatch):
        monkeypatch.setattr(llu_module, "_cached_settings", None)
        monkeypatch.setenv("CGM_URGENT_LOW", "54")
        monkeypatch.setenv("CGM_TARGET_LOW", "65")
        monkeypatch.setenv("CGM_TARGET_HIGH", "140")
        monkeypatch.setenv("CGM_URGENT_HIGH", "200")
        settings = llu_module.get_nightscout_settings()
        thresholds = settings.get("thresholds", {})
        assert thresholds["bgLow"] == 54
        assert thresholds["bgTargetBottom"] == 65
        assert thresholds["bgTargetTop"] == 140
        assert thresholds["bgHigh"] == 200

    def test_mmol_units_via_env(self, llu_module, monkeypatch):
        monkeypatch.setattr(llu_module, "_cached_settings", None)
        monkeypatch.setenv("CGM_UNITS", "mmol")
        settings = llu_module.get_nightscout_settings()
        assert settings.get("units") == "mmol"


# ============================================================================
# Integration Tests (end-to-end with mocked API)
# ============================================================================

class TestEndToEnd:
    """Test full workflow from fetch to analysis."""

    def test_fetch_then_analyze(self, llu_module, mock_llu_login_response,
                                 mock_llu_connections_response, mock_llu_graph_response):
        """Verify that fetched LibreLinkUp data can be analyzed."""
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[mock_llu_connections_response, mock_llu_graph_response]),
                raise_for_status=MagicMock(),
            )

            # Fetch data
            fetch_result = llu_module.fetch_from_librelinkup()
            assert fetch_result["new_readings"] > 0

            # Now verify the data is in the database and queryable
            conn = sqlite3.connect(llu_module.DB_PATH)
            rows = conn.execute("SELECT sgv FROM readings WHERE sgv > 0").fetchall()
            conn.close()

            values = [r[0] for r in rows]
            assert len(values) > 0

            # Test that our analysis functions work on this data
            stats = llu_module.get_stats(values)
            assert "mean" in stats
            assert "count" in stats
            assert stats["count"] > 0

            tir = llu_module.get_time_in_range(values)
            assert "in_range_pct" in tir

    def test_database_schema_matches(self, llu_module, mock_llu_login_response,
                                      mock_llu_connections_response, mock_llu_graph_response):
        """Verify LibreLinkUp data matches the expected schema."""
        with patch("requests.post") as mock_post, \
             patch("requests.get") as mock_get:
            mock_post.return_value = MagicMock(
                json=MagicMock(return_value=mock_llu_login_response),
                raise_for_status=MagicMock(),
            )
            mock_get.return_value = MagicMock(
                json=MagicMock(side_effect=[mock_llu_connections_response, mock_llu_graph_response]),
                raise_for_status=MagicMock(),
            )

            llu_module.fetch_from_librelinkup()

            conn = sqlite3.connect(llu_module.DB_PATH)
            # Check column names
            cursor = conn.execute("PRAGMA table_info(readings)")
            columns = {row[1] for row in cursor.fetchall()}
            conn.close()

            expected = {"id", "sgv", "date_ms", "date_string", "trend", "direction", "device"}
            assert columns == expected
