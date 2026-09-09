# Drive 2 Retail — Backend Architecture

**Status:** proposed · **Version:** 1.0 · **Audience:** developers, ops, D2R stakeholders

This document set specifies the backend for the Drive 2 Retail wholesale platform:
the stack decision, data model, API, critical flows, security, performance and the
admin/ops surface.

| Doc | Contents |
| --- | --- |
| `00-overview.md` | Frontend audit, stack decision, system architecture |
| `01-data-model.md` | Every table, column, index and constraint |
| `02-api.md` | Endpoints, request/response contracts, errors, pagination |
| `03-flows.md` | Checkout, payment, stock, fulfilment, reorder — step by step |
| `04-security.md` | AuthN/AuthZ, RBAC matrix, OWASP, secrets, PII |
| `05-performance.md` | Caching, indexing, search, budgets |
| `06-admin-ops.md` | The admin and inventory dashboards |
| `07-delivery-plan.md` | Milestones, environments, handover |
| `08-dispatch-delivery.md` | Fleet, routes, trips, proof of delivery, cash on delivery |
| `09-procurement-batches.md` | Purchase orders, goods receipt, batch/expiry, FEFO |
| `schema.sql` | Executable Postgres DDL |

---

## 1. Frontend audit

### 1.1 What exists today

62 routes, all statically prerendered, **with no data layer of any kind**. There is
no `fetch`, no API client, no server actions, no database. Every product, price,
order and customer on screen is hard-coded markup ported from the Sellzy template.

```
src/lib/  →  company.ts, faqs.ts, navigation.ts, ui-store.tsx
             (content + UI state only — zero data access)
```

That is the correct starting point — the UI shell is complete and brand-correct —
but every dynamic surface has to be built.

### 1.2 The route inventory, classified

| Class | Count | Routes | Disposition |
| --- | --- | --- | --- |
| **Keep, wire to API** | 12 | `/`, `/product-details`, `/cart-single-vendor`, `/checkout`, `/order-successful`, `/my-account`, `/wishlist-style-v1`, `/compare`, `/shop-left-sidebar-4col`, `/vendor-dashboard`, `/vendor-account`, `/vendors-grid` | Become the real storefront |
| **Content, done** | 8 | `/about`, `/contact`, `/faq`, `/terms`, `/privacy`, `/returns`, `/delivery`, `/restricted-products` | Static, already D2R content |
| **Layout duplicates** | 26 | 14 × `banner-*`/`full-banner-*`/`top-banner-*`, 3 × `shop-left-sidebar-*`, 5 × `product-details-*`, 4 × homepage variants | Collapse to one catalogue template + one PDP |
| **Marketplace-shaped** | 6 | `/vendors-*`, `/vendor-left-*-marketplace`, `/cart-multi-vendor` | **Reframe** — see 1.4 |
| **Template demo** | 5 | `/404`, `/coming-soon`, `/blog-*` | Drop or repurpose |
| **Variants** | 5 | `/checkout-v2`, `/wishlist-style-v2`, `/index-2..5` | Pick one, delete the rest |

Collapsing the 26 layout duplicates into parameterised routes is the single biggest
maintenance win available. They differ only in column count and filter position —
both of which are props, not pages.

### 1.3 Routes the PRD requires that do not exist

| Missing route | Why it is needed |
| --- | --- |
| `/search` | PRD FR-05 — search by name, SKU, brand, keyword |
| `/c/[...slug]` | Category and subcategory browsing |
| `/b/[brand]` | Brand pages |
| `/p/[slug]` | Real product URLs (today: one hard-coded PDP) |
| `/account/orders/[id]` | Order detail is a tab, not a linkable page |
| `/account/invoices/[id]` | PRD OPS-06 — printable invoice |
| `/checkout/payment/[reference]` | PRD PAY-07 — success / failure / pending result screens |
| `/login`, `/register`, `/reset-password/[token]` | Auth is trapped in slide-over panels. Password-reset and verification emails must deep-link to real URLs |
| `/admin/**` | The entire admin portal |

