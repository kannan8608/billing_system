# Billing System

A Django + Django REST Framework billing/invoicing app, matching the
"Billing System" wireframe: a product catalog, a billing form (Page 1),
a generated-bill view (Page 2), and purchase history.

## Stack

- **Django 6.1** + **Django REST Framework 3.18** (tested versions, pinned in `requirements.txt`).
  The code has no version-specific features, so Django 4.2+ / DRF 3.14+ should also work if your
  environment can't install these exact versions.
- SQLite (zero-config; swap `DATABASES` in `billing_system/settings.py` for Postgres/MySQL in production).
- **Jinja2** templates for the billing pages (Page 1 / Page 2 / history), via Django's built-in
  Jinja2 backend. Django's own template engine is still enabled for `django.contrib.admin`.
- Plain JS `fetch()` (no frontend framework) for the async "Generate Bill" call, per the "no
  need for fancy CSS" / keep-it-simple note in the task.

## Project layout

```
billing_system/        # Django project settings, root URLs, Jinja2 environment
billing/
  models.py             # Product, Denomination, Purchase, PurchaseItem, BalanceDenomination
  serializers.py         # DRF serializers (input validation + output shapes)
  views.py                # REST API (ProductViewSet, GenerateBillAPIView, Purchase list/detail)
  web_views.py            # Server-rendered pages (Page 1, Page 2, history)
  utils.py                 # Money rounding, denomination-change algorithm, async email
  urls.py                   # billing app's API + web URL patterns
  admin.py                   # Django admin registration (CRUD for products, seed via UI)
  jinja2/billing/             # page1.html, page2.html, history.html, base.html
  management/commands/
    seed_products.py           # `manage.py seed_products` — sample data
  fixtures/seed_data.json      # Alternative: `manage.py loaddata billing/fixtures/seed_data.json`
  tests.py                     # Unit + API tests
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_products      # creates 5 sample products + the 500/50/20/10/5/2/1 denominations
python manage.py createsuperuser    # optional, for /admin/
python manage.py runserver
```

Then open:

- **Page 1 (billing form):** http://127.0.0.1:8000/
- **Purchase history:** http://127.0.0.1:8000/purchases/history/
- **Django admin (product CRUD):** http://127.0.0.1:8000/admin/
- **Browsable REST API:** http://127.0.0.1:8000/api/products/

## Running tests

```bash
python manage.py test billing
```

Covers: floor-rounding of the net price, the greedy change-denomination algorithm (including the
exact numbers from the wireframe's Page 2 example, and the "not enough denominations in the till"
error case), bill generation totals/stock decrement, insufficient-cash and unknown-product
rejections, and purchase history filtering.

## REST API

| Method | Endpoint                              | Purpose                                             |
|--------|----------------------------------------|------------------------------------------------------|
| GET/POST | `/api/products/`                     | List / create products                                |
| GET/PUT/PATCH/DELETE | `/api/products/<id>/`   | Retrieve / update / delete a product                   |
| POST   | `/api/purchases/generate-bill/`        | Generate a bill (the "Generate Bill" button)            |
| GET    | `/api/purchases/?customer_email=...`   | List a customer's previous purchases                     |
| GET    | `/api/purchases/<id>/`                 | Full detail of one purchase (Page 2 data)                 |

`POST /api/purchases/generate-bill/` body:

```json
{
  "customer_email": "customer@example.com",
  "items": [{"product_id": "SKU-1001", "quantity": 2}],
  "denominations": [{"value": 500, "count": 3}, {"value": 50, "count": 10}],
  "cash_paid": "3000.00"
}
```

## Design decisions & assumptions

Per the task's note ("if there is any doubt, implement based on assumptions and mention them"):

1. **Decimal instead of float for money.** The task spec says "float" for price/tax, but
   `float` is well known to introduce rounding errors in currency arithmetic (e.g.
   `0.1 + 0.2 != 0.3`). All money fields (`unit_price`, `tax_percentage`, totals, etc.) use
   Django's `DecimalField` / Python's `Decimal` instead, which is the standard production
   practice for financial data.

2. **The "Denominations" section on Page 1 = the shop's current till counts, not a persistent
   stock model.** The wireframe's note "the denominations are the values that are available in
   the shop" is read as: the cashier enters what's physically in the till *at the time of billing*
   (like counting a cash drawer at the start of a shift), which is then used to compute exact
   change for that one bill. This avoids the concurrency/consistency problems of a shared mutable
   "till stock" record being decremented by concurrent bills, while a `Denomination` lookup table
   still exists (admin-manageable) purely to define which denomination values are valid
   (500/50/20/10/5/2/1 seeded by default).

3. **Rounding rule.** "Rounded down value of the purchased items net price" is implemented as
   flooring the net price to the nearest whole currency unit (e.g. `2357.60 -> 2357.00`), matching
   the wireframe's Page 2 numbers exactly. The customer must pay at least this rounded amount;
   `balance_amount = cash_paid - rounded_net_price`.

4. **Change-denomination algorithm.** A greedy, highest-denomination-first algorithm is used to
   break the balance down into denomination counts, bounded by what the cashier said is available.
   If exact change can't be made from the available denominations, bill generation is rejected
   with a clear error (rather than silently giving incorrect change) — this is intentionally a
   hard validation, matching "production-ready" behavior for a POS/billing system.

5. **Async invoice email.** Emails are sent on a background `threading.Thread` rather than a task
   queue (Celery/RQ), so the project has no extra infrastructure dependency (broker + worker) and
   runs with a single `manage.py runserver`. The bill-generation API responds immediately once the
   bill is saved, and the email send happens after. `Purchase.email_sent` / `Purchase.email_error`
   record the outcome. For a larger production deployment, swap `send_invoice_email_async` in
   `billing/utils.py` for a Celery task — the call site in `views.py` would not need to change.

6. **Historical accuracy of past bills.** Each `PurchaseItem` snapshots the product's name, unit
   price, and tax percentage at the time of sale, so editing a product's price later does not
   retroactively change old invoices (standard invoicing practice).

7. **Product lookup key.** Products are looked up by the human-facing `product_id` field entered
   on the form (e.g. `SKU-1001`), which is distinct from Django's internal auto-incrementing `id`.

8. **Stock handling.** Stock availability is checked and then decremented atomically inside a
   database transaction when a bill is generated; insufficient stock for any line item rejects the
   whole bill (no partial bills).

## Email configuration

By default, `EMAIL_BACKEND` is the console backend — invoice emails are printed to the terminal
running `runserver`, so the project works out of the box with no SMTP account. To send real email,
set these environment variables before starting the server:

```bash
export DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
export DJANGO_EMAIL_HOST=smtp.gmail.com
export DJANGO_EMAIL_PORT=587
export DJANGO_EMAIL_USE_TLS=True
export DJANGO_EMAIL_HOST_USER=you@example.com
export DJANGO_EMAIL_HOST_PASSWORD=your-app-password
export DJANGO_DEFAULT_FROM_EMAIL=you@example.com
```

## Notes for evaluation

- `DEBUG=True` and `ALLOWED_HOSTS=["*"]` by default for ease of local evaluation; override via
  `DJANGO_DEBUG` / `DJANGO_ALLOWED_HOSTS` env vars for anything resembling production.
- SQLite is used so the project runs with zero external services. `db.sqlite3` is created by
  `manage.py migrate`.
- CSRF: the Page 1 "Generate Bill" JS reads the `csrftoken` cookie and sends it as `X-CSRFToken`,
  following Django's documented AJAX CSRF pattern, so the form also works correctly if CSRF
  enforcement is tightened later (e.g. by adding session-authenticated staff users).
