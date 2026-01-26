"""
Tests for Weekly Summary enhancements including:
- Week-over-week TIR trend
- Summary text for each week (best day)
- Mini sparkline data
"""
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


class TestWeeklySummaryEnhancements:
    """Tests for enhanced weekly summary features."""
    
    def test_weekly_stats_include_daily_tir(self, cgm_module, populated_db, tmp_path):
        """Weekly stats should include daily TIR breakdown for sparkline."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=21,  # 3 weeks
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check that daily_tir data is present in the output
        assert "daily_tir" in content
        
    def test_weekly_stats_include_best_day(self, cgm_module, populated_db, tmp_path):
        """Weekly stats should include best day information."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for best day data in the output
        assert "best_day" in content
        assert "best_day_tir" in content
        
    def test_weekly_stats_include_tir_change(self, cgm_module, populated_db, tmp_path):
        """Weekly stats should include week-over-week TIR change."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=21,  # Need multiple weeks for trend
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for TIR change data
        assert "tir_change" in content
        
    def test_weekly_summary_text_container_exists(self, cgm_module, populated_db, tmp_path):
        """Weekly summary should have a text container for displaying summaries."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for weekly summary text container
        assert 'id="weeklySummaryText"' in content
        
    def test_weekly_chart_has_enhanced_tooltip(self, cgm_module, populated_db, tmp_path):
        """Weekly chart should have enhanced tooltip with trend and best day."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for tooltip customization in the chart
        assert "afterBody" in content
        assert "Best day:" in content
        assert "Trend:" in content
        
    def test_weekly_summary_update_function_exists(self, cgm_module, populated_db, tmp_path):
        """Should have a function to update weekly summary text."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for the update function
        assert "updateWeeklySummaryText" in content
        
    def test_weekly_summary_sparkline_visualization(self, cgm_module, populated_db, tmp_path):
        """Weekly summary tooltip should include text-based sparkline."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for sparkline in tooltip
        assert "Daily:" in content
        assert "M T W T F S S" in content  # Day labels
