# Backend Architecture — Drive 2 Retail

Complete specification for the D2R wholesale platform backend, derived from an audit
of this repository, the client PRD and the company pitch deck.

## Read in this order

| # | Doc | What it answers |
| --- | --- | --- |
| 0 | [00-overview.md](00-overview.md) | What the frontend is today, which stack to build on, and why |
| 1 | [01-data-model.md](01-data-model.md) | Every table, column, index and constraint |
| 2 | [02-api.md](02-api.md) | Every endpoint, payload, error code and rate limit |
| 3 | [03-flows.md](03-flows.md) | Checkout, payment, stock, refunds — the parts that must not break |
| 4 | [04-security.md](04-security.md) | Auth, the RBAC matrix, OWASP, secrets, retention |
| 5 | [05-performance.md](05-performance.md) | Budgets, caching, indexes, load tests |
| 6 | [06-admin-ops.md](06-admin-ops.md) | The admin and inventory dashboards |
| 7 | [07-delivery-plan.md](07-delivery-plan.md) | Milestones, testing, handover, cost drivers |
| 8 | [08-dispatch-delivery.md](08-dispatch-delivery.md) | Fleet, routes, trips, proof of delivery, cash on delivery |
| 9 | [09-procurement-batches.md](09-procurement-batches.md) | Purchase orders, goods receipt, batch/expiry tracking, FEFO |
| — | [schema.sql](schema.sql) | Executable Postgres DDL, 67 tables |

## The short version

**Stack:** Django 5 + DRF + PostgreSQL 16 + Redis + Celery.

The deciding factor is that **D2R manages the catalogue on its vendors' behalf** —
this is an internal-tools product with a shop attached. Django Admin delivers the
entire PRD §9 back-office surface on day one; in Node that is 6–10 extra weeks of
work that no customer ever sees. The second factor is correctness around money and
stock, where Django's transaction and constraint tooling is the most mature option.

NestJS + Prisma is the credible runner-up **if the team is TypeScript-only** — take
it only with the admin-portal budget explicitly allowed for.

**Frontend today:** 62 routes, fully static, zero data layer. The shell is complete
and brand-correct; every dynamic surface is still to build.

**Biggest structural finding:** the template is marketplace-shaped (vendor logins,
multi-vendor carts, vendor dashboards). D2R is a single seller with suppliers. That
removes ~30% of a marketplace build and moves the weight into admin and inventory
tooling.

## The three things that must be right

1. **Stock reservation** — hold at payment initiation, 20-minute TTL, never at
   add-to-cart. Enforced with `SELECT … FOR UPDATE` in a fixed lock order and a
   `check (quantity_reserved <= quantity_on_hand)` constraint as the last line of
   defence. → `03-flows.md` §4
2. **Payment idempotency** — `unique (provider, event_id)` on the webhook ledger;
   insert first, process second. Always re-verify against the provider API; never
   trust a redirect or a payload amount. → `03-flows.md` §5
3. **Order snapshots** — every order line copies SKU, names, unit, price and tax.
   Renaming a product must never rewrite history. → `01-data-model.md` §6

## Decisions blocking the build

From PRD §17. The first three cannot be changed once real orders exist:

1. Currency, and whether displayed prices include VAT
2. Invoice numbering format and required tax fields
3. Alcohol/restricted-product rules for Lagos
4. Selling units and MOQ rules per category
5. Payment gateway: Paystack, Flutterwave or both
6. Whether accounts need approval before seeing prices
7. Delivery zones, fees and any free-delivery threshold
8. **Is cash on delivery offered?** — changes the payment model and finance workflow
   and cannot be retrofitted cleanly (`08-dispatch-delivery.md` §11)

Full list with impact and cost-if-late in `07-delivery-plan.md` §1.


## Known gaps

Fixed since the first draft:

- **Dispatch and fleet** — `08-dispatch-delivery.md`
- **Procurement and batch/expiry tracking** — `09-procurement-batches.md`

Still to specify before build starts. None blocks the architecture; each is a
half-day to a day of writing:

| Gap | Why it matters | When |
| --- | --- | --- |
| **Notification catalogue** | `notification.template_code` exists but nothing lists which emails/SMS fire on which event, with what content. ~25 templates. | Before M4 |
| **NDPR compliance** | `04-security.md` §7 is written generically. Nigeria's NDPR is the applicable law — it has its own consent, DPO and breach-notification requirements. | Before launch |
| **CI/CD pipeline** | Test/build/migrate/deploy stages, migration safety checks, rollback procedure. | M0 |
| **Timezone policy** | Store UTC, present `Africa/Lagos`. Route cut-off times and "delivered today" reports are timezone-sensitive. | M0 |
| **DR runbook** | RTO/RPO are stated; the actual step-by-step recovery procedure is not written. | Before launch |
| **Barcode/scanner workflow** | Assumed manual keying at goods receipt and picking. If the warehouse has scanners the flows change. | Depends on Q25 |

Deliberately out of scope, per PRD §19: loyalty, referrals, gift cards,
subscriptions, multi-currency, ERP integration, native apps.
