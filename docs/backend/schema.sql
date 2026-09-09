-- Drive 2 Retail — PostgreSQL 16 schema
--
-- Reference DDL for the model specified in 01-data-model.md. In the Django build
-- these tables come from migrations; this file is the canonical statement of
-- structure, constraints and indexes, and is used to review the design and to
-- seed a scratch database for query planning.
--
--   psql -d d2r -f schema.sql

begin;

create extension if not exists pg_trgm;
create extension if not exists citext;
create extension if not exists pgcrypto;

-- ============================================================================
-- 1. IDENTITY & ACCESS
-- ============================================================================

create table "user" (
  id                  bigserial primary key,
  public_id           uuid not null default gen_random_uuid(),
  email               citext not null,
  password            varchar(128) not null,
  first_name          varchar(100) not null,
  last_name           varchar(100) not null,
  phone               varchar(32),
  user_type           varchar(16) not null default 'customer',
  is_active           boolean not null default true,
  is_email_verified   boolean not null default false,
  email_verified_at   timestamptz,
  last_login_at       timestamptz,
  failed_login_count  smallint not null default 0,
  locked_until        timestamptz,
  mfa_secret          varchar(64),
  mfa_enabled         boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint uq_user_email     unique (email),
  constraint uq_user_public_id unique (public_id),
  constraint ck_user_type      check (user_type in ('customer','staff'))
);
create index idx_user_type_active on "user" (user_type, is_active);

create table customer_group (
  id               bigserial primary key,
  code             varchar(30) not null unique,
  name             varchar(100) not null,
  discount_percent numeric(5,2) not null default 0,
  priority         smallint not null default 0,
  created_at       timestamptz not null default now()
);

create table delivery_zone (
  id                   bigserial primary key,
  code                 varchar(20) not null unique,
  name                 varchar(150) not null,
  description          text,
  is_active            boolean not null default true,
  supports_restricted  boolean not null default false,
  sort_order           integer not null default 0,
  created_at           timestamptz not null default now()
);

create table business_account (
  id                          bigserial primary key,
  public_id                   uuid not null default gen_random_uuid(),
  account_number              varchar(20) not null,
  business_name               varchar(200) not null,
  business_type               varchar(32) not null,
  registration_number         varchar(64),
  tax_id                      varchar(64),
  primary_contact_name        varchar(150) not null,
  primary_email               citext not null,
  primary_phone               varchar(32) not null,
  status                      varchar(16) not null default 'pending',
  approved_at                 timestamptz,
  approved_by_id              bigint references "user"(id) on delete set null,
  rejection_reason            text,
  can_view_prices             boolean not null default false,
  can_order                   boolean not null default false,
  customer_group_id           bigint references customer_group(id) on delete set null,
  credit_limit                numeric(14,2),
  payment_terms_days          smallint,
  assigned_rep_id             bigint references "user"(id) on delete set null,
  delivery_zone_id            bigint references delivery_zone(id) on delete set null,
  restricted_products_allowed boolean not null default false,
  internal_notes              text,
  created_at                  timestamptz not null default now(),
  updated_at                  timestamptz not null default now(),
  constraint uq_ba_number    unique (account_number),
  constraint uq_ba_public_id unique (public_id),
  constraint ck_ba_status    check (status in ('pending','approved','suspended','rejected','closed')),
  constraint ck_ba_type      check (business_type in
    ('retailer','wholesaler','supermarket','chain','open_market','neighbourhood','other'))
);
create index idx_ba_status on business_account (status);
create index idx_ba_name_trgm on business_account using gin (business_name gin_trgm_ops);
create index idx_ba_group on business_account (customer_group_id);

create table business_account_member (
  id                  bigserial primary key,
  business_account_id bigint not null references business_account(id) on delete cascade,
  user_id             bigint not null references "user"(id) on delete cascade,
  role                varchar(16) not null,
  is_default          boolean not null default false,
  invited_by_id       bigint references "user"(id) on delete set null,
  joined_at           timestamptz not null default now(),
  constraint uq_bam   unique (business_account_id, user_id),
  constraint ck_bam_role check (role in ('owner','buyer','viewer'))
);
create index idx_bam_user on business_account_member (user_id);

create table address (
  id                    bigserial primary key,
  public_id             uuid not null default gen_random_uuid(),
  business_account_id   bigint not null references business_account(id) on delete cascade,
  label                 varchar(60),
  address_type          varchar(16) not null default 'delivery',
  contact_name          varchar(150) not null,
  contact_phone         varchar(32) not null,
  line1                 varchar(200) not null,
  line2                 varchar(200),
  city                  varchar(100) not null,
  state                 varchar(100) not null,
  postal_code           varchar(20),
  country               char(2) not null default 'NG',
  latitude              numeric(9,6),
  longitude             numeric(9,6),
  delivery_zone_id      bigint references delivery_zone(id) on delete set null,
  delivery_instructions text,
  is_default_billing    boolean not null default false,
  is_default_delivery   boolean not null default false,
  archived_at           timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  constraint uq_addr_public_id unique (public_id),
  constraint ck_addr_type check (address_type in ('billing','delivery','both'))
);
create index idx_addr_account on address (business_account_id) where archived_at is null;
create unique index uq_addr_default_billing  on address (business_account_id) where is_default_billing;
create unique index uq_addr_default_delivery on address (business_account_id) where is_default_delivery;

create table staff_role (
  id          bigserial primary key,
  code        varchar(40) not null unique,
  name        varchar(100) not null,
  description text,
  is_system   boolean not null default false
);

create table staff_assignment (
  id             bigserial primary key,
  user_id        bigint not null references "user"(id) on delete cascade,
  role_id        bigint not null references staff_role(id) on delete cascade,
  granted_by_id  bigint references "user"(id) on delete set null,
  granted_at     timestamptz not null default now(),
  constraint uq_staff_assignment unique (user_id, role_id)
);

create table auth_token (
  id              bigserial primary key,
  user_id         bigint not null references "user"(id) on delete cascade,
  token_hash      char(64) not null,
  purpose         varchar(24) not null,
  expires_at      timestamptz not null,
  used_at         timestamptz,
  revoked_at      timestamptz,
  rotated_from_id bigint references auth_token(id) on delete set null,
  ip_address      inet,
  user_agent      varchar(300),
  created_at      timestamptz not null default now(),
  constraint uq_token_hash unique (token_hash),
  constraint ck_token_purpose check (purpose in ('refresh','password_reset','email_verify','otp'))
);
create index idx_token_user_purpose on auth_token (user_id, purpose) where revoked_at is null;
create index idx_token_expiry on auth_token (expires_at) where revoked_at is null;

-- ============================================================================
-- 2. CATALOGUE
-- ============================================================================

create table category (
  id               bigserial primary key,
  public_id        uuid not null default gen_random_uuid(),
  parent_id        bigint references category(id) on delete restrict,
  path             varchar(255) not null,
  depth            smallint not null default 0,
  name             varchar(150) not null,
  slug             varchar(160) not null,
  description      text,
  image_url        varchar(500),
  icon             varchar(60),
  is_active        boolean not null default true,
  is_restricted    boolean not null default false,
  sort_order       integer not null default 0,
  meta_title       varchar(200),
  meta_description varchar(320),
  product_count    integer not null default 0,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint uq_category_slug unique (slug)
);
create index idx_category_path   on category (path text_pattern_ops);
create index idx_category_parent on category (parent_id, sort_order);

