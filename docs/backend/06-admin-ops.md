# Admin & Operations

D2R manages the catalogue on its vendors' behalf. Staff live in these screens all
day; customers pass through the storefront in minutes. **This is the product.**

---

## 1. Two surfaces, deliberately

| | Django Admin | Custom admin (Next.js) |
| --- | --- | --- |
| Purpose | Data management | Operational workflow |
| Users | Catalogue, finance, superuser | Ops, inventory, support, sales |
| Built | Configuration, days | React, weeks |
| Covers | CRUD on all 67 tables, search, filters, bulk actions, history | Dashboard, fulfilment board, stock console, reconciliation, imports |

Django Admin is not a placeholder to be replaced later. It is the correct tool for
"edit this product's tax class" and it will never be worth rebuilding. The custom UI
exists only where a workflow spans several tables and needs to be fast under
repetition — picking and dispatching fifty orders, or counting stock.

Both authenticate against the same users, roles and permission matrix
(`04-security.md` §2.3), and both write to the same `audit_log`.

---

## 2. Django Admin configuration

Not default scaffolding. Each model gets deliberate configuration:

```python
@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display  = ("sku", "name", "product_link", "selling_unit",
                     "base_units", "moq", "current_price", "available", "status")
    list_filter   = ("status", "selling_unit", "product__category", "product__brand")
    search_fields = ("sku", "barcode", "name", "product__name")
    list_select_related = ("product", "product__brand")
    readonly_fields = ("base_units", "public_id", "created_at", "updated_at")
    actions = ("activate", "deactivate", "export_csv")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "product", "product__brand"
        ).prefetch_related("inventory_items", "prices")
```

Applied across the board:

- `list_select_related` / `prefetch_related` on every admin — an unoptimised admin
  list is the most common source of 5-second internal page loads.
- `readonly_fields` for generated and audit columns.
- `raw_id_fields` for high-cardinality FKs (variant, order, user) so the page does
  not render a 20,000-option select.
- `date_hierarchy` on orders, movements and audit log.
- Inlines: variants and images under product; items under order (read-only);
  lines under stock adjustment.
- **Read-only admins** for `order_item`, `inventory_movement`, `payment_attempt`,
  `webhook_event` and `audit_log`. These are historical records; editing them is
  never legitimate.

### Guardrails

`has_delete_permission` returns `False` for orders, payments, invoices and movements.
Records are archived or reversed, never deleted — a deleted paid order is an
unauditable hole in the accounts.

---

## 3. Dashboard

The frontend already renders this shell at `/vendor-dashboard` — a donut, a line
chart and two tables. It becomes the D2R staff dashboard.

**Row 1 — today**
`Orders today · Revenue today · Pending payment · Awaiting dispatch`, each with a
period-over-period delta.

**Row 2 — the donut** (already built)
Order mix: Recent · Pending Payment · Processing · Completed.

**Row 3 — the line chart** (already built)
Revenue over 12 months, with a comparison series for the prior period.

**Row 4 — action queues.** The part that makes the dashboard a workspace rather than
a report. Each is a filtered list with the action inline:

| Queue | Action |
| --- | --- |
| Orders awaiting dispatch | Create shipment |
| Payments pending verification > 15 min | Verify now |
| Customers awaiting approval | Approve / reject |
| Low-stock SKUs | Create purchase order |
| Failed webhooks | Retry |
| Refunds awaiting approval | Approve / decline |

**Row 5 — trending products and recent orders** (already built).

`GET /admin/dashboard/summary` serves rows 1–3 in one call; the queues are separate
endpoints so they can poll independently.

---

## 4. Catalogue management

The workflow D2R staff repeat most: onboarding a vendor's range.

```
Vendor sends a price list
        │
        ├─ Bulk import (CSV/XLSX)  ── the normal path
        │     upload → validate → review errors → apply
        │
        └─ Manual entry ── for one-off SKUs
              product → variants → prices → images → publish
```

### Product form

Grouped, not one long form:

