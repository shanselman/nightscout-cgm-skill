# Nightscout CGM Skill - Planned Improvements

This document tracks potential enhancements to the Nightscout CGM Skill.

## High Impact

### 1. Meal/Event Annotations
Let users tag meals, exercise, insulin doses and see correlations.
- "What happens when I eat pizza?"
- "Show me my post-workout patterns"
- Store annotations in local SQLite alongside readings

### 2. Trend Alerts Summary
Proactive pattern warnings based on recent data.
- "You've had 3 lows after 2am this week"
- "Friday lunches are consistently high"
- Surface concerning patterns automatically

### 3. Compare Periods
Side-by-side comparison of different time periods.
- "Compare this week to last week"
- "January vs December"
- Show delta in TIR, average, variability

## Report Enhancements

### 4. Ambulatory Glucose Profile (AGP)
The standard clinical report format that doctors use.
- Matches the format endocrinologists expect
- Easy to share with healthcare providers
- Industry-standard percentile bands

### 5. Export to PDF
One-click PDF generation for doctor visits.
- Print-friendly formatting
- Include key metrics and charts
- Date range selection

### 6. Goal Tracking
Set personal goals and track progress over time.
- Set a TIR goal (e.g., 70%)
- Show progress trend over weeks/months
- Celebrate milestones

## Quality of Life

### 7. Auto-refresh Daemon
Background sync so data is always current.
- Periodic fetch from Nightscout
- Configurable interval
- Low resource usage

### 8. Notification Integration
System notifications for concerning patterns.
- "You've been high for 2 hours"
- Configurable thresholds
- Desktop/terminal notifications

### 9. Multiple Profiles
Support family members with separate Nightscout instances.
- Switch between profiles
- Separate databases per profile
- Named configurations

## Data Science

### 10. ML Pattern Detection
Machine learning to find non-obvious patterns.
- "You tend to go high 3 hours after meals over 50g carbs"
- Day-of-week and time-of-day correlations
- Predictive insights

---

## Status

| # | Feature | Issue | Status |
|---|---------|-------|--------|
| 1 | Meal/Event Annotations | [#4](https://github.com/shanselman/nightscout-cgm-skill/issues/4) | Planned |
| 2 | Trend Alerts Summary | [#5](https://github.com/shanselman/nightscout-cgm-skill/issues/5) | Planned |
| 3 | Compare Periods | [#6](https://github.com/shanselman/nightscout-cgm-skill/issues/6) | Planned |
| 4 | AGP Report | [#7](https://github.com/shanselman/nightscout-cgm-skill/issues/7) | Planned |
| 5 | Export to PDF | [#8](https://github.com/shanselman/nightscout-cgm-skill/issues/8) | Planned |
| 6 | Goal Tracking | [#9](https://github.com/shanselman/nightscout-cgm-skill/issues/9) | Planned |
| 7 | Auto-refresh Daemon | [#10](https://github.com/shanselman/nightscout-cgm-skill/issues/10) | Planned |
| 8 | Notification Integration | [#11](https://github.com/shanselman/nightscout-cgm-skill/issues/11) | Planned |
| 9 | Multiple Profiles | [#12](https://github.com/shanselman/nightscout-cgm-skill/issues/12) | Planned |
| 10 | ML Pattern Detection | [#13](https://github.com/shanselman/nightscout-cgm-skill/issues/13) | Planned |
