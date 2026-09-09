# Procurement, Goods Receipt & Batch Tracking

Two gaps in the original specification, both material for an FMCG re-distributor.

`00-overview.md` through `08` modelled everything **outbound** — catalogue, orders,
payment, dispatch. But D2R's business is buying from Beiersdorf, Kraft Heinz, Givanas
and Morning Star and re-distributing. **Inbound was missing entirely**, and so was
**batch and expiry tracking** — which for food, beverages and cosmetics is not
optional.

---

## Part 1 — Why batch tracking is mandatory here

Every category in D2R's range has a shelf life:

| Range | Shelf life | Consequence of no batch tracking |
| --- | --- | --- |
| Kraft Heinz ketchup, mayonnaise | 12–24 months | Wholesale buyers reject short-dated stock |
| O&B beef jerky, OBE sauces | 6–12 months | Write-offs; food safety exposure |
| Vektro Chapman, juices | 6–12 months | Same |
| NIVEA, Givanas cosmetics | 24–36 months + PAO | Regulatory: cosmetics carry expiry marking |
| Colavita oils | 18–24 months | Rancidity claims |

Three things break without it:

1. **You cannot do FEFO.** First-Expired-First-Out is the standard picking rule in
   FMCG. Without batches you ship whatever is nearest the door, and the oldest stock
   quietly expires on the racks.
2. **You cannot run a recall.** If Beiersdorf recalls lot `L4421`, you must be able
   to answer *"which shops received it"* within hours. Without batch-to-order
   traceability that answer does not exist.
3. **Buyers reject deliveries.** A supermarket buyer checks the date on the case. If
   40% of remaining life is gone, they refuse it — and you have already paid to put it
   on a van.

`quantity_on_hand` as a single integer per SKU cannot express *"46 cases: 12 expiring
in March, 34 in September"*. That is the change.

### The model

```
inventory_item  (variant × warehouse)     ← running totals, unchanged
      │
      └── inventory_batch  (variant × warehouse × lot)
              lot_number, expiry_date, quantity_on_hand, quantity_reserved,
              unit_cost, received_at, supplier_batch_ref, status
```

`inventory_item.quantity_on_hand` becomes the **sum of its batches** — maintained by
trigger, so the existing checkout, reservation and availability logic in `03-flows.md`
keeps working untouched. Batches add a layer beneath; they do not rewrite what is above.

### `inventory_batch`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `inventory_item_id` | FK → inventory_item cascade | |
| `variant_id` | FK → product_variant restrict | denormalised |
| `warehouse_id` | FK → warehouse restrict | |
| `lot_number` | varchar(60) not null | manufacturer's lot |
| `supplier_batch_ref` | varchar(60) null | their internal ref |
| `manufactured_date` | date null | |
| `expiry_date` | date null | null for non-perishables |
| `best_before_date` | date null | distinct from expiry for food |
| `quantity_received` | integer not null | never changes — the audit anchor |
| `quantity_on_hand` | integer not null | |
| `quantity_reserved` | integer not null default 0 | |
| `quantity_available` | integer generated | `on_hand - reserved` |
| `unit_cost` | numeric(14,2) null | **per batch** — this is what makes COGS real |
| `goods_receipt_id` | FK → goods_receipt null | where it came from |
| `status` | varchar(16) not null default `'available'` | `available` \| `quarantine` \| `expired` \| `recalled` \| `depleted` |
| `received_at` | timestamptz not null | |

```
uq_batch          unique (inventory_item_id, lot_number)
idx_batch_fefo    (variant_id, warehouse_id, expiry_date)
                  where status='available' and quantity_available > 0
idx_batch_expiring (expiry_date) where status='available'
ck_batch_qty      check (quantity_on_hand >= 0 and quantity_reserved <= quantity_on_hand)
```

`idx_batch_fefo` is the index that makes FEFO allocation a single ordered read.

### FEFO allocation

Reservation (`03-flows.md` §4 step 10) gains a batch-selection step:

