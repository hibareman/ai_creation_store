# AI Store Backend

A multi-tenant e-commerce backend built with **Django** and **Django REST Framework**, designed to support store creation, store management, product/catalog operations, order management, public storefront flows, and AI-assisted draft store setup.

---

## Overview

This project provides the backend for an AI-powered store platform where each store owner manages their own isolated store data, while public visitors can browse products, use a mock cart, and place orders.

The system is built with a **layered architecture**:

- **Views** → request/response orchestration
- **Services** → business logic
- **Selectors** → read/query layer
- **Models** → persistence layer

It also enforces **strict multi-tenant isolation** using `tenant_id` and store ownership checks.

---

## Main Features

### Authentication & Users
- User registration
- Email activation
- JWT login
- Current authenticated user endpoint
- Role-based access (`Store Owner`, `Super Admin`)

### Multi-Tenant Store Management
- Store creation and update
- Store settings
- Store publish / unpublish
- Store subdomain support
- Public store detail by subdomain
- Appearance / branding endpoints

### Categories & Products
- Category CRUD
- Product CRUD
- Product inventory update
- Product image management
- Public store products list
- Public product detail by store subdomain
- Unified product response DTOs for frontend usage

### Orders
#### Owner Side
- Store dashboard
- Customers list
- Orders list
- Order detail
- Order status update

#### Public Side
- Public direct order creation
- Mock cart
- Checkout from cart

### AI Store Creation Workflow
- Start AI draft
- Clarification rounds
- Full regenerate
- Partial regenerate
- Apply draft to store

### API Documentation
- OpenAPI schema
- Swagger UI
- ReDoc

---

## Tech Stack

- **Python**
- **Django**
- **Django REST Framework**
- **SimpleJWT**
- **drf-spectacular**
- **PostgreSQL**
- **Redis / LocMemCache fallback**
- **Pillow**

Optional AI provider support:
- **OpenRouter**
- Local fallback/cache-based draft flow

---

## Architecture

The project follows a layered, maintainable backend architecture:

```text
views.py       -> HTTP handling only
services.py    -> business logic
selectors.py   -> read/query logic
models.py      -> database models
serializers.py -> validation + DTO formatting
````

### Key Rules

* No business logic inside serializers
* No DB query logic inside views
* Every owner-scoped query must respect:

  * `tenant_id`
  * `store_id`
  * `owner_id` where required
* Public endpoints only expose published / active store data

---

## Project Structure

```text
AI Store Backend
├── users/
├── stores/
├── categories/
├── products/
├── orders/
├── themes/
├── AI_Store_Creation_Service/
├── config/
└── utils/
```

---

## Implemented Modules

### `users`

Authentication, activation, login, identity endpoints.

### `stores`

Store CRUD, settings, publish flow, subdomain, public store detail.

### `themes`

Store appearance / branding configuration.

### `categories`

Store category management.

### `products`

Product CRUD, images, inventory, public product browsing.

### `orders`

Owner dashboard, owner orders/customers, public order creation, mock cart, checkout.

### `AI_Store_Creation_Service`

AI-assisted temporary draft generation and application workflow.

---

## Environment Variables

Create a `.env` file in the project root.

Example:

```env
SECRET_KEY=your-secret-key
DEBUG=True

DB_ENGINE=django.db.backends.postgresql
DB_NAME=ai_store_db
DB_USER=postgres
DB_PASSWORD=1234
DB_HOST=localhost
DB_PORT=5433

CORS_ALLOW_ALL_ORIGINS=True

AI_API_KEY=
AI_MODEL_NAME=google/gemma-4-31b-it:free
AI_TIMEOUT=240
AI_API_URL=https://openrouter.ai/api/v1/chat/completions
AI_HTTP_REFERER=http://localhost:8000
AI_APP_TITLE=AI Store Backend

AI_DRAFT_TTL=3600
AI_DRAFT_PREFIX=ai_draft

REDIS_URL=
CACHE_KEY_PREFIX=ai_store_creation
```

### Notes

* If `REDIS_URL` is not provided, the project uses **LocMemCache** as a safe local fallback.
* If `AI_API_KEY` is not configured, AI draft flow may fall back to clarification mode depending on the current provider behavior.

---

## Installation

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd <your-project-folder>
```

### 2. Create virtual environment

```bash
python -m venv .venv
```

### 3. Activate virtual environment

#### Windows

```bash
.venv\Scripts\activate
```

#### Linux / macOS

```bash
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Apply migrations

```bash
python manage.py migrate
```

### 6. Run development server

```bash
python manage.py runserver
```

---

## Running Tests

Run all tests:

```bash
python manage.py test
```

Run a specific app:

```bash
python manage.py test orders
```

Run system checks:

```bash
python manage.py check
```

---

## API Documentation

After running the server, API docs are available at:

* **Swagger UI**: `/api/docs/`
* **ReDoc**: `/api/redoc/`
* **OpenAPI Schema**: `/api/schema/`

---

## Example API Areas

### Owner Store Settings

* `GET /api/stores/{store_id}/settings/`
* `PATCH /api/stores/{store_id}/settings/`

### Owner Appearance

* `GET /api/stores/{store_id}/appearance/`
* `PATCH /api/stores/{store_id}/appearance/`

### Owner Orders

* `GET /api/stores/{store_id}/orders/`
* `GET /api/stores/{store_id}/orders/{order_id}/`
* `PATCH /api/stores/{store_id}/orders/{order_id}/status/`

### Public Store / Products

* `GET /api/public/store/{subdomain}/`
* `GET /api/public/store/{subdomain}/products/`
* `GET /api/public/store/{subdomain}/products/{product_id}/`

### Public Cart

* `GET /api/public/store/{subdomain}/cart/`
* `POST /api/public/store/{subdomain}/cart/items/`
* `PATCH /api/public/store/{subdomain}/cart/items/{product_id}/`
* `DELETE /api/public/store/{subdomain}/cart/items/{product_id}/`
* `DELETE /api/public/store/{subdomain}/cart/`

### Public Checkout

* `POST /api/public/store/{subdomain}/cart/checkout/`
* `POST /api/public/store/{subdomain}/orders/`

### AI Draft Workflow

* `POST /api/ai/stores/draft/start/`
* `GET /api/ai/stores/{store_id}/draft/`
* `POST /api/ai/stores/{store_id}/draft/clarify/`
* `POST /api/ai/stores/{store_id}/draft/regenerate/`
* `POST /api/ai/stores/{store_id}/draft/regenerate-section/`
* `POST /api/ai/stores/{store_id}/draft/apply/`

---

## Current Status

### Completed

* Authentication
* Multi-tenant store isolation
* Store settings
* Appearance / branding
* Categories
* Products
* Public product browsing
* Owner dashboard and order management
* Public direct order creation
* Mock cart
* Checkout from cart
* AI draft workflow
* Large test coverage for orders and AI flows
* API documentation improvements

### Planned / Future Work

* SEO module expansion
* Super Admin dashboard
* Billing / subscriptions
* Logo upload endpoint refinement
* Sitemap / robots / advanced SEO
* Additional analytics

---

## Multi-Tenant Security Notes

This project enforces isolation using:

* `tenant_id`
* store ownership checks
* public-store resolution only through published/active store lookup

All sensitive owner endpoints are protected and scoped to the authenticated store owner.

---

## Development Notes

* Use the existing layered structure for any new feature.
* Keep response contracts stable for frontend integration.
* Prefer minimal safe changes over broad refactors.
* Reuse existing services/selectors before introducing new patterns.

---

## License

This project is for academic / educational / prototype use unless otherwise specified.

