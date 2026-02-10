# FreeStyle Libre 3 Integration Analysis

## Executive Summary

**The nightscout-cgm-skill already works with FreeStyle Libre 3 data** — but only indirectly, through Nightscout as an intermediary. This document analyzes whether a *direct* integration with Abbott's FreeStyle Libre 3 is feasible and what it would entail.

**Verdict:** Direct integration is possible via the unofficial LibreLinkUp API, but Nightscout remains the recommended path for most users. A hybrid approach — adding LibreLinkUp as an optional alternative data source — offers the best tradeoff.

---

## Current State

### How Libre 3 Data Reaches This Skill Today

```
Libre 3 Sensor
    ↓ (Bluetooth)
FreeStyle Libre 3 / LibreLink App (phone)
    ↓ (upload)
Abbott LibreView Cloud
    ↓ (bridge app: xDrip+, Juggluco, Diabox, or LibreLinkUp→Nightscout plugin)
Nightscout Server
    ↓ (GET /api/v1/entries.json)
nightscout-cgm-skill (cgm.py)
    ↓
Local SQLite → Analysis & Reports
```

This works today. Users with Libre 3 who already run Nightscout can use every feature of this skill without modification. The `device` field in the database will contain a Libre-specific identifier, but no code paths branch on device type.

### What References to Libre Already Exist

- `README.md`: References Libre in the context of AGP report formatting
- `cgm.py:4956`: Notes that AGP matches the clinical format used by "Dexcom, Libre, and diabetes clinics"
- No device-specific code for any CGM manufacturer

---

## Direct Integration Options

### Option 1: LibreLinkUp API (Recommended for Direct Integration)

Abbott does **not** publish an official public API. However, the community has reverse-engineered the LibreLinkUp sharing service endpoints:

**API Details:**

| Item | Value |
|------|-------|
| Base URL | `https://api.libreview.io` (US) / `https://api-eu.libreview.io` (EU) |
| Auth | `POST /llu/auth/login` with email/password → JWT token (~6 month validity) |
| Connections | `GET /llu/connections` → list of patients with current reading |
| Graph Data | `GET /llu/connections/{patientId}/graph` → 12h of 15-min averages |
| Required Headers | `product: llu.android`, `version: 4.2.1`, `Authorization: Bearer <JWT>` |

**Glucose Reading Structure (from LibreLinkUp):**
```json
{
  "Value": 125,
  "TrendArrow": 3,
  "FactoryTimestamp": "1/15/2026 2:30:00 PM",
  "Timestamp": "1/15/2026 2:30:00 PM",
  "isHigh": false,
  "isLow": false,
  "MeasurementColor": 1
}
```

**Mapping to Current Schema:**

| Current Schema (readings) | LibreLinkUp Source | Notes |
|---------------------------|-------------------|-------|
| `id` | Generated (timestamp-based) | No `_id` from Abbott; generate `libre-{timestamp}` |
| `sgv` | `Value` | Already in mg/dL |
| `date_ms` | `Timestamp` | Parse and convert to epoch ms |
| `date_string` | `Timestamp` | Convert to ISO format |
| `trend` | `TrendArrow` | Map to Nightscout trend codes (1-9) |
| `direction` | `TrendArrow` | Map to text: "Flat", "FortyFiveUp", etc. |
| `device` | Hardcoded | `"libre3-librelinkup"` |

**Trend Arrow Mapping:**

| LibreLinkUp TrendArrow | Nightscout Direction | Nightscout Trend Code |
|------------------------|---------------------|-----------------------|
| 1 | SingleDown | 6 |
| 2 | FortyFiveDown | 5 |
| 3 | Flat | 4 |
| 4 | FortyFiveUp | 3 |
| 5 | SingleUp | 2 |