**The auth panels are the most urgent gap.** A reset-password email cannot open a
slide-over. Those flows need real routes; the panels can stay as a convenience
entry point that links to them.

### 1.4 The template is multi-vendor; D2R is not

The template models a **marketplace** — sellers with their own storefronts,
dashboards and self-service catalogues. D2R's model is the opposite:

> D2R buys from manufacturers/importers and re-distributes. **D2R manages the
> catalogue on the vendors' behalf.** Vendors never log in.

That single constraint changes the architecture significantly:

- `Vendor` is a **supplier/brand-owner record**, not a user account. No vendor auth,
  no vendor portal, no vendor payouts, no commission engine, no vendor onboarding.
- `/vendor-dashboard` becomes the **D2R staff dashboard**.
- `/vendors-grid` becomes a **"Brands we carry"** marketing page.
- `/cart-multi-vendor` is meaningless — there is one seller. Delete it.
- Stock is D2R's own inventory in D2R's own warehouse. There is no split-shipment,
  no per-vendor fulfilment, no marketplace settlement ledger.

This removes perhaps 30% of the complexity of a true marketplace build — and moves
that weight into the **admin and inventory tooling**, which becomes the core product.

### 1.5 B2B concepts absent from the UI

The frontend is a B2C shop. Wholesale needs:

- Selling unit on every product card (unit / pack / case) and units-per-case
- Minimum order quantity and order-increment enforcement, with inline validation
- Business account context — company name, approval state, assigned rep
- "Prices visible after approval" gating
- Quick-order / pad entry (PRD FR-06) — add by SKU and quantity without opening PDPs
- Reorder from order history
- Restricted-product badges and checkout acknowledgements

### 1.6 Fields the UI already collects

Extracted from the built markup — these drive the write API:

```
register      first-name, last-name, email, password, confirm-password
login         email, password
reset         password, confirm-password  (+ token from email link)
checkout      first_name, last_name, user_name, email_address, phone_number,
              city, state, zip_code, address_comment, address-type,
              shipping-method, payment-method
account       + new_password, confirm_new_password, shipping_* address set
contact       business name, contact name, email, phone, enquiry-type, message
catalogue     search, sorting, category, price range, rating, colour, size,
              discount, brand, pack size
```

`register` collects a personal name but **no business name** — the PRD's FR-01 makes
business name, business type and optional tax ID mandatory. The register panel needs
extending.

### 1.7 Catalogue filter facets already in the UI

`Category · Price Range · Rating · Colour · Size · Discount · Brand · Pack Size`

Sort: `popularity · price asc · price desc · average rating · A-Z · Z-A`

These define the required facet/aggregation surface on the search endpoint.

### 1.8 Order status vocabulary in the UI

`Processing · Delivering · Completed · Cancelled · Delivered · Out of Stock`

The PRD (OPS-05) specifies `Pending Payment · Paid · Processing · Dispatched ·
Delivered · Cancelled`. **These must be reconciled** — the backend is authoritative;
the UI labels map onto it (see `01-data-model.md` §Orders).

---

## 2. Stack decision

### 2.1 Recommendation

> **Django 5 + Django REST Framework + PostgreSQL 16 + Redis + Celery.**

### 2.2 Why — the decisive argument

The requirement that settles this is section 1.4: **D2R operates the catalogue on
behalf of its vendors.** Staff will spend all day in the back office; customers
spend minutes in the storefront. This is an internal-tools product with a shop
attached, not a shop with an admin page.

Django ships a production-grade, permission-aware, audit-friendly admin out of the
box. On day one you get catalogue CRUD, inventory adjustment, order management,
customer approval, staff roles and change history — the exact surface described in
PRD §9 — with search, filtering, bulk actions and CSV export. In Node you build all
of that yourself, and it is months of work that delivers no customer-visible value.

