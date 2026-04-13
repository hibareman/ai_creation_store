# AI Store Creation Backend

Multi-Tenant E-commerce Backend API with AI-Powered Features

## Quick Start

### Prerequisites
- Python 3.12
- PostgreSQL 13+
- pip

### Installation & Setup

1. **Clone Repository**
```bash
git clone <repo-url>
cd ai_store_creation
```

2. **Create Virtual Environment**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
```

3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

4. **Database Setup**
```bash
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
python manage.py migrate
```

5. **Create Superuser**
```bash
python manage.py createsuperuser
```

6. **Run Development Server**
```bash
python manage.py runserver
```

Server will be available at: http://localhost:8000

---

## 📚 API Documentation

### Access Documentation

1. **Swagger UI** (Interactive):
   - URL: http://localhost:8000/api/docs/
   - Try requests directly in browser
   - Parameter validation & syntax highlighting

2. **ReDoc** (Clean View):
   - URL: http://localhost:8000/api/redoc/
   - Better for reading documentation
   - Organized by endpoint groups

3. **OpenAPI Schema**:
   - URL: http://localhost:8000/api/schema/
   - JSON format for API client generation

### Full Documentation

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for:
- Complete endpoint reference
- Request/response examples
- Authentication flow
- Multi-tenant isolation explanation
- Error handling
- Testing examples

---

## 🏗️ Project Structure

```
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
├── utils/
│   ├── exceptions.py            # Custom exceptions
│   ├── errors.py                # Error utilities
│   ├── middleware.py            # Custom middleware
│   └── logging_config.py        # Logging setup
├── tests_integration.py         # Multi-tenant isolation tests
├── API_DOCUMENTATION.md         # Complete API guide
├── requirements.txt             # Python dependencies
├── manage.py                    # Django management
└── README.md                    # This file
```

---

## 🧪 Testing

### Run All Tests
```bash
python manage.py test
```

Output: 126 tests, all must pass

### Run Specific App Tests
```bash
python manage.py test stores
python manage.py test users
python manage.py test categories
python manage.py test products
```

### Run with Coverage
```bash
coverage run --source='.' manage.py test
coverage report
coverage html  # Creates htmlcov/index.html
```

### Integration Tests
Multi-tenant isolation is verified in:
```bash
python manage.py test tests_integration
```

---

## 🚀 CI/CD Pipeline

### GitHub Actions Workflow

**File:** `.github/workflows/backend-tests.yml`

**Triggers:**
- Every push to `main` or `develop` branches
- Every pull request

**What It Does:**
1. Sets up Python 3.12
2. Installs PostgreSQL service
3. Installs dependencies
4. Runs migrations
5. Executes all 126 tests
6. Generates coverage reports
7. Uploads artifacts

**Monitor:**
- Go to GitHub Actions tab
- See real-time test results
- Download coverage reports

---

## 📊 Database Schema

### Core Models

**Users**
- Authentication & authorization
- Multi-tenant isolation
- Email activation

**Stores**
- Store instance per owner
- Belongs to tenant
- Has settings & domains

**StoreSettings**
- Currency, language, timezone
- Per-store configuration

**StoreDomain**
- Custom domains
- Primary domain selection

**Categories**
- Product categorization
- Per-store isolation

**Products**
- Product catalog
- SKU tracking
- Status management

**ProductImages**
- Product gallery
- Media storage

**Inventory**
- Stock tracking
- Quantity management

---

## 🔐 Security Features

### Authentication
- JWT Bearer tokens (SimplJWT)
- Email activation required
- Secure password hashing

### Authorization
- Multi-tenant isolation
- Role-based access control
- Ownership verification
- Permission-based views

### Data Protection
- Tenant_id in all queries
- Cross-tenant access blocked
- Error messages don't leak data
- CSRF protection on POST/PUT/PATCH/DELETE

### Environment Variables
```bash
DATABASE_URL=postgresql://user:pass@host:port/db
SECRET_KEY=your-secret-key
DEBUG=False (production)
ALLOWED_HOSTS=yourdomain.com
```

---

## 🛠️ Development

### Code Style
- PEP 8 compliance
- Functions < 30 lines
- Docstrings required for public functions
- Type hints (optional but recommended)

### Layered Architecture
- **Views/Serializers:** API interface
- **Services:** Business logic
- **Selectors:** Database queries
- **Models:** Data structures

### Adding Features

1. Define model in `app/models.py`
2. Create migrations: `python manage.py makemigrations`
3. Write serializers in `app/serializers.py`
4. Add help_text for OpenAPI docs
5. Implement views in `app/views.py`
6. Add business logic in `app/services.py`
7. Write tests in `app/tests/`
8. Update `API_DOCUMENTATION.md`

---

## 📝 Logging

Logs are stored in `logs/` directory with format:
```
[TIMESTAMP] LEVEL LOGGER_NAME -> MESSAGE
```

### Log Levels
- DEBUG: Detailed information
- INFO: Confirmation of operations
- WARNING: Warning messages
- ERROR: Error messages (with stack trace)

### View Logs
```bash
tail -f logs/*.log
```

---

## 🐛 Troubleshooting

### Database Connection Error
```
Check:
- PostgreSQL is running
- DATABASE_URL is correct
- Port 5433 is accessible
```

### Migration Error
```bash
# Reset migrations (development only!)
python manage.py migrate app_name zero
python manage.py migrate
```

### Port Already in Use
```bash
# Use different port
python manage.py runserver 8001
```

### Tests Failing
1. Run individually to isolate issue
2. Check logs in `logs/` directory
3. Ensure database is migrated
4. Check multi-tenant isolation in test

---

## 📦 Dependencies

### Core
- Django 6.0.3
- Django REST Framework 3.17.1
- drf-spectacular 0.27.0 (API documentation)
- djangorestframework_simplejwt 5.5.1 (JWT auth)

### Database
- psycopg2-binary (PostgreSQL adapter)

### Development
- coverage (test coverage reporting)

### Testing
- Django TestCase
- DRF APITestCase

Full list: See `requirements.txt`

---

## 🎯 API Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/register/` | POST | User registration |
| `/api/auth/login/` | POST | User login |
| `/api/stores/` | GET/POST | List/create stores |
| `/api/stores/{id}/` | GET/PATCH/DELETE | Store operations |
| `/api/stores/{id}/settings/` | PATCH | Update store settings |
| `/api/stores/{id}/domains/` | GET/POST | Domain management |
| `/api/stores/{id}/categories/` | GET/POST | Category operations |
| `/api/stores/{id}/products/` | GET/POST | Product operations |
| `/api/stores/{id}/products/{id}/` | GET/PATCH/DELETE | Product details |
| `/api/docs/` | GET | Swagger UI documentation |
| `/api/redoc/` | GET | ReDoc documentation |
| `/api/schema/` | GET | OpenAPI schema (JSON) |

---

## 📞 Support & Contribution

### Reporting Issues
1. Check GitHub Issues
2. Check troubleshooting section
3. Check logs in `logs/` directory
4. Create new issue with:
   - Error message
   - Steps to reproduce
   - System info
   - Logs

### Contributing
1. Create feature branch: `git checkout -b feature/name`
2. Make changes
3. Run tests: `python manage.py test`
4. Commit: `git commit -m "description"`
5. Push: `git push origin feature/name`
6. Create Pull Request

---

## 📄 License

MIT License - See LICENSE file

---

## Version History

- v1.0.0 (2024-04-08)
  - Initial release
  - Complete API endpoints
  - Multi-tenant support
  - API documentation
  - CI/CD pipeline
  - 126 tests passing
