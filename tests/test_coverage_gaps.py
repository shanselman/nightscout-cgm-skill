"""
Tests specifically targeting coverage gaps identified in the coverage report.
These tests focus on error handling, edge cases, and features not covered by existing tests.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestConfigFileErrorHandling:
    """Test config file save/load error handling."""

    def test_save_config_handles_io_error(self, cgm_module, tmp_path, monkeypatch):
        """Test that _save_config gracefully handles IOError."""
        # Point to a directory that exists but make file read-only
        config_path = tmp_path / "config.json"
        config_path.write_text('{}')
        config_path.chmod(0o444)  # Read-only
        
        # Point CONFIG_PATH to our test file
        monkeypatch.setattr(cgm_module, 'CONFIG_PATH', config_path)
        
        # This should not raise an exception
        cgm_module._save_config({"test": "value"})
        
        # File should still have old content (write failed silently)
        assert config_path.read_text() == '{}'


class TestPeriodParsingEdgeCases:
    """Test edge cases in parse_period function."""

    def test_parse_month_by_name_with_year(self, cgm_module):
        """Test parsing month name with explicit year."""
        start, end, label = cgm_module.parse_period("january 2025")
        
        assert start.year == 2025
        assert start.month == 1
        assert end.year == 2025
        assert end.month == 2

    def test_parse_month_name_december(self, cgm_module):
        """Test parsing December (edge case for month+1)."""
        start, end, label = cgm_module.parse_period("december 2025")
        
        assert start.month == 12
        assert start.year == 2025
        assert end.month == 1
        assert end.year == 2026

    def test_invalid_period_raises_error(self, cgm_module):
        """Test that invalid period strings raise ValueError."""
        with pytest.raises(ValueError, match="Could not parse period"):
            cgm_module.parse_period("not a valid period")


class TestSettingsApiErrorHandling:
    """Test error handling in get_nightscout_settings."""

    def test_settings_api_invalid_json(self, cgm_module):
        """Test handling of invalid JSON from settings API."""
        # Mock API to return invalid JSON
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            # Reset cache
            cgm_module._cached_settings = None
            
            settings = cgm_module.get_nightscout_settings()
            
            # Should return empty dict on error
            assert settings == {}

    def test_settings_api_non_dict_response(self, cgm_module):
        """Test handling when settings API returns non-dict."""
        # Mock API to return a list instead of dict
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = ["not", "a", "dict"]
        mock_response.raise_for_status.return_value = None
        
        with patch('requests.get', return_value=mock_response):
            # Reset cache
            cgm_module._cached_settings = None
            
            settings = cgm_module.get_nightscout_settings()
            
            # Should return empty dict
            assert settings == {}


class TestRequestExceptionHandling:
    """Test various RequestException handling paths."""

    def test_devicestatus_network_error(self, cgm_module):
        """Test that devicestatus network errors are handled gracefully."""
        import requests
        
        def mock_get(url, **kwargs):
            if "devicestatus" in url:
                raise requests.RequestException("Network timeout")
            # Return success for other endpoints
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            return mock_resp
        
        with patch('requests.get', side_effect=mock_get):
            # Reset cache
            cgm_module._pump_capabilities = None
            
            result = cgm_module.detect_pump_capabilities()
            
            # Should complete without error
            assert result is not None
            assert "has_devicestatus" in result

    def test_profile_network_error(self, cgm_module):
        """Test that profile endpoint network errors are handled gracefully."""
        import requests
        
        def mock_get(url, **kwargs):
            if "profile" in url:
                raise requests.RequestException("Network timeout")
            # Return success for other endpoints
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            return mock_resp
        
        with patch('requests.get', side_effect=mock_get):
            # Reset cache
            cgm_module._pump_capabilities = None
            
            result = cgm_module.detect_pump_capabilities()
            
            # Should complete without error
            assert result is not None
            assert "has_profile" in result
