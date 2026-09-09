# Dispatch, Fleet & Delivery

D2R is not a shop that posts parcels. It runs a re-distribution fleet — the pitch
deck's *"Logistics & Delivery: timely and reliable delivery operations powered by
optimised re-distribution routes"* across five Lagos axes covering 2,500 VAN outlets,
500 key accounts and 60 wholesalers.

That makes dispatch a first-class module, not a status field on the order.

---

## 1. What this has to handle

| Reality | Requirement |
| --- | --- |
| Own vans and drivers | Fleet, driver assignment, vehicle capacity |
| Fixed route days per axis | Route templates, scheduled trips, cut-off times |
| Many drops per trip | Trip → many shipments, sequenced |
| Cash collected on delivery | **Cash reconciliation per driver per trip** |
| Part-delivered orders | Line-level delivery, shortages, rejections |
| Shop closed, owner absent | Failed attempts, reattempt policy |
| Disputes about what arrived | Proof of delivery — signature, photo, receiver name |
| Growth beyond own fleet | Third-party courier adapters |

The two that most e-commerce backends get wrong, and that matter most here, are
**cash-on-delivery reconciliation** and **line-level delivery outcomes**. A driver
returning with ₦2.4m in cash and eleven part-delivered orders is a normal Tuesday.

---

## 2. Model

Six tables on top of the `shipment` / `shipment_item` already specified in
`01-data-model.md` §8.

### `driver`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `user_id` | FK → user null | if the driver has a login for the driver app |
| `code` | varchar(20) unique not null | `DRV-014` |
| `full_name` | varchar(150) not null | |
| `phone` | varchar(32) not null | |
| `licence_number` | varchar(60) null | |
| `licence_expiry` | date null | compliance alerting |
| `home_zone_id` | FK → delivery_zone null | usual axis |
| `status` | varchar(16) not null default `'active'` | `active` \| `on_leave` \| `suspended` \| `inactive` |
| `cash_limit` | numeric(14,2) null | max COD a driver may hold |
| `notes` | text null | |

### `vehicle`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `code` | varchar(20) unique not null | `VAN-07` |
| `registration` | varchar(20) unique not null | plate |
| `vehicle_type` | varchar(20) not null | `van` \| `truck` \| `bike` \| `tricycle` |
| `capacity_kg` | numeric(9,2) null | |
| `capacity_volume_m3` | numeric(7,3) null | |
| `warehouse_id` | FK → warehouse | home base |
| `status` | varchar(16) not null default `'available'` | `available` \| `on_trip` \| `maintenance` \| `retired` |
| `insurance_expiry` / `roadworthiness_expiry` | date null | compliance alerting |

### `route`

A **template**, not an instance. "Ikorodu axis, Tuesdays and Fridays."

| Column | Type | Notes |
| --- | --- | --- |
| `code` | varchar(20) unique not null | `RT-IKD-A` |
| `name` | varchar(150) not null | |
| `zone_id` | FK → delivery_zone | |
| `days_of_week` | smallint[] not null | `{2,5}` = Tue, Fri |
| `cut_off_time` | time not null | order by this to make the next run |
| `default_driver_id` | FK → driver null | |
| `default_vehicle_id` | FK → vehicle null | |
| `max_stops` | smallint null | |
| `is_active` | boolean not null default true | |

Route templates are what let the storefront promise *"order before 4pm Monday for
Tuesday delivery"* without a human deciding it each time.

### `trip` — **the dispatch unit**

One van, one driver, one day, many drops.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `trip_number` | varchar(24) unique not null | `TRP-2026-0912-03` |
| `route_id` | FK → route null | null for an ad-hoc run |
| `warehouse_id` | FK → warehouse | |
| `driver_id` | FK → driver restrict | |
| `vehicle_id` | FK → vehicle restrict | |
| `scheduled_date` | date not null | |
| `status` | varchar(20) not null default `'planned'` | `planned` \| `loading` \| `dispatched` \| `in_progress` \| `completed` \| `cancelled` |
| `stop_count` | smallint not null default 0 | |
| `total_weight_kg` | numeric(9,2) null | capacity check |
| `total_value` | numeric(14,2) not null default 0 | goods on board |
| `cash_expected` | numeric(14,2) not null default 0 | sum of COD drops |
| `cash_collected` | numeric(14,2) not null default 0 | driver-declared |
| `cash_remitted` | numeric(14,2) not null default 0 | counted at cash office |
| `cash_variance` | numeric(14,2) generated | `remitted - expected` |
| `odometer_start` / `odometer_end` | integer null | |
| `departed_at` / `returned_at` | timestamptz null | |
| `dispatched_by_id` / `reconciled_by_id` | FK → user null | |
| `reconciled_at` | timestamptz null | |
| `notes` | text null | |

