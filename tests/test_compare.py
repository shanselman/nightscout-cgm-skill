"""
Tests for period comparison functionality.
"""
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


class TestParsePeriod:
    """Tests for parse_period() function."""
    
    def test_parse_last_n_days(self, cgm_module):
        """Should parse 'last N days' correctly."""
        start, end, desc = cgm_module.parse_period("last 7 days")
        assert desc == "Last 7 days"
        
        # Check that it's approximately 7 days
        delta = (end - start).days
        assert delta == 7
    
    def test_parse_previous_n_days(self, cgm_module):
        """Should parse 'previous N days' correctly."""
        start, end, desc = cgm_module.parse_period("previous 7 days")
        assert desc == "Previous 7 days"
        
        # Check that it's approximately 7 days
        delta = (end - start).days
        assert delta == 7
        
        # End should be before now
        now = datetime.now(timezone.utc)
        assert end < now
    
    def test_parse_this_week(self, cgm_module):
        """Should parse 'this week' correctly."""
        start, end, desc = cgm_module.parse_period("this week")
        assert desc == "This week"
        
        # Start should be Monday of this week
        assert start.weekday() == 0  # Monday
    
    def test_parse_last_week(self, cgm_module):
        """Should parse 'last week' correctly."""
        start, end, desc = cgm_module.parse_period("last week")
        assert desc == "Last week"
        
        # Start should be Monday
        assert start.weekday() == 0
        
        # Should be 7 days
        delta = (end - start).days
        assert delta == 7
    
    def test_parse_this_month(self, cgm_module):
        """Should parse 'this month' correctly."""
        start, end, desc = cgm_module.parse_period("this month")
        
        # Start should be first day of current month
        now = datetime.now(timezone.utc)
        assert start.day == 1
        assert start.month == now.month
        assert start.year == now.year
    
    def test_parse_last_month(self, cgm_module):
        """Should parse 'last month' correctly."""
        start, end, desc = cgm_module.parse_period("last month")
        
        # Start should be first day of last month
        assert start.day == 1
        
        # End should be first day of current month
        now = datetime.now(timezone.utc)
        assert end.month == now.month
    
    def test_parse_month_by_name(self, cgm_module):
        """Should parse month names like 'January'."""
        start, end, desc = cgm_module.parse_period("january")
        
        assert start.month == 1
        assert start.day == 1
        assert "January" in desc
    
    def test_parse_invalid_period(self, cgm_module):
        """Should raise ValueError for invalid period."""
        with pytest.raises(ValueError, match="Could not parse period"):
            cgm_module.parse_period("invalid period string")


@pytest.fixture
def multi_week_db(temp_db):
    """Create a database with multiple weeks of data for comparison."""
    conn = sqlite3.connect(temp_db)
    
    # Generate readings for last 4 weeks
    now = datetime.now(timezone.utc)
    readings = []
    
    for week in range(4):
        for day in range(7):
            day_offset = week * 7 + day
            day_start = now - timedelta(days=day_offset)
            
            for hour in range(24):
                for minute in range(0, 60, 5):
                    dt = day_start.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    date_ms = int(dt.timestamp() * 1000)
                    date_string = dt.isoformat().replace("+00:00", "Z")
                    
                    # Week 0 (most recent) has better control
                    # Week 1-3 (older) has worse control
                    if week == 0:
                        base = 120  # Better average
                    else:
                        base = 150  # Worse average
                    
                    # Add variation
                    import random
                    random.seed(date_ms)
                    variation = random.randint(-15, 15)
                    sgv = max(40, min(400, base + variation))
                    
                    readings.append((
                        f"entry_{date_ms}",
                        sgv,
                        date_ms,
                        date_string,
                        5,  # trend
                        "Flat",
                        "test_device"
                    ))
    
    conn.executemany(
        "INSERT OR REPLACE INTO readings (id, sgv, date_ms, date_string, trend, direction, device) VALUES (?, ?, ?, ?, ?, ?, ?)",
        readings
    )
    conn.commit()
    conn.close()
    
    return temp_db


