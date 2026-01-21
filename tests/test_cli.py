"""
Tests for CLI argument parsing and main() function.
"""
import sys
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO


class TestMainArgumentParsing:
    """Tests for CLI argument parsing."""
    
    def test_current_command(self, cgm_module):
        """'current' command should work."""
        with patch.object(cgm_module, "get_current_glucose") as mock_get:
            mock_get.return_value = {"glucose": 120, "status": "in range"}
            with patch.object(sys, "argv", ["cgm.py", "current"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_get.assert_called_once()
    
    def test_analyze_command(self, cgm_module):
        """'analyze' command should work."""
        with patch.object(cgm_module, "analyze_cgm") as mock_analyze:
            mock_analyze.return_value = {"readings": 100}
            with patch.object(sys, "argv", ["cgm.py", "analyze"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_analyze.assert_called_once()
    
    def test_analyze_with_days(self, cgm_module):
        """'analyze --days N' should pass days parameter."""
        with patch.object(cgm_module, "analyze_cgm") as mock_analyze:
            mock_analyze.return_value = {"readings": 100}
            with patch.object(sys, "argv", ["cgm.py", "analyze", "--days", "30"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_analyze.assert_called_once_with(30)
    
    def test_refresh_command(self, cgm_module):
        """'refresh' command should work."""
        with patch.object(cgm_module, "fetch_and_store") as mock_fetch:
            mock_fetch.return_value = {"new_readings": 50}
            with patch.object(sys, "argv", ["cgm.py", "refresh"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_fetch.assert_called_once()
    
    def test_patterns_command(self, cgm_module):
        """'patterns' command should work."""
        with patch.object(cgm_module, "find_patterns") as mock_patterns:
            mock_patterns.return_value = {"insights": {}}
            with patch.object(sys, "argv", ["cgm.py", "patterns"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_patterns.assert_called_once()
    
    def test_query_command(self, cgm_module):
        """'query' command should work."""
        with patch.object(cgm_module, "query_patterns") as mock_query:
            mock_query.return_value = {"statistics": {}}
            with patch.object(sys, "argv", ["cgm.py", "query"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_query.assert_called_once()
    
    def test_query_with_filters(self, cgm_module):
        """'query' with filters should pass parameters."""
        with patch.object(cgm_module, "query_patterns") as mock_query:
            mock_query.return_value = {"statistics": {}}
            with patch.object(sys, "argv", [
                "cgm.py", "query", 
                "--day", "Tuesday",
                "--hour-start", "11",
                "--hour-end", "14"
            ]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_query.assert_called_once()
                    call_kwargs = mock_query.call_args
                    assert call_kwargs[1]["day_of_week"] == "Tuesday"
                    assert call_kwargs[1]["hour_start"] == 11
                    assert call_kwargs[1]["hour_end"] == 14


class TestDayCommand:
    """Tests for 'day' command parsing."""
    
    def test_day_command_basic(self, cgm_module):
        """'day' command should work with date argument."""
        with patch.object(cgm_module, "view_day") as mock_view:
            mock_view.return_value = {"date": "2026-01-16", "readings": []}
            with patch.object(sys, "argv", ["cgm.py", "day", "yesterday"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_view.assert_called_once()
                    assert mock_view.call_args[0][0] == "yesterday"
    
    def test_day_command_with_hours(self, cgm_module):
        """'day' command with hour filters."""
        with patch.object(cgm_module, "view_day") as mock_view:
            mock_view.return_value = {"date": "2026-01-16", "readings": []}
            with patch.object(sys, "argv", [
                "cgm.py", "day", "2026-01-16",
                "--hour-start", "11",
                "--hour-end", "14"
            ]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_view.assert_called_once()
                    call_kwargs = mock_view.call_args[1]
                    assert call_kwargs["hour_start"] == 11
                    assert call_kwargs["hour_end"] == 14


class TestWorstCommand:
    """Tests for 'worst' command parsing."""
    
    def test_worst_command_basic(self, cgm_module):
        """'worst' command should work."""
        with patch.object(cgm_module, "find_worst_days") as mock_worst:
            mock_worst.return_value = {"worst_days": []}
            with patch.object(sys, "argv", ["cgm.py", "worst"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_worst.assert_called_once()
    
    def test_worst_command_with_options(self, cgm_module):
        """'worst' command with all options."""
        with patch.object(cgm_module, "find_worst_days") as mock_worst:
            mock_worst.return_value = {"worst_days": []}
            with patch.object(sys, "argv", [
                "cgm.py", "worst",
                "--days", "21",
                "--hour-start", "11",
                "--hour-end", "14",
                "--limit", "3"
            ]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    call_kwargs = mock_worst.call_args[1]
                    assert call_kwargs["days"] == 21
                    assert call_kwargs["hour_start"] == 11
                    assert call_kwargs["hour_end"] == 14
                    assert call_kwargs["limit"] == 3


class TestChartCommand:
    """Tests for 'chart' command parsing."""
    
    def test_chart_sparkline(self, cgm_module):
        """'chart --sparkline' should call show_sparkline."""
        with patch.object(cgm_module, "show_sparkline") as mock_spark:
            with patch.object(sys, "argv", ["cgm.py", "chart", "--sparkline"]):
                with pytest.raises(SystemExit) as exc_info:
                    cgm_module.main()
                # Chart commands exit with 0
                assert exc_info.value.code == 0
                mock_spark.assert_called_once()
    
    def test_chart_sparkline_with_hours(self, cgm_module):
        """'chart --sparkline --hours N' should pass hours."""
        with patch.object(cgm_module, "show_sparkline") as mock_spark:
            with patch.object(sys, "argv", [
                "cgm.py", "chart", "--sparkline", "--hours", "6"
            ]):
                with pytest.raises(SystemExit):
                    cgm_module.main()
                call_kwargs = mock_spark.call_args[1]
                assert call_kwargs["hours"] == 6
    
    def test_chart_sparkline_with_date(self, cgm_module):
        """'chart --date' should call show_sparkline with date."""
        with patch.object(cgm_module, "show_sparkline") as mock_spark:
            with patch.object(sys, "argv", [
                "cgm.py", "chart", "--date", "yesterday",
                "--hour-start", "11", "--hour-end", "14"
            ]):
                with pytest.raises(SystemExit):
                    cgm_module.main()
                call_kwargs = mock_spark.call_args[1]
                assert call_kwargs["date_str"] == "yesterday"
                assert call_kwargs["hour_start"] == 11
                assert call_kwargs["hour_end"] == 14
    
    def test_chart_heatmap(self, cgm_module):
        """'chart --heatmap' should call show_heatmap."""
        with patch.object(cgm_module, "show_heatmap") as mock_heatmap:
            with patch.object(sys, "argv", ["cgm.py", "chart", "--heatmap"]):
                with pytest.raises(SystemExit):
                    cgm_module.main()
                mock_heatmap.assert_called_once()
    
    def test_chart_week(self, cgm_module):
        """'chart --week' should call show_sparkline_week."""
        with patch.object(cgm_module, "show_sparkline_week") as mock_week:
            with patch.object(sys, "argv", ["cgm.py", "chart", "--week"]):
                with pytest.raises(SystemExit):
                    cgm_module.main()
                mock_week.assert_called_once()
    
    def test_chart_day(self, cgm_module):
        """'chart --day NAME' should call show_day_chart."""
        with patch.object(cgm_module, "show_day_chart") as mock_day:
            with patch.object(sys, "argv", [
                "cgm.py", "chart", "--day", "Saturday"
            ]):
                with pytest.raises(SystemExit):
                    cgm_module.main()
                mock_day.assert_called_once()
                assert mock_day.call_args[0][0] == "Saturday"
    
    def test_chart_color_flag(self, cgm_module):
        """'--color' flag should be passed to chart functions."""
        with patch.object(cgm_module, "show_sparkline") as mock_spark:
            with patch.object(sys, "argv", [
                "cgm.py", "chart", "--sparkline", "--color"
            ]):
                with pytest.raises(SystemExit):
                    cgm_module.main()
                call_kwargs = mock_spark.call_args[1]
                assert call_kwargs["use_color"] is True
    
    def test_chart_default_is_heatmap(self, cgm_module):
        """'chart' with no options should default to heatmap."""
        with patch.object(cgm_module, "show_heatmap") as mock_heatmap:
            with patch.object(sys, "argv", ["cgm.py", "chart"]):
                with pytest.raises(SystemExit):
                    cgm_module.main()
                mock_heatmap.assert_called_once()


class TestNoCommand:
    """Tests for when no command is provided."""
    
    def test_no_command_shows_help(self, cgm_module, capsys):
        """No command should show help."""
        with patch.object(sys, "argv", ["cgm.py"]):
            with pytest.raises(SystemExit) as exc_info:
                cgm_module.main()
            # Should exit with error
            assert exc_info.value.code == 1
            
            captured = capsys.readouterr()
            # Help should be printed
            assert "usage:" in captured.out.lower() or "usage:" in captured.err.lower() or len(captured.out) > 0


class TestInvalidArguments:
    """Tests for invalid arguments."""
    
    def test_invalid_command(self, cgm_module):
        """Invalid command should show error."""
        with patch.object(sys, "argv", ["cgm.py", "invalid_command"]):
            with pytest.raises(SystemExit) as exc_info:
                cgm_module.main()
            # Should exit with error
            assert exc_info.value.code != 0
    
    def test_invalid_hour_range(self, cgm_module):
        """Invalid hour values should be rejected."""
        with patch.object(sys, "argv", [
            "cgm.py", "query", "--hour-start", "25"
        ]):
            with pytest.raises(SystemExit) as exc_info:
                cgm_module.main()
            assert exc_info.value.code != 0
    
    def test_day_missing_date(self, cgm_module):
        """'day' without date should error."""
        with patch.object(sys, "argv", ["cgm.py", "day"]):
            with pytest.raises(SystemExit) as exc_info:
                cgm_module.main()
            assert exc_info.value.code != 0


class TestOutputFormat:
    """Tests for output formatting."""
    
    def test_json_output(self, cgm_module, capsys):
        """Commands should output valid JSON."""
        import json
        
        with patch.object(cgm_module, "get_current_glucose") as mock_get:
            mock_get.return_value = {"glucose": 120, "status": "in range"}
            with patch.object(sys, "argv", ["cgm.py", "current"]):
                try:
                    cgm_module.main()
                except SystemExit:
                    pass
                
                captured = capsys.readouterr()
                # Should be valid JSON
                result = json.loads(captured.out)
                assert "glucose" in result


class TestGoalCommand:
    """Tests for 'goal' command parsing."""
    
    def test_goal_set_tir(self, cgm_module):
        """'goal set --tir' command should work."""
        with patch.object(cgm_module, "set_goal") as mock_set:
            mock_set.return_value = {"status": "success", "metric": "tir", "target": 70}
            with patch.object(sys, "argv", ["cgm.py", "goal", "set", "--tir", "70"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_set.assert_called_once_with("tir", 70.0)
    
    def test_goal_set_cv(self, cgm_module):
        """'goal set --cv' command should work."""
        with patch.object(cgm_module, "set_goal") as mock_set:
            mock_set.return_value = {"status": "success", "metric": "cv", "target": 33}
            with patch.object(sys, "argv", ["cgm.py", "goal", "set", "--cv", "33"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_set.assert_called_once_with("cv", 33.0)
    
    def test_goal_set_multiple(self, cgm_module):
        """'goal set' with multiple goals should work."""
        with patch.object(cgm_module, "set_goal") as mock_set:
            mock_set.return_value = {"status": "success"}
            with patch.object(sys, "argv", ["cgm.py", "goal", "set", "--tir", "70", "--cv", "33"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    assert mock_set.call_count == 2
    
    def test_goal_view(self, cgm_module):
        """'goal view' command should work."""
        with patch.object(cgm_module, "get_goals") as mock_get:
            mock_get.return_value = {"goals": {"tir": {"target": 70}}}
            with patch.object(sys, "argv", ["cgm.py", "goal", "view"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_get.assert_called_once()
    
    def test_goal_clear_all(self, cgm_module):
        """'goal clear' without metric should clear all."""
        with patch.object(cgm_module, "clear_goal") as mock_clear:
            mock_clear.return_value = {"status": "success", "message": "All goals cleared"}
            with patch.object(sys, "argv", ["cgm.py", "goal", "clear"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_clear.assert_called_once_with(None)
    
    def test_goal_clear_specific(self, cgm_module):
        """'goal clear <metric>' should clear specific goal."""
        with patch.object(cgm_module, "clear_goal") as mock_clear:
            mock_clear.return_value = {"status": "success", "message": "Goal cleared: tir"}
            with patch.object(sys, "argv", ["cgm.py", "goal", "clear", "tir"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_clear.assert_called_once_with("tir")
    
    def test_goal_progress(self, cgm_module):
        """'goal progress' command should work."""
        with patch.object(cgm_module, "calculate_goal_progress") as mock_progress:
            mock_progress.return_value = {"progress": {}}
            with patch.object(sys, "argv", ["cgm.py", "goal", "progress"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_progress.assert_called_once_with(7)
    
    def test_goal_progress_with_days(self, cgm_module):
        """'goal progress --days N' should pass days parameter."""
        with patch.object(cgm_module, "calculate_goal_progress") as mock_progress:
            mock_progress.return_value = {"progress": {}}
            with patch.object(sys, "argv", ["cgm.py", "goal", "progress", "--days", "14"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
                    mock_progress.assert_called_once_with(14)
