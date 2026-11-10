# Retraction Checker frontend checklist

## B12 — React + TypeScript frontend

- [x] B12.1 Scaffold Vite React + TypeScript frontend; React Router is installed.
- [x] B12.2 Inspect frontend structure, package configuration, Vite setup, and Flask API/authentication.
- [x] B12.3 Add routed sign-in, registration, document dashboard, and analysis results screens.
- [x] B12.4 Integrate Flask cookie sessions and CSRF tokens for state-changing requests.
- [x] B12.5 Connect PDF upload, document history, and reference results to existing API endpoints.
- [x] B12.6 Configure Vite `/api` proxy to Flask at `127.0.0.1:5000`.
- [x] B12.7 Run frontend build and lint; both pass.
- [ ] B12.8 Verify the frontend against a running Flask backend, including registration, login, PDF analysis, history, results, and logout.

## B13 — Analysis reliability and error handling

- [x] B13.1 Validate uploaded PDF format, size, structure, encryption, and readable text before analysis.
- [x] B13.2 Return distinct safe API codes and messages for PDF errors, missing references, GROBID, Retraction Watch data, database saves, and unexpected analysis failures.
- [x] B13.3 Keep technical exception details in server logs and return JSON error codes for frontend handling.
- [x] B13.4 Add backend tests for PDF validation and analysis error responses.
- [x] B13.5 Run the full backend test suite (93 passed), frontend production build, and frontend lint.
- [ ] B13.6 Verify with a running GROBID service and a user supplied PDF; the previous failing PDF is not retained by the application.

## B14 — Reference verification statuses

- [x] B14.1 Add explicit `retracted`, `verified`, `not_verified`, and `missing_doi` statuses while retaining `is_retracted` for compatibility.
- [x] B14.2 Mark absent DOI matches as `not_verified` when the Retraction Watch snapshot is stale.
- [x] B14.3 Add an idempotent migration and classify historical negative results conservatively.
- [x] B14.4 Create pre-migration backups and migrate the active analysis database.
- [x] B14.5 Display the four statuses distinctly in reference reports.
- [x] B14.6 Add migration and status tests (48 focused tests passed).

## B15 — Guest mode and analysis history controls

- [x] B15.1 Add a public landing page with guest and account entry points.
- [x] B15.2 Add a public, CSRF-protected guest analysis endpoint with one report per session and an IP rate limit.
- [x] B15.3 Keep reports from the compatibility guest endpoint in bounded, process-local memory for one hour; authorize reads by the current session.
- [x] B15.4 Reuse PDF preflight and temporary-file cleanup for guest analyses without saving them to the user database; remove only expired app-named temporary PDFs after an interrupted run.
- [x] B15.5 Add report deletion for authenticated users with owner checks and ORM cascades.
- [x] B15.6 Preserve notifications without their document link and retain shared retraction publication records when an analysis is deleted.
- [x] B15.7 Add guest isolation, expiry, rate-limit, delete ownership, and cascade tests.
- [x] B15.8 Run the full backend test suite (106 passed), frontend build, and lint.
- [ ] B15.9 Replace process-local guest storage and rate limiting with a shared service before running multiple application workers.

## Integration notes

- Start Flask on port 5000 and Vite on port 5174 during this local session.
- Flask session cookies are sent with `credentials: 'include'`; no token is stored in browser local storage.
- Login, registration, upload, and logout send the CSRF token obtained from `/api/csrf`.
- The application database was additively migrated for B14; the user database was not changed. Two pre-migration backups were created, and no existing backups were removed.
- PDF preflight uses `pypdf==6.21.4`; install Python dependencies from `requirements.txt` in the project virtual environment.
- Reports from the older synchronous guest endpoint live in process memory for one hour. The frontend now uses the persistent queued endpoint, with a 48-hour lifetime. Both allow one guest analysis per session; requests are limited to three per IP per hour.
- The legacy guest report store and rate limiter are process-local. The queued report data is in SQLite. A multi-worker deployment still needs shared rate-limit storage and a single-worker coordination strategy.

## B16 — Background analyses and email notifications

- [x] B16.1 Add persistent analysis-job records and queue endpoints while keeping the existing synchronous API routes available.
- [x] B16.2 Add a separate worker process; queued work continues if the browser page closes, and unfinished jobs are re-queued when the single worker restarts.
- [x] B16.3 Update the frontend to poll job status without cancelling work when the user opens another report.
- [x] B16.4 Store guest reports in the application database and support a signed, 48-hour email link.
- [x] B16.5 Add configurable SMTP email delivery for account and guest reports.
- [x] B16.6 Simplify the landing page copy and remove the fabricated sample report artwork.
- [x] B16.7 Add tests for queueing, worker completion, SMTP-ready email content, missing-email configuration, and report-link access; full suite passes (110 tests), frontend build and lint pass.
- [ ] B16.8 Configure SMTP and `APP_PUBLIC_URL`, start the worker, and verify email delivery end to end.

