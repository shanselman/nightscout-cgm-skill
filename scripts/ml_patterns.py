#!/usr/bin/env python3
"""
Machine Learning Pattern Detection for CGM Data.
Uses scikit-learn for pattern detection, clustering, and anomaly detection.
All processing stays local - privacy-first implementation.
"""
import numpy as np
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Any

try:
    from sklearn.cluster import KMeans
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
except ImportError:
    print("Error: scikit-learn required. Install with: pip install scikit-learn")
    raise

# Minimum data requirements for ML analyses
MIN_READINGS_CLUSTERING = 50
MIN_READINGS_ANOMALY = 100
MIN_DAYS_ANOMALY = 10
MIN_READINGS_ML_INSIGHTS = 50


def extract_features_from_readings(rows: List[Tuple], thresholds: Dict) -> Tuple[np.ndarray, List[Dict]]:
    """
    Extract features from glucose readings for ML analysis.
    
    Features per reading:
    - Hour of day (normalized 0-1)
    - Day of week (normalized 0-1)
    - Glucose value (normalized)
    - Time in range indicator
    - Rate of change (if available)
    
    Returns:
        features: numpy array of shape (n_readings, n_features)
        metadata: list of dicts with timestamp and glucose info
    """
    features = []
    metadata = []
    
    for i, (sgv, date_ms, ds) in enumerate(rows):
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            
            # Normalized hour (0-1)
            hour_norm = dt.hour / 24.0
            
            # Normalized day of week (0-1)
            day_norm = dt.weekday() / 7.0
            
            # Normalized glucose (use reasonable range 40-400 mg/dL)
            glucose_norm = (sgv - 40) / (400 - 40)
            
            # Time in range indicator (-1: low, 0: in range, 1: high)
            if sgv < thresholds["target_low"]:
                tir_indicator = -1
            elif sgv > thresholds["target_high"]:
                tir_indicator = 1
            else:
                tir_indicator = 0
            
            # Calculate rate of change if we have previous reading
            rate_of_change = 0
            if i > 0:
                prev_sgv, prev_date_ms, _ = rows[i-1]
                time_diff_min = (date_ms - prev_date_ms) / (1000 * 60)
                if time_diff_min > 0 and time_diff_min < 30:  # Only if within 30 min
                    rate_of_change = (sgv - prev_sgv) / time_diff_min
            
            # Normalized rate of change (clip to reasonable range)
            rate_norm = np.clip(rate_of_change / 5.0, -1, 1)
            
            features.append([hour_norm, day_norm, glucose_norm, tir_indicator, rate_norm])
            metadata.append({
                "datetime": dt,
                "glucose": sgv,
                "hour": dt.hour,
                "day_of_week": dt.weekday()
            })
        except (ValueError, TypeError):
            continue
    
    return np.array(features), metadata


