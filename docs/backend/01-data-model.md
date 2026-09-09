# Data Model

PostgreSQL 16. 67 tables across 14 domains.

**Conventions used throughout**

- Primary keys are `bigserial` internally; every externally-visible row also has a
  `public_id uuid` so sequential IDs never leak enumerable business volume.
- `created_at`, `updated_at` are `timestamptz not null default now()`.
- Money is `numeric(14,2)`. Never float. Currency is stored per-row alongside it.
- Soft delete is `archived_at timestamptz null` — used only where history matters
  (products, prices). Everything else deletes for real.
- Every table that a human can change has a matching `audit_log` entry (§11).
- `citext` is used for emails so lookup is case-insensitive without `lower()` scans.

---

## 1. Identity & access

### `user`

Custom user model — email is the identifier, there is no username.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | default `gen_random_uuid()` |
| `email` | citext unique not null | login identifier |
| `password` | varchar(128) not null | Argon2id |
| `first_name` | varchar(100) not null | |
| `last_name` | varchar(100) not null | |
| `phone` | varchar(32) null | E.164, `+234...` |
| `user_type` | varchar(16) not null | `customer` \| `staff` |
| `is_active` | boolean not null default true | |
| `is_email_verified` | boolean not null default false | |
| `email_verified_at` | timestamptz null | |
| `last_login_at` | timestamptz null | |
| `failed_login_count` | smallint not null default 0 | lockout counter |
| `locked_until` | timestamptz null | |
| `mfa_secret` | varchar(64) null | TOTP, **staff only** |
| `mfa_enabled` | boolean not null default false | |
| `created_at` / `updated_at` | timestamptz | |

```
idx_user_email          unique (email)
idx_user_type_active    (user_type, is_active)
```

Staff never share a login with a customer account: `user_type` is immutable after
creation and enforced by a check constraint on the admin path.

### `business_account`

The wholesale customer. **This is the entity that orders, not the user.**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `account_number` | varchar(20) unique not null | human reference, e.g. `D2R-C-00417` |
| `business_name` | varchar(200) not null | |
| `business_type` | varchar(32) not null | `retailer` \| `wholesaler` \| `supermarket` \| `chain` \| `open_market` \| `neighbourhood` \| `other` |
| `registration_number` | varchar(64) null | CAC number |
| `tax_id` | varchar(64) null | TIN |
| `primary_contact_name` | varchar(150) not null | |
| `primary_email` | citext not null | |
| `primary_phone` | varchar(32) not null | |
| `status` | varchar(16) not null default `'pending'` | `pending` \| `approved` \| `suspended` \| `rejected` \| `closed` |
| `approved_at` | timestamptz null | |
| `approved_by_id` | FK → user null | |
| `rejection_reason` | text null | |
| `can_view_prices` | boolean not null default false | PRD §17 open question — configurable |
| `can_order` | boolean not null default false | |
| `customer_group_id` | FK → customer_group null | tier pricing (Phase 2) |
| `credit_limit` | numeric(14,2) null | Phase 2 |
| `payment_terms_days` | smallint null | Phase 2 |
| `assigned_rep_id` | FK → user null | Phase 2 sales rep |
| `delivery_zone_id` | FK → delivery_zone null | default zone |
| `restricted_products_allowed` | boolean not null default false | alcohol eligibility |
| `internal_notes` | text null | staff-only |
| `created_at` / `updated_at` | timestamptz | |

```
idx_ba_status            (status)
idx_ba_name_trgm         gin (business_name gin_trgm_ops)   -- admin search
idx_ba_account_number    unique (account_number)
idx_ba_group             (customer_group_id)
```

**Why separate from `user`:** a shop may have an owner, a buyer and an accountant
who all need logins against the same account and the same order history. Modelling
the business as the customer is what makes B2B work; it is the mistake most B2C
carts make when retrofitted.

### `business_account_member`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `business_account_id` | FK → business_account cascade | |
| `user_id` | FK → user cascade | |
| `role` | varchar(16) not null | `owner` \| `buyer` \| `viewer` |
| `is_default` | boolean not null default false | user's active account |
| `invited_by_id` | FK → user null | |
| `joined_at` | timestamptz not null | |

```
uq_bam                  unique (business_account_id, user_id)
idx_bam_user            (user_id)
```

`viewer` can browse and see prices but cannot place orders — useful for a manager
who approves spend without executing it.

### `address`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `business_account_id` | FK → business_account cascade | |
| `label` | varchar(60) null | "Ikorodu shop" |
| `address_type` | varchar(16) not null | `billing` \| `delivery` \| `both` |
| `contact_name` | varchar(150) not null | |
| `contact_phone` | varchar(32) not null | |
| `line1` | varchar(200) not null | |
| `line2` | varchar(200) null | |
| `city` | varchar(100) not null | |
| `state` | varchar(100) not null | |
| `postal_code` | varchar(20) null | optional — Nigeria |
| `country` | char(2) not null default `'NG'` | ISO-3166-1 |
| `latitude` / `longitude` | numeric(9,6) null | future routing |
| `delivery_zone_id` | FK → delivery_zone null | resolved at save |
| `delivery_instructions` | text null | |
| `is_default_billing` | boolean not null default false | |
| `is_default_delivery` | boolean not null default false | |
| `archived_at` | timestamptz null | |

```
idx_addr_account         (business_account_id) where archived_at is null
uq_addr_default_billing  unique (business_account_id) where is_default_billing
uq_addr_default_delivery unique (business_account_id) where is_default_delivery
```

Partial unique indexes guarantee **exactly one** default of each kind without a
trigger.

### `staff_role` · `staff_role_permission` · `staff_assignment`

Django's `Group`/`Permission` tables are reused; these are the D2R-specific wrappers.

