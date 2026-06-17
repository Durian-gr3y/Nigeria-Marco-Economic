# Codex Prompt — Nigeria Macroeconomic Dashboard: Automated Data Pipeline

---

## Project Context

You are building the automated data pipeline for a **Nigeria Macroeconomic Dashboard** — a static HTML/JS webpage hosted on GitHub Pages that displays seven key economic indicators for Nigeria. Your job is to produce every file needed for the pipeline to work end-to-end. Do not produce stubs or outlines. Every file must be complete, runnable code.

The dashboard reads from a single file called `data/data.json`. Your pipeline fetches data from three free public APIs on a bi-weekly schedule, merges the results into that JSON file, and commits it back to the repository. GitHub Pages then serves the updated dashboard automatically.

---

## Repository File Structure to Create

Produce the following files. Create all of them — do not skip any:

```
.github/
  workflows/
    update-data.yml         ← GitHub Actions workflow (bi-weekly trigger)

scripts/
  fetch_data.py             ← Python script that hits all APIs and writes data.json
  requirements.txt          ← Python dependencies (requests only)

data/
  data.json                 ← Initial seed file with placeholder values

.env.example                ← Template showing which secrets are needed (no real values)
README_PIPELINE.md          ← Setup instructions for configuring secrets and first run
```

---

## Task 1 — GitHub Actions Workflow (`.github/workflows/update-data.yml`)

### Schedule
Run the workflow **every two weeks**, specifically at **06:00 UTC on the 1st and 15th of every month**:

```
cron: '0 6 1,15 * *'
```

Also expose a `workflow_dispatch` trigger so the workflow can be run manually from the GitHub Actions UI at any time (e.g. for testing or an emergency data refresh).

### Jobs
Define a single job called `fetch-and-commit` that runs on `ubuntu-latest`.

### Steps, in order:
1. `actions/checkout@v4` — check out the repository with `persist-credentials: true` so the commit step can push
2. `actions/setup-python@v5` with `python-version: '3.11'`
3. Install dependencies: `pip install -r scripts/requirements.txt`
4. Run the fetch script: `python scripts/fetch_data.py`
   - Pass the following environment variables to this step from GitHub Secrets:
     - `EIA_API_KEY: ${{ secrets.EIA_API_KEY }}`
     - `ALPHA_VANTAGE_KEY: ${{ secrets.ALPHA_VANTAGE_KEY }}`
5. Commit and push using `stefanzweifel/git-auto-commit-action@v5` with:
   - `commit_message`: `"data: bi-weekly macro update [skip ci]"`
   - `file_pattern`: `data/data.json`

The `[skip ci]` tag in the commit message is critical — it prevents the commit from triggering a new workflow run, which would cause an infinite loop.

---

## Task 2 — Python Fetch Script (`scripts/fetch_data.py`)

### Overview
The script fetches data from three APIs, merges results into the existing `data.json`, and writes the updated file. It must **never crash the entire run** if one API fails — it should catch exceptions per-source, log the failure, and preserve the previous value for that indicator with a `stale: true` flag.

### API Source 1 — World Bank API (no key required)

Base URL: `https://api.worldbank.org/v2/country/NG/indicator/{INDICATOR}?format=json&per_page=10&mrv=10`

Fetch the following three indicators:

| Field in data.json | World Bank Indicator Code | Notes |
|--------------------|--------------------------|-------|
| `externalReserves` | `FI.RES.TOTL.CD` | Returns USD. Divide by 1,000,000,000 to get USD billions. Round to 2 decimal places. |
| `publicDebt` | `GC.DOD.TOTL.GD.ZS` | Returns % of GDP directly. Round to 1 decimal place. |
| `inflationTrend` | `FP.CPI.TOTL.ZG` | Returns annual % change. Use the last 10 non-null values for the `history` array. Round to 1 decimal place. |

The World Bank response format is an array of two elements: `[metadata, dataArray]`. Iterate `dataArray` and skip entries where `value` is `None`/`null`. The `date` field is a year string (e.g. `"2023"`).

### API Source 2 — EIA API (requires free key: `EIA_API_KEY` env var)

Base URL: `https://api.eia.gov/v2/`

#### Brent Crude Price
Endpoint: `https://api.eia.gov/v2/petroleum/pri/spt/data/`

