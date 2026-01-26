"""
Tests for HTML report generation (generate_html_report function).
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


class TestGenerateHtmlReport:
    """Tests for generate_html_report function."""
    
    def test_generates_html_file(self, cgm_module, populated_db, tmp_path):
        """Should generate an HTML file at the specified path."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        assert "error" not in result
        assert result["status"] == "success"
        assert output_path.exists()
    
    def test_html_contains_chart_js(self, cgm_module, populated_db, tmp_path):
        """Generated HTML should include Chart.js library reference."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        assert "chart.js" in content.lower()
        assert "<canvas" in content
    
    def test_html_contains_annotation_plugin(self, cgm_module, populated_db, tmp_path):
        """Generated HTML should include Chart.js annotation plugin for target range lines."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        assert "chartjs-plugin-annotation" in content.lower()
    
    def test_html_contains_key_sections(self, cgm_module, populated_db, tmp_path):
        """Generated HTML should contain all key sections."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for key sections
        assert "Time in Range" in content
        assert "Modal Day" in content
        assert "Day of Week" in content
        assert "Heatmap" in content
        assert "GMI" in content or "A1C" in content
    
    def test_returns_correct_result_structure(self, cgm_module, populated_db, tmp_path):
        """Result should have expected fields."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        assert "status" in result
        assert "report" in result
        assert "days_analyzed" in result
        assert "readings" in result
        assert "date_range" in result
        assert result["days_analyzed"] == 7
    
    def test_uses_default_output_path(self, cgm_module, populated_db):
        """Should use default output path when none specified."""
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.generate_html_report(days=7)
        
        assert "error" not in result
        assert "nightscout_report.html" in result["report"]
        
        # Clean up
        report_path = Path(result["report"])
        if report_path.exists():
            report_path.unlink()
    
    def test_handles_no_data(self, cgm_module, temp_db):
        """Should return error when no data available."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                result = cgm_module.generate_html_report(days=7)
        
        assert "error" in result
    
    def test_html_is_valid_structure(self, cgm_module, populated_db, tmp_path):
        """Generated HTML should be well-formed."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Basic HTML structure checks
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content
        assert "<head>" in content
        assert "</head>" in content
        assert "<body>" in content
        assert "</body>" in content
    
    def test_mmol_mode(self, cgm_module, populated_db, tmp_path):
        """Should use mmol/L when configured."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=True):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        assert "mmol/L" in content
    
    def test_days_parameter(self, cgm_module, populated_db, tmp_path):
        """Should respect days parameter."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.generate_html_report(
                            days=30,
                            output_path=str(output_path)
                        )
        
        assert result["days_analyzed"] == 30


