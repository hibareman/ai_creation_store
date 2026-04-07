# AI Backend Development Protocol


## Purpose
هذا الملف هو الدليل الرسمي لأي AI Agent يعمل على Backend هذا المشروع.

الهدف من هذا الملف:
- تنظيم طريقة تنفيذ المهام
- ضمان الالتزام بالمعمارية
- منع هلوسة الذكاء الاصطناعي
- الحفاظ على جودة الكود
- ضمان العزل بين المتاجر (Multi-Tenant Isolation)

⚠️ يجب اتباع هذا البروتوكول لكل مهمة بدون استثناء.

---

# Project Context

Framework: Python + Django  
Project Type: Multi-Tenant Backend API  
Database: PostgreSQL With JSONB columns where needed  

---

## Framework used: 
Python + Django


# System Architecture

المشروع يعتمد على:

Layered Architecture

مع استخدام:

Service-Based Architecture لميزات الذكاء الاصطناعي.

---

## Layered Architecture

النظام مقسم إلى طبقات واضحة:

API Layer  
Service Layer  
Data Access Layer  
Database Layer  

---
## Django App Structure

كل Django App يجب أن يتبع الهيكل التالي:

app_name/

models.py  
views.py  
serializers.py  
services.py  
selectors.py  
urls.py  
tests/  
---

# Layer Responsibilities

## API Layer

Files:
views.py  
serializers.py  
urls.py  

Responsibilities:

- استقبال HTTP requests
- التحقق من المدخلات
- استدعاء service
- إرجاع response

⚠️ ممنوع وضع business logic داخل views.

---

## Service Layer

Files:
services.py

Responsibilities:

- تنفيذ business logic
- تنسيق العمليات
- استدعاء selectors أو models

Examples:

create_store()  
update_product()  
generate_ai_store()  

---

## Data Access Layer

Files:
selectors.py

Responsibilities:

- قراءة البيانات من قاعدة البيانات
- تنفيذ queries
- تحسين الأداء

Examples:

get_store_by_id()  
get_products_for_store()  

---

## Database Layer

Files:
models.py

Responsibilities:

- تعريف Models
- العلاقات بين الجداول
- قيود البيانات

---

# AI Services Architecture

Service-Based Architecture تستخدم لميزات الذكاء الاصطناعي.

Example structure:

ai_services/

store_generator_service.py  
product_description_service.py  
design_generation_service.py  

كل AI Service يجب أن تكون:

- معزولة
- قابلة للاستبدال
- لا تحتوي منطق خاص بالـ API

---

# Multi-Tenant Rules

النظام Multi-Tenant.

كل البيانات يجب أن تكون مرتبطة بـ:

tenant_id  
store_id  

---

## Mandatory Query Rule

❌ غير صحيح

Product.objects.all()

✅ الصحيح

Product.objects.filter(store=current_store)

---

# Task Execution Workflow

أي مهمة يجب أن تتبع الخطوات التالية.

---
# Task Execution Workflow

أي مهمة يجب أن تتبع الخطوات التالية.

اتبع الخطوات التالية لإكمال مهامك :
Step 1. فهم المهمة Understand Task
- قراء وصف المهمة بعناية 
- قبل أي تنفيذ يجب فهم:
  - الهدف
  - المدخلات
  - المخرجات
  - القيود
- إذا كان هناك غموض:
اسألني وسأوضح لك الأمر.
الهدف من ذلك أن تكون الفكرة مفهومة لك بشكل جيد و تكون متطابقة مع متطلباتي (تكون صح من الناحية التقنية و متوافقة مع الشي ألي أنا احتاجه)


## step 2. جمع المتطلبات 
- قم بتوفير جميع الموارد اللازم لتنفيذ المتطلب 
- تأكد أنني قمت لك جميع الملفات المطلوبة و المراجع


