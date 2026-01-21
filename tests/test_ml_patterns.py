"""
Tests for ML pattern detection (ml_patterns.py).
Tests clustering, day-of-week correlations, and anomaly detection.
"""
import sqlite3
import pytest
import numpy as np
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Import ml_patterns module
try:
    import ml_patterns
except ImportError:
    pytest.skip("scikit-learn not installed", allow_module_level=True)


class TestExtractFeatures:
    """Tests for feature extraction from glucose readings."""
    
    def test_extract_basic_features(self):
        """Should extract normalized features from readings."""
        now = datetime.now(timezone.utc)
        rows = []
        for i in range(10):
            dt = now - timedelta(hours=i)
            date_ms = int(dt.timestamp() * 1000)
            date_string = dt.isoformat().replace("+00:00", "Z")
            rows.append((120 + i * 10, date_ms, date_string))
        
        thresholds = {"target_low": 70, "target_high": 180}
        features, metadata = ml_patterns.extract_features_from_readings(rows, thresholds)
        
        # Should have same number of features as rows
        assert len(features) == len(rows)
        assert len(metadata) == len(rows)
        
        # Features should have 5 dimensions
        assert features.shape[1] == 5
        
        # All features should be normalized (approximately 0-1 or -1 to 1)
        assert np.all(features[:, 0] >= 0) and np.all(features[:, 0] <= 1)  # hour
        assert np.all(features[:, 1] >= 0) and np.all(features[:, 1] <= 1)  # day
    
    def test_time_in_range_indicator(self):
        """TIR indicator should correctly classify readings."""
        now = datetime.now(timezone.utc)
        date_ms = int(now.timestamp() * 1000)
        date_string = now.isoformat().replace("+00:00", "Z")
        
        thresholds = {"target_low": 70, "target_high": 180}
        
        # Test low reading
        rows = [(50, date_ms, date_string)]
        features, _ = ml_patterns.extract_features_from_readings(rows, thresholds)
        assert features[0, 3] == -1  # Low indicator
        
        # Test in-range reading
        rows = [(120, date_ms, date_string)]
        features, _ = ml_patterns.extract_features_from_readings(rows, thresholds)
        assert features[0, 3] == 0  # In-range indicator
        
        # Test high reading
        rows = [(250, date_ms, date_string)]
        features, _ = ml_patterns.extract_features_from_readings(rows, thresholds)
        assert features[0, 3] == 1  # High indicator
    
    def test_metadata_extraction(self):
        """Metadata should include datetime and glucose info."""
        now = datetime.now(timezone.utc)
        date_ms = int(now.timestamp() * 1000)
        date_string = now.isoformat().replace("+00:00", "Z")
        rows = [(120, date_ms, date_string)]
        
        thresholds = {"target_low": 70, "target_high": 180}
        features, metadata = ml_patterns.extract_features_from_readings(rows, thresholds)
        
        assert "datetime" in metadata[0]
        assert "glucose" in metadata[0]
        assert "hour" in metadata[0]
        assert "day_of_week" in metadata[0]
        assert metadata[0]["glucose"] == 120


