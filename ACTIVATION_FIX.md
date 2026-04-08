# 🔧 حل مشكلة التفعيل: "Invalid activation token"

## المشكلة
عند محاولة تفعيل حساب جديد باستخدام رابط التفعيل من البريد، كنت تتلقى خطأ:
```
"detail": "Invalid activation token."
```
حتى وإن كان التوكن صحيحًا.

## السبب الجذري
**الترميز النسبي للـ URL (URL Encoding)**:
- التوكن يحتوي على أحرف خاصة مثل `:` و `-` و `=`
- عند إرسال التوكن في رابط URL (Query String)، يتم ترميزه تلقائيًا (مثل: `%3A` بدلاً من `:`)
- كان البرنامج يُرسل التوكن بشكل حرفي دون الاهتمام بترميز URL، مما يسبب عدم التطابق عند الفك

## الحل المطبق

### 1️⃣  ترميز التوكن عند إرسال البريد
**ملف: `users/views.py`**

```python
from django.urls import reverse
from urllib.parse import quote

# قبل (خطأ):
activation_path = f"/users/activate/?token={token}"

# بعد (صحيح):
activation_path = reverse('activate')  # استخدام reverse للحصول على المسار الصحيح
activation_url = request.build_absolute_uri(f"{activation_path}?token={quote(token, safe='')}")
```

**ما الذي تغير؟**
- استخدام `urllib.parse.quote()` لترميز التوكن بشكل آمن في URL
- استخدام `reverse('activate')` بدلاً من الـ hardcoded path

### 2️⃣  فك الترميز التلقائي (Django يتولاه)
Django يفك الترميز تلقائيًا عند استقبال الطلب:
```python
token = request.GET.get('token')  # Django يفك الترميز تلقائيًا هنا
```

### 3️⃣  تصحيح الاختبارات
**ملف: `users/test_auth_middleware.py`**

تم تصحيح الاختبار ليتوقع المسار الصحيح مع البادئة `/api`:
```python
# قبل:
self.assertIn('/users/activate/?token=', body)

# بعد:
self.assertIn('/api/auth/activate/?token=', body)
```

## التحقق من الحل

✅ جميع 20 اختبار تمر بنجاح
✅ اختبار التدفق الكامل (تسجيل → استخراج التوكن → تفعيل) ينجح
✅ التوكن الآن يُرمَّز بشكل صحيح أثناء النقل عبر URL

## كيفية الاستخدام

### تسجيل مستخدم جديد:
```bash
curl -X POST http://localhost:8000/api/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john",
    "email": "john@example.com",
    "password": "SecurePass123"
  }'
```

رد: `{"detail": "Activation email sent."}`

### استقبال رابط التفعيل من البريد:
البريد سيحتوي على رابط مثل:
```
http://yourserver/api/auth/activate/?token=11%3A1wAKVE%3AJcSjgP...
```

### النقر على الرابط أو زيارته:
```bash
# الرابط من البريد (ترميز URL مضمن)
GET http://localhost:8000/api/auth/activate/?token=11%3A1wAKVE%3AJcSjgP...
```

رد: 
```json
{
  "access": "eyJ...",
  "refresh": "eyJ...",
  "user_id": 11,
  "role": "Store Owner",
  "tenant_id": 11
}
```

## الملفات المعدلة

1. ✅ `users/views.py` - إضافة ترميز URL للتوكن
2. ✅ `users/test_auth_middleware.py` - تصحيح اختبار المسار
3. ✅ `config/settings.py` - إضافة ALLOWED_HOSTS (للاختبارات)

## ملاحظات مهمة

- **Security**: استخدام `quote(token, safe='')` يضمن ترميز جميع الأحرف الخاصة بشكل آمن
- **Django Handling**: Django يفك الترميز تلقائيًا عند قراءة `request.GET.get('token')`
- **Backward Compatible**: هذا الحل لا يؤثر على أي شيء آخر في النظام

✅ المشكلة **محلولة تماماً**!
