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

 feature/ai-store-creation
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

Multi-Tenant E-commerce Backend API

## Quick Start

### Prerequisites
- Python 3.12
- PostgreSQL 13+
- pip

### Installation & Setup

1. **Clone Repository**
 main
```bash
git clone <repo-url>
cd ai_store_creation

 feature/ai-store-creation
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

2. Create Virtual Environment



python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate

3. Install Dependencies



 main
pip install -r requirements.txt

 feature/ai-store-creation
### 4) Configure environment variables
Create `.env` in project root.

### 5) Run migrations
```bash

4. Database Setup



# Django reads DATABASE_URL automatically if provided
export DATABASE_URL=postgresql://user:password@localhost:5432/ai_store_db
# Windows PowerShell:
# $env:DATABASE_URL="postgresql://user:password@localhost:5432/ai_store_db"

# Or use DB_* fallback variables:
# DB_ENGINE=django.db.backends.postgresql
# DB_NAME=ai_store_db
# DB_USER=postgres
# DB_PASSWORD=1234
# DB_HOST=localhost
# DB_PORT=5433

# Run migrations
 main
python manage.py migrate

 feature/ai-store-creation
### 6) (Optional) Create regular Django admin user
```bash

5. Create Superuser



 main
python manage.py createsuperuser

 feature/ai-store-creation
### 7) Run backend server
```bash

6. Run Development Server



 main
python manage.py runserver

 feature/ai-store-creation
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
| `AI_MODEL_NAME` | Yes | Model name | `gpt-4o-mini` |
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

Server will be available at: http://localhost:8000


---

📚 API Documentation

Access Documentation

1. Swagger UI (Interactive):

URL: http://localhost:8000/api/docs/

Try requests directly in browser

Parameter validation & syntax highlighting



2. ReDoc (Clean View):

URL: http://localhost:8000/api/redoc/

Better for reading documentation

Organized by endpoint groups



3. OpenAPI Schema:

URL: http://localhost:8000/api/schema/

JSON format for API client generation




Full Documentation

Use the live OpenAPI docs:

Swagger UI: http://localhost:8000/api/docs/

ReDoc: http://localhost:8000/api/redoc/

OpenAPI schema: http://localhost:8000/api/schema/



---

🏗️ Project Structure

ai_store_creation/
├── .github/
│   └── workflows/
│       └── backend-tests.yml     # CI/CD pipeline
├── config/
│   ├── settings.py              # Django settings + drf-spectacular config
│   ├── urls.py                  # URL routing + docs endpoints
│   ├── wsgi.py
│   └── asgi.py
├── users/
│   ├── models.py                # User model with multi-tenant
│   ├── serializers.py           # Register/Login serializers
│   ├── views.py                 # Auth endpoints
│   ├── services.py              # Auth business logic
│   ├── permissions.py           # Tenant-based permissions
│   └── tests/
├── stores/
│   ├── models.py                # Store, StoreSettings, StoreDomain
│   ├── serializers.py           # Store serializers + OpenAPI docs
│   ├── views.py                 # Store CRUD endpoints
│   ├── services.py              # Store business logic
│   ├── selectors.py             # Database queries
│   └── tests/
├── categories/
│   ├── models.py                # Category model
│   ├── serializers.py           # Category serializers
│   ├── views.py                 # Category endpoints
│   ├── services.py              # Business logic
│   └── tests/
├── products/
│   ├── models.py                # Product, ProductImage, Inventory
│   ├── serializers.py           # Product serializers with help_text
│   ├── views.py                 # Product endpoints
│   ├── services.py              # Business logic
│   └── tests/
├── themes/
│   ├── models.py                # ThemeTemplate, StoreThemeConfig
│   ├── serializers.py           # Theme serializers
│   ├── selectors.py             # Theme read queries
│   ├── services.py              # Theme business logic
│   ├── views.py                 # Theme endpoints
│   ├── urls.py                  # Theme routes
│   ├── migrations/
│   └── tests/
├── utils/
│   ├── exceptions.py            # Custom exceptions
│   ├── errors.py                # Error utilities
│   ├── middleware.py            # Custom middleware
│   └── logging_config.py        # Logging setup
├── tests_integration.py         # Multi-tenant isolation tests
├── requirements.txt             # Python dependencies
├── manage.py                    # Django management
└── README.md                    # This file

 main

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
feature/ai-store-creation
## 🧪 Testing
Run full test suite:
```bash

🧪 Testing

Run All Tests

 main
python manage.py test

 feature/ai-store-creation
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
- MIT License

Current test suite passes.

Run Specific App Tests

python manage.py test stores
python manage.py test users
python manage.py test categories
python manage.py test products
python manage.py test themes
 feature/increment-1-multi-tenant-backend
```