class TestClusterTimePatterns:
    """Tests for time-based pattern clustering."""
    
    def test_cluster_patterns_basic(self, populated_db):
        """Should identify time-based clusters in glucose data."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.cluster_time_patterns(rows, thresholds, n_clusters=3)
        
        assert "patterns" in result
        assert "n_clusters" in result
        assert result["n_clusters"] == 3
        assert len(result["patterns"]) <= 3
    
    def test_insufficient_data_for_clustering(self):
        """Should return error with insufficient data."""
        rows = [(120, 1000, "2024-01-01T00:00:00Z") for _ in range(10)]
        thresholds = {"target_low": 70, "target_high": 180}
        
        result = ml_patterns.cluster_time_patterns(rows, thresholds, n_clusters=5)
        assert "error" in result
    
    def test_cluster_descriptions_generated(self, populated_db):
        """Cluster patterns should include human-readable descriptions."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.cluster_time_patterns(rows, thresholds, n_clusters=3)
        
        for pattern in result["patterns"]:
            assert "description" in pattern
            assert "pattern_type" in pattern
            assert "avg_glucose" in pattern
            assert "most_common_day" in pattern
    
    def test_patterns_sorted_by_frequency(self, populated_db):
        """Patterns should be sorted by reading count (most common first)."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.cluster_time_patterns(rows, thresholds, n_clusters=3)
        
        # Check that patterns are sorted by reading_count
        counts = [p["reading_count"] for p in result["patterns"]]
        assert counts == sorted(counts, reverse=True)


class TestDayCorrelations:
    """Tests for day-of-week correlation analysis."""
    
    def test_day_correlations_basic(self, populated_db):
        """Should analyze day-of-week patterns."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.detect_day_correlations(rows, thresholds)
        
        assert "day_stats" in result
        assert "best_day" in result
        assert "worst_day" in result
        assert "insights" in result
    
    def test_day_stats_structure(self, populated_db):
        """Day stats should include all required metrics."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.detect_day_correlations(rows, thresholds)
        
        for stat in result["day_stats"]:
            assert "day" in stat
            assert "avg_glucose" in stat
            assert "std_dev" in stat
            assert "tir_percent" in stat
            assert "low_count" in stat
            assert "high_count" in stat
            assert "total_readings" in stat
    
    def test_best_worst_day_identified(self, populated_db):
        """Should correctly identify best and worst days."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.detect_day_correlations(rows, thresholds)
        
        # Best day should have highest TIR
        best_tir = result["best_day"]["tir_percent"]
        worst_tir = result["worst_day"]["tir_percent"]
        assert best_tir >= worst_tir
    
    def test_stability_metrics(self, populated_db):
        """Should identify most and least stable days."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.detect_day_correlations(rows, thresholds)
        
        assert "most_stable_day" in result
        assert "least_stable_day" in result
        
        most_stable_std = result["most_stable_day"]["std_dev"]
        least_stable_std = result["least_stable_day"]["std_dev"]
        assert most_stable_std <= least_stable_std
    
    def test_insufficient_data_error(self):
        """Should return error with insufficient data."""
        rows = [(120, 1000, "2024-01-01T00:00:00Z")]
        thresholds = {"target_low": 70, "target_high": 180}
        
        result = ml_patterns.detect_day_correlations(rows, thresholds)
        assert "error" in result


class TestAnomalyDetection:
    """Tests for anomaly detection using Isolation Forest."""
    
    def test_anomaly_detection_basic(self, populated_db):
        """Should detect anomalous days in glucose data or return error if insufficient."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.detect_anomalies(rows, thresholds)
        
        # May not have enough days in populated_db (only 7 days)
        if "error" in result:
            assert "10 days" in result["error"]
        else:
            assert "total_days_analyzed" in result
            assert "anomalies_detected" in result
            assert "insights" in result
    
    def test_anomaly_structure(self, populated_db):
        """Anomalies should include date and metrics when detected."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.detect_anomalies(rows, thresholds)
        
        # Skip test if insufficient data
        if "error" not in result and result.get("anomalies_detected", 0) > 0:
            anomaly = result["anomalies"][0]
            assert "date" in anomaly
            assert "avg_glucose" in anomaly
            assert "tir_percent" in anomaly
            assert "anomaly_score" in anomaly
    
    def test_anomaly_detection_with_extreme_day(self):
        """Should detect a day with extreme glucose values as anomalous."""
        # Generate data with mostly normal days and one extreme day
        now = datetime.now(timezone.utc)
        rows = []
        
        # 15 normal days
        for day in range(15):
            for hour in range(24):
                dt = now - timedelta(days=day, hours=hour)
                date_ms = int(dt.timestamp() * 1000)
                date_string = dt.isoformat().replace("+00:00", "Z")
                # Normal glucose around 120
                rows.append((120 + np.random.randint(-20, 20), date_ms, date_string))
        
        # 1 extreme day with very high glucose
        extreme_day = now - timedelta(days=20)
        for hour in range(24):
            dt = extreme_day.replace(hour=hour)
            date_ms = int(dt.timestamp() * 1000)
            date_string = dt.isoformat().replace("+00:00", "Z")
            rows.append((300, date_ms, date_string))
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.detect_anomalies(rows, thresholds, contamination=0.1)
        
        # Should detect at least one anomaly
        assert result["anomalies_detected"] > 0
    
    def test_insufficient_data_for_anomalies(self):
        """Should return error with insufficient data."""
        rows = [(120, 1000 + i*1000, f"2024-01-{i+1:02d}T00:00:00Z") for i in range(50)]
        thresholds = {"target_low": 70, "target_high": 180}
        
        result = ml_patterns.detect_anomalies(rows, thresholds)
        assert "error" in result


class TestMLInsightsGeneration:
    """Tests for comprehensive ML insights generation."""
    
    def test_generate_ml_insights(self, populated_db):
        """Should generate comprehensive ML insights."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.generate_ml_insights(rows, thresholds)
        
        assert "total_readings" in result
        assert "summary" in result
        assert "insights" in result
        assert "detailed_results" in result
    
    def test_insights_are_human_readable(self, populated_db):
        """Insights should be human-readable strings."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.generate_ml_insights(rows, thresholds)
        
        # All insights should be strings
        for insight in result["insights"]:
            assert isinstance(insight, str)
            assert len(insight) > 0
    
    def test_detailed_results_structure(self, populated_db):
        """Detailed results should include all ML analyses."""
        conn = sqlite3.connect(populated_db)
        rows = conn.execute(
            "SELECT sgv, date_ms, date_string FROM readings ORDER BY date_ms"
        ).fetchall()
        conn.close()
        
        thresholds = {"urgent_low": 55, "target_low": 70, "target_high": 180, "urgent_high": 250}
        result = ml_patterns.generate_ml_insights(rows, thresholds)
        
        assert "time_patterns" in result["detailed_results"]
        assert "day_correlations" in result["detailed_results"]
        assert "anomalies" in result["detailed_results"]
    
    def test_insufficient_data_for_ml(self):
        """Should return error with insufficient data."""
        rows = [(120, 1000, "2024-01-01T00:00:00Z") for _ in range(30)]
        thresholds = {"target_low": 70, "target_high": 180}
        
        result = ml_patterns.generate_ml_insights(rows, thresholds)
        assert "error" in result


class TestClusterDescriptionGeneration:
    """Tests for generating human-readable cluster descriptions."""
    
    def test_low_pattern_description(self):
        """Should generate appropriate description for low glucose pattern."""
        desc = ml_patterns.generate_cluster_description(
            "Low glucose pattern", 65, 14.5, "Tuesday", 50
        )
        assert "low" in desc.lower()
        assert "Tuesday" in desc
        assert "65" in desc
        assert "50" in desc
    
    def test_high_pattern_description(self):
        """Should generate appropriate description for high glucose pattern."""
        desc = ml_patterns.generate_cluster_description(
            "High glucose pattern", 220, 13.2, "Friday", 75
        )
        assert "high" in desc.lower()
        assert "Friday" in desc
        assert "220" in desc
    
    def test_in_range_pattern_description(self):
        """Should generate appropriate description for in-range pattern."""
        desc = ml_patterns.generate_cluster_description(
            "In-range pattern", 125, 8.3, "Monday", 100
        )
        assert "range" in desc.lower()
        assert "Monday" in desc
        assert "125" in desc
    
    def test_time_of_day_detection(self):
        """Should correctly identify time of day in descriptions."""
        # Overnight
        desc = ml_patterns.generate_cluster_description(
            "In-range pattern", 120, 3.5, "Monday", 50
        )
        assert "overnight" in desc
        
        # Morning
        desc = ml_patterns.generate_cluster_description(
            "In-range pattern", 120, 9.0, "Monday", 50
        )
        assert "morning" in desc
        
        # Afternoon
        desc = ml_patterns.generate_cluster_description(
            "In-range pattern", 120, 15.0, "Monday", 50
        )
        assert "afternoon" in desc
        
        # Evening
        desc = ml_patterns.generate_cluster_description(
            "In-range pattern", 120, 19.0, "Monday", 50
        )
        assert "evening" in desc
