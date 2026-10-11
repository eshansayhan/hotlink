import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_JSON = os.path.join(ROOT, "version.json")
VERSION_H = os.path.join(ROOT, "core_cpp", "src", "version.h")

def bump(part="patch"):
    if not os.path.exists(VERSION_JSON):
        data = {"major": 1, "minor": 0, "patch": 0, "build": 1, "version": "1.0.0"}
    else:
        with open(VERSION_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

    if part == "major":
        data["major"] += 1
        data["minor"] = 0
        data["patch"] = 0
        data["build"] = data.get("build", 0) + 1
    elif part == "minor":
        data["minor"] += 1
        data["patch"] = 0
        data["build"] = data.get("build", 0) + 1
    elif part == "patch":
        data["patch"] += 1
        data["build"] = data.get("build", 0) + 1
    elif part == "build":
        data["build"] = data.get("build", 0) + 1
    # if part == "sync", keep current values
    data["version"] = f"{data['major']}.{data['minor']}.{data['patch']}"
    data["releaseDate"] = datetime.now().strftime("%Y-%m-%d")

    # 1. Update version.json
    with open(VERSION_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[*] version.json güncellendi: v{data['version']} (Build {data['build']})")

    # 2. Update or create version.h for C++
    os.makedirs(os.path.dirname(VERSION_H), exist_ok=True)
    header_content = f"""// Otomatik uretilmistir. Manuel degistirmeyiniz.
#pragma once

#define HF_VERSION_MAJOR {data['major']}
#define HF_VERSION_MINOR {data['minor']}
#define HF_VERSION_PATCH {data['patch']}
#define HF_VERSION_BUILD {data['build']}
#define HF_VERSION_STRING "{data['version']}"
#define HF_APP_NAME "HFVideoPlatform"
#define HF_COMPANY_NAME "HFStream Network"
#define HF_LEGAL_COPYRIGHT "Copyright (C) 2026 Eshan Sayhan"
"""
    with open(VERSION_H, "w", encoding="utf-8") as f:
        f.write(header_content)
    print(f"[*] core_cpp/src/version.h güncellendi: v{data['version']}")

if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"
    bump(part)
