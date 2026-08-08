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
from wechatauto.utils.lock import uilock

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

    @uilock
    def capture(self, save_dir: str = None) -> Optional[str]:
        """截取当前表情包图片，返回保存路径；失败返回 None。

        方案：打开会话 → 滚动到底 → 截取消息区底部全宽画面 → 用连通域
        分析自动裁剪到最后一条消息的气泡内容（排除头像等小元素）。
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
            if not gui.open_chat(who):
                wxlog.warning('表情截图失败：无法打开会话 %s', who)
                return None
            time.sleep(1.2)
            box = gui.get_input_box()
            if not box:
                wxlog.warning('表情截图失败：未检测到输入框')
                return None
            ry0 = box[1]
            self._scroll_to_bottom(gui, ry0)
            time.sleep(0.6)
            box = gui.get_input_box()
            if not box:
                wxlog.warning('表情截图失败：滚动后未检测到输入框')
                return None
            ry0 = box[1]
            rpl = gui.right_pane_left
            render_w = gui.render_w
            bottom = ry0 - 24
            top = max(ry0 - 620, 110)
            # 右边缘留出 16px，避免面板边框/滚动条被误当作消息内容
            screen_box = gui._rel_to_screen((rpl, top, render_w - 16, bottom))
            img = gui._grab_screen(screen_box)
            crop = self._crop_last_bubble(img)
            if crop is None:
                wxlog.warning('表情截图失败：未识别到消息气泡')
                return None
            save_dir = save_dir or os.path.join(
                tempfile.gettempdir(), PROJECT_NAME, 'emoji')
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(
                save_dir, 'emoji_%d.png' % int(time.time() * 1000))
            crop.save(path)
            return path
        except Exception as e:
            wxlog.warning('表情截图异常：%s', e)
            return None

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

    def _crop_last_bubble(self, img) -> Optional[Any]:
        """从消息区截图自动裁剪到最后一条消息的气泡内容。

        聊天背景为近白/浅灰，气泡内为彩色内容、头像为小尺寸彩色圆图。
        算法：建立「非背景内容掩码」→ 全图连通域 → 按 y 方向重叠分组
        （同一消息的头像与气泡同排重叠；不同消息被行距分隔成不同组）→
        取最底部一组，并剔除边缘的类头像小元素。
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
        # 取最底部一组（maxy 最大）
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