| `staff_role` | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `code` | varchar(40) unique not null | `admin`, `ops`, `catalogue`, `finance`, `support`, `sales` |
| `name` | varchar(100) not null | |
| `description` | text null | |
| `is_system` | boolean not null default false | cannot be deleted |

| `staff_assignment` | Type | Notes |
| --- | --- | --- |
| `user_id` | FK → user cascade | |
| `role_id` | FK → staff_role cascade | |
| `granted_by_id` | FK → user null | |
| `granted_at` | timestamptz not null | |

```
uq_staff_assignment  unique (user_id, role_id)
```

Full permission matrix in `04-security.md` §3.

### `auth_token`

Refresh tokens and password-reset/verification tokens. Access tokens are stateless
JWTs and are not stored.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `user_id` | FK → user cascade | |
| `token_hash` | char(64) not null | SHA-256 — **never the raw token** |
| `purpose` | varchar(24) not null | `refresh` \| `password_reset` \| `email_verify` \| `otp` |
| `expires_at` | timestamptz not null | |
| `used_at` | timestamptz null | single-use for reset/verify |
| `revoked_at` | timestamptz null | |
| `rotated_from_id` | FK → auth_token null | refresh rotation chain |
| `ip_address` | inet null | |
| `user_agent` | varchar(300) null | |

```
uq_token_hash        unique (token_hash)
idx_token_user_purp  (user_id, purpose) where revoked_at is null
idx_token_expiry     (expires_at) where revoked_at is null
```

Reuse of an already-rotated refresh token revokes the entire chain — standard
detection of a stolen token.

---

## 2. Catalogue

### `category`

Materialised-path tree. Fast subtree queries without recursive CTEs on the hot path.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `parent_id` | FK → category null | |
| `path` | varchar(255) not null | `0001.0007.0002` |
| `depth` | smallint not null | |
| `name` | varchar(150) not null | |
| `slug` | varchar(160) not null | |
| `description` | text null | |
| `image_url` | varchar(500) null | |
| `icon` | varchar(60) null | hugeicons class, matches frontend |
| `is_active` | boolean not null default true | |
| `is_restricted` | boolean not null default false | alcohol etc. — cascades to products |
| `sort_order` | integer not null default 0 | |
| `meta_title` / `meta_description` | varchar(200) / varchar(320) null | SEO |
| `product_count` | integer not null default 0 | denormalised, refreshed async |

```
uq_category_slug    unique (slug)
idx_category_path   (path text_pattern_ops)   -- subtree: path like '0001.0007.%'
idx_category_parent (parent_id, sort_order)
```

### `brand`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `name` | varchar(150) not null | |
| `slug` | varchar(160) unique not null | |
| `logo_url` | varchar(500) null | |
| `description` | text null | |
| `vendor_id` | FK → vendor null | the supplier that owns this brand |
| `is_active` | boolean not null default true | |

### `vendor`

**A supplier record, not a user.** D2R buys from these companies. They have no login.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `code` | varchar(20) unique not null | `VND-NIVEA` |
| `name` | varchar(200) not null | "Beiersdorf Nigeria" |
| `vendor_type` | varchar(24) not null | `manufacturer` \| `importer` \| `distributor` |
| `contact_name` | varchar(150) null | |
| `contact_email` | citext null | |
| `contact_phone` | varchar(32) null | |
| `address` | text null | |
| `payment_terms_days` | smallint null | D2R's terms *with the vendor* |
| `is_active` | boolean not null default true | |
| `notes` | text null | |

Used for purchase-order and margin reporting later. It never appears in a customer's
checkout.

### `product`

The merchandising object. **Not sellable** — variants are.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `name` | varchar(250) not null | |
| `slug` | varchar(260) unique not null | |
| `description` | text null | |
| `short_description` | varchar(500) null | |
| `category_id` | FK → category restrict | primary category |
| `brand_id` | FK → brand null | |
| `vendor_id` | FK → vendor null | |
| `tax_class_id` | FK → tax_class not null | |
| `status` | varchar(16) not null default `'draft'` | `draft` \| `active` \| `discontinued` \| `archived` |
| `is_restricted` | boolean not null default false | alcohol / age-gated |
| `restriction_note` | varchar(300) null | shown at checkout |
| `attributes` | jsonb not null default `'{}'` | spec table on the PDP |
| `search_vector` | tsvector | generated, GIN-indexed |
| `rating_avg` | numeric(3,2) not null default 0 | denormalised |
| `rating_count` | integer not null default 0 | |
| `meta_title` / `meta_description` | varchar | SEO |
| `published_at` | timestamptz null | |
| `archived_at` | timestamptz null | |

```
uq_product_slug        unique (slug)
idx_product_search     gin (search_vector)
idx_product_cat_status (category_id, status) where archived_at is null
idx_product_brand      (brand_id) where status = 'active'
idx_product_name_trgm  gin (name gin_trgm_ops)
idx_product_attrs      gin (attributes jsonb_path_ops)
```

`search_vector` is a generated column:

```sql
generated always as (
  setweight(to_tsvector('simple', coalesce(name,'')), 'A') ||
  setweight(to_tsvector('simple', coalesce(short_description,'')), 'B') ||
  setweight(to_tsvector('simple', coalesce(description,'')), 'C')
) stored
```

`attributes` holds the PDP spec table the frontend already renders (Brand, Model,
Dimensions, Weight, Warranty, Battery Type…). JSONB rather than EAV: specs are
read whole, never filtered on individually. The **filterable** facets are columns.

### `product_category` — secondary categories

```
product_id  FK → product cascade
category_id FK → category cascade
uq unique (product_id, category_id)
```

### `product_variant` — **the sellable SKU**

