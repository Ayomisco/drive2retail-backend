# Security

Maps to PRD §12. Everything here is a build requirement, not a recommendation.

---

## 1. Authentication

### 1.1 Token model

| Token | Lifetime | Storage | Notes |
| --- | --- | --- | --- |
| Access (JWT) | 15 min | Memory in the Next.js BFF only | RS256, never in `localStorage` |
| Refresh (opaque) | 14 days, rotating | `httpOnly` `Secure` `SameSite=Lax` cookie | SHA-256 hash stored, never the raw value |
| Password reset | 30 min, single use | Emailed | Hashed at rest |
| Email verify | 24 h, single use | Emailed | Hashed at rest |
| OTP | 10 min, 5 attempts | Redis | Rate limited per phone |

**The browser never sees a token.** The BFF holds the pair and issues an
`httpOnly` session cookie. This eliminates the entire class of XSS token theft that
`localStorage`-based SPAs live with.

**Refresh rotation with reuse detection.** Every refresh issues a new token and
revokes the old one, linked via `auth_token.rotated_from_id`. Presenting an
already-rotated token means it was stolen: the whole chain is revoked and the user
is forced to re-authenticate. This is the standard OAuth 2.1 recommendation and it
is cheap to implement given the table already exists.

### 1.2 Passwords

- **Argon2id**, Django's `ARGON2` hasher, `time_cost=2 memory_cost=102400 parallelism=8`.
- Minimum 10 characters; checked against Django's `CommonPasswordValidator` and a
  breach list (`pwned-passwords` k-anonymity range query — never send the password).
- No composition rules (no "must contain a symbol"). Length and breach-checking are
  what actually work; composition rules push users toward `Password1!`.
- Changing a password revokes every refresh token for that user except the current
  session.

### 1.3 Lockout

`failed_login_count` increments on failure and resets on success. At 10 failures,
`locked_until = now() + 15 min`. Combined with the 5/min/IP and 10/hour/email
throttles, credential stuffing is impractical.

**Login always returns the same error and takes the same time** whether the email
exists or not — `invalid_credentials`, with a constant-time comparison against a
dummy hash when the user is absent. Password reset always returns `202` for the same
reason.

### 1.4 Staff MFA

**Mandatory** for every `user_type='staff'` account. TOTP, enrolled on first login,
with 10 single-use recovery codes stored hashed. A staff session that has not
completed MFA can reach nothing but the enrolment endpoint.

Staff sessions are 8 hours, not 14 days, and are bound to the IP that created them
(with a grace band for mobile networks).

---

## 2. Authorization

### 2.1 Three-layer check

Every request passes three gates. Missing any one is a vulnerability.

```
1  Authentication      Who is this?
2  Role permission     Is this role allowed to perform this action at all?
3  Object scope        Is this specific row theirs to touch?
```

Layer 3 is the one that gets skipped. `GET /account/orders/{n}` must filter by
`business_account_id` from the token — never trust the ID in the URL. Every
customer-facing queryset starts from the account, not from the model:

```python
# correct — scoping is structural, not conditional
def get_queryset(self):
    return Order.objects.filter(business_account=self.request.account)

# wrong — one forgotten check away from IDOR
Order.objects.get(order_number=n)
```

The base `AccountScopedViewSet` makes the correct form the default, so a developer
has to actively opt out to create the vulnerability.

### 2.2 Customer roles

| Capability | `owner` | `buyer` | `viewer` |
| --- | :-: | :-: | :-: |
| Browse catalogue | ✅ | ✅ | ✅ |
| See prices | ✅ | ✅ | ✅ |
| Manage cart | ✅ | ✅ | — |
| Place order | ✅ | ✅ | — |
| View order history | ✅ | ✅ | ✅ |
| Cancel order | ✅ | ✅ | — |
| Manage addresses | ✅ | — | — |
| Invite/remove members | ✅ | — | — |
| Edit business profile | ✅ | — | — |

### 2.3 Staff permission matrix

