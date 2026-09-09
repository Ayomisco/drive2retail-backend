# API Design

REST over HTTPS. JSON only. Versioned at the path root: `/api/v1/`.

OpenAPI 3.1 is generated from DRF serializers via `drf-spectacular` and published at
`/api/schema/`. The Next.js client is generated from it, so a contract change that
breaks the frontend fails at build time rather than in production.

---

## 1. Conventions

### 1.1 Envelope

Successful single-resource responses return the object directly. Collections are
wrapped:

```json
{
  "results": [ ... ],
  "pagination": {
    "count": 1284,
    "page": 3,
    "page_size": 24,
    "total_pages": 54,
    "next": "/api/v1/catalogue/products?page=4",
    "previous": "/api/v1/catalogue/products?page=2"
  },
  "facets": { ... }
}
```

Cursor pagination is used where the dataset is large or append-heavy
(`/orders`, `/inventory/movements`, `/audit-log`): stable under concurrent inserts,
and `OFFSET 50000` never happens.

### 1.2 Errors

One shape, everywhere.

```json
{
  "error": {
    "code": "insufficient_stock",
    "message": "Not enough stock for 2 items in your cart.",
    "detail": [
      {
        "field": "items.0.quantity",
        "code": "insufficient_stock",
        "message": "Only 8 cases available.",
        "meta": { "variant_id": "…", "requested": 12, "available": 8 }
      }
    ],
    "request_id": "1f0b…"
  }
}
```

`message` is safe to show a customer. `detail[].meta` carries what the UI needs to
correct the input inline. `request_id` matches the log line.

| HTTP | When |
| --- | --- |
| 400 | Validation failed |
| 401 | No/invalid credentials |
| 403 | Authenticated, not permitted — **or account not yet approved** |
| 404 | Not found, or exists but not visible to this actor |
| 409 | State conflict — illegal transition, price changed, stock gone |
| 410 | Cart/reservation expired |
| 422 | Business-rule violation (MOQ, order increment, restricted product) |
| 429 | Throttled — includes `Retry-After` |
| 500 | Unhandled; never leaks internals |

**403 for an unapproved account, not 404.** The customer must be told they are
waiting on approval, not that the catalogue does not exist.

Error codes are a closed set exported in the OpenAPI schema so the frontend can
switch on them: `invalid_credentials`, `account_pending_approval`,
`account_suspended`, `below_moq`, `invalid_order_increment`, `insufficient_stock`,
`price_changed`, `cart_expired`, `unsupported_delivery_area`,
`restricted_not_permitted`, `restricted_ack_required`, `promotion_invalid`,
`payment_verification_failed`, `duplicate_request`, `invalid_state_transition`.

### 1.3 Common headers

| Header | Direction | Purpose |
| --- | --- | --- |
| `Authorization: Bearer <jwt>` | → | Access token (BFF adds it) |
| `X-Request-ID` | ↔ | Correlation; echoed and logged |
| `Idempotency-Key` | → | Required on unsafe money/stock writes |
| `X-Business-Account` | → | Active account when a user belongs to several |
| `ETag` / `If-None-Match` | ↔ | Catalogue caching |
| `Retry-After` | ← | On 429/503 |

### 1.4 Naming

Plural nouns, kebab-case paths, snake_case JSON fields (Python-native, and the
generated TS client camelises at the boundary). No verbs in paths except for explicit
state actions, which are sub-resources: `POST /orders/{id}/cancel`.

---

## 2. Public catalogue

Unauthenticated where `accounts.hide_prices_until_approved` is false; otherwise
prices are omitted for anonymous callers and the payload carries
`"pricing_visible": false`.

### `GET /api/v1/catalogue/products`

The main catalogue and search endpoint. Serves every one of the frontend's shop
layouts.

**Query parameters**