Query parameters:
```
api_key={EIA_API_KEY}
frequency=monthly
data[0]=value
facets[series][]=RBRTE
sort[0][column]=period
sort[0][direction]=desc
length=6
```

Response path: `response["data"]` — a list of dicts with `period` (format `"YYYY-MM"`) and `value` (string, cast to float). Take the most recent non-null entry as `current`, the second most recent as `previous`. Round to 2 decimal places. Unit: `USD/bbl`. Build a `history` array from all 6 entries (oldest first).

#### Nigeria Crude Oil Production
Endpoint: `https://api.eia.gov/v2/international/data/`

Query parameters:
```
api_key={EIA_API_KEY}
frequency=monthly
data[0]=value
facets[activityId][]=1
facets[productId][]=53
facets[countryRegionId][]=NGA
sort[0][column]=period
sort[0][direction]=desc
length=6
```

Response path: `response["data"]` — same structure as above. Values are in thousand barrels/day. Divide by 1000 to convert to mbpd (million barrels per day). Round to 3 decimal places. Unit: `mbpd`.

### API Source 3 — Alpha Vantage (requires free key: `ALPHA_VANTAGE_KEY` env var)

#### USD/NGN Exchange Rate
Endpoint: `https://www.alphavantage.co/query`

Query parameters:
```
function=FX_MONTHLY
from_symbol=USD
to_symbol=NGN
apikey={ALPHA_VANTAGE_KEY}
```

Response key: `"Time Series FX (Monthly)"` — a dict of date strings (`"YYYY-MM-DD"`) to OHLC dicts. Sort the keys descending. Take the most recent entry's `"4. close"` as `current`, the second entry's `"4. close"` as `previous`. Cast both to float. Round to 2 decimal places. Unit: `NGN/USD`. Build a `history` array from the last 12 entries (oldest first), each entry being `{"period": "YYYY-MM", "value": float}`.

If the Alpha Vantage response contains a key `"Note"` (rate limit message) or `"Information"`, treat this as a failure and preserve the previous value.

---

## Task 3 — Data Schema (`data/data.json`)

The script must read the existing `data.json` before fetching (to use previous values as fallback) and write back the full updated object. The schema is as follows — produce this as the initial seed file with placeholder values and `"stale": true` on all indicators:

```json
{
  "meta": {
    "lastUpdated": "2025-06-01",
    "nextUpdate": "2025-06-15",
    "updateFrequency": "bi-weekly",
    "timezone": "UTC"
  },
  "indicators": {
    "inflation": {
      "label": "Headline Inflation",
      "current": null,
      "previous": null,
      "unit": "%",
      "period": null,
      "source": "NBS",
      "sourceUrl": "https://nigerianstat.gov.ng",
      "trend": "neutral",
      "note": "manual_update",
      "stale": true,
      "history": []
    },
    "inflationTrend": {
      "label": "Inflation Trend (Annual CPI %)",
      "current": null,
      "previous": null,
      "unit": "%",
      "period": null,
      "source": "World Bank",
      "sourceUrl": "https://data.worldbank.org",
      "trend": "neutral",
      "stale": true,
      "history": []
    },
    "mpr": {
      "label": "Monetary Policy Rate",
      "current": null,
      "previous": null,
      "unit": "%",
      "period": null,
      "source": "CBN",
      "sourceUrl": "https://www.cbn.gov.ng",
      "trend": "neutral",
      "note": "manual_update",
      "stale": true,
      "history": []
    },
    "exchangeRate": {
      "label": "USD/NGN Exchange Rate",
      "current": null,
      "previous": null,
      "unit": "NGN/USD",
      "period": null,
      "source": "Alpha Vantage",
      "sourceUrl": "https://www.alphavantage.co",
      "trend": "neutral",
      "stale": true,
      "history": []
    },
    "externalReserves": {
      "label": "External Reserves",
      "current": null,
      "previous": null,
      "unit": "USD Bn",
      "period": null,
      "source": "World Bank",
      "sourceUrl": "https://data.worldbank.org",
      "trend": "neutral",
      "stale": true,
      "history": []
    },
    "publicDebt": {
      "label": "Public Debt (% of GDP)",
      "current": null,
      "previous": null,
      "unit": "% of GDP",
      "period": null,
      "source": "World Bank / DMO",
      "sourceUrl": "https://www.dmo.gov.ng",
      "trend": "neutral",
      "stale": true,
      "history": []
    },
    "oilPrice": {
      "label": "Brent Crude Price",
      "current": null,
      "previous": null,
      "unit": "USD/bbl",
      "period": null,
      "source": "EIA",
      "sourceUrl": "https://www.eia.gov",
      "trend": "neutral",
      "stale": true,
      "history": []
    },
    "oilProduction": {
      "label": "Nigeria Oil Production",
      "current": null,
      "previous": null,
      "unit": "mbpd",
      "period": null,
      "source": "EIA",
      "sourceUrl": "https://www.eia.gov",
      "trend": "neutral",
      "stale": true,
      "history": []
    }
  }
}
```

