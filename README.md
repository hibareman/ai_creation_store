# 🛍️ AI-Assisted Multi-Tenant E-Commerce Store Builder (Backend)

## 📌 Overview
This project is a production-style backend built with Django + DRF for a multi-tenant e-commerce system.  
It supports core commerce modules (auth, stores, categories, products, themes) and an AI-assisted store setup workflow that generates and applies a draft store configuration.

## ✨ Core Features
- Multi-tenant isolation via trusted middleware context (`request.tenant_id`).
- JWT authentication + email activation flow.
- Role-aware access control.
- Store management (store, settings, custom domains, slug tools).
- Category and product management (including product images and inventory).
- Theme foundation (template catalog + per-store theme config).
- AI Store Creation workflow:
  - start draft
  - current draft retrieval
  - clarification rounds
  - full regenerate
  - partial regenerate (`theme`, `categories`, `products`)
  - confirm/apply
- Redis-backed temporary AI draft cache with TTL.
- Lightweight AI audit logging.

## 🧰 Tech Stack
- Backend: Django, Django REST Framework
- API docs: drf-spectacular (Swagger/ReDoc/OpenAPI)
- Auth: JWT (SimpleJWT)
- Database: PostgreSQL (SQLite only optional fallback via `DATABASE_URL`)
- Cache: Redis (adopted), LocMem fallback for tests/dev
- AI Provider integration: OpenAI-style provider layer (config-driven)

## 🏗️ Project Structure
- `config/` - project settings and root URLs
- `users/` - authentication, registration, activation, current user identity
- `stores/` - store core, settings, domains, slug helpers
- `categories/` - store categories with tenant/owner checks
- `products/` - products, images, inventory
- `themes/` - templates + store theme config
- `AI_Store_Creation_Service/` - AI workflow (draft generation, clarification, regeneration, apply)

## ✅ Prerequisites
- Python 3.12+
- PostgreSQL
- Redis
- Git
- (Optional for frontend app) Node.js 18+

## 🚀 Local Setup (Step-by-Step)

### 1) Clone repository
```bash
git clone <repo-url>
cd ai_store_creation
```

### 2) Create and activate virtual environment
```bash
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

### 3) Install dependencies
```bash
pip install -r requirements.txt
```

### 4) Configure environment variables
Create `.env` in project root.

### 5) Run migrations
```bash
python manage.py migrate
```

### 6) (Optional) Create regular Django admin user
```bash
python manage.py createsuperuser
```

### 7) Run backend server
```bash
python manage.py runserver
```

Backend default URL: `http://localhost:8000`

## 🔐 Environment Variables
Use these in `.env` (do not commit secrets):

| Variable | Required | Purpose | Example |
|---|---|---|---|
| `SECRET_KEY` | Yes | Django secret key | `change-me` |
| `DEBUG` | Yes | Debug mode | `True` |
| `ALLOWED_HOSTS` | Optional (project currently permissive) | Allowed hosts policy | `localhost,127.0.0.1` |
| `DATABASE_URL` | Recommended | Main DB connection URL | `postgresql://postgres:1234@localhost:5433/ai_store_db` |
| `DB_ENGINE` | Optional fallback | DB engine when `DATABASE_URL` absent | `django.db.backends.postgresql` |
| `DB_NAME` | Optional fallback | DB name | `ai_store_db` |
| `DB_USER` | Optional fallback | DB user | `postgres` |
| `DB_PASSWORD` | Optional fallback | DB password | `1234` |
| `DB_HOST` | Optional fallback | DB host | `localhost` |
| `DB_PORT` | Optional fallback | DB port | `5433` |
| `CACHE_BACKEND` | Recommended | Cache backend selector (`redis` / `locmem`) | `redis` |
| `REDIS_CACHE_URL` | Yes for Redis mode | Redis cache URL | `redis://127.0.0.1:6379/1` |
| `CORS_ALLOWED_ORIGINS` | Yes (for frontend integration) | Allowed frontend origins (comma-separated) | `http://localhost:3000` |
| `CORS_ALLOW_CREDENTIALS` | Optional | CORS credentials support | `True` |
| `CORS_ALLOW_ALL_ORIGINS` | Optional (dev only) | Allow all origins | `False` |
| `AI_API_KEY` | For real AI calls | Provider API key | `<secret>` |
| `AI_API_URL` | Optional | OpenAI-compatible chat completions URL | `https://api.openai.com/v1/chat/completions` |
| `AI_MODEL_NAME` | Yes | Model name | `gpt-5.2` |
| `AI_HTTP_REFERER` | Optional (recommended for OpenRouter) | App/site URL sent as provider header | `http://localhost:8000` |
| `AI_APP_TITLE` | Optional (recommended for OpenRouter) | App title sent as provider header | `AI Store Backend` |
| `AI_TIMEOUT` | Yes | Provider timeout in seconds | `30` |
| `AI_DRAFT_TTL` | Yes | Temporary draft cache TTL | `3600` |
| `AI_DRAFT_PREFIX` | Yes | AI draft cache key prefix | `ai_draft` |