1. **Basics** — name, slug (auto, editable), category, brand, vendor, status
2. **Description** — short + long, sanitised rich text
3. **Specifications** — key/value rows writing to `product.attributes` JSONB; this
   is the PDP spec table the frontend already renders
4. **Variants** — inline table: SKU, name, selling unit, units/pack, packs/case,
   MOQ, increment, weight, barcode. `base_units` computes live.
5. **Pricing** — per variant, per customer group, with volume breaks and validity
   windows. Shows the current effective price and the next scheduled change.
6. **Images** — drag-drop to S3, reorder, set primary, alt text **required**
7. **Inventory** — opening stock per warehouse (creates a `receipt` movement)
8. **SEO** — meta title/description with a SERP preview
9. **Restrictions** — restricted flag, restriction note, permitted zones

### Bulk operations

| Operation | Notes |
| --- | --- |
| Import products | Two-phase, dry-run first (`03-flows.md` §9) |
| Import prices | Same, with an effective-date so a rise can be scheduled |
| Import stock | Creates movements with a reason, never a silent overwrite |
| Export | Any filtered list → CSV/XLSX |
| Bulk publish / archive | Multi-select with a confirmation count |
| Bulk category move | With a preview of affected SKUs |

**Every import is dry-run by default.** The operator sees `4,812 rows valid, 188
errors` and downloads the error CSV before anything is written.

---

## 5. Inventory console

The screen an inventory manager keeps open.

**Stock list** — SKU, product, warehouse, on hand, reserved, available, incoming,
reorder point, value. Filters: warehouse, category, brand, vendor, low stock, out of
stock, overstocked. Inline quantity edit is **not** offered — every change goes
through an adjustment with a reason (PRD OPS-03).

**Adjustment flow**

```
New adjustment
  ├ type: count | damage | expiry | theft | correction | receipt
  ├ reason: free text, REQUIRED
  ├ lines: SKU, current qty, new qty, delta (computed), unit cost
  ├ save as draft ─────────────▶ nothing has moved
  └ apply (permission-gated) ──▶ movements written, stock changes, audit logged
```

Draft-then-apply matters for stock takes: a warehouse count is entered over hours,
then committed once.

**Movement history** — the append-only ledger, filterable by SKU, type, date, user,
reference. Every row links to its source order or adjustment. This is what answers
*"where did 40 cases go?"* and it is the reason `inventory_movement` is never updated.

**Low-stock report** — below reorder point, with days-of-cover computed from the
trailing 30-day sales rate, and a one-click purchase-order draft.

---

## 6. Order management

### Order list

Columns: order number, business account, placed, status, payment, fulfilment, total,
zone. Saved views for the queues in §3.

Filters: status, payment status, fulfilment status, date range, zone, customer group,
value band, contains-restricted, free-text over order number / business name / SKU.

### Order detail

Left: items with snapshot names and SKUs, quantities, per-line fulfilment progress.
Right rail: customer with account status and order count, delivery address with zone,
payment attempts (all of them, with provider references), shipments, timeline.

Actions, permission-gated: change status · create shipment · add internal note ·
cancel · request refund · resend confirmation · download invoice · print pick list.

**The timeline is the audit log filtered to this order** — status changes, payment
events, notes, shipments, refunds, each with actor and timestamp. Support staff
answer "what happened to my order?" from one place.

### Fulfilment board

Kanban across `Paid → Processing → Dispatched → Delivered`. Drag to transition,
with the state machine rejecting illegal moves. Bulk-select to print pick lists.
Built for the ops team processing the day's orders in one sitting.

---

## 7. Payments and reconciliation

**Payment list** — every attempt, not just successes. Provider, reference, amount,
status, channel, fees, timestamp. The failures are where the diagnostics live.

**Reconciliation view** (PRD PAY-08) — the finance screen:

```
Date range │ Provider │ Status

Order          Provider ref        Amount      Fees     Net      Status    Verified
D2R-2026-417   pay_9f2a1c…      363,121.00  5,446.82  357,674  success   14:22:07
D2R-2026-418   pay_7c1b8e…      184,500.00       —          —  failed    —
                                ───────────────────────────────
                     Totals     547,621.00  5,446.82  357,674

⚠ 2 exceptions
   • D2R-2026-421 — verified 250,000.00, order total 240,000.00  [review]
   • D2R-2026-419 — payment successful, order still pending_payment  [reconcile]
```

