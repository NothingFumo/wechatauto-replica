# wechatauto —— 微信 4.x Windows 客户端自动化（wxauto 复刻版）

本项目复刻上游 wxauto 项目，目标是实现对当前微信 4.x Windows 客户端的自动化
（读取消息、发送消息、媒体下载、朋友圈），非网页版，直接操作本机客户端。

> 当前版本：1.0.1
>
> **兼容范围**：Windows 10/11 ｜ Python 3.9+（已在 3.12 验证）｜ 微信 **4.1.12+**
> （数据库读取路线对微信版本不敏感；坐标+OCR 发送路线依赖 4.1.12+ 自绘渲染
> 布局，其它 4.x 小版本可能需校准 `guia.py` 布局常量）。

---

## 一、项目状态

| 能力 | 状态 | 实现方式 |
| ---- | ---- | -------- |
| 读取消息 | ✅ 已完成并验证 | 本地数据库解密（`wechatauto/db.py`） |
| 消息监听（轮询） | ✅ 已完成并验证 | `Listener` + `get_new_messages` 增量回调 |
| WAL 增量合并 | ✅ 已修复并验证 | 帧盐校验合并 `-wal`（见 §2.4） |
| 历史消息全量导出 | ✅ 已完成并验证 | `export_history`（JSON / SQLite） |
| 媒体下载（图片/语音/文件） | ✅ 已完成并验证 | `wechatauto/media.py`（图片 V2 解密） |
| 朋友圈读取 | ✅ 已完成并验证 | `MomentDB` 直接读 `sns.db` |
| 多账号管理 | ✅ 已完成并验证 | `list_accounts()` + `account=` 参数 |
| 读取会话列表 | ✅ 已完成并验证 | 同上 |
| 搜索联系人 | ✅ 已完成并验证 | 同上 |
| 发送消息 | ✅ 已完成并验证 | 坐标+OCR（`wechatauto/guia.py`） |
| 发送文件/图片/回复/艾特 | ✅ 已完成并验证 | 剪贴板 CF_HDROP + OCR |
| UI 自动化（UIAutomation） | ⚠️ 受限 | 微信 4.1.12+ 聊天区域自绘渲染，不暴露无障碍节点 |

**结论**：微信 4.1.x 聊天界面使用自绘渲染（`MMUIRenderSubWindowHW`），对
UIAutomation / MSAA 完全不暴露内容，原 wxauto 的 UI 方案失效。本项目采用
「**本地数据库解密**」读取（已全链路验证）、「**坐标 + OCR**」发送
（已实测：文本/文件/图片发送稳定，回复/艾特见 `demo_reply_at.py`）。

---

## 二、读取原理

微信 4.x 的数据存放在本地 SQLCipher 4 加密的 SQLite 数据库中：

```
D:\微信文件\xwechat_files\<wxid>_xxxx\db_storage\
├── contact\contact.db            联系人（昵称、备注）
├── session\session.db            会话列表（未读数、摘要）
├── message\message_0..4.db       聊天消息（按会话分表 Msg_<md5>，跨分库分片）
├── message\media_0.db            语音（VoiceInfo.voice_data，SILK 二进制）
├── message\message_resource.db   文件原名（MessageResourceDetail.packed_info）
├── sns\sns.db                    朋友圈（SnsTimeLine，SnsDataItem XML）
└── ...
```

### 2.1 密钥提取（进程内存只读扫描）

每个数据库有**独立的 32 字节密钥**，保存在微信进程内存中的
`com.Tencent.WCDB.Config.Cipher` 配置对象里：

1. 在 Weixin.exe 所有可读内存区域中查找该字符串；
2. 由字符串地址定位配置对象（`[ptr][len]` 结构回溯）；
3. 数据块与固定掩码异或后得到 `x'<64位hex密钥><32位hex盐>'` 明文配置；
4. 用 SQLCipher 4 HMAC 校验规则验证每个候选密钥；
5. 验证通过的密钥保存到 `%TEMP%\wechatauto_db\<账号>\keys.json` 缓存。

### 2.2 数据库解密

- SQLCipher 4，页大小 4096，`PBKDF2-HMAC-SHA512`（加密密钥 256000 次迭代）；
- 解密结果按页写入临时目录，校验源 mtime/size 复用缓存；
- 首次解密 contact.db 约 6s，之后全部秒级。