## 👤 Authentication & Roles
- Public registration is available only for `Store Owner`.
- `Super Admin` cannot self-register.
- Super Admin creation is backend-controlled only.
- Protected endpoints require:
  - `Authorization: Bearer <access_token>`
- `tenant_id` is resolved server-side by middleware; clients must not send trusted tenant context in request body/query.

## 🛡️ Backend-Controlled Super Admin
Create/update the fixed backend-managed super admin account:

```bash
python manage.py bootstrap_superadmin --password "StrongSuperAdmin123!"
```

This command controls the privileged account:
- Email: `superadmin@gmail.com`

## 📚 API Documentation Endpoints
- `GET /api/schema/` - OpenAPI schema
- `GET /api/docs/` - Swagger UI
- `GET /api/redoc/` - ReDoc

## 🔗 Complete Endpoint Reference

### 🧑‍💼 Admin
| Method | Endpoint | Auth | Success | Description |
|---|---|---|---|---|
| GET | `/admin/` | Session | 200 | Django admin panel |

### 🔑 Authentication (`/api/auth/`)
| Method | Endpoint | Auth | Success | Request Body (main fields) | Description |
|---|---|---|---|---|---|
| POST | `/api/auth/register/` | Public | 201 | `username`, `email`, `password`, `role` (`Store Owner` only) | Register account and send activation email |
| POST | `/api/auth/login/` | Public | 200 | `email`, `password` | Login and return JWT tokens |
| GET | `/api/auth/me/` | Bearer | 200 | - | Get current authenticated identity |
| GET | `/api/auth/activate/{token}/` | Public | 200 | - | Activate account by UUID token |
| POST | `/api/auth/token/` | Public | 200 | SimpleJWT default payload | Obtain token pair (compatibility route) |
| POST | `/api/auth/token/refresh/` | Public | 200 | `refresh` | Refresh access token |

### 🏬 Stores (`/api/stores/`)
| Method | Endpoint | Auth | Success | Request Body (main fields) | Description |
|---|---|---|---|---|---|
| GET | `/api/stores/` | Bearer | 200 | - | List stores owned by current user |
| POST | `/api/stores/` | Bearer | 201 | `name`, `description?`, `slug?` | Create store |
| PUT/PATCH | `/api/stores/{id}/` | Bearer | 200 | Store editable fields | Update store |
| DELETE | `/api/stores/{id}/delete/` | Bearer | 204 | - | Delete store |
| GET | `/api/stores/{store_id}/settings/` | Bearer | 200 | - | Get store settings |
| PATCH | `/api/stores/{store_id}/settings/` | Bearer | 200 | `currency?`, `language?`, `timezone?` | Update store settings |
| POST | `/api/stores/slug/check/` | Bearer | 200 | `slug`, `store_id?` | Check slug availability |
| POST | `/api/stores/slug/suggest/` | Bearer | 200 | `name`, `store_id?`, `limit?` | Suggest slugs |
| GET | `/api/stores/{store_id}/domains/` | Bearer | 200 | - | List store domains |
| POST | `/api/stores/{store_id}/domains/` | Bearer | 201 | `domain`, `is_primary?` | Add domain |
| GET | `/api/stores/{store_id}/domains/{domain_id}/` | Bearer | 200 | - | Get domain details |
| PATCH | `/api/stores/{store_id}/domains/{domain_id}/` | Bearer | 200 | `domain?`, `is_primary?` | Update domain |
| DELETE | `/api/stores/{store_id}/domains/{domain_id}/` | Bearer | 204 | - | Delete domain |

### 🗂️ Categories (Primary Contract Routes)
Mounted via: `path("api/", include("categories.urls"))`

| Method | Endpoint | Auth | Success | Request Body (main fields) | Description |
|---|---|---|---|---|---|
| GET | `/api/stores/{store_id}/categories/` | Bearer | 200 | - | List categories for store |
| POST | `/api/stores/{store_id}/categories/` | Bearer | 201 | `name`, `description?` | Create category |
| GET | `/api/stores/{store_id}/categories/{category_id}/` | Bearer | 200 | - | Get category |
| PUT/PATCH | `/api/stores/{store_id}/categories/{category_id}/` | Bearer | 200 | `name?`, `description?` | Update category |
| DELETE | `/api/stores/{store_id}/categories/{category_id}/` | Bearer | 204 | - | Delete category |

### 🧩 Categories (Legacy-Compatible Prefix)
Mounted via: `path("api/categories/", include("categories.urls"))`