```
idx_trip_date    (scheduled_date, status)
idx_trip_driver  (driver_id, scheduled_date desc)
idx_trip_unrecon (scheduled_date) where status='completed' and reconciled_at is null
ck_trip_cash     check (cash_collected >= 0 and cash_remitted >= 0)
```

`idx_trip_unrecon` drives the finance queue: *trips that came back but whose cash has
not been counted.*

### `trip_stop`

A shipment's place in a trip's sequence, with its own outcome.

| Column | Type | Notes |
| --- | --- | --- |
| `trip_id` | FK → trip cascade | |
| `shipment_id` | FK → shipment restrict | |
| `sequence` | smallint not null | drop order |
| `status` | varchar(20) not null default `'pending'` | `pending` \| `arrived` \| `delivered` \| `partial` \| `failed` \| `rescheduled` |
| `eta` | timestamptz null | |
| `arrived_at` / `completed_at` | timestamptz null | |
| `cash_due` | numeric(14,2) not null default 0 | COD for this drop |
| `cash_received` | numeric(14,2) not null default 0 | |
| `receiver_name` | varchar(150) null | |
| `receiver_phone` | varchar(32) null | |
| `signature_url` | varchar(500) null | |
| `photo_url` | varchar(500) null | |
| `latitude` / `longitude` | numeric(9,6) null | captured at completion |
| `failure_reason` | varchar(40) null | see §5 |
| `failure_note` | text null | |
| `attempt_number` | smallint not null default 1 | |

```
uq_stop        unique (trip_id, shipment_id)
uq_stop_seq    unique (trip_id, sequence)
idx_stop_ship  (shipment_id)
ck_stop_cash   check (cash_received >= 0 and cash_received <= cash_due + 0.01)
```

### `delivery_exception`

Shortages, damages and rejections recorded **at the door**, per line. This is what
feeds returns and stock corrections without a phone call.

| Column | Type | Notes |
| --- | --- | --- |
| `trip_stop_id` | FK → trip_stop cascade | |
| `shipment_item_id` | FK → shipment_item restrict | |
| `exception_type` | varchar(24) not null | `short_delivered` \| `damaged` \| `rejected` \| `wrong_item` \| `expired` |
| `quantity` | integer not null | |
| `reason` | varchar(200) null | |
| `photo_url` | varchar(500) null | |
| `resolution` | varchar(24) null | `credit_note` \| `replace` \| `refund` \| `none` |
| `resolved_by_id` | FK → user null | |
| `resolved_at` | timestamptz null | |

### `courier_account` — third-party path (Phase 2)

| Column | Type |
| --- | --- |
| `code`, `name` | varchar |
| `provider` | varchar(24) — `gig`, `kwik`, `sendbox`, `dhl`, `manual` |
| `api_credentials_ref` | varchar(120) — **secret manager key, not the secret** |
| `supports_cod` | boolean |
| `is_active` | boolean |

`shipment` already carries `carrier` and `tracking_reference`; adding a courier means
implementing an adapter behind the same `DeliveryProvider` interface used by the own
fleet. No schema change.

---

## 3. Dispatch flow

```
Paid orders
    │
    ├─ 1. ALLOCATE      resolve zone → route → next trip date (respects cut-off)
    │                    create shipment, reserve a trip_stop
    │
    ├─ 2. PLAN          ops opens the dispatch board for tomorrow
    │                    drag shipments onto trips, sequence the drops
    │                    capacity check: weight/volume vs vehicle
    │
    ├─ 3. LOAD          pick list per trip, scan out
    │                    trip.status = loading → dispatched
    │                    shipment.status = dispatched, order.fulfilment = dispatched
    │                    cash_expected = Σ trip_stop.cash_due
    │
    ├─ 4. DELIVER       per stop, in the driver app:
    │                    arrive → capture receiver, signature/photo
    │                    confirm lines, record exceptions
    │                    collect cash → cash_received
    │                    stop.status = delivered | partial | failed
    │
    ├─ 5. RETURN        odometer, undelivered goods scanned back in
    │                    trip.status = completed
    │
    └─ 6. RECONCILE     cash office counts → cash_remitted
                         variance ≠ 0 → finance exception
                         exceptions → credit notes / replacements
                         stock corrections written as movements
```

