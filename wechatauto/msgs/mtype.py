from .base import (
    BaseMessage,
    HumanMessage,
)
from wechatauto import uia
from wechatauto.param import (
    WxParam,
    WxResponse,
    PROJECT_NAME
)

from typing import (
    Dict,
    List,
    Any,
    Optional,
    TYPE_CHECKING
)
import os
import re
import time
import tempfile
if TYPE_CHECKING:
    from wechatauto.ui.chatbox import ChatBox


class TextMessage(BaseMessage):
    type = 'text'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)


class QuoteMessage(BaseMessage):
    type = 'quote'
    repattern = r"^(.*?) \n引用 (.*?) 的消息 : (.*?)$"

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)
        self.content, self.quote_nickname, self.quote_content = \
            re.findall(self.repattern, self.content, re.DOTALL)[0]


class VoiceMessage(BaseMessage):
    type = 'voice'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)


class ImageMessage(BaseMessage):
    type = 'image'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)

    @property
    def image(self):
        """打开并返回图片预览窗口实例"""
        from wechatauto.ui.component import WeChatImage
        self.roll_into_view()
        self.control.Click()
        return WeChatImage(self)

    def save(self, dir_path=None, timeout=10):
        """保存图片

        Args:
            dir_path (str): 保存文件夹路径
            timeout (int, optional): 保存超时时间，默认10秒

        Returns:
            Path: 文件保存路径
        """
        preview = self.image
        if not preview.control:
            return WxResponse.failure('未找到图片预览窗口')
        return preview.save(dir_path, timeout)