```sql
select id, quantity_available
from inventory_batch
where variant_id = %s and warehouse_id = %s
  and status = 'available'
  and quantity_available > 0
  and (expiry_date is null or expiry_date > current_date + interval '%s days')
order by expiry_date asc nulls last, received_at asc
for update;
```

The `%s days` guard is **minimum remaining shelf life** — a per-category setting.
Stock inside that window is not sold; it is flagged for markdown or write-off. This is
the rule that stops you shipping a case with three weeks left to a shop that needs
three months.

One order line can draw from several batches. `order_item_batch` records which:

```
order_item_batch (order_item_id, inventory_batch_id, quantity)
```

That table is the recall trail. *Which shops got lot L4421* becomes one join.

### Expiry lifecycle

| Days to expiry | Automatic action |
| --- | --- |
| 90 | Appears in the expiring-stock report |
| 60 | Ops alert; suggest promotion or bundle |
| 30 | Blocked from new orders (setting per category) |
| 0 | `status = 'expired'`, written off, `inventory_movement` type `damage` |

Run by Celery beat daily. Every transition writes a movement and an audit entry —
expired stock is a real cost and must be visible in the P&L, not silently vanish.

---

## Part 2 — Procurement

D2R currently has a `vendor` table and nothing that buys from it. `quantity_incoming`
exists on `inventory_item` with nothing to populate it.

### Flow

```
Low stock / forecast
      │
   ┌──▼───────────────┐
   │ purchase_order   │  draft → approved → sent → partially_received → received
   │ (to vendor)      │
   └──┬───────────────┘
      │
   ┌──▼───────────────┐
   │ goods_receipt    │  what actually arrived at the gate
   │ + inspection     │  quantity, lot numbers, expiry dates, damage
   └──┬───────────────┘
      │
      ├─▶ inventory_batch created per lot
      ├─▶ inventory_movement (type=receipt)
      └─▶ inventory_item.quantity_on_hand += received
      │
   ┌──▼───────────────┐
   │ supplier_invoice │  three-way match: PO ↔ receipt ↔ invoice
   └──────────────────┘
```

The **three-way match** is the control that stops D2R paying for goods it never
received, or paying twice. It is standard in distribution and cheap to build once the
three tables exist.

### `purchase_order`

| Column | Type | Notes |
| --- | --- | --- |
| `po_number` | varchar(24) unique not null | `D2R-PO-2026-0142` |
| `vendor_id` | FK → vendor restrict | |
| `warehouse_id` | FK → warehouse restrict | delivery destination |
| `status` | varchar(24) not null | `draft` \| `pending_approval` \| `approved` \| `sent` \| `partially_received` \| `received` \| `cancelled` |
| `currency` | char(3) not null default `'NGN'` | |
| `subtotal`, `tax_total`, `shipping_cost`, `other_charges`, `grand_total` | numeric(14,2) | |
| `expected_date` | date null | |
| `payment_terms_days` | smallint null | copied from vendor |
| `created_by_id`, `approved_by_id` | FK → user | **must differ** |
| `approved_at`, `sent_at`, `received_at` | timestamptz null | |
| `notes` | text null | |

With `purchase_order_line (po_id, variant_id, quantity_ordered, quantity_received, unit_cost, line_total, expected_expiry_date)`.

### `goods_receipt`

| Column | Type | Notes |
| --- | --- | --- |
| `grn_number` | varchar(24) unique not null | |
| `purchase_order_id` | FK → purchase_order restrict | |
| `warehouse_id` | FK → warehouse restrict | |
| `delivery_note_ref` | varchar(60) null | vendor's document |
| `status` | varchar(16) not null | `draft` \| `inspecting` \| `accepted` \| `partially_accepted` \| `rejected` |
| `received_by_id`, `inspected_by_id` | FK → user | |
| `received_at`, `accepted_at` | timestamptz | |