### Running background analysis locally

- Start Flask and the Vite frontend as before, then start one worker in another terminal with `.venv/bin/python -m app.analysis_worker`.
- Email requires `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_SSL` or `SMTP_USE_STARTTLS`, `MAIL_FROM`, and `APP_PUBLIC_URL` in `.env`. Never commit real credentials.
- The GROBID request has a configurable 300-second safety timeout (`GROBID_TIMEOUT`); the browser itself has no analysis timeout. The 3-second frontend interval only refreshes status.
- Flask was restarted from this project and the Vite proxy now returns JSON responses from the current routes. One analysis worker is running in this session.

## B17 — GROBID performance on Apple Silicon

- [x] B17.1 Diagnose the bottleneck as GROBID reference extraction, before DOI lookups.
- [x] B17.2 Replace the amd64-only GROBID 0.8.2 image, which Docker emulated on this arm64 Mac, with the native arm64 GROBID 0.9.1 CRF image.
- [x] B17.3 Restart GROBID and confirm `/api/isalive` returns `true`.
- [x] B17.4 Resume the interrupted PDF analysis; the saved report now has three findings (one retracted and two verified).
- [x] B17.5 Re-run the same one-page PDF through GROBID without saving another report: first run 48.63 seconds, warm run 1.65 seconds; both extracted three references.
- [ ] B17.6 Measure a new full analysis from upload through database save and compare with a longer real paper.

## B18 — Report filters and email notice cleanup

- [x] B18.1 Remove dashboard and guest-report warnings that expose failed email delivery; keep the analysis-in-progress status neutral.
- [x] B18.2 Replace the single retraction checkbox with a reference filter for all, retracted, and missing-DOI entries.
- [x] B18.3 Add focused automated tests for all three filter modes, including blank and absent DOI values.
- [x] B18.4 Verify frontend tests, production build, and lint after the UI changes.
- [x] B18.5 Remove the persistent upload-success banner; the active-job row remains the analysis status.

## B19 — Daily retraction status notifications

- [x] B19.1 Replace the browser-native delete confirmation with a styled in-app dialog.
- [x] B19.2 Add a durable daily status check for saved references that were previously verified.
- [x] B19.3 Change a reference to retracted only on its first verified-to-retracted transition and queue one account notification.
- [x] B19.4 Send one digest email per affected account and record successful delivery to prevent repeat alerts.
- [x] B19.5 Add tests for status transition deduplication, email delivery deduplication, and missing SMTP settings.
- [ ] B19.6 Configure real SMTP credentials and verify delivery end to end.
- [x] B19.7 Restart the background worker and confirm the daily monitor records its first successful check.

The monitor runs in the single background worker, checks at most once every 24 hours, and retries queued email delivery hourly. It only promotes a saved `verified` reference to `retracted`; already retracted, unverified, and missing-DOI references do not generate alerts. Real delivery remains pending until SMTP settings are added to the local `.env` file.

## B20 — Email confirmation for new accounts

- [x] B20.1 Add a one-time, hashed confirmation token that expires after 24 hours.
- [x] B20.2 Require confirmation before a new account can sign in, and provide a resend-link endpoint and UI.
- [x] B20.3 Preserve existing accounts as confirmed through an additive users-database migration.
- [x] B20.4 Add API tests for confirmation, blocked login, one-time use, resend invalidation, and migration behavior.
- [x] B20.5 Add a confirmation page opened from the email link.
- [ ] B20.6 Select and configure the application's email provider, then verify actual delivery for registration and retraction notices.

## B21 — DOI-to-publication identity verification

- [x] B21.1 Resolve DOI metadata with DOI content negotiation and compare it with the extracted citation title.
- [x] B21.2 Compare the first author when both the citation and DOI metadata provide one; recognize editorial title prefixes such as `Retraction:`.
- [x] B21.3 Only classify a reference as verified or retracted after its DOI is confirmed against the citation; otherwise return `not_verified` with an explanation.
- [x] B21.4 Persist verification notes and show them in reports; preserve old retraction flags with a review note and conservatively reclassify legacy `verified` results as `not_verified`.
- [x] B21.5 Back up the existing SQLite analysis database before applying the additive identity-verification migration.
- [x] B21.6 Add tests for matching and mismatching DOI metadata, unavailable metadata, retracted-title prefixes, first-author mismatches, and migration behavior; all 131 backend tests pass, and frontend tests, build, and lint pass.
- [ ] B21.7 Re-upload a real PDF in the running app to confirm the complete GROBID-to-report flow with the new DOI check.

DOI metadata is retrieved from the DOI resolver using CSL JSON content negotiation. If the resolver cannot provide comparable metadata, the app does not claim `verified`; it marks the reference `not_verified` and explains why.
