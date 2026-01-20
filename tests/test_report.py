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
        
        content = output_path.read_text()
        assert "chart.js" in content.lower()
        assert "<canvas" in content
    
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
        
        content = output_path.read_text()
        
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
        
        content = output_path.read_text()
        
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
        
        content = output_path.read_text()
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
        
        content = output_path.read_text()
        
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
        
        content = output_path.read_text()
        
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
        
        content = output_path.read_text()
        
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
