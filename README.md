# Drive 2 Retail — Backend

Wholesale e-commerce API for **Drive 2 Retail Limited**, an FMCG re-distribution
company operating across Lagos.

Django 5 · Django REST Framework · PostgreSQL 16 · Redis · Celery

> D2R manages the catalogue on its vendors' behalf — vendors never log in. That
> makes this an internal-tools product with a storefront attached, which is why
> Django was chosen over Node. The reasoning is in
> [`docs/backend/00-overview.md`](docs/backend/00-overview.md) §2.

## Quick start

```bash
cp .env.example .env          # then fill in the values below
make install                  # uv venv + dependencies
docker compose up -d db redis # or point DATABASE_URL / REDIS_URL at your own
make migrate
make seed                     # roles, tax classes, Lagos delivery zones, settings
make superuser
make dev                      # http://localhost:8000
```

| URL | What |
| --- | --- |
| `/api/v1/` | The API |
| `/api/docs/` | Swagger UI (drf-spectacular) |
| `/api/redoc/` | ReDoc |
| `/api/schema/` | OpenAPI 3.1 — the Next.js clients are generated from this |
| `/staff/` | Django admin — the staff back office |
| `/health/` | Full dependency check (DB, cache, broker) |
| `/health/live/` | Liveness only |

## What you need to provision

| Service | Version | Used for |
| --- | --- | --- |
| **PostgreSQL** | 16+ | Everything authoritative. Needs `pg_trgm`, `citext`, `pgcrypto` |
| **Redis** | 7+ | Cache, rate limits, Celery broker and results |
| **S3-compatible storage** | — | Product images, invoice PDFs, import files. Cloudflare R2 or AWS S3 |
| **Resend** | — | Transactional email |
| **Paystack** | — | Payments. Flutterwave sits behind the same adapter interface |
| **Sentry** | — | Errors and tracing |
| **PgBouncer** | — | Connection pooling in production (transaction mode) |

Every key is documented in [`.env.example`](.env.example).

Two workers are expected in production, on separate queues, so payment
verification never waits behind a 20,000-row import:

```bash
celery -A config worker -Q critical,default -l info --concurrency 4
celery -A config worker -Q bulk -l info --concurrency 2
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

## Layout

A modular monolith. Not microservices — at this scale they would add operational
cost and distributed-transaction risk for no benefit.

```
config/
  settings/       base · local · test · staging · production
  celery.py       queue routing and beat schedules
  urls.py         /api/v1 + OpenAPI + admin + health

d2r/
  core/           base models, error envelope, idempotency, pagination,
                  permissions, structured logging, Resend backend, health
  accounts/       users, business accounts, members, addresses, staff roles, tokens
  catalogue/      categories, brands, vendors, products, variants, attributes
  pricing/        tax classes, price lists, volume breaks, promotions
  inventory/      warehouses, stock, reservations, movements, batches
  carts/          carts with MOQ and order-increment validation
  orders/         orders, snapshots, the status machine
  payments/       gateway adapters, attempts, webhooks, refunds, invoices
  delivery/       zones, area matching, rates, shipments
  dispatch/       drivers, vehicles, routes, trips, proof of delivery, COD
  procurement/    purchase orders, goods receipt, supplier invoices
  content/        reviews, wishlists, notifications, banners
  ops/            audit log, imports, idempotency keys, settings
```

Each app follows the same shape:

```
models.py  constants.py  services.py  selectors.py  tasks.py  admin.py
api/       serializers.py  views.py  urls.py  filters.py  permissions.py
tests/
```

**Business logic lives in `services.py`**, not in views, serializers or model
`save()`. Anything touching money or stock runs inside `transaction.atomic()`
with explicit row locks, and side effects are dispatched via
`transaction.on_commit`.

`selectors.py` owns read queries so `select_related`/`prefetch_related` stay in
one place and list endpoints keep passing their `assertNumQueries` budgets.

## The three things that must be right

1. **Stock reservation** — held at payment initiation with a 20-minute TTL, never
   at add-to-cart. `SELECT … FOR UPDATE` in a fixed lock order, plus a
   `check (quantity_reserved <= quantity_on_hand)` constraint as the last line of
   defence. → [`03-flows.md`](docs/backend/03-flows.md) §4
2. **Payment idempotency** — `unique (provider, event_id)` on the webhook ledger;
   insert first, process second. Always re-verify against the provider API; never
   trust a redirect or a payload amount. → [`03-flows.md`](docs/backend/03-flows.md) §5
3. **Order snapshots** — every line copies SKU, names, unit, price and tax.
   Renaming a product must never rewrite history. → [`01-data-model.md`](docs/backend/01-data-model.md) §6

## Documentation

Full specification in [`docs/backend/`](docs/backend/). Start with
[`README.md`](docs/backend/README.md) there.

## Development

```bash
make test        # pytest, parallel
make test-cov    # with coverage
make lint        # ruff
make format      # ruff format + fix
make typecheck   # mypy, strict
make schema      # regenerate and validate the OpenAPI schema
make audit       # pip-audit
```

`pre-commit install` wires ruff, secret detection and large-file checks into
every commit.

### Non-negotiable tests

These exist because each corresponds to a way this class of system loses money.
CI runs them on every commit:

1. Two concurrent checkouts on the last unit — exactly one succeeds
2. Duplicate webhook delivery — no double fulfilment, no double stock deduction
3. Payment verified for the wrong amount — order is **not** marked paid
4. Expired reservation — stock released, order expires
5. Price changes mid-checkout — `409`, old price never charged
6. Account A cannot read account B's order, invoice or address
7. A refund requester cannot approve their own refund
8. MOQ and increment violations rejected server-side

## Build status

Scaffold complete and verified: `manage.py check` passes, migrations generate,
the OpenAPI schema builds without warnings, lint/format/tests are green.

`accounts`, `ops` and `delivery` have full models. The remaining apps have their
package structure, constants and app configs in place; their models are specified
table-by-table in [`01-data-model.md`](docs/backend/01-data-model.md) and
[`schema.sql`](docs/backend/schema.sql) and are implemented per the milestones in
[`07-delivery-plan.md`](docs/backend/07-delivery-plan.md).

## Decisions still needed

Listed with impact and cost-if-late in
[`07-delivery-plan.md`](docs/backend/07-delivery-plan.md) §1. The ones that
cannot be changed once real orders exist:

1. Currency, and whether displayed prices include VAT
2. Invoice numbering format and required tax fields
3. Alcohol/restricted-product rules for Lagos
4. **Is cash on delivery offered?** — changes the payment model and finance workflow
5. **Do you track lot numbers and expiry today?** — decides whether batch tracking
   is built at M3 or retrofitted expensively
