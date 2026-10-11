import requests, re

urls = [
    'https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/livecenter-serverless/static/js/main.fb8cbd18.js',
    'https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/livecenter-serverless/static/js/2467.c6aa8eae.js'
]
for u in urls:
    res = requests.get(u)
    # find occurrences of webcast and finish
    matches = re.findall(r'(/webcast/[^"\']*(?:finish|close)[^"\']*)', res.text)
    print(u[-20:], matches)
    for m in re.finditer(r'finish_abnormal|anchor_finish|anchor_pre_finish|finish/', res.text):
        idx = m.start()
        start = max(0, idx - 100)
        end = min(len(res.text), idx + 200)
        print("CONTEXT:", res.text[start:end])
        print("="*40)