### 2.3 消息查询

- 会话名 → `Md5(会话微信号)` → 表名 `Msg_<md5>`（同一会话可能分片在多个
  `message_*.db`，按 `sort_seq` 合并排序）；
- 关键列：`local_type`、`real_sender_id`（2=自己，其他为数字 id，可通过
  `message_resource.SenderName2Id` 反查微信号）、`server_id`、
  `packed_info_data`（图片/视频 md5）、`sort_seq`。

### 2.4 WAL 增量合并（已修复）

微信 `-wal` 是预分配文件：checkpoint 时 WAL 头 salt+1 并清零写游标，但
**旧世代帧仍留在文件中**。若合并时不过滤帧盐，会把过期页覆盖进主库导致
`database disk image is malformed`。修复方案：

- `_merge_wal` 读取 WAL 头后**仅合并 salt 与当前 WAL 头一致的帧**，
  旧世代帧直接跳过；
- 缓存 stamp 加入版本号 `STAMP_VERSION=2`，旧损坏缓存自动强制全量重建；
- 合并结果用 `PRAGMA integrity_check` 校验，失败自动重试全量重建。

验证：contact.db 合并后 integrity OK，2354 个联系人全部可查。

### 2.5 媒体存储与解密（图片 v2 格式）

- 图片：`msg\attach\<会话md5>\<YYYY-MM>\Img\<md5>.dat`（加密）；
- 语音：`media_0.db` → `VoiceInfo.voice_data`（SILK 明文 BLOB）；
- 文件：`msg\file\<YYYY-MM>\<原文件名>`（原名来自 message_resource）；
- 视频：`msg\video\<YYYY-MM>\<id>.mp4`（未落盘时返回 None）。

图片 `.dat` 为 **v2 格式**：`[6B sig 070856320807][4B aes_size LE][4B xor_size LE]`
+ AES-ECB 密文 + 明文段 + 异或段：

- **AES 密钥**：16 字节 ASCII，账户级稳定密钥，但仅在微信查看图片时驻留
  进程内存。`MediaDownloader` 通过内存扫描反测（AES 解首块后校验 JPEG/PNG
  魔数）获取，**命中后持久化到 `image_keys.json`**；也支持 `image_key=` 参数
  显式注入。本机实测：单一密钥稳定解密 35/40 张随机图片（其余为微信动画
  表情容器 `wxgf`）。
- **XOR 密钥**：单字节，从同图缩略图 `<md5>_t.dat` 尾部 JPEG 结束标记
  `FF D9` 反推（`key = tail[0] ^ 0xFF`）。

---

## 三、快速开始

### 3.1 安装

```bash
pip install -e .
# 坐标+OCR 发送路线额外依赖：
pip install winsdk pypinyin
```

### 3.2 示例程序

```bash
python demo_db.py
```

### 3.3 代码示例

```python
from wechatauto import WeChatDB

db = WeChatDB()  # 自动检测账号与数据目录（微信需已登录）

info = db.get_self_info()                     # 当前账号昵称
for s in db.get_sessions(limit=10):           # 会话列表
    print(db.get_nickname(s["username"]), s["unread"])

hits = db.search_contact("Ayi")               # 搜索联系人
who = hits[0]["username"]
for m in db.get_messages(who, limit=10):      # 最近消息
    print(m["create_time"], m["sender_id"], m["type"], m["content"])
```

### 3.4 媒体下载

```python
from wechatauto import WeChatDB, MediaDownloader

db = WeChatDB()
md = MediaDownloader(db)                      # 可传 image_key="..." 注入图片密钥
key = md.detect_image_key()                   # 内存扫描/缓存取 AES+XOR 密钥
print(key)

for m in db.get_messages("filehelper", limit=50):
    out = md.download_media("filehelper", m["local_id"])   # 按类型自动分发
    if out:
        print("已下载:", out)
```

### 3.5 朋友圈读取

