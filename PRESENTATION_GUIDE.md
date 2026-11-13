# Technical walkthrough and viva guide

## Suggested title
Stockroom: Transactional Warehouse Operations with Demand Intelligence

## Seven-minute live demonstration

1. Open Overview. Explain physical stock, reserved units, open purchases and overdue orders.
2. Open Procurement. Show a multi-product order with an Approved status and another with Partially received quantities. Enter a partial receipt, show its outstanding balance, inventory update and PO-linked stock ledger entries.
3. Attempt to receive more than outstanding; the server rejects it and posts nothing.
4. Open Order fulfillment. Show a Reserved order: on-hand stock is unchanged but available stock is reduced. Confirm shipment; physical stock decreases once. Explain that resubmitting the request cannot ship twice.
5. Create a sales draft requiring more stock than available. Try Reserve: all lines remain in Draft, with no partial allocation.
6. Open Demand intelligence. Expand Forecast & model evidence. Explain seven rolling-origin validation folds, selected model, MAE versus baseline, current reservations and approved incoming stock. Use Plan purchase to prefill a purchase draft.
7. Open Audit trail to show actor/reference/state changes. Sign in as warehouse.ops to demonstrate receiving/shipping access without purchase approval. A viewer cannot submit stock changes.

## Sample role accounts
Admin: admin / College@123. Manager: ops.manager / Stockroom@2026. Operator: warehouse.ops / Stockroom@2026. Viewer: warehouse.viewer / Stockroom@2026. These are local synthetic scenario accounts, not real organization credentials.

## Questions you should be ready to answer

- **Why is this more than CRUD?** Order state transitions enforce business rules. Reservation, multi-line rollback, partial receiving, replay protection and role checks coordinate changes across several entities.
- **What prevents overselling?** Available stock subtracts active reservations. A conditional database write and SQLite writer transaction serialize competing allocation operations. A test proves two orders cannot both reserve six out of ten units.
- **What if receiving fails halfway?** Receipt quantities, physical balances, movements, order status and audit record share one transaction. A failure on the second line rolls back the first.
- **What is idempotency?** A submitted form carries a unique key stored with the audit event. Replaying the same successful key returns without applying the effect again. Different keys still must satisfy state checks. Manual stock forms are not yet protected against replay.
- **What is the difference between on hand and available?** On hand is physically present; available subtracts stock promised to reserved customer orders.
- **How does the AI work?** Local linear regression competes against a seven-day moving average on rolling daily validation. The selected model estimates future dispatch demand. A separate planning formula subtracts reservations and adds outstanding approved purchases.
- **What does MAE mean?** Average absolute error in units per day. Lower is better. These scores are validation used for model selection, not independent accuracy guarantees.
- **Does a high forecast place an order automatically?** No. The recommendation prefills a draft; a manager chooses supplier, warehouse, due date and approval.
- **Why integer paise in orders?** Order totals need stable snapshots and exact whole subunits. Catalogue float prices are retained for compatibility and converted when the order is created.
- **Why preserve the original license?** The application adapts an MIT-licensed project. Credit the base and explain the warehouse-specific extensions honestly.
- **Is it fully production-ready?** It has production-style workflows and a WSGI launcher. Public deployment still needs HTTPS, hardened session settings, rate limiting, account lifecycle, backups, migrations, monitoring and broader operational testing.

## Evidence to include in a report

Use ARCHITECTURE.md for ER and state diagrams. Include screenshots of partial receiving, reserved vs available stock, audit events and model comparison. Run the 22 automated checks and explain the important assertions rather than claiming that passing tests proves complete correctness. State clearly that the seeded supplier/customer and movement data are synthetic.

Add your real name, organization, mentor and actual implementation dates. Do not invent internship work or claim authorship of the upstream base.