Run with Coverage
 main

coverage run --source='.' manage.py test
coverage report
coverage html  # Creates htmlcov/index.html

Integration Tests

Multi-tenant isolation is verified in:

python manage.py test tests_integration


---

🚀 CI/CD Pipeline

GitHub Actions Workflow

File: .github/workflows/backend-tests.yml

Triggers:

Every push to main or develop branches

Every pull request


What It Does:

1. Sets up Python 3.12


2. Installs PostgreSQL service


3. Installs dependencies


4. Runs migrations


5. Executes all tests


6. Generates coverage reports


7. Uploads artifacts



Monitor:

Go to GitHub Actions tab

See real-time test results

Download coverage reports



---

📊 Database Schema

Core Models

Users

Authentication & authorization

Multi-tenant isolation

Email activation


Stores

Store instance per owner

Belongs to tenant

Has settings & domains


StoreSettings

Currency, language, timezone

Per-store configuration


StoreDomain

Custom domains

Primary domain selection


Categories

Product categorization

Per-store isolation


Products

Product catalog

SKU tracking

Status management


ProductImages

Product gallery

Media storage


Inventory

Stock tracking

Quantity management


Themes

Shared ThemeTemplate records

Per-store StoreThemeConfig

Theme Foundation endpoints for listing templates and reading/updating the current store theme



**Themes**
- Shared `ThemeTemplate` records
- Per-store `StoreThemeConfig`
- Theme Foundation endpoints for listing templates and reading/updating the current store theme

---

## Theme Foundation API

- `GET /api/stores/{store_id}/themes/templates/`
  Returns the available theme templates for the authenticated store owner.

- `GET /api/stores/{store_id}/theme/`
  Returns the current theme configuration for the specified store.

- `PATCH /api/stores/{store_id}/theme/`
  Updates only the editable theme fields for the specified store:
  `theme_template`, `primary_color`, `secondary_color`, `font_family`, `logo_url`, `banner_url`.

---

Theme Foundation API

GET /api/stores/{store_id}/themes/templates/ Returns the available theme templates for the authenticated store owner.

GET /api/stores/{store_id}/theme/ Returns the current theme configuration for the specified store.

PATCH /api/stores/{store_id}/theme/ Updates only the editable theme fields for the specified store: theme_template, primary_color, secondary_color, font_family, logo_url, banner_url.



---

🔐 Security Features

Authentication

JWT Bearer tokens (SimpleJWT)

Email activation required

Secure password hashing


Authorization

Multi-tenant isolation

Role-based access control

Ownership verification

Permission-based views


Data Protection

Tenant_id in all queries

Cross-tenant access blocked

Error messages don't leak data

CSRF protection on POST/PUT/PATCH/DELETE


Environment Variables

DATABASE_URL=postgresql://user:pass@host:port/db
SECRET_KEY=your-secret-key
DEBUG=False
ALLOWED_HOSTS=yourdomain.com


---

🛠️ Development

Code Style

PEP 8 compliance

Functions < 30 lines

Docstrings required for public functions

Type hints (optional but recommended)


Layered Architecture

Views/Serializers: API interface

Services: Business logic

Selectors: Database queries

Models: Data structures


Adding Features

1. Define model in app/models.py


2. Create migrations: python manage.py makemigrations


3. Write serializers in app/serializers.py


4. Add help_text for OpenAPI docs


5. Implement views in app/views.py


6. Add business logic in app/services.py


7. Write tests in app/tests/


8. Update README + OpenAPI annotations (help_text, schema docs)




---

📝 Logging

Logs are stored in logs/ directory with format:

[TIMESTAMP] LEVEL LOGGER_NAME -> MESSAGE

Log Levels

DEBUG: Detailed information

INFO: Confirmation of operations

WARNING: Warning messages

ERROR: Error messages (with stack trace)


View Logs

