---
name: nightscout-cgm
description: Analyze CGM blood glucose data from Nightscout. Use this skill when asked about current glucose levels, blood sugar trends, A1C estimates, time-in-range statistics, glucose variability, or diabetes management insights.
---

# Nightscout CGM Analysis Skill

This skill provides tools for fetching and analyzing Continuous Glucose Monitor (CGM) data from Nightscout.

## ⚠️ Before Making Changes

**Always run tests before and after modifying `cgm.py`:**

```bash
cd <skill-path>
python -m pytest tests/ -q           # Quick check (150 tests)
python -m pytest tests/ --cov=scripts  # With coverage
```

## Available Commands

Run the `cgm.py` script from this skill's `scripts/` directory:

```bash
python <skill-path>/scripts/cgm.py <command> [options]
```

Where `<skill-path>` is the location where this skill is installed (e.g., `~/.copilot/skills/nightscout-cgm`, `.github/skills/nightscout-cgm`, or `.claude/skills/nightscout-cgm`).

### Commands

| Command | Description |
|---------|-------------|
| `current` | Get the latest glucose reading |
| `analyze [--days N]` | Analyze CGM data (default: 90 days) |
| `refresh [--days N]` | Fetch latest data from Nightscout |
| `patterns [--days N]` | Find interesting patterns (best/worst times, problem areas) |
| `query [options]` | Query with filters (day of week, time range) |
| `day <date> [options]` | View all readings for a specific date |
| `worst [options]` | Find your worst days for glucose control |
| `chart [options]` | Terminal visualizations (heatmap, sparkline, day chart) |
| `goal <action>` | Set and track personal goals (TIR, CV, GMI, average glucose) |
| `report [options]` | Generate interactive HTML report with charts |

### Goal Command

Set and track personal goals for your glucose management:
- `goal set [--tir PCT] [--cv PCT] [--gmi VALUE] [--avg-glucose VALUE]` - Set goals
- `goal view` - View current goals
- `goal progress [--days N]` - Track progress toward goals (default: 7 days)
- `goal clear [metric]` - Clear specific goal or all goals

### Day Command

View detailed readings for a specific date:
- `day <date>` - Date can be 'today', 'yesterday', '2026-01-16', or 'Jan 16'
- `--hour-start H` - Start hour for time window (0-23)
- `--hour-end H` - End hour for time window (0-23)

### Worst Command

Find your worst days ranked by peak glucose:
- `--days N` - Number of days to search (default: 21)
- `--hour-start H` - Start hour for time window (0-23)
- `--hour-end H` - End hour for time window (0-23)
- `--limit N` - Number of worst days to show (default: 5)

### Query Options

The `query` command supports flexible filtering:
- `--days N` - Number of days to analyze (default: 90)
- `--day NAME` - Filter by day of week (e.g., Tuesday, or 0-6 where 0=Monday)
- `--hour-start H` - Start hour for time window (0-23)
- `--hour-end H` - End hour for time window (0-23)

### Chart Options

The `chart` command creates terminal visualizations:
- `--sparkline` - Compact trend line using Unicode blocks (▁▂▃▄▅▆▇█)
- `--hours N` - Hours of data for sparkline (default: 24)
- `--date DATE` - Specific date for sparkline (e.g., today, yesterday, 2026-01-16)
- `--hour-start H` - Start hour for sparkline time window (0-23)
- `--hour-end H` - End hour for sparkline time window (0-23)
- `--heatmap` - Weekly grid showing time-in-range by day and hour
- `--day NAME` - Hourly breakdown for a specific day of week
- `--color` - Use ANSI colors (for direct terminal, not inside Copilot)

### Examples

```bash
# Get current glucose
python scripts/cgm.py current

# Analyze last 30 days
python scripts/cgm.py analyze --days 30

# Find patterns automatically (best/worst times, problem areas)
python scripts/cgm.py patterns

# What happened yesterday during lunch (11am-2pm)?
python scripts/cgm.py day yesterday --hour-start 11 --hour-end 14

# Find my worst lunch days in the last 3 weeks
python scripts/cgm.py worst --days 21 --hour-start 11 --hour-end 14

# What happens on Tuesdays after lunch?
python scripts/cgm.py query --day Tuesday --hour-start 12 --hour-end 15

# How are my overnight numbers on weekends?
python scripts/cgm.py query --day Saturday --hour-start 22 --hour-end 6
python scripts/cgm.py query --day Sunday --hour-start 22 --hour-end 6

# Morning analysis across all days
python scripts/cgm.py query --hour-start 6 --hour-end 10

# Show sparkline of last 24 hours (compact visual trend)
python scripts/cgm.py chart --sparkline --hours 24

# Show sparkline for a specific date and time range (with colors)
python scripts/cgm.py chart --date yesterday --hour-start 11 --hour-end 15 --color

# Show heatmap of time-in-range by day/hour
python scripts/cgm.py chart --heatmap

# Show hourly breakdown for a specific day
python scripts/cgm.py chart --day Saturday

# Set a Time-in-Range goal of 70%
python scripts/cgm.py goal set --tir 70

# Set multiple goals at once
python scripts/cgm.py goal set --tir 70 --cv 33 --gmi 6.5

# View current goals
python scripts/cgm.py goal view

# Track progress toward goals (last 7 days)
python scripts/cgm.py goal progress

# Generate interactive HTML report with goal indicators
python scripts/cgm.py report --days 90 --open

# Refresh data from Nightscout
python scripts/cgm.py refresh
```

## Example Questions You Can Ask

With the pattern analysis capabilities, you can ask natural questions like:

- "What's my current glucose?"
- "Analyze my blood sugar for the last 30 days"
- "What patterns do you see in my data?"
- "What's happening on Tuesdays after lunch?"
- "When are my worst times for blood sugar control?"
- "How are my overnight numbers?"
- "When do I tend to go low?"
- "What day of the week is my best for time-in-range?"
- "Show me my morning patterns"
- "Show me a sparkline of my last 24 hours"
- "Show me a heatmap of my glucose"
- "What does Saturday look like?"
- "What was my worst lunch this week?" (you'll be asked what hours you eat lunch)
- "Show me what happened yesterday during dinner"
- "What were my worst days for breakfast the last two weeks?"
- "Set a time-in-range goal of 70%"
- "What's my progress toward my CV goal?"
- "Show me a report with my goal progress"

## Output Interpretation

### Time in Range (TIR)
- **Very Low** (<54 mg/dL): Dangerous hypoglycemia
- **Low** (54-69 mg/dL): Hypoglycemia
- **In Range** (70-180 mg/dL): Target range
- **High** (181-250 mg/dL): Hyperglycemia
- **Very High** (>250 mg/dL): Significant hyperglycemia

### Key Metrics
- **GMI**: Glucose Management Indicator (estimated A1C from CGM data)
- **CV**: Coefficient of Variation (<36% indicates stable glucose)
- **Hourly Averages**: Shows patterns throughout the day

## Configuration (Required)

Set the `NIGHTSCOUT_URL` environment variable to your Nightscout API endpoint:

```bash
# Linux/macOS
export NIGHTSCOUT_URL="https://your-nightscout-site.com/api/v1/entries.json"

# Windows PowerShell
$env:NIGHTSCOUT_URL = "https://your-nightscout-site.com/api/v1/entries.json"

# Windows (persistent)
[Environment]::SetEnvironmentVariable("NIGHTSCOUT_URL", "https://your-nightscout-site.com/api/v1/entries.json", "User")
```

The script will not run without this environment variable configured.
