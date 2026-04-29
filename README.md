# AI Store Creation Backend

## Project Overview

Multi-tenant, AI-assisted e-commerce store creation backend built with Django REST Framework. The platform supports Store Owners and Super Admins, with APIs for AI draft generation, store management, products, categories, themes, orders, SEO, and platform administration.

Swagger is the source of truth for full request and response schemas:

- Swagger UI: http://localhost:8000/api/docs/
- ReDoc: http://localhost:8000/api/redoc/
- OpenAPI schema: http://localhost:8000/api/schema/

## Getting Started

```powershell
git clone <repo-url>
cd ai_store_creation

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Create a `.env` file from an example if available, or add the required values manually. Configure PostgreSQL with either `DATABASE_URL` or the `DB_*` variables.

```powershell
python manage.py migrate
python manage.py check
python manage.py bootstrap_superadmin --password "ChangeMeStrong123!"
python manage.py runserver
```

Then open http://localhost:8000/api/docs/.

## Environment Variables

Important `.env` values only:

```env
SECRET_KEY=change-me
DEBUG=True

DATABASE_URL=postgres://postgres:password@localhost:5432/ai_store_db
# Or:
DB_ENGINE=django.db.backends.postgresql
DB_NAME=ai_store_db
DB_USER=postgres
DB_PASSWORD=password
DB_HOST=localhost
DB_PORT=5432

CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

AI_PROVIDER=ollama
AI_API_KEY=
AI_API_URL=http://localhost:11434/api/chat
AI_MODEL_NAME=qwen2.5:1.5b
AI_TIMEOUT=60
AI_MAX_TOKENS=4096
AI_TEMPERATURE=0.2
ANTHROPIC_VERSION=2023-06-01