This is the single most important table. Every price, stock level and order line
points here.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `product_id` | FK → product cascade | |
| `sku` | varchar(60) unique not null | D2R's own SKU |
| `barcode` | varchar(40) null | EAN/UPC |
| `name` | varchar(200) not null | "NIVEA Men Cream 150ml — Case of 24" |
| `selling_unit` | varchar(12) not null | `unit` \| `pack` \| `case` |
| `units_per_pack` | integer not null default 1 | |
| `packs_per_case` | integer not null default 1 | |
| `base_units` | integer not null | generated: units in one sellable unit |
| `moq` | integer not null default 1 | minimum order quantity, **in selling units** |
| `order_increment` | integer not null default 1 | must order in multiples of |
| `max_order_qty` | integer null | anti-hoarding cap |
| `weight_kg` | numeric(8,3) null | delivery pricing |
| `length_cm` / `width_cm` / `height_cm` | numeric(7,2) null | |
| `variant_attributes` | jsonb not null default `'{}'` | `{"size":"150ml","colour":"blue"}` |
| `is_default` | boolean not null default false | shown first on the PDP |
| `status` | varchar(16) not null default `'active'` | `active` \| `inactive` \| `discontinued` |
| `low_stock_threshold` | integer not null default 0 | alerting |
| `archived_at` | timestamptz null | |

```
uq_variant_sku       unique (sku)
idx_variant_product  (product_id) where archived_at is null
idx_variant_status   (status)
idx_variant_barcode  (barcode) where barcode is not null
uq_variant_default   unique (product_id) where is_default
ck_variant_moq       check (moq >= 1 and order_increment >= 1)
ck_variant_units     check (units_per_pack >= 1 and packs_per_case >= 1)
```

`base_units` is generated:

```sql
base_units integer generated always as (
  case selling_unit
    when 'unit' then 1
    when 'pack' then units_per_pack
    when 'case' then units_per_pack * packs_per_case
  end
) stored
```

This is what makes "12 cases = 3,456 sachets" computable for inventory without the
application doing arithmetic it can get wrong.

### `product_image`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `product_id` | FK → product cascade | |
| `variant_id` | FK → product_variant null | variant-specific shot |
| `url` | varchar(500) not null | S3 key |
| `alt_text` | varchar(250) null | accessibility + SEO |
| `sort_order` | integer not null default 0 | |
| `is_primary` | boolean not null default false | |
| `width` / `height` | integer null | avoids CLS in Next/Image |

```
idx_pi_product      (product_id, sort_order)
uq_pi_primary       unique (product_id) where is_primary
```

### `attribute` · `attribute_value` — filterable facets only

| `attribute` | Type | Notes |
| --- | --- | --- |
| `code` | varchar(40) unique not null | `size`, `colour`, `pack_size` |
| `name` | varchar(100) not null | |
| `data_type` | varchar(16) not null | `text` \| `number` \| `boolean` \| `colour` |
| `is_filterable` | boolean not null default true | |
| `sort_order` | integer not null default 0 | |

| `attribute_value` | Type | Notes |
| --- | --- | --- |
| `attribute_id` | FK → attribute cascade | |
| `variant_id` | FK → product_variant cascade | |
| `value_text` | varchar(200) null | |
| `value_number` | numeric(12,3) null | |

```
uq_av             unique (attribute_id, variant_id)
idx_av_lookup     (attribute_id, value_text)
idx_av_variant    (variant_id)
```

Facet counts come from this table. Everything non-filterable stays in the JSONB
column — no EAV sprawl.

---

## 3. Pricing & tax

### `tax_class`

| Column | Type | Notes |
| --- | --- | --- |
| `code` | varchar(30) unique not null | `standard`, `zero`, `exempt` |
| `name` | varchar(100) not null | |
| `rate_percent` | numeric(5,2) not null | 7.50 for Nigerian VAT |
| `is_inclusive` | boolean not null default false | **PRD §17 open question** |
| `effective_from` | date not null | |
| `effective_to` | date null | rate changes keep history |

### `customer_group` — Phase 2 tier pricing

| Column | Type | Notes |
| --- | --- | --- |
| `code` | varchar(30) unique not null | `standard`, `gold`, `key_account` |
| `name` | varchar(100) not null | |
| `discount_percent` | numeric(5,2) not null default 0 | blanket fallback |
| `priority` | smallint not null default 0 | |

### `price`

Time-boxed and optionally group-scoped. Prices are **never updated in place** —
a change closes the old row and opens a new one, so an old order can always be
explained.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `variant_id` | FK → product_variant cascade | |
| `customer_group_id` | FK → customer_group null | null = list price |
| `currency` | char(3) not null default `'NGN'` | |
| `amount` | numeric(14,2) not null | per selling unit, tax-exclusive |
| `compare_at_amount` | numeric(14,2) null | strike-through "was" price |
| `min_quantity` | integer not null default 1 | volume break |
| `valid_from` | timestamptz not null default now() | |
| `valid_to` | timestamptz null | |
| `created_by_id` | FK → user null | |

```
idx_price_lookup  (variant_id, customer_group_id, min_quantity, valid_from desc)
ck_price_positive check (amount >= 0)
ck_price_window   check (valid_to is null or valid_to > valid_from)
```

Resolution order: group + qty break → group → list + qty break → list. Highest
`min_quantity` that the line satisfies wins.

### `promotion` · `promotion_redemption`

| `promotion` | Type | Notes |
| --- | --- | --- |
| `code` | varchar(40) unique not null | the coupon the cart page already collects |
| `name` | varchar(150) not null | |
| `discount_type` | varchar(16) not null | `percent` \| `fixed` \| `free_delivery` |
| `discount_value` | numeric(14,2) not null | |
| `min_order_amount` | numeric(14,2) null | |
| `max_discount_amount` | numeric(14,2) null | caps a percentage |
| `applies_to` | varchar(16) not null default `'order'` | `order` \| `category` \| `brand` \| `variant` |
| `target_ids` | bigint[] null | scoped targets |
| `usage_limit_total` | integer null | |
| `usage_limit_per_account` | integer null | |
| `usage_count` | integer not null default 0 | |
| `customer_group_id` | FK null | |
| `starts_at` / `ends_at` | timestamptz | |
| `is_active` | boolean not null default true | |

