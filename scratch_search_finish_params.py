import requests, re

res = requests.get('https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/livecenter-serverless/static/js/main.fb8cbd18.js')
text = res.text

for target in ['finish_abnormal', 'anchor_pre_finish', 'anchor_finish_info']:
    for m in re.finditer(re.escape(target), text):
        idx = m.start()
        start = max(0, idx - 400)
        end = min(len(text), idx + 400)
        print(f"=== {target} ===")
        print(text[start:end])