The second decisive factor is **correctness around money and stock**. The riskiest
requirements in the PRD are PAY-04/05 (server-side verification, idempotent
webhooks) and OPS-01/02 (never oversell, consistent reservation policy). Django's
ORM gives mature `select_for_update`, savepoints, `constraints=[CheckConstraint,
UniqueConstraint]` and a migration system that has been correct for fifteen years.
Getting these wrong costs real money; getting them right is easier here.

### 2.3 Honest comparison

| | Django + DRF | NestJS + Prisma | Laravel + Filament | Express + raw |
| --- | --- | --- | --- | --- |
| Admin out of the box | **Excellent** — Django Admin | None — build it | **Excellent** — Filament/Nova | None |
| Transactional integrity | Excellent | Good (Prisma tx) | Excellent | Manual |
| Migrations | Excellent | Good | Excellent | Manual |
| RBAC / permissions | Built-in + guardian | Build it | Built-in (Spatie) | Build it |
| Shared types with Next.js | No (OpenAPI codegen) | **Yes** | No | Yes |
| Paystack/Flutterwave SDKs | Community, solid | Community, solid | **First-class** | Solid |
| Background jobs | Celery (mature) | BullMQ (good) | Horizon (excellent) | Manual |
| Bulk CSV/XLSX import | pandas/openpyxl | Fine | Fine | Fine |
| Talent pool in Lagos | Deep | Growing | **Deepest** | Deep |
| Raw request throughput | Adequate | Higher | Adequate | Highest |

**Throughput is a non-issue.** Catalogue reads are cached and CDN-fronted; writes are
order-rate, not tweet-rate. At D2R's stated coverage — 500 KAM + 2,500 VAN + 60
wholesale outlets — peak load is a few hundred concurrent users. Django with
gunicorn handles that on modest hardware. Choosing Node for speed here optimises the
one dimension that is not constrained.

### 2.4 The runner-up, and when to pick it

**NestJS + Prisma + PostgreSQL** is a legitimate second choice, and the right one
if — and only if — the team is TypeScript-only. You get one language across the
stack and generated types shared with Next.js, which genuinely reduces contract bugs.

The cost is explicit: budget **6–10 additional weeks** to build the admin portal
(Refine or react-admin over the same API), plus your own RBAC, audit trail and
import tooling. If that budget exists and the team is stronger in TS, take it. If
it does not, Django is the lower-risk path to the same launch date.

**Laravel + Filament** is a close third and would be the pick if the team is
PHP-first: Filament is as strong as Django Admin, and Paystack/Flutterwave support
in PHP is the most mature of any ecosystem.

**Plain Express is not recommended.** Nothing about this system benefits from an
unopinionated framework; the permission, transaction and audit requirements all
want structure.

### 2.5 Supporting choices

| Concern | Choice | Rationale |
| --- | --- | --- |
| Database | PostgreSQL 16 | Transactions, partial/GIN indexes, `numeric` money, JSONB for specs, row locking |
| Cache / broker / locks | Redis 7 | Session cache, rate limits, Celery broker, stock-reservation TTLs |
| Async jobs | Celery + beat | Webhooks, email, imports, reports, reservation expiry |
| Object storage | S3-compatible (Cloudflare R2 / AWS S3) | Product images, invoice PDFs, import files |
| Search | Postgres FTS at launch → Meilisearch when catalogue > ~20k SKUs | Avoid a second datastore until the catalogue justifies it |
| Images | Next/Image + CDN, originals in S3 | Already wired in the frontend |
| Email | Transactional provider (Resend / SES / Postmark) | Order, invoice, auth mail |
| Payments | Paystack primary, Flutterwave behind the same interface | PRD PAY-01 wants it configurable |
| PDF invoices | WeasyPrint | Server-side, deterministic, no headless browser |
| Errors / APM | Sentry + structured JSON logs | PRD §12 |
| Deploy | Docker Compose → managed Postgres/Redis | Staging + production parity |

### 2.6 Money is never a float

All monetary values are `numeric(14,2)` in Postgres and `Decimal` in Python,
**stored in kobo-safe minor units where the provider requires it** (Paystack
transacts in kobo). One conversion boundary, in the payment gateway adapter, and
nowhere else. There is no `float` anywhere in the money path.