## step 3.تخطيط النهج و التنفيذ Implementation Plan:
- قسم المهام إلى مهام أصغر و أكثر قابلية للإدارة 
- قبل التنفيذ يجب تقديم خطة التنفيذ :
 - قدم لي الخطة لتنفيذ المتطلب و انتظر موافقتي 
 Example:
Plan:
1. Create model
2. Create serializer
3. Implement service
4. Add API endpoint
5. Write tests


## step 4.Identify Affected Filesقبل كتابة الكود يجب تحديد الملفات المتأثرة:
Example:

stores/models.py  
stores/services.py  
stores/views.py  
tests/test_store_creation.py

-
## Step 5 — Implementation

ابدأ التنفيذ فقط بعد موافقتي.

## Step 6 — Testing اختبار العمل :
تحقق أن كل خطوة  مكتملة و أن كل شي كما هو متوقع 
راجع عملك من حيث الدقة و الكمال 
كل كود جديد يجب أن تقوم باختباره اختر نوع الاختبار المناسب و نفذه 
مثل :
Unit Tests  
Integration Tests


## step 7. Tenant Tests هذا هو اهم اختبار في مشروعنا لازم كل مرة تتحقق منه
يجب اختبار العزل بين المتاجر.
Example:
User A → Store A  
User B → Store B
ويجب التأكد أن:
User A cannot access Store B


## step 8. التسليم:
قدم لي شرحا كافيا لما قمت به من عمل 

كرر هذه الخطوات السابقة من اجل كل مهمة اطلبها منك 



## Function Design
الدوال يجب أن تكون:
- قصيرة
- واضحة
- ذات مسؤولية واحدة
إذا تجاوزت الدالة:
30 lines
يجب تقسيمها.

## Documentation

أي دالة عامة يجب أن تحتوي:

docstring

Example:

def create_store(owner, name):
    """
    Creates a new store for a given owner.
    """
    pass


# 8. Database Constraints

قاعدة البيانات عنصر حساس في المشروع.

ممنوع على AI القيام بالتالي دون موافقة المطور:

- حذف جداول
- حذف migrations
- تعديل العلاقات الأساسية
- تغيير schema بشكل قد يكسر البيانات

---

## Allowed Database Operations

مسموح فقط:

- إضافة Models جديدة
- إضافة Fields
- إنشاء Migrations

مع توضيح السبب.

---

# 9. API Constraints

ممنوع:

- تغيير endpoints موجودة
- تغيير response structure
- حذف APIs

إلا إذا طلب المطور ذلك صراحة.

---

# 10. Dependency Rules

ممنوع إضافة مكتبات جديدة بدون سبب واضح.

عند اقتراح مكتبة يجب ذكر:

- لماذا نحتاجها
- البدائل
- تأثيرها على المشروع

---

# 11. Performance Rules

يجب تجنب:

N+1 Queries

واستخدام:

select_related  
prefetch_related

عند الحاجة.

---

# 12. Logging and Error Handling

أي منطق مهم يجب أن يحتوي:

Error Handling مناسب.

يمكن إضافة logging عند الحاجة.

لكن يجب تجنب logging المفرط.

---

# 13. Security Rules

ممنوع:

- تخزين كلمات المرور كنص صريح
- وضع secrets داخل الكود
- تسريب معلومات حساسة

يجب استخدام:

Environment Variables

---

# 14. AI Hallucination Prevention Rules

هذه القواعد تقلل أخطاء AI.

---

## Never Invent

ممنوع اختراع:

- database schema
- models
- APIs
- business rules

---

## Never Guess

إذا لم يكن واضحًا:

ASK THE DEVELOPER

---

## Never Over-Engineer

ممنوع:

- تعقيد الحل
- بناء أنظمة غير مطلوبة

---

# 15. Final Validation Before Delivering Code

قبل تسليم الكود يجب تنفيذ هذا الفحص:

Architecture
- هل الكود يلتزم بالـ Layered Architecture؟
- هل business logic موجود في services؟

Structure
- هل Django app مقسم إلى طبقات؟

Multi-Tenant
- هل كل query مقيدة بـ tenant أو store؟

