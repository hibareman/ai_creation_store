# 🛍️ AI Store Creation Backend

Backend API for a multi-tenant e-commerce platform where store owners can create, manage, and publish online stores. The project includes an AI-powered workflow that turns a merchant's natural store description into a ready draft containing store details, theme, categories, and starter products.

API documentation is available after running the server:

- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI schema: `http://localhost:8000/api/schema/`

## 🚀 Getting Started

### 1. Clone and enter the project

```powershell
git clone <repo-url>
cd ai_store_creation
```

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Create `.env`

Create a `.env` file in the project root:

```env
SECRET_KEY=change-me
DEBUG=True

DATABASE_URL=postgres://postgres:password@localhost:5432/ai_store_db

CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

AI_PROVIDER=ollama
AI_API_URL=https://ollama.com/api/chat
AI_API_KEY=your-ollama-cloud-api-key
AI_MODEL_NAME=gpt-oss:120b
AI_TIMEOUT=60
AI_MAX_TOKENS=4096
AI_TEMPERATURE=0.2

CACHE_BACKEND=locmem
AI_DRAFT_TTL=3600
AI_DRAFT_PREFIX=ai_draft
```

For Redis cache instead of local memory:

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

Never commit real secrets.

### 5. Prepare the database

```powershell
python manage.py migrate
python manage.py check
```

### 6. Create a Super Admin

```powershell
python manage.py bootstrap_superadmin --password "ChangeMeStrong123!"
```

### 7. Run the server

```powershell
python manage.py runserver
```

Open:

```text
http://localhost:8000/api/docs/
```

## ✨ Key Features

- JWT authentication with email activation
- Multi-tenant isolation using `tenant_id`
- Store CRUD, settings, domains, subdomains, and publishing flow
- Category, product, image, and inventory management
- Theme templates and store appearance configuration
- Public store browsing APIs
- Cart, checkout, customers, and order management
- SEO metadata APIs for stores, products, and categories
- AI store draft generation with clarification questions
- Full draft regeneration and section regeneration
- Safe AI draft cache before applying data to the database
- Super Admin dashboard, store management, user management, and settings
- Swagger/OpenAPI documentation

## 🧰 Tech Stack

- Python
- Django
- Django REST Framework
- SimpleJWT
- drf-spectacular / Swagger
- PostgreSQL
- Redis / Django cache
- Ollama / OpenAI-compatible providers / Anthropic
- Pillow
- django-cors-headers
- Git / GitHub


## 🗂️ Project Structure

| Path | What it does |
|---|---|
| `users/` | Authentication, activation, roles, permissions, tenant context |
| `stores/` | Store CRUD, settings, domains, subdomains, publish flow |
| `categories/` | Store category APIs |
| `products/` | Products, images, inventory, and public product browsing |
| `orders/` | Public cart, checkout, customers, and owner order management |
| `themes/` | Theme templates and store appearance configuration |
| `seo/` | SEO metadata for stores, products, categories, and public pages |
| `AI_Store_Creation_Service/` | AI draft generation, clarification, regeneration, and apply workflow |
| `platform_admin/` | Super Admin dashboard, users, stores, and settings |
| `config/` | Django settings, root URLs, ASGI, WSGI |
| `utils/` | Shared middleware, exceptions, logging, and response helpers |
| `docs/` | Project documentation assets |
| `media/` | Uploaded media files |

## 🤖 AI Workflow

The AI flow is intentionally layered:

```text
View → Service → Provider → Prompt → AI → Parser → Validator → Cache → Apply to DB
```

- `prompts.py` builds the instructions sent to the AI provider.
- `providers.py` communicates with Ollama/OpenAI-compatible/Anthropic APIs.
- `parsers.py` converts the raw AI response into a Python `dict`.
- `validators.py` validates the generated draft schema.
- `draft_store.py` stores temporary drafts in cache.
- `services.py` controls the business flow and applies approved drafts to the database inside transactions.

## 🔐 Authentication

Protected endpoints require:

```http
Authorization: Bearer <access_token>
```

Store Owner endpoints are scoped by tenant and store ownership. Super Admin endpoints require a Super Admin role.

## 🧪 Useful Commands

```powershell
python manage.py check
python manage.py test
python manage.py spectacular --file schema.yaml --validate
```

## 📌 Notes for Developers

- Swagger is the source of truth for full request/response schemas.
- AI drafts are temporary and are applied only after user approval.
- Draft cleanup happens after a successful database commit.
- Use `CACHE_BACKEND=locmem` for simple local development.
- Use Redis for shared or production-like draft storage.
- Keep `.env` secrets out of Git.

## 📄 License

This project is for academic, educational, or prototype use unless another license is provided.