---

## 3. System architecture

```
                            ┌──────────────────┐
   Browser ────────────────▶│  Next.js 15      │
                            │  storefront      │
                            │  (SSR/ISR + BFF) │
                            └────────┬─────────┘
                                     │ HTTPS, httpOnly session cookie
                                     │ (BFF holds the token; browser never sees it)
                                     ▼
   D2R staff ──────────────▶┌──────────────────┐
   (Django Admin)           │  Django + DRF    │◀──── webhooks ──── Paystack
                            │  API + Admin     │                    Flutterwave
                            └───┬───┬───┬──────┘
                                │   │   │
             ┌──────────────────┘   │   └──────────────────┐
             ▼                      ▼                      ▼
      ┌─────────────┐       ┌──────────────┐       ┌──────────────┐
      │ PostgreSQL  │       │    Redis     │       │  Celery      │
      │ (primary)   │       │ cache/locks  │       │  workers     │
      └─────────────┘       │ broker       │       │  + beat      │
                            └──────────────┘       └──────┬───────┘
                                                          ▼
                                            S3 · email · SMS/WhatsApp
```

### 3.1 Why a BFF layer in Next.js

The storefront talks to Django through Next.js route handlers (`/api/*`) rather than
calling DRF directly from the browser. This buys three things:

1. **Tokens never reach JavaScript.** The session lives in an `httpOnly`, `Secure`,
   `SameSite=Lax` cookie owned by the Next server. XSS cannot exfiltrate it.
2. **Server components can fetch with the user's identity** without shipping an API
   client to the client bundle.
3. **One origin.** No CORS, no preflight latency, no third-party cookie problems.

Public catalogue reads bypass the BFF and hit DRF directly from the Next server at
build/revalidate time, cached at the edge.

### 3.2 Service boundaries inside the Django project

A modular monolith. Not microservices — at this scale they would add operational
cost and distributed-transaction risk for no benefit.

```
d2r/
├── accounts/      users, business accounts, addresses, staff roles
├── catalogue/     categories, brands, vendors, products, variants, media, attributes
├── pricing/       price lists, tiers, tax classes, promotions
├── inventory/     warehouses, stock, reservations, movements, adjustments
├── carts/         carts, cart items, validation rules
├── orders/        orders, items, status machine, invoices, reorder
├── payments/      gateway adapters, payment attempts, webhooks, refunds, reconciliation
├── delivery/      zones, rates, shipments, tracking
├── content/       reviews, wishlists, CMS blocks, notifications
├── procurement/   purchase orders, goods receipt, supplier invoices
├── ops/           audit log, imports/exports, reporting
└── core/          base models, permissions, pagination, errors, idempotency
```

Each app owns its tables and exposes a service layer. Cross-app writes go through
services, never through another app's ORM models directly — so extracting a service
later is a refactor, not a rewrite.

### 3.3 Request lifecycle

```
1  Nginx/CDN         TLS termination, static/media, rate limit by IP
2  Next.js BFF       session cookie → bearer token, SSR/ISR
3  DRF middleware    request ID, auth, throttle, audit context
4  Serializer        validation, field-level permissions
5  Service layer     business rules inside an explicit transaction
6  Repository/ORM    row locks where money or stock is involved
7  Signals/Celery    async side effects only — never inside the tx
8  Response          envelope, ETag, cache headers
```

Business logic lives in **services**, not in views, serializers or model `save()`.
Anything that touches stock or money is called inside `transaction.atomic()` with
explicit locking, and side effects (email, webhooks out, search reindex) are
dispatched **after commit** via `transaction.on_commit`.

---

## 4. What "granular" means here

The remaining documents specify, without hand-waving:

- **69 tables** with every column, type, nullability, default, index and constraint
- The **order state machine** and every legal transition
- The **stock reservation policy** — the single most important correctness decision
- **Idempotency** for webhooks and for client retries
- The **RBAC matrix** — every role against every action
- Concrete **performance budgets** and the indexes that meet them

Read `01-data-model.md` next.
