# AI Store Creation Backend

Production-style backend built with **Django + DRF** for a multi-tenant e-commerce system, including AI-assisted store draft generation and apply workflow.

## Implemented Features
- JWT authentication and account activation flow.
- Tenant isolation via middleware (`request.tenant_id`).
- Store management: Store, StoreSettings, StoreDomain, slug helpers.
- Category management with owner + tenant checks.
- Product management with images and inventory.
- Theme Foundation (template catalog + per-store theme config).
- AI Store Creation workflow:
  - start draft
  - get current draft
  - clarification rounds
  - full regenerate
  - partial regenerate (theme/categories/products)
  - apply draft
- Official fallback policy: **clarification-style fallback**.
- Lightweight AI audit logging.

---

## Prerequisites
- Python 3.12+
- PostgreSQL
- Redis (for temporary AI draft cache)

---

## Setup and Run (Ordered)

### 1) Clone and create virtual environment
```bash
git clone <repo-url>
cd ai_store_creation
python -m venv .venv
```

Linux/macOS:
```bash
source .venv/bin/activate
```

Windows PowerShell:
```powershell
.venv\Scripts\Activate.ps1
```

### 2) Install dependencies
```bash
pip install -r requirements.txt
```

### 3) Configure environment variables (`.env`)
Create or update `.env` in project root:

```env
# Django
SECRET_KEY=change-me
DEBUG=True

# Preferred DB config
DATABASE_URL=postgresql://postgres:1234@localhost:5433/ai_store_db

# Optional DATABASE_URL fallback
DB_ENGINE=django.db.backends.postgresql
DB_NAME=ai_store_db
DB_USER=postgres
DB_PASSWORD=1234
DB_HOST=localhost
DB_PORT=5433

# Cache / Redis (AI draft temp storage)
CACHE_BACKEND=redis
REDIS_CACHE_URL=redis://127.0.0.1:6379/1

# AI settings
AI_API_KEY=
AI_MODEL_NAME=gpt-5.2
AI_TIMEOUT=30
AI_DRAFT_TTL=3600
AI_DRAFT_PREFIX=ai_draft
```

Notes:
- Test mode uses local cache fallback automatically.
- You can force local cache in development with `CACHE_BACKEND=locmem`.

### 4) Run migrations
```bash
python manage.py migrate
```

### 5) Create admin user (recommended)
```bash
python manage.py createsuperuser
```

### 6) Start server
```bash
python manage.py runserver
```

---

## API Docs
- Swagger UI: `GET /api/docs/`
- ReDoc: `GET /api/redoc/`
- OpenAPI schema: `GET /api/schema/`

---

## Auth and Tenant Rules
- Protected endpoints require `Authorization: Bearer <access_token>`.
- `POST /api/auth/register/` is public.
- Do **not** pass `tenant_id` from client body/query.
- Tenant context is resolved by middleware from JWT and used server-side.

---

## Endpoint Reference

## 1) Auth (`/api/auth/`)

| Method | Path | Auth | Request Body | Description |
|---|---|---|---|---|
| POST | `/api/auth/register/` | Public | `username`, `email`, `password`, `role?` (self-registration supports `Store Owner`) | Register user and send activation email |
| POST | `/api/auth/login/` | Public | `email`, `password` | Login and return JWT tokens |
| GET | `/api/auth/me/` | Bearer | - | Return current authenticated identity |
| GET | `/api/auth/activate/{token}/` | Public | - | Activate account by UUID token |
| POST | `/api/auth/token/` | Public | SimpleJWT payload | JWT pair endpoint (compatibility route) |
| POST | `/api/auth/token/refresh/` | Public | `refresh` | Refresh access token |

---

## 2) Stores (`/api/stores/`)

| Method | Path | Auth | Request Body | Description |
|---|---|---|---|---|
| GET / POST | `/api/stores/` | Bearer | POST: `name` (required), `description?`, `slug?` | List user stores or create store |
| PUT / PATCH | `/api/stores/{id}/` | Bearer | Store editable fields | Update store |
| DELETE | `/api/stores/{id}/delete/` | Bearer | - | Delete store |
| GET / PATCH | `/api/stores/{store_id}/settings/` | Bearer | PATCH: `currency?`, `language?`, `timezone?` | Read/update store settings |
| POST | `/api/stores/slug/check/` | Bearer | `slug`, `store_id?` | Check slug availability |
| POST | `/api/stores/slug/suggest/` | Bearer | `name`, `store_id?`, `limit?` | Suggest slug options |
| GET / POST | `/api/stores/{store_id}/domains/` | Bearer | POST: `domain`, `is_primary?` | List/create store domains |
| GET / PATCH / DELETE | `/api/stores/{store_id}/domains/{domain_id}/` | Bearer | PATCH: `domain?`, `is_primary?` | Retrieve/update/delete one domain |

