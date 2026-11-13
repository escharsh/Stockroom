# Stockroom — Warehouse Operations Platform

A Flask web application for inventory, procurement, fulfillment and demand planning. It extends [inventory-management-flask](https://github.com/Rumaisas-islam/inventory-management-flask), upstream commit `41a87483be4e69c9cd797f51dd07604c0149592a`. The original MIT license is retained in LICENSE. Reused components include the User and Item models, password helpers and Flask extension setup. Warehouse workflows, business services, role checks, audit storage, forecasting and the current interface are extensions in this version.

## Run locally

Python 3.11+ is required. On Windows, extract the ZIP and double-click **START.bat**. The launcher installs pinned dependencies, initializes the sample scenario once and starts the application using the Waitress WSGI server at http://127.0.0.1:5000 . Keep the terminal open. Ctrl+C stops the server. Existing stock and orders are preserved on subsequent launches.

Manual setup:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe seed_demo.py
.venv\Scripts\python.exe seed_workflows.py
.venv\Scripts\python.exe serve.py
```

## Sample access

| Username | Password | Role |
| --- | --- | --- |
| admin | College@123 | Administrator |
| ops.manager | Stockroom@2026 | Operations manager |
| warehouse.ops | Stockroom@2026 | Warehouse operator |
| warehouse.viewer | Stockroom@2026 | Viewer |

These accounts and all initialized suppliers/customers are synthetic sample data. No emails are sent and no real orders are placed. Passwords are hashed in the database. Sample credentials are intentionally public; do not expose this initialized workspace to the internet.

## Interface

The workspace uses a light sidebar, green operational accents, compact tables and card panels inspired by the supplied interface references. The dashboard charts cumulative inventory flow and shows real per-location balances. New purchase and customer orders use a three-step form (details, products, review) with a live value summary. Page navigation search, order search/status filters and sidebar collapse are functional.

Animations cover card entry, chart drawing, stock-share bars, hover states and form-step transitions. The interface honors `prefers-reduced-motion`. No external fonts, image assets or animation libraries are required. The UI theme is implemented in `static/horizon.css`, `static/horizon.js` and the `icons.html` SVG macro library; it does not change stock transaction rules.

## Operational workflows

- **Procurement:** multi-product draft → approval → partial receipts → fully received. Outstanding quantities remain open. Over-receipts are rejected. Unreceived drafts/approved orders can be cancelled; partially received orders cannot be cancelled in this version.
- **Fulfillment:** multi-product draft → reserve all lines → ship. A failed allocation leaves every line unreserved. Cancellation releases reservations. Physical stock changes at shipment, not reservation.
- **Stock control:** manual receipts, dispatches and transfers; reserved stock cannot be spent by an unrelated movement. Inventory shows on-hand, reserved and available units separately.
- **Configuration:** create warehouse locations and supplier records; set per-product minimum, maximum and replenishment lead time. Defaults are 20 / 200 units and seven days. Supplier lead time is reference metadata; product policy lead time controls forecasting.
- **Permissions:** administrators manage team access; managers create/approve orders and configure the workspace; operators receive approved purchases, ship reserved orders and record manual movements; viewers can read operational pages and export reports. Audit access is limited to managers and administrators.
- **Audit:** actor, action, reference, details and UTC time recorded with successful application transactions. Audit records have no edit/delete route. They are not cryptographically tamper-proof.
- **Retry handling:** enterprise workflow commands carry unique request keys. Replaying a completed form does not create a second receipt, shipment or order. Order-state checks also reject duplicate shipments with different keys. Manual movement forms do not yet have replay protection.
- **Reporting:** stock and movement CSV exports scoped to the active workspace. Stock reports include on-hand, reserved and available quantities. ABC classification groups products by cumulative inventory value (first 80%, next 15%, remainder).

## Demand intelligence

The local model aggregates up to 30 calendar days of outbound movements, including zero-demand days. With at least 14 days, seven rolling one-day backtests compare linear regression against a seven-day moving-average baseline; the lowest MAE selects the model. Each validation prediction uses only earlier days. With 7–13 days, regression remains provisional; fewer than seven days produces no forecast.

Planning uses:

```text
available = on hand - reserved
inventory position = available + approved outstanding purchase quantities
reorder target = predicted demand over product lead time + daily standard deviation * sqrt(lead time)
suggested order = max(0, ceil(reorder target) - inventory position)
```

Days of cover uses available stock. Forecast evidence shows recent actuals, seven daily predictions, selected model, MAE and baseline MAE. “Plan purchase” prefills a product and suggested quantity in the procurement form; a manager still chooses supplier, warehouse, date and approval.

Backtest scores are model-selection validation, not an independent test result or a guarantee of business accuracy. Seeded movements are synthetic and deliberately reconciled; sample metrics do not establish real-world predictive accuracy. Current UTC-day totals may be incomplete. The model does not distinguish lost demand from zero demand, model seasonality, or adjust incoming inventory for late arrivals. Order unit values are snapshots of catalogue prices, stored in integer paise; stock catalogue prices retain the upstream floating-point representation.

## Source map

| File | Responsibility |
| --- | --- |
| app.py | App factory, authentication, dashboard, inventory and CSV routes |
| models.py / extensions.py | Upstream-derived core models and extension setup; stock and movement records |
| enterprise_models.py | Workspace membership, warehouses, suppliers, policies, orders, order lines and audit tables |
| enterprise.py | Authorized workspace commands, replay handling, configuration and order screens |
| services.py | Reservation, receipt and shipment business rules |
| forecast.py | Forecast models and rolling-origin validation |
| templates / static | Shared workspace layout, workflow forms and responsive interface |
| seed_demo.py / seed_workflows.py | Idempotent synthetic scenario initialization |
| serve.py | Waitress entry point |
| test_warehouse.py / test_enterprise.py | Automated regression and workflow checks |

The development checkout retains legacy upstream reference modules; the distributable ZIP includes only active application files.

## Storage and upgrades

SQLite lives at `instance/warehouse.db`. This upgrade adds tables without replacing existing products, balances or movements. It is compatible with the previous Stockroom schema; it does not import arbitrary upstream databases. Existing locations are retained as historical labels. A local session signing secret is generated once in `instance/.session-key`; `SECRET_KEY` overrides it. Back up the database and signing key together. The ZIP excludes databases and secret files; run the seed scripts to create a fresh workspace.

## Verification

```powershell
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest test_warehouse.py test_enterprise.py -q
```

22 checks pass, covering stock conservation, invalid quantities, authentication and CSRF, workspace isolation, partial receiving, over-receipt rejection, rollback across multiple lines, replayed receipts, reservation cancellation, reserved-stock protection, shipment-once semantics, role permissions, configuration, model validation and two concurrent reservations competing for the same stock. Foreign key enforcement is enabled for SQLite connections.

## Deployment boundary

This is a locally runnable, production-style foundation, not a completed production deployment. Waitress replaces the development server in the launcher. Still required for public use: HTTPS/reverse-proxy configuration, deployment secrets and hardened cookies, login rate limiting, account disable/reset flows, database migrations, backups/restore drills, monitoring and load testing. SQLite serializes writes; large deployments need database/concurrency design beyond this local implementation. The interface does not yet include returns, barcode hardware integration, multi-currency accounting, invoice generation or product retirement. Order lists and stock history need pagination before large datasets.

`STOCKROOM_HOST` and `STOCKROOM_PORT` configure the WSGI listener; default host is loopback. No external AI API, paid service or internet access is needed after dependency installation.