```
uq_promo_code      unique (upper(code))
idx_promo_active   (is_active, starts_at, ends_at)
```

| `promotion_redemption` | Type |
| --- | --- |
| `promotion_id` | FK → promotion |
| `order_id` | FK → order |
| `business_account_id` | FK → business_account |
| `amount_discounted` | numeric(14,2) |
| `redeemed_at` | timestamptz |

```
uq_promo_order  unique (promotion_id, order_id)   -- cannot double-apply
```

---

## 4. Inventory

### `warehouse`

| Column | Type | Notes |
| --- | --- | --- |
| `code` | varchar(20) unique not null | `IKD` (Ikorodu fulfilment centre) |
| `name` | varchar(150) not null | |
| `address` | text null | |
| `is_active` | boolean not null default true | |
| `is_default` | boolean not null default false | |
| `priority` | smallint not null default 0 | allocation order, Phase 2 |

One row at launch. Modelled now so multi-warehouse (PRD P2-04) is a data change,
not a migration of every stock query.

### `inventory_item` — **the stock ledger head**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `variant_id` | FK → product_variant cascade | |
| `warehouse_id` | FK → warehouse restrict | |
| `quantity_on_hand` | integer not null default 0 | physically present |
| `quantity_reserved` | integer not null default 0 | held by unpaid carts/orders |
| `quantity_available` | integer generated | `on_hand - reserved` |
| `quantity_incoming` | integer not null default 0 | on a purchase order |
| `reorder_point` | integer not null default 0 | |
| `reorder_quantity` | integer not null default 0 | |
| `last_counted_at` | timestamptz null | stock take |
| `version` | integer not null default 0 | optimistic-lock counter |

```
uq_inv_variant_wh   unique (variant_id, warehouse_id)
idx_inv_low_stock   (warehouse_id) where quantity_available <= reorder_point
ck_inv_nonneg       check (quantity_on_hand >= 0 and quantity_reserved >= 0)
ck_inv_reserved     check (quantity_reserved <= quantity_on_hand)
```

`ck_inv_reserved` is the database's last line of defence against overselling. Even
if application logic has a bug, the transaction aborts.

`quantity_available` is generated:

```sql
quantity_available integer generated always as (quantity_on_hand - quantity_reserved) stored
```

### `stock_reservation`

**The mechanism that prevents two buyers paying for the same case.**

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `inventory_item_id` | FK → inventory_item cascade | |
| `variant_id` | FK → product_variant restrict | denormalised for query speed |
| `quantity` | integer not null | |
| `order_id` | FK → order null | set once an order exists |
| `cart_id` | FK → cart null | pre-order hold |
| `status` | varchar(16) not null | `held` \| `committed` \| `released` \| `expired` |
| `expires_at` | timestamptz not null | |
| `committed_at` | timestamptz null | |
| `released_at` | timestamptz null | |
| `release_reason` | varchar(40) null | `payment_failed`, `expired`, `cancelled` |

```
idx_res_expiry    (expires_at) where status = 'held'
idx_res_order     (order_id)
idx_res_inv       (inventory_item_id, status)
ck_res_qty        check (quantity > 0)
```

**Reservation policy — the decision PRD §17 leaves open.** Recommended:

| Moment | Action | TTL |
| --- | --- | --- |
| Add to cart | *No reservation.* Availability is advisory only. | — |
| Checkout started (payment initiated) | Reserve. `quantity_reserved += qty` | **20 min** |
| Payment verified | Commit: `quantity_on_hand -= qty`, `quantity_reserved -= qty` | — |
| Payment failed/cancelled | Release: `quantity_reserved -= qty` | — |
| TTL elapsed | Celery beat releases | every 60 s |

Reserving at add-to-cart is the common mistake: abandoned carts then hold stock for
hours and the catalogue reads as sold out. Reserving at *payment initiation* holds
stock for exactly as long as the customer is actually paying.

### `inventory_movement` — append-only ledger

Never updated, never deleted. The auditable truth of every stock change.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `inventory_item_id` | FK → inventory_item restrict | |
| `variant_id` | FK → product_variant restrict | |
| `warehouse_id` | FK → warehouse restrict | |
| `movement_type` | varchar(24) not null | `receipt` \| `sale` \| `return` \| `adjustment` \| `damage` \| `transfer_in` \| `transfer_out` \| `count` |
| `quantity_delta` | integer not null | signed |
| `quantity_after` | integer not null | running balance snapshot |
| `unit_cost` | numeric(14,2) null | for COGS/margin reporting |
| `reference_type` | varchar(24) null | `order` \| `adjustment` \| `purchase_order` |
| `reference_id` | bigint null | |
| `reason` | varchar(200) null | **required** for adjustments — PRD OPS-03 |
| `performed_by_id` | FK → user null | null = system |
| `created_at` | timestamptz not null | |

```
idx_mv_item_time    (inventory_item_id, created_at desc)
idx_mv_reference    (reference_type, reference_id)
idx_mv_type_time    (movement_type, created_at desc)
ck_mv_delta         check (quantity_delta <> 0)
```

`quantity_after` lets you reconstruct the balance at any past date without replaying
the whole ledger — essential for month-end reconciliation.

### `stock_adjustment`

The staff-facing wrapper that produces movements. Requires a reason (OPS-03) and is
approvable.