tail -f logs/*.log


---

🐛 Troubleshooting

Database Connection Error

Check:
- PostgreSQL is running
- DATABASE_URL is correct
- Port 5433 is accessible

Migration Error

# Reset migrations (development only!)
python manage.py migrate app_name zero
python manage.py migrate

Port Already in Use

# Use different port
python manage.py runserver 8001

Tests Failing

1. Run individually to isolate issue


2. Check logs in logs/ directory


3. Ensure database is migrated


4. Check multi-tenant isolation in tests




---

📦 Dependencies

Core

Django 6.0.3

Django REST Framework 3.17.1

drf-spectacular 0.27.0 (API documentation)

djangorestframework_simplejwt 5.5.1 (JWT auth)


Database

psycopg2-binary (PostgreSQL adapter)


Development

coverage (test coverage reporting)


Testing

Django TestCase

DRF APITestCase


Full list: See requirements.txt


---

🎯 API Endpoints Summary

Endpoint	Method	Purpose

/api/auth/register/	POST	User registration
/api/auth/login/	POST	User login
/api/stores/	GET/POST	List/create stores
/api/stores/{id}/	PATCH	Update store
/api/stores/{id}/delete/	DELETE	Delete store
/api/stores/{id}/settings/	GET/PATCH	Store settings
/api/stores/{id}/domains/	GET/POST	Domain management
/api/stores/{id}/domains/{domain_id}/	GET/PATCH/DELETE	Domain detail
/api/stores/slug/check/	POST	Check slug availability
/api/stores/slug/suggest/	POST	Suggest slug candidates
/api/stores/{id}/categories/	GET/POST	Category operations
/api/stores/{id}/categories/{category_id}/	GET/PATCH/DELETE	Category details
/api/categories/stores/{id}/categories/	GET/POST	Legacy-compatible category route
/api/categories/stores/{id}/categories/{category_id}/	GET/PATCH/DELETE	Legacy-compatible category detail routeح
/api/products/{store_id}/products/	GET/POST	Product operations
/api/products/{store_id}/products/{product_id}/	GET/PATCH/DELETE	Product details
/api/products/{store_id}/products/{product_id}/images/	GET/POST	Product images
/api/products/{store_id}/products/{product_id}/images/{image_id}/	DELETE	Delete product image
/api/products/{store_id}/products/{product_id}/inventory/	PUT/PATCH	Update inventory
/api/stores/{store_id}/themes/templates/	GET	List available theme templates
/api/stores/{store_id}/theme/	GET/PATCH	Read/update current store theme
/api/docs/	GET	Swagger UI documentation
/api/redoc/	GET	ReDoc documentation
/api/schema/	GET	OpenAPI schema (JSON)



---

📞 Support & Contribution

Reporting Issues

1. Check GitHub Issues


2. Check troubleshooting section


3. Check logs in logs/ directory


4. Create new issue with:

Error message

Steps to reproduce

System info

Logs




Contributing

1. Create feature branch: git checkout -b feature/name


2. Make changes


3. Run tests: python manage.py test


4. Commit: git commit -m "description"


5. Push: git push origin feature/name


6. Create Pull Request




---

📄 License

MIT License - See LICENSE file


---

Version History

v1.0.0 (2024-04-08)

Initial release

Complete API endpoints

Multi-tenant support

API documentation

CI/CD pipeline

 feature/increment-1-multi-tenant-backend
- v1.0.0 (2024-04-08)
  - Initial release
  - Complete API endpoints
  - Multi-tenant support
  - API documentation
  - CI/CD pipeline
  - 143 tests passing

---

## Auth Session Bootstrap Endpoints

- `POST /api/auth/register/` is a **public endpoint** for new user self-registration (no login required).
- `GET /api/auth/me/` is a **protected endpoint** and requires `Authorization: Bearer <access_token>`.

### GET /api/auth/me/

Returns the current authenticated user identity derived from the access token.

Example response:

```json
{
  "user_id": 1,
  "username": "omarMas",
  "email": "omarmas@gmail.com",
  "role": "Store Owner",
  "tenant_id": 1,
  "is_active": true,
  "display_name": "Omar Mas",
  "created_at": "2026-04-14T22:56:42.259202Z",
  "updated_at": "2026-04-14T22:56:42.259202Z"
}
```

Notes:
- `tenant_id` may be `null` for `Super Admin` when no tenant is associated.
- This endpoint does **not** return `access` or `refresh`.
- This endpoint does **not** return stores; stores are fetched separately via `GET /api/stores/`.

Theme Foundation
 main
 main