Testing
- هل تمت إضافة الاختبارات؟

Code Quality
- هل الكود يتبع PEP8؟
- هل الدوال أقل من 30 سطر؟

Security
- هل يوجد secrets داخل الكود؟

Performance
- هل هناك احتمال N+1 query؟

---

# 16. Final Rule

المطور هو صاحب القرار النهائي.

إذا تعارضت أي قاعدة مع تعليمات المطور:

تعليمات المطور هي المرجع الأعلى.






This protocol must be followed for every task without exception.



# AI Backend Development Protocol – Extended with Non-Functional Requirements

## Purpose
هذا الملف هو الدليل الرسمي لأي AI Agent يعمل على Backend هذا المشروع.  
يهدف هذا القسم لإضافة التوجيهات المتعلقة بالمتطلبات غير الوظيفية، لضمان:

- الأداء
- الأمان
- العزل بين المتاجر
- القابلية للتوسع
- الصيانة المستمرة
- تجربة مستخدم واضحة

⚠️ يجب على AI Agent الالتزام بهذه التوجيهات عند تنفيذ أي مهمة.

---

# Non-Functional Requirements (المتطلبات غير الوظيفية)

## 1. Data Isolation – عزل البيانات بين المتاجر

**القيود والقواعد:**
- يجب ضمان عدم وصول أي مستخدم إلى بيانات متجر آخر.
- كل عمليات CRUD يجب أن تتم ضمن سياق tenant_id/store_id.
- أي طلب بدون tenant context يجب رفضه فورًا.

**تنفيذ التصميم:**
- **Database Layer:** جميع الجداول تحتوي على عمود tenant_id.
- **Application Layer:** تمرير tenant_id لجميع Controllers و Services.
- **Middleware:** استخراج tenant context من التوكن (JWT).
- **Data Access Layer:** تصفية كل الاستعلامات بواسطة tenant_id.
- **Security Controls:** التحقق من ملكية الموارد قبل منح الوصول.

---

## 2. Performance – الأداء

**القيود والقواعد:**
- يجب أن يتم تسليم النسخة الأولية للمتجر المولّد بالذكاء الاصطناعي خلال 3–5 ثوانٍ.
- العمليات العادية يجب أن تبقى ضمن أوقات استجابة مقبولة.
- العمليات الطويلة للذكاء الاصطناعي لا يجب أن تمنع تفاعل المستخدم.

**تنفيذ التصميم:**
- **AI Generation:** إنشاء مسودة أولية محدودة (2–4 منتجات فقط).
- **Pipeline:** استدعاء واحد للـ AI لتقليل التأخير.
- **Backend Handling:** معالجة قليلة أثناء الطلب المتزامن.
- **UI Feedback:** عرض مؤشرات تحميل للمستخدم.
- **Timeout Protection:** استخدام آلية fallback إذا تجاوزت الاستجابة الوقت المحدد.

---

## 3. Security – الأمان

**القيود والقواعد:**
- لا تخزن كلمات مرور كنص صريح.
- لا تستخدم secrets داخل الكود.
- التحقق من صحة المدخلات وفلترة المحتوى الضار.

**التعامل مع المحتوى المولّد من AI:**

| النوع | الوصف | التعامل |
|-------|------|---------|
| Schema Violation | عدم تطابق JSON | إعادة توليد جزئية أو fallback |
| Malformed Data | JSON غير قابل للمعالجة | validation failure → fallback |
| Offensive Content | كلمات مسيئة | فلترة أو استبدال المحتوى |
| Irrelevant Data | منتجات/فئات خارج نطاق المتجر | فلترة وتسجيل | 
| Sensitive Data Leakage | كشف بيانات شخصية | حظر وتسجيل تنبيه |