| Param | Type | Notes |
| --- | --- | --- |
| `q` | string | Full-text over name, SKU, brand, description |
| `category` | slug, repeatable | Includes descendants |
| `brand` | slug, repeatable | |
| `price_min` / `price_max` | decimal | |
| `rating_min` | 1–5 | |
| `attr.<code>` | string, repeatable | `attr.size=150ml&attr.colour=blue` |
| `pack_size` | `unit`\|`pack`\|`case` | |
| `discount_min` | int | percent off |
| `in_stock` | bool | |
| `restricted` | bool | Omitted → excluded for ineligible accounts |
| `sort` | enum | `popularity`(default) `price_asc` `price_desc` `rating` `name_asc` `name_desc` `newest` |
| `page` / `page_size` | int | max 96 |

**Response**

```json
{
  "results": [{
    "id": "0c1e…",
    "slug": "nivea-men-cream-150ml",
    "name": "NIVEA Men Creme 150ml",
    "brand": { "slug": "nivea", "name": "NIVEA" },
    "category": { "slug": "skincare", "name": "Skincare" },
    "primary_image": { "url": "https://…", "alt": "…", "width": 600, "height": 600 },
    "rating_avg": 4.4,
    "rating_count": 189,
    "is_restricted": false,
    "default_variant": {
      "id": "9ab2…",
      "sku": "D2R-NIV-CRM150-CS",
      "selling_unit": "case",
      "units_per_pack": 1,
      "packs_per_case": 24,
      "base_units": 24,
      "moq": 1,
      "order_increment": 1,
      "price": { "amount": "27490.00", "currency": "NGN",
                 "compare_at": "39990.00", "discount_percent": 31 },
      "availability": { "in_stock": true, "quantity_available": 46, "low_stock": false }
    },
    "variant_count": 3
  }],
  "pagination": { "…": "…" },
  "facets": {
    "category":  [{ "slug": "skincare", "name": "Skincare", "count": 214 }],
    "brand":     [{ "slug": "nivea", "name": "NIVEA", "count": 88 }],
    "price":     { "min": "450.00", "max": "184000.00" },
    "attributes": { "size": [{ "value": "150ml", "count": 34 }] },
    "rating":    [{ "value": 4, "count": 121 }]
  }
}
```

`facets` are computed in the same request. Postgres does this with `FILTER` aggregates
over a CTE of the matched set — one query, not one per facet.

**Caching.** `Cache-Control: public, s-maxage=120, stale-while-revalidate=600` +
`ETag`. Anonymous responses are edge-cached; authenticated ones vary on customer
group only (not on user), so the cache still works.

### `GET /api/v1/catalogue/products/{slug}`

Full PDP payload: all variants with prices and availability, images, `attributes`
(the spec table), the breadcrumb trail, approved reviews with a rating histogram, and
`related_products`.

### `GET /api/v1/catalogue/categories` · `GET /api/v1/catalogue/categories/{slug}`

Full tree (cached 1 hour) and single-node detail with ancestors and children.

### `GET /api/v1/catalogue/brands` · `/brands/{slug}`

### `GET /api/v1/catalogue/search/suggest?q=`

Typeahead for the header search the frontend already renders. Returns up to 5
products, 3 categories, 3 brands. Target **p95 < 80 ms**; served from Redis with a
60 s TTL keyed on the normalised query.

### `POST /api/v1/catalogue/quick-order/resolve`

PRD FR-06 — the wholesale pad. Accepts SKUs and quantities, returns resolved lines
with prices, MOQ validation and availability, without opening product pages.

```json
{ "lines": [{ "sku": "D2R-NIV-CRM150-CS", "quantity": 12 }] }
```

---

## 3. Authentication

