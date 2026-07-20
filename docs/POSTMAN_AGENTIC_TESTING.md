# اختبار Agentic AI Store Creation بعد Phase 1M

## أولًا: نسخ الملفات

استبدل الملفات التالية في مشروعك:

```text
AI_Store_Creation_Service/serializers.py
AI_Store_Creation_Service/views.py
AI_Store_Creation_Service/tests.py
```

وانسخ الملفات الجديدة:

```text
docs/postman/AI_Store_Agentic.postman_collection.json
docs/postman/AI_Store_Local.postman_environment.json
docs/POSTMAN_AGENTIC_TESTING.md
```

الملفات `constants.py` و`agentic_production_services.py` و`agentic/merging.py`
مرفقة في الحزمة لأنها تحتوي أصلًا منطق 1M المطلوب، ولم تحتج تعديلًا جديدًا.

## إعداد `.env`

```env
AI_AGENTIC_WORKFLOW_ENABLED=True
CACHE_BACKEND=locmem
AI_DRAFT_TTL=3600

AI_PROVIDER=ollama
AI_API_URL=<OLLAMA_URL>
AI_API_KEY=<OLLAMA_KEY_IF_REQUIRED>
AI_MODEL_NAME=<MODEL_NAME>
AI_TIMEOUT=60
AI_MAX_TOKENS=4096
AI_TEMPERATURE=0.2
```

بعد تعديل الـFeature Flag أعد تشغيل السيرفر.

## تجهيز المشروع

```bash
python manage.py migrate
python manage.py check
```

يجب وجود ThemeTemplate واحدة على الأقل:

```bash
python manage.py shell
```

```python
from themes.models import ThemeTemplate

ThemeTemplate.objects.get_or_create(
    name="Modern",
    defaults={"description": "Modern local test template"},
)
```

ثم:

```bash
python manage.py runserver
```

Swagger:

```text
http://127.0.0.1:8000/api/docs/
```

## تشغيل الاختبارات

```bash
python manage.py test AI_Store_Creation_Service.tests.AIAgenticApiEndToEndTests --keepdb
```

ثم:

```bash
python manage.py test \
AI_Store_Creation_Service.tests.AICreationApiTests \
AI_Store_Creation_Service.tests.AIAgenticProductionBridgeTests \
AI_Store_Creation_Service.tests.AIFeatureFlagProductionRoutingTests \
--keepdb
```

ثم:

```bash
python manage.py test AI_Store_Creation_Service --keepdb
python manage.py spectacular --file schema.yml
python -m pip check
```

## استيراد Postman

استورد:

```text
docs/postman/AI_Store_Agentic.postman_collection.json
docs/postman/AI_Store_Local.postman_environment.json
```

ثم اختر:

```text
AI Store Local — Phase 1M
```

## تسلسل الاختبار الكامل

### 1. إنشاء الحساب

شغّل:

```text
Authentication → 1. Register Store Owner
```

المسار:

```http
POST /api/auth/register/
```

المتوقع:

```text
HTTP 201
Activation email sent. Please check your inbox.
```

### 2. تفعيل الحساب

الحساب الجديد غير فعال حتى فتح رابط التفعيل.

انسخ UUID من رابط التفعيل وضعه في:

```text
activation_token
```

ثم شغّل:

```text
Authentication → 2. Activate Account
```

للحصول على التوكن محليًا عند عدم توفر البريد:

```bash
python manage.py shell
```

```python
from users.models import User
user = User.objects.get(email="phase1m_owner@example.com")
print(user.activation_token)
```

### 3. تسجيل الدخول

شغّل:

```text
Authentication → 3. Login
```

Postman يحفظ `access_token` تلقائيًا.

### 4. إنشاء متجر بوصف واضح

شغّل:

```text
4. Start — Clear Description
```

المتوقع:

```text
HTTP 201
draft_metadata.workflow_engine = agentic
draft_metadata.status = ready_for_review
```

### 5. إنشاء متجر بوصف غامض

شغّل:

```text
5. Start — Vague Description
```

المتوقع غالبًا:

```text
HTTP 201
draft_metadata.status = needs_clarification
```

Postman يحفظ تلقائيًا:

```text
store_id
question_key
selected_option
```

### 6. إرسال الإجابة

شغّل:

```text
7. Submit Clarification Answers
```

المتوقع:

```text
HTTP 200
```

والحالة تصبح:

```text
ready_for_review
```

أو سؤال جديد:

```text
needs_clarification
```

أو فشل قابل للاستعادة:

```text
failed_recoverable
```

### 7. استرجاع المسودة

شغّل:

```text
6. Get Current Draft
8. Get Updated Draft
```

المتوقع:

```text
HTTP 200
workflow_engine = agentic
```

### 8. التأكد من رفض العمليات المؤجلة

شغّل:

```text
9. Regenerate — Expected Agentic Rejection
10. Apply — Expected Agentic Rejection
```

المتوقع:

```json
{
  "detail": "This operation is not available for the current AI session yet.",
  "error_code": "agentic_operation_not_available"
}
```

مع HTTP 400.

### 9. اختبار غياب JWT

شغّل:

```text
11. Unauthorized Check
```

المتوقع:

```text
HTTP 401
```

## ملاحظات

- لا ترسل `tenant_id` أو `user_id` في body.
- مع `LocMemCache` تضيع جلسة Agentic عند إعادة تشغيل السيرفر.
- استخدم `store_id` جديدًا لكل مقارنة بين Legacy وAgentic.
- `AI_AGENTIC_WORKFLOW_ENABLED=False` يجعل عمليات Start الجديدة Legacy.
- الجلسة Agentic الموجودة تظل Agentic حتى بعد إطفاء الـFlag.
- Agentic Apply وRegenerate مؤجلان بعد 1M.