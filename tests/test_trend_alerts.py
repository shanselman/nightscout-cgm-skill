"""
Tests for trend alerts detection (detect_trend_alerts function).
"""
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class TestDetectTrendAlerts:
    """Tests for detect_trend_alerts function."""
    
    def test_basic_structure(self, cgm_module, populated_db):
        """Should return expected structure."""
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.detect_trend_alerts(days=7, min_occurrences=2)
                        
                        # Check structure
                        assert "days_analyzed" in result
                        assert "alert_count" in result
                        assert "alerts" in result
                        assert "thresholds" in result
                        assert isinstance(result["alerts"], list)
    
    def test_returns_error_when_no_data(self, cgm_module, temp_db):
        """Should return error when no data available."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            with patch.object(cgm_module, "ensure_data", return_value=False):
                result = cgm_module.detect_trend_alerts(days=7)
                assert "error" in result
    
    def test_detects_recurring_lows(self, cgm_module, temp_db):
        """Should detect recurring low patterns."""
        # Create database with recurring lows at 2am
        conn = sqlite3.connect(temp_db)
        now = datetime.now(timezone.utc)
        
        # Insert readings with recurring lows at 2am over 5 days
        readings = []
        for day_offset in range(7):
            day_start = now - timedelta(days=day_offset)
            for hour in range(24):
                for minute in range(0, 60, 30):
                    dt = day_start.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    date_ms = int(dt.timestamp() * 1000)
                    date_string = dt.isoformat().replace("+00:00", "Z")
                    
                    # Make 2am consistently low for pattern detection
                    if hour == 2 and day_offset < 5:
                        sgv = 60  # Low value
                    else:
                        sgv = 120  # Normal value
                    
                    readings.append((
                        f"entry_{date_ms}",
                        sgv,
                        date_ms,
                        date_string,
                        5,
                        "Flat",
                        "test_device"
                    ))
        
        conn.executemany(
            "INSERT OR REPLACE INTO readings (id, sgv, date_ms, date_string, trend, direction, device) VALUES (?, ?, ?, ?, ?, ?, ?)",
            readings
        )
        conn.commit()
        conn.close()
        
        with patch.object(cgm_module, "DB_PATH", temp_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.detect_trend_alerts(days=7, min_occurrences=2)
                        
                        # Should detect the recurring lows at 2am
                        assert result["alert_count"] > 0
                        
                        # Check that there's at least one low-related alert
                        low_alerts = [a for a in result["alerts"] if a["category"] == "recurring_lows"]
                        assert len(low_alerts) > 0
    
    def test_detects_recurring_highs(self, cgm_module, temp_db):
        """Should detect recurring high patterns."""
        # Create database with recurring highs at 12pm (lunch)
        conn = sqlite3.connect(temp_db)
        now = datetime.now(timezone.utc)
        
        # Insert readings with recurring highs at 12pm over multiple days
        readings = []
        for day_offset in range(7):
            day_start = now - timedelta(days=day_offset)
            for hour in range(24):
                for minute in range(0, 60, 30):
                    dt = day_start.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    date_ms = int(dt.timestamp() * 1000)
                    date_string = dt.isoformat().replace("+00:00", "Z")
                    
                    # Make 12pm consistently high for pattern detection
                    if hour == 12 and day_offset < 5:
                        sgv = 200  # High value
                    else:
                        sgv = 120  # Normal value
                    
                    readings.append((
                        f"entry_{date_ms}",
                        sgv,
                        date_ms,
                        date_string,
                        5,
                        "Flat",
                        "test_device"
                    ))
        
        conn.executemany(
            "INSERT OR REPLACE INTO readings (id, sgv, date_ms, date_string, trend, direction, device) VALUES (?, ?, ?, ?, ?, ?, ?)",
            readings
        )
        conn.commit()
        conn.close()
        
        with patch.object(cgm_module, "DB_PATH", temp_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.detect_trend_alerts(days=7, min_occurrences=2)
                        
                        # Should detect the recurring highs at 12pm
                        assert result["alert_count"] > 0
                        
                        # Check that there's at least one high-related alert
                        high_alerts = [a for a in result["alerts"] if a["category"] == "recurring_highs"]
                        assert len(high_alerts) > 0
    
    def test_alert_severity_levels(self, cgm_module, temp_db):
        """Should assign appropriate severity levels."""
        # Create database with overnight lows (should be high severity)
        conn = sqlite3.connect(temp_db)
        now = datetime.now(timezone.utc)
        
        readings = []
        for day_offset in range(7):
            day_start = now - timedelta(days=day_offset)
            for hour in range(24):
                for minute in range(0, 60, 30):
                    dt = day_start.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    date_ms = int(dt.timestamp() * 1000)
                    date_string = dt.isoformat().replace("+00:00", "Z")
                    
                    # Make 2am (overnight) consistently low - should be high severity
                    if hour == 2 and day_offset < 5:
                        sgv = 60  # Low value
                    else:
                        sgv = 120  # Normal value
                    
                    readings.append((
                        f"entry_{date_ms}",
                        sgv,
                        date_ms,
                        date_string,
                        5,
                        "Flat",
                        "test_device"
                    ))
        
        conn.executemany(
            "INSERT OR REPLACE INTO readings (id, sgv, date_ms, date_string, trend, direction, device) VALUES (?, ?, ?, ?, ?, ?, ?)",
            readings
        )
        conn.commit()
        conn.close()
        
        with patch.object(cgm_module, "DB_PATH", temp_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.detect_trend_alerts(days=7, min_occurrences=2)
                        
                        # Check that alerts have severity field
                        for alert in result["alerts"]:
                            assert "severity" in alert
                            assert alert["severity"] in ["high", "medium", "low"]
    
    def test_min_occurrences_threshold(self, cgm_module, temp_db):
        """Should respect min_occurrences threshold."""
        # Create database with only 1 low event
        conn = sqlite3.connect(temp_db)
        now = datetime.now(timezone.utc)
        
        readings = []
        for day_offset in range(7):
            day_start = now - timedelta(days=day_offset)
            for hour in range(24):
                dt = day_start.replace(hour=hour, minute=0, second=0, microsecond=0)
                date_ms = int(dt.timestamp() * 1000)
                date_string = dt.isoformat().replace("+00:00", "Z")
                
                # Only one low event
                if hour == 2 and day_offset == 0:
                    sgv = 60  # Low value
                else:
                    sgv = 120  # Normal value
                
                readings.append((
                    f"entry_{date_ms}",
                    sgv,
                    date_ms,
                    date_string,
                    5,
                    "Flat",
                    "test_device"
                ))
        
        conn.executemany(
            "INSERT OR REPLACE INTO readings (id, sgv, date_ms, date_string, trend, direction, device) VALUES (?, ?, ?, ?, ?, ?, ?)",
            readings
        )
        conn.commit()
        conn.close()
        
        with patch.object(cgm_module, "DB_PATH", temp_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        # With min_occurrences=2, should not trigger alert
                        result = cgm_module.detect_trend_alerts(days=7, min_occurrences=2)
                        
                        # Should have no alerts (only 1 occurrence, needs 2)
                        low_alerts = [a for a in result["alerts"] if a["category"] == "recurring_lows"]
                        assert len(low_alerts) == 0
    
    def test_alert_categories(self, cgm_module, populated_db):
        """Should categorize alerts correctly."""
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.detect_trend_alerts(days=7, min_occurrences=2)
                        
                        # Check that all alerts have proper categories
                        valid_categories = [
                            "recurring_lows", 
                            "recurring_highs", 
                            "trend_improvement",
                            "trend_worsening"
                        ]
                        
                        for alert in result["alerts"]:
                            assert "category" in alert
                            assert alert["category"] in valid_categories
