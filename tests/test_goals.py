"""
Tests for goal tracking functionality.
"""
import pytest
from unittest.mock import patch


class TestGoalManagement:
    """Tests for goal management functions."""
    
    def test_set_tir_goal(self, cgm_module, temp_db):
        """Should set time-in-range goal."""
        result = cgm_module.set_goal("tir", 70)
        assert result["status"] == "success"
        assert result["metric"] == "tir"
        assert result["target"] == 70
    
    def test_set_cv_goal(self, cgm_module, temp_db):
        """Should set CV goal."""
        result = cgm_module.set_goal("cv", 33)
        assert result["status"] == "success"
        assert result["metric"] == "cv"
        assert result["target"] == 33
    
    def test_set_gmi_goal(self, cgm_module, temp_db):
        """Should set GMI goal."""
        result = cgm_module.set_goal("gmi", 6.5)
        assert result["status"] == "success"
        assert result["metric"] == "gmi"
        assert result["target"] == 6.5
    
    def test_set_avg_glucose_goal(self, cgm_module, temp_db):
        """Should set average glucose goal."""
        result = cgm_module.set_goal("avg_glucose", 140)
        assert result["status"] == "success"
        assert result["metric"] == "avg_glucose"
        assert result["target"] == 140
    
    def test_invalid_metric(self, cgm_module, temp_db):
        """Should reject invalid metric."""
        result = cgm_module.set_goal("invalid", 50)
        assert "error" in result
        assert "Invalid metric" in result["error"]
    
    def test_tir_validation(self, cgm_module, temp_db):
        """TIR goal should be 0-100."""
        result = cgm_module.set_goal("tir", 150)
        assert "error" in result
        
        result = cgm_module.set_goal("tir", -10)
        assert "error" in result
    
    def test_cv_validation(self, cgm_module, temp_db):
        """CV goal should be 0-100."""
        result = cgm_module.set_goal("cv", 150)
        assert "error" in result
    
    def test_gmi_validation(self, cgm_module, temp_db):
        """GMI goal should be 4-14."""
        result = cgm_module.set_goal("gmi", 2)
        assert "error" in result
        
        result = cgm_module.set_goal("gmi", 20)
        assert "error" in result
    
    def test_avg_glucose_validation(self, cgm_module, temp_db):
        """Average glucose goal should be positive."""
        result = cgm_module.set_goal("avg_glucose", -50)
        assert "error" in result
    
    def test_get_goals_empty(self, cgm_module, temp_db):
        """Should return empty goals when none set."""
        result = cgm_module.get_goals()
        assert "goals" in result
        assert result["goals"] == {}
    
    def test_get_goals_with_data(self, cgm_module, temp_db):
        """Should return all set goals."""
        cgm_module.set_goal("tir", 70)
        cgm_module.set_goal("cv", 33)
        
        result = cgm_module.get_goals()
        assert "goals" in result
        assert "tir" in result["goals"]
        assert "cv" in result["goals"]
        assert result["goals"]["tir"]["target"] == 70
        assert result["goals"]["cv"]["target"] == 33
    
    def test_clear_specific_goal(self, cgm_module, temp_db):
        """Should clear a specific goal."""
        cgm_module.set_goal("tir", 70)
        cgm_module.set_goal("cv", 33)
        
        result = cgm_module.clear_goal("tir")
        assert result["status"] == "success"
        
        goals = cgm_module.get_goals()
        assert "tir" not in goals["goals"]
        assert "cv" in goals["goals"]
    
    def test_clear_all_goals(self, cgm_module, temp_db):
        """Should clear all goals."""
        cgm_module.set_goal("tir", 70)
        cgm_module.set_goal("cv", 33)
        
        result = cgm_module.clear_goal()
        assert result["status"] == "success"
        
        goals = cgm_module.get_goals()
        assert goals["goals"] == {}
    
    def test_update_existing_goal(self, cgm_module, temp_db):
        """Should update an existing goal."""
        cgm_module.set_goal("tir", 70)
        cgm_module.set_goal("tir", 80)
        
        goals = cgm_module.get_goals()
        assert goals["goals"]["tir"]["target"] == 80


class TestGoalProgress:
    """Tests for goal progress tracking."""
    
    def test_calculate_progress_no_goals(self, cgm_module, temp_db):
        """Should handle no goals set."""
        result = cgm_module.calculate_goal_progress()
        assert "message" in result
        assert "No goals set" in result["message"]
    
    def test_calculate_progress_tir(self, cgm_module, temp_db):
        """Should calculate TIR goal progress."""
        cgm_module.set_goal("tir", 70)
        
        with patch.object(cgm_module, 'analyze_cgm') as mock_analyze:
            mock_analyze.return_value = {
                "time_in_range": {"in_range_pct": 65.5},
                "cv_variability": 30,
                "gmi_estimated_a1c": 6.8,
                "statistics": {"mean": 140},
                "date_range": {"from": "2026-01-01", "to": "2026-01-07"}
            }
            
            result = cgm_module.calculate_goal_progress(7)
            
            assert "progress" in result
            assert "tir" in result["progress"]
            assert result["progress"]["tir"]["current"] == 65.5
            assert result["progress"]["tir"]["target"] == 70
            assert result["progress"]["tir"]["met"] is False
    
    def test_calculate_progress_cv(self, cgm_module, temp_db):
        """Should calculate CV goal progress (lower is better)."""
        cgm_module.set_goal("cv", 33)
        
        with patch.object(cgm_module, 'analyze_cgm') as mock_analyze:
            mock_analyze.return_value = {
                "time_in_range": {"in_range_pct": 70},
                "cv_variability": 30,
                "gmi_estimated_a1c": 6.8,
                "statistics": {"mean": 140},
                "date_range": {"from": "2026-01-01", "to": "2026-01-07"}
            }
            
            result = cgm_module.calculate_goal_progress(7)
            
            assert "progress" in result
            assert "cv" in result["progress"]
            assert result["progress"]["cv"]["current"] == 30
            assert result["progress"]["cv"]["target"] == 33
            assert result["progress"]["cv"]["met"] is True  # 30 <= 33
    
    def test_calculate_progress_multiple_goals(self, cgm_module, temp_db):
        """Should calculate progress for multiple goals."""
        cgm_module.set_goal("tir", 70)
        cgm_module.set_goal("cv", 33)
        cgm_module.set_goal("gmi", 7.0)
        
        with patch.object(cgm_module, 'analyze_cgm') as mock_analyze:
            mock_analyze.return_value = {
                "time_in_range": {"in_range_pct": 75},
                "cv_variability": 30,
                "gmi_estimated_a1c": 6.5,
                "statistics": {"mean": 140},
                "date_range": {"from": "2026-01-01", "to": "2026-01-07"}
            }
            
            result = cgm_module.calculate_goal_progress(7)
            
            assert "progress" in result
            assert "tir" in result["progress"]
            assert "cv" in result["progress"]
            assert "gmi" in result["progress"]
            assert result["progress"]["tir"]["met"] is True  # 75 >= 70
            assert result["progress"]["cv"]["met"] is True  # 30 <= 33
            assert result["progress"]["gmi"]["met"] is True  # 6.5 <= 7.0
