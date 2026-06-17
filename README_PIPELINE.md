# Nigeria Macro Data Pipeline

## What the pipeline does

This pipeline updates `data/data.json`, the single data file used by the Nigeria Macroeconomic Dashboard. It fetches public macroeconomic data from the World Bank, EIA, and Alpha Vantage, merges successful updates into the existing JSON, preserves previous values when a source fails, and commits the refreshed file back to the repository.

The pipeline files are:

- `.github/workflows/update-data.yml`: bi-weekly GitHub Actions workflow with manual run support.
- `scripts/fetch_data.py`: Python data fetch and merge script.
- `scripts/requirements.txt`: Python dependency list.
- `data/data.json`: dashboard data file.
- `.env.example`: local environment variable template.

## Register for API keys

Create free API keys for the two keyed data sources:

- EIA: https://www.eia.gov/opendata/register.php
- Alpha Vantage: https://www.alphavantage.co/support/#api-key

The World Bank API does not require a key.

## Add GitHub secrets

In your GitHub repository, go to `Settings -> Secrets and variables -> Actions -> New repository secret`.

Add these two repository secrets:

- `EIA_API_KEY`
- `ALPHA_VANTAGE_KEY`

Use the exact secret names above so the workflow can pass them to `scripts/fetch_data.py`.

## Run the workflow manually

For the first run, open the repository on GitHub and go to `Actions`. Select the `Update macro data` workflow, choose `Run workflow`, and confirm the run. This uses the `workflow_dispatch` trigger and is useful for testing before waiting for the scheduled run.

## Manually update inflation and MPR

Two indicators do not have API-backed updates: `inflation` and `mpr`. To update them, edit `data/data.json` directly.

For each manual indicator, update:

- `current`
- `previous`
- `period`
- `trend`
- `stale: false`

The fetch script detects `"note": "manual_update"` and never overwrites those manual values.

## Verify a successful run

Open the workflow run in GitHub Actions and confirm the `Fetch macro data` and `Commit updated data` steps completed successfully. Then check the commit history for `data/data.json` and confirm a commit with the message `data: bi-weekly macro update [skip ci]` updated the file.
