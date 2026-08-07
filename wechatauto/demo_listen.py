# -*- coding: utf-8 -*-
"""实时消息监听示例 —— 基于本地数据库增量轮询（Listener）

用法：
    python demo_listen.py [会话名1] [会话名2] ...
    # 不带参数则默认监听「文件传输助手」

例：
    python demo_listen.py 文件传输助手 我的群
    python demo_listen.py --all        # 监听所有非隐藏会话
"""
from __future__ import annotations

import os
import sys
import time
import threading

try:
    os.system("chcp 65001 >nul 2>&1")
except Exception:
    pass
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from wechatauto.db import WeChatDB, Listener


def fmt_time(ts: float) -> str:
    return time.strftime("%m-%d %H:%M:%S", time.localtime(ts))


def sender_name(db, sid: int) -> str:
    if sid == 2:
        return "我"
    nick = db.get_nickname(sid) if isinstance(sid, str) else None
    return nick or f"用户{sid}"


def make_callback(db, chat_name: str):
    """为某个会话生成回调函数。callback(msg: dict, listener)"""
    def on_msg(msg: dict, lst: Listener):
        sender = sender_name(db, msg["sender_id"])
        t = fmt_time(msg["create_time"])
        print(f"[{t}] {chat_name} | {sender} ({msg['type']}) {msg['content']}")
        # 可在此扩展业务：msg['content'] 含关键字时自动回复等
    return on_msg


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    all_chats = "--all" in sys.argv

    db = WeChatDB()
    info = db.get_self_info()
    print(f"账号：{info.get('nick_name') or info.get('username')}")

    # 1. 列出当前会话，供挑选
    sessions = db.get_sessions(limit=30)
    print(f"\n当前会话（共 {len(sessions)} 个，最近 15 个）：")
    for s in sessions[:15]:
        print(f"  {s['username']:<24} 未读={s['unread']}  {s['summary'][:24] or ''}")

    # 2. 确定监听目标
    if all_chats:
        names = [s["username"] for s in sessions]
    elif not names:
        names = ["wxid_x0xigu0t3d1922"]
    if not names:
        print("未找到任何会话，退出")
        sys.exit(1)

    # 3. 注册监听（回调在后台线程触发）
    lst = Listener(db, interval=1.0)
    for name in names:
        lst.add_listener(name, make_callback(db, name))
        print(f"  监听：{name}")

    print("\n开始监听（Ctrl+C 停止）...")
    lst.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        lst.stop()
        print("\n已停止监听。")


if __name__ == "__main__":
    main()