class TestReportCharts:
    """Tests for specific chart data in the report."""
    
    def test_tir_pie_chart_data(self, cgm_module, populated_db, tmp_path):
        """TIR pie chart should have all categories."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for TIR categories in data
        assert "very_low" in content
        assert "in_range" in content
        assert "very_high" in content
    
    def test_modal_day_chart_data(self, cgm_module, populated_db, tmp_path):
        """Modal day chart should have hourly data."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for modal day data structure
        assert "modalDayData" in content
        assert "median" in content
        assert "p10" in content
        assert "p90" in content
    
    def test_heatmap_data(self, cgm_module, populated_db, tmp_path):
        """Heatmap should have 7 days × 24 hours of data."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for heatmap data
        assert "heatmapTir" in content
        assert "heatmapGrid" in content


class TestReportCliCommand:
    """Tests for the report CLI command."""
    
    def test_report_command_exists(self, cgm_module):
        """The report command should be recognized."""
        import argparse
        
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        
        # This should not raise an exception
        report_parser = subparsers.add_parser("report")
        report_parser.add_argument("--days", type=int, default=90)
        report_parser.add_argument("--output", "-o", type=str)
        report_parser.add_argument("--open", action="store_true")
        
        args = parser.parse_args(["report", "--days", "30"])
        assert args.command == "report"
        assert args.days == 30
    
    def test_report_command_default_values(self, cgm_module):
        """Report command should have sensible defaults."""
        import argparse
        
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        
        report_parser = subparsers.add_parser("report")
        report_parser.add_argument("--days", type=int, default=90)
        report_parser.add_argument("--output", "-o", type=str)
        report_parser.add_argument("--open", action="store_true")
        
        args = parser.parse_args(["report"])
        assert args.days == 90
        assert args.output is None
        assert args.open is False


class TestReportDateControls:
    """Tests for interactive date controls in the report."""
    
    def test_date_controls_present(self, cgm_module, populated_db, tmp_path):
        """Report should include date range controls."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for date control buttons
        assert "date-btn" in content
        assert "7 days" in content
        assert "14 days" in content
        assert "30 days" in content
        assert "90 days" in content
        assert "6 months" in content
        assert "1 year" in content
        assert 'data-days="0"' in content  # "All" button
    
    def test_date_picker_inputs_present(self, cgm_module, populated_db, tmp_path):
        """Report should include custom date picker inputs."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for date inputs
        assert 'id="startDate"' in content
        assert 'id="endDate"' in content
        assert 'type="date"' in content
    
    def test_date_filtering_javascript_functions(self, cgm_module, populated_db, tmp_path):
        """Report should include JavaScript functions for date filtering."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for JS filtering functions
        assert "function setDateRange" in content
        assert "function applyCustomDateRange" in content
        assert "function filterReadingsByDays" in content
        assert "function filterReadingsByDateRange" in content
        assert "function updateAllCharts" in content
    
    def test_all_readings_data_included(self, cgm_module, populated_db, tmp_path):
        """Report should include all readings data for client-side filtering."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for all readings data array
        assert "allReadings" in content
        assert "const allReadings = [" in content


class TestReportColorScheme:
    """Tests for the CGM-style color scheme (blue lows, yellow/red highs)."""
    
    def test_distinct_colors_for_ranges(self, cgm_module, populated_db, tmp_path):
        """Each glucose range should have a distinct color."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for distinct colors - blue for lows, yellow for highs
        assert "#1d4ed8" in content  # Deep blue for very low
        assert "#3b82f6" in content  # Light blue for low
        assert "#10b981" in content  # Green for in-range
        assert "#eab308" in content  # Yellow for high
        assert "#ef4444" in content  # Red for very high
    
    def test_colors_in_javascript(self, cgm_module, populated_db, tmp_path):
        """JavaScript color constants should have correct values."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Verify JS color object has correct structure
        assert "veryLow: '#1d4ed8'" in content
        assert "low: '#3b82f6'" in content
        assert "inRange: '#10b981'" in content
        assert "high: '#eab308'" in content
        assert "veryHigh: '#ef4444'" in content


class TestReportHeatmapHover:
    """Tests for heatmap hover effects and tooltips."""
    
    def test_heatmap_hover_css(self, cgm_module, populated_db, tmp_path):
        """Heatmap cells should have hover CSS styles."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for hover styles
        assert ".heatmap-cell:not(.heatmap-header):not(.heatmap-label):hover" in content
        assert "transform: scale(1.15)" in content
        assert "box-shadow:" in content
        assert "filter: brightness" in content
    
    def test_heatmap_tooltip_css(self, cgm_module, populated_db, tmp_path):
        """Heatmap should have styled tooltip CSS."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for tooltip styles
        assert ".heatmap-cell .tooltip" in content
        assert ".heatmap-cell:hover .tooltip" in content
        assert "display: block" in content
    
    def test_heatmap_tooltip_javascript(self, cgm_module, populated_db, tmp_path):
        """Heatmap should create tooltip elements in JavaScript."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for tooltip creation in JS
        assert "tooltip.className = 'tooltip'" in content
        assert "cell.appendChild(tooltip)" in content
        assert "Good" in content  # Status indicator
        assert "Fair" in content
        assert "Needs work" in content


