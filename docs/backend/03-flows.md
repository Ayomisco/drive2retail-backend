# Critical Flows

The flows where a bug costs real money or real stock. Everything else in the system
is CRUD; these are the parts that need to be exactly right.

---

## 1. The three rules

Every flow below obeys these. They are not style preferences — each one prevents a
specific, expensive failure.

**Rule 1 — The client never decides anything that matters.**
Prices, totals, stock availability, discounts and eligibility are all re-resolved
server-side at the moment of commit. The cart response carries computed totals so the
UI can render them, but the checkout transaction recomputes from scratch and ignores
anything the client sent.

**Rule 2 — Money and stock move inside one transaction, with row locks.**
Any code path that touches `inventory_item` or `order.amount_paid` runs inside
`transaction.atomic()` and takes `select_for_update()` on the rows it will change.
Locks are acquired in a **fixed global order** — `inventory_item.id` ascending — so
two concurrent checkouts can never deadlock by grabbing the same two rows in
opposite order.

**Rule 3 — Side effects happen after commit, never inside it.**
Email, gateway calls, search reindexing and webhooks out are dispatched via
`transaction.on_commit()`. An SMTP timeout must never roll back a paid order, and a
transaction must never be held open across a network call to a third party.

---

## 2. Registration and approval

```
Customer                  API                        Staff
   │                       │                           │
   ├─ POST /auth/register ─▶                           │
   │                       ├─ create user (inactive email)
   │                       ├─ create business_account (status=pending)
   │                       ├─ create address
   │                       ├─ create membership (role=owner)
   │                       ├─ audit: account.registered
   │                       └─ on_commit → verification email
   │◀─ 201 next_step=verify_email
   │                       │                           │
   ├─ click email link ────▶                           │
   ├─ POST /auth/email/verify                          │
   │                       ├─ mark verified, consume token
   │                       └─ on_commit → notify staff ─▶ approval queue
   │◀─ 200 next_step=awaiting_approval                 │
   │                       │                           │
   │                       │◀─ POST /admin/customers/{id}/approve
   │                       ├─ status=approved, can_view_prices=true, can_order=true
   │                       ├─ audit: account.approved (actor, reason)
   │                       └─ on_commit → welcome email
   │◀─ email: you can now order                        │
```

**Design notes**

- `accounts.require_approval` is a `setting`. If false, registration sets
  `approved` immediately and the staff step is skipped. PRD §17 leaves this open;
  the code must not assume either answer.
- Until approved, catalogue browsing works but prices are omitted and
  `POST /cart/items` returns `403 account_pending_approval`.
- Email verification and approval are independent. A verified-but-unapproved account
  can log in and see the catalogue; an approved-but-unverified one cannot log in.

---

## 3. Add to cart

Deliberately cheap. **No stock is reserved here.**

```
POST /cart/items { variant_id, quantity }

  1  Load variant + product. Not active → 404
  2  Restricted and account not eligible → 422 restricted_not_permitted
  3  quantity < moq                      → 422 below_moq        (meta: moq)
  4  (quantity - moq) % order_increment  → 422 invalid_order_increment
  5  quantity > max_order_qty            → 422 exceeds_max_quantity
  6  Resolve price (group, qty break, validity window)
  7  Upsert cart_item; snapshot unit_price
  8  Read availability — advisory only, never blocking
  9  Recompute cart totals
 10  Return the entire cart
```

Step 8 is the important one. Availability is shown, not enforced, at this stage.
Enforcement happens at checkout. Blocking add-to-cart on stock produces a worse
experience (the customer cannot even assemble a basket) without preventing anything —
the race is at payment, not at browsing.

**Why no reservation here:** a wholesale buyer builds a 40-line basket over twenty
minutes. Reserving at add-to-cart would hold hundreds of cases across dozens of
abandoned carts and make the catalogue read as sold out. Reservation belongs at
payment initiation, where the customer has committed.

---

## 4. Checkout — the transaction that matters

This is the highest-risk code in the system.

