# Nightscout CGM Skill

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-Open%20Standard-blue)](https://github.com/agentskills/agentskills)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An [Agent Skill](https://github.com/agentskills/agentskills) for analyzing Continuous Glucose Monitor (CGM) data from [Nightscout](http://www.nightscout.info/). Works with GitHub Copilot CLI, Claude Code, and VS Code agent mode.

![Nightscout CGM Report with interactive charts](images/newcharts.png)

> **⚠️ Disclaimer:** We are not doctors. This is DIY body hacking by and for the diabetes community. If you're using Nightscout, you already know the deal: **don't trust anyone or anything to make decisions about your blood sugar except yourself.** This tool is for informational purposes only and should never replace medical advice, your own judgment, or looking at your actual CGM.

## Features

- **Interactive HTML Reports** - Generate comprehensive local reports with charts (like [tally](https://github.com/davidfowl/tally) for diabetes)
- **Trend Alerts** - Automatic detection of concerning patterns (recurring lows/highs, time-of-day issues)
- **Current Glucose** - Real-time blood glucose with trend direction
- **Pattern Analysis** - Find your best/worst times, problem days, overnight patterns
- **Specific Day Analysis** - Drill into what happened on a particular date
- **Worst Days Finder** - Find your problem days ranked by peak glucose
- **Time Queries** - "What happens Tuesdays after lunch?" 
- **Terminal Visualizations** - Heatmaps, sparklines, and day charts
- **Statistics** - Time-in-range, GMI (estimated A1C), glucose variability
- **Privacy-First** - All data stored and analyzed locally on your machine

## Interactive HTML Reports

Generate beautiful, self-contained HTML reports with interactive charts - similar to [tally](https://github.com/davidfowl/tally) but for diabetes/CGM data:

```bash
python scripts/cgm.py report --days 90 --open
```

![Glucose distribution, heatmap, and weekly summary](images/heatmap2.png)

### Report Features

- **Date Range Controls** - Quick buttons for 7d/14d/30d/90d/6mo/1yr/All, plus custom date pickers
- **All charts update dynamically** - No server needed, everything recalculates in your browser
- **Trend Alerts Dashboard** - Automatic detection of concerning patterns and trends
- **Key Stats Dashboard** - Time-in-Range %, GMI (estimated A1C), CV (variability), average glucose
- **7 Interactive Charts:**
  - Time-in-Range pie chart
  - Modal Day (typical 24-hour profile with percentile bands)
  - Daily trends (average glucose + TIR per day)
  - Day of week comparison
  - Glucose distribution histogram
  - Time-in-Range heatmap (day × hour) with hover tooltips
  - Weekly summary

## Trend Alerts

Proactively surfaces concerning patterns in your CGM data. The system automatically detects:

- **Recurring Lows** - "You've had 3 lows after 2am this week"
- **Recurring Highs** - "Friday lunches are consistently high"
- **Time-of-Day Issues** - Specific hours that consistently cause problems
- **Day-of-Week Issues** - Problematic days that need attention
- **Trend Changes** - "Your overnight control has improved 15% this month"

Alerts are shown in both:
- **CLI output** - `python scripts/cgm.py alerts --days 90`
- **HTML reports** - Integrated dashboard at the top of reports

Each alert includes severity (high/medium/low), specific details, and actionable insights. High-severity alerts (like overnight lows) are prioritized for safety.

### Color Scheme

Uses CGM-style colors (like Dexcom/Libre):
- 🔵 **Blue** for lows (easier to see at a glance)
- 🟢 **Green** for in-range
- 🟡 **Yellow** for highs
- 🔴 **Red** for very high

### Privacy

The report is a single self-contained HTML file. **All your data stays local** - no data is sent anywhere. Open it in any browser, share it with your doctor, or keep it for your records.

## Quick Examples

Just ask naturally:

```
"What's my current glucose?"
"Generate a report of my last 90 days"
"Show me trend alerts for concerning patterns"
"What patterns do you see in my data?"
"What's happening on Tuesdays after lunch?"
"When do I tend to go low?"
"Show me a sparkline of my last 24 hours"
"Show me a heatmap of my glucose"
"What does Saturday look like?"
"What was my worst lunch this week?"
"Show me what happened yesterday during dinner"
```

Or use the CLI directly:

```bash
# Generate interactive HTML report (includes trend alerts)
python scripts/cgm.py report --days 90 --open

# Show trend alerts for concerning patterns
python scripts/cgm.py alerts --days 90

# Current glucose
python scripts/cgm.py current

# Find patterns (best/worst times, problem areas)
python scripts/cgm.py patterns

# What happened yesterday at lunch (11am-2pm)?
python scripts/cgm.py day yesterday --hour-start 11 --hour-end 14

# Find worst lunch days in last 3 weeks
python scripts/cgm.py worst --days 21 --hour-start 11 --hour-end 14

# Sparkline for a specific date and time window (with colors)
python scripts/cgm.py chart --date yesterday --hour-start 11 --hour-end 14 --color

# Tuesdays after lunch
python scripts/cgm.py query --day Tuesday --hour-start 12 --hour-end 15

# Sparkline of last 24 hours
python scripts/cgm.py chart --sparkline

# Weekly heatmap
python scripts/cgm.py chart --heatmap
```

## Privacy & Data Architecture

**Your glucose data stays on your machine.** Here's how it works:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         YOUR MACHINE                                │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │
│  │ Copilot CLI │───>│  cgm.py     │───>│ SQLite DB (cgm_data.db) │  │
│  │ (local)     │    │  (local)    │    │ (local file)            │  │
│  └─────────────┘    └──────┬──────┘    └─────────────────────────┘  │
│                            │                                        │
└────────────────────────────┼────────────────────────────────────────┘
                             │ HTTPS (fetch only)
                             ▼
                    ┌─────────────────┐
                    │ YOUR Nightscout │
                    │ (your server)   │
                    └─────────────────┘
```

**What stays local:**
- ✅ SQLite database with your glucose readings (stored in the skill directory)
- ✅ All analysis (statistics, time-in-range, GMI, patterns) computed locally by Python
- ✅ The script runs entirely on your machine

**What the AI sees:**
- Only the JSON output you request (e.g., `{"glucose": 152, "status": "in range"}`)
- This is just text in your conversation - same as if you typed it yourself
- The AI cannot access your Nightscout directly or read your SQLite database

**What the AI does NOT have access to:**
- ❌ Your Nightscout URL or API credentials
- ❌ Your SQLite database file
- ❌ Your historical readings (unless you explicitly ask for analysis)

The skill simply runs a local Python script and returns text output. Your health data never leaves your machine except to fetch from your own Nightscout server (which you already trust).

## Prerequisites

- Python 3.8+
- `requests` library (`pip install requests`)
- A [Nightscout](http://www.nightscout.info/) instance with API access

## Installation

### GitHub Copilot CLI / Claude Code (Personal Skill)

```bash
git clone https://github.com/shanselman/nightscout-cgm-skill ~/.copilot/skills/nightscout-cgm
```

Or for Claude Code:
```bash
git clone https://github.com/shanselman/nightscout-cgm-skill ~/.claude/skills/nightscout-cgm
```

### Project Skill (Repository-specific)

```bash
cd your-repo
git clone https://github.com/shanselman/nightscout-cgm-skill .github/skills/nightscout-cgm
```

### Install Dependencies

```bash
pip install requests
```

## Configuration

Set the `NIGHTSCOUT_URL` environment variable to your Nightscout API endpoint.

> **⚠️ Important:** Before configuring, test your Nightscout URL in a browser to ensure it returns JSON data. If your Nightscout instance requires authentication, you'll need to include your API token as a query parameter:
> ```
> https://your-nightscout-site.com/api/v1/entries.json?token=YOUR_API_SECRET
> ```
> You can find or create API tokens in your Nightscout settings under "Admin Tools" → "Subjects".

**Linux/macOS:**
```bash
export NIGHTSCOUT_URL="https://your-nightscout-site.com/api/v1/entries.json?token=YOUR_API_SECRET"
```

**Windows PowerShell:**
```powershell
$env:NIGHTSCOUT_URL = "https://your-nightscout-site.com/api/v1/entries.json?token=YOUR_API_SECRET"
```

**Windows (persistent):**
```powershell
[Environment]::SetEnvironmentVariable("NIGHTSCOUT_URL", "https://your-nightscout-site.com/api/v1/entries.json?token=YOUR_API_SECRET", "User")
```

## Getting Started

After installation and configuration, just start asking questions! The skill automatically fetches your data on first use.

```
> What's my current glucose?

No local data found. Fetching from Nightscout (this may take a moment)...
Fetched 31123 readings. Total: 31123

{"glucose": 142, "unit": "mg/dL", "trend": "Flat", "status": "in range"}
```

Data is cached locally in a SQLite database for fast queries. Run `refresh` periodically to pull in new readings, or just ask the AI to "refresh my CGM data".

## Usage

### With AI Agents

Just ask naturally:

**Basic queries:**
- "What's my current glucose?"
- "Analyze my blood sugar for the last 30 days"
- "What's my estimated A1C?"
- "Show me my time in range"

**Pattern analysis:**
- "What patterns do you see in my data?"
- "What's happening on Tuesdays after lunch?"
- "When are my worst times for blood sugar control?"
- "How are my overnight numbers?"
- "When do I tend to go low?"
- "What day of the week is my best for time-in-range?"
- "Show me my morning patterns"

**Specific day analysis:**
- "What was my worst lunch this week?" (you'll be asked what hours you eat lunch)
- "Show me what happened yesterday during dinner"
- "What were my worst breakfast days the last two weeks?"
- "What did my blood sugar do on January 16th between 11am and 3pm?"

**Visualizations:**
- "Show me a sparkline of my last 24 hours"
- "Show me a heatmap of my glucose"
- "What does Saturday look like?"

### Direct CLI Usage

```bash
# Generate interactive HTML report (opens in browser)
python scripts/cgm.py report --days 90 --open

# Generate report for custom period
python scripts/cgm.py report --days 30 --output my_report.html

# Get current glucose reading
python scripts/cgm.py current

# Analyze last 90 days (default)
python scripts/cgm.py analyze

# Analyze last 30 days
python scripts/cgm.py analyze --days 30

# Find patterns automatically (best/worst times, problem areas)
python scripts/cgm.py patterns

# View all readings for a specific date
python scripts/cgm.py day yesterday
python scripts/cgm.py day 2026-01-16 --hour-start 11 --hour-end 14

# Find your worst days (ranked by peak glucose)
python scripts/cgm.py worst --days 21 --hour-start 11 --hour-end 14

# What happens on Tuesdays after lunch?
python scripts/cgm.py query --day Tuesday --hour-start 12 --hour-end 15

# How are my overnight numbers on weekends?
python scripts/cgm.py query --day Saturday --hour-start 22 --hour-end 6

# Morning analysis across all days
python scripts/cgm.py query --hour-start 6 --hour-end 10

# Show sparkline of last 24 hours (compact visual trend)
python scripts/cgm.py chart --sparkline

# Show sparkline of last 6 hours
python scripts/cgm.py chart --sparkline --hours 6

# Show sparkline for a specific date and time range
python scripts/cgm.py chart --date yesterday --hour-start 11 --hour-end 14 --color

# Show week view (one sparkline per day - great for terminals!)
python scripts/cgm.py chart --week --days 14 --color

# Show ASCII heatmap (works inside Copilot)
python scripts/cgm.py chart --heatmap

# Show day chart with colors (direct terminal)
python scripts/cgm.py chart --day Saturday --color

# Generate interactive HTML report (like tally for diabetes)
python scripts/cgm.py report --days 90

# Generate report and open in browser
python scripts/cgm.py report --days 30 --open

# Save report to specific location
python scripts/cgm.py report --days 90 --output ~/my_glucose_report.html

# Refresh data from Nightscout
python scripts/cgm.py refresh --days 90
```

### Standalone Terminal Usage

You don't need an AI agent to use this tool! The Python script works great on its own with colorful ANSI output:

```bash
cd ~/.copilot/skills/nightscout-cgm
python scripts/cgm.py chart --week --days 7 --color
```

There's also a PowerShell script that generates a full report:

```powershell
cd ~/.copilot/skills/nightscout-cgm
.\show-all-charts.ps1
```

This outputs:
- 📈 14-day sparklines (one line per day)
- 🗓️ Weekly heatmap
- 📊 Hourly breakdown for each day of the week
- 🔍 Pattern analysis (best/worst times)
- 📋 Full statistics

### Interactive HTML Report

Generate a comprehensive, self-contained HTML report with interactive charts - similar to [tally](https://github.com/davidfowl/tally) but for diabetes data:

```bash
python scripts/cgm.py report --days 90 --open
```

The report includes:
- 📊 **Time-in-Range pie chart** - Visual breakdown of glucose distribution
- 📈 **Modal Day chart** - Your typical 24-hour glucose profile with percentile bands
- 📅 **Daily trends** - Day-by-day average glucose and time-in-range
- 🗓️ **Day of week comparison** - Which days are your best/worst
- 📉 **Glucose distribution histogram** - See your glucose spread
- 🔥 **Time-in-Range heatmap** - Identify problem times at a glance
- 📆 **Weekly summary** - Track progress over weeks

The report is:
- **Self-contained** - Single HTML file with embedded Chart.js
- **Privacy-first** - All data stays local, no external servers
- **Interactive** - Hover for details, responsive design
- **Shareable** - Open in any browser, send to your doctor

## Output Examples

### Current Glucose
```json
{
  "glucose_mg_dl": 142,
  "trend": "Flat",
  "timestamp": "2024-01-15T14:30:00.000Z",
  "status": "in range"
}
```

### Analysis
```json
{
  "date_range": {"from": "2024-10-17", "to": "2025-01-15", "days_analyzed": 90},
  "readings": 25920,
  "statistics": {"count": 25920, "mean": 138.5, "std": 42.1, "min": 45, "max": 320, "median": 132},
  "time_in_range": {
    "very_low_pct": 0.5,
    "low_pct": 2.1,
    "in_range_pct": 72.3,
    "high_pct": 18.6,
    "very_high_pct": 6.5
  },
  "gmi_estimated_a1c": 6.6,
  "cv_variability": 30.4,
  "cv_status": "stable"
}
```

## Glucose Ranges

This skill uses your **Nightscout configuration**:
- **Units**: Automatically detected from your `DISPLAY_UNITS` setting (mg/dL or mmol/L)
- **Thresholds**: Uses your configured `bgLow`, `bgTargetBottom`, `bgTargetTop`, and `bgHigh` values

Default thresholds (if not configured in Nightscout):

| Range | mg/dL | mmol/L | Status |
|-------|-------|--------|--------|
| Very Low | <55 | <3.0 | Dangerous hypoglycemia |
| Low | 55-69 | 3.0-3.8 | Hypoglycemia |
| In Range | 70-180 | 3.9-10.0 | Target range |
| High | 181-250 | 10.1-13.9 | Hyperglycemia |
| Very High | >250 | >13.9 | Significant hyperglycemia |

## Key Metrics

- **GMI (Glucose Management Indicator)**: Estimated A1C calculated from average glucose
- **CV (Coefficient of Variation)**: Glucose variability measure. <36% is considered stable
- **Time in Range**: Percentage of readings in each glucose range

## License

MIT License - see [LICENSE](LICENSE) file.

## Contributing

Contributions welcome! Please feel free to submit a Pull Request.

## Appendix: How Nightscout Units Work

If you're wondering why we need to convert units when Nightscout already has a `DISPLAY_UNITS` setting - here's the quirk:

**The Nightscout API always returns glucose values in mg/dL**, regardless of your display settings. This is a deliberate design decision:

- **Database storage**: Always mg/dL (integers are easier to store and compare)
- **API responses**: Always mg/dL (the `sgv` field is always in mg/dL)
- **`DISPLAY_UNITS` setting**: Only affects the Nightscout web UI, not the API

So a European user with `DISPLAY_UNITS=mmol` will see `8.4 mmol/L` on their Nightscout dashboard, but the API still returns `"sgv": 152` (mg/dL). Every Nightscout client app (including this skill) must convert values for display if the user prefers mmol/L.

This skill reads your `DISPLAY_UNITS` setting and converts automatically - you don't need to configure anything extra.

## Related

- [Nightscout](http://www.nightscout.info/) - Open source CGM data platform
- [Agent Skills](https://github.com/agentskills/agentskills) - Open standard for AI agent skills
- [GitHub Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli) - AI-powered terminal assistant

## Development

### Running Tests

The skill has 150 tests covering all functionality:

```bash
cd ~/.copilot/skills/nightscout-cgm

# Run all tests
python -m pytest tests/ -v

# Quick run (just pass/fail)
python -m pytest tests/ -q

# With coverage report
python -m pytest tests/ --cov=scripts --cov-report=term-missing

# Run specific test file
python -m pytest tests/test_real_data.py -v
```

**Always run tests before and after modifying cgm.py.**

### Test Structure

| File | Description |
|------|-------------|
| test_pure_functions.py | Unit conversion, stats, sparklines |
| test_database.py | SQLite storage operations |
| test_analysis.py | Pattern analysis, worst days |
| test_charts.py | Chart rendering output |
| test_cli.py | Command-line argument parsing |
| test_edge_cases.py | Error handling, boundaries |
| test_real_data.py | Tests using real Nightscout API responses |