| Method | Endpoint | Auth | Success | Description |
|---|---|---|---|---|
| GET/POST | `/api/categories/stores/{store_id}/categories/` | Bearer | 200/201 | Same behavior as primary contract route |
| GET/PUT/PATCH/DELETE | `/api/categories/stores/{store_id}/categories/{category_id}/` | Bearer | 200/204 | Same behavior as primary contract route |

### 📦 Products (`/api/products/`)
| Method | Endpoint | Auth | Success | Request Body (main fields) | Description |
|---|---|---|---|---|---|
| GET | `/api/products/{store_id}/products/` | Bearer | 200 | - | List products |
| POST | `/api/products/{store_id}/products/` | Bearer | 201 | `name`, `description`, `price`, `sku`, `category`, `status?` | Create product |
| GET | `/api/products/{store_id}/products/{product_id}/` | Bearer | 200 | - | Get product |
| PUT/PATCH | `/api/products/{store_id}/products/{product_id}/` | Bearer | 200 | Product editable fields | Update product |
| DELETE | `/api/products/{store_id}/products/{product_id}/` | Bearer | 204 | - | Delete product |
| GET | `/api/products/{store_id}/products/{product_id}/images/` | Bearer | 200 | - | List product images |
| POST | `/api/products/{store_id}/products/{product_id}/images/` | Bearer | 201 | `image_file` or `image_url` | Add product image |
| DELETE | `/api/products/{store_id}/products/{product_id}/images/{image_id}/` | Bearer | 204 | - | Delete product image |
| PUT/PATCH | `/api/products/{store_id}/products/{product_id}/inventory/` | Bearer | 200 | `stock_quantity` | Update inventory |

### 🎨 Themes (Mounted under `/api/`)
| Method | Endpoint | Auth | Success | Request Body (main fields) | Description |
|---|---|---|---|---|---|
| GET | `/api/stores/{store_id}/themes/templates/` | Bearer | 200 | - | List available theme templates |
| GET | `/api/stores/{store_id}/theme/` | Bearer | 200 | - | Get current store theme config |
| PATCH | `/api/stores/{store_id}/theme/` | Bearer | 200 | `theme_template?`, `primary_color?`, `secondary_color?`, `font_family?`, `logo_url?`, `banner_url?` | Update store theme config |

### 🤖 AI Store Creation (`/api/ai/`)
| Method | Endpoint | Auth | Success | Request Body (main fields) | Description |
|---|---|---|---|---|---|
| POST | `/api/ai/stores/draft/start/` | Bearer | 201 | `name`, `user_store_description` | Create draft store + generate initial AI draft |
| GET | `/api/ai/stores/{store_id}/draft/` | Bearer | 200 | - | Get current temporary draft state |
| POST | `/api/ai/stores/{store_id}/draft/clarify/` | Bearer | 200 | `clarification_answers` | Submit one clarification round |
| POST | `/api/ai/stores/{store_id}/draft/regenerate/` | Bearer | 200 | `{}` | Full draft regeneration |
| POST | `/api/ai/stores/{store_id}/draft/regenerate-section/` | Bearer | 200 | `target_section` (`theme`, `categories`, `products`) | Partial regeneration for one section |
| POST | `/api/ai/stores/{store_id}/draft/apply/` | Bearer | 200 | `{}` | Apply draft to database and move store to `setup` |

## 🧪 Testing
Run full test suite:
```bash
python manage.py test
```

Run AI-focused tests:
```bash
python manage.py test AI_Store_Creation_Service.tests --verbosity 2 --keepdb --noinput
```

Run optional live-provider integration test (real API call, disabled by default):

Linux/macOS:
```bash
export RUN_LIVE_AI_TESTS=1
export AI_API_URL="https://openrouter.ai/api/v1/chat/completions"
export AI_MODEL_NAME="openai/gpt-4o-mini"
python manage.py test AI_Store_Creation_Service.tests_live_provider -v 2
```

Windows PowerShell:
```powershell
$env:RUN_LIVE_AI_TESTS="1"
$env:AI_API_URL="https://openrouter.ai/api/v1/chat/completions"
$env:AI_MODEL_NAME="openai/gpt-4o-mini"
python manage.py test AI_Store_Creation_Service.tests_live_provider -v 2
```

Run selected module tests:
```bash
python manage.py test users.tests stores.tests categories.tests products.tests themes.tests --verbosity 2 --keepdb --noinput
```

## 🔁 Git Workflow (Recommended)
- Branch naming: `feature/<scope>`
- Commit style: `feat(scope): message`, `fix(scope): message`
- Open PR with:
  - summary
  - test evidence
  - scope boundaries

## 🚢 Deployment Notes
- Production requires:
  - PostgreSQL
  - Redis
  - secure secret management (`SECRET_KEY`, `AI_API_KEY`, DB creds)
  - restrictive `ALLOWED_HOSTS` and CORS policy
- Do not use `DEBUG=True` in production.

## 👥 Team / Authors
- Project team: add names here as needed.

## 📄 License
- Add project license here (if applicable).
