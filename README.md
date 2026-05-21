# Tableau Pulse Metric Audit

This project audits Tableau Pulse metric definitions using the Tableau Cloud REST API (v3.21+).

## Features
- Authenticates using Personal Access Token (PAT) from environment variables
- Produces three audit CSVs:
  1. Certified metrics with non-certified datasource
  2. Metric definitions with no active subscriptions
  3. Metric definitions with dead or unreachable datasources
- Robust error handling and progress logging

## Setup
1. Set the following environment variables:
   - `TABLEAU_SERVER` (e.g. https://your-domain.tableaucloud.com)
   - `TABLEAU_SITE` (site content URL, not display name)
   - `TABLEAU_PAT_NAME`
   - `TABLEAU_PAT_SECRET`
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the script:
   ```bash
   python audit_pulse_metrics.py
   ```

## References
- [Tableau Pulse REST API Docs](https://help.tableau.com/current/api/rest_api/en-us/REST/rest_api_ref_pulse.htm)
