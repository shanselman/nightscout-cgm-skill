# Nightscout CGM Skill

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-Open%20Standard-blue)](https://github.com/agentskills/agentskills)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **⚠️ Disclaimer:** We are not doctors. This is DIY body hacking by and for the diabetes community. If you're using Nightscout, you already know the deal: **don't trust anyone or anything to make decisions about your blood sugar except yourself.** This tool is for informational purposes only and should never replace medical advice, your own judgment, or looking at your actual CGM.

An [Agent Skill](https://github.com/agentskills/agentskills) for analyzing Continuous Glucose Monitor (CGM) data from [Nightscout](http://www.nightscout.info/). Works with GitHub Copilot CLI, Claude Code, and VS Code agent mode.

## What It Does

- **Current Glucose**: Get real-time blood glucose readings with trend direction
- **CGM Analysis**: Calculate statistics, time-in-range, GMI (estimated A1C), and glucose variability
- **Data Refresh**: Fetch and cache CGM data from your Nightscout instance

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

## Usage

### With AI Agents

Just ask naturally:
- "What's my current glucose?"
- "Analyze my blood sugar for the last 30 days"
- "What's my estimated A1C?"
- "Show me my time in range"

### Direct CLI Usage

```bash
# Get current glucose reading
python scripts/cgm.py current

# Analyze last 90 days (default)
python scripts/cgm.py analyze

# Analyze last 30 days
python scripts/cgm.py analyze --days 30

# Refresh data from Nightscout
python scripts/cgm.py refresh --days 90
```

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
  "date_range": {"from": "2024-10-15", "to": "2024-01-15", "days_analyzed": 90},
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

This skill displays values in the units configured in your Nightscout instance (`DISPLAY_UNITS` setting). The script automatically detects whether your Nightscout is set to mg/dL or mmol/L.

| Range | mg/dL | mmol/L | Status |
|-------|-------|--------|--------|
| Very Low | <54 | <3.0 | Dangerous hypoglycemia |
| Low | 54-69 | 3.0-3.8 | Hypoglycemia |
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

## Related

- [Nightscout](http://www.nightscout.info/) - Open source CGM data platform
- [Agent Skills](https://github.com/agentskills/agentskills) - Open standard for AI agent skills
- [GitHub Copilot CLI](https://docs.github.com/copilot/concepts/agents/about-copilot-cli) - AI-powered terminal assistant