| Column | Type | Notes |
| --- | --- | --- |
| `public_id` | uuid unique not null | |
| `warehouse_id` | FK → warehouse | |
| `adjustment_type` | varchar(24) not null | `count` \| `damage` \| `expiry` \| `theft` \| `correction` \| `receipt` |
| `reason` | text not null | |
| `status` | varchar(16) not null default `'draft'` | `draft` \| `applied` \| `cancelled` |
| `created_by_id` / `approved_by_id` | FK → user | |
| `applied_at` | timestamptz null | |

With `stock_adjustment_line (adjustment_id, variant_id, quantity_delta, unit_cost, note)`.

---

## 5. Cart

### `cart`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | the client-visible cart token |
| `business_account_id` | FK → business_account null | null while anonymous |
| `user_id` | FK → user null | who is building it |
| `session_key` | varchar(64) null | anonymous carts |
| `status` | varchar(16) not null default `'active'` | `active` \| `converted` \| `abandoned` \| `merged` |
| `currency` | char(3) not null default `'NGN'` | |
| `promotion_id` | FK → promotion null | applied coupon |
| `delivery_address_id` | FK → address null | |
| `notes` | text null | |
| `converted_order_id` | FK → order null | |
| `last_activity_at` | timestamptz not null | abandonment analytics |
| `expires_at` | timestamptz not null | 30 days |

```
uq_cart_active_account  unique (business_account_id) where status = 'active'
idx_cart_session        (session_key) where status = 'active'
idx_cart_expiry         (expires_at) where status = 'active'
```

One active cart per business account — a buyer and the owner adding items build the
same basket, which is what wholesale customers expect.

### `cart_item`

| Column | Type | Notes |
| --- | --- | --- |
| `cart_id` | FK → cart cascade | |
| `variant_id` | FK → product_variant restrict | |
| `quantity` | integer not null | in selling units |
| `unit_price_snapshot` | numeric(14,2) not null | price when added |
| `price_changed` | boolean not null default false | flagged at revalidation |
| `added_at` / `updated_at` | timestamptz | |

```
uq_cart_variant  unique (cart_id, variant_id)
ck_cart_qty      check (quantity > 0)
```

Prices are re-resolved server-side at checkout. The snapshot exists only so the UI
can say *"the price of this line changed since you added it"* — never to charge the
old price.

---

## 6. Orders

### `order`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `order_number` | varchar(24) unique not null | `D2R-2026-000417`, from a sequence |
| `business_account_id` | FK → business_account restrict | |
| `placed_by_user_id` | FK → user restrict | which member |
| `status` | varchar(24) not null | see state machine below |
| `payment_status` | varchar(24) not null | `pending` \| `initiated` \| `paid` \| `failed` \| `cancelled` \| `refunded` \| `partially_refunded` |
| `fulfilment_status` | varchar(24) not null | `unfulfilled` \| `processing` \| `dispatched` \| `delivered` \| `returned` |
| `currency` | char(3) not null default `'NGN'` | |
| `subtotal` | numeric(14,2) not null | sum of lines, ex-tax |
| `discount_total` | numeric(14,2) not null default 0 | |
| `delivery_fee` | numeric(14,2) not null default 0 | |
| `tax_total` | numeric(14,2) not null default 0 | |
| `grand_total` | numeric(14,2) not null | what was charged |
| `amount_paid` | numeric(14,2) not null default 0 | |
| `amount_refunded` | numeric(14,2) not null default 0 | |
| **Address snapshot** | | copied, never FK'd — addresses change |
| `delivery_*` | denormalised columns | name, phone, line1, line2, city, state, postal, country, instructions |
| `billing_*` | denormalised columns | same shape |
| `delivery_zone_id` | FK → delivery_zone null | |
| `promotion_id` | FK → promotion null | |
| `restricted_ack_at` | timestamptz null | alcohol acknowledgement (PRD §11) |
| `restricted_ack_text` | text null | exact wording shown, for evidence |
| `customer_note` | text null | |
| `internal_note` | text null | staff-only |
| `placed_at` | timestamptz null | set when payment initiated |
| `paid_at` / `dispatched_at` / `delivered_at` / `cancelled_at` | timestamptz null | |
| `cancellation_reason` | varchar(200) null | |
| `source` | varchar(16) not null default `'web'` | `web` \| `admin` \| `rep` \| `api` |
| `created_at` / `updated_at` | timestamptz | |

```
uq_order_number      unique (order_number)
idx_order_account    (business_account_id, created_at desc)
idx_order_status     (status, created_at desc)
idx_order_payment    (payment_status) where payment_status in ('pending','initiated')
idx_order_fulfil     (fulfilment_status) where fulfilment_status <> 'delivered'
idx_order_placed     (placed_at desc)
ck_order_totals      check (grand_total = subtotal - discount_total + delivery_fee + tax_total)
ck_order_refund      check (amount_refunded <= amount_paid)
```

`ck_order_totals` means an arithmetic bug cannot persist a wrong invoice.

**Address is snapshotted, not referenced.** If a customer edits their shop address
next year, last year's invoice must still show where it actually went.

#### Order state machine

```
                    ┌──────────────┐
                    │ pending_     │  created, nothing charged
                    │ payment      │
                    └──────┬───────┘
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌───────────┐ ┌──────────┐ ┌───────────┐
       │ payment_  │ │cancelled │ │  expired  │
       │ failed    │ └──────────┘ └───────────┘
       └─────┬─────┘        ▲
     retry   │              │
             ▼              │
        ┌─────────┐         │
        │  paid   │─────────┘  (cancel before dispatch)
        └────┬────┘
             ▼
      ┌─────────────┐
      │ processing  │  picked, packed
      └──────┬──────┘
             ▼
      ┌─────────────┐
      │ dispatched  │  left the warehouse
      └──────┬──────┘
             ▼
      ┌─────────────┐      ┌──────────┐
      │  delivered  │─────▶│ returned │
      └─────────────┘      └──────────┘
                                 │
                                 ▼
                          ┌─────────────┐
                          │  refunded / │
                          │  partially  │
                          └─────────────┘
```