class EmojiMessage(BaseMessage):
    """表情包（动画表情）消息。

    微信 4.x 表情消息在本地数据库中 content 为加密数据，无法直接还原
    表情图片；因此 ``capture()`` 采用「打开会话 → 滚动到底 → 对最后一条
    消息区域截图」的屏幕截图方案，返回图片路径供上层（如 AI 视觉识别）使用。
    """
    type = 'emotion'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)

    def capture(self, save_dir: str = None) -> Optional[str]:
        """截取当前表情包图片，返回保存路径；失败返回 None。

        方案：打开会话 → 滚动到表情消息可见 → 用 uia 元素 BoundingRectangle
        获取其精确屏幕坐标 → 截图该区域 → 裁剪掉空白边缘后保存。相比按
        消息区固定高度截图，不会因表情超出截图区域而被截断。
        """
        from wechatauto.logger import wxlog

        chat = getattr(self.parent, 'root', None)
        if chat is None:
            wxlog.warning('表情截图失败：无法定位会话')
            return None
        gui = getattr(chat, '_gui', None)
        if gui is None:
            wxlog.warning('表情截图失败：无法定位 GUI')
            return None
        who = (getattr(self.parent, 'who', None)
               or getattr(chat, 'who', None)
               or getattr(chat, 'nickname', None))
        if not who:
            wxlog.warning('表情截图失败：会话名称为空')
            return None
        try:
            # 会话已打开（主窗面板或独立聊天窗口）时跳过 open_chat：
            # 重复 open_chat 会刷新消息列表/切换窗口，使消息控件失效。
            # 注意 _find_chat_window 未找到时返回 0 而非 None，需转 bool。
            opened = (gui._chat_is_open(who)
                      or bool(gui._find_chat_window(who)))
            if not opened:
                if not gui.open_chat(who):
                    wxlog.warning('表情截图失败：无法打开会话 %s', who)
                    return None
            time.sleep(0.8)
            save_dir = save_dir or os.path.join(
                tempfile.gettempdir(), PROJECT_NAME, 'emoji')
            # 滚动到底，让底部表情消息在消息列表中实例化（uia 可见）
            box = gui.get_input_box()
            if box:
                self._scroll_to_bottom(gui, box[1])
                time.sleep(0.6)
            # 微信 4.x 主窗口为 Qt，不暴露 uia 子树，无法用控件坐标定位；
            # 直接走消息区截图 + 底部消息裁剪。
            img = self._pane_capture_img(gui)
            if img is None:
                wxlog.warning('表情截图失败：无法获取截图画面')
                return None
            # 诊断：保存原始消息区截图，便于跨电脑排查
            try:
                img.save(os.path.join(
                    os.path.expanduser('~'), 'pane_diag_raw.png'))
            except Exception:
                pass
            attr = getattr(self, 'attr', 'friend')
            # 方向感知：对方消息优先用左侧头像锚定消息顶部；自己消息用
            # 消息分隔空白定位。任一失败回退到另一种方式。
            if attr == 'self':
                crop = self._crop_bottom_message(img)
                used = 'blank'
                if crop is None:
                    crop = self._crop_by_avatar(img)
                    used = 'avatar'
            else:
                crop = self._crop_by_avatar(img)
                used = 'avatar'
                if crop is None:
                    crop = self._crop_bottom_message(img)
                    used = 'blank'
            print(f'[CAP] attr={attr} img={img.size} '
                  f'used={used} crop={crop.size if crop else None}')
            if crop is None:
                wxlog.warning('表情截图失败：消息区域内容为空')
                return None
            crop = self._content_bbox_crop(crop)
            if crop is None:
                wxlog.warning('表情截图失败：内容边界裁剪失败')
                return None
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(
                save_dir, 'emoji_%d.png' % int(time.time() * 1000))
            crop.save(path)
            return path
        except Exception as e:
            wxlog.warning('表情截图异常：%s', e)
            return None

    @staticmethod
    def _content_bbox_crop(img) -> Optional[Any]:
        """按内容边界裁剪，去掉空白边缘与相邻头像等无关元素。"""
        try:
            w, h = img.size
            px = img.load()
            minx, miny, maxx, maxy = w, h, -1, -1
            for y in range(0, h, 2):
                for x in range(0, w, 2):
                    p = px[x, y]
                    if len(p) >= 3:
                        r, g, b = p[0], p[1], p[2]
                    else:
                        r = g = b = p
                    mxv = max(r, g, b)
                    mnv = min(r, g, b)
                    if not (mxv > 235 and (mxv - mnv) < 22):
                        if x < minx:
                            minx = x
                        if y < miny:
                            miny = y
                        if x > maxx:
                            maxx = x
                        if y > maxy:
                            maxy = y
            if maxx < 0:
                return None
            pad = 4
            x0 = max(0, minx - pad)
            y0 = max(0, miny - pad)
            x1 = min(w, maxx + pad + 1)
            y1 = min(h, maxy + pad + 1)
            if x1 - x0 < 8 or y1 - y0 < 8:
                return None
            return img.crop((x0, y0, x1, y1))
        except Exception:
            return None

    def _last_msg_rect(self, gui) -> Optional[tuple]:
        """从主窗口 uia 树定位消息区最后一条消息的屏幕矩形。

        DB 模式消息的 control 是伪控件（BoundingRectangle 恒为 0），
        无法用于定位。这里实时从微信主窗口构建 uia 树，找到消息列表
        最后一项（即最新一条消息）读取真实坐标。
        """
        try:
            main = uia.ControlFromHandle(gui.main_hwnd)
            if main is None:
                print('[DIAG uia] 主窗口控件为空')
                return None
            chatbox = main.GroupControl(ClassName="mmui::ChatMessagePage") \
                          .CustomControl(ClassName="mmui::XSplitterView")
            msgbox = chatbox.GroupControl(ClassName="mmui::MessageView") \
                            .ListControl()
            items = msgbox.GetChildren()
            print(f'[DIAG uia] 消息项数量={len(items)}')
            if not items:
                return None
            last = items[-1]
            rect = last.BoundingRectangle
            w, h = rect.width(), rect.height()
            print(f'[DIAG uia] last rect=({rect.left},{rect.top},{rect.right},{rect.bottom}) '
                  f'w={w} h={h} name={last.Name!r}')
            if w <= 8 or h <= 8:
                return None
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception as e:
            print(f'[DIAG uia] 异常 {type(e).__name__}: {e}')
            return None

    def _uia_capture_img(self, gui) -> Optional[Any]:
        """用 uia 元素坐标定位表情消息并截图（精确到单条消息）。

        从主窗口实时定位最后一条消息（滚动到底后即最新表情）；
        定位失败返回 None，由调用方回退到消息区截图。
        """
        try:
            rect = self._last_msg_rect(gui)
            if rect is None:
                return None
            pad = 4
            return gui._grab_screen((
                rect[0] - pad, rect[1] - pad,
                rect[2] + pad, rect[3] + pad))
        except Exception:
            return None

    def _pane_capture_img(self, gui) -> Optional[Any]:
        """截取消息区全宽画面（渲染顶部到输入框），供底部消息裁剪。"""
        try:
            box = gui.get_input_box()
            if not box:
                return None
            ry0 = box[1]
            rpl = gui.right_pane_left
            render_w = gui.render_w
            # 从渲染顶部开始，覆盖整个消息区，避免表情顶部超出固定高度被裁
            top = 110
            bottom = ry0 - 24
            if bottom <= top:
                return None
            screen_box = gui._rel_to_screen((rpl, top, render_w - 16, bottom))
            return gui._grab_screen(screen_box)
        except Exception:
            return None

    @staticmethod
    def _crop_bottom_message(img) -> Optional[Any]:
        """取最底部一条消息的完整内容（从底部内容行向上到消息分隔空白）。

        底部消息的顶部边界用「连续空白行超过阈值」判定。阈值自适应取
        消息区高度的 2.5%（采样行），跨分辨率/DPI 保持一致：大于表情包
        图片内部的小留白、小于消息列表相邻消息的分隔留白。
        """
        try:
            w, h = img.size
            rows = []
            for y in range(0, h, 2):
                cnt = 0
                for x in range(0, w, 3):
                    p = img.getpixel((x, y))
                    if len(p) >= 3:
                        r, g, b = p[0], p[1], p[2]
                    else:
                        r = g = b = p
                    mxv = max(r, g, b)
                    mnv = min(r, g, b)
                    if not (mxv > 235 and (mxv - mnv) < 22):
                        cnt += 1
                rows.append(cnt)
            content = [i for i, c in enumerate(rows) if c > 3]
            if not content:
                return None
            bottom = max(content)
            gap = max(8, int(h * 0.025) // 2)  # 采样行，每行=2px
            blank = 0
            top_idx = 0
            for i in range(bottom, -1, -1):
                if rows[i] <= 3:
                    blank += 1
                    if blank > gap:
                        top_idx = i + gap
                        break
                else:
                    blank = 0
            pad = 4
            y0 = max(0, top_idx * 2 - pad)
            y1 = min(h, bottom * 2 + pad + 1)
            if y1 - y0 < 8:
                return None
            return img.crop((0, y0, w, y1))
        except Exception:
            return None

    @staticmethod
    def _avatar_top(img) -> Optional[int]:
        """在消息区左侧找最底部头像的顶部 y（相对截图坐标）。

        头像位于消息区左侧一条窄列内，是圆形彩色块；其顶部与消息气泡
        顶部对齐。头像直径与屏幕缩放成正比，跨分辨率特征稳定。
        """
        try:
            w, h = img.size
            px = img.load()
            x0 = max(0, int(w * 0.02))
            x1 = max(x0 + 20, int(w * 0.10))
            x1 = min(w, x1)
            cols = []
            for y in range(0, h, 2):
                cnt = 0
                for x in range(x0, x1):
                    r, g, b = px[x, y][:3]
                    mxv = max(r, g, b)
                    mnv = min(r, g, b)
                    if not (mxv > 235 and (mxv - mnv) < 22):
                        cnt += 1
                cols.append(cnt)
            bottom = -1
            for y in range(len(cols) - 1, -1, -1):
                if cols[y] > 2:
                    bottom = y
                    break
            if bottom < 0:
                return None
            top = bottom
            while top > 0 and cols[top - 1] > 2:
                top -= 1
            height = (bottom - top + 1) * 2
            if not (8 <= height <= 220):
                return None
            return top * 2
        except Exception:
            return None

    def _crop_by_avatar(self, img) -> Optional[Any]:
        """对方消息：以左侧头像顶部为消息顶部，裁到消息区底部内容。"""
        try:
            w, h = img.size
            top = self._avatar_top(img)
            if top is None or top <= 0:
                return None
            px = img.load()
            bottom = -1
            for y in range(h - 1, -1, -1):
                cnt = 0
                for x in range(0, w, 3):
                    p = px[x, y]
                    if len(p) >= 3:
                        r, g, b = p[0], p[1], p[2]
                    else:
                        r = g = b = p
                    mxv = max(r, g, b)
                    mnv = min(r, g, b)
                    if not (mxv > 235 and (mxv - mnv) < 22):
                        cnt += 1
                if cnt > 3:
                    bottom = y
                    break
            if bottom < 0:
                return None
            pad = 4
            y0 = max(0, top - pad)
            y1 = min(h, bottom + pad + 1)
            if y1 - y0 < 8:
                return None
            return img.crop((0, y0, w, y1))
        except Exception:
            return None

    @staticmethod
    def _crop_remove_avatar(img) -> Any:
        """裁掉左侧头像区域，只保留消息内容（气泡）。

        从左侧扫描，找到头像与气泡之间的空白列，裁掉该列左侧的头像。
        """
        try:
            w, h = img.size
            if w < 50:
                return img
            threshold = max(3, int(h * 0.15))
            cut_x = 0
            for x in range(min(w, int(w * 0.4))):
                blank = 0
                for y in range(0, h, 3):
                    p = img.getpixel((x, y))
                    if len(p) >= 3:
                        r, g, b = p[0], p[1], p[2]
                    else:
                        r = g = b = p
                    mxv = max(r, g, b)
                    mnv = min(r, g, b)
                    if not (mxv > 235 and (mxv - mnv) < 22):
                        blank += 1
                if blank <= threshold:
                    cut_x = x
                    break
            if cut_x > 0:
                img = img.crop((cut_x, 0, w, h))
            return img
        except Exception:
            return img

    def _scroll_to_bottom(self, gui, ry0: int) -> None:
        """将鼠标悬停在消息区中部并向下滚动，确保最后一条消息可见。"""
        try:
            import win32api
            mx = gui.origin_x + (gui.right_pane_left + gui.render_w) // 2
            my = gui.origin_y + (115 + ry0) // 2
            win32api.SetCursorPos((mx, my))
            for _ in range(3):
                gui._input.wheel(-300)
        except Exception:
            pass

    @staticmethod
    def _bottom_has_right_content(img, ratio=0.82) -> bool:
        """底部区域右侧是否有内容（自己发的消息）。

        自己消息的气泡贴右边缘，内容会出现在截图右侧约 18% 内；对方
        消息内容即使很宽也极少延伸到该区域。用于判断是否需要方向裁剪
        来避开自己刚发的消息。
        """
        try:
            w, h = img.size
            x0 = int(w * ratio)
            cnt = 0
            for y in range(int(h * 0.4), h, 3):
                for x in range(x0, w, 3):
                    p = img.getpixel((x, y))
                    if len(p) >= 3:
                        r, g, b = p[0], p[1], p[2]
                    else:
                        r = g = b = p
                    mxv = max(r, g, b)
                    mnv = min(r, g, b)
                    if not (mxv > 235 and (mxv - mnv) < 22):
                        cnt += 1
            return cnt > 15
        except Exception:
            return False

    def _crop_last_bubble(self, img, want_left=None) -> Optional[Any]:
        """从消息区截图自动裁剪到最后一条消息的气泡内容。

        聊天背景为近白/浅灰，气泡内为彩色内容、头像为小尺寸彩色圆图。
        算法：建立「非背景内容掩码」→ 全图连通域 → 按 y 方向重叠分组
        （同一消息的头像与气泡同排重叠；不同消息被行距分隔成不同组）→
        取最底部一组，并剔除边缘的类头像小元素。

        want_left: True 取最底部一条左侧（对方）消息；False 取最底部
        一条右侧（自己）消息；None 取整个最底部一条（原行为）。
        """
        try:
            from PIL import Image as PILImage
        except Exception:
            return None

        w, h = img.size
        scale = max(1, int((w * h) ** 0.5 // 350))
        sw, sh = max(1, w // scale), max(1, h // scale)
        small = img.convert('RGB').resize((sw, sh), PILImage.LANCZOS)
        px = small.load()

        # 1. 内容掩码：非「近白/浅灰」背景像素
        mask = bytearray(sw * sh)
        for y in range(sh):
            base = y * sw
            for x in range(sw):
                r, g, b = px[x, y]
                mxv = max(r, g, b)
                mnv = min(r, g, b)
                if mxv > 235 and (mxv - mnv) < 22:
                    continue
                mask[base + x] = 1

        # 2. 全图连通域（扫描线 BFS）
        from collections import deque
        labels = [-1] * (sw * sh)
        comps = []
        for y in range(sh):
            for x in range(sw):
                i = y * sw + x
                if not mask[i] or labels[i] != -1:
                    continue
                labels[i] = len(comps)
                area = 0
                minx = maxx = x
                miny = maxy = y
                dq = deque([(x, y)])
                while dq:
                    cx, cy = dq.popleft()
                    area += 1
                    if cx < minx: minx = cx
                    if cx > maxx: maxx = cx
                    if cy < miny: miny = cy
                    if cy > maxy: maxy = cy
                    if cx + 1 < sw and mask[cy * sw + cx + 1] and labels[cy * sw + cx + 1] == -1:
                        labels[cy * sw + cx + 1] = len(comps); dq.append((cx + 1, cy))
                    if cx - 1 >= 0 and mask[cy * sw + cx - 1] and labels[cy * sw + cx - 1] == -1:
                        labels[cy * sw + cx - 1] = len(comps); dq.append((cx - 1, cy))
                    if cy + 1 < sh and mask[(cy + 1) * sw + cx] and labels[(cy + 1) * sw + cx] == -1:
                        labels[(cy + 1) * sw + cx] = len(comps); dq.append((cx, cy + 1))
                    if cy - 1 >= 0 and mask[(cy - 1) * sw + cx] and labels[(cy - 1) * sw + cx] == -1:
                        labels[(cy - 1) * sw + cx] = len(comps); dq.append((cx, cy - 1))
                comps.append((area, minx, miny, maxx, maxy))
        # 过滤细长竖条（滚动条/面板边框，非消息内容）
        thin_h = max(8, int(60 / scale))
        thin_w = max(3, int(12 / scale))
        comps = [c for c in comps
                 if not (c[4] - c[2] + 1 >= thin_h and c[3] - c[1] + 1 <= thin_w)]
        if not comps:
            return None

        # 3. 按 y 重叠分组：同一消息的头像/气泡同排重叠，不同消息被行距分开
        comps.sort(key=lambda c: c[2])  # 按 miny 升序
        groups = []
        for c in comps:
            placed = False
            for g in groups:
                if c[2] <= g[1]:  # 该组件顶部不高于当前组底部 => 同组
                    g[0].append(c)
                    if c[4] > g[1]:
                        g[1] = c[4]
                    placed = True
                    break
            if not placed:
                groups.append([[c], c[4]])
        if not groups:
            return None
        # 选择目标消息组：从底部向上找第一组目标方向的（气泡在左=对方、
        # 在右=自己）；方向不明时取最底部一组
        if want_left is None:
            bottom = max(groups, key=lambda g: g[1])
        else:
            mid = sw / 2.0
            bottom = None
            for g in sorted(groups, key=lambda g: g[1], reverse=True):
                comps_list = g[0]
                xs = [c[1] for c in comps_list]
                xe = [c[3] for c in comps_list]
                center = (min(xs) + max(xe)) / 2.0
                if (want_left and center < mid) or (not want_left and center >= mid):
                    bottom = g
                    break
            if bottom is None:
                bottom = max(groups, key=lambda g: g[1])

        # 4. 底部组内：核心 = 最大连通域；只取与其 y 重叠的组件求并集
        gcomps = bottom[0]
        big = max(gcomps, key=lambda c: c[0])
        _, bminx, bminy, bmaxx, bmaxy = big
        big_area = big[0]
        keep = [c for c in gcomps if c[2] <= bmaxy and c[4] >= bminy] or gcomps
        allminx = min(c[1] for c in keep)
        allminy = min(c[2] for c in keep)
        allmaxx = max(c[3] for c in keep)
        allmaxy = max(c[4] for c in keep)
        bbox = [allminx, allminy, allmaxx, allmaxy]

        # 5. 剔除左/右边缘的头像类小元素（面积 < 核心 40% 且较窄）
        max_av = int(90 / scale)  # 头像直径约 90 逻辑像素
        left_comp = min(keep, key=lambda c: c[1])
        right_comp = max(keep, key=lambda c: c[3])
        for is_left, comp in ((True, left_comp), (False, right_comp)):
            if is_left and comp[1] != allminx:
                continue
            if not is_left and comp[3] != allmaxx:
                continue
            ea, eminx, eminy, emaxx, emaxy = comp
            if ea < big_area * 0.4 and (emaxx - eminx + 1) <= max_av:
                if is_left:
                    bbox[0] = max(bminx, emaxx + 1)
                else:
                    bbox[2] = min(bmaxx, eminx - 1)

        # 6. 换算回原图并加边距
        pad = max(2, scale)
        x0 = max(0, bbox[0] * scale - pad)
        y0 = max(0, bbox[1] * scale - pad)
        x1 = min(w, (bbox[2] + 1) * scale + pad)
        y1 = min(h, (bbox[3] + 1) * scale + pad)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return img.crop((x0, y0, x1, y1))


class VideoMessage(BaseMessage):
    type = 'video'
    repattern = r'视频(\d+):(\d+)'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)

    @property
    def video(self):
        """打开并返回视频预览窗口实例"""
        from wechatauto.ui.component import WeChatImage
        self.roll_into_view()
        self.control.Click()
        return WeChatImage(self)

    def save(self, dir_path=None, timeout=10):
        """保存视频

        Args:
            dir_path (str): 保存文件夹路径
            timeout (int, optional): 保存超时时间，默认10秒

        Returns:
            Path: 文件保存路径
        """
        preview = self.video
        if not preview.control:
            return WxResponse.failure('未找到视频预览窗口')
        return preview.save(dir_path, timeout)


class FileMessage(BaseMessage):
    type = 'file'
    repattern = r"^文件\n([^\n]+)\n(\d+(\.\d+)?)(B|KB|MB|GB|TB)\n微信电脑版$"

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)
        self._parse()

    def _parse(self):
        match = re.search(self.repattern, self.content)
        if match:
            self.filename = match.group(1)
            self.filesize = float(match.group(2))
            self.sizeunit = match.group(4)
        else:
            self.filename = None
            self.filesize = None
            self.sizeunit = None


class LinkMessage(BaseMessage):
    type = 'link'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)


class LocationMessage(BaseMessage):
    type = 'location'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)


class PersonalCardMessage(BaseMessage):
    type = 'personal_card'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)


class OtherMessage(BaseMessage):
    type = 'other'

    def __init__(
            self,
            control: uia.Control,
            parent: "ChatBox",
            additonal_attr: Dict[str, Any] = {}
        ):
        super().__init__(control, parent, additonal_attr)