def cluster_time_patterns(rows: List[Tuple], thresholds: Dict, n_clusters: int = 5) -> Dict[str, Any]:
    """
    Use K-means clustering to identify recurring time-based patterns.
    Groups similar time periods based on glucose behavior.
    
    Args:
        rows: List of (sgv, date_ms, date_string) tuples
        thresholds: Glucose threshold dictionary
        n_clusters: Number of clusters to identify
    
    Returns:
        Dictionary with cluster insights and patterns
    """
    if len(rows) < MIN_READINGS_CLUSTERING:
        return {"error": f"Need at least {MIN_READINGS_CLUSTERING} readings for pattern clustering"}
    
    features, metadata = extract_features_from_readings(rows, thresholds)
    
    if len(features) < n_clusters:
        return {"error": f"Need at least {n_clusters} readings for clustering"}
    
    # Standardize features for better clustering
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)
    
    # K-means clustering
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    cluster_labels = kmeans.fit_predict(features_scaled)
    
    # Analyze each cluster
    cluster_info = defaultdict(list)
    for i, label in enumerate(cluster_labels):
        cluster_info[label].append({
            "glucose": metadata[i]["glucose"],
            "hour": metadata[i]["hour"],
            "day": metadata[i]["day_of_week"],
            "datetime": metadata[i]["datetime"]
        })
    
    # Generate insights for each cluster
    insights = []
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    for label, readings in cluster_info.items():
        avg_glucose = np.mean([r["glucose"] for r in readings])
        avg_hour = np.mean([r["hour"] for r in readings])
        
        # Most common day
        day_counts = defaultdict(int)
        for r in readings:
            day_counts[r["day"]] += 1
        most_common_day = max(day_counts, key=day_counts.get)
        
        # Determine pattern type
        if avg_glucose < thresholds["target_low"]:
            pattern_type = "Low glucose pattern"
        elif avg_glucose > thresholds["target_high"]:
            pattern_type = "High glucose pattern"
        else:
            pattern_type = "In-range pattern"
        
        insights.append({
            "cluster_id": int(label),
            "pattern_type": pattern_type,
            "avg_glucose": round(avg_glucose, 0),
            "avg_hour": round(avg_hour, 1),
            "most_common_day": day_names[most_common_day],
            "reading_count": len(readings),
            "description": generate_cluster_description(
                pattern_type, avg_glucose, avg_hour, day_names[most_common_day], len(readings)
            )
        })
    
    # Sort by reading count (most common patterns first)
    insights.sort(key=lambda x: x["reading_count"], reverse=True)
    
    return {
        "n_clusters": n_clusters,
        "total_readings": len(rows),
        "patterns": insights
    }


def generate_cluster_description(pattern_type: str, avg_glucose: float, avg_hour: float, 
                                 common_day: str, count: int) -> str:
    """Generate human-readable description for a cluster pattern."""
    hour_int = int(avg_hour)
    
    # Determine time of day
    if hour_int < 6:
        time_desc = "overnight"
    elif hour_int < 12:
        time_desc = "morning"
    elif hour_int < 17:
        time_desc = "afternoon"
    elif hour_int < 21:
        time_desc = "evening"
    else:
        time_desc = "late night"
    
    if "Low" in pattern_type:
        trend = f"tend to run low (avg {int(avg_glucose)} mg/dL)"
    elif "High" in pattern_type:
        trend = f"tend to run high (avg {int(avg_glucose)} mg/dL)"
    else:
        trend = f"stay in range (avg {int(avg_glucose)} mg/dL)"
    
    return f"You {trend} during {time_desc} on {common_day}s ({count} readings)"