Legal transitions are declared in `orders/state.py` and enforced in the service
layer. An illegal transition raises, is logged and returns `409`.

Mapping to the labels the frontend already renders:

| DB status | UI label |
| --- | --- |
| `pending_payment` | Pending Payment |
| `paid`, `processing` | Processing |
| `dispatched` | Delivering |
| `delivered` | Completed |
| `cancelled`, `expired` | Cancelled |

### `order_item` — **historical snapshot** (PRD OPS-04)

| Column | Type | Notes |
| --- | --- | --- |
| `order_id` | FK → order cascade | |
| `variant_id` | FK → product_variant restrict | **restrict** — never orphan a line |
| `sku` | varchar(60) not null | snapshot |
| `product_name` | varchar(250) not null | snapshot |
| `variant_name` | varchar(200) not null | snapshot |
| `brand_name` | varchar(150) null | snapshot |
| `image_url` | varchar(500) null | snapshot |
| `selling_unit` | varchar(12) not null | snapshot |
| `base_units` | integer not null | snapshot |
| `quantity` | integer not null | |
| `unit_price` | numeric(14,2) not null | |
| `line_subtotal` | numeric(14,2) not null | qty × unit_price |
| `discount_amount` | numeric(14,2) not null default 0 | |
| `tax_rate` | numeric(5,2) not null | snapshot |
| `tax_amount` | numeric(14,2) not null | |
| `line_total` | numeric(14,2) not null | |
| `is_restricted` | boolean not null default false | snapshot |
| `quantity_fulfilled` | integer not null default 0 | partial shipments |
| `quantity_returned` | integer not null default 0 | |

```
idx_oi_order    (order_id)
idx_oi_variant  (variant_id)
ck_oi_qty       check (quantity > 0)
ck_oi_line      check (line_total = line_subtotal - discount_amount + tax_amount)
```

Every display field is copied. Renaming a product must never rewrite history.

### `order_status_history`

| Column | Type |
| --- | --- |
| `order_id` | FK → order cascade |
| `from_status` / `to_status` | varchar(24) |
| `changed_by_id` | FK → user null |
| `note` | text null |
| `created_at` | timestamptz |

```
idx_osh_order  (order_id, created_at)
```

---

## 7. Payments

### `payment_attempt`

One row **per attempt**, never overwritten. A customer who retries three times leaves
three rows — which is exactly what reconciliation needs.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `public_id` | uuid unique not null | |
| `order_id` | FK → order restrict | |
| `provider` | varchar(20) not null | `paystack` \| `flutterwave` \| `bank_transfer` |
| `provider_reference` | varchar(120) not null | **their** transaction ref |
| `internal_reference` | varchar(60) unique not null | **ours**, sent to the provider |
| `amount` | numeric(14,2) not null | |
| `currency` | char(3) not null | |
| `status` | varchar(20) not null | `initiated` \| `pending` \| `successful` \| `failed` \| `cancelled` \| `abandoned` |
| `channel` | varchar(24) null | `card` \| `bank` \| `ussd` \| `transfer` |
| `authorization_code` | varchar(80) null | tokenised, for future repeat payment |
| `card_last4` | char(4) null | display only |
| `card_brand` | varchar(20) null | |
| `fees` | numeric(14,2) null | provider fee, for margin reporting |
| `gateway_response` | text null | human-readable message |
| `raw_payload` | jsonb null | full verify response, redacted |
| `verified_at` | timestamptz null | **server-side** verification |
| `failure_reason` | varchar(200) null | |
| `ip_address` | inet null | |
| `created_at` / `updated_at` | timestamptz | |

```
uq_pay_internal_ref   unique (internal_reference)
uq_pay_provider_ref   unique (provider, provider_reference)
idx_pay_order         (order_id, created_at desc)
idx_pay_status        (status, created_at desc)
idx_pay_recon         (provider, verified_at) where status = 'successful'
```

`uq_pay_provider_ref` is what makes duplicate webhook delivery harmless.

### `webhook_event` — **idempotency ledger** (PRD PAY-05)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `provider` | varchar(20) not null | |
| `event_id` | varchar(120) not null | provider's own event id |
| `event_type` | varchar(60) not null | `charge.success` |
| `signature_valid` | boolean not null | |
| `payload` | jsonb not null | |
| `status` | varchar(16) not null default `'received'` | `received` \| `processed` \| `failed` \| `ignored` |
| `processed_at` | timestamptz null | |
| `error` | text null | |
| `attempts` | smallint not null default 0 | |
| `received_at` | timestamptz not null | |

```
uq_webhook_event   unique (provider, event_id)   -- THE idempotency guarantee
idx_webhook_status (status, received_at) where status in ('received','failed')
```

The unique constraint is the entire mechanism: insert first, process second. A
duplicate delivery hits a constraint violation and is answered `200 OK` without
doing the work twice.

### `refund`

| Column | Type | Notes |
| --- | --- | --- |
| `public_id` | uuid unique not null | |
| `order_id` | FK → order restrict | |
| `payment_attempt_id` | FK → payment_attempt restrict | |
| `amount` | numeric(14,2) not null | |
| `reason` | varchar(200) not null | |
| `refund_type` | varchar(16) not null | `full` \| `partial` |
| `status` | varchar(16) not null | `pending` \| `processing` \| `completed` \| `failed` |
| `provider_reference` | varchar(120) null | |
| `requested_by_id` / `approved_by_id` | FK → user | two-person rule |
| `restock` | boolean not null default true | return stock to inventory |
| `completed_at` | timestamptz null | |

With `refund_line (refund_id, order_item_id, quantity, amount)`.

