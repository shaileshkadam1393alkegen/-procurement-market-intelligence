# Procurement Market Intelligence — private website MVP

A browser-based, invitation-only **development website** for public economic series, historical charts, simple trend scenarios, and in-app price movement alerts. Not an approved Alkegen system and not production-hardened.

## Local setup

Python 3.11+ required.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set a random secret; e.g. python -c "import secrets;print(secrets.token_urlsafe(48))"
# Windows PowerShell: $env:SESSION_SECRET="paste-long-random-secret"
# macOS/Linux: export SESSION_SECRET="paste-long-random-secret"
# Local HTTP ONLY: set COOKIE_SECURE=false (production must use HTTPS and true)
python create_admin.py
uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Log in using the admin account, click **Refresh official data**. First synchronization depends on network/API availability and may produce partial failures. Only an admin can trigger synchronization or invite users. Admins can invite users with the API endpoint `/api/admin/invite` using an authenticated browser or HTTP client, e.g. `POST` JSON `{"email":"colleague@example.com","password":"unique-strong-temporary-password","admin":false}`. This initial implementation does **not** have email invitations, password resets, MFA, or self-service enrollment. Share credentials securely, never in chat/email plaintext.

## Live data coverage

- BLS: US CPI all items, energy, gasoline, average hourly earnings, using BLS public v1 series endpoints (no key). Some series or requests may fail due to rate limits. Series IDs should be verified before production use.
- Eurostat: EA20 HICP and industrial producer price index using JSON-stat REST endpoints. The industrial PPI dimension filters are preliminary and may need adjustment; the adapter **fails closed** if any non-time dimension has multiple values.
- IMF, LME, India, UK and China: **not yet connected**. No data are fabricated for them.
- Observations stored in SQLite with original period, retrieval timestamp and source URL. Latest values are not guaranteed current until successful sync. Historical revisions overwrite observations; a production version needs vintage/revision auditing.
- The displayed MoM percentage compares adjacent stored observations. It is **not** an annual inflation rate and is not seasonally adjusted unless the specific source series is. YoY requires 13 contiguous monthly observations; the prototype checks count only, so production must verify continuity.
- Forecast cards are **unvalidated linear-trend extrapolations with heuristic ranges**, not statistically calibrated predictions. Do not use as a budgeting forecast without model validation and backtesting.
- Alerts: abs(MoM)>=2% WATCH; >=5% HIGH. One alert per series and period, with SQLite uniqueness. Alerts are in-app only. No email/push delivery. The initial rule applies to *index levels*, not published inflation rates; a production engine should support appropriate index-specific measures and revisions.

## Deployment and IT/security considerations

Deploy only after appropriate company authorization. The website can run on a Python-capable host with a persistent database, HTTPS, `SESSION_SECRET` configured, and `COOKIE_SECURE=true`. Static-only hosts cannot run the Python backend without a separate API service. Avoid using the Alkegen name/logo or importing supplier contracts, spend, personal data, or other company information without permission.

**Not production-ready:** add managed identity/MFA, CSRF protection for cookie-authenticated writes, rate limiting and lockout on login, audit logging, secrets management, managed Postgres, backups, secure invite tokens, session revocation, data quality and API integration tests, legal review of source terms, and a job scheduler with monitoring. Avoid putting this prototype directly on the public internet before those controls.

## Scheduling sync

A private administrator can trigger `/api/admin/sync` manually. For recurring refreshes, deploy a trusted scheduler with service-to-service authentication (not implemented here). Do not expose a publicly callable sync endpoint.

## Category modules

MRO, waste, industrial needles, heating elements, bearings, PPE/uniforms, labor/indirect services, logistics/packaging. Several categories currently share general macroeconomic indicators as **proxies**, not actual component price indexes. Category-specific metal, textile, chemical, waste PPI and labor series should be added with validated definitions and local relevance.