def detect_day_correlations(rows: List[Tuple], thresholds: Dict) -> Dict[str, Any]:
    """
    Identify day-of-week correlations with glucose control.
    Uses statistical analysis to find significant patterns.
    
    Args:
        rows: List of (sgv, date_ms, date_string) tuples
        thresholds: Glucose threshold dictionary
    
    Returns:
        Dictionary with day-of-week correlation insights
    """
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # Group readings by day of week
    by_day = defaultdict(list)
    for sgv, date_ms, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            by_day[dt.weekday()].append(sgv)
        except (ValueError, TypeError):
            continue
    
    # Calculate metrics for each day
    day_stats = []
    for day_idx in range(7):
        if day_idx not in by_day or len(by_day[day_idx]) < 10:
            continue
        
        readings = by_day[day_idx]
        avg = np.mean(readings)
        std = np.std(readings)
        
        # Time in range
        in_range = sum(1 for x in readings if thresholds["target_low"] <= x <= thresholds["target_high"])
        tir_pct = (in_range / len(readings)) * 100
        
        # Low/high counts
        lows = sum(1 for x in readings if x < thresholds["target_low"])
        highs = sum(1 for x in readings if x > thresholds["target_high"])
        
        day_stats.append({
            "day": day_names[day_idx],
            "day_index": day_idx,
            "avg_glucose": round(avg, 1),
            "std_dev": round(std, 1),
            "tir_percent": round(tir_pct, 1),
            "low_count": lows,
            "high_count": highs,
            "total_readings": len(readings)
        })
    
    if not day_stats:
        return {"error": "Insufficient data for day correlation analysis"}
    
    # Find best and worst days
    best_day = max(day_stats, key=lambda x: x["tir_percent"])
    worst_day = min(day_stats, key=lambda x: x["tir_percent"])
    
    # Find most/least variable days
    most_stable = min(day_stats, key=lambda x: x["std_dev"])
    least_stable = max(day_stats, key=lambda x: x["std_dev"])
    
    # Generate insights
    insights = []
    
    # Best/worst day insights
    if best_day["day"] != worst_day["day"]:
        diff = best_day["tir_percent"] - worst_day["tir_percent"]
        if diff > 10:  # Significant difference
            insights.append(
                f"{best_day['day']}s are your best day with {best_day['tir_percent']:.0f}% time-in-range"
            )
            insights.append(
                f"{worst_day['day']}s are more challenging with {worst_day['tir_percent']:.0f}% time-in-range"
            )
    
    # Variability insights
    if most_stable["day"] != least_stable["day"]:
        insights.append(
            f"Glucose is most stable on {most_stable['day']}s (std dev {most_stable['std_dev']:.0f})"
        )
        if least_stable["std_dev"] > 50:
            insights.append(
                f"More variable on {least_stable['day']}s (std dev {least_stable['std_dev']:.0f})"
            )
    
    # Weekend vs weekday pattern
    weekday_readings = []
    weekend_readings = []
    for stat in day_stats:
        if stat["day_index"] < 5:  # Monday-Friday
            weekday_readings.extend([stat["avg_glucose"]] * stat["total_readings"])
        else:  # Saturday-Sunday
            weekend_readings.extend([stat["avg_glucose"]] * stat["total_readings"])
    
    if weekday_readings and weekend_readings:
        weekday_avg = np.mean(weekday_readings)
        weekend_avg = np.mean(weekend_readings)
        diff = abs(weekday_avg - weekend_avg)
        if diff > 10:
            if weekday_avg > weekend_avg:
                insights.append(
                    f"Weekday average ({weekday_avg:.0f}) is higher than weekend ({weekend_avg:.0f})"
                )
            else:
                insights.append(
                    f"Weekend average ({weekend_avg:.0f}) is higher than weekday ({weekday_avg:.0f})"
                )
    
    return {
        "day_stats": day_stats,
        "best_day": best_day,
        "worst_day": worst_day,
        "most_stable_day": most_stable,
        "least_stable_day": least_stable,
        "insights": insights
    }