---

## 3) Categories

### Contract routes (primary)
Prefix: `/api/`

| Method | Path | Auth | Request Body | Description |
|---|---|---|---|---|
| GET / POST | `/api/stores/{store_id}/categories/` | Bearer | POST: `name`, `description?` | List/create categories for a store |
| GET / PUT / PATCH / DELETE | `/api/stores/{store_id}/categories/{category_id}/` | Bearer | PUT/PATCH: `name?`, `description?` | Category detail/update/delete |

### Legacy-compatible routes (temporary)
Prefix: `/api/categories/`

| Method | Path | Auth | Request Body | Description |
|---|---|---|---|---|
| GET / POST | `/api/categories/stores/{store_id}/categories/` | Bearer | POST: `name`, `description?` | Same behavior as primary route |
| GET / PUT / PATCH / DELETE | `/api/categories/stores/{store_id}/categories/{category_id}/` | Bearer | PUT/PATCH: `name?`, `description?` | Same behavior as primary route |

---

## 4) Products (`/api/products/`)

| Method | Path | Auth | Request Body | Description |
|---|---|---|---|---|
| GET / POST | `/api/products/{store_id}/products/` | Bearer | POST: `name`, `price`, `sku`, `category`, `description?`, `status?` | List/create products |
| GET / PUT / PATCH / DELETE | `/api/products/{store_id}/products/{product_id}/` | Bearer | PUT/PATCH: product fields | Retrieve/update/delete product |
| GET / POST | `/api/products/{store_id}/products/{product_id}/images/` | Bearer | POST: `image_file` or `image_url` | List/add product images |
| DELETE | `/api/products/{store_id}/products/{product_id}/images/{image_id}/` | Bearer | - | Delete one image |
| PUT / PATCH | `/api/products/{store_id}/products/{product_id}/inventory/` | Bearer | `stock_quantity` | Update inventory |

---

## 5) Themes (`/api/`)

| Method | Path | Auth | Request Body | Description |
|---|---|---|---|---|
| GET | `/api/stores/{store_id}/themes/templates/` | Bearer | - | List available theme templates |
| GET | `/api/stores/{store_id}/theme/` | Bearer | - | Get current store theme config |
| PATCH | `/api/stores/{store_id}/theme/` | Bearer | `theme_template?`, `primary_color?`, `secondary_color?`, `font_family?`, `logo_url?`, `banner_url?` | Update store theme config |

---

## 6) AI Store Creation (`/api/ai/`)

| Method | Path | Auth | Request Body | Description |
|---|---|---|---|---|
| POST | `/api/ai/stores/draft/start/` | Bearer | `name`, `user_store_description` | Create draft store and generate initial AI draft |
| GET | `/api/ai/stores/{store_id}/draft/` | Bearer | - | Get current temporary draft state |
| POST | `/api/ai/stores/{store_id}/draft/clarify/` | Bearer | `clarification_answers` (non-empty string/object/list) | Run one clarification round |
| POST | `/api/ai/stores/{store_id}/draft/regenerate/` | Bearer | `{}` | Full draft regeneration |
| POST | `/api/ai/stores/{store_id}/draft/regenerate-section/` | Bearer | `target_section` in `theme,categories,products` | Partial section regeneration |
| POST | `/api/ai/stores/{store_id}/draft/apply/` | Bearer | `{}` | Apply draft to persistent models |

AI notes:
- Official fallback: **clarification-style fallback**.
- Drafts are cached (Redis in adopted runtime mode).
- Tenant and ownership checks are enforced on all store-scoped operations.

---

## Useful Test Commands
```bash
python manage.py test
python manage.py test AI_Store_Creation_Service.tests --verbosity 2 --keepdb --noinput
```

---

## Quick Troubleshooting
- DB connection issues: verify `DATABASE_URL` or `DB_*` values.
- AI draft cache issues: verify Redis and `REDIS_CACHE_URL`.
- Local dev fallback cache: set `CACHE_BACKEND=locmem` if needed.

