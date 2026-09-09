# Delivery Plan

---

## 1. Blockers — decisions needed before development starts

PRD §17 lists these as open. Each one below either blocks a milestone or forces
rework if answered late. Ranked by how much they cost if deferred.

| # | Decision | Blocks | Cost if late |
| --- | --- | --- | --- |
| 1 | Payment gateway: Paystack, Flutterwave, or both | M4 | Low — adapter interface absorbs it |
| 2 | Currency, and whether prices include VAT | M2 | **High** — changes every price calculation and stored total |
| 3 | Do accounts need approval before seeing prices? | M1 | Medium — it is a setting, but the UX differs |
| 4 | Selling units and MOQ rules per category | M2 | **High** — shapes the variant model in practice |
| 5 | Inventory reservation policy | M3 | Medium — §3 of `03-flows.md` proposes one; confirm it |
| 6 | Delivery zones, fees, free-delivery threshold | M5 | Medium — data, not code |
| 7 | Invoice numbering format and required tax fields | M4 | **High** — invoices are legally immutable once issued |
| 8 | Alcohol/restricted rules for Lagos | M5 | **High** — compliance, cannot be retrofitted |
| 9 | Email/SMS/WhatsApp provider | M4 | Low |
| 10 | Launch catalogue size and staff headcount | M0 | Low — sizing only |
| 11 | Hosting, domain, DNS ownership | M0 | Medium — must be in D2R's name, not the agency's |

**#2, #7 and #8 should be settled first.** They are the three that cannot be changed
after real orders exist.

---

## 2. Milestones

Sequenced so each one ends with something demonstrable. 16–20 weeks to launch with
2 backend + 1 frontend engineer.

### M0 — Foundation · 1 week
Repo, Docker Compose (Postgres, Redis, Django, Celery), CI (lint, type-check, test,
migration check), staging environment, Sentry, base models, `audit_log`,
`idempotency_key`, error envelope, health check.
**Exit:** CI green, staging reachable, `/health` returns 200.

### M1 — Identity · 2 weeks
Custom user, business accounts, members, addresses, staff roles, the full permission
matrix, JWT + refresh rotation, staff MFA, registration/verification/approval flow,
Next.js BFF session handling, real `/login` `/register` `/reset-password` routes.
**Exit:** a customer registers, verifies, is approved by staff, and logs in. Every
role's permissions have passing negative tests.

### M2 — Catalogue · 3 weeks
Categories, brands, vendors, products, variants, images, attributes, tax classes,
prices with group and volume breaks. Listing, search, facets, PDP, suggest. Django
Admin fully configured. CSV import (dry-run + apply).
**Exit:** 500 real SKUs imported; the storefront catalogue renders from the API;
`assertNumQueries` budgets hold.

### M3 — Cart & inventory · 2 weeks
Warehouse, inventory items, movements, adjustments, reservations. Cart with full
MOQ/increment/availability validation. Delivery zones and fee calculation.
**Exit:** the concurrent-checkout load test passes — 100 users, 10 units, exactly
10 succeed.

### M4 — Checkout & payments · 3 weeks
Order model and state machine, checkout transaction, Paystack adapter, webhooks with
idempotency, server-side verification, invoices with gapless numbering and PDFs,
refunds with two-person approval, reconciliation view, order confirmation emails.
**Exit:** end-to-end paid order in the provider's test environment. Duplicate and
forged webhooks both handled correctly. Amount-mismatch is flagged, not paid.

### M5 — Fulfilment & admin · 3 weeks
Shipments, partial dispatch, fulfilment board, dashboard, inventory console, customer
management, promotions, restricted-product controls, reports, settings.
**Exit:** ops processes a day of orders from paid to delivered without a developer.

### M6 — Storefront integration · 2 weeks
Wire the remaining Next.js pages, collapse the 26 duplicate layout routes to
parameterised templates, add the missing routes (`/search`, `/c/`, `/b/`, `/p/`,
order detail, invoice, payment result), quick-order pad, reorder, wishlist.
**Exit:** no hard-coded product data anywhere in `src/`.

### M7 — Hardening · 2 weeks
Load tests, penetration test, restore drill, accessibility audit, SEO (sitemap,
structured data), monitoring and alerting, runbooks, documentation, staff training.
**Exit:** the pre-launch checklist in `04-security.md` §9 is fully ticked.