With `goods_receipt_line (grn_id, po_line_id, variant_id, quantity_received,
quantity_accepted, quantity_rejected, rejection_reason, lot_number, expiry_date,
manufactured_date, unit_cost)`.

**The receipt line is where lot number and expiry enter the system.** Nothing else
creates a batch. That single choke point is what keeps traceability honest.

### `supplier_invoice`

| Column | Type | Notes |
| --- | --- | --- |
| `invoice_number` | varchar(60) not null | vendor's number |
| `vendor_id` | FK → vendor restrict | |
| `purchase_order_id` | FK → purchase_order null | |
| `goods_receipt_id` | FK → goods_receipt null | |
| `invoice_date`, `due_date` | date | |
| `subtotal`, `tax_total`, `total`, `amount_paid` | numeric(14,2) | |
| `status` | varchar(16) not null | `pending` \| `matched` \| `disputed` \| `approved` \| `paid` |
| `match_variance` | numeric(14,2) generated | invoice total − receipt value |
| `approved_by_id` | FK → user null | |

```
uq_supplier_invoice unique (vendor_id, invoice_number)
idx_si_unpaid       (due_date) where status in ('approved','matched') and amount_paid < total
```

`uq_supplier_invoice` prevents paying the same vendor invoice twice — the most common
accounts-payable error.

### Landed cost

For importers like Morning Star (Colavita, Amalfi), the purchase price is not the
cost. Duty, clearing, freight and haulage are.

```
landed_unit_cost = unit_cost
                 + (freight + duty + clearing + handling) × (line_value / po_value)
```

Apportioned across PO lines by value and written to `inventory_batch.unit_cost` at
receipt. Without it, gross margin is overstated on every imported line — and margin
is the number the vendor team makes buying decisions on.

---

## Part 3 — What this unlocks

Reports that were impossible before, all now single queries:

| Report | Uses |
| --- | --- |
| True gross margin by SKU/brand/vendor | `inventory_batch.unit_cost` (landed) vs `order_item.unit_price` |
| Stock expiring in 30/60/90 days, with value at risk | `idx_batch_expiring` |
| Write-off analysis by category | expired movements |
| Recall trace: lot → shops | `order_item_batch` → order → business_account |
| Vendor performance: on-time, in-full, quality | PO expected vs GRN actual |
| Purchase price variance | PO unit cost vs invoice unit cost |
| Days inventory outstanding | batch received date vs sale date |
| Accounts payable ageing | `supplier_invoice.due_date` |

Vendor OTIF (on-time in-full) is the one that pays for itself. It turns *"Kraft Heinz
are always late"* from a feeling into a number you can negotiate with.

---

## Part 4 — Build impact

| Milestone | Addition |
| --- | --- |
| M2 Catalogue | `+3 days` — batch fields on the variant form, minimum-shelf-life setting per category |
| M3 Inventory | `+1 week` — `inventory_batch`, FEFO allocation, expiry beat job, batch-aware adjustments |
| M5 Admin | `+1.5 weeks` — PO, goods receipt with lot capture, three-way match, supplier invoices |
| Reports | `+3 days` — margin, expiry, vendor OTIF |

**About 3 weeks total**, and it should be built at M3, not retrofitted. Adding batch
tracking to a system that already holds live stock means reconciling every existing
quantity to a lot that nobody recorded — a manual stock take of the entire warehouse.

---

## Part 5 — Open questions

Add to `07-delivery-plan.md` §1:

20. **Do you track lot numbers and expiry today?** If the warehouse already records
    them on paper, the model must match that practice.
21. Minimum remaining shelf life you will ship, by category?
22. Who approves a purchase order, and above what value?
23. Do you import directly (landed cost applies) or buy locally in NGN?
24. Is stock costed FIFO, weighted average, or standard cost?
25. Does the warehouse have barcode scanners, or is receipt keyed manually?

**20 and 21 are the ones to answer first** — they determine whether batch tracking is
built in M3 or deferred, and deferring is expensive.