**تنفيذ التصميم:**
- **Tenant-Scoped AI Requests:** كل استدعاء AI يحتوي tenant_id وstore_id.
- **Prompt Sanitization:** تنظيف مدخلات المستخدم.
- **AI Response Handling:** تحقق من JSON schema وفلترة المحتوى.
- **Service & API Enforcement:** منع أي عمليات بين tenants.
- **Audit & Logging:** تسجيل كل حدث AI مع tenant info.

---

## 4. Scalability – القابلية للتوسع

**القيود والقواعد:**
- دعم الطلبات المتزامنة دون فقدان الأداء.
- السماح بإضافة Instances للخدمات دون تغيير معماري.

**تنفيذ التصميم:**
- **AI Service Scaling:**  
  - نشر AI Service كـ stateless instances  
  - استخدام Load Balancer  
  - التوسع أفقيًا حسب الحمل
- **Backend Service Scaling:**  
  - stateless services للتوسع الأفقي  
- **Database Scaling:**  
  - استخدام indexes على tenant_id  
  - استخدام read replicas  
  - تقسيم البيانات حسب tenant إذا لزم الأمر
- **Workload Distribution:**  
  - عزل عمليات AI عن العمليات الأساسية  

---

## 5. Availability – التوفر

**القيود والقواعد:**
- في حال فشل AI Service أو بطء الاستجابة، يجب تقديم بديل خلال 1–2 ثانية.
- المستخدم يجب أن يواصل عملية إنشاء المتجر بدون توقف.

**تنفيذ التصميم:**
- **Fallback Mechanism:**  
  - إذا نجح AI → عرض المتجر  
  - إذا فشل أو تجاوز الوقت → عرض قالب جاهز  
- **User Flow:**  
  - يمكن للمستخدم العمل بالقالب أو إعادة المحاولة لاحقًا  
- **Asynchronous Processing:**  
  - النتائج يمكن إرسالها لاحقًا إذا تأخرت  
- **System Design:**  
  - Backend stateless لتحسين التوفر  

---

## 6. Usability – سهولة الاستخدام

**القيود والقواعد:**
- يجب أن تكون واجهة المستخدم بسيطة وواضحة (3–5 خطوات لإنشاء متجر).
- توضيح حالة النظام خلال AI processing.
- سهولة تعديل محتوى AI الناتج.

**تنفيذ التصميم:**
- **Simple User Flow:** خطوات مبسطة لإنشاء المتجر.  
- **Feedback & Status:** مؤشرات تحميل ورسائل واضحة.  
- **Editable AI Output:** السماح بتعديل البيانات المولدة.  
- **Consistent UI Design:** استخدام layout و navigation ثابتة.  
- **Error Handling:** رسائل خطأ ودية وخيارات استرداد.

---

## 7. Maintainability – قابلية الصيانة

**القيود والقواعد:**
- فصل المسؤوليات بين المكونات (Controllers, Services, Data Access).  
- تغييرات في وحدة واحدة لا تؤثر على الوحدات الأخرى.  
- إضافة ميزات جديدة يجب أن يكون لها تأثير محدود.  

**تنفيذ التصميم:**
- **Layered Architecture:** Presentation → Controller → Service → Data Access  
- **Service-Based Design:** عزل وظائف AI وStore Service  
- **Loose Coupling:** واجهات واضحة بين المكونات  
- **Code Organization:** بنية متسقة داخل Django apps  
- **Separation of AI Logic:** وحدة AI مستقلة لتسهيل الاستبدال أو التحديث  

---

# Integration with AI Agent

- كل هذه التوجيهات تصبح جزء من **AI Self-Check System**.
- قبل تنفيذ أي كود، يجب على AI Agent مراجعة:  
  - الأداء، الأمان، العزل، التوسع، التوفر، سهولة الاستخدام، والصيانة.  
  - التأكد من الالتزام بالـ Layered Architecture وService-Based Design.  
  - التحقق من أن كل استعلامات البيانات مقيدة بـ tenant_id.  
  - عدم إجراء أي تغييرات على قواعد البيانات أو API بدون إذن المطور.  
  - إضافة اختبارات لكل وظيفة جديدة.

  ---