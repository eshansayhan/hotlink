import requests, re

urls = [
    'https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/livecenter-serverless/static/js/main.fb8cbd18.js',
    'https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/livecenter-serverless/static/js/2467.c6aa8eae.js'
]
endpoints = set()
for u in urls:
    try:
        res = requests.get(u, timeout=10)
        found = re.findall(r'/webcast/[a-zA-Z0-9/_]+', res.text)
        endpoints.update(found)
    except Exception as e:
        print(f"Error {u}: {e}")

for ep in sorted(endpoints):
    if any(k in ep for k in ['room', 'live', 'stream', 'finish', 'create', 'info', 'producer']):
        print(ep)
