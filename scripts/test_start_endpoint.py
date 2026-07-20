import os
import sys
import django
import json
from urllib import request, parse

# ensure project root is on sys.path so `config` settings module is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

EMAIL = 'postman_test@example.com'
PASSWORD = 'TestPass123!'

# Create or get user
user, created = User.objects.get_or_create(email=EMAIL, defaults={'username': 'postman_test'})
if created:
    user.set_password(PASSWORD)
    user.is_active = True
    user.save()
else:
    user.set_password(PASSWORD)
    user.is_active = True
    user.save()

BASE = 'http://127.0.0.1:8000'

# Helper to POST JSON
def post_json(url, data, headers=None):
    data_bytes = json.dumps(data).encode('utf-8')
    req = request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'} if not headers else headers)
    try:
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8')
            return resp.getcode(), json.loads(body)
    except Exception as e:
        print('Request error', url, e)
        return None, None

# 1) Login
login_url = BASE + '/api/auth/login/'
login_payload = {'email': EMAIL, 'password': PASSWORD}
code, body = post_json(login_url, login_payload)
print('Login:', code, body)
if not body or 'access' not in body:
    print('Login failed; aborting')
    exit(1)

access = body['access']
headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {access}'}

# 2) Start draft
start_url = BASE + '/api/ai/stores/draft/start/'
start_payload = {'user_description': 'Automated Postman test store description.'}
code, body = post_json(start_url, start_payload, headers=headers)
print('Start:', code, json.dumps(body, indent=2))

# 3) If store created, show store_id and any clarification questions
if body and 'store_id' in body:
    print('store_id:', body['store_id'])
    print('draft_payload:', body.get('draft_payload'))

print('Done')