create table vendor (
  id                 bigserial primary key,
  public_id          uuid not null default gen_random_uuid(),
  code               varchar(20) not null unique,
  name               varchar(200) not null,
  vendor_type        varchar(24) not null,
  contact_name       varchar(150),
  contact_email      citext,
  contact_phone      varchar(32),
  address            text,
  payment_terms_days smallint,
  is_active          boolean not null default true,
  notes              text,
  created_at         timestamptz not null default now(),
  constraint ck_vendor_type check (vendor_type in ('manufacturer','importer','distributor'))
);

create table brand (
  id          bigserial primary key,
  public_id   uuid not null default gen_random_uuid(),
  name        varchar(150) not null,
  slug        varchar(160) not null unique,
  logo_url    varchar(500),
  description text,
  vendor_id   bigint references vendor(id) on delete set null,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

create table tax_class (
  id             bigserial primary key,
  code           varchar(30) not null unique,
  name           varchar(100) not null,
  rate_percent   numeric(5,2) not null,
  is_inclusive   boolean not null default false,
  effective_from date not null default current_date,
  effective_to   date,
  constraint ck_tax_rate check (rate_percent >= 0 and rate_percent <= 100)
);

create table product (
  id                bigserial primary key,
  public_id         uuid not null default gen_random_uuid(),
  name              varchar(250) not null,
  slug              varchar(260) not null,
  description       text,
  short_description varchar(500),
  category_id       bigint not null references category(id) on delete restrict,
  brand_id          bigint references brand(id) on delete set null,
  vendor_id         bigint references vendor(id) on delete set null,
  tax_class_id      bigint not null references tax_class(id) on delete restrict,
  status            varchar(16) not null default 'draft',
  is_restricted     boolean not null default false,
  restriction_note  varchar(300),
  attributes        jsonb not null default '{}'::jsonb,
  rating_avg        numeric(3,2) not null default 0,
  rating_count      integer not null default 0,
  meta_title        varchar(200),
  meta_description  varchar(320),
  published_at      timestamptz,
  archived_at       timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  search_vector     tsvector generated always as (
    setweight(to_tsvector('simple', coalesce(name, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(short_description, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(description, '')), 'C')
  ) stored,
  constraint uq_product_slug unique (slug),
  constraint ck_product_status check (status in ('draft','active','discontinued','archived')),
  constraint ck_product_rating check (rating_avg >= 0 and rating_avg <= 5)
);
create index idx_product_search     on product using gin (search_vector);
create index idx_product_name_trgm  on product using gin (name gin_trgm_ops);
create index idx_product_attrs      on product using gin (attributes jsonb_path_ops);
create index idx_product_cat_status on product (category_id, status) where archived_at is null;
create index idx_product_listing    on product (category_id, published_at desc)
  where archived_at is null and status = 'active';

create table product_category (
  product_id  bigint not null references product(id) on delete cascade,
  category_id bigint not null references category(id) on delete cascade,
  primary key (product_id, category_id)
);

create table product_variant (
  id                  bigserial primary key,
  public_id           uuid not null default gen_random_uuid(),
  product_id          bigint not null references product(id) on delete cascade,
  sku                 varchar(60) not null,
  barcode             varchar(40),
  name                varchar(200) not null,
  selling_unit        varchar(12) not null default 'unit',
  units_per_pack      integer not null default 1,
  packs_per_case      integer not null default 1,
  moq                 integer not null default 1,
  order_increment     integer not null default 1,
  max_order_qty       integer,
  weight_kg           numeric(8,3),
  length_cm           numeric(7,2),
  width_cm            numeric(7,2),
  height_cm           numeric(7,2),
  variant_attributes  jsonb not null default '{}'::jsonb,
  is_default          boolean not null default false,
  status              varchar(16) not null default 'active',
  low_stock_threshold integer not null default 0,
  archived_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  base_units          integer generated always as (
    case selling_unit
      when 'unit' then 1
      when 'pack' then units_per_pack
      when 'case' then units_per_pack * packs_per_case
      else 1
    end
  ) stored,
  constraint uq_variant_sku    unique (sku),
  constraint ck_variant_unit   check (selling_unit in ('unit','pack','case')),
  constraint ck_variant_status check (status in ('active','inactive','discontinued')),
  constraint ck_variant_moq    check (moq >= 1 and order_increment >= 1),
  constraint ck_variant_units  check (units_per_pack >= 1 and packs_per_case >= 1),
  constraint ck_variant_max    check (max_order_qty is null or max_order_qty >= moq)
);
create index idx_variant_product on product_variant (product_id) where archived_at is null;
create index idx_variant_status  on product_variant (status);
create index idx_variant_barcode on product_variant (barcode) where barcode is not null;
create unique index uq_variant_default on product_variant (product_id) where is_default;

create table product_image (
  id         bigserial primary key,
  product_id bigint not null references product(id) on delete cascade,
  variant_id bigint references product_variant(id) on delete cascade,
  url        varchar(500) not null,
  alt_text   varchar(250),
  sort_order integer not null default 0,
  is_primary boolean not null default false,
  width      integer,
  height     integer,
  created_at timestamptz not null default now()
);
create index idx_pi_product on product_image (product_id, sort_order);
create unique index uq_pi_primary on product_image (product_id) where is_primary;

create table attribute (
  id            bigserial primary key,
  code          varchar(40) not null unique,
  name          varchar(100) not null,
  data_type     varchar(16) not null default 'text',
  is_filterable boolean not null default true,
  sort_order    integer not null default 0,
  constraint ck_attr_type check (data_type in ('text','number','boolean','colour'))
);

create table attribute_value (
  id           bigserial primary key,
  attribute_id bigint not null references attribute(id) on delete cascade,
  variant_id   bigint not null references product_variant(id) on delete cascade,
  value_text   varchar(200),
  value_number numeric(12,3),
  constraint uq_av unique (attribute_id, variant_id)
);
create index idx_av_lookup  on attribute_value (attribute_id, value_text);
create index idx_av_variant on attribute_value (variant_id);
create index idx_av_facet   on attribute_value (attribute_id, value_text) include (variant_id);

-- ============================================================================
-- 3. PRICING & PROMOTIONS
-- ============================================================================

create table price (
  id                 bigserial primary key,
  variant_id         bigint not null references product_variant(id) on delete cascade,
  customer_group_id  bigint references customer_group(id) on delete cascade,
  currency           char(3) not null default 'NGN',
  amount             numeric(14,2) not null,
  compare_at_amount  numeric(14,2),
  min_quantity       integer not null default 1,
  valid_from         timestamptz not null default now(),
  valid_to           timestamptz,
  created_by_id      bigint references "user"(id) on delete set null,
  created_at         timestamptz not null default now(),
  constraint ck_price_positive check (amount >= 0),
  constraint ck_price_window   check (valid_to is null or valid_to > valid_from),
  constraint ck_price_minqty   check (min_quantity >= 1)
);
create index idx_price_lookup on price
  (variant_id, customer_group_id, min_quantity desc, valid_from desc);
create index idx_price_resolve on price
  (variant_id, customer_group_id, min_quantity desc, valid_from desc)
  where valid_to is null or valid_to > now();

create table promotion (
  id                      bigserial primary key,
  public_id               uuid not null default gen_random_uuid(),
  code                    varchar(40) not null,
  name                    varchar(150) not null,
  discount_type           varchar(16) not null,
  discount_value          numeric(14,2) not null,
  min_order_amount        numeric(14,2),
  max_discount_amount     numeric(14,2),
  applies_to              varchar(16) not null default 'order',
  target_ids              bigint[],
  usage_limit_total       integer,
  usage_limit_per_account integer,
  usage_count             integer not null default 0,
  customer_group_id       bigint references customer_group(id) on delete set null,
  starts_at               timestamptz not null default now(),
  ends_at                 timestamptz,
  is_active               boolean not null default true,
  created_at              timestamptz not null default now(),
  constraint ck_promo_type   check (discount_type in ('percent','fixed','free_delivery')),
  constraint ck_promo_target check (applies_to in ('order','category','brand','variant')),
  constraint ck_promo_value  check (discount_value >= 0)
);
create unique index uq_promo_code   on promotion (upper(code));
create index idx_promo_active on promotion (is_active, starts_at, ends_at);

-- ============================================================================
-- 4. INVENTORY
-- ============================================================================

create table warehouse (
  id         bigserial primary key,
  code       varchar(20) not null unique,
  name       varchar(150) not null,
  address    text,
  is_active  boolean not null default true,
  is_default boolean not null default false,
  priority   smallint not null default 0,
  created_at timestamptz not null default now()
);
create unique index uq_warehouse_default on warehouse (is_default) where is_default;

create table inventory_item (
  id                 bigserial primary key,
  variant_id         bigint not null references product_variant(id) on delete cascade,
  warehouse_id       bigint not null references warehouse(id) on delete restrict,
  quantity_on_hand   integer not null default 0,
  quantity_reserved  integer not null default 0,
  quantity_incoming  integer not null default 0,
  reorder_point      integer not null default 0,
  reorder_quantity   integer not null default 0,
  last_counted_at    timestamptz,
  version            integer not null default 0,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  quantity_available integer generated always as (quantity_on_hand - quantity_reserved) stored,
  constraint uq_inv_variant_wh unique (variant_id, warehouse_id),
  constraint ck_inv_nonneg     check (quantity_on_hand >= 0 and quantity_reserved >= 0),
  -- last line of defence against overselling
  constraint ck_inv_reserved   check (quantity_reserved <= quantity_on_hand)
);
create index idx_inv_low_stock on inventory_item (warehouse_id)
  where quantity_available <= reorder_point;
create index idx_inv_reorder on inventory_item (warehouse_id, quantity_available)
  where quantity_available <= reorder_point;

-- forward declaration resolved below via alter table
create table stock_reservation (
  id                bigserial primary key,
  public_id         uuid not null default gen_random_uuid(),
  inventory_item_id bigint not null references inventory_item(id) on delete cascade,
  variant_id        bigint not null references product_variant(id) on delete restrict,
  quantity          integer not null,
  order_id          bigint,
  cart_id           bigint,
  status            varchar(16) not null default 'held',
  expires_at        timestamptz not null,
  committed_at      timestamptz,
  released_at       timestamptz,
  release_reason    varchar(40),
  created_at        timestamptz not null default now(),
  constraint ck_res_qty    check (quantity > 0),
  constraint ck_res_status check (status in ('held','committed','released','expired'))
);
create index idx_res_expiry on stock_reservation (expires_at) where status = 'held';
create index idx_res_order  on stock_reservation (order_id);
create index idx_res_inv    on stock_reservation (inventory_item_id, status);

create table inventory_movement (
  id                bigserial primary key,
  inventory_item_id bigint not null references inventory_item(id) on delete restrict,
  variant_id        bigint not null references product_variant(id) on delete restrict,
  warehouse_id      bigint not null references warehouse(id) on delete restrict,
  movement_type     varchar(24) not null,
  quantity_delta    integer not null,
  quantity_after    integer not null,
  unit_cost         numeric(14,2),
  reference_type    varchar(24),
  reference_id      bigint,
  reason            varchar(200),
  performed_by_id   bigint references "user"(id) on delete set null,
  created_at        timestamptz not null default now(),
  constraint ck_mv_delta check (quantity_delta <> 0),
  constraint ck_mv_type  check (movement_type in
    ('receipt','sale','return','adjustment','damage','transfer_in','transfer_out','count'))
);
create index idx_mv_item_time  on inventory_movement (inventory_item_id, created_at desc);
create index idx_mv_reference  on inventory_movement (reference_type, reference_id);
create index idx_mv_type_time  on inventory_movement (movement_type, created_at desc);

create table stock_adjustment (
  id              bigserial primary key,
  public_id       uuid not null default gen_random_uuid(),
  warehouse_id    bigint not null references warehouse(id) on delete restrict,
  adjustment_type varchar(24) not null,
  reason          text not null,
  status          varchar(16) not null default 'draft',
  created_by_id   bigint references "user"(id) on delete set null,
  approved_by_id  bigint references "user"(id) on delete set null,
  applied_at      timestamptz,
  created_at      timestamptz not null default now(),
  constraint ck_adj_type   check (adjustment_type in
    ('count','damage','expiry','theft','correction','receipt')),
  constraint ck_adj_status check (status in ('draft','applied','cancelled'))
);

create table stock_adjustment_line (
  id             bigserial primary key,
  adjustment_id  bigint not null references stock_adjustment(id) on delete cascade,
  variant_id     bigint not null references product_variant(id) on delete restrict,
  quantity_delta integer not null,
  unit_cost      numeric(14,2),
  note           varchar(200),
  constraint ck_adjline_delta check (quantity_delta <> 0)
);

-- ============================================================================
-- 5. CART
-- ============================================================================

create table cart (
  id                  bigserial primary key,
  public_id           uuid not null default gen_random_uuid(),
  business_account_id bigint references business_account(id) on delete cascade,
  user_id             bigint references "user"(id) on delete set null,
  session_key         varchar(64),
  status              varchar(16) not null default 'active',
  currency            char(3) not null default 'NGN',
  promotion_id        bigint references promotion(id) on delete set null,
  delivery_address_id bigint references address(id) on delete set null,
  notes               text,
  converted_order_id  bigint,
  last_activity_at    timestamptz not null default now(),
  expires_at          timestamptz not null default (now() + interval '30 days'),
  created_at          timestamptz not null default now(),
  constraint uq_cart_public_id unique (public_id),
  constraint ck_cart_status check (status in ('active','converted','abandoned','merged'))
);
create unique index uq_cart_active_account on cart (business_account_id)
  where status = 'active' and business_account_id is not null;
create index idx_cart_session on cart (session_key) where status = 'active';
create index idx_cart_expiry  on cart (expires_at) where status = 'active';

create table cart_item (
  id                  bigserial primary key,
  cart_id             bigint not null references cart(id) on delete cascade,
  variant_id          bigint not null references product_variant(id) on delete restrict,
  quantity            integer not null,
  unit_price_snapshot numeric(14,2) not null,
  price_changed       boolean not null default false,
  added_at            timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint uq_cart_variant unique (cart_id, variant_id),
  constraint ck_cart_qty     check (quantity > 0)
);

-- ============================================================================
-- 6. ORDERS
-- ============================================================================

create sequence order_number_seq start 1000;
create sequence invoice_number_seq start 1000;

create table "order" (
  id                     bigserial primary key,
  public_id              uuid not null default gen_random_uuid(),
  order_number           varchar(24) not null,
  business_account_id    bigint not null references business_account(id) on delete restrict,
  placed_by_user_id      bigint not null references "user"(id) on delete restrict,
  status                 varchar(24) not null default 'pending_payment',
  payment_status         varchar(24) not null default 'pending',
  fulfilment_status      varchar(24) not null default 'unfulfilled',
  currency               char(3) not null default 'NGN',
  subtotal               numeric(14,2) not null,
  discount_total         numeric(14,2) not null default 0,
  delivery_fee           numeric(14,2) not null default 0,
  tax_total              numeric(14,2) not null default 0,
  grand_total            numeric(14,2) not null,
  amount_paid            numeric(14,2) not null default 0,
  amount_refunded        numeric(14,2) not null default 0,
  -- delivery address snapshot
  delivery_contact_name  varchar(150) not null,
  delivery_contact_phone varchar(32) not null,
  delivery_line1         varchar(200) not null,
  delivery_line2         varchar(200),
  delivery_city          varchar(100) not null,
  delivery_state         varchar(100) not null,
  delivery_postal_code   varchar(20),
  delivery_country       char(2) not null default 'NG',
  delivery_instructions  text,
  -- billing address snapshot
  billing_contact_name   varchar(150),
  billing_line1          varchar(200),
  billing_line2          varchar(200),
  billing_city           varchar(100),
  billing_state          varchar(100),
  billing_postal_code    varchar(20),
  billing_country        char(2),
  delivery_zone_id       bigint references delivery_zone(id) on delete set null,
  promotion_id           bigint references promotion(id) on delete set null,
  restricted_ack_at      timestamptz,
  restricted_ack_text    text,
  customer_note          text,
  internal_note          text,
  placed_at              timestamptz,
  paid_at                timestamptz,
  dispatched_at          timestamptz,
  delivered_at           timestamptz,
  cancelled_at           timestamptz,
  cancellation_reason    varchar(200),
  source                 varchar(16) not null default 'web',
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  constraint uq_order_number    unique (order_number),
  constraint uq_order_public_id unique (public_id),
  constraint ck_order_status check (status in
    ('pending_payment','payment_failed','paid','processing','dispatched',
     'delivered','cancelled','expired','returned')),
  constraint ck_order_payment check (payment_status in
    ('pending','initiated','paid','failed','cancelled','refunded','partially_refunded')),
  constraint ck_order_fulfil check (fulfilment_status in
    ('unfulfilled','processing','dispatched','delivered','returned')),
  constraint ck_order_source check (source in ('web','admin','rep','api')),
  -- an arithmetic bug can never persist a wrong invoice
  constraint ck_order_totals check
    (grand_total = subtotal - discount_total + delivery_fee + tax_total),
  constraint ck_order_refund check (amount_refunded <= amount_paid),
  constraint ck_order_amounts check
    (subtotal >= 0 and discount_total >= 0 and delivery_fee >= 0 and tax_total >= 0)
);
create index idx_order_account on "order" (business_account_id, created_at desc);
create index idx_order_status  on "order" (status, created_at desc);
create index idx_order_payment on "order" (payment_status)
  where payment_status in ('pending','initiated');
create index idx_order_fulfil  on "order" (fulfilment_status)
  where fulfilment_status <> 'delivered';
create index idx_order_queue   on "order" (status, placed_at)
  where status in ('paid','processing');
create index idx_order_history on "order" (business_account_id, created_at desc)
  include (order_number, status, grand_total);

alter table stock_reservation
  add constraint fk_res_order foreign key (order_id) references "order"(id) on delete set null,
  add constraint fk_res_cart  foreign key (cart_id)  references cart(id)    on delete set null;
alter table cart
  add constraint fk_cart_order foreign key (converted_order_id) references "order"(id) on delete set null;

create table order_item (
  id                 bigserial primary key,
  order_id           bigint not null references "order"(id) on delete cascade,
  variant_id         bigint not null references product_variant(id) on delete restrict,
  sku                varchar(60) not null,
  product_name       varchar(250) not null,
  variant_name       varchar(200) not null,
  brand_name         varchar(150),
  image_url          varchar(500),
  selling_unit       varchar(12) not null,
  base_units         integer not null,
  quantity           integer not null,
  unit_price         numeric(14,2) not null,
  line_subtotal      numeric(14,2) not null,
  discount_amount    numeric(14,2) not null default 0,
  tax_rate           numeric(5,2) not null default 0,
  tax_amount         numeric(14,2) not null default 0,
  line_total         numeric(14,2) not null,
  is_restricted      boolean not null default false,
  quantity_fulfilled integer not null default 0,
  quantity_returned  integer not null default 0,
  constraint ck_oi_qty  check (quantity > 0),
  constraint ck_oi_line check (line_total = line_subtotal - discount_amount + tax_amount),
  constraint ck_oi_fulfil check (quantity_fulfilled <= quantity and quantity_returned <= quantity)
);
create index idx_oi_order   on order_item (order_id);
create index idx_oi_variant on order_item (variant_id);

create table order_status_history (
  id            bigserial primary key,
  order_id      bigint not null references "order"(id) on delete cascade,
  from_status   varchar(24),
  to_status     varchar(24) not null,
  changed_by_id bigint references "user"(id) on delete set null,
  note          text,
  created_at    timestamptz not null default now()
);
create index idx_osh_order on order_status_history (order_id, created_at);

-- ============================================================================
-- 7. PAYMENTS
-- ============================================================================

create table payment_attempt (
  id                 bigserial primary key,
  public_id          uuid not null default gen_random_uuid(),
  order_id           bigint not null references "order"(id) on delete restrict,
  provider           varchar(20) not null,
  provider_reference varchar(120) not null,
  internal_reference varchar(60) not null,
  amount             numeric(14,2) not null,
  currency           char(3) not null default 'NGN',
  status             varchar(20) not null default 'initiated',
  channel            varchar(24),
  authorization_code varchar(80),
  card_last4         char(4),
  card_brand         varchar(20),
  fees               numeric(14,2),
  gateway_response   text,
  raw_payload        jsonb,
  verified_at        timestamptz,
  failure_reason     varchar(200),
  ip_address         inet,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint uq_pay_internal_ref unique (internal_reference),
  constraint uq_pay_provider_ref unique (provider, provider_reference),
  constraint ck_pay_provider check (provider in ('paystack','flutterwave','bank_transfer')),
  constraint ck_pay_status check (status in
    ('initiated','pending','successful','failed','cancelled','abandoned')),
  constraint ck_pay_amount check (amount > 0)
);
create index idx_pay_order  on payment_attempt (order_id, created_at desc);
create index idx_pay_status on payment_attempt (status, created_at desc);
create index idx_pay_recon  on payment_attempt (provider, verified_at) where status = 'successful';

create table webhook_event (
  id              bigserial primary key,
  provider        varchar(20) not null,
  event_id        varchar(120) not null,
  event_type      varchar(60) not null,
  signature_valid boolean not null default false,
  payload         jsonb not null,
  status          varchar(16) not null default 'received',
  processed_at    timestamptz,
  error           text,
  attempts        smallint not null default 0,
  received_at     timestamptz not null default now(),
  -- the entire idempotency guarantee for webhook delivery
  constraint uq_webhook_event unique (provider, event_id),
  constraint ck_webhook_status check (status in ('received','processed','failed','ignored'))
);
create index idx_webhook_status on webhook_event (status, received_at)
  where status in ('received','failed');

create table refund (
  id                 bigserial primary key,
  public_id          uuid not null default gen_random_uuid(),
  order_id           bigint not null references "order"(id) on delete restrict,
  payment_attempt_id bigint not null references payment_attempt(id) on delete restrict,
  amount             numeric(14,2) not null,
  reason             varchar(200) not null,
  refund_type        varchar(16) not null,
  status             varchar(16) not null default 'pending',
  provider_reference varchar(120),
  requested_by_id    bigint references "user"(id) on delete set null,
  approved_by_id     bigint references "user"(id) on delete set null,
  restock            boolean not null default true,
  completed_at       timestamptz,
  created_at         timestamptz not null default now(),
  constraint ck_refund_amount check (amount > 0),
  constraint ck_refund_type   check (refund_type in ('full','partial')),
  constraint ck_refund_status check (status in ('pending','processing','completed','failed')),
  -- separation of duties: requester cannot approve
  constraint ck_refund_approver check (approved_by_id is null or approved_by_id <> requested_by_id)
);
create index idx_refund_order on refund (order_id);

create table refund_line (
  id            bigserial primary key,
  refund_id     bigint not null references refund(id) on delete cascade,
  order_item_id bigint not null references order_item(id) on delete restrict,
  quantity      integer not null,
  amount        numeric(14,2) not null,
  constraint ck_refundline_qty check (quantity > 0)
);

create table invoice (
  id                  bigserial primary key,
  public_id           uuid not null default gen_random_uuid(),
  invoice_number      varchar(24) not null,
  order_id            bigint not null references "order"(id) on delete restrict,
  business_account_id bigint not null references business_account(id) on delete restrict,
  issue_date          date not null default current_date,
  due_date            date,
  subtotal            numeric(14,2) not null,
  tax_total           numeric(14,2) not null default 0,
  total               numeric(14,2) not null,
  amount_paid         numeric(14,2) not null default 0,
  status              varchar(16) not null default 'draft',
  pdf_url             varchar(500),
  issued_at           timestamptz,
  created_at          timestamptz not null default now(),
  constraint uq_invoice_number unique (invoice_number),
  constraint ck_invoice_status check (status in ('draft','issued','paid','void'))
);
create index idx_invoice_account on invoice (business_account_id, issue_date desc);

-- ============================================================================
-- 8. DELIVERY
-- ============================================================================

create table delivery_zone_area (
  id          bigserial primary key,
  zone_id     bigint not null references delivery_zone(id) on delete cascade,
  match_type  varchar(16) not null,
  match_value varchar(120) not null,
  constraint uq_dza unique (zone_id, match_type, match_value),
  constraint ck_dza_type check (match_type in ('city','state','postal','lga'))
);
create index idx_dza_lookup on delivery_zone_area (match_type, lower(match_value));

create table delivery_rate (
  id                 bigserial primary key,
  zone_id            bigint not null references delivery_zone(id) on delete cascade,
  name               varchar(100) not null,
  rate_type          varchar(16) not null default 'flat',
  base_fee           numeric(14,2) not null default 0,
  per_kg_fee         numeric(14,2),
  min_order_value    numeric(14,2),
  max_order_value    numeric(14,2),
  free_above_amount  numeric(14,2),
  estimated_days_min smallint,
  estimated_days_max smallint,
  is_active          boolean not null default true,
  priority           smallint not null default 0,
  constraint ck_rate_type check (rate_type in ('flat','weight','order_value','free')),
  constraint ck_rate_band check (max_order_value is null or min_order_value is null
                                 or max_order_value > min_order_value)
);
create index idx_rate_zone on delivery_rate (zone_id, priority) where is_active;

create table shipment (
  id                 bigserial primary key,
  public_id          uuid not null default gen_random_uuid(),
  order_id           bigint not null references "order"(id) on delete cascade,
  warehouse_id       bigint not null references warehouse(id) on delete restrict,
  shipment_number    varchar(24) not null unique,
  status             varchar(16) not null default 'pending',
  carrier            varchar(100),
  tracking_reference varchar(120),
  driver_name        varchar(150),
  driver_phone       varchar(32),
  vehicle_reference  varchar(60),
  dispatched_at      timestamptz,
  delivered_at       timestamptz,
  delivery_proof_url varchar(500),
  received_by        varchar(150),
  failure_reason     varchar(200),
  notes              text,
  created_at         timestamptz not null default now(),
  constraint ck_shipment_status check (status in
    ('pending','packed','dispatched','delivered','failed','returned'))
);
create index idx_shipment_order on shipment (order_id);

create table shipment_item (
  id            bigserial primary key,
  shipment_id   bigint not null references shipment(id) on delete cascade,
  order_item_id bigint not null references order_item(id) on delete restrict,
  quantity      integer not null,
  constraint ck_shipitem_qty check (quantity > 0)
);

-- ============================================================================
-- 9. CONTENT & ENGAGEMENT
-- ============================================================================

create table review (
  id                   bigserial primary key,
  public_id            uuid not null default gen_random_uuid(),
  product_id           bigint not null references product(id) on delete cascade,
  business_account_id  bigint references business_account(id) on delete set null,
  user_id              bigint references "user"(id) on delete set null,
  order_id             bigint references "order"(id) on delete set null,
  rating               smallint not null,
  title                varchar(150),
  body                 text,
  status               varchar(16) not null default 'pending',
  is_verified_purchase boolean not null default false,
  moderated_by_id      bigint references "user"(id) on delete set null,
  helpful_count        integer not null default 0,
  created_at           timestamptz not null default now(),
  constraint ck_review_rating check (rating between 1 and 5),
  constraint ck_review_status check (status in ('pending','approved','rejected','spam'))
);
create index idx_review_product on review (product_id, status, created_at desc);
create unique index uq_review_order_product on review (order_id, product_id)
  where order_id is not null;

create table wishlist (
  id                  bigserial primary key,
  business_account_id bigint not null references business_account(id) on delete cascade,
  name                varchar(100) not null default 'Wishlist',
  is_default          boolean not null default true,
  created_at          timestamptz not null default now()
);

create table wishlist_item (
  id          bigserial primary key,
  wishlist_id bigint not null references wishlist(id) on delete cascade,
  variant_id  bigint not null references product_variant(id) on delete cascade,
  note        varchar(200),
  added_at    timestamptz not null default now(),
  constraint uq_wishlist_variant unique (wishlist_id, variant_id)
);

create table notification (
  id                  bigserial primary key,
  user_id             bigint not null references "user"(id) on delete cascade,
  channel             varchar(16) not null,
  template_code       varchar(60) not null,
  subject             varchar(200),
  payload             jsonb not null default '{}'::jsonb,
  status              varchar(16) not null default 'queued',
  provider_message_id varchar(120),
  sent_at             timestamptz,
  read_at             timestamptz,
  error               text,
  created_at          timestamptz not null default now(),
  constraint ck_notif_channel check (channel in ('email','sms','whatsapp','in_app')),
  constraint ck_notif_status  check (status in ('queued','sent','failed','read'))
);
create index idx_notif_user on notification (user_id, created_at desc);

-- ============================================================================
-- 10. SEARCH & MERCHANDISING
-- ============================================================================

create table search_query_log (
  id                  bigserial primary key,
  query               varchar(200) not null,
  normalised_query    varchar(200) not null,
  business_account_id bigint references business_account(id) on delete set null,
  result_count        integer not null default 0,
  clicked_variant_id  bigint references product_variant(id) on delete set null,
  created_at          timestamptz not null default now()
);
create index idx_sql_norm on search_query_log (normalised_query, created_at desc);
-- what customers look for that D2R does not stock
create index idx_sql_zero on search_query_log (normalised_query) where result_count = 0;

create table banner (
  id                bigserial primary key,
  placement         varchar(40) not null,
  title             varchar(200),
  subtitle          varchar(300),
  cta_label         varchar(60),
  cta_url           varchar(500),
  image_url         varchar(500) not null,
  mobile_image_url  varchar(500),
  background_colour varchar(9),
  starts_at         timestamptz,
  ends_at           timestamptz,
  sort_order        integer not null default 0,
  is_active         boolean not null default true,
  created_at        timestamptz not null default now()
);
create index idx_banner_placement on banner (placement, sort_order) where is_active;

-- ============================================================================
-- 11. AUDIT & OPERATIONS
-- ============================================================================

create table audit_log (
  id          bigserial primary key,
  actor_id    bigint references "user"(id) on delete set null,
  actor_type  varchar(16) not null default 'system',
  action      varchar(60) not null,
  object_type varchar(60) not null,
  object_id   bigint not null,
  object_repr varchar(200),
  changes     jsonb,
  reason      varchar(300),
  ip_address  inet,
  user_agent  varchar(300),
  request_id  uuid,
  created_at  timestamptz not null default now(),
  constraint ck_audit_actor check (actor_type in ('staff','customer','system','webhook'))
);
create index idx_audit_object on audit_log (object_type, object_id, created_at desc);
create index idx_audit_actor  on audit_log (actor_id, created_at desc);
create index idx_audit_action on audit_log (action, created_at desc);

create table import_job (
  id              bigserial primary key,
  public_id       uuid not null default gen_random_uuid(),
  job_type        varchar(24) not null,
  file_url        varchar(500) not null,
  file_name       varchar(200) not null,
  status          varchar(16) not null default 'pending',
  total_rows      integer not null default 0,
  processed_rows  integer not null default 0,
  success_rows    integer not null default 0,
  error_rows      integer not null default 0,
  errors          jsonb,
  dry_run         boolean not null default true,
  created_by_id   bigint references "user"(id) on delete set null,
  started_at      timestamptz,
  completed_at    timestamptz,
  created_at      timestamptz not null default now(),
  constraint ck_import_type   check (job_type in ('products','prices','inventory','customers')),
  constraint ck_import_status check (status in
    ('pending','validating','ready','processing','completed','failed'))
);

create table idempotency_key (
  id              bigserial primary key,
  key             varchar(120) not null,
  user_id         bigint references "user"(id) on delete cascade,
  endpoint        varchar(120) not null,
  request_hash    char(64) not null,
  response_status smallint,
  response_body   jsonb,
  status          varchar(16) not null default 'in_progress',
  created_at      timestamptz not null default now(),
  expires_at      timestamptz not null default (now() + interval '24 hours'),
  constraint uq_idem unique (key, endpoint),
  constraint ck_idem_status check (status in ('in_progress','completed'))
);
create index idx_idem_expiry on idempotency_key (expires_at);

create table setting (
  id            bigserial primary key,
  key           varchar(80) not null unique,
  value         jsonb not null,
  value_type    varchar(16) not null default 'string',
  description   text,
  is_public     boolean not null default false,
  updated_by_id bigint references "user"(id) on delete set null,
  updated_at    timestamptz not null default now()
);

commit;

-- ============================================================================
-- Seed data
-- ============================================================================

begin;

insert into staff_role (code, name, description, is_system) values
  ('admin',     'Administrator',    'Full access', true),
  ('catalogue', 'Catalogue',        'Products, prices, promotions', true),
  ('inventory', 'Inventory',        'Stock and adjustments', true),
  ('ops',       'Operations',       'Orders and fulfilment', true),
  ('finance',   'Finance',          'Payments, refunds, reconciliation', true),
  ('support',   'Customer Support', 'Read-only customer and order access', true),
  ('sales',     'Sales',            'Customer accounts and assisted ordering', true);

insert into tax_class (code, name, rate_percent, is_inclusive) values
  ('standard', 'Standard VAT', 7.50, false),
  ('zero',     'Zero rated',   0.00, false),
  ('exempt',   'Exempt',       0.00, false);

insert into customer_group (code, name, discount_percent, priority) values
  ('standard',    'Standard',    0.00, 0),
  ('gold',        'Gold',        2.50, 10),
  ('key_account', 'Key Account', 5.00, 20);

insert into warehouse (code, name, is_default, priority) values
  ('IKD', 'Ikorodu Fulfilment Centre', true, 0);

-- Coverage axes from the D2R pitch deck
insert into delivery_zone (code, name, sort_order) values
  ('LAG-KMS', 'Kosofe / Mushin / Shomolu',        1),
  ('LAG-AAA', 'Amuwo Odofin / Ajeromi / Apapa',   2),
  ('LAG-EIL', 'Eti Osa / Ibeju Lekki / Lagos Island', 3),
  ('LAG-SYE', 'Surulere / Yaba / Ebute Metta',    4),
  ('LAG-IKD', 'Ikorodu Axis',                     5);

insert into attribute (code, name, data_type, is_filterable, sort_order) values
  ('size',      'Size',      'text',   true, 1),
  ('colour',    'Colour',    'colour', true, 2),
  ('pack_size', 'Pack Size', 'text',   true, 3),
  ('flavour',   'Flavour',   'text',   true, 4);

insert into setting (key, value, value_type, description, is_public) values
  ('accounts.require_approval',            'true',  'boolean', 'New accounts need staff approval before ordering', true),
  ('accounts.hide_prices_until_approved',  'true',  'boolean', 'Hide prices from unapproved accounts', true),
  ('checkout.reservation_ttl_minutes',     '20',    'number',  'How long stock is held during payment', false),
  ('checkout.min_order_value',             '0',     'number',  'Minimum order value in NGN', true),
  ('payment.active_gateway',               '"paystack"', 'string', 'Primary payment provider', false),
  ('delivery.free_above',                  'null',  'number',  'Free delivery threshold in NGN', true),
  ('tax.prices_include_tax',               'false', 'boolean', 'Whether displayed prices include VAT', true),
  ('restricted.require_acknowledgement',   'true',  'boolean', 'Require checkout acknowledgement for restricted items', true);

commit;

-- ============================================================================
-- 12. DISPATCH, FLEET & DELIVERY  (see 08-dispatch-delivery.md)
-- ============================================================================

begin;

create table driver (
  id             bigserial primary key,
  public_id      uuid not null default gen_random_uuid(),
  user_id        bigint references "user"(id) on delete set null,
  code           varchar(20) not null unique,
  full_name      varchar(150) not null,
  phone          varchar(32) not null,
  licence_number varchar(60),
  licence_expiry date,
  home_zone_id   bigint references delivery_zone(id) on delete set null,
  status         varchar(16) not null default 'active',
  cash_limit     numeric(14,2),
  notes          text,
  created_at     timestamptz not null default now(),
  constraint ck_driver_status check (status in ('active','on_leave','suspended','inactive'))
);
create index idx_driver_status on driver (status);

create table vehicle (
  id                     bigserial primary key,
  code                   varchar(20) not null unique,
  registration           varchar(20) not null unique,
  vehicle_type           varchar(20) not null default 'van',
  capacity_kg            numeric(9,2),
  capacity_volume_m3     numeric(7,3),
  warehouse_id           bigint not null references warehouse(id) on delete restrict,
  status                 varchar(16) not null default 'available',
  insurance_expiry       date,
  roadworthiness_expiry  date,
  created_at             timestamptz not null default now(),
  constraint ck_vehicle_type   check (vehicle_type in ('van','truck','bike','tricycle')),
  constraint ck_vehicle_status check (status in ('available','on_trip','maintenance','retired'))
);

create table route (
  id                 bigserial primary key,
  code               varchar(20) not null unique,
  name               varchar(150) not null,
  zone_id            bigint not null references delivery_zone(id) on delete restrict,
  days_of_week       smallint[] not null,
  cut_off_time       time not null default '16:00',
  default_driver_id  bigint references driver(id) on delete set null,
  default_vehicle_id bigint references vehicle(id) on delete set null,
  max_stops          smallint,
  is_active          boolean not null default true,
  created_at         timestamptz not null default now()
);
create index idx_route_zone on route (zone_id) where is_active;

create table trip (
  id                bigserial primary key,
  public_id         uuid not null default gen_random_uuid(),
  trip_number       varchar(24) not null unique,
  route_id          bigint references route(id) on delete set null,
  warehouse_id      bigint not null references warehouse(id) on delete restrict,
  driver_id         bigint not null references driver(id) on delete restrict,
  vehicle_id        bigint not null references vehicle(id) on delete restrict,
  scheduled_date    date not null,
  status            varchar(20) not null default 'planned',
  stop_count        smallint not null default 0,
  total_weight_kg   numeric(9,2),
  total_value       numeric(14,2) not null default 0,
  cash_expected     numeric(14,2) not null default 0,
  cash_collected    numeric(14,2) not null default 0,
  cash_remitted     numeric(14,2) not null default 0,
  odometer_start    integer,
  odometer_end      integer,
  departed_at       timestamptz,
  returned_at       timestamptz,
  dispatched_by_id  bigint references "user"(id) on delete set null,
  reconciled_by_id  bigint references "user"(id) on delete set null,
  reconciled_at     timestamptz,
  notes             text,
  created_at        timestamptz not null default now(),
  cash_variance     numeric(14,2) generated always as (cash_remitted - cash_expected) stored,
  constraint ck_trip_status check (status in
    ('planned','loading','dispatched','in_progress','completed','cancelled')),
  constraint ck_trip_cash check (cash_collected >= 0 and cash_remitted >= 0 and cash_expected >= 0),
  constraint ck_trip_odo  check (odometer_end is null or odometer_start is null
                                 or odometer_end >= odometer_start)
);
create index idx_trip_date    on trip (scheduled_date, status);
create index idx_trip_driver  on trip (driver_id, scheduled_date desc);
-- finance queue: trips back at base whose cash has not been counted
create index idx_trip_unrecon on trip (scheduled_date)
  where status = 'completed' and reconciled_at is null;

create table trip_stop (
  id             bigserial primary key,
  trip_id        bigint not null references trip(id) on delete cascade,
  shipment_id    bigint not null references shipment(id) on delete restrict,
  sequence       smallint not null,
  status         varchar(20) not null default 'pending',
  eta            timestamptz,
  arrived_at     timestamptz,
  completed_at   timestamptz,
  cash_due       numeric(14,2) not null default 0,
  cash_received  numeric(14,2) not null default 0,
  receiver_name  varchar(150),
  receiver_phone varchar(32),
  signature_url  varchar(500),
  photo_url      varchar(500),
  latitude       numeric(9,6),
  longitude      numeric(9,6),
  failure_reason varchar(40),
  failure_note   text,
  attempt_number smallint not null default 1,
  created_at     timestamptz not null default now(),
  constraint uq_stop     unique (trip_id, shipment_id),
  constraint uq_stop_seq unique (trip_id, sequence),
  constraint ck_stop_status check (status in
    ('pending','arrived','delivered','partial','failed','rescheduled')),
  constraint ck_stop_cash check (cash_received >= 0 and cash_received <= cash_due + 0.01),
  constraint ck_stop_fail check (failure_reason is null or failure_reason in
    ('shop_closed','customer_absent','refused_delivery','payment_unavailable',
     'wrong_address','access_denied','vehicle_breakdown','security_incident',
     'weather','out_of_time'))
);
create index idx_stop_ship on trip_stop (shipment_id);
create index idx_stop_trip on trip_stop (trip_id, sequence);

create table delivery_exception (
  id               bigserial primary key,
  trip_stop_id     bigint not null references trip_stop(id) on delete cascade,
  shipment_item_id bigint not null references shipment_item(id) on delete restrict,
  exception_type   varchar(24) not null,
  quantity         integer not null,
  reason           varchar(200),
  photo_url        varchar(500),
  resolution       varchar(24),
  resolved_by_id   bigint references "user"(id) on delete set null,
  resolved_at      timestamptz,
  created_at       timestamptz not null default now(),
  constraint ck_exc_type check (exception_type in
    ('short_delivered','damaged','rejected','wrong_item','expired')),
  constraint ck_exc_res  check (resolution is null or resolution in
    ('credit_note','replace','refund','none')),
  constraint ck_exc_qty  check (quantity > 0)
);
create index idx_exc_stop        on delivery_exception (trip_stop_id);
create index idx_exc_unresolved  on delivery_exception (created_at) where resolved_at is null;

create table courier_account (
  id                  bigserial primary key,
  code                varchar(20) not null unique,
  name                varchar(150) not null,
  provider            varchar(24) not null,
  api_credentials_ref varchar(120),
  supports_cod        boolean not null default false,
  is_active           boolean not null default true,
  created_at          timestamptz not null default now()
);

alter table business_account add column cod_allowed boolean not null default false;
alter table delivery_zone   add column cod_allowed boolean not null default false;
alter table shipment        add column trip_id bigint references trip(id) on delete set null;
create index idx_shipment_trip on shipment (trip_id);

commit;

-- ============================================================================
-- 13. PROCUREMENT & BATCH TRACKING  (see 09-procurement-batches.md)
-- ============================================================================

begin;

create table purchase_order (
  id                 bigserial primary key,
  public_id          uuid not null default gen_random_uuid(),
  po_number          varchar(24) not null unique,
  vendor_id          bigint not null references vendor(id) on delete restrict,
  warehouse_id       bigint not null references warehouse(id) on delete restrict,
  status             varchar(24) not null default 'draft',
  currency           char(3) not null default 'NGN',
  subtotal           numeric(14,2) not null default 0,
  tax_total          numeric(14,2) not null default 0,
  shipping_cost      numeric(14,2) not null default 0,
  other_charges      numeric(14,2) not null default 0,
  grand_total        numeric(14,2) not null default 0,
  expected_date      date,
  payment_terms_days smallint,
  created_by_id      bigint references "user"(id) on delete set null,
  approved_by_id     bigint references "user"(id) on delete set null,
  approved_at        timestamptz,
  sent_at            timestamptz,
  received_at        timestamptz,
  notes              text,
  created_at         timestamptz not null default now(),
  constraint ck_po_status check (status in
    ('draft','pending_approval','approved','sent','partially_received','received','cancelled')),
  -- separation of duties: raiser cannot approve their own PO
  constraint ck_po_approver check (approved_by_id is null or approved_by_id <> created_by_id)
);
create index idx_po_vendor on purchase_order (vendor_id, created_at desc);
create index idx_po_open   on purchase_order (expected_date)
  where status in ('approved','sent','partially_received');

create table purchase_order_line (
  id                   bigserial primary key,
  purchase_order_id    bigint not null references purchase_order(id) on delete cascade,
  variant_id           bigint not null references product_variant(id) on delete restrict,
  quantity_ordered     integer not null,
  quantity_received    integer not null default 0,
  unit_cost            numeric(14,2) not null,
  line_total           numeric(14,2) not null,
  expected_expiry_date date,
  constraint ck_pol_qty  check (quantity_ordered > 0),
  constraint ck_pol_recv check (quantity_received >= 0 and quantity_received <= quantity_ordered)
);
create index idx_pol_po on purchase_order_line (purchase_order_id);

create table goods_receipt (
  id                bigserial primary key,
  public_id         uuid not null default gen_random_uuid(),
  grn_number        varchar(24) not null unique,
  purchase_order_id bigint not null references purchase_order(id) on delete restrict,
  warehouse_id      bigint not null references warehouse(id) on delete restrict,
  delivery_note_ref varchar(60),
  status            varchar(16) not null default 'draft',
  received_by_id    bigint references "user"(id) on delete set null,
  inspected_by_id   bigint references "user"(id) on delete set null,
  received_at       timestamptz not null default now(),
  accepted_at       timestamptz,
  notes             text,
  constraint ck_grn_status check (status in
    ('draft','inspecting','accepted','partially_accepted','rejected'))
);
create index idx_grn_po on goods_receipt (purchase_order_id);

create table inventory_batch (
  id                 bigserial primary key,
  inventory_item_id  bigint not null references inventory_item(id) on delete cascade,
  variant_id         bigint not null references product_variant(id) on delete restrict,
  warehouse_id       bigint not null references warehouse(id) on delete restrict,
  lot_number         varchar(60) not null,
  supplier_batch_ref varchar(60),
  manufactured_date  date,
  expiry_date        date,
  best_before_date   date,
  quantity_received  integer not null,
  quantity_on_hand   integer not null default 0,
  quantity_reserved  integer not null default 0,
  unit_cost          numeric(14,2),
  goods_receipt_id   bigint references goods_receipt(id) on delete set null,
  status             varchar(16) not null default 'available',
  received_at        timestamptz not null default now(),
  quantity_available integer generated always as (quantity_on_hand - quantity_reserved) stored,
  constraint uq_batch     unique (inventory_item_id, lot_number),
  constraint ck_batch_qty check (quantity_on_hand >= 0 and quantity_reserved >= 0
                                 and quantity_reserved <= quantity_on_hand),
  constraint ck_batch_status check (status in
    ('available','quarantine','expired','recalled','depleted'))
);
-- the FEFO pick order
create index idx_batch_fefo on inventory_batch (variant_id, warehouse_id, expiry_date)
  where status = 'available' and quantity_available > 0;
create index idx_batch_expiring on inventory_batch (expiry_date) where status = 'available';

create table goods_receipt_line (
  id                 bigserial primary key,
  goods_receipt_id   bigint not null references goods_receipt(id) on delete cascade,
  po_line_id         bigint not null references purchase_order_line(id) on delete restrict,
  variant_id         bigint not null references product_variant(id) on delete restrict,
  quantity_received  integer not null,
  quantity_accepted  integer not null default 0,
  quantity_rejected  integer not null default 0,
  rejection_reason   varchar(200),
  lot_number         varchar(60),
  expiry_date        date,
  manufactured_date  date,
  unit_cost          numeric(14,2),
  inventory_batch_id bigint references inventory_batch(id) on delete set null,
  constraint ck_grl_qty check (quantity_received > 0
    and quantity_accepted + quantity_rejected <= quantity_received)
);
create index idx_grl_grn on goods_receipt_line (goods_receipt_id);

-- the recall trail: which lots went to which customer order
create table order_item_batch (
  id                 bigserial primary key,
  order_item_id      bigint not null references order_item(id) on delete cascade,
  inventory_batch_id bigint not null references inventory_batch(id) on delete restrict,
  quantity           integer not null,
  constraint uq_oib unique (order_item_id, inventory_batch_id),
  constraint ck_oib_qty check (quantity > 0)
);
create index idx_oib_batch on order_item_batch (inventory_batch_id);

create table supplier_invoice (
  id                bigserial primary key,
  public_id         uuid not null default gen_random_uuid(),
  invoice_number    varchar(60) not null,
  vendor_id         bigint not null references vendor(id) on delete restrict,
  purchase_order_id bigint references purchase_order(id) on delete set null,
  goods_receipt_id  bigint references goods_receipt(id) on delete set null,
  invoice_date      date not null,
  due_date          date,
  subtotal          numeric(14,2) not null,
  tax_total         numeric(14,2) not null default 0,
  total             numeric(14,2) not null,
  amount_paid       numeric(14,2) not null default 0,
  receipt_value     numeric(14,2) not null default 0,
  status            varchar(16) not null default 'pending',
  approved_by_id    bigint references "user"(id) on delete set null,
  created_at        timestamptz not null default now(),
  match_variance    numeric(14,2) generated always as (total - receipt_value) stored,
  -- prevents paying the same vendor invoice twice
  constraint uq_supplier_invoice unique (vendor_id, invoice_number),
  constraint ck_si_status check (status in ('pending','matched','disputed','approved','paid')),
  constraint ck_si_paid   check (amount_paid <= total)
);
create index idx_si_unpaid on supplier_invoice (due_date)
  where status in ('approved','matched') and amount_paid < total;

-- minimum remaining shelf life before a batch stops being sellable
alter table category add column min_shelf_life_days smallint not null default 0;

commit;
