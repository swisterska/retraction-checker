# Retraction Checker frontend checklist

## B12 — React + TypeScript frontend

- [x] B12.1 Scaffold Vite React + TypeScript frontend; React Router is installed.
- [x] B12.2 Inspect frontend structure, package configuration, Vite setup, and Flask API/authentication.
- [x] B12.3 Add routed sign-in, registration, document dashboard, and analysis results screens.
- [x] B12.4 Integrate Flask cookie sessions and CSRF tokens for state-changing requests.
- [x] B12.5 Connect PDF upload, document history, and reference results to existing API endpoints.
- [x] B12.6 Configure Vite `/api` proxy to Flask at `127.0.0.1:5000`.
- [ ] B12.7 Run frontend build and lint; fix any issues. (Lint runs with two React effect advisory warnings; build was blocked by Desktop write permissions.)
- [ ] B12.8 Verify the frontend against a running Flask backend, including registration, login, PDF analysis, history, results, and logout.

## Integration notes

- Start Flask on port 5000 and Vite on port 5173 during development.
- Flask session cookies are sent with `credentials: 'include'`; no token is stored in browser local storage.
- Login, registration, upload, and logout send the CSRF token obtained from `/api/csrf`.
- No Flask backend files or data stores are modified by this frontend work.
