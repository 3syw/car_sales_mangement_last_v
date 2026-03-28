# Car Sales Desktop Client

Status: On hold during the current web-only deployment phase.

Electron desktop shell for the Django multi-tenant backend (kept for a later roadmap phase).

## Features

- Tenant-aware JWT login against `/api/auth/token/`
- Dashboard fed from `/api/reports/summary/`, `/api/cars/`, `/api/sales/`, `/api/finance-vouchers/`, `/api/debt-payments/`
- Live websocket updates from `/ws/tenants/<tenant_id>/events/`
- Local session restore inside the desktop app

## Current policy

- This desktop client is not part of the active production deployment.
- Current production target is web-only (Django web + API).
- Desktop build and publish steps are intentionally disabled for now.

## Run locally

Run commands are intentionally disabled in this phase.
When the desktop roadmap is resumed, these commands can be re-enabled.

Default backend URL for local use:

- `http://127.0.0.1:8000`

The tenant access key, tenant id, username, and password must match a real tenant user in the Django backend.