Exceptions are surfaced first. A payment that verified for the wrong amount, or a
successful payment whose order never transitioned, are the two failures that lose
money quietly.

**Refunds** — request captures order, lines, amount, reason and a restock flag.
Approval is a **different person** (`04-security.md` §2.3). The provider call happens
after approval, and the refund tracks to `completed` via webhook.

---

## 8. Customer management

**List** — account number, business name, type, status, orders, lifetime value,
zone, registered date. Filter by status, type, group, zone, has-ordered.

**Approval queue** — the gate on new accounts. Shows business name, type, CAC/TIN,
contact, address and resolved delivery zone. Approve sets `can_view_prices` and
`can_order`; reject requires a reason that is emailed.

**Account detail** — profile, members and their roles, addresses, order history with
totals, payment history, notes. Actions: approve · suspend (with reason) · reset
password · set customer group · set credit limit (Phase 2) · assign rep (Phase 2) ·
toggle restricted-product eligibility · impersonate.

**Impersonation** is read-only, time-boxed to 30 minutes, requires a reason, and
writes a prominent `audit_log` entry. Support cannot place an order as a customer.

---

## 9. Reports

All exportable to CSV/XLSX, all date-ranged, all generated in the `bulk` queue with
an email link when large.

| Report | Contents |
| --- | --- |
| Sales summary | Revenue, orders, AOV, by day/week/month |
| Sales by product | Units, revenue, margin (needs `unit_cost`) |
| Sales by category / brand / vendor | Same, grouped |
| Sales by customer | Top accounts, frequency, recency |
| Sales by zone | Revenue and delivery cost per axis |
| Inventory valuation | On-hand × unit cost, by warehouse |
| Stock movement | Full ledger for a period |
| Slow-moving stock | No sales in N days, with value at risk |
| Payment reconciliation | Per §7 |
| Customer acquisition | Registrations, approvals, first-order conversion |
| Abandoned carts | Value, age, contents |
| Zero-result searches | From `search_query_log` — **what customers want that D2R does not stock** |

The last one is the most commercially useful and the cheapest to build; it turns the
search log into a buying signal for the vendor team.

---

## 10. Settings

Runtime configuration, no deploy required, every change audited:

| Group | Keys |
| --- | --- |
| Accounts | `require_approval`, `hide_prices_until_approved`, `allow_self_registration` |
| Checkout | `reservation_ttl_minutes`, `min_order_value`, `allow_guest_checkout` (false) |
| Payments | `active_gateway`, `paystack_enabled`, `flutterwave_enabled`, `bank_transfer_enabled` |
| Delivery | `free_delivery_above`, `default_zone`, `block_unsupported_zones` |
| Tax | `default_tax_class`, `prices_include_tax` |
| Restricted | `require_acknowledgement`, `acknowledgement_text` |
| Notifications | Per-template on/off per channel |
| Store | Trading hours, order cut-off time, holiday closures |

Several of these are the PRD §17 open questions. Making them settings rather than
constants means launch is not blocked on a final answer, and a change of mind is a
click rather than a release.

---

## 11. What the existing frontend gives us

The template already ships usable admin shell components:

| Built | Becomes |
| --- | --- |
| `/vendor-dashboard` donut + line chart (ApexCharts) | Dashboard rows 2–3 |
| Dashboard product/order tables | Trending products, recent orders |
| `/vendor-account` settings form | Staff profile |
| Order status badges | Fulfilment board cards |
| Filter sidebar, range slider, nice-select | Admin list filters |
| `Carousel`, `Accordion`, `TemplateRangeSlider` | Reusable across admin screens |

The chart components are already dynamically imported and admin-scoped, so they add
nothing to the storefront bundle.

**Still to build:** data tables with server-side sort/filter/paginate, drag-drop
upload, the kanban board, the import wizard, and the bulk-select toolbar.