| Action | `admin` | `catalogue` | `inventory` | `ops` | `finance` | `support` | `sales` |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| View dashboard | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Create/edit products | ✅ | ✅ | — | — | — | — | — |
| Publish/archive products | ✅ | ✅ | — | — | — | — | — |
| Change prices | ✅ | ✅ | — | — | ✅ | — | — |
| Bulk price import | ✅ | ✅ | — | — | — | — | — |
| View inventory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Adjust stock | ✅ | — | ✅ | — | — | — | — |
| Approve stock adjustment | ✅ | — | — | — | — | — | — |
| View orders | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ |
| Change order status | ✅ | — | — | ✅ | — | — | — |
| Create shipment | ✅ | — | ✅ | ✅ | — | — | — |
| Cancel order | ✅ | — | — | ✅ | ✅ | — | — |
| View payments | ✅ | — | — | — | ✅ | ✅ | — |
| Request refund | ✅ | — | — | ✅ | ✅ | ✅ | — |
| **Approve refund** | ✅ | — | — | — | ✅ | — | — |
| Reconciliation view | ✅ | — | — | — | ✅ | — | — |
| View customers | ✅ | — | — | ✅ | ✅ | ✅ | ✅ |
| Approve/suspend customer | ✅ | — | — | — | — | — | ✅ |
| Edit delivery zones/rates | ✅ | — | — | ✅ | — | — | — |
| Manage promotions | ✅ | ✅ | — | — | ✅ | — | — |
| Manage staff & roles | ✅ | — | — | — | — | — | — |
| View audit log | ✅ | — | — | — | ✅ | — | — |
| Edit settings | ✅ | — | — | — | — | — | — |

**Separation of duties is deliberate.** The person who requests a refund cannot
approve it. The person who adjusts stock cannot approve their own adjustment. For a
distribution business where staff handle valuable inventory, this is the control that
matters most.

---

## 3. Payment security (PRD PAY-04, PAY-05, PAY-09)

| Requirement | Implementation |
| --- | --- |
| No raw card data | Cards are entered on the provider's page or via their JS SDK. D2R stores only `card_last4`, `card_brand`, `authorization_code`. **The checkout page has no card fields** — the template's `card_number`/`security_code` inputs must be removed. |
| Server-side verification | `GET /transaction/verify/{ref}` against the provider before any state change. A redirect never marks paid. |
| Webhook authenticity | HMAC-SHA512 over the **raw** body, compared with `hmac.compare_digest`. Body is read before parsing so no middleware can mutate it. |
| Webhook idempotency | `uq_webhook_event (provider, event_id)`. Insert first, work second. |
| Amount integrity | Verified amount and currency must equal the order's. Mismatch → manual review, never auto-paid. |
| Secrets | Environment only. Never in source, never in the database, never logged. |
| Provider IP allowlist | Optional second gate on webhook endpoints. |
| Replay window | Webhook events older than 5 minutes are rejected. |

**The template's card inputs are a liability.** `src/app/checkout/page-content.tsx`
collects `card_number` and `security_code`. Those fields must be deleted before
launch — collecting a PAN, even without storing it, drags D2R into PCI-DSS scope
that the provider-hosted flow otherwise avoids entirely.

---

## 4. Input handling

| Vector | Control |
| --- | --- |
| SQL injection | ORM parameterisation. Raw SQL only via `params=`, never f-strings. |
| XSS | React escapes by default. `dangerouslySetInnerHTML` is banned by lint. Any admin-authored HTML is sanitised with `nh3`/`bleach` on write. |
| CSRF | `SameSite=Lax` cookies + Django CSRF token on cookie-authenticated writes. Bearer-token API calls are not cookie-authenticated and so are not CSRF-exposed. |
| Mass assignment | Explicit `fields` on every serializer. `__all__` is banned by lint. |
| IDOR | Account-scoped querysets (§2.1) + `public_id` UUIDs in URLs. |
| File upload | Extension + MIME sniff + magic-byte check; images re-encoded through Pillow to strip payloads and EXIF; 10 MB cap; served from a separate origin. |
| SSRF | No user-supplied URLs are fetched server-side. |
| Open redirect | `next` parameters validated against an allowlist of internal paths. |
| Enumeration | Uniform auth errors; UUID public IDs; no "email already registered" on register — send a "you already have an account" email instead. |
| ReDoS | No user input compiled into regex. |
| Zip bomb | Import files size-capped and row-capped before parsing. |

### Validation happens twice, and the server wins

Client-side validation is UX. Server-side validation is security. MOQ, order
increments, price, stock, delivery eligibility and restricted-product rules are all
re-checked in the checkout transaction regardless of what the cart API returned
moments earlier.

---

## 5. Transport and headers