def detect_anomalies(rows: List[Tuple], thresholds: Dict, contamination: float = 0.05) -> Dict[str, Any]:
    """
    Use Isolation Forest to detect unusual days with abnormal glucose patterns.
    
    Args:
        rows: List of (sgv, date_ms, date_string) tuples
        thresholds: Glucose threshold dictionary
        contamination: Expected proportion of outliers (default 5%)
    
    Returns:
        Dictionary with anomaly detection results
    """
    if len(rows) < MIN_READINGS_ANOMALY:
        return {"error": f"Need at least {MIN_READINGS_ANOMALY} readings for anomaly detection"}
    
    # Group readings by day
    by_date = defaultdict(list)
    for sgv, date_ms, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            date_key = dt.date()
            by_date[date_key].append(sgv)
        except (ValueError, TypeError):
            continue
    
    # Create feature vector for each day
    day_features = []
    day_metadata = []
    
    for date, readings in by_date.items():
        if len(readings) < 10:  # Need minimum readings per day
            continue
        
        avg = np.mean(readings)
        std = np.std(readings)
        min_val = np.min(readings)
        max_val = np.max(readings)
        range_val = max_val - min_val
        
        # Time in range
        in_range = sum(1 for x in readings if thresholds["target_low"] <= x <= thresholds["target_high"])
        tir_pct = (in_range / len(readings)) * 100
        
        # Low/high percentages
        low_pct = sum(1 for x in readings if x < thresholds["target_low"]) / len(readings) * 100
        high_pct = sum(1 for x in readings if x > thresholds["target_high"]) / len(readings) * 100
        
        day_features.append([avg, std, min_val, max_val, range_val, tir_pct, low_pct, high_pct])
        day_metadata.append({
            "date": date,
            "avg_glucose": avg,
            "readings_count": len(readings),
            "tir_percent": tir_pct
        })
    
    if len(day_features) < MIN_DAYS_ANOMALY:
        return {"error": f"Need at least {MIN_DAYS_ANOMALY} days of data for anomaly detection"}
    
    features_array = np.array(day_features)
    
    # Standardize features
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features_array)
    
    # Isolation Forest for anomaly detection
    iso_forest = IsolationForest(contamination=contamination, random_state=42)
    anomaly_labels = iso_forest.fit_predict(features_scaled)
    anomaly_scores = iso_forest.score_samples(features_scaled)
    
    # Identify anomalies (label = -1)
    anomalies = []
    for i, label in enumerate(anomaly_labels):
        if label == -1:
            meta = day_metadata[i]
            anomalies.append({
                "date": str(meta["date"]),
                "avg_glucose": round(meta["avg_glucose"], 0),
                "tir_percent": round(meta["tir_percent"], 1),
                "readings_count": meta["readings_count"],
                "anomaly_score": round(float(anomaly_scores[i]), 3)
            })
    
    # Sort by anomaly score (most anomalous first)
    anomalies.sort(key=lambda x: x["anomaly_score"])
    
    # Generate insights
    insights = []
    if anomalies:
        insights.append(f"Detected {len(anomalies)} unusual days in your data")
        
        # Describe the most anomalous day
        most_unusual = anomalies[0]
        date_obj = datetime.strptime(most_unusual["date"], "%Y-%m-%d")
        day_name = date_obj.strftime("%A")
        insights.append(
            f"Most unusual: {date_obj.strftime('%b %d')} ({day_name}) - "
            f"avg {most_unusual['avg_glucose']:.0f} mg/dL, "
            f"{most_unusual['tir_percent']:.0f}% time-in-range"
        )
        
        # Check for patterns in anomalies
        if len(anomalies) >= 3:
            avg_tir_anomalies = np.mean([a["tir_percent"] for a in anomalies])
            avg_glucose_anomalies = np.mean([a["avg_glucose"] for a in anomalies])
            
            if avg_tir_anomalies < 50:
                insights.append(
                    f"Unusual days typically have poor control (avg {avg_tir_anomalies:.0f}% TIR)"
                )
            if avg_glucose_anomalies > 180:
                insights.append(
                    f"Unusual days tend to run high (avg {avg_glucose_anomalies:.0f} mg/dL)"
                )
    else:
        insights.append("No significant anomalies detected - your patterns are consistent")
    
    return {
        "total_days_analyzed": len(day_features),
        "anomalies_detected": len(anomalies),
        "anomalies": anomalies[:10],  # Limit to top 10
        "insights": insights
    }


def generate_ml_insights(rows: List[Tuple], thresholds: Dict) -> Dict[str, Any]:
    """
    Main function to generate comprehensive ML-based insights.
    Combines clustering, correlation analysis, and anomaly detection.
    
    Args:
        rows: List of (sgv, date_ms, date_string) tuples
        thresholds: Glucose threshold dictionary
    
    Returns:
        Dictionary with all ML insights
    """
    if len(rows) < MIN_READINGS_ML_INSIGHTS:
        return {"error": f"Need at least {MIN_READINGS_ML_INSIGHTS} readings for ML pattern analysis"}
    
    # Run all ML analyses
    cluster_results = cluster_time_patterns(rows, thresholds)
    correlation_results = detect_day_correlations(rows, thresholds)
    anomaly_results = detect_anomalies(rows, thresholds)
    
    # Combine insights
    all_insights = []
    
    # Add correlation insights
    if "insights" in correlation_results:
        all_insights.extend(correlation_results["insights"])
    
    # Add cluster insights (top 3 patterns)
    if "patterns" in cluster_results:
        for pattern in cluster_results["patterns"][:3]:
            all_insights.append(pattern["description"])
    
    # Add anomaly insights
    if "insights" in anomaly_results:
        all_insights.extend(anomaly_results["insights"])
    
    return {
        "total_readings": len(rows),
        "summary": f"Analyzed {len(rows)} readings using machine learning",
        "insights": all_insights,
        "detailed_results": {
            "time_patterns": cluster_results,
            "day_correlations": correlation_results,
            "anomalies": anomaly_results
        }
    }
