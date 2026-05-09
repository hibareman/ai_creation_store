# 🛍️ Souq Engine

Souq Engine is a multi-tenant e-commerce platform where store owners can create, manage, and publish online stores. The system includes a Django REST backend, a Next.js frontend, and an AI-powered workflow that turns a merchant's natural store description into a ready draft containing store details, theme, categories, and starter products.

API documentation is available after running the backend server:

- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI schema: `http://localhost:8000/api/schema/`

## 🚀 Getting Started

### ⚙️ Backend setup

#### 1. Clone and enter the backend project

```powershell
git clone <backend-repo-url>
cd ai_store_creation
```

#### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

#### 4. Create `.env`

Create a `.env` file in the backend project root:

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

#### 5. Prepare the database

```powershell
python manage.py migrate
python manage.py check
```

#### 6. Create a Super Admin

```powershell
python manage.py bootstrap_superadmin --password "ChangeMeStrong123!"
```

#### 7. Run the backend server

```powershell
python manage.py runserver
```

Open:

```text
http://localhost:8000/api/docs/
```

### 🎨 Frontend setup

#### 1. Clone and enter the frontend project

```powershell
git clone <frontend-repo-url>
cd SouqEnginFrontEnd-main
```

#### 2. Install dependencies

```powershell
npm install
```

#### 3. Create `.env.local`

Create a `.env.local` file in the frontend project root:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
NEXT_PUBLIC_DATA_SOURCE=backend
NEXT_PUBLIC_USE_MOCK_API=false
```

#### 4. Run the frontend server

```powershell
npm run dev
```

Open:

```text
http://localhost:3000
```

## ✨ Key Features

- JWT authentication with email activation
- Multi-tenant isolation using `tenant_id`
- Store CRUD, settings, domains, subdomains, and publishing flow
- Category, product, image, and inventory management
- Theme templates and store appearance configuration
- Public store browsing APIs and storefront UI
- Cart, checkout, customers, and order management
- SEO metadata APIs for stores, products, and categories
- AI store draft generation with clarification questions
- Full draft regeneration and section regeneration
- Safe AI draft cache before applying data to the database
- Store owner dashboard for products, categories, orders, customers, appearance, and AI generation
- Super Admin dashboard, store management, user management, and settings
- Swagger/OpenAPI documentation

## 🧰 Tech Stack

### ⚙️ Backend

- Python
- Django
- Django REST Framework
- SimpleJWT
- drf-spectacular / Swagger
- PostgreSQL
- Redis / Django cache
- Ollama 
- Pillow
- django-cors-headers

### 🎨 Frontend

- TypeScript
- Next.js
- React
- Tailwind CSS
- Radix UI
- TanStack Query
- Zustand
- React Hook Form
- Zod
- Lucide React
- Vitest
- Playwright

### 🤝 Shared

- Git / GitHub

## 🗂️ Backend Project Structure

```text
ai_store_creation/
├─ users/                      # Authentication, activation, roles, permissions, tenant context
├─ stores/                     # Store CRUD, settings, domains, subdomains, publish flow
├─ categories/                 # Store category APIs
├─ products/                   # Products, images, inventory, and public product browsing
├─ orders/                     # Public cart, checkout, customers, and owner order management
├─ themes/                     # Theme templates and store appearance configuration
├─ seo/                        # SEO metadata for stores, products, categories, and public pages
├─ AI_Store_Creation_Service/  # AI draft generation, clarification, regeneration, and apply workflow
├─ platform_admin/             # Super Admin dashboard, users, stores, and settings
├─ config/                     # Django settings, root URLs, ASGI, WSGI
├─ utils/                      # Shared middleware, exceptions, logging, and response helpers
├─ docs/                       # Project documentation assets
└─ media/                      # Uploaded media files
```

## 🧩 Frontend Project Structure

```text
SouqEnginFrontEnd-main/
├─ src/
│  ├─ app/                    # Next.js routes, layouts, and route composition
│  ├─ features/               # Domain screens and feature logic
│  │  ├─ ai-generator/        # AI store generation UI
│  │  ├─ admin/               # Super Admin frontend screens
│  │  ├─ dashboard/           # Store owner dashboard screens
│  │  ├─ products/            # Product management UI
│  │  ├─ categories/          # Category management UI
│  │  ├─ orders/              # Order management UI
│  │  ├─ customers/           # Customer management UI
│  │  ├─ appearance/          # Store theme and appearance UI
│  │  └─ storefront/          # Public storefront UI
│  ├─ components/             # Shared UI and layout components
│  │  ├─ ui/                  # Reusable design-system primitives
│  │  ├─ layouts/             # Dashboard, admin, and storefront shells
│  │  └─ shared/              # Shared app-specific components
│  ├─ services/               # API client, data source, and query integration
│  ├─ lib/                    # Providers, storage, and framework helpers
│  ├─ hooks/                  # Shared React hooks
│  ├─ types/                  # Shared TypeScript types and API contracts
│  ├─ utils/                  # Pure utilities
│  ├─ config/                 # Runtime configuration
│  ├─ constants/              # App-wide constants
│  ├─ styles/                 # Shared style files
│  └─ assets/                 # Source-controlled static imports
├─ public/                    # Static public assets
└─ tests/                     # End-to-end tests
```

## 🤖 AI Workflow

The AI flow is intentionally layered:

```text
View -> Service -> Provider -> Prompt -> AI -> Parser -> Validator -> Cache -> Apply to DB
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

### ⚙️ Backend

```powershell
python manage.py check
python manage.py test
python manage.py spectacular --file schema.yaml --validate
```

### 🎨 Frontend

```powershell
npm run lint
npm run typecheck
npm run test
npm run test:e2e
npm run build
```

## 📌 Notes for Developers

- Run the backend on `http://localhost:8000` and the frontend on `http://localhost:3000` during local development.
- Swagger is the source of truth for full request/response schemas.
- AI drafts are temporary and are applied only after user approval.
- Draft cleanup happens after a successful database commit.
- Use `CACHE_BACKEND=locmem` for simple local development.
- Use Redis for shared or production-like draft storage.
- Keep `.env` and `.env.local` secrets out of Git.

## 📄 License

This project is for academic, educational, or prototype use unless another license is provided.