```
POST /checkout/initiate     Idempotency-Key: <uuid>

┌─ idempotency guard ────────────────────────────────────────┐
│ INSERT idempotency_key … status='in_progress'              │
│   duplicate + completed   → replay stored response         │
│   duplicate + in_progress → 409 duplicate_request          │
└────────────────────────────────────────────────────────────┘

BEGIN;

  1  SELECT … FROM cart WHERE id=%s FOR UPDATE
       └ status ≠ active or expired → 410 cart_expired

  2  Account gate
       └ status ≠ approved or not can_order → 403

  3  Re-resolve EVERY line server-side
       ├ product/variant inactive     → 409 with per-line detail
       ├ price differs from snapshot  → 409 price_changed + diff
       └ MOQ / increment re-check     → 422

  4  Delivery
       ├ resolve zone from address    → none → 422 unsupported_delivery_area
       ├ restricted lines + zone.supports_restricted=false → 422
       └ compute fee from delivery_rate

  5  Restricted acknowledgement
       └ any restricted line and not restricted_acknowledged → 422 restricted_ack_required

  6  Promotion — re-validate window, limits, per-account usage

  7  Totals  (Decimal, banker's rounding to 2dp)
       subtotal → discount → delivery → tax → grand_total

  8  SELECT … FROM inventory_item
       WHERE variant_id = ANY(%s) AND warehouse_id=%s
       ORDER BY id            ← fixed lock order, prevents deadlock
       FOR UPDATE
       └ any quantity_available < needed → 409 insufficient_stock (per line)

  9  INSERT order (status=pending_payment, order_number from sequence)
     INSERT order_item × N   ← full snapshot: sku, names, unit, price, tax
     Snapshot delivery_* and billing_* onto the order

 10  UPDATE inventory_item SET quantity_reserved = quantity_reserved + %s
     INSERT stock_reservation (status=held, expires_at = now() + 20 min)
       └ ck_inv_reserved fires if logic is wrong → transaction aborts, nothing sold twice

 11  INSERT payment_attempt (status=initiated, internal_reference=D2R-PAY-…)

 12  UPDATE cart SET status='converted', converted_order_id=…

 13  audit_log: order.created

COMMIT;

on_commit:
  → gateway.initialize(reference, amount_kobo, email, callback_url)
  → store authorization_url on the payment_attempt
  → schedule reservation-expiry check
```

**Why the reservation is created before the gateway call.** If we called the gateway
first and then reserved, a slow gateway response would leave a window where two
customers both get an authorization URL for the last case. Reserving inside the
transaction closes that window: the second customer fails at step 8 with a clean
`409` before any payment page opens.

**Why `ck_inv_reserved` exists.** `check (quantity_reserved <= quantity_on_hand)`
is redundant with correct application logic — which is exactly why it is there. It
is the constraint that turns a future refactoring bug into an aborted transaction
instead of an oversold pallet.

---

## 5. Payment verification

Two independent paths converge on the same idempotent handler. Either can arrive
first; neither may double-apply.

```
      Customer returns                    Provider webhook
             │                                   │
   GET /checkout/verify/{ref}          POST /webhooks/paystack
             │                                   │
             │                          ┌────────▼─────────┐
             │                          │ raw body read    │
             │                          │ HMAC verified    │  invalid → 401
             │                          │ INSERT           │
             │                          │ webhook_event    │  duplicate → 200, stop
             │                          │ enqueue task     │
             │                          │ return 200 <5s   │
             │                          └────────┬─────────┘
             │                                   │
             └───────────────┬───────────────────┘
                             ▼
              ┌──────────────────────────────┐
              │  verify_payment(reference)   │
              │  ── the single source of     │
              │     truth, idempotent ──     │
              └──────────────┬───────────────┘
                             ▼
          GET provider.transaction/verify/{reference}
                             │
       ┌─────────────────────┼─────────────────────┐
       ▼                     ▼                     ▼
   success               failed              pending/abandoned
       │                     │                     │
       │                     │                     └─ leave as-is; retry later
       │                     │
       │                     └─ BEGIN
       │                          payment_attempt → failed
       │                          release reservations
       │                          order.payment_status = failed
       │                          (order stays pending_payment → retryable)
       │                        COMMIT
       ▼
   BEGIN;
     SELECT order FOR UPDATE
     already paid? → COMMIT, return (idempotent no-op)

     amount mismatch? → flag for manual review, DO NOT mark paid
     currency mismatch? → same

     payment_attempt → successful, verified_at, fees, channel, card_last4
     order.payment_status = paid, status = paid, paid_at = now()
     amount_paid = verified amount

     -- commit the stock
     SELECT inventory_item … ORDER BY id FOR UPDATE
     quantity_on_hand   -= qty
     quantity_reserved  -= qty
     stock_reservation.status = committed
     INSERT inventory_movement (type=sale, delta=-qty, quantity_after=…, ref=order)

     INSERT invoice (number from gapless sequence, status=issued)
     order_status_history: pending_payment → paid
     audit_log: payment.verified
   COMMIT;

   on_commit:
     → render invoice PDF → S3
     → email confirmation + invoice
     → notify ops queue
     → reindex affected variants
```

**The amount check is not optional.** A verified transaction whose amount differs
from `order.grand_total` is either a bug or an attack. It is never auto-paid — it is
flagged for a human. This is the single most common way payment integrations lose
money.

**Why verification is re-run against the provider even for webhooks.** The webhook
payload tells you *something happened*; the verify endpoint tells you *what is true*.
Signature verification proves the message came from the provider, not that the
enclosed amount is what you should charge.

---

## 6. Reservation expiry

Celery beat, every 60 seconds:

```sql
SELECT * FROM stock_reservation
WHERE status = 'held' AND expires_at < now()
FOR UPDATE SKIP LOCKED
LIMIT 500;
```