### `invoice` (PRD OPS-06)

| Column | Type | Notes |
| --- | --- | --- |
| `invoice_number` | varchar(24) unique not null | own sequence, **gapless** |
| `order_id` | FK → order restrict | |
| `business_account_id` | FK → business_account restrict | |
| `issue_date` | date not null | |
| `due_date` | date null | Phase 2 credit terms |
| `subtotal` / `tax_total` / `total` | numeric(14,2) not null | snapshot |
| `amount_paid` | numeric(14,2) not null default 0 | |
| `status` | varchar(16) not null | `draft` \| `issued` \| `paid` \| `void` |
| `pdf_url` | varchar(500) null | S3 |
| `issued_at` | timestamptz null | |

Invoice numbers must be gapless for tax purposes — allocated from a dedicated
Postgres sequence inside the issuing transaction, never from `count(*) + 1`.

---

## 8. Delivery

### `delivery_zone`

| Column | Type | Notes |
| --- | --- | --- |
| `code` | varchar(20) unique not null | `LAG-IKD` |
| `name` | varchar(150) not null | "Ikorodu Axis" |
| `description` | text null | |
| `is_active` | boolean not null default true | |
| `supports_restricted` | boolean not null default false | can alcohol go here |
| `sort_order` | integer not null default 0 | |

Seeded from the coverage table the About page already renders.

### `delivery_zone_area`

Matching rules — a zone is a set of areas, not a polygon (no GIS needed at launch).

| Column | Type | Notes |
| --- | --- | --- |
| `zone_id` | FK → delivery_zone cascade | |
| `match_type` | varchar(16) not null | `city` \| `state` \| `postal` \| `lga` |
| `match_value` | varchar(120) not null | `Ikorodu` |

```
uq_dza          unique (zone_id, match_type, match_value)
idx_dza_lookup  (match_type, lower(match_value))
```

### `delivery_rate`

| Column | Type | Notes |
| --- | --- | --- |
| `zone_id` | FK → delivery_zone cascade | |
| `name` | varchar(100) not null | "Standard" |
| `rate_type` | varchar(16) not null | `flat` \| `weight` \| `order_value` \| `free` |
| `base_fee` | numeric(14,2) not null default 0 | |
| `per_kg_fee` | numeric(14,2) null | |
| `min_order_value` | numeric(14,2) null | band floor |
| `max_order_value` | numeric(14,2) null | band ceiling |
| `free_above_amount` | numeric(14,2) null | free delivery threshold |
| `estimated_days_min` / `estimated_days_max` | smallint null | |
| `is_active` | boolean not null default true | |
| `priority` | smallint not null default 0 | |

```
idx_rate_zone  (zone_id, priority) where is_active
```

### `shipment`

| Column | Type | Notes |
| --- | --- | --- |
| `public_id` | uuid unique not null | |
| `order_id` | FK → order cascade | |
| `warehouse_id` | FK → warehouse restrict | |
| `shipment_number` | varchar(24) unique not null | |
| `status` | varchar(16) not null | `pending` \| `packed` \| `dispatched` \| `delivered` \| `failed` \| `returned` |
| `carrier` | varchar(100) null | own fleet or third party |
| `tracking_reference` | varchar(120) null | PRD OPS-07 |
| `driver_name` / `driver_phone` | varchar null | own-fleet delivery |
| `vehicle_reference` | varchar(60) null | |
| `dispatched_at` / `delivered_at` | timestamptz null | |
| `delivery_proof_url` | varchar(500) null | signature/photo |
| `received_by` | varchar(150) null | who signed |
| `failure_reason` | varchar(200) null | |
| `notes` | text null | |

With `shipment_item (shipment_id, order_item_id, quantity)` for partial dispatch.

---

## 9. Content & engagement

### `review`

| Column | Type | Notes |
| --- | --- | --- |
| `public_id` | uuid unique not null | |
| `product_id` | FK → product cascade | |
| `business_account_id` | FK → business_account null | |
| `user_id` | FK → user null | |
| `order_id` | FK → order null | verified-purchase proof |
| `rating` | smallint not null | 1–5 |
| `title` | varchar(150) null | |
| `body` | text null | |
| `status` | varchar(16) not null default `'pending'` | `pending` \| `approved` \| `rejected` \| `spam` |
| `is_verified_purchase` | boolean not null default false | |
| `moderated_by_id` | FK → user null | |
| `helpful_count` | integer not null default 0 | |

```
uq_review_order_product  unique (order_id, product_id) where order_id is not null
idx_review_product       (product_id, status, created_at desc)
ck_review_rating         check (rating between 1 and 5)
```

Moderated by default. Reviews are public content and an unmoderated queue is a spam
vector.

### `wishlist` · `wishlist_item` · `saved_list` (Phase 2)

```
wishlist       (business_account_id, name, is_default)
wishlist_item  (wishlist_id, variant_id, added_at, note)
               uq (wishlist_id, variant_id)
```

`saved_list` is the Phase 2 "standing order template" — the same shape with a
`default_quantity` on each line, so a shop can reorder its weekly basket in one click.

### `notification`

| Column | Type | Notes |
| --- | --- | --- |
| `user_id` | FK → user cascade | |
| `channel` | varchar(16) not null | `email` \| `sms` \| `whatsapp` \| `in_app` |
| `template_code` | varchar(60) not null | `order_confirmed` |
| `subject` | varchar(200) null | |
| `payload` | jsonb not null | template variables |
| `status` | varchar(16) not null | `queued` \| `sent` \| `failed` \| `read` |
| `provider_message_id` | varchar(120) null | |
| `sent_at` / `read_at` | timestamptz null | |
| `error` | text null | |

---

## 10. Search & merchandising

### `search_query_log`

Feeds "recommended searches" (already in the header UI) and reveals catalogue gaps.

