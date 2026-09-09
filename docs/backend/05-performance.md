# Performance

Sized for D2R's stated coverage — 500 KAM + 2,500 VAN + 60 wholesale outlets across
five Lagos axes. Realistic peak: **200–400 concurrent users**, a few thousand orders
a month, a catalogue of 2k–20k SKUs.

This is a small system. The engineering risk is correctness, not throughput. The
budgets below are set so the site feels instant on a Lagos 4G connection, not so it
survives Black Friday at Amazon scale.

---

## 1. Budgets

| Surface | p50 | p95 | Hard ceiling |
| --- | --- | --- | --- |
| Catalogue listing (cached) | 40 ms | 120 ms | 300 ms |
| Catalogue listing (cold, with facets) | 120 ms | 300 ms | 600 ms |
| Search suggest | 25 ms | 80 ms | 150 ms |
| Product detail | 60 ms | 180 ms | 400 ms |
| Cart read | 40 ms | 120 ms | 250 ms |
| Cart mutate | 80 ms | 200 ms | 500 ms |
| **Checkout initiate** | 250 ms | 700 ms | 2 s |
| Payment verify | 400 ms | 1.2 s | 3 s (provider-bound) |
| Admin list views | 100 ms | 350 ms | 800 ms |
| Webhook ack | 20 ms | 60 ms | **5 s** (provider retry threshold) |

Front-end targets: **LCP < 2.0 s, INP < 200 ms, CLS < 0.05** on 4G / mid-range
Android — the actual device profile of a Lagos shop owner.

---

## 2. Caching layers

```
Browser  →  CDN edge  →  Next.js ISR  →  Redis  →  Postgres
 (30 s)     (2 min)        (5 min)       (varies)
```

| Layer | Holds | TTL | Invalidation |
| --- | --- | --- | --- |
| CDN | Images, CSS, JS, anonymous catalogue JSON | 1 y (hashed assets), 2 min (JSON) | Purge on deploy; tag purge on product change |
| Next.js ISR | Category and product pages | 5 min | `revalidateTag('product:{id}')` on write |
| Redis: catalogue | Category tree, brand list, facet counts | 1 h | Explicit delete on catalogue write |
| Redis: search | Suggest results by normalised query | 60 s | TTL only |
| Redis: pricing | Resolved price per (variant, group) | 10 min | Delete on price write |
| Redis: session | User context, permissions, active account | 15 min | Delete on logout/role change |
| Postgres | Everything authoritative | — | — |

**Never cached:** cart, stock quantities, order state, anything under `/admin`.
Stock is the one number that must always be read from the row that a lock protects —
a cached availability figure is how you oversell.

### Cache key discipline

```
cat:list:v1:{hash(filters)}:{group_id}
cat:facets:v1:{hash(filters)}
prod:detail:v1:{slug}:{group_id}
price:v1:{variant_id}:{group_id}:{qty_band}
```

Keys are versioned (`v1`) so a shape change is a prefix bump, not a flush. Prices
vary by **customer group**, never by user — so the cache stays effective for
authenticated traffic.

---

## 3. Query performance

### 3.1 The N+1 problem, structurally prevented

A catalogue page renders 24 products, each with a brand, a category, a primary image,
a default variant, a price and an availability figure. Naïvely that is 150+ queries.

```python
Product.objects
  .select_related("brand", "category", "tax_class")
  .prefetch_related(
      Prefetch("images", queryset=ProductImage.objects.filter(is_primary=True)),
      Prefetch("variants", queryset=(
          ProductVariant.objects
            .filter(status="active", is_default=True)
            .select_related("inventory_item")
            .prefetch_related(active_prices_for(group))
      )),
  )
```

**4 queries, not 150.** Enforced in CI: `nplusone` runs in the test suite and fails
the build on detection, and every list endpoint has an
`assertNumQueries` test pinning its query count. A regression breaks the build rather
than the production p95.

### 3.2 The indexes that matter

Beyond the schema's declared indexes, these are the ones that carry the hot paths:

```sql
-- catalogue listing: the dominant query
create index idx_product_listing on product (category_id, status, published_at desc)
  where archived_at is null and status = 'active';

-- price resolution, run once per line at checkout
create index idx_price_resolve on price
  (variant_id, customer_group_id, min_quantity desc, valid_from desc)
  where valid_to is null or valid_to > now();

-- the order history screen
create index idx_order_history on "order"
  (business_account_id, created_at desc) include (order_number, status, grand_total);

-- ops fulfilment board
create index idx_order_queue on "order" (status, placed_at)
  where status in ('paid', 'processing');

-- low-stock alerting
create index idx_inv_reorder on inventory_item (warehouse_id, quantity_available)
  where quantity_available <= reorder_point;

-- facet aggregation
create index idx_av_facet on attribute_value (attribute_id, value_text) include (variant_id);
```

Partial indexes throughout: indexing only `status='active'` products keeps the
listing index a fraction of the table size and entirely in memory.

`INCLUDE` columns make the order-history and facet queries **index-only scans** — no
heap fetch at all.

### 3.3 Facets in one query