### M8 — Launch · 1 week
Production environment, DNS, TLS, live payment keys, catalogue and customer data
migration, pilot with a small group of retailers, then open.

---

## 3. Environments

| | Local | Staging | Production |
| --- | --- | --- | --- |
| Data | Seeded fixtures | Anonymised copy | Live |
| Payments | Provider test keys | Provider test keys | Live keys |
| Email | MailHog | Real, to an internal domain | Real |
| Debug | On | **Off** | **Off** |
| Backups | — | Weekly | Nightly + PITR |
| Access | Developer | Team | Break-glass, audited |

Staging must mirror production in shape and scale. A staging database with 50
products will not reveal the query that takes 4 seconds against 20,000.

---

## 4. Testing

| Layer | Coverage target | Tooling |
| --- | --- | --- |
| Unit — services, pricing, tax, state machine | **95%** | pytest |
| Integration — API contracts | 85% | pytest + DRF test client |
| Concurrency — checkout, reservations, webhooks | Every path | pytest + threads |
| Contract — OpenAPI vs client | 100% | schemathesis |
| E2E — register → browse → order → pay → fulfil | Critical paths | Playwright |
| Load | Per `05-performance.md` §7 | k6 |
| Security | Every OWASP category | ZAP + manual |

**Non-negotiable tests.** These exist because each one corresponds to a way this
class of system loses money:

1. Two concurrent checkouts on the last unit — exactly one succeeds.
2. Duplicate webhook delivery — no double fulfilment, no double stock deduction.
3. Payment verified for the wrong amount — order is **not** marked paid.
4. Expired reservation — stock is released, order expires.
5. Price changes mid-checkout — `409`, and the old price is never charged.
6. Account A cannot read account B's order, invoice or address.
7. Refund requester cannot approve their own refund.
8. MOQ and order-increment violations rejected server-side even when the client sends
   a valid-looking payload.

CI runs 1–8 on every commit. They are the regression suite for the parts that matter.

---

## 5. Handover (PRD §18)

- Source in a **D2R-owned** repository, with the agency as a collaborator.
- All production credentials issued in D2R's name — domain, hosting, payment,
  email, S3. This is the single most commonly botched part of an agency engagement.
- Documentation: local setup, environment variables, migrations, payment and webhook
  flow, deployment, backup/restore, runbooks for the alerts in
  `04-security.md` §8.
- Admin manual with screenshots, plus a recorded walkthrough.
- Two training sessions: catalogue/inventory staff, and ops/finance staff.
- Agreed support period and defect-warranty terms in the contract.

---

## 6. Phase 2 — already modelled, deliberately not built

The schema accommodates these without migration. Each is a feature flag or a data
change, not a redesign.

| Feature | What already exists |
| --- | --- |
| Volume / group pricing | `customer_group`, `price.customer_group_id`, `price.min_quantity` |
| Saved order lists | `saved_list` shape defined |
| Sales rep portal | `business_account.assigned_rep_id`, `order.source='rep'` |
| Credit terms | `credit_limit`, `payment_terms_days`, `invoice.due_date` |
| Multi-warehouse | `warehouse` table, `inventory_item` keyed by warehouse, `priority` |
| Courier integration | `shipment.carrier`, `tracking_reference` |
| SMS/WhatsApp | `notification.channel` |
| Public API | Same DRF layer, scoped tokens |

---

## 7. Cost drivers

Not a quote — the variables that move the number.

**Infrastructure, monthly:** managed Postgres (~$50–150), Redis (~$15–40), app
hosting (~$40–120), object storage + CDN (~$10–50), email (~$10–30), Sentry
(~$26), search when introduced (~$30). Roughly **$180–450/month** at launch scale.

**Transaction costs:** Paystack ~1.5% + ₦100, capped ₦2,000 locally. On ₦50m monthly
GMV that is meaningful — worth negotiating a rate before launch.

**Build effort:** ~16–20 weeks with 2 backend + 1 frontend. Choosing NestJS over
Django adds 6–10 weeks for the admin portal (`00-overview.md` §2.4).

The largest non-obvious cost is **catalogue data entry**. 2,000 SKUs with images,
specs, units and pricing is weeks of work by someone who knows the products. Budget
for it explicitly; it is the usual reason a technically-finished platform sits
unlaunched.