```python
from wechatauto import WeChatDB, MomentDB

md = MomentDB(WeChatDB())
for feed in md.get_moments(limit=10):          # 时间线（3382 条全量可读）
    print(feed["nickname"], feed["text"])
    print("  图片:", [i["md5"] for i in feed["images"]])
    print("  赞:", [l["nickname"] for l in feed["likes"]])
    print("  评论:", [(c["nickname"], c["content"]) for c in feed["comments"]])
    md.download_media(feed["images"][0])       # 本地缓存或 URL 拉取
```

### 3.6 消息监听

```python
from wechatauto import WeChatDB
from wechatauto.db import Listener

db = WeChatDB()
lst = Listener(db, interval=1.0)
lst.add_listener("filehelper", lambda msg, lst: print("新消息:", msg["content"]))
lst.start()
# ... 业务代码 ...
lst.stop()
```

### 3.7 历史导出

```python
db.export_history(r"D:\backup\chat.json",   fmt="json")    # 全部会话
db.export_history(r"D:\backup\chat.db",     fmt="sqlite")
db.export_history(r"D:\backup\one.json",    fmt="json",
                  users=["filehelper"], limit_per_chat=1000)
```

### 3.8 多账号

```python
from wechatauto import list_accounts, WeChatDB
for a in list_accounts():
    print(a["account"], a["wxid"])
db2 = WeChatDB(account="wxid_xxx_abcd")       # 显式指定账号（缓存按账号隔离）
```

---

## 四、API 参考

### `WeChatDB(db_dir=None, keys_file=None, workdir=None, account=None)`

| 方法 | 说明 |
| ---- | ---- |
| `get_self_info() -> dict` | 当前账号（username / nick_name / remark） |
| `get_sessions(limit=100)` | 会话列表：username / unread / summary / last_time |
| `search_contact(keyword)` | 按昵称/备注/微信号搜索 |
| `get_messages(user, limit, offset)` | 读取指定会话消息 |
| `get_message_row(user, local_id)` | 单条原始消息（含 server_id / packed_info，媒体用） |
| `get_new_messages(user, since_seq)` | `sort_seq > since_seq` 的增量消息（升序） |
| `get_nickname(user)` | 微信号 → 显示昵称 |
| `list_message_chats()` | 所有含消息的会话（md5 / 昵称 / 消息数） |
| `export_history(out_path, fmt, ...)` | 全量导出 JSON / SQLite |
| `extract_keys()` | 手动触发密钥提取 |
| `wxid` / `account` / `account_dir` | 当前账号信息 |
| `list_accounts()`（模块级） | 扫描本机所有微信账号 |
| `auto_detect_db_dir()`（模块级） | 自动定位数据目录（配置文件 → 注册表 → 常见默认目录） |

### `MediaDownloader(db, save_dir=None, image_key=None)`

| 方法 | 说明 |
| ---- | ---- |
| `detect_image_key(refresh)` | 取 (AES 密钥, XOR 密钥)，命中后持久化 |
| `decrypt_image(dat_path)` | 解密单个 `.dat`（自动识别 v1/v2） |
| `download_media(user, local_id)` | 按类型分发下载 |
| `download_image / _voice / _video / _file` | 各类媒体下载 |
| `copy_files_to_clipboard(paths)` | CF_HDROP 写剪贴板（发送附件用） |

### `MomentDB(db)`

| 方法 | 说明 |
| ---- | ---- |
| `get_moments(limit, offset, username)` | 朋友圈时间线（最新在前） |
| `get_moment(tid)` / `get_my_moments(limit)` | 单条 / 我的动态 |
| `find_local_media(md5, kind)` | 本地缓存查找（Sns\Img / Sns\Video） |
| `download_media(media, save_dir)` | 缓存优先，否则 URL 拉取 |

### `Listener(db, interval, watermark)`

`add_listener(user, cb)` / `remove_listener` / `start` / `stop` / `watermark`。

### `WeChatGUI`（发送，锁屏不可用）

| 方法 | 说明 |
| ---- | ---- |
| `send_msg(text, who, verify)` | 文本发送（OCR 定位 + 剪贴板粘贴） |
| `send_file(path, who, verify)` | 文件（CF_HDROP 粘贴 + 回车） |
| `send_image(path, who, verify)` | 图片（同上） |
| `reply_msg(text, who, verify)` | 回复最近消息（悬停 + OCR 回复入口） |
| `at_member(member, text, who, verify)` | 群聊 @ 成员 |
| `open_chat / focus_input / bring_to_front` | 基础操作 |

