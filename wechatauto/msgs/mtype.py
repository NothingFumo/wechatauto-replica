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
    TYPE_CHECKING
)
import re
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