CACHE_BACKEND=locmem
REDIS_URL=redis://127.0.0.1:6379/1
AI_DRAFT_TTL=3600
AI_DRAFT_PREFIX=ai_draft
```

### Ollama Local Example

```env
AI_PROVIDER=ollama
AI_API_URL=http://localhost:11434/api/chat
AI_MODEL_NAME=qwen2.5:1.5b
AI_API_KEY=
```

Run Ollama separately and pull the model once:

```powershell
ollama serve
ollama pull qwen2.5:1.5b
```

### Anthropic / Claude Example

```env
AI_PROVIDER=anthropic
AI_API_URL=https://api.anthropic.com/v1/messages
AI_API_KEY=your-api-key
AI_MODEL_NAME=claude-3-5-sonnet-latest
AI_TIMEOUT=240
AI_MAX_TOKENS=4096
AI_TEMPERATURE=0.2
ANTHROPIC_VERSION=2023-06-01
```

Do not commit real secrets.

## Technologies Used

- Python
- Django
- Django REST Framework
- SimpleJWT
- drf-spectacular / Swagger
- PostgreSQL
- Redis / Django cache
- Ollama / OpenAI-compatible providers / Anthropic Claude
- Pillow
- Git / GitHub

## Main Features

- JWT authentication and email activation
- Super Admin bootstrap and login
- Multi-tenant store isolation using `tenant_id`
- Store CRUD, settings, publishing, slug, subdomain, and domain management
- Product, category, inventory, and image management
- Theme and appearance management
- Public store APIs
- Cart, checkout, and order APIs
- SEO APIs
- AI-assisted store draft workflow
- Clarification questions
- Full and partial AI regeneration
- AI fallback and temporary draft storage
- Super Admin dashboard, stores, users, and settings APIs
- Swagger API documentation

## Project Structure

| Path | Purpose |
|---|---|
| `users/` | Auth, activation, JWT login, roles, permissions |
| `stores/` | Store CRUD, settings, domains, slug, subdomain, publish flow |
| `categories/` | Store category endpoints |
| `products/` | Products, images, inventory, public product browsing |
| `orders/` | Owner orders, customers, public cart and checkout |
| `themes/` | Theme templates, appearance, logo upload |
| `seo/` | Store, product, category, and public SEO metadata |
| `AI_Store_Creation_Service/` | AI draft generation and apply workflow |
| `platform_admin/` | Super Admin dashboard, stores, users, settings |
| `config/` | Django settings, root URLs, ASGI/WSGI |
| `utils/` | Shared utilities and middleware |
| `docs/` | Project documentation assets |
| `media/` | Uploaded media files |

## API Endpoints Summary

Protected endpoints require:

```http
Authorization: Bearer <access_token>
```

Use Swagger for complete schemas, validation rules, and examples.

### Auth

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| POST | `/api/auth/register/` | Register Store Owner and send activation email | User registration fields | Activation message |
| POST | `/api/auth/login/` | Login with email/password | `email`, `password` | JWT tokens and user bootstrap data |
| GET | `/api/auth/me/` | Current authenticated identity | None | User identity and store bootstrap data |
| GET | `/api/auth/activate/{token}/` | Activate account by email token | None | Activation message and JWT data |
| POST | `/api/auth/token/refresh/` | Refresh JWT access token | `refresh` | New `access` token |

### Stores

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| GET | `/api/stores/` | List owner stores | None | Store list |
| POST | `/api/stores/` | Create store | Store payload | Created store |
| PUT/PATCH | `/api/stores/{id}/` | Update store | Store fields | Updated store |
| DELETE | `/api/stores/{id}/delete/` | Delete store | None | Empty/delete response |
| POST | `/api/stores/slug/check/` | Check slug availability | Slug payload | Availability result |
| POST | `/api/stores/slug/suggest/` | Suggest slug | Name payload | Suggested slug |
| GET | `/api/stores/public/store/{subdomain}/` | Public store detail | None | Public store data |
| PATCH | `/api/stores/{store_id}/subdomain/` | Set store subdomain | Subdomain payload | Updated store/subdomain data |
| PATCH | `/api/stores/{store_id}/publish/` | Publish or unpublish store | Publish action | Updated publish state |
| GET/PUT/PATCH | `/api/stores/{store_id}/settings/` | Store settings | Settings payload for updates | Store settings |
| GET/POST | `/api/stores/{store_id}/domains/` | List or add domains | Domain payload for create | Domain list or created domain |
| GET/PUT/PATCH/DELETE | `/api/stores/{store_id}/domains/{domain_id}/` | Domain detail/update/delete | Domain payload for updates | Domain data or delete response |

### Themes

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| GET | `/api/stores/{store_id}/themes/templates/` | List theme templates | None | Theme templates |
| GET/PATCH | `/api/stores/{store_id}/theme/` | Get or update active theme config | Theme config fields | Theme config |
| GET/PUT/PATCH | `/api/stores/{store_id}/appearance/` | Store appearance settings | Appearance fields | Appearance config |
| POST | `/api/stores/{store_id}/assets/logo/` | Upload store logo | Multipart logo file | Updated logo data |

### Products and Categories

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| GET/POST | `/api/stores/{store_id}/categories/` | List or create categories | Category payload for create | Category list or created category |
| GET/PUT/PATCH/DELETE | `/api/stores/{store_id}/categories/{category_id}/` | Category detail/update/delete | Category fields for updates | Category data or delete response |
| GET/POST | `/api/products/{store_id}/products/` | List or create products | Product payload for create | Product list or created product |
| GET/PUT/PATCH/DELETE | `/api/products/{store_id}/products/{product_id}/` | Product detail/update/delete | Product fields for updates | Product data or delete response |
| GET/POST | `/api/products/{store_id}/products/{product_id}/images/` | List or upload product images | Image payload | Image list or created image |
| DELETE | `/api/products/{store_id}/products/{product_id}/images/{image_id}/` | Delete product image | None | Delete response |
| PUT/PATCH | `/api/products/{store_id}/products/{product_id}/inventory/` | Update inventory | Inventory fields | Updated inventory |
| GET | `/api/products/public/store/{subdomain}/products/` | Public products list | None | Public product list |
| GET | `/api/products/public/store/{subdomain}/products/{product_id}/` | Public product detail | None | Public product data |

### Orders and Cart

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| GET | `/api/stores/{store_id}/dashboard/` | Owner order dashboard | None | Dashboard metrics |
| GET | `/api/stores/{store_id}/customers/` | Owner customers list | None | Customers list |
| GET | `/api/stores/{store_id}/orders/` | Owner orders list | None | Orders list |
| GET | `/api/stores/{store_id}/orders/{order_id}/` | Owner order detail | None | Order detail |
| PATCH | `/api/stores/{store_id}/orders/{order_id}/status/` | Update owner order status | Status payload | Updated order |
| POST | `/api/public/store/{subdomain}/orders/` | Public direct order creation | Order payload | Created order |
| GET/DELETE | `/api/public/store/{subdomain}/cart/` | Get or clear public cart | None | Cart data or clear result |
| POST | `/api/public/store/{subdomain}/cart/items/` | Add cart item | Item payload | Updated cart |
| PATCH/DELETE | `/api/public/store/{subdomain}/cart/items/{product_id}/` | Update or remove cart item | Quantity payload for patch | Updated cart or remove result |
| POST | `/api/public/store/{subdomain}/cart/checkout/` | Checkout from cart | Checkout payload | Created order |

### SEO

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| GET/PUT/PATCH | `/api/stores/{store_id}/seo/` | Store SEO metadata | SEO fields for updates | Store SEO |
| GET/PUT/PATCH | `/api/products/{store_id}/products/{product_id}/seo/` | Product SEO metadata | SEO fields for updates | Product SEO |
| GET/PUT/PATCH | `/api/categories/{store_id}/categories/{category_id}/seo/` | Category SEO metadata | SEO fields for updates | Category SEO |
| GET | `/api/public/store/{subdomain}/seo/` | Public store SEO | None | Public SEO metadata |
| GET | `/api/public/store/{subdomain}/products/{product_id}/seo/` | Public product SEO | None | Public product SEO metadata |

### AI Store Creation

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| POST | `/api/ai/stores/draft/start/` | Start AI draft | Store brief/prompt | Draft response |
| GET | `/api/ai/stores/{store_id}/draft/` | Get current draft | None | Current draft |
| POST | `/api/ai/stores/{store_id}/draft/clarify/` | Answer clarification questions | Clarification answers | Updated draft state |
| POST | `/api/ai/stores/{store_id}/draft/regenerate/` | Regenerate full draft | Regeneration payload | New draft |
| POST | `/api/ai/stores/{store_id}/draft/regenerate-section/` | Regenerate one section | Section payload | Updated section |
| POST | `/api/ai/stores/{store_id}/draft/apply/` | Apply draft to store | Apply payload | Applied store data |

### Super Admin

| Method | URL | Description | Body | Response |
|---|---|---|---|---|
| GET | `/api/admin/dashboard/` | Platform metrics and recent stores | None | Dashboard summary |
| GET | `/api/admin/stores/` | Manage stores list | Optional query params | Store admin summaries |
| PATCH | `/api/admin/stores/{store_id}/status/` | Update admin store status | `status` | Updated store summary |
| GET | `/api/admin/users/` | Manage users list | Optional `search` query | User admin summaries |
| GET | `/api/admin/settings/` | Get platform settings | None | Platform settings |
| PATCH | `/api/admin/settings/` | Update platform settings | Settings wrapper | Updated platform settings |

## Testing

```powershell
python manage.py check
python manage.py test
python manage.py spectacular --file schema.yaml --validate
```

## Notes

- All protected endpoints require `Authorization: Bearer <access_token>`.
- Super Admin endpoints require `role = "Super Admin"`.
- Store Owner endpoints are scoped by tenant and store ownership.
- AI provider behavior is controlled by `AI_PROVIDER`.
- Swagger is the source of truth for detailed schemas.

## License

This project is for academic, educational, or prototype use unless another license is provided.