class TestReportCalculationFunctions:
    """Tests for JavaScript calculation functions used in dynamic updates."""
    
    def test_calcstats_function(self, cgm_module, populated_db, tmp_path):
        """Report should have calcStats function for dynamic recalculation."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        assert "function calcStats(readings)" in content
        assert "tir:" in content  # Returns TIR data
        assert "gmi:" in content  # Returns GMI
        assert "cv:" in content   # Returns CV
    
    def test_build_functions_for_all_charts(self, cgm_module, populated_db, tmp_path):
        """Report should have build functions for all chart types."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for all build functions
        assert "function buildModalDay" in content
        assert "function buildDailyStats" in content
        assert "function buildDowStats" in content
        assert "function buildHistogram" in content
        assert "function buildWeeklyStats" in content
        assert "function buildHeatmap" in content
    
    def test_chart_update_functions(self, cgm_module, populated_db, tmp_path):
        """Report should have functions to update all charts."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for chart instance variables (for updates)
        assert "tirChart =" in content or "tirChart=" in content
        assert "modalChart =" in content or "modalChart=" in content
        assert "dailyChart =" in content or "dailyChart=" in content
        assert "dowChart =" in content or "dowChart=" in content
        assert "histChart =" in content or "histChart=" in content
        assert "weeklyChart =" in content or "weeklyChart=" in content


class TestReportDataIntegrity:
    """Tests for data integrity in the report."""
    
    def test_readings_data_has_required_fields(self, cgm_module, populated_db, tmp_path):
        """All readings data should have sgv, date, and direction fields."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check that readings have required structure
        assert '"sgv":' in content
        assert '"date":' in content
        assert '"direction":' in content
    
    def test_thresholds_passed_to_javascript(self, cgm_module, populated_db, tmp_path):
        """Thresholds should be available in JavaScript for filtering."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=7,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check thresholds object
        assert "thresholds" in content
        assert "urgentLow:" in content
        assert "targetLow:" in content
        assert "targetHigh:" in content
        assert "urgentHigh:" in content
    
    def test_initial_days_parameter_passed(self, cgm_module, populated_db, tmp_path):
        """Initial days parameter should be passed to JavaScript."""
        output_path = tmp_path / "test_report.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_html_report(
                            days=30,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check initial days is set
        assert "currentDays = 30" in content or "let currentDays = 30" in content



class TestGenerateAgpReport:
    """Tests for generate_agp_report function (AGP = Ambulatory Glucose Profile)."""
    
    def test_generates_agp_html_file(self, cgm_module, populated_db, tmp_path):
        """Should generate an AGP HTML file at the specified path."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.generate_agp_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        assert "error" not in result
        assert result["status"] == "success"
        assert output_path.exists()
    
    def test_agp_html_contains_required_sections(self, cgm_module, populated_db, tmp_path):
        """AGP HTML should contain all standard AGP sections."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_agp_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for AGP standard sections
        assert "Ambulatory Glucose Profile" in content
        assert "Glucose Statistics" in content
        assert "Time in Ranges" in content
        assert "Daily Glucose Profiles" in content
        assert "GMI" in content
    
    def test_agp_calculates_standard_percentiles(self, cgm_module, populated_db, tmp_path):
        """AGP should calculate standard percentiles (5, 25, 50, 75, 95)."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_agp_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check that percentile data is present
        assert "p5" in content or "5th" in content
        assert "p25" in content or "25th" in content
        assert "p50" in content or "50th" in content or "Median" in content
        assert "p75" in content or "75th" in content
        assert "p95" in content or "95th" in content
    
    def test_agp_contains_annotation_plugin(self, cgm_module, populated_db, tmp_path):
        """AGP HTML should include Chart.js annotation plugin for target range lines."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_agp_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        assert "chartjs-plugin-annotation" in content.lower()
    
    def test_agp_returns_correct_result_structure(self, cgm_module, populated_db, tmp_path):
        """AGP result should have expected fields including unique_days."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.generate_agp_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        assert "status" in result
        assert "report" in result
        assert "readings" in result
        assert "date_range" in result
        assert "unique_days" in result
        assert result["status"] == "success"
    
    def test_agp_default_14_days(self, cgm_module, populated_db, tmp_path):
        """AGP should default to 14 days, which is the standard AGP period."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        result = cgm_module.generate_agp_report(
                            output_path=str(output_path)
                        )
        
        assert result["days_analyzed"] == 14
    
    def test_agp_is_print_friendly(self, cgm_module, populated_db, tmp_path):
        """AGP should have print-friendly CSS."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_agp_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for print media query
        assert "@media print" in content
        assert "no-print" in content
    
    def test_agp_handles_empty_data(self, cgm_module, temp_db, tmp_path):
        """AGP should handle empty database gracefully."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", temp_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                result = cgm_module.generate_agp_report(
                    days=14,
                    output_path=str(output_path)
                )
        
        assert "error" in result
        assert "No data found" in result["error"]
    
    def test_agp_includes_time_in_range_bar(self, cgm_module, populated_db, tmp_path):
        """AGP should include visual time-in-range bar chart."""
        output_path = tmp_path / "test_agp.html"
        
        with patch.object(cgm_module, "DB_PATH", populated_db):
            with patch.object(cgm_module, "ensure_data", return_value=True):
                with patch.object(cgm_module, "use_mmol", return_value=False):
                    with patch.object(cgm_module, "get_thresholds", return_value={
                        "urgent_low": 55, "target_low": 70,
                        "target_high": 180, "urgent_high": 250
                    }):
                        cgm_module.generate_agp_report(
                            days=14,
                            output_path=str(output_path)
                        )
        
        content = output_path.read_text(encoding="utf-8")
        
        # Check for TIR bar elements
        assert "tir-bar" in content
        assert "tir-very-low" in content
        assert "tir-low" in content
        assert "tir-in-range" in content
        assert "tir-high" in content
        assert "tir-very-high" in content