### Allocation rule

```
order.delivery address
   → delivery_zone_area match (postal → lga → city → state, most specific wins)
   → zone
   → active routes for that zone
   → next route day where now() < cut_off_time, else the day after
   → trip for that route + date (created if absent)
```

If no zone matches, checkout already rejected the order with
`422 unsupported_delivery_area` (`03-flows.md` §4) — dispatch never sees an
undeliverable address.

---

## 4. Cash on delivery

The requirement most likely to be underestimated. In Nigerian wholesale a large share
of value arrives as cash in a van.

**Model.** COD is a payment method whose `payment_attempt.provider = 'cash_on_delivery'`,
created at checkout in `pending`, and only moved to `successful` when the cash office
confirms remittance — **not** when the driver says they collected it.

```
order paid?                      no  — order.payment_status = pending
stock reserved?                  yes — COD orders reserve at dispatch, not at payment
driver collects ₦363,121         →   trip_stop.cash_received
driver declares total            →   trip.cash_collected
cash office counts               →   trip.cash_remitted
cash_variance = remitted - expected
   0        → payment_attempts → successful, orders → paid, invoices issued
   ≠ 0      → trip stays unreconciled, finance exception raised, per-stop drill-down
```

**Controls**

- `driver.cash_limit` — a trip whose `cash_expected` exceeds it needs approval.
- A driver cannot be assigned a new trip while an old one is unreconciled beyond N
  days (a setting).
- `cash_variance` is a generated column, so a shortfall cannot be edited away.
- Every cash figure change writes to `audit_log`.
- COD availability is per zone and per customer: `business_account.cod_allowed`,
  defaulting off for new accounts.

Prepaid (Paystack) orders skip all of this — the trip's `cash_expected` is simply 0.

---

## 5. Failed and partial deliveries

`trip_stop.failure_reason` is a closed set so the data is analysable:

`shop_closed` · `customer_absent` · `refused_delivery` · `payment_unavailable` ·
`wrong_address` · `access_denied` · `vehicle_breakdown` · `security_incident` ·
`weather` · `out_of_time`

**Reattempt policy** (settings-driven):

| Attempt | Action |
| --- | --- |
| 1 | Auto-reschedule onto the next trip for that route |
| 2 | Reschedule + support call to the customer |
| 3 | Return to warehouse, restock, order → `returned`, refund if prepaid |

Each attempt creates a **new** `trip_stop` with `attempt_number` incremented and the
same shipment. History is preserved; the shipment is not silently reused.

**Partial delivery** sets `trip_stop.status = 'partial'`, writes
`delivery_exception` rows per affected line, and increments
`order_item.quantity_fulfilled` by what actually landed. The order reaches
`delivered` only when every line is fully accounted for — delivered, returned or
credited.

---

## 6. Driver app

Not a native app at launch. A **mobile web view** at `/driver`, authenticated with a
short-lived token, designed for a cheap Android phone on a patchy 3G connection.

| Requirement | Approach |
| --- | --- |
| Works offline | Service worker caches the manifest; stop completions queue in IndexedDB and sync on reconnect |
| Low data | Manifest is JSON with thumbnail-only images; no product photography |
| One-handed | Large targets, minimal typing, camera for signature and photo |
| Trustworthy | GPS captured at completion; timestamps are server-assigned on sync |

**Endpoints** (`/api/v1/driver/`, driver-scoped, no access to catalogue or other trips):

```
GET  /trips/today                  manifest: stops, addresses, phones, lines, cash due
POST /stops/{id}/arrive            timestamp + GPS
POST /stops/{id}/complete          receiver, signature, photo, lines, cash received
POST /stops/{id}/fail              reason, note, photo
POST /trips/{id}/return            odometer, declared cash
```

`POST /stops/{id}/complete` requires an `Idempotency-Key` — a driver on a bad
connection will tap submit more than once, and that must never double-deliver a stop
or double-count cash.

---

## 7. Customer-facing tracking

No live GPS breadcrumb. A shop owner wants a **delivery window and a phone number**,
not a moving dot.

`GET /account/orders/{n}/tracking`

```json
{
  "status": "out_for_delivery",
  "scheduled_date": "2026-09-12",
  "window": { "from": "09:00", "to": "13:00" },
  "stop_position": 4,
  "stops_ahead": 3,
  "driver": { "name": "Emeka O.", "phone": "+234801…", "vehicle": "VAN-07" },
  "timeline": [
    { "at": "2026-09-11T16:40:00Z", "event": "Order packed" },
    { "at": "2026-09-12T07:15:00Z", "event": "Dispatched from Ikorodu" },
    { "at": "2026-09-12T09:02:00Z", "event": "Out for delivery" }
  ]
}
```