| Column | Type |
| --- | --- |
| `query` | varchar(200) not null |
| `normalised_query` | varchar(200) not null |
| `business_account_id` | FK null |
| `result_count` | integer not null |
| `clicked_variant_id` | FK null |
| `created_at` | timestamptz |

```
idx_sql_norm  (normalised_query, created_at desc)
idx_sql_zero  (normalised_query) where result_count = 0   -- what we fail to stock
```

### `banner`

Powers the homepage hero and promo tiles without a deploy.

| Column | Type |
| --- | --- |
| `placement` | varchar(40) not null (`home_hero`, `home_promo_1`, `category_top`) |
| `title` / `subtitle` / `cta_label` / `cta_url` | varchar |
| `image_url` / `mobile_image_url` | varchar(500) |
| `background_colour` | varchar(9) null |
| `starts_at` / `ends_at` | timestamptz null |
| `sort_order` | integer, `is_active` boolean |

---

## 11. Audit & operations

### `audit_log` (PRD §9)

Every material action. Append-only; no update or delete grant on this table.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | bigserial PK | |
| `actor_id` | FK → user null | null = system |
| `actor_type` | varchar(16) not null | `staff` \| `customer` \| `system` \| `webhook` |
| `action` | varchar(60) not null | `order.status_changed` |
| `object_type` | varchar(60) not null | `order` |
| `object_id` | bigint not null | |
| `object_repr` | varchar(200) null | human label at the time |
| `changes` | jsonb null | `{"status": ["paid", "processing"]}` |
| `reason` | varchar(300) null | |
| `ip_address` | inet null | |
| `user_agent` | varchar(300) null | |
| `request_id` | uuid null | ties to application logs |
| `created_at` | timestamptz not null | |

```
idx_audit_object  (object_type, object_id, created_at desc)
idx_audit_actor   (actor_id, created_at desc)
idx_audit_action  (action, created_at desc)
```

Partitioned monthly by `created_at` once it passes ~10M rows.

Mandatory audit events: stock adjustments, price changes, order status changes,
payment state changes, refunds, customer approval/suspension, permission changes,
product publish/archive, bulk imports.

### `import_job` (PRD FR-10)

| Column | Type | Notes |
| --- | --- | --- |
| `public_id` | uuid unique not null | |
| `job_type` | varchar(24) not null | `products` \| `prices` \| `inventory` \| `customers` |
| `file_url` | varchar(500) not null | |
| `file_name` | varchar(200) not null | |
| `status` | varchar(16) not null | `pending` \| `validating` \| `ready` \| `processing` \| `completed` \| `failed` |
| `total_rows` / `processed_rows` / `success_rows` / `error_rows` | integer default 0 | |
| `errors` | jsonb null | row-level errors for download |
| `dry_run` | boolean not null default true | **validate before commit** |
| `created_by_id` | FK → user | |
| `started_at` / `completed_at` | timestamptz null | |

Imports are two-phase: upload → validate and report → operator confirms → apply.
A 5,000-row price file that silently half-applies is a catastrophe; this prevents it.

### `idempotency_key`

Protects client retries on unsafe writes (see `02-api.md` §6).

| Column | Type |
| --- | --- |
| `key` | varchar(120) not null |
| `user_id` | FK → user null |
| `endpoint` | varchar(120) not null |
| `request_hash` | char(64) not null |
| `response_status` | smallint null |
| `response_body` | jsonb null |
| `status` | varchar(16) not null (`in_progress` \| `completed`) |
| `created_at` / `expires_at` | timestamptz |

```
uq_idem  unique (key, endpoint)
idx_idem_expiry (expires_at)
```

### `setting`

Runtime configuration so staff change behaviour without a deploy (PRD FR-03 spirit).

| Column | Type |
| --- | --- |
| `key` | varchar(80) unique not null |
| `value` | jsonb not null |
| `value_type` | varchar(16) not null |
| `description` | text null |
| `is_public` | boolean not null default false |
| `updated_by_id` | FK → user null |

> **Superseded for payments.** A single `payment.active_gateway` string cannot
> express multiple live gateways, per-gateway sandbox/live modes, or routing.
> Gateways now live in `payment_gateway` and `payment_routing_rule` — see
> `schema.sql` §14 and `drive2retail-admin/docs/08-payments-gateways.md`.

Seeded keys: `payment.active_gateway` *(deprecated)*, `checkout.reservation_ttl_minutes`,
`accounts.require_approval`, `accounts.hide_prices_until_approved`,
`orders.allow_cancel_before`, `delivery.free_above`, `tax.default_class`,
`restricted.require_acknowledgement`.

---

## 12. Table summary

| Domain | Tables |
| --- | --- |
| Identity | `user`, `business_account`, `business_account_member`, `address`, `staff_role`, `staff_assignment`, `auth_token` |
| Catalogue | `category`, `brand`, `vendor`, `product`, `product_category`, `product_variant`, `product_image`, `attribute`, `attribute_value` |
| Pricing | `tax_class`, `customer_group`, `price`, `promotion`, `promotion_redemption` |
| Inventory | `warehouse`, `inventory_item`, `stock_reservation`, `inventory_movement`, `stock_adjustment`, `stock_adjustment_line` |
| Cart | `cart`, `cart_item` |
| Orders | `order`, `order_item`, `order_status_history` |
| Payments | `payment_attempt`, `webhook_event`, `refund`, `refund_line`, `invoice` |
| Delivery | `delivery_zone`, `delivery_zone_area`, `delivery_rate`, `shipment`, `shipment_item` |
| Content | `review`, `wishlist`, `wishlist_item`, `notification` |
| Search | `search_query_log`, `banner` |
| Ops | `audit_log`, `import_job`, `idempotency_key`, `setting` |

**67 tables.** Executable DDL in `schema.sql`.