Facet counts are the expensive part of a catalogue page. One CTE, `FILTER`
aggregates, no per-facet round trip:

```sql
with matched as (
  select p.id, p.brand_id, p.category_id, v.id as variant_id
  from product p
  join product_variant v on v.product_id = p.id and v.is_default
  where p.status = 'active' and p.archived_at is null
    and p.search_vector @@ plainto_tsquery('simple', %s)
)
select
  (select json_agg(x) from (
     select b.slug, b.name, count(*) as count
     from matched m join brand b on b.id = m.brand_id
     group by b.slug, b.name order by count desc limit 20) x) as brands,
  (select json_agg(y) from (
     select c.slug, c.name, count(*) as count
     from matched m join category c on c.id = m.category_id
     group by c.slug, c.name order by count desc limit 20) y) as categories;
```

### 3.4 Connection pooling

PgBouncer in **transaction** mode, 20 server connections per app instance.
Django's `CONN_MAX_AGE=0` behind PgBouncer (persistent connections at the app layer
would defeat it). Prepared statements disabled in transaction mode.

Postgres `max_connections=200`; PgBouncer fronts it so a traffic spike queues rather
than exhausting the database.

---

## 4. Async work

Anything slower than ~100 ms that the response does not need moves to Celery.

| Queue | Concurrency | Work |
| --- | --- | --- |
| `critical` | 4 | Payment verification, webhook processing |
| `default` | 4 | Email, invoice PDFs, notifications |
| `bulk` | 2 | CSV imports, report generation, exports |
| `beat` | 1 | Reservation expiry, stale-payment sweep, counter refresh |

Separate queues so a 20,000-row import cannot delay payment verification. Retries
use exponential backoff with jitter, `max_retries=5`, and a dead-letter queue that
alerts.

---

## 5. Frontend performance

The Next.js app is already well-placed: 62 static routes, ~102 kB shared JS. Keeping
it that way as data arrives:

| Technique | Application |
| --- | --- |
| Server Components by default | Product cards, listings, PDP content ship zero JS |
| Client Components only where interactive | Cart, quantity steppers, filters, carousels |
| Streaming + Suspense | Shell renders immediately; product grid streams in |
| ISR | Catalogue pages regenerate every 5 min; `revalidateTag` on write |
| Optimistic UI | Cart updates render instantly, reconcile with the server response |
| `next/image` | AVIF/WebP, correct `sizes`, explicit dimensions (CLS already handled) |
| Route prefetching | Viewport-based on product links |
| Bundle discipline | ApexCharts is admin-only and dynamically imported — it must never enter the storefront bundle |

**The current 32 MB of `public/assets` needs attention before launch.** Template
demo imagery should be pruned to what the live site uses, and real product images
must go to S3 + CDN rather than the repo.

---

## 6. Scaling path

Deliberately staged. Do not build stage 3 on day one.

| Stage | Trigger | Action |
| --- | --- | --- |
| 1 (launch) | — | Single app instance, managed Postgres, Redis, 2 workers |
| 2 | p95 > budget or CPU > 60% | Scale app instances horizontally (stateless), add workers |
| 3 | Read load dominates | Postgres read replica; route catalogue reads to it |
| 4 | Catalogue > 20k SKUs or facets > 200 ms | Meilisearch |
| 5 | Multi-region / national expansion | CDN origin shield, regional read replicas |
| 6 | Sustained order volume | Partition `order`, `inventory_movement`, `audit_log` by month |

**Writes never go to a replica.** Stock and payment paths are primary-only, always —
replica lag would produce exactly the overselling the reservation system exists to
prevent.

---

## 7. Load testing before launch

k6 scenarios, run against staging with production-shaped data:

| Scenario | Profile | Pass condition |
| --- | --- | --- |
| Catalogue browse | 300 VU, 10 min | p95 < 300 ms, 0 errors |
| Search | 100 VU, 5 min | p95 < 150 ms |
| Cart operations | 150 VU, 10 min | p95 < 250 ms |
| **Checkout contention** | 100 VU, same SKU, 10 units of stock | **exactly 10 succeed**, 90 get clean `409` |
| Webhook burst | 500 events in 30 s, 30% duplicates | 0 double-fulfilment, all acked < 5 s |
| Admin reporting | 20 VU on 12-month reports | p95 < 2 s, no lock contention with storefront |

The checkout contention test is the one that must not be skipped. It is the direct
test of the reservation design in `03-flows.md` §4, and it is the only way to prove
the system cannot oversell before real money is involved.

---

## 8. Observability

- **Traces**: OpenTelemetry, sampled at 10% (100% for checkout and payment paths).
- **Metrics**: request rate/latency/error by endpoint; Celery queue depth and task
  duration; database connections and slow queries; cache hit ratio; payment success
  rate; stock reservation hold time.
- **Logs**: structured JSON, `request_id` correlated end to end from the BFF through
  DRF into Celery.
- **Business dashboard**: orders/hour, GMV, conversion, cart abandonment, payment
  failure rate by provider, average fulfilment time.

The alert that matters most is **payment success rate**. A gateway degradation is
invisible in CPU and latency graphs and costs money every minute it goes unnoticed.