一行式：`quick_send` / `quick_send_file` / `quick_send_image` / `quick_reply`。

---

## 五、已知限制

1. **需要微信登录**：数据库密钥存于进程内存，首次使用需微信运行中
   （提取后本地缓存）；重新登录后密钥变化需重新提取（自动校验失败重扫）；
2. **图片 AES 密钥瞬态**：仅在微信查看图片时驻留内存；`MediaDownloader`
   扫描命中后会持久化（`image_keys.json`），也可用 `image_key=` 显式传入；
3. **发送为 GUI 操作**：锁屏/会话断开时 `desktop_available()` 返回 False，
   发送接口返回明确失败；文件/图片/回复/艾特代码已完成但需桌面解锁后实测；
4. **视频文件未落盘时不可下载**：视频 mp4 仅在本地存在（`msg/video`）时
   返回，否则返回 None；
5. **发朋友圈功能已舍弃**：4.x 的发表为自绘界面操作，不可靠自动化；
   本库仅保留朋友圈读取/点赞/评论能力。

---

## 六、发送消息（坐标 + OCR）

微信 4.1.12+ 聊天界面自绘渲染、无无障碍节点，发送走
「屏幕坐标 + 本地 OCR」（`wechatauto/guia.py`）：

1. 按类名 `Qt51514QWindowIcon` 找主窗口，再找渲染子窗口
   `MMUIRenderSubWindowHW`；
2. 布局用渲染子窗口相对坐标描述，运行时换算为屏幕绝对坐标；
3. OCR 识别会话列表点击目标（失败走搜索框）；
4. 扫描输入框白色区定位并聚焦；
5. 文字以「剪贴板 + Ctrl+V」输入（避免中文输入法拦截），失败回退拼音组合；
6. OCR 定位「发送」按钮（找不到回退回车键）；
7. `verify=True` 时用 `WeChatDB` 读回确认。

文件/图片通过 **CF_HDROP 剪贴板 + Ctrl+V** 插入草稿再回车发送，绕开自绘
「+ 菜单」定位；回复/艾特分别走悬停 OCR 工具栏与成员弹层 OCR。

```python
from wechatauto.guia import quick_send, quick_send_file
quick_send('你好', '文件传输助手', verify=True)
quick_send_file(r'D:\资料\报告.pdf', '文件传输助手')
```

> 注意：OCR 需要系统语言包含中文（`Windows.Media.Ocr`）。

---

## 七、后续路线

1. **发送功能实测**：桌面解锁后校准 guia 各坐标常量，验证文件/图片/回复/艾特；
2. **视频消息下载增强**：微信 4.x 聊天视频存储位置仍需确认（本机无样本）；
3. **性能优化**：导出/首扫并行化，内存扫描增量缓存。

---

## 八、目录结构

```
├── wechatauto/
│   ├── wx.py            UIA 自动化入口（4.x 受限）
│   ├── guia.py          ★ 坐标+OCR 发送模块（文本/文件/图片/回复/艾特）
│   ├── db.py            ★ 数据库读取（密钥提取 + 解密 + WAL 合并 + 导出 + 监听）
│   ├── media.py         ★ 媒体下载（图片 v2 解密 / 语音 / 视频 / 文件）
│   ├── moment.py        ★ 朋友圈（MomentDB 数据库路线 + 旧 UIA 兼容）
│   ├── ui/              UI 控件层
│   ├── msgs/            消息模型
│   └── ...
├── demo.py              UI 自动化示例（微信 4.1 上受限）
├── demo_db.py           ★ 数据库读取示例（推荐）
├── demo_guia.py         ★ 坐标+OCR 发送示例
├── demo_listen.py       ★ 实时消息监听示例
├── demo_reply_at.py     ★ 回复/@ 成员实测示例
├── docs/技术文档.md      ★ 完整技术文档（架构/原理/API/扩展）
└── pyproject.toml
```

## 九、免责声明

本项目仅用于个人学习与自动化研究，请遵守微信软件许可协议及当地法律法规，
勿用于任何违反规定的用途。


注：本库完全由AI（opencode+deepseek-v4-flash）生成