For each, in a transaction: lock the `inventory_item`, decrement
`quantity_reserved`, mark the reservation `expired`, and if the order is still
`pending_payment` with no successful attempt, transition it to `expired`.

`SKIP LOCKED` means multiple workers can run this concurrently without contending.
The 500-row batch bounds transaction duration.

**Race with a late payment.** A payment can verify at second 1201, just after the
reservation expired. The verify handler re-checks availability: if stock is still
there it re-reserves and commits normally; if not, the order is flagged
`payment_received_no_stock` for ops to refund or backorder. This is rare but must
not silently oversell.

---

## 7. Fulfilment

```
paid ──▶ processing ──▶ dispatched ──▶ delivered
  │           │              │
  │           │              └─ shipment.tracking_reference, driver, vehicle
  │           └─ pick list generated, shipment created (partial allowed)
  └─ cancellable up to dispatch
```

`POST /admin/orders/{id}/shipments` creates a `shipment` with `shipment_item` lines.
Partial shipment is supported: `order_item.quantity_fulfilled` accumulates, and the
order only reaches `dispatched` when every line is fully shipped.

Delivery confirmation captures `received_by` and `delivery_proof_url` — a photo or
signature. For a wholesale business delivering to shops, proof of delivery is the
thing that settles disputes.

---

## 8. Cancellation and refund

**Customer cancellation** is permitted while `status IN (pending_payment, paid,
processing)` and no shipment has dispatched. It releases or reverses stock and, if
paid, opens a `refund` in `pending`.

**Refunds require two people** — `requested_by_id` and `approved_by_id` must differ.
This is enforced in the service layer, not just the UI.

```
BEGIN;
  SELECT order FOR UPDATE
  validate: amount_refunded + amount <= amount_paid   (also a check constraint)
  INSERT refund (status=pending) + refund_line rows
  restock? → for each line:
      inventory_item.quantity_on_hand += qty
      INSERT inventory_movement (type=return, delta=+qty, reason)
  order.amount_refunded += amount
  order.payment_status = refunded | partially_refunded
  audit_log: refund.created
COMMIT;
on_commit → provider.refund(...) → poll/webhook → refund.status = completed
```

---

## 9. Bulk import (PRD FR-10)

Two-phase, always. A half-applied 5,000-row price file is unrecoverable without a
restore.

```
Phase 1  upload → import_job (dry_run=true, status=validating)
         Celery: parse, validate every row, collect per-row errors
         → status=ready, errors[] downloadable as CSV
         Nothing has been written.

Phase 2  operator reviews the error report and confirms
         POST /admin/imports/{id}/apply   (idempotent)
         Celery: apply in chunks of 500 inside per-chunk transactions
         → inventory_movement / price rows / audit_log per change
         → status=completed with counts
```

Chunked transactions rather than one giant one: a 20,000-row import should not hold
locks for minutes, and a failure at row 19,000 should not discard the first 18,500.

---

## 10. Search indexing

At launch, Postgres FTS with the generated `search_vector` column — no external
service, no sync problem, no extra thing to operate.

Reindexing is unnecessary for FTS (the column is generated), but the **denormalised
counters** need maintenance:

| Counter | Refreshed by |
| --- | --- |
| `product.rating_avg` / `rating_count` | `on_commit` after review approval |
| `category.product_count` | Celery beat, every 15 min |
| `inventory_item.quantity_available` | generated column, always current |

When the catalogue passes ~20k SKUs or facet queries exceed the 200 ms budget,
introduce Meilisearch: index on `on_commit` of product/variant/price/stock changes,
with a nightly full reconcile to catch anything a failed task dropped.

---

## 11. Failure modes and responses

| Failure | Detection | Response |
| --- | --- | --- |
| Gateway timeout on initialize | HTTP timeout | Order stays `pending_payment`; customer retries; reservation TTL protects stock |
| Webhook never arrives | Beat job scans `initiated` attempts > 15 min | Actively verify against the provider |
| Duplicate webhook | `uq_webhook_event` | 200, no work |
| Two checkouts, last case | `FOR UPDATE` + `ck_inv_reserved` | Second gets `409 insufficient_stock` |
| Paid but stock gone | Verify-time availability re-check | Flag `payment_received_no_stock`, alert ops |
| Amount mismatch | Compare verified vs `grand_total` | Never auto-pay; manual review |
| Price changed mid-checkout | Snapshot vs resolved | `409 price_changed` with the diff |
| Celery worker dies mid-task | Task acks late, visibility timeout | Task redelivered; handlers are idempotent |
| Redis down | Connection error | Cache misses degrade to Postgres; **checkout still works** — Redis is never authoritative for stock |
| Postgres failover | Connection error | Read-only banner; writes rejected cleanly rather than half-applied |

The Redis row matters: reservations live in Postgres, not Redis. A Redis outage
must slow the site down, not corrupt inventory.