class TestComparePeriods:
    """Tests for compare_periods() function."""
    
    def test_compare_last_week_vs_previous(self, cgm_module, multi_week_db, monkeypatch):
        """Should compare last 7 days vs previous 7 days."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        # Mock ensure_data to return True
        with patch.object(cgm_module, "ensure_data", return_value=True):
            result = cgm_module.compare_periods("last 7 days", "previous 7 days")
        
        # Should return comparison structure
        assert "comparison" in result
        assert "period1" in result["comparison"]
        assert "period2" in result["comparison"]
        assert "deltas" in result
        assert "summary" in result
        
        # Both periods should have data
        assert result["comparison"]["period1"]["readings"] > 0
        assert result["comparison"]["period2"]["readings"] > 0
        
        # Deltas should be calculated
        assert "average_glucose" in result["deltas"]
        assert "time_in_range" in result["deltas"]
        assert "gmi_estimated_a1c" in result["deltas"]
        assert "cv_variability" in result["deltas"]
    
    def test_compare_includes_key_metrics(self, cgm_module, multi_week_db, monkeypatch):
        """Should include all key metrics in comparison."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        with patch.object(cgm_module, "ensure_data", return_value=True):
            result = cgm_module.compare_periods("last 7 days", "previous 7 days")
        
        # Period data should include key metrics
        for period in ["period1", "period2"]:
            period_data = result["comparison"][period]
            assert "statistics" in period_data
            assert "time_in_range" in period_data
            assert "gmi_estimated_a1c" in period_data
            assert "cv_variability" in period_data
    
    def test_compare_calculates_deltas(self, cgm_module, multi_week_db, monkeypatch):
        """Should calculate deltas with correct structure."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        with patch.object(cgm_module, "ensure_data", return_value=True):
            result = cgm_module.compare_periods("last 7 days", "previous 7 days")
        
        # Check delta structure
        delta = result["deltas"]["time_in_range"]
        assert "value" in delta
        assert "change" in delta
        assert delta["change"] in ["improved", "worsened", "unchanged"]
    
    def test_compare_identifies_improvements(self, cgm_module, multi_week_db, monkeypatch):
        """Should identify improvements in summary."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        with patch.object(cgm_module, "ensure_data", return_value=True):
            result = cgm_module.compare_periods("last 7 days", "previous 7 days")
        
        # Summary should have improvements and regressions lists
        assert "key_improvements" in result["summary"]
        assert "key_regressions" in result["summary"]
        assert isinstance(result["summary"]["key_improvements"], list)
        assert isinstance(result["summary"]["key_regressions"], list)
    
    def test_compare_with_no_data_period1(self, cgm_module, temp_db, monkeypatch):
        """Should return error if period1 has no data."""
        monkeypatch.setattr(cgm_module, "DB_PATH", temp_db)
        
        with patch.object(cgm_module, "ensure_data", return_value=True):
            result = cgm_module.compare_periods("last 365 days", "previous 7 days")
        
        # Should return error since empty DB
        assert "error" in result
    
    def test_compare_invalid_period(self, cgm_module, multi_week_db, monkeypatch):
        """Should return error for invalid period string."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        result = cgm_module.compare_periods("invalid", "last 7 days")
        
        assert "error" in result
        assert "Could not parse period" in result["error"]


class TestCompareCLI:
    """Tests for compare CLI command."""
    
    def test_compare_command_exists(self, cgm_module):
        """Compare command should be registered."""
        with patch.object(sys, "argv", ["cgm.py", "compare", "--help"]):
            with pytest.raises(SystemExit):
                cgm_module.main()
    
    def test_compare_requires_both_periods(self, cgm_module):
        """Compare command should require both --period1 and --period2."""
        with patch.object(sys, "argv", ["cgm.py", "compare", "--period1", "last 7 days"]):
            with pytest.raises(SystemExit):
                cgm_module.main()
    
    def test_compare_command_calls_function(self, cgm_module, multi_week_db, monkeypatch):
        """Compare command should call compare_periods function."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        with patch.object(cgm_module, "compare_periods") as mock_compare:
            mock_compare.return_value = {"comparison": {}, "deltas": {}}
            with patch.object(sys, "argv", [
                "cgm.py", "compare",
                "--period1", "last 7 days",
                "--period2", "previous 7 days"
            ]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_compare.assert_called_once_with("last 7 days", "previous 7 days")


class TestCompareEdgeCases:
    """Tests for edge cases in period comparison."""
    
    def test_compare_same_period(self, cgm_module, multi_week_db, monkeypatch):
        """Should handle comparing identical periods."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        with patch.object(cgm_module, "ensure_data", return_value=True):
            result = cgm_module.compare_periods("last 7 days", "last 7 days")
        
        # Should work, but deltas should be zero or near-zero
        if "error" not in result:
            # All deltas should be close to zero
            assert abs(result["deltas"]["time_in_range"]["value"]) < 1
    
    def test_compare_different_length_periods(self, cgm_module, multi_week_db, monkeypatch):
        """Should handle comparing periods of different lengths."""
        monkeypatch.setattr(cgm_module, "DB_PATH", multi_week_db)
        
        with patch.object(cgm_module, "ensure_data", return_value=True):
            result = cgm_module.compare_periods("last 7 days", "last month")
        
        # Should work - we're comparing statistics, not raw counts
        if "error" not in result:
            assert result["comparison"]["period1"]["readings"] > 0
            assert result["comparison"]["period2"]["readings"] > 0