Driver name and phone are exposed only while the trip is in progress, and the number
is a masked relay where the telephony provider supports it.

---

## 8. Dispatch board

The screen the logistics coordinator runs the day from. Adds to `06-admin-ops.md`.

```
Date: Fri 12 Sep        Warehouse: Ikorodu

UNASSIGNED (14)          TRP-…-01 Kosofe      TRP-…-02 Ikorodu
┌──────────────────┐     Driver: Emeka        Driver: Bola
│ D2R-2026-000418  │     VAN-07 · 8/12 stops  VAN-03 · 11/12 stops
│ Surulere · 42kg  │     ┌──────────────────┐ ┌──────────────────┐
│ ₦184,500 · COD   │     │ 1 D2R-…-401  ✓   │ │ 1 D2R-…-410  ✓   │
├──────────────────┤     │ 2 D2R-…-403  ✓   │ │ 2 D2R-…-411  ⚠   │
│ D2R-2026-000419  │     │ 3 D2R-…-407  ●   │ │ 3 D2R-…-412      │
│ Yaba · 18kg      │     └──────────────────┘ └──────────────────┘
│ ₦92,000 · Paid   │     Load 340/800kg       Load 690/800kg
└──────────────────┘     Cash due ₦1.2m       Cash due ₦2.4m
```

- Drag unassigned shipments onto a trip; drag within a trip to resequence.
- Live capacity bar; blocks over-loading against `vehicle.capacity_kg`.
- Cash-due total per trip against `driver.cash_limit`.
- Bulk actions: auto-assign by zone, print all pick lists, dispatch trip.
- Live stop status: ✓ delivered · ⚠ exception · ● in progress.

Supporting queues on the dashboard:

| Queue | Why it matters |
| --- | --- |
| Unassigned shipments past cut-off | Orders that will miss their promised day |
| Trips returned, cash not reconciled | Money outstanding with drivers |
| Failed stops awaiting reschedule | Customers waiting without knowing |
| Delivery exceptions unresolved | Credit notes owed |
| Vehicle/licence documents expiring | Compliance |

---

## 9. Reports

| Report | Use |
| --- | --- |
| Delivery performance by route/driver | On-time %, first-attempt success rate |
| Cost per drop by zone | Delivery fees vs actual cost — is a zone profitable? |
| Cash reconciliation by driver | Variance trend; the fraud and error signal |
| Failed delivery analysis | Reason breakdown by zone and time of day |
| Exception rate by product | Damage-prone SKUs, packaging problems |
| Vehicle utilisation | Load factor, idle capacity |
| Route density | Drops per trip per axis — where to add a van |

Route density and cost-per-drop are the two that inform expansion decisions, and both
come free once trips are modelled properly.

---

## 10. Build sequence

Fits inside the milestones in `07-delivery-plan.md`.

| Phase | Scope | Milestone |
| --- | --- | --- |
| **1 — Launch** | Zones, rates, shipments, manual dispatch from the order list, PDF pick lists, manual delivery confirmation | M5 |
| **2 — Fleet** | Drivers, vehicles, routes, trips, dispatch board, driver web app, proof of delivery | M5–M6 |
| **3 — Cash** | COD payment method, per-trip reconciliation, finance queue, variance reporting | M6 |
| **4 — Optimisation** | Capacity planning, drop sequencing, ETA windows, customer tracking | Post-launch |
| **5 — Third party** | Courier adapters for zones outside own-fleet coverage | Phase 2 |

**Phase 3 is not optional if D2R takes cash on delivery**, and it is the phase most
often deferred and then bolted on badly. If cash is part of the model at launch,
build it at launch.

---

## 11. Open questions for D2R

Add to `07-delivery-plan.md` §1:

12. Is delivery own-fleet only, or third-party in some zones?
13. **Is cash on delivery offered?** If so, which accounts and which zones?
14. Fixed route days per axis, or dispatch on demand?
15. Order cut-off time for next-day delivery?
16. Is proof of delivery signature, photo, or both?
17. Reattempt policy and who bears the cost of a failed delivery?
18. Do drivers get logins, or does ops record outcomes on their behalf?
19. Driver cash-holding limit and remittance frequency?

13 is the big one. It changes the payment model, the finance workflow and the
security posture, and it cannot be retrofitted cleanly.