All under `/api/v1/auth/`. Called by the Next.js BFF, which converts the token pair
into an `httpOnly` cookie.

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/register` | Creates `user` + `business_account` (status `pending`) |
| POST | `/login` | Returns access + refresh; throttled 5/min/IP, 10/hour/email |
| POST | `/logout` | Revokes the refresh token |
| POST | `/refresh` | Rotates; reuse of a spent token revokes the chain |
| POST | `/password/forgot` | **Always 202**, regardless of whether the email exists |
| POST | `/password/reset` | Token from the email link |
| POST | `/password/change` | Authenticated; requires current password |
| POST | `/email/verify` | Token from the email link |
| POST | `/email/resend` | Throttled 1/min |
| POST | `/otp/request` · `/otp/verify` | Phone verification, matches the OTP panel |
| GET | `/me` | Current user, memberships, permissions, active account |

**Register** — the field set the panel must grow into:

```json
{
  "business_name": "Adeola Stores Ltd",
  "business_type": "retailer",
  "registration_number": "RC1234567",
  "tax_id": "12345678-0001",
  "first_name": "Adeola",
  "last_name": "Okonkwo",
  "email": "buyer@adeolastores.ng",
  "phone": "+2348012345678",
  "password": "…",
  "delivery_address": { "line1": "…", "city": "Ikorodu", "state": "Lagos" },
  "accepts_terms": true
}
```

Response `201`:

```json
{
  "user": { "id": "…", "email": "…", "is_email_verified": false },
  "business_account": { "id": "…", "account_number": "D2R-C-00417", "status": "pending" },
  "next_step": "verify_email",
  "message": "Check your email to confirm your address. Your account will be reviewed for wholesale purchasing."
}
```

`next_step` lets the UI drive the flow without hard-coding business rules.

---

## 4. Account

| Method | Path | Notes |
| --- | --- | --- |
| GET/PATCH | `/account/profile` | Name, phone |
| GET/PATCH | `/account/business` | Business details; some fields lock after approval |
| GET | `/account/members` | Users on this account |
| POST | `/account/members/invite` | Owner only |
| DELETE | `/account/members/{id}` | Owner only |
| GET/POST | `/account/addresses` | |
| GET/PATCH/DELETE | `/account/addresses/{id}` | |
| POST | `/account/addresses/{id}/set-default` | |
| GET | `/account/orders` | Cursor paginated; filters `status`, `date_from`, `date_to`, `q` |
| GET | `/account/orders/{order_number}` | Full detail with items, shipments, payments |
| POST | `/account/orders/{order_number}/reorder` | → returns a cart |
| POST | `/account/orders/{order_number}/cancel` | Only before dispatch |
| GET | `/account/invoices/{invoice_number}` | JSON |
| GET | `/account/invoices/{invoice_number}/pdf` | Signed S3 URL, 5-min expiry |
| GET/POST/DELETE | `/account/wishlist` | Maps to the wishlist pages |
| GET | `/account/dashboard` | Counts + recent orders for the account landing tab |

### `POST /account/orders/{n}/reorder` (PRD FR-09)

Never blindly recreates the order. Returns what changed:

```json
{
  "cart_id": "…",
  "added": [ { "sku": "…", "quantity": 12 } ],
  "adjustments": [
    { "sku": "D2R-KH-KET-CS", "issue": "price_changed",
      "old_price": "18500.00", "new_price": "19750.00" },
    { "sku": "D2R-OB-JRK-PK", "issue": "insufficient_stock",
      "requested": 40, "added": 12 },
    { "sku": "D2R-VK-CHP-CS", "issue": "discontinued", "added": 0 }
  ]
}
```

---

## 5. Cart

Server-authoritative. The client never computes a total that is charged.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/cart` | Current cart; creates one lazily |
| POST | `/cart/items` | `{variant_id, quantity}` |
| PATCH | `/cart/items/{id}` | `{quantity}` |
| DELETE | `/cart/items/{id}` | |
| DELETE | `/cart/items` | Empty |
| POST | `/cart/merge` | Anonymous cart → account cart at login |
| POST | `/cart/promotion` | Apply coupon |
| DELETE | `/cart/promotion` | |
| POST | `/cart/validate` | Full server revalidation before checkout |
| POST | `/cart/delivery-estimate` | `{address_id}` → zone, fee, ETA |

**Response**

```json
{
  "id": "…",
  "currency": "NGN",
  "items": [{
    "id": "…",
    "variant": { "id": "…", "sku": "…", "name": "…", "selling_unit": "case",
                 "base_units": 24, "moq": 1, "order_increment": 1,
                 "image_url": "…", "is_restricted": false },
    "quantity": 12,
    "unit_price": "27490.00",
    "line_subtotal": "329880.00",
    "line_total": "354621.00",
    "availability": { "in_stock": true, "quantity_available": 46 },
    "issues": []
  }],
  "totals": {
    "subtotal": "329880.00", "discount_total": "0.00",
    "delivery_fee": "8500.00", "tax_total": "24741.00",
    "grand_total": "363121.00"
  },
  "promotion": null,
  "requires_restricted_ack": false,
  "issues": [],
  "is_checkoutable": true
}
```