**Existing Open-Source Clients:**
- [libre-link-up-api-client](https://github.com/DiaKEM/libre-link-up-api-client) (TypeScript, MIT license, 195+ stars)
- [libre-link-unofficial-api](https://github.com/DRFR0ST/libre-link-unofficial-api) (TypeScript, MIT license)

Both are TypeScript. A Python implementation would need to be written, but the API is simple enough (3 endpoints) that this is straightforward.

### Option 2: Third-Party Aggregator APIs

Services like [Terra API](https://tryterra.co/integrations/freestylelibre) and [Thryve](https://www.thryve.health/features/connections/abbott-freestyle-libre-integration) offer unified APIs that include Libre data. These are commercial services with costs and add another dependency. Not recommended for an open-source privacy-first tool.

### Option 3: Continue via Nightscout Only (Status Quo)

The current approach: users set up a Nightscout instance and use xDrip+, Juggluco, or similar bridge apps to get Libre 3 data into Nightscout. This skill then reads from Nightscout.

---

## Feasibility Assessment

### Technical Complexity: **Low to Moderate**

The skill's architecture makes this integration relatively clean:

1. **Data fetching is isolated** — `fetch_and_store()` at `cgm.py:326` is the single point where external data enters the system. Adding a parallel `fetch_from_librelinkup()` function is straightforward.

2. **Schema is compatible** — The `readings` table schema (`id`, `sgv`, `date_ms`, `date_string`, `trend`, `direction`, `device`) maps directly to LibreLinkUp data with minor transformations.

3. **All analysis is source-agnostic** — Every analytical function (`get_stats()`, `get_time_in_range()`, `analyze_cgm()`, report generation, etc.) operates on the `readings` table without checking where data came from.

4. **No new dependencies required** — The `requests` library already used for Nightscout calls is sufficient for the LibreLinkUp API.

### Risks and Limitations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Unofficial API** — Abbott could change endpoints without notice | High | Version-pin API version header; design for graceful failure |
| **Rate limiting** — Abbott may rate-limit or block automated access | Medium | Respect reasonable polling intervals (1-5 min minimum) |
| **Limited history** — LibreLinkUp only returns ~12 hours of data | High | More frequent syncs needed; cannot backfill like Nightscout |
| **Auth complexity** — Login may require handling Terms of Service acceptance, redirects, region-specific endpoints | Medium | Handle redirect logic; document manual LibreLinkUp app login for initial ToS |
| **No treatments/pump data** — LibreLinkUp only provides glucose readings | Low | Pump commands already handle "not available" gracefully |
| **Legal/ToS concerns** — Using an unofficial API may violate Abbott's Terms of Service | Medium | Document clearly; make opt-in only |

### What Would NOT Work with Direct LibreLinkUp Integration

These features depend on Nightscout-specific APIs and would not be available:

- `pump` command (requires `/api/v1/devicestatus.json`)
- `treatments` command (requires `/api/v1/treatments.json`)
- `profile` command (requires `/api/v1/profile.json`)
- Custom glucose thresholds from Nightscout settings (would need local config)
- Nightscout unit preference (would need local config)

---

## Recommended Implementation Approach

### Phase 1: Add LibreLinkUp as an Alternative Data Source

**New environment variables:**
```bash
# Option A: Use Nightscout (existing)
export NIGHTSCOUT_URL='https://your-site.herokuapp.com'

# Option B: Use LibreLinkUp directly (new)
export LIBRELINKUP_EMAIL='user@example.com'
export LIBRELINKUP_PASSWORD='password'
export LIBRELINKUP_REGION='US'  # or 'EU'
```

**New configuration logic:**
```
If NIGHTSCOUT_URL is set → use Nightscout (existing behavior)
If LIBRELINKUP_EMAIL is set → use LibreLinkUp
If both are set → use Nightscout as primary, LibreLinkUp as fallback
If neither → error with setup instructions for both options
```

**Implementation scope:**
- ~200-300 lines of new code in `cgm.py`
- New `fetch_from_librelinkup()` function
- LibreLinkUp auth handler (login, token caching, region redirect)
- Trend arrow mapping
- Timestamp parsing
- Modify `fetch_and_store()` to dispatch to the correct data source
- Add local config for thresholds/units when not using Nightscout

**Estimated new/modified files:**
- `scripts/cgm.py` — Add LibreLinkUp fetcher, modify data source selection
- `tests/test_librelinkup.py` — New test file (~100-150 tests)
- `tests/fixtures/librelinkup_response.json` — Mock API responses
- `README.md` — Document new configuration option
- `SKILL.md` — Add LibreLinkUp setup instructions

### Phase 2: Enhanced Libre-Specific Features (Optional)

- Sensor session tracking (Libre sensors last 14 days)
- Sensor warmup period detection
- Libre-specific data quality indicators

---

## Architecture Diagram (Proposed)

```
                  ┌─────────────────────────┐
                  │    cgm.py main()         │
                  │    fetch_and_store()      │
                  └────────┬────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
   ┌──────────────────┐    ┌──────────────────────┐
   │  Nightscout API   │    │  LibreLinkUp API      │
   │  (existing path)  │    │  (new path)           │
   │                    │    │                        │
   │  /api/v1/entries   │    │  /llu/auth/login       │
   │  /api/v1/status    │    │  /llu/connections      │
   │  /api/v1/device..  │    │  /llu/connections/     │
   │  /api/v1/treat..   │    │    {id}/graph          │
   │  /api/v1/profile   │    │                        │
   └────────┬───────────┘    └──────────┬─────────────┘
            │                           │
            └────────────┬──────────────┘
                         ▼
              ┌─────────────────────┐
              │  SQLite (readings)   │
              │  Unified schema      │
              └─────────┬───────────┘
                        ▼
              ┌─────────────────────┐
              │  Analysis Engine     │
              │  (unchanged)         │
              │  Reports, AGP, etc.  │
              └─────────────────────┘
```

---

## Comparison: Nightscout Path vs Direct LibreLinkUp

| Factor | Via Nightscout | Direct LibreLinkUp |
|--------|---------------|-------------------|
| **Setup complexity** | High (need Nightscout server + bridge app) | Low (just email/password) |
| **Data history** | Months/years (Nightscout stores everything) | ~12 hours per API call |
| **Update frequency** | Depends on bridge app (1-5 min) | Every 1 minute |
| **Pump/treatment data** | Yes (if Loop/OpenAPS) | No |
| **Custom thresholds** | From Nightscout settings | Must configure locally |
| **Reliability** | Stable (official Nightscout API) | Unofficial API, could break |
| **Privacy** | Data on user's own server | Reads from Abbott's cloud |
| **Cost** | Nightscout hosting costs | Free (Abbott's service) |
| **Maintenance burden** | Low (Nightscout community maintains bridges) | Medium (must track API changes) |

---

## Conclusion

Direct FreeStyle Libre 3 integration is **technically feasible** and would significantly lower the barrier to entry for Libre users who don't want to run a full Nightscout instance. The implementation is clean because:

1. The existing architecture already separates data fetching from analysis
2. The SQLite schema maps naturally to LibreLinkUp's data format
3. No analysis code needs to change
4. The `requests` library already handles HTTP calls

**The main tradeoff is reliability vs. accessibility.** The LibreLinkUp API is unofficial and could break at any time, but it eliminates the need for a Nightscout server, xDrip+, and bridge apps — which is a significant simplification for users who just want to analyze their Libre 3 data.

**Recommendation:** Implement as an opt-in alternative data source (Phase 1). Keep Nightscout as the default and recommended path. Document the risks of the unofficial API clearly.

---

## References

- [LibreLinkUp HTTP API Documentation (Gist)](https://gist.github.com/khskekec/6c13ba01b10d3018d816706a32ae8ab2)
- [libre-link-up-api-client (TypeScript)](https://github.com/DiaKEM/libre-link-up-api-client)
- [libre-link-unofficial-api (TypeScript)](https://github.com/DRFR0ST/libre-link-unofficial-api)
- [Nightscout Supported Uploaders](https://nightscout.github.io/uploader/uploaders/)
- [Nightscout Libre Guide](https://nightscout-user-guide.readthedocs.io/en/latest/docs/grundlagen/libre.html)
- [Nightscout Pro - Freestyle Libre](https://nightscout.pro/knowledge-base/freestyle-libre/)
- [Terra API - FreeStyle Libre Integration](https://tryterra.co/integrations/freestylelibre)
- [Thryve - Abbott FreeStyle Libre Integration](https://www.thryve.health/features/connections/abbott-freestyle-libre-integration)
