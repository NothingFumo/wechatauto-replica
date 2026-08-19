# -*- coding: utf-8 -*-
"""密钥提取失败诊断脚本。

在微信【已登录】状态下运行（务必让微信窗口保持打开）：

    python -m wechatauto.diagnose_keys

或直接：

    python wechatauto/diagnose_keys.py

把输出完整发给维护者。
"""
import json
import os
import subprocess
import sys
import traceback

print("=" * 60)
print("wechatauto-replica key diagnostic")
print("=" * 60)
print("Python:", sys.version.split()[0])
print("OS:", sys.platform)

# 1. library version
try:
    import wechatauto
    from wechatauto import WeChatDB
    print("lib version:", getattr(wechatauto, "__version__", "?"))
    import wechatauto.db as dbmod
    print("db.py:", dbmod.__file__)
except Exception as e:
    print("import error:", repr(e))
    traceback.print_exc()

# 2. Weixin processes
print("\n--- Weixin processes ---")
try:
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True)
    print("tasklist:\n%s" % (r.stdout.strip() or "(no Weixin.exe)"))
except Exception as e:
    print("tasklist failed:", repr(e))

# 3. data dir detection
print("\n--- data dir ---")
try:
    from wechatauto.db import auto_detect_db_dir
    d = auto_detect_db_dir()
    print("auto_detect_db_dir:", d)
    if d and os.path.isdir(d):
        for x in os.listdir(d):
            if x.startswith("wxid_"):
                print("  account dir:", x)
except Exception as e:
    print("dir detect error:", repr(e))

# 4. WeChatDB init (uses cached keys)
print("\n--- WeChatDB init ---")
db = None
try:
    db = WeChatDB()
    print("workdir:", db.workdir)
    print("keys_file:", db.keys_file, "exists:", os.path.exists(db.keys_file))
    print("account:", db.account)
    if os.path.exists(db.keys_file):
        with open(db.keys_file, encoding="utf-8") as f:
            keys = json.load(f)
        print("keys cached:", len(keys))
        for k in sorted(keys):
            print("   ", k)
    else:
        print("keys cached: (file not found)")
    print("db_files:", len(db._db_files))
    print("keys loaded:", len(db._keys))
    missing = [rel for rel, _, _ in db._db_files if rel not in db._keys]
    print("missing:", missing)
    print("unkeyed:", db.unkeyed)
except Exception as e:
    print("init error:", repr(e))
    traceback.print_exc()

# 5. fresh key extraction from memory
print("\n--- extract_keys from Weixin.exe memory ---")
try:
    if db is None:
        db = WeChatDB()
    pids = db._find_weixin_pids()
    print("Weixin PIDs:", pids)
    if not pids:
        print("no Weixin.exe running - open WeChat and log in first")
    else:
        keys = db.extract_keys()
        print("extracted:", len(keys))
        for k in sorted(keys):
            print("   ", k)
        missing2 = [rel for rel, _, _ in db._db_files if rel not in keys]
        print("still missing:", missing2)
except Exception as e:
    print("extract error:", repr(e))
    traceback.print_exc()

# 6. verify cached keys actually work
print("\n--- verify cached keys ---")
try:
    if db is None:
        db = WeChatDB()
    works = 0
    for rel, _, _ in db._db_files:
        if db._key_works(rel):
            works += 1
    print("keys that verify: %d / %d" % (works, len(db._db_files)))
except Exception as e:
    print("verify error:", repr(e))

print("=" * 60)
print("done. send the full output to the maintainer.")
print("=" * 60)