TLS 1.2+ only. HSTS with `max-age=31536000; includeSubDomains; preload`.

```
Content-Security-Policy: default-src 'self';
  script-src 'self' 'nonce-{random}' https://js.paystack.co;
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https://cdn.drive2retail.com;
  font-src 'self';
  connect-src 'self' https://api.paystack.co;
  frame-src https://checkout.paystack.com;
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self'
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=()
Cross-Origin-Opener-Policy: same-origin
```

`frame-ancestors 'none'` replaces `X-Frame-Options`. The nonce is generated per
request in the Next.js middleware — no `unsafe-inline` for scripts.

---

## 6. Secrets and configuration

- All secrets from environment variables, injected by the platform's secret manager.
- `.env` files are git-ignored; a committed `.env.example` documents every key with
  placeholder values.
- Separate credentials per environment. Staging never holds production keys.
- Rotation: payment keys and `SECRET_KEY` quarterly; database credentials on staff
  departure.
- A pre-commit hook (`gitleaks`) and CI secret scan block accidental commits.
- **`DEBUG=False` in every non-local environment**, enforced by a startup assertion
  that refuses to boot otherwise.

---

## 7. Data protection

### 7.1 Classification

| Class | Data | Handling |
| --- | --- | --- |
| Restricted | Password hashes, MFA secrets, payment tokens, API keys | Encrypted at rest, never logged, never in an export |
| Confidential | Business details, addresses, phone, order history, prices | Access-controlled, audited |
| Internal | Catalogue, stock levels, staff notes | Staff only |
| Public | Product names, images, descriptions | Cacheable at the edge |

### 7.2 Logging discipline

Structured JSON logs with a `request_id`. A field allowlist means new PII cannot
leak by accident — `password`, `token`, `authorization`, `card_number`, `cvv`,
`secret` and `signature` are redacted at the formatter, not at each call site.

Full webhook payloads are stored in `webhook_event.payload` for reconciliation, with
card and auth fields stripped before insert.

### 7.3 Retention

| Data | Retention | Basis |
| --- | --- | --- |
| Orders, invoices, payments | **7 years** | Nigerian tax/accounting |
| Inventory movements | 7 years | Audit trail |
| Audit log | 3 years, then archived to S3 | |
| Application logs | 90 days hot, 1 year cold | |
| Carts | 30 days after inactivity | |
| Auth tokens | Purged 30 days after expiry | |
| Search logs | 12 months, anonymised at 90 days | |
| Closed customer accounts | Anonymised after 7 years; orders retained with a tombstoned customer | |

PRD §17 leaves the exact figures open — these are defensible defaults pending
confirmation with D2R's accountant.

---

## 8. Availability and recovery

| Control | Target |
| --- | --- |
| Database backup | Nightly full + PITR (WAL) with 30-day retention |
| **Restore drill** | **Quarterly, timed, documented** — an untested backup is not a backup |
| RPO | ≤ 5 minutes |
| RTO | ≤ 4 hours |
| Object storage | Versioned, cross-region replicated |
| Monitoring | Sentry (errors), uptime probe on `/health`, Postgres/Redis metrics |
| Alerting | Payment failure rate > 5%, webhook backlog > 50, worker queue depth, disk > 80%, failed logins spike |

`/health` checks database connectivity, Redis, and Celery broker reachability, and
returns `503` if any is down so the load balancer stops routing.

---

## 9. Pre-launch security checklist

- [ ] `DEBUG=False`; `ALLOWED_HOSTS` restricted
- [ ] TLS + HSTS live; HTTP redirects to HTTPS
- [ ] All secrets in the secret manager; git history scanned clean
- [ ] Card fields removed from the checkout UI
- [ ] Webhook signature verification tested with a forged payload
- [ ] Duplicate webhook delivery tested — no double fulfilment
- [ ] Concurrent checkout on the last unit tested — exactly one succeeds
- [ ] IDOR tested: account A cannot read account B's order, invoice or address
- [ ] Staff MFA enforced; recovery codes issued
- [ ] Rate limits verified on login, register, forgot-password, checkout
- [ ] Restore drill completed and timed
- [ ] `pip-audit` / `npm audit` clean; CI gate enabled
- [ ] Permission matrix tested per role, including negative cases
- [ ] Audit log verified for every action in §2.3
- [ ] Penetration test by an independent party