`issues` on a line uses the same code vocabulary as errors — `below_moq`,
`invalid_order_increment`, `insufficient_stock`, `price_changed`,
`restricted_not_permitted`, `discontinued`. `is_checkoutable` is the single flag the
checkout button binds to.

**Every mutation returns the whole cart.** No client-side total arithmetic, no drift.

---

## 6. Checkout & payment

The most safety-critical surface. Every write here requires `Idempotency-Key`.

### `POST /api/v1/checkout/initiate`

```json
{
  "delivery_address_id": "…",
  "billing_address_id": "…",
  "delivery_rate_id": "…",
  "payment_provider": "paystack",
  "customer_note": "Deliver before 10am",
  "restricted_acknowledged": true
}
```

Inside one transaction:

1. Lock the cart (`select_for_update`).
2. Re-resolve every price server-side. Any change → `409 price_changed` with the diff.
3. Re-validate MOQ, increments, product status, restricted eligibility.
4. Resolve delivery zone from the address; unsupported → `422 unsupported_delivery_area`.
5. Compute delivery fee, discount, tax, grand total.
6. Create `order` (`pending_payment`) and snapshot every `order_item`.
7. **Reserve stock** — `select_for_update` each `inventory_item`, create
   `stock_reservation` rows with a 20-minute TTL.
8. Create `payment_attempt` (`initiated`) with our `internal_reference`.
9. `on_commit` → call the gateway for an authorization URL.

```json
{
  "order": { "order_number": "D2R-2026-000417", "status": "pending_payment",
             "grand_total": "363121.00", "currency": "NGN" },
  "payment": {
    "provider": "paystack",
    "reference": "D2R-PAY-9f2a1c…",
    "authorization_url": "https://checkout.paystack.com/…",
    "expires_at": "2026-09-08T14:22:00Z"
  }
}
```

### `GET /api/v1/checkout/verify/{reference}` (PRD PAY-04)

Called when the customer returns from the gateway. **Verifies server-side against the
provider API.** A browser redirect alone never marks an order paid — the redirect is
only a hint that verification should run now.

Returns `{ "status": "paid" | "pending" | "failed", "order": {...} }`, which drives
the success / pending / failure screens.

### `POST /api/v1/webhooks/paystack` · `/webhooks/flutterwave`

1. Read the raw body **before** any parsing.
2. Verify the HMAC signature (`x-paystack-signature`) with `hmac.compare_digest`.
   Invalid → `401`, logged, no processing.
3. Optionally check the source IP against the provider's published range.
4. `INSERT INTO webhook_event` — a unique violation on `(provider, event_id)` means
   this is a duplicate: return `200` immediately, do nothing.
5. Enqueue a Celery task; **return `200` within 5 seconds**. Providers retry on
   timeout, and slow processing causes duplicate deliveries.
6. The worker verifies the transaction against the provider API — the webhook payload
   is a *notification*, not evidence — then transitions the order.

### `POST /api/v1/checkout/retry/{order_number}` (PRD PAY-07)

Creates a fresh `payment_attempt` for an unpaid order, re-checking stock and
re-reserving if the previous hold expired.

---

## 7. Admin API

Under `/api/v1/admin/`. Requires staff auth + MFA. Every endpoint is permission-gated
per `04-security.md` §3, and every write emits an `audit_log` row.

The Django Admin covers day-to-day CRUD. This API exists for the custom dashboard
screens (analytics, bulk operations, the fulfilment board) that the admin does not
model well.

