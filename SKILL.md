---
name: nightscout-cgm
description: Analyze CGM blood glucose data from Nightscout. Use this skill when asked about current glucose levels, blood sugar trends, A1C estimates, time-in-range statistics, glucose variability, or diabetes management insights.
---

# Nightscout CGM Analysis Skill

This skill provides tools for fetching and analyzing Continuous Glucose Monitor (CGM) data from Nightscout.

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

### Query Options

The `query` command supports flexible filtering:
- `--days N` - Number of days to analyze (default: 90)
- `--day NAME` - Filter by day of week (e.g., Tuesday, or 0-6 where 0=Monday)
- `--hour-start H` - Start hour for time window (0-23)
- `--hour-end H` - End hour for time window (0-23)

### Examples

```bash
# Get current glucose
python scripts/cgm.py current

# Analyze last 30 days
python scripts/cgm.py analyze --days 30

# Find patterns automatically (best/worst times, problem areas)
python scripts/cgm.py patterns

# What happens on Tuesdays after lunch?
python scripts/cgm.py query --day Tuesday --hour-start 12 --hour-end 15

# How are my overnight numbers on weekends?
python scripts/cgm.py query --day Saturday --hour-start 22 --hour-end 6
python scripts/cgm.py query --day Sunday --hour-start 22 --hour-end 6

# Morning analysis across all days
python scripts/cgm.py query --hour-start 6 --hour-end 10

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