### Trend computation rule
After updating `current` and `previous`, compute `trend` as follows:
- If `current > previous` → `"up"`
- If `current < previous` → `"down"`
- If equal or either is null → `"neutral"`

### `period` field format
- World Bank indicators: use the `date` string as-is (e.g. `"2023"`)
- EIA and Alpha Vantage: use `"YYYY-MM"` format from the response period string
- Always use the most recent non-null value's period

### `stale` flag
Set `"stale": false` when an indicator was successfully updated in this run. Set `"stale": true` when the previous value was preserved due to an API failure. Leave it unchanged for `manual_update` fields (`inflation`, `mpr`) which the script never touches.

### `meta.lastUpdated` and `meta.nextUpdate`
Set `meta.lastUpdated` to today's date in `YYYY-MM-DD` format using `datetime.utcnow()`. Compute `meta.nextUpdate` as follows:
- If today is the 1st–14th of the month → next update is the 15th of the same month
- If today is the 15th–31st → next update is the 1st of the next month

---

## Task 4 — Dependencies (`scripts/requirements.txt`)

```
requests==2.31.0
```

No other libraries. Use only the Python standard library and `requests`.

---

## Task 5 — Environment Template (`.env.example`)

```
# Copy this file to .env for local testing.
# For GitHub Actions, add these as repository secrets under:
# Settings → Secrets and variables → Actions → New repository secret

EIA_API_KEY=your_eia_api_key_here
ALPHA_VANTAGE_KEY=your_alpha_vantage_key_here

# How to get these keys (both are free):
# EIA:           https://www.eia.gov/opendata/register.php
# Alpha Vantage: https://www.alphavantage.co/support/#api-key
```

---

## Task 6 — Setup Instructions (`README_PIPELINE.md`)

Write a clear, concise README covering exactly:
1. What the pipeline does and which files it creates/modifies
2. How to register for both free API keys (EIA and Alpha Vantage) with links
3. How to add the two secrets in GitHub (exact menu path: Settings → Secrets and variables → Actions)
4. How to run the workflow manually for the first time using workflow_dispatch
5. How to manually update the two indicators that have no API (`inflation` and `mpr`) — instruct the user to edit `data/data.json` directly, update `current`, `previous`, `period`, `trend`, and set `stale: false`
6. How to verify the pipeline ran successfully (GitHub Actions log + checking `data/data.json` commit history)

---

## Non-Negotiable Requirements

1. **No API keys in code.** All keys must be read from environment variables using `os.environ.get()`. If a key is missing, log a warning and skip that source — do not raise an exception.
2. **Never overwrite manual fields.** The script must never modify `inflation.current`, `inflation.previous`, `mpr.current`, or `mpr.previous`. These fields carry a `"note": "manual_update"` marker. Detect this flag and skip those indicators entirely.
3. **Atomic file write.** Write the JSON to a temp file first, then rename it to `data/data.json`. This prevents a partial write from corrupting the file if the script is interrupted.
4. **Preserve history array length.** Cap the `history` array at 24 entries (2 years). If new data would push it beyond 24, drop the oldest entry first.
5. **Logging.** Use Python's `logging` module (not `print`). Log at INFO level for each successful fetch and at WARNING level for each failure. Include the indicator name and the HTTP status code or exception message in every log line.
6. **Exit code.** If all three API sources fail in a single run, exit with code 1 so GitHub Actions marks the run as failed. If at least one source succeeds, exit with code 0.
7. **Idempotent.** Running the script twice in a row should produce the same output (the second run just re-fetches and writes the same data).