| Area | Endpoints |
| --- | --- |
| Dashboard | `GET /admin/dashboard/summary`, `/sales-series`, `/top-products`, `/low-stock` |
| Catalogue | `GET|POST /admin/products`, `GET|PATCH|DELETE /admin/products/{id}`, `POST /admin/products/{id}/publish`, `/archive`, `/duplicate`, variants + images sub-resources |
| Pricing | `GET|POST /admin/prices`, `POST /admin/prices/bulk-update` |
| Inventory | `GET /admin/inventory`, `POST /admin/inventory/adjustments`, `POST /admin/inventory/adjustments/{id}/apply`, `GET /admin/inventory/movements`, `GET /admin/inventory/low-stock` |
| Orders | `GET /admin/orders`, `GET /admin/orders/{id}`, `POST /admin/orders/{id}/status`, `/note`, `/cancel`, `POST /admin/orders/{id}/shipments`, `PATCH /admin/shipments/{id}` |
| Payments | `GET /admin/payments`, `GET /admin/payments/reconciliation`, `POST /admin/refunds`, `POST /admin/refunds/{id}/approve` |
| Customers | `GET /admin/customers`, `GET /admin/customers/{id}`, `POST /admin/customers/{id}/approve`, `/reject`, `/suspend`, `PATCH /admin/customers/{id}/settings` |
| Delivery | CRUD on zones, areas, rates |
| Promotions | CRUD + `GET /admin/promotions/{id}/redemptions` |
| Imports | `POST /admin/imports` (upload), `GET /admin/imports/{id}` (progress + errors), `POST /admin/imports/{id}/apply` |
| Reports | `GET /admin/reports/{sales|products|customers|inventory|payments}` with `?format=csv|xlsx` |
| Staff | `GET|POST /admin/staff`, `PATCH /admin/staff/{id}/roles` |
| Audit | `GET /admin/audit-log` |
| Settings | `GET|PATCH /admin/settings` |

### `GET /admin/dashboard/summary`

Feeds the dashboard the frontend already renders (donut + line chart + tables):

```json
{
  "period": { "from": "2026-09-01", "to": "2026-09-08" },
  "orders": { "total": 184, "pending_payment": 12, "processing": 41,
              "dispatched": 28, "delivered": 96, "cancelled": 7 },
  "revenue": { "gross": "18420500.00", "net": "17890200.00",
               "refunded": "530300.00", "currency": "NGN",
               "change_percent": 12.4 },
  "inventory": { "skus": 1284, "low_stock": 37, "out_of_stock": 9,
                 "stock_value": "94210000.00" },
  "customers": { "total": 412, "pending_approval": 8, "new_this_period": 23 },
  "payments": { "successful": 176, "failed": 14, "pending": 12 }
}
```

---

## 8. Idempotency

Required on: `POST /checkout/initiate`, `/checkout/retry`, `/admin/refunds`,
`/admin/inventory/adjustments/{id}/apply`, `/admin/imports/{id}/apply`.

```
1  Client sends Idempotency-Key: <uuid4>
2  Server INSERTs idempotency_key (key, endpoint, request_hash, status='in_progress')
3  Unique violation?
     └─ status='completed' and request_hash matches → replay the stored response
     └─ status='in_progress'                       → 409 duplicate_request (retry later)
     └─ request_hash differs                       → 422 (key reused for a different body)
4  Execute, store (response_status, response_body), mark 'completed'
5  Rows expire after 24 h
```

The client generates the key once per user intent and reuses it across retries —
so a flaky connection during checkout can never create two orders.

---

## 9. Rate limits

| Scope | Limit |
| --- | --- |
| Anonymous, global | 100 req/min/IP |
| Authenticated, global | 600 req/min/user |
| `POST /auth/login` | 5/min/IP **and** 10/hour/email |
| `POST /auth/register` | 3/hour/IP |
| `POST /auth/password/forgot` | 3/hour/email |
| `GET /catalogue/search/suggest` | 30/min/IP |
| `POST /checkout/initiate` | 10/hour/account |
| Webhooks | Not limited; signature-gated |
| Admin | 1200 req/min/user |

Enforced in Redis with a sliding window. 429 responses carry `Retry-After`.

---

## 10. Versioning & deprecation

`/api/v1/` is stable. Additive changes (new optional field, new endpoint) ship
in-place. Breaking changes open `/api/v2/`; `v1` then serves for **at least 6 months**
with a `Deprecation` and `Sunset` header on every response.
