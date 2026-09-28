"""maimaiDX 查分 MaiBot 插件。

数据来源：
- 水鱼查分器 https://www.diving-fish.com/api/maimaidxprober（曲目/定数/拟合定数/成绩）
- 柚子社别名库 https://www.yuzuchan.moe/api/maimaidx（曲目别名）
"""

from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
import zlib
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

try:
    from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool
    from maibot_sdk.types import CONFIG_RELOAD_SCOPE_SELF, ToolParamType, ToolParameterInfo
except ImportError:  # 允许无 SDK 环境做核心模块测试
    Command = Tool = MaiBotPlugin = PluginConfigBase = None
    Field = None
    CONFIG_RELOAD_SCOPE_SELF = 'self'
    ToolParamType = ToolParameterInfo = None

try:
    from .maimaidx_core import (
        AliasItem,
        MaiMusic,
        MaimaiAPI,
        MaimaiError,
        Music,
        MusicList,
        OAuthBindingMismatchError,
        OAuthConfirmationCodeError,
        OAuthError,
        OAuthNotBoundError,
        PlayChart,
        PlayRecord,
        TooManyRequestsError,
        format_b50,
        format_player_record,
        format_search_list,
        format_song_brief,
        format_song_info,
        paginate,
    )
    from .maimaidx_core import extra as mai_extra
    from .maimaidx_core import guess as mai_guess
    from .maimaidx_core import render as mai_render
except ImportError:  # Runner 以单文件方式加载 plugin.py 时走这里
    import sys
    from pathlib import Path as _Path

    _HERE = _Path(__file__).resolve().parent
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    from maimaidx_core import (
        AliasItem,
        MaiMusic,
        MaimaiAPI,
        MaimaiError,
        Music,
        MusicList,
        OAuthBindingMismatchError,
        OAuthConfirmationCodeError,
        OAuthError,
        OAuthNotBoundError,
        PlayChart,
        PlayRecord,
        TooManyRequestsError,
        format_b50,
        format_player_record,
        format_search_list,
        format_song_brief,
        format_song_info,
        paginate,
    )
    from maimaidx_core import extra as mai_extra
    from maimaidx_core import guess as mai_guess
    from maimaidx_core import render as mai_render


SUPPORTED_CONFIG_VERSION = '1.2.0'

_HELP_TEXT = '''【maimaiDX 查分帮助】
♪ 查歌
· 查歌 关键词 [页码] —— 按曲名/别名查歌
· xxx是什么歌 —— 通过别名反查乐曲
· id 曲目ID —— 曲目详情：定数/拟合定数/版本/难度/曲师/谱师
· 随个 [dx/sd] [绿黄红紫白] 等级 —— 随机曲目，如：随个 紫14+
· 随机 变量 值 —— 按条件随机：
　变量：定数/拟合定数/版本/难度/分区/曲师/谱师/定数差距
　示例：随机 定数 14.0-14.2 ｜ 随机 版本 祭
　随机 分区 东方 ｜ 随机 曲师 Yooh ｜ 随机 定数差距 0.5（差值=0.5）
· 今日mai —— 今日运势与推荐歌曲
· mai什么 —— 随机来一首；mai什么推分 按B50推荐
♪ 筛选查歌
· 定数查歌 定数 [上限] [页码] —— 按歌曲定数筛选
· 拟合查歌 定数 [上限] [页码] —— 按拟合定数筛选
· 曲师查歌 / 谱师查歌 / bpm查歌 名称 [页码]
· 14定数表 —— 查看该等级定数列表（源插件同款图）
· 14完成表 / 14ap完成表 —— 等级完成表（源插件同款图）
♪ 查分
· b50 [用户名/QQ号] —— B50 成绩单（不填查自己）
· minfo 曲目ID或别名 —— 查自己的单曲成绩
· 查成绩 用户名/QQ号 曲目 —— 查他人单曲成绩（需开发者 token）
· 查看排名 [用户名] [页码] / 我的排名 —— Rating 排行
· 我要上10分 —— 基于 B50 的推分建议
· 分数线 紫799 100 —— 分数线容错计算（分数线 帮助）
♪ 猜歌游戏
· 开始猜歌 —— 文字提示猜歌（游玩过万的热门曲）
· 猜曲绘 —— 裁剪曲绘猜歌
· 猜黑白曲绘 —— 曲绘黑白化后猜歌
· 答案 歌名 —— 猜歌作答（也可「答案是歌名」「答案：歌名」）
· 结束猜歌 —— 放弃并公布答案（5 分钟超时自动公布）
♪ 进度查询
· 爽将进度 / 真極进度 —— 版本牌子进度
· 14 sss 进度 —— 等级进度（等级需 10+，评价需 s 起）
· 爽将完成表 / 真極完成表 —— 牌子完成表（源插件同款图）
♪ 水鱼账号
· 绑定水鱼 → 水鱼确认码 XXXX → 绑定完成
· 解绑水鱼 —— 清除本地代查令牌
♪ 别名与其他
· 添加别名 曲目ID或歌名 别名 —— 申请别名投票
· 同意别名 Tag —— 给进行中的别名投票
· 添加曲师别名/谱师别名 原名 新别名 —— 用原名或已有别名添加新别名
· 曲师别名 / 谱师别名 —— 查看别名列表
· maimai更新数据 —— 刷新曲库/别名/牌子数据
· maihelp —— 显示本帮助
※ 数据来源：水鱼查分器（maimai.diving-fish.com）'''

# 帮助菜单分组数据（供主题风帮助图使用）
HELP_SECTIONS = [
    ('查歌 / 随机', (98, 126, 244), [
        ('查歌 关键词 [页码]', '按曲名/别名查歌'),
        ('xxx是什么歌', '通过别名反查乐曲'),
        ('id 曲目ID', '谱面详情：定数/拟合定数/notes/曲师/谱师'),
        ('随机 变量 值', '定数/拟合定数/版本/难度/分区/曲师/谱师/定数差距'),
        ('随个 [dx/sd] [颜色] 等级', '随机曲目，如：随个紫14+'),
        ('今日mai', '今日运势与推荐歌曲'),
        ('mai什么', '随机来一首（mai什么推分）'),
    ]),
    ('筛选查歌', (255, 140, 105), [
        ('定数查歌 / 拟合查歌 定数 [上限]', '按定数筛选，[页码] 可选'),
        ('曲师查歌 / 谱师查歌 / bpm查歌', '名称 [页码]'),
        ('14定数表', '该等级定数列表'),
        ('14完成表 / 14ap完成表', '等级完成表'),
    ]),
    ('查分', (72, 96, 226), [
        ('b50 [用户名/QQ号]', 'B50 成绩单（不填查自己）'),
        ('minfo 曲目', '查自己的单曲成绩'),
        ('查成绩 用户名/QQ号 曲目', '查他人单曲成绩'),
        ('查看排名 [页码] / 我的排名', 'Rating 排行'),
        ('我要上10分', '基于 B50 的推分建议'),
        ('分数线 紫799 100', '分数线容错（分数线 帮助）'),
    ]),
    ('进度查询', (186, 109, 230), [
        ('爽将进度 / 真極进度', '版本牌子进度'),
        ('爽将完成表 / 真極完成表', '牌子完成表'),
        ('14 sss 进度', '等级进度（10+ 起，s 起）'),
    ]),
    ('猜歌游戏', (255, 108, 152), [
        ('开始猜歌', '文字提示猜歌（热门曲）'),
        ('猜曲绘', '裁剪曲绘猜歌'),
        ('猜黑白曲绘', '曲绘黑白化后猜歌'),
        ('答案 歌名', '也支持 答案是歌名 / 答案：歌名'),
        ('结束猜歌', '放弃并公布答案（5 分钟超时）'),
    ]),
    ('水鱼账号', (34, 197, 0), [
        ('绑定水鱼', '发起绑定，获取授权链接'),
        ('水鱼确认码 XXXX', '回填确认码完成绑定'),
        ('解绑水鱼', '清除本地代查令牌'),
    ]),
    ('别名与其他', (150, 150, 150), [
        ('添加别名 曲目 别名', '申请别名投票'),
        ('同意别名 Tag', '给进行中的别名投票'),
        ('添加曲师别名/谱师别名 原名 新别名', '用原名或已有别名添加新别名'),
        ('曲师别名 / 谱师别名', '查看别名列表'),
        ('maimai更新数据', '刷新曲库/别名/牌子数据'),
        ('maihelp', '显示本帮助'),
    ]),
]

DIFF_NAMES = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master', 'UTAGE']
DIFF_INDEX = {name.lower(): i for i, name in enumerate(DIFF_NAMES)}

RANDOM_VAR_MAP: Dict[str, str] = {
    '定数': 'ds', '歌曲定数': 'ds', 'ds': 'ds',
    '拟合定数': 'fit', '拟合': 'fit', 'fit': 'fit', 'fitdiff': 'fit',
    '版本': 'version', 'ver': 'version', 'version': 'version',
    '难度': 'difficulty', 'diff': 'difficulty', 'difficulty': 'difficulty',
    '分区': 'genre', '分类': 'genre', '类别': 'genre', 'genre': 'genre',
    '曲师': 'artist', '艺术家': 'artist', 'artist': 'artist',
    '谱师': 'charter', 'charter': 'charter',
    '定数差距': 'gap', '差距': 'gap', 'gap': 'gap',
}

if PluginConfigBase is not None:

    class PluginSectionConfig(PluginConfigBase):
        __ui_label__ = '插件'
        __ui_icon__ = 'package'
        __ui_order__ = 0

        enabled: bool = Field(default=True, description='是否启用插件')
        config_version: str = Field(
            default=SUPPORTED_CONFIG_VERSION,
            description='配置版本（与插件版本同步）',
            json_schema_extra={'hidden': True, 'disabled': True},
        )

    class ApiSectionConfig(PluginConfigBase):
        __ui_label__ = '查分器接口'
        __ui_icon__ = 'cloud'
        __ui_order__ = 1

        maimaidx_token: str = Field(
            default='oyfk03QObSiAhRtp45XYHBWEJG7Fv9I8',
            description='水鱼查分器开发者 token（用于开发者成绩接口）',
        )
        request_timeout: int = Field(default=30, ge=5, le=120, description='接口请求超时（秒）')
        use_prober_proxy: bool = Field(default=False, description='查分器接口走 yuzuchan 反代')
        use_alias_proxy: bool = Field(default=False, description='别名接口走 yuzuchan 反代')
        cover_base_url: str = Field(
            default='https://www.yuzuchan.moe/assets/maimaidx/cover',
            description='在线曲绘基础地址（留空关闭在线曲绘；也可把曲绘图片放入数据目录 covers/ 文件夹）',
        )
        divingfish_client_id: str = Field(
            default='35f1d7cf74e58e2d7680f76f9028d399',
            description='水鱼 OAuth client_id（与 client_secret 同时填写后启用新版授权）',
        )
        divingfish_client_secret: str = Field(
            default='bl0OzOzpIze1DA-Ej6BkrnPS24jSH55MqPuA25V1tck',
            description='水鱼 OAuth client_secret',
        )
        divingfish_auth_url: str = Field(
            default='https://auth.diving-fish.com',
            description='水鱼账号服务地址',
        )
        divingfish_scope: str = Field(
            default='prober.records.read',
            description='OAuth 授权范围，空格分隔：profile / prober.profile.read / prober.records.read / prober.records.write',
        )
        artist_alias_url: str = Field(
            default='',
            description='曲师别名库 JSON 地址（格式 {"别名": "全名"} 或 {"别名": ["全名1","全名2"]}），留空仅用本地别名',
        )
        charter_alias_url: str = Field(
            default='',
            description='谱师别名库 JSON 地址，格式同上',
        )

    class DisplaySectionConfig(PluginConfigBase):
        __ui_label__ = '输出'
        __ui_icon__ = 'visibility'
        __ui_order__ = 2

        songs_per_page: int = Field(default=25, ge=5, le=50, description='查歌列表每页条数')
        send_cover_image: bool = Field(default=True, description='查询曲目详情时尝试附带曲绘图片')
        long_output_forward: bool = Field(default=True, description='长输出（B50 等）使用合并转发发送')
        use_image_output: bool = Field(
            default=True,
            description='用图片输出查询结果（Pillow 绘制，失败自动回退纯文本）',
        )
        font_path: str = Field(
            default='',
            description='自定义中文字体路径（.ttf/.ttc/.otf），留空自动探测系统字体',
        )
        assets_dir: str = Field(
            default='',
            description='官方素材包 static 目录（Resource CN 1.55+），启用源插件同款渲染；留空用简化渲染',
        )
        render_theme: str = Field(
            default='prism_plus',
            description='渲染主题：prism_plus / circle',
        )
        bot_name: str = Field(
            default='苏涂二舟(xiaocutedog)',
            description='渲染图片 Generated by 署名（美术作者署名 Designed by 按素材条款保留）',
        )

    class ResourceSectionConfig(PluginConfigBase):
        __ui_label__ = '资源'
        __ui_icon__ = 'download'
        __ui_order__ = 4

        auto_download: bool = Field(
            default=True,
            description='未找到官方素材包时自动下载（约 445MB，需 2GB 磁盘空间；下载在后台进行）',
        )
        assets_dir: str = Field(
            default='',
            description='已下载素材的 static 目录路径；留空则自动管理（首次运行自动下载到数据目录）',
        )
        download_url: str = Field(
            default='',
            description='自定义素材包下载地址（.7z），留空使用内置官方源',
        )

    class AccessSectionConfig(PluginConfigBase):
        __ui_label__ = '访问控制'
        __ui_icon__ = 'shield'
        __ui_order__ = 3

        access_mode: Literal['off', 'black', 'white'] = Field(
            default='off',
            description='访问控制：off=不限制，black=黑名单（名单内禁用），white=白名单（仅名单内可用）',
        )
        blacklist: str = Field(
            default='',
            description='黑名单（黑名单模式生效）。条目：user:QQ=用户，纯数字或 group:群号=群聊，空格/逗号分隔',
        )
        whitelist: str = Field(
            default='',
            description='白名单（白名单模式生效）。条目格式同黑名单；为空表示暂不限制',
        )
        notify: bool = Field(
            default=True,
            description='拒绝时是否提示（关闭则静默拦截）',
        )

    class MaimaidxConfig(PluginConfigBase):
        plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
        api: ApiSectionConfig = Field(default_factory=ApiSectionConfig)
        display: DisplaySectionConfig = Field(default_factory=DisplaySectionConfig)
        resources: ResourceSectionConfig = Field(default_factory=ResourceSectionConfig)
        access: AccessSectionConfig = Field(default_factory=AccessSectionConfig)

else:  # 无 SDK 时的占位，保证模块可导入
    MaimaidxConfig = None


class MaimaidxPlugin(MaiBotPlugin):
    """maimaiDX 查分插件。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = MaimaidxConfig

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except TypeError:
            super().__init__()
        self.api: Optional[MaimaiAPI] = None
        self.mai: Optional[MaiMusic] = None
        self._ready: Optional[asyncio.Event] = None
        self._load_task: Optional[asyncio.Task] = None
        self._last_refresh: float = 0.0
        self._ws_uuid: str = str(uuid.uuid1())
        self.guess_games: Dict[str, Dict[str, Any]] = {}
        self.srender = None
        self._assets_task: Optional[asyncio.Task] = None

    # ---------- 源渲染器与素材 ----------

    def _init_source_renderer(self) -> None:
        from pathlib import Path as _P

        try:
            from maimaidx_core.source_render import SourceRenderer
        except ImportError:
            from .maimaidx_core.source_render import SourceRenderer
        candidates = []
        for cfg_key in ('display.assets_dir', 'resources.assets_dir'):
            section, _, field = cfg_key.partition('.')
            raw = getattr(getattr(self.config, section, None), field, '') or ''
            if raw.strip():
                candidates.append(_P(raw.strip()))
        try:
            candidates.append(_P(__file__).resolve().parent / 'assets' / 'static')
            candidates.append(_P(__file__).resolve().parent / 'assets')
        except NameError:
            pass
        candidates.append(self.ctx.paths.data_dir / 'assets' / 'static')
        candidates.append(self.ctx.paths.data_dir / 'assets')
        for c in candidates:
            try:
                self.srender = SourceRenderer(c, theme=self.config.display.render_theme)
                self.ctx.logger.info('maimaidx 源渲染已启用（素材：%s，主题：%s）', c, self.config.display.render_theme)
                return
            except Exception:  # noqa: BLE001 - 换下一个候选目录
                continue
        self.srender = None

    async def _ensure_assets(self) -> None:
        """后台下载官方素材包并启用源渲染（不阻塞聊天命令）。"""
        from pathlib import Path as _P

        try:
            import shutil as _shutil

            from maimaidx_core.asset_fetch import (
                ARCHIVE_NAME,
                DEFAULT_ASSET_URLS,
                download_archive,
                enough_space,
                extract_archive,
            )
        except ImportError:
            from .maimaidx_core.asset_fetch import (
                ARCHIVE_NAME,
                DEFAULT_ASSET_URLS,
                download_archive,
                enough_space,
                extract_archive,
            )
        log = self.ctx.logger
        data_dir = _P(self.ctx.paths.data_dir)
        archive = data_dir / ARCHIVE_NAME
        work = data_dir / 'assets_extract'
        target = data_dir / 'assets' / 'static'

        urls: List[str] = []
        custom = (self.config.resources.download_url or '').strip()
        if custom:
            urls.append(custom)
        urls.extend(DEFAULT_ASSET_URLS)

        try:
            if not enough_space(data_dir):
                log.error('maimaidx 素材自动下载跳过：磁盘剩余空间不足 2GB，'
                          '请手动下载素材包并在 resources.assets_dir 配置路径')
                return
            if archive.exists():
                log.info('maimaidx 检测到已下载的素材包，跳过下载直接解压')
            else:
                total_mb = 445
                log.info('maimaidx 开始下载官方素材包（约 %dMB，期间查询功能正常使用简化渲染）...', total_mb)

                async def progress(done: int, total: int) -> None:
                    log.info('maimaidx 素材下载进度: %.0f%% (%.0f/%.0f MB)',
                             done / total * 100, done / 1024 / 1024, total / 1024 / 1024)

                await download_archive(urls, archive, progress_cb=progress, log=log)
                log.info('maimaidx 素材包下载完成，开始解压（约 1-2 分钟）...')
            static = extract_archive(archive, work)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                _shutil.rmtree(target)
            _shutil.move(str(static), str(target))
            _shutil.rmtree(work, ignore_errors=True)
            try:
                archive.unlink()
            except OSError:
                pass
            self._init_source_renderer()
            if self.srender is not None:
                log.info('maimaidx 素材就绪，源插件同款渲染已启用！')
            else:
                log.error('maimaidx 素材解压完成但渲染器初始化失败，请检查素材完整性')
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 下载失败不影响其他功能
            log.error('maimaidx 素材自动下载失败: %s（查询功能不受影响；'
                      '可手动下载素材包解压后把 static 目录放到 %s，或在 resources.download_url 配置其他地址）',
                      e, target)

    # ---------- 猜歌游戏辅助 ----------

    GUESS_TIMEOUT = 300  # 单轮猜歌时限（秒）

    def _reserve_guess(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """同步占位：同一会话只允许一轮猜歌，已存在则返回 None（以第一个为准）。

        占位在第一个 await 之前完成，避免两次快速连发都通过检查后互相覆盖。
        """
        if stream_id in self.guess_games:
            return None
        game: Dict[str, Any] = {
            'music': None,
            'answers': [],
            'mode': '',
            'attempts': 0,
            'task': None,
            'starting': True,
        }
        self.guess_games[stream_id] = game
        return game

    def _commit_guess(self, stream_id: str, game: Dict[str, Any], music: Music, mode: str) -> None:
        """占位成功后填入题目并启动超时计时。"""
        aliases = self.mai.total_alias_list.aliases_of(int(music.id))
        game.update({
            'music': music,
            'answers': mai_guess.build_answers(music, aliases),
            'mode': mode,
            'attempts': 0,
            'starting': False,
        })
        game['task'] = asyncio.create_task(self._guess_timeout(stream_id))

    def _end_guess(self, stream_id: str) -> Optional[Dict[str, Any]]:
        game = self.guess_games.pop(stream_id, None)
        if game and game.get('task'):
            game['task'].cancel()
        return game

    async def _guess_timeout(self, stream_id: str) -> None:
        try:
            await asyncio.sleep(self.GUESS_TIMEOUT)
        except asyncio.CancelledError:
            return
        game = self.guess_games.pop(stream_id, None)
        if game:
            music: Music = game['music']
            await self._send_text(
                stream_id,
                f'⏰ 猜歌时间到！正确答案是：《{music.title}》（ID {music.id}）',
            )
            try:
                await self._send_song_info(stream_id, music)
            except Exception:  # noqa: BLE001
                pass

    # ---------- 访问控制 ----------

    def _access_parse(self, raw: str) -> List[str]:
        return [x.strip().lower() for x in re.split(r'[\s,，;；]+', raw or '') if x.strip()]

    def _access_check(self, kwargs: Dict[str, Any]) -> Optional[str]:
        """访问控制判定：返回拒绝提示文本，None 表示允许。"""
        mode = getattr(getattr(self.config, 'access', None), 'access_mode', 'off')
        if mode not in ('black', 'white'):
            return None
        if kwargs.get('is_local_operator'):
            return None
        uid = str(kwargs.get('user_id') or '').strip()
        gid = str(kwargs.get('group_id') or '').strip()

        def hit(entries: List[str]) -> Tuple[bool, bool]:
            u_hit = bool(uid) and f'user:{uid}' in entries
            g_hit = bool(gid) and (gid in entries or f'group:{gid}' in entries)
            return u_hit, g_hit

        if mode == 'black':
            bl = self._access_parse(self.config.access.blacklist)
            u_hit, g_hit = hit(bl)
            if u_hit:
                return '你已被禁止使用 maimai 查分功能。'
            if g_hit:
                return '本群已禁止使用 maimai 查分功能。'
            return None
        # white
        wl = self._access_parse(self.config.access.whitelist)
        if not wl:
            return None  # 白名单为空视为尚未配置，暂不限制
        u_hit, g_hit = hit(wl)
        if u_hit or g_hit:
            return None
        if gid:
            return 'maimai 查分功能未对本群开放。'
        return 'maimai 查分功能未对你开放。'

    @staticmethod
    def _access_wrap(fn):
        """包装命令处理器：进入前做黑白名单检查。"""
        import functools

        info = getattr(fn, '__maibot_component_info__', None)

        @functools.wraps(fn)
        async def wrapper(self, *args, **kwargs):
            deny = self._access_check(kwargs)
            if deny:
                if getattr(self.config.access, 'notify', True):
                    stream_id = str(kwargs.get('stream_id') or '')
                    if stream_id:
                        try:
                            await self.ctx.send.text(deny, stream_id)
                        except Exception:  # noqa: BLE001
                            pass
                return True, '已拒绝', True
            return await fn(self, *args, **kwargs)

        if info is not None:
            wrapper.__maibot_component_info__ = info
        return wrapper

    # ---------- 生命周期 ----------

    async def on_load(self) -> None:
        self._ready = asyncio.Event()
        self._load_task = asyncio.create_task(self._init_data())
        self.ctx.logger.info('maimaidx 插件已加载，曲库数据正在后台初始化')

    async def on_unload(self) -> None:
        if self._load_task:
            self._load_task.cancel()
            try:
                await self._load_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._load_task = None
        for stream_id in list(self.guess_games):
            self._end_guess(stream_id)
        if self._assets_task and not self._assets_task.done():
            self._assets_task.cancel()
            try:
                await self._assets_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._assets_task = None
        self.ctx.logger.info('maimaidx 插件已卸载')

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF and self.api:
            cfg = self.config.api
            self.api.apply_config(
                token=cfg.maimaidx_token.strip(),
                timeout=cfg.request_timeout,
                prober_proxy=cfg.use_prober_proxy,
                alias_proxy=cfg.use_alias_proxy,
                client_id=cfg.divingfish_client_id.strip(),
                client_secret=cfg.divingfish_client_secret.strip(),
                auth_url=cfg.divingfish_auth_url.strip(),
                scope=cfg.divingfish_scope.strip(),
            )
            if self.mai:
                self.mai.cover_base_url = cfg.cover_base_url.rstrip('/')
                self.mai.artist_alias_url = cfg.artist_alias_url.strip()
                self.mai.charter_alias_url = cfg.charter_alias_url.strip()
            self.ctx.logger.info('maimaidx 配置已热更新（OAuth %s）',
                                 '已启用' if self.api.oauth_enabled else '未启用')

    async def _init_data(self) -> None:
        if self._ready is None:
            self._ready = asyncio.Event()
        try:
            cfg = self.config.api
            self.api = MaimaiAPI(
                token=cfg.maimaidx_token.strip(),
                timeout=cfg.request_timeout,
                prober_proxy=cfg.use_prober_proxy,
                alias_proxy=cfg.use_alias_proxy,
                client_id=cfg.divingfish_client_id.strip(),
                client_secret=cfg.divingfish_client_secret.strip(),
                auth_url=cfg.divingfish_auth_url.strip(),
                scope=cfg.divingfish_scope.strip(),
            )
            self.mai = MaiMusic(
                data_dir=self.ctx.paths.data_dir,
                api=self.api,
                cover_base_url=cfg.cover_base_url,
                artist_alias_url=cfg.artist_alias_url.strip(),
                charter_alias_url=cfg.charter_alias_url.strip(),
            )
            await self.mai.load_all()
            mai_render.init_fonts(
                font_path=self.config.display.font_path,
                extra_dirs=[self.ctx.paths.data_dir],
            )
            self.ctx.logger.info(
                'maimaidx 曲库初始化完成：%d 首曲目，%d 条别名（图片输出：%s）',
                len(self.mai.total_list),
                len(self.mai.total_alias_list),
                '开启' if mai_render.available() else '字体不可用，回退文本',
            )
        except Exception as e:  # noqa: BLE001 - 加载失败不影响插件运行
            self.ctx.logger.error('maimaidx 曲库初始化失败: %s（可稍后发送「maimai更新数据」重试）', e)
        finally:
            try:
                self._init_source_renderer()
            except Exception as e:  # noqa: BLE001
                self.ctx.logger.warning('maimaidx 源渲染初始化异常: %s', e)
            self._ready.set()
        # 素材缺失时后台自动下载（不阻塞聊天命令，下载完成后自动切换源渲染）
        if self.srender is None:
            try:
                auto = getattr(self.config.resources, 'auto_download', False)
            except AttributeError:
                auto = False
            if auto and (self._assets_task is None or self._assets_task.done()):
                self.ctx.logger.info('maimaidx 将在后台自动下载官方素材包，完成后自动启用源渲染')
                self._assets_task = asyncio.create_task(self._ensure_assets())

    # ---------- 通用辅助 ----------

    async def _wait_ready(self, timeout: float = 60.0) -> bool:
        if self._ready is None:
            return False
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    def _data_ready(self) -> bool:
        return bool(self.mai and self.mai.music_loaded)

    async def _send_text(self, stream_id: str, text: str) -> None:
        await self.ctx.send.text(text, stream_id)

    async def _send_data_error(self, stream_id: str) -> None:
        await self._send_text(
            stream_id,
            'maimai 曲库数据尚未加载完成，请稍等片刻再试；如持续失败请发送「maimai更新数据」。',
        )

    async def _send_long(self, stream_id: str, text: str, nickname: str = 'maimaidx 查分') -> None:
        if self.config.display.long_output_forward and len(text) > 600:
            try:
                node = {
                    'user_id': '0',
                    'nickname': nickname,
                    'segments': [{'type': 'text', 'content': text}],
                }
                ok = await self.ctx.send.forward([node], stream_id)
                if ok:
                    return
            except Exception:  # noqa: BLE001 - 适配器不支持转发时回退文本
                pass
        await self.ctx.send.text(text, stream_id)

    async def _send_cover(self, stream_id: str, music_id: str) -> None:
        import base64

        if not self.config.display.send_cover_image or not self.mai:
            return
        try:
            data = await self.mai.get_cover(music_id)
            if data:
                await self.ctx.send.image(base64.b64encode(data).decode(), stream_id)
        except Exception:  # noqa: BLE001 - 曲绘失败静默跳过
            pass

    async def _send_image(self, stream_id: str, png: bytes) -> bool:
        import base64

        try:
            ok = await self.ctx.send.image(base64.b64encode(png).decode(), stream_id)
            return bool(ok)
        except Exception:  # noqa: BLE001 - 适配器不支持图片时回退文本
            return False

    def _image_enabled(self) -> bool:
        return self.config.display.use_image_output and mai_render.available()

    async def _send_candidates(self, stream_id: str, candidates: List[Music], note: str) -> None:
        lines = [f'{m.id}：{m.title}' for m in candidates[:20]]
        text = f'{note}：\n' + '\n'.join(lines) + '\n※ 请使用「id 曲目ID」查询指定曲目。'
        await self._send_text(stream_id, text)

    async def _send_search_results(self, stream_id: str, songs: List[Music], page: int = 1,
                                   user_id: Any = None) -> None:
        """源插件查歌结果渲染：1 首发详情卡，≤5 首发文本，>5 首发曲目列表卡。"""
        if not songs:
            return
        if len(songs) == 1:
            await self._send_song_info(stream_id, songs[0], user_id=user_id)
            return
        if len(songs) <= 5:
            lines = ''.join(f'{f"「{m.id}」":<7} {m.title}\n' for m in songs)
            await self._send_text(stream_id, lines.rstrip())
            return
        if self.srender is not None and self._image_enabled():
            try:
                png = self.srender.song_list(songs, page, bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return
            except Exception:  # noqa: BLE001 - 源渲染失败回退简化列表
                pass
        rows = [f'「{m.id}」 {m.title}' for m in songs]
        per = self.config.display.songs_per_page
        page_rows, page2, total = paginate(rows, page, per)
        await self._send_list(stream_id, f'找到 {len(songs)} 首：', page_rows, page2, total, len(rows))

    async def _send_song_info(self, stream_id: str, music: Music, prefix: str = '',
                              user_id: Any = None) -> None:
        aliases = self.mai.total_alias_list.aliases_of(int(music.id))
        text = prefix + format_song_info(music, aliases)
        if prefix:
            await self._send_text(stream_id, prefix.rstrip())
        if self.srender is not None and self._image_enabled():
            try:
                player = None
                qqid = _to_int(user_id)
                if qqid:
                    try:
                        player = await self.api.query_user_b50(qqid=qqid)
                    except MaimaiError:
                        player = None
                if music.is_utage:
                    png = self.srender.song_chart_banquet_info(music, bot_name=self.config.display.bot_name)
                else:
                    png = self.srender.song_chart_info(music, player, bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return
            except Exception:  # noqa: BLE001 - 源渲染失败回退简化渲染
                pass
        if self._image_enabled():
            try:
                cover = await self.mai.get_cover(music.id) if self.config.display.send_cover_image else None
                png = mai_render.song_info_image(music, aliases, cover)
                if png and await self._send_image(stream_id, png):
                    return
            except Exception:  # noqa: BLE001 - 渲染失败回退文本
                pass
            if self.config.display.send_cover_image:
                await self._send_cover(stream_id, music.id)
        else:
            if self.config.display.send_cover_image:
                await self._send_cover(stream_id, music.id)
        await self._send_text(stream_id, text)

    async def _send_list(
        self,
        stream_id: str,
        header: str,
        page_rows: List[str],
        page: int,
        total_pages: int,
        total_count: int,
    ) -> None:
        footer = f'第「{page}」页，共「{total_pages}」页（{total_count} 条）。请使用「id 曲目ID」查询详情。'
        if self._image_enabled():
            try:
                png = mai_render.list_image(header, page_rows, footer)
                if png and await self._send_image(stream_id, png):
                    return
            except Exception:  # noqa: BLE001
                pass
        await self._send_text(stream_id, format_search_list(header, page_rows, page, total_pages, total_count))

    async def _resolve_song(self, keyword: str) -> Tuple[Optional[Music], List[Music], str]:
        """关键词 -> (唯一曲目, 候选列表, 说明)。优先别名，其次标题，最后在线别名兜底。"""
        mai = self.mai
        kw = keyword.strip()
        if not kw:
            return None, [], ''
        if kw.isdigit():
            m = mai.total_list.by_id(kw)
            if m:
                return m, [], ''
        # 本地别名
        hits = mai.total_alias_list.by_alias(kw)
        songs = [s for s in (mai.total_list.by_id(a.SongID) for a in hits) if s]
        if len(songs) == 1:
            return songs[0], [], ''
        if len(songs) > 1:
            return None, songs, f'找到 {len(songs)} 个相同别名的曲目'
        # 本地标题
        exact = mai.total_list.by_title(kw, exact=True)
        if len(exact) == 1:
            return exact[0], [], ''
        if len(exact) > 1:
            return None, exact, f'找到 {len(exact)} 个相同标题的曲目'
        part = mai.total_list.by_title(kw)
        if len(part) == 1:
            return part[0], [], ''
        if 1 < len(part) <= 50:
            return None, part, f'找到 {len(part)} 个相似标题的曲目'
        # 在线别名兜底
        try:
            result = await self.api.get_songs(kw)
        except MaimaiError:
            result = None
        if result and result.code == 0 and isinstance(result.content, list) and result.content:
            items = [AliasItem.model_validate(x) for x in result.content]
            songs = [s for s in (mai.total_list.by_id(a.SongID) for a in items) if s]
            if len(songs) == 1:
                return songs[0], [], ''
            if len(songs) > 1:
                return None, songs, f'找到 {len(songs)} 个相同别名的曲目'
        elif result and result.code == 3006 and isinstance(result.content, list) and result.content:
            vote_lines = [f'- ID {x.get("SongID")}：{x.get("Name")}（{kw}）' for x in result.content]
            return None, [], '未收录该别名，但有相同别名的投票进行中：\n' + '\n'.join(vote_lines)
        return None, [], ''

    # ---------- 命令：曲目详情 ----------

    @Command(
        'maimaidx_song_info',
        description='查询曲目详情（定数/拟合定数/版本/难度/曲师/谱师）',
        pattern=r'(?<!\S)/?(?:[iI][dD]|歌曲信息|曲目信息)\s*(?P<sid>[0-9]+)\s*$',
    )
    async def cmd_song_info(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        sid = str((kwargs.get('matched_groups') or {}).get('sid', '')).strip()
        music = self.mai.total_list.by_id(sid)
        if not music:
            await self._send_text(stream_id, f'未找到 ID「{sid}」的乐曲')
            return True, '未找到', True
        await self._send_song_info(stream_id, music, user_id=kwargs.get('user_id'))
        return True, '查询完成', True

    # ---------- 命令：查歌 ----------

    @Command(
        'maimaidx_search',
        description='按标题或别名查歌',
        pattern=r'(?<!\S)/?(?:查歌|搜索曲目|search)\s+(?P<name>.+?)\s*$',
    )
    async def cmd_search(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        name = str((kwargs.get('matched_groups') or {}).get('name', '')).strip()
        page = 1
        tokens = name.split()
        if len(tokens) > 1 and tokens[-1].isdigit():
            page = int(tokens[-1])
            name = ' '.join(tokens[:-1])
        if not name:
            await self._send_text(stream_id, '请输入查询关键词，如：查歌 Gourmandise')
            return True, '参数为空', True
        music, candidates, note = await self._resolve_song(name)
        if music:
            await self._send_song_info(stream_id, music, user_id=kwargs.get('user_id'))
            return True, '查询完成', True
        if candidates:
            await self._send_search_results(stream_id, candidates, page, kwargs.get('user_id'))
            return True, '查询完成', True
        await self._send_text(
            stream_id,
            f'没有找到「{name}」相关的乐曲。\n'
            '※ 别名查询可用「xxx是什么歌」；确定曲名后可用「id 曲目ID」查询详情。',
        )
        return True, '未找到', True

    # ---------- 命令：定数查歌 / 拟合定数查歌 ----------

    @Command(
        'maimaidx_search_ds',
        description='按歌曲定数区间查歌',
        pattern=r'(?<!\S)/?(?:定数查歌|ds查歌)\s+(?P<args>.+?)\s*$',
    )
    async def cmd_search_ds(self, **kwargs):
        return await self._cmd_ds_search(kwargs, fit_mode=False)

    @Command(
        'maimaidx_search_fit',
        description='按拟合定数区间查歌',
        pattern=r'(?<!\S)/?(?:拟合定数查歌|拟合查歌)\s+(?P<args>.+?)\s*$',
    )
    async def cmd_search_fit(self, **kwargs):
        return await self._cmd_ds_search(kwargs, fit_mode=True)

    async def _cmd_ds_search(self, kwargs: Dict[str, Any], fit_mode: bool) -> Tuple[bool, str, bool]:
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args = str((kwargs.get('matched_groups') or {}).get('args', '')).strip().split()
        page = 1
        try:
            if len(args) == 1:
                low, high = float(args[0]), float(args[0])
            elif len(args) == 2 and '.' in args[1]:
                low, high = float(args[0]), float(args[1])
            elif len(args) == 2:
                low, high = float(args[0]), float(args[0])
                page = int(args[1])
            elif len(args) == 3:
                low, high, page = float(args[0]), float(args[1]), int(args[2])
            else:
                raise ValueError
        except ValueError:
            label = '拟合查歌' if fit_mode else '定数查歌'
            await self._send_text(
                stream_id,
                f'命令格式：\n{label} 「定数」\n{label} 「下限」「上限」「页数」',
            )
            return True, '参数错误', True
        if low > high:
            low, high = high, low
        if fit_mode:
            result = self.mai.total_list.by_fit(low, high)
        else:
            result = self.mai.total_list.by_ds(low, high)
        songs: List[Music] = []
        seen = set()
        for item in result:
            m = item[0]
            if m.id not in seen:
                seen.add(m.id)
                songs.append(m)
        if not songs:
            await self._send_text(stream_id, '没有找到该定数范围内的乐曲。')
            return True, '无结果', True
        await self._send_search_results(stream_id, songs, page, kwargs.get('user_id'))
        return True, '查询完成', True

    # ---------- 命令：曲师查歌 / 谱师查歌 ----------

    @Command(
        'maimaidx_search_artist',
        description='按曲师查歌',
        pattern=r'(?<!\S)/?曲师查歌\s+(?P<args>.+?)\s*$',
    )
    async def cmd_search_artist(self, **kwargs):
        return await self._cmd_name_search(kwargs, mode='artist')

    @Command(
        'maimaidx_search_charter',
        description='按谱师查歌',
        pattern=r'(?<!\S)/?谱师查歌\s+(?P<args>.+?)\s*$',
    )
    async def cmd_search_charter(self, **kwargs):
        return await self._cmd_name_search(kwargs, mode='charter')

    async def _cmd_name_search(self, kwargs: Dict[str, Any], mode: str) -> Tuple[bool, str, bool]:
        stream_id = str(kwargs.get('stream_id') or '')
        label = '曲师' if mode == 'artist' else '谱师'
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args = str((kwargs.get('matched_groups') or {}).get('args', '')).strip().split()
        page = 1
        if len(args) == 1:
            name = args[0]
        elif len(args) == 2 and args[1].isdigit():
            name, page = args[0], int(args[1])
        else:
            await self._send_text(stream_id, f'命令格式：\n{label}查歌「{label}名称」「页数」')
            return True, '参数错误', True
        if mode == 'artist':
            result = self.mai.total_list.by_artist(name)
        else:
            result = self.mai.total_list.by_charter(name)
        if not result:
            await self._send_text(stream_id, f'没有找到{label}包含「{name}」的乐曲。')
            return True, '无结果', True
        await self._send_search_results(stream_id, result, page, kwargs.get('user_id'))
        return True, '查询完成', True

    # ---------- 命令：bpm查歌 ----------

    @Command(
        'maimaidx_search_bpm',
        description='按 BPM 查歌',
        pattern=r'(?<!\S)/?[bB][pP][mM]查歌\s+(?P<args>.+?)\s*$',
    )
    async def cmd_search_bpm(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args = str((kwargs.get('matched_groups') or {}).get('args', '')).strip().split()
        page = 1
        try:
            if len(args) == 1:
                low = high = int(args[0])
            elif len(args) == 2:
                low, high = int(args[0]), int(args[1])
            elif len(args) == 3:
                low, high, page = int(args[0]), int(args[1]), int(args[2])
            else:
                raise ValueError
        except ValueError:
            await self._send_text(stream_id, '命令格式：\nbpm查歌 「bpm」\nbpm查歌 「下限」「上限」「页数」')
            return True, '参数错误', True
        if low > high:
            low, high = high, low
        result = self.mai.total_list.by_bpm(low, high)
        if not result:
            await self._send_text(stream_id, '没有找到该 BPM 范围的乐曲。')
            return True, '无结果', True
        await self._send_search_results(stream_id, result, page, kwargs.get('user_id'))
        return True, '查询完成', True

    # ---------- 命令：xxx是什么歌 ----------

    @Command(
        'maimaidx_alias_lookup',
        description='通过别名查询乐曲',
        pattern=r'(?<!\S)/?(?P<name>.{1,40})(?:是什么歌|是啥歌)\s*$',
    )
    async def cmd_alias_lookup(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            return True, '数据未加载', False  # 数据未就绪时不拦截，交回主流程
        name = str((kwargs.get('matched_groups') or {}).get('name', '')).strip()
        if not name:
            return True, '参数为空', True
        music, candidates, note = await self._resolve_song(name)
        if music:
            await self._send_song_info(stream_id, music, prefix='您要找的是不是：\n')
            return True, '查询完成', True
        if candidates:
            await self._send_candidates(stream_id, candidates, note)
            return True, '查询完成', True
        if note:  # 别名投票中
            await self._send_text(stream_id, note)
            return True, '查询完成', True
        await self._send_text(
            stream_id,
            f'未找到别名为「{name}」的歌曲。\n'
            '※ 如果是歌名的一部分，请使用「查歌 关键词」查询。',
        )
        return True, '未找到', True

    # ---------- 命令：b50 查分 ----------

    @Command(
        'maimaidx_b50',
        description='查询玩家 B50 成绩',
        pattern=r'(?<!\S)/?(?:[bB]50|查分)(?:\s+(?P<target>.+?))?\s*$',
    )
    async def cmd_b50(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self.api or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        target = str((kwargs.get('matched_groups') or {}).get('target') or '').strip()
        qqid: Optional[int] = None
        username: Optional[str] = None
        if not target:
            qqid = _to_int(kwargs.get('user_id'))
            if not qqid:
                await self._send_text(
                    stream_id,
                    '请在水鱼查分器绑定 QQ 后直接发送「b50」，或使用「b50 查分器用户名 / QQ号」。',
                )
                return True, '参数为空', True
        elif target.isdigit():
            qqid = int(target)
        else:
            username = target
        try:
            user = await self.api.query_user_b50(qqid=qqid, username=username)
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        except Exception as e:  # noqa: BLE001
            await self._send_text(stream_id, f'查询失败：网络错误（{e}）')
            return True, '查询失败', True
        text = format_b50(user)
        if self.srender is not None and self._image_enabled():
            try:
                import base64 as _b64
                import httpx as _hx
                logo = None
                if qqid:
                    try:
                        async with _hx.AsyncClient(timeout=15) as session:
                            res = await session.get(
                                'https://q1.qlogo.cn/g',
                                params={'b': 'qq', 'nk': qqid, 's': 100})
                        if res.status_code == 200 and res.content:
                            logo = res.content
                    except Exception:  # noqa: BLE001
                        logo = None
                png = self.srender.draw_b50(user, self.mai.total_list, qq_logo=logo,
                                            bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return True, '查询完成', True
            except Exception:  # noqa: BLE001 - 源渲染失败回退
                pass
        if self._image_enabled():
            try:
                png = mai_render.b50_image(user)
                if png and await self._send_image(stream_id, png):
                    return True, '查询完成', True
            except Exception:  # noqa: BLE001
                pass
        await self._send_long(stream_id, text)
        return True, '查询完成', True

    # ---------- 命令：查成绩（OAuth 代查 / 开发者接口） ----------

    @Command(
        'maimaidx_record',
        description='查询玩家指定曲目成绩（minfo 查自己，查成绩 可查自己或他人）',
        pattern=r'(?<!\S)/?(?:查成绩|[mM][iI][nN][fF][oO])\s+(?P<args>.+?)\s*$',
    )
    async def cmd_record(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self.api or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args = str((kwargs.get('matched_groups') or {}).get('args', '')).strip().split(None, 1)
        oauth_user: Optional[str] = None
        qqid: Optional[int] = None
        username: Optional[str] = None
        display_name: str = ''
        if len(args) == 1:
            # 查自己的成绩：走 OAuth 代查
            if not self.api.oauth_enabled:
                await self._send_text(
                    stream_id,
                    '查自己的成绩需要配置水鱼 OAuth，请在插件配置中填写 divingfish_client_id 和 '
                    'divingfish_client_secret；\n查他人成绩请用：查成绩 「查分器用户名或QQ号」「曲目ID或别名」',
                )
                return True, 'OAuth 未配置', True
            oauth_user = str(kwargs.get('user_id') or '')
            if not oauth_user:
                await self._send_text(stream_id, '无法识别你的用户标识，请使用：查成绩 「查分器用户名或QQ号」「曲目ID或别名」')
                return True, '无用户标识', True
            display_name = '你'
            song_kw = args[0].strip()
        else:
            target, song_kw = args[0].strip(), args[1].strip()
            display_name = target
            if target.isdigit():
                qqid = int(target)
            else:
                username = target
        music, candidates, note = await self._resolve_song(song_kw)
        if not music:
            if candidates:
                await self._send_candidates(stream_id, candidates, note)
            else:
                await self._send_text(stream_id, f'没有找到乐曲「{song_kw}」。')
            return True, '未找到曲目', True
        try:
            result = await self.api.query_user_record(
                oauth_user=oauth_user, qqid=qqid, username=username, music_id=music.id)
        except OAuthError as e:
            await self._send_text(stream_id, f'{e}')
            return True, 'OAuth 错误', True
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        except Exception as e:  # noqa: BLE001
            await self._send_text(stream_id, f'查询失败：网络错误（{e}）')
            return True, '查询失败', True
        raw = (result or {}).get(str(music.id)) or []
        records = [PlayChart.model_validate(x) for x in raw]
        if not records:
            await self._send_text(stream_id, f'{display_name}没有乐曲「{music.title}」的成绩记录。')
            return True, '无成绩', True
        # 源渲染：minfo 谱面游玩数据
        if self.srender is not None and self._image_enabled() and not music.is_utage:
            try:
                diff: List[Optional[PlayRecord]] = [None for _ in music.ds]
                for r in records:
                    if r.level_index < len(diff):
                        diff[r.level_index] = PlayRecord(
                            song_id=r.song_id or int(music.id),
                            achievements=r.achievements, fc=r.fc, fs=r.fs,
                            level=r.level or (music.level[r.level_index] if r.level_index < len(music.level) else ''),
                            level_index=r.level_index, ds=r.ds or music.ds[r.level_index],
                            dxScore=r.dxScore, ra=r.ra, rate=r.rate, title=r.title, type=r.type)
                png = self.srender.song_play_data(music, diff, bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return True, '查询完成', True
            except Exception:  # noqa: BLE001 - 源渲染失败回退文本
                pass
        text = format_player_record(display_name, music, records)
        await self._send_text(stream_id, text)
        return True, '查询完成', True

    # ---------- 命令：绑定水鱼 / 确认码 / 解绑 ----------

    @Command(
        'maimaidx_bind_divingfish',
        description='发起水鱼账号绑定（OAuth 设备授权）',
        pattern=r'(?<!\S)/?(?:绑定水鱼|水鱼绑定)\s*$',
    )
    async def cmd_bind_divingfish(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        user_id = str(kwargs.get('user_id') or '')
        if not self.api or not self.api.oauth_enabled:
            await self._send_text(
                stream_id,
                '本机器人未启用水鱼 OAuth，暂时无法绑定。\n'
                '※ 需要管理员在插件配置中填写 divingfish_client_id 与 divingfish_client_secret。',
            )
            return True, 'OAuth 未配置', True
        if not user_id:
            await self._send_text(stream_id, '无法识别你的用户标识，请在聊天中直接发送「绑定水鱼」。')
            return True, '无用户标识', True
        try:
            info = await self.api.start_binding(user_id)
        except MaimaiError as e:
            await self._send_text(stream_id, f'发起绑定失败：{e}')
            return True, '绑定失败', True
        except Exception as e:  # noqa: BLE001
            await self._send_text(stream_id, f'发起绑定失败：网络错误（{e}）')
            return True, '绑定失败', True
        uri = info.get('verification_uri_complete') or info.get('verification_uri') or ''
        text = (
            '【水鱼账号绑定】\n'
            f'1. 点开下面的链接，登录水鱼账号并确认授权（{info.get("expires_in", "?")} 秒内有效）：\n{uri}\n'
            '2. 授权成功后页面会显示一串确认码，把它发给我：\n'
            '水鱼确认码 确认码\n'
            '※ 绑定只代表允许本机器人按你授权的范围代查成绩，机器人不会保存你的账号密码。'
        )
        await self._send_text(stream_id, text)
        return True, '已发起绑定', True

    @Command(
        'maimaidx_confirm_binding',
        description='回填水鱼绑定确认码，完成绑定',
        pattern=r'(?<!\S)/?(?:水鱼确认码|水鱼绑定确认|绑定确认码)\s+(?P<code>.+?)\s*$',
    )
    async def cmd_confirm_binding(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        user_id = str(kwargs.get('user_id') or '')
        code = str((kwargs.get('matched_groups') or {}).get('code', '')).strip()
        if not self.api or not self.api.oauth_enabled:
            await self._send_text(stream_id, '本机器人未启用水鱼 OAuth，无需绑定。')
            return True, 'OAuth 未配置', True
        if not user_id:
            await self._send_text(stream_id, '无法识别你的用户标识。')
            return True, '无用户标识', True
        if not code:
            await self._send_text(stream_id, '请把授权页面显示的确认码发给我：水鱼确认码 确认码')
            return True, '参数为空', True
        try:
            await self.api.complete_binding(user_id, code)
        except OAuthError as e:
            await self._send_text(stream_id, f'绑定失败：{e}')
            return True, '绑定失败', True
        except MaimaiError as e:
            await self._send_text(stream_id, f'绑定失败：{e}')
            return True, '绑定失败', True
        except Exception as e:  # noqa: BLE001
            await self._send_text(stream_id, f'绑定失败：网络错误（{e}）')
            return True, '绑定失败', True
        await self._send_text(
            stream_id,
            '绑定成功！现在可以直接发送：\n'
            '· 查成绩 曲目ID或别名 —— 查你自己的单曲成绩\n'
            '※ 如需取消授权，请到水鱼查分器账号页管理。',
        )
        return True, '绑定完成', True

    @Command(
        'maimaidx_unbind_divingfish',
        description='丢弃本机缓存的水鱼代查令牌',
        pattern=r'(?<!\S)/?(?:解绑水鱼|取消绑定水鱼)\s*$',
    )
    async def cmd_unbind_divingfish(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        user_id = str(kwargs.get('user_id') or '')
        if self.api:
            self.api.unbind(user_id)
        await self._send_text(
            stream_id,
            '已清除本机缓存的代查令牌。\n'
            '※ 如需彻底取消授权，请登录水鱼查分器账号页，在已授权应用中移除本机器人。',
        )
        return True, '已解绑', True

    # ---------- 扩展功能辅助 ----------

    def _parse_user_target(self, target: str, kwargs: Dict[str, Any]) -> Tuple[Optional[int], Optional[str], str]:
        """目标参数 -> (qqid, username, 展示名)。为空时回退发送者。"""
        target = (target or '').strip()
        if not target:
            qqid = _to_int(kwargs.get('user_id'))
            return (qqid, None, '您' if qqid else '')
        if target.isdigit():
            return int(target), None, target
        return None, target, target

    async def _fetch_verlist(self, qqid: Optional[int], username: Optional[str]) -> List[PlayRecord]:
        """拉取用户全部版本成绩列表（verlist）。"""
        records = await self.api.query_user_plate(
            qqid=qqid, username=username, version=mai_extra.ALL_DX_VERSIONS)
        return [PlayRecord.model_validate(x) for x in records]

    def _random_song(self, tp: Optional[List[str]] = None,
                     level: Optional[str] = None,
                     diff_index: Optional[int] = None) -> Optional[Music]:
        pool = []
        for m in self.mai.total_list:
            if m.is_utage:
                continue
            if tp and m.type not in tp:
                continue
            if level is not None:
                if diff_index is not None:
                    if diff_index >= len(m.level) or m.level[diff_index] != level:
                        continue
                elif level not in m.level:
                    continue
            pool.append(m)
        return random.choice(pool) if pool else None

    # ---------- 命令：随机曲目 ----------

    @Command(
        'maimaidx_random',
        description='随机一首曲目（可指定谱面类型/难度/等级）',
        pattern=r'(?<!\S)/?[随来给]个\s*(?P<diff>[dD][xX]|[sS][dD]|标准)?\s*(?P<color>[绿黄红紫白])?\s*(?P<level>[0-9]+\+?)?\s*$',
    )
    async def cmd_random(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        g = kwargs.get('matched_groups') or {}
        diff = (g.get('diff') or '').strip()
        tp: Optional[List[str]] = None
        if diff.lower() == 'dx':
            tp = ['DX']
        elif diff:
            tp = ['SD']
        color = (g.get('color') or '').strip()
        diff_index = mai_extra.COLOR_TO_INDEX.get(color) if color else None
        music = self._random_song(tp=tp, level=(g.get('level') or '').strip() or None,
                                  diff_index=diff_index)
        if not music:
            await self._send_text(stream_id, '没有这样的乐曲哦。')
            return True, '无结果', True
        await self._send_song_info(stream_id, music)
        return True, '查询完成', True

    # ---------- 命令：随机 变量 值 ----------

    @Command(
        'maimaidx_random_var',
        description='随机指定条件的曲目：随机 变量 值（定数/拟合定数/版本/难度/曲师/谱师/定数差距）',
        pattern=r'(?<!\S)/?随机\s*(?P<var>\S+)?\s*(?P<value>\S.*?)?\s*$',
    )
    async def cmd_random_var(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        g = kwargs.get('matched_groups') or {}
        var_raw = (g.get('var') or '').strip().lower()
        value = (g.get('value') or '').strip()
        if not var_raw:
            music = self._random_song()
            if not music:
                await self._send_text(stream_id, '没有这样的乐曲哦。')
                return True, '无结果', True
            await self._send_song_info(stream_id, music)
            return True, '查询完成', True
        var = RANDOM_VAR_MAP.get(var_raw)
        if not var:
            await self._send_text(
                stream_id,
                f'不支持的变量「{var_raw}」。\n'
                '可选变量：定数 / 拟合定数 / 版本 / 难度 / 分区 / 曲师 / 谱师 / 定数差距\n'
                '示例：随机 定数 14.0-14.2 ｜ 随机 版本 祭 ｜ 随机 难度 紫 ｜ '
                '随机 分区 东方 ｜ 随机 曲师 Yooh ｜ 随机 定数差距 0.5',
            )
            return True, '未知变量', True
        charts: List[Tuple[Music, int]] = []
        songs: List[Music] = []
        try:
            if var in ('ds', 'fit'):
                low, high = mai_extra.parse_range(value)
                for m in self.mai.total_list:
                    if m.is_utage:
                        continue
                    for i in range(len(m.ds)):
                        v = m.ds[i] if var == 'ds' else m.fit_diff(i)
                        if v is None:
                            continue
                        if low <= v <= high:
                            charts.append((m, i))
            elif var == 'version':
                vers = mai_extra.resolve_versions(value, list(
                    {m.version for m in self.mai.total_list if m.version}))
                if not vers:
                    await self._send_text(
                        stream_id,
                        f'没有找到版本「{value}」，可用牌子单字（真/熊/华/爽/煌/宙/星/祭/祝/双/宴/镜/彩…）或版本名关键词。',
                    )
                    return True, '无版本', True
                songs = [m for m in self.mai.total_list
                         if not m.is_utage and m.version.lower() in vers]
            elif var == 'difficulty':
                parsed = mai_extra.parse_difficulty(value)
                if not parsed:
                    await self._send_text(
                        stream_id, '难度值请用 绿/黄/红/紫/白（或 Basic~Re:Master），也可以直接给等级如 14+')
                    return True, '参数错误', True
                kind, v = parsed
                if kind == 'diff':
                    for m in self.mai.total_list:
                        if not m.is_utage and v < len(m.level):
                            charts.append((m, v))
                else:
                    for m in self.mai.total_list:
                        if m.is_utage:
                            continue
                        for i, lv in enumerate(m.level):
                            if lv == v:
                                charts.append((m, i))
            elif var == 'genre':
                genres = sorted({m.basic_info.genre for m in self.mai.total_list
                                 if m.basic_info.genre})
                if not value:
                    await self._send_text(
                        stream_id,
                        '请指定分区，当前曲库包含：' + ' / '.join(genres) + '\n'
                        '示例：随机 分区 东方 ｜ 随机 分区 舞萌',
                    )
                    return True, '参数为空', True
                vl = value.lower()
                songs = [m for m in self.mai.total_list if vl in m.basic_info.genre.lower()]
                if not songs:
                    await self._send_text(
                        stream_id,
                        f'没有找到分区「{value}」的乐曲。\n当前曲库包含：' + ' / '.join(genres),
                    )
                    return True, '无分区', True
            elif var == 'artist':
                names = self.mai.resolve_name('artist', value)
                songs = [m for m in self.mai.total_list
                         if not m.is_utage and any(n.lower() in m.artist.lower() for n in names)]
            elif var == 'charter':
                names = self.mai.resolve_name('charter', value)
                for m in self.mai.total_list:
                    if m.is_utage:
                        continue
                    for i, c in enumerate(m.charts):
                        if any(n.lower() in (c.charter or '').lower() for n in names):
                            charts.append((m, i))
            elif var == 'gap':
                low, high = mai_extra.parse_range(value)
                single = low == high
                for m in self.mai.total_list:
                    if m.is_utage:
                        continue
                    for i in range(len(m.ds)):
                        fit = m.fit_diff(i)
                        if fit is None:
                            continue
                        gap = round(abs(m.ds[i] - fit), 2)
                        # 单值 = 精确匹配（保留两位小数）；区间 = 落在区间内
                        if (gap == round(low, 2)) if single else (low <= gap <= high):
                            charts.append((m, i))
        except ValueError:
            await self._send_text(stream_id, '数值格式错误，区间示例：14.0-14.2（也支持 ~ 连接）')
            return True, '格式错误', True
        if charts:
            music, _ = random.choice(charts)
        elif songs:
            music = random.choice(songs)
        else:
            music = None
        if not music:
            await self._send_text(stream_id, '没有符合条件的乐曲。')
            return True, '无结果', True
        await self._send_song_info(stream_id, music)
        return True, '查询完成', True

    # ---------- 命令：曲师/谱师别名管理 ----------

    @Command(
        'maimaidx_name_alias_add',
        description='添加曲师/谱师别名（添加曲师别名 原名/已有别名 新别名）',
        pattern=r'(?<!\S)/?添加(?P<kind>曲师|谱师)别名\s+(?P<args>.+?)\s*$',
    )
    async def cmd_name_alias_add(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        g = kwargs.get('matched_groups') or {}
        kind = 'artist' if g.get('kind') == '曲师' else 'charter'
        label = '曲师' if kind == 'artist' else '谱师'
        args = (g.get('args') or '').strip().split(None, 1)
        if len(args) < 2:
            await self._send_text(
                stream_id,
                f'命令格式：添加{label}别名 「原名/已有别名」 「新别名」\n'
                f'示例：添加{label}别名 {("BlackY" if kind == "artist" else "某S氏")} '
                f'{("黑橘" if kind == "artist" else "某S老师")}',
            )
            return True, '参数不足', True
        ref, new_alias = args[0].strip(), args[1].strip()
        # 解析第一个参数：已有别名 -> 其全名；曲库精确/唯一子串匹配 -> 该曲师；否则视为新全名
        store = self.mai.artist_aliases if kind == 'artist' else self.mai.charter_aliases
        ref_l = ref.lower()
        canonical: Optional[str] = None
        known_ref = False
        if ref_l in store and store[ref_l]:
            canonical = store[ref_l][0]
            known_ref = True
        if canonical is None:
            exact = sorted({m.artist for m in self.mai.total_list
                            if m.artist and m.artist.lower() == ref_l})
            if exact:
                canonical = exact[0]
                known_ref = True
        if canonical is None:
            sub = sorted({m.artist for m in self.mai.total_list
                          if m.artist and ref_l in m.artist.lower()})
            if len(sub) == 1:
                canonical = sub[0]
                known_ref = True
        if canonical is None:
            canonical = ref
        ok = self.mai.add_name_alias(kind, new_alias, canonical)
        if ok:
            msg = f'已添加{label}别名：「{new_alias}」→「{canonical}」'
            if not known_ref:
                msg += f'\n⚠ 未在曲库/别名库中找到「{ref}」，已按原样保存为新{label}名。'
            msg += f'\n现在可以用「随机 {label} {new_alias}」使用它。'
            await self._send_text(stream_id, msg)
        else:
            await self._send_text(stream_id, f'「{new_alias}」已是「{canonical}」的{label}别名，无需重复添加。')
        return True, '完成', True

    @Command(
        'maimaidx_name_alias_list',
        description='查看曲师/谱师别名列表',
        pattern=r'(?<!\S)/?(?P<kind>曲师|谱师)别名\s*$',
    )
    async def cmd_name_alias_list(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        kind = 'artist' if (kwargs.get('matched_groups') or {}).get('kind') == '曲师' else 'charter'
        label = '曲师' if kind == 'artist' else '谱师'
        store = self.mai.artist_aliases if kind == 'artist' else self.mai.charter_aliases
        if not store:
            url_field = 'artist_alias_url' if kind == 'artist' else 'charter_alias_url'
            await self._send_text(
                stream_id,
                f'{label}别名库为空。\n'
                f'※ 添加别名：添加{label}别名 别名 全名\n'
                f'※ 导入别名库：在插件配置 {url_field} 填入 JSON 地址（格式 {{"别名": "全名"}}）',
            )
            return True, '空', True
        rows = [f'{k} → {" / ".join(v)}' for k, v in list(store.items())[:50]]
        text = f'{label}别名（{len(store)} 条）：\n' + '\n'.join(rows)
        if len(store) > 50:
            text += f'\n……其余 {len(store) - 50} 条已省略'
        await self._send_text(stream_id, text)
        return True, '查询完成', True

    # ---------- 命令：今日mai运势 ----------

    @Command(
        'maimaidx_today',
        description='今日 maimai 运势与推荐歌曲',
        pattern=r'(?<!\S)/?(?:今日[mM][aA][iI]|[mM][aA][iI]今日运势|今日舞萌)\s*$',
    )
    async def cmd_today(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        uid = str(kwargs.get('user_id') or '')
        qq = _to_int(uid) or (zlib.crc32(uid.encode('utf-8')) or 1)
        fortune = mai_extra.today_fortune(qq)
        music = self.mai.total_list[fortune['music_index'] % len(self.mai.total_list)]
        lines = [f'今日人品值：{fortune["rp"]}', *fortune['lines'],
                 '打机时不要大力拍打或滑动哦',
                 f'今日推荐歌曲：ID.{music.id} - {music.title}']
        await self._send_text(stream_id, '\n'.join(lines))
        await self._send_song_info(stream_id, music)
        return True, '查询完成', True

    # ---------- 命令：mai什么 ----------

    @Command(
        'maimaidx_what',
        description='随机来一首（mai什么推分 按B50推荐）',
        pattern=r'(?<!\S)/?(?:[mM][aA][iI]|maimai)什么(?P<point>.{0,8})\s*$',
    )
    async def cmd_what(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        point = str((kwargs.get('matched_groups') or {}).get('point') or '').strip()
        push = any(k in point for k in ('推分', '上分', '加分'))
        music: Optional[Music] = None
        if push:
            qqid = _to_int(kwargs.get('user_id'))
            if qqid:
                try:
                    user = await self.api.query_user_b50(qqid=qqid)
                    r = random.randint(0, 1)
                    charts = user.charts
                    bucket = charts.sd if (r == 0 and charts) else (charts.dx if charts else None)
                    if bucket and bucket[-1].ra > 0:
                        ignore = {m.song_id for m in bucket if m.achievements < 100.5}
                        ds = round(bucket[-1].ra / 22.4, 1)
                        cands = [(m, i) for m, i in self.mai.total_list.by_ds(ds, ds + 1)
                                 if int(m.id) not in ignore and not m.is_utage]
                        if cands:
                            music = random.choice(cands)[0]
                except MaimaiError:
                    music = None
        if music is None:
            pool = [m for m in self.mai.total_list if not m.is_utage]
            music = random.choice(pool)
        await self._send_song_info(stream_id, music)
        return True, '查询完成', True

    # ---------- 命令：Rating 排行 ----------

    @Command(
        'maimaidx_ranking',
        description='查看查分器 Rating 排行榜',
        pattern=r'(?<!\S)/?(?:查看排名|查看排行)\s*(?P<args>.*?)\s*$',
    )
    async def cmd_ranking(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args = str((kwargs.get('matched_groups') or {}).get('args') or '').strip()
        page, name = 1, ''
        if args.isdigit():
            page = int(args)
        else:
            name = args.lower()
        try:
            data = await self.api.rating_ranking()
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        # 源插件格式：带用户名时精确匹配返回名次文本
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        if name:
            found = next(((idx + 1, u.get('username', ''))
                          for idx, u in enumerate(data)
                          if str(u.get('username', '')).lower() == name), None)
            if found:
                await self._send_text(
                    stream_id,
                    f'截止至「{current_time}」玩家「{found[1]}」\n'
                    f'在查分器已注册用户 RA 排行第「{found[0]}」位')
            else:
                await self._send_text(
                    stream_id, f'未在查分器排行榜前「{len(data)}」名中找到玩家「{name}」')
            return True, '查询完成', True
        # 源插件格式：50 名一页的等宽文本图
        per = 50
        total_pages = max(1, (len(data) + per - 1) // per)
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * per
        page_data = data[start_idx:start_idx + per]
        header = f'截止至「{current_time}」，查分器已注册用户 RA 排行：\n'
        lines = [f'No.{start_idx + i:02d}.「{u.get("ra", 0)}」 {u.get("username", "?")}'
                 for i, u in enumerate(page_data, 1)]
        footer = f'\n第「{page} / {total_pages}」页，共「{len(data)}」名玩家'
        full_text = header + '\n'.join(lines) + footer
        if self.srender is not None and self._image_enabled():
            try:
                png = self.srender.text_image(full_text)
                if await self._send_image(stream_id, png):
                    return True, '查询完成', True
            except Exception:  # noqa: BLE001
                pass
        await self._send_text(stream_id, full_text)
        return True, '查询完成', True

    @Command(
        'maimaidx_my_rank',
        description='查询我的 Rating 排名',
        pattern=r'(?<!\S)/?我的排名\s*$',
    )
    async def cmd_my_rank(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        qqid = _to_int(kwargs.get('user_id'))
        if not qqid:
            await self._send_text(stream_id, '请在水鱼查分器绑定 QQ 后使用「我的排名」。')
            return True, '无QQ', True
        try:
            user = await self.api.query_user_b50(qqid=qqid)
            ranking = await self.api.rating_ranking()
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        username = (user.username or '').strip()
        for num, u in enumerate(ranking, 1):
            if str(u.get('username', '')).strip() == username and username:
                await self._send_text(
                    stream_id, f'您的Rating为「{u.get("ra")}」，排名第「{num}」名')
                return True, '查询完成', True
        await self._send_text(stream_id, '排行榜中暂未找到您的查分器账号。')
        return True, '未找到', True

    # ---------- 命令：全局统计 ----------

    @Command(
        'maimaidx_ginfo',
        description='查询乐曲全局游玩统计（拟合难度/平均达成率等）',
        pattern=r'(?<!\S)/?[gG][iI][nN][fF][oO]\s+(?P<args>.+?)\s*$',
    )
    async def cmd_ginfo(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args_raw = str((kwargs.get('matched_groups') or {}).get('args') or '').strip()
        idx = 3
        if args_raw[:1] in mai_extra.COLOR_TO_INDEX:
            idx = mai_extra.COLOR_TO_INDEX[args_raw[:1]]
            args_raw = args_raw[1:].strip()
        if not args_raw:
            await self._send_text(stream_id, '请输入曲目id或曲名，如：ginfo 紫Gourmandise')
            return True, '参数为空', True
        music, candidates, note = await self._resolve_song(args_raw)
        if not music:
            if candidates:
                await self._send_candidates(stream_id, candidates, note)
            else:
                await self._send_text(stream_id, f'没有找到乐曲「{args_raw}」。')
            return True, '未找到', True
        if music.is_utage and args_raw[:1] not in mai_extra.COLOR_TO_INDEX:
            idx = 4
        stats = music.stats[idx] if idx < len(music.stats) else None
        if not stats:
            await self._send_text(stream_id, '该乐曲还没有这个等级的统计信息。')
            return True, '无统计', True
        text = (
            f'{music.title}「{mai_extra.DIFFS[idx]}」（ID {music.id}）\n'
            f'游玩次数：{round(stats.cnt or 0)}\n'
            f'拟合难度：{stats.fit_diff:.2f}\n'
            f'平均达成率：{stats.avg:.2f}%\n'
            f'平均 DX 分数：{stats.avg_dx:.1f}\n'
            f'谱面成绩标准差：{stats.std_dev:.2f}'
        )
        await self._send_text(stream_id, text)
        return True, '查询完成', True

    # ---------- 命令：分数线 ----------

    @Command(
        'maimaidx_score_line',
        description='计算曲目分数线容错（分数线 帮助 查看用法）',
        pattern=r'(?<!\S)/?分数线\s+(?P<args>.+?)\s*$',
    )
    async def cmd_score_line(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args_raw = str((kwargs.get('matched_groups') or {}).get('args') or '').strip()
        parts = args_raw.split()
        if parts and parts[0] == '帮助':
            await self._send_text(stream_id, mai_extra.SCORE_LINE_HELP)
            return True, '已发送帮助', True
        m = re.search(r'([绿黄红紫白])\s?([0-9]+)', args_raw)
        if not m or len(parts) < 2:
            await self._send_text(stream_id, '格式错误，输入「分数线 帮助」以查看帮助信息')
            return True, '格式错误', True
        idx = mai_extra.COLOR_TO_INDEX[m.group(1)]
        music = self.mai.total_list.by_id(m.group(2))
        if not music:
            await self._send_text(stream_id, f'未找到ID「{m.group(2)}」的乐曲')
            return True, '未找到', True
        if idx >= len(music.charts) or idx >= len(music.ds):
            await self._send_text(stream_id, '该乐曲没有这个难度')
            return True, '无此难度', True
        try:
            line = float(parts[-1])
        except ValueError:
            await self._send_text(stream_id, '格式错误，输入「分数线 帮助」以查看帮助信息')
            return True, '格式错误', True
        result = mai_extra.score_line(music.title, mai_extra.DIFFS[idx], line, music.charts[idx].notes)
        if result is None:
            await self._send_text(stream_id, '分数线需在 0~100 之间')
            return True, '参数错误', True
        await self._send_text(stream_id, result)
        return True, '查询完成', True

    # ---------- 命令：牌子进度 ----------

    @Command(
        'maimaidx_plate',
        description='查询版本牌子完成进度（如：爽将进度）',
        pattern=r'(?<!\S)/?(?P<ver>[真超檄橙暁晓桃櫻樱紫菫堇白雪輝辉舞霸熊華华爽煌星宙祭祝双宴镜彩])(?P<plan>[極极将舞神者])舞?进度\s*(?P<user>.+?)?\s*$',
    )
    async def cmd_plate(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        if not self.mai.plate_loaded:
            await self._send_text(stream_id, '牌子数据未加载，请先发送「maimai更新数据」。')
            return True, '牌子数据缺失', True
        g = kwargs.get('matched_groups') or {}
        ver_char = mai_extra.PLATE_CN.get(g.get('ver', ''), g.get('ver', ''))
        plan = g.get('plan', '')
        if f'{ver_char}{plan}' == '真将':
            await self._send_text(stream_id, '真系没有真将哦')
            return True, '无此牌子', True
        entry = mai_extra.VERSION_MAP.get(ver_char)
        if not entry:
            await self._send_text(stream_id, f'无法识别的牌子「{ver_char}」')
            return True, '无法识别', True
        ver, key = entry
        qqid, username, display = self._parse_user_target(g.get('user') or '', kwargs)
        if not qqid and not username:
            await self._send_text(
                stream_id, '请在水鱼查分器绑定 QQ 后直接使用，或指定用户名：爽将进度 查分器用户名')
            return True, '无目标用户', True
        plate_ids = set(self.mai.total_plate_id_list.get(key, []))
        if not plate_ids:
            await self._send_text(stream_id, f'未找到「{ver_char}{plan}」的牌子数据。')
            return True, '无牌子数据', True
        remaster = set(self.mai.total_plate_id_list.get('舞ReMASTER', [])) if key == '舞' else set()
        try:
            records = [PlayRecord.model_validate(x) for x in
                       await self.api.query_user_plate(qqid=qqid, username=username, version=ver)]
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        # 源渲染：牌子进度图
        if self.srender is not None and self._image_enabled():
            try:
                png = self.srender.draw_plate_progress(
                    ver_char, plan, key, sorted(plate_ids), sorted(remaster),
                    records, self.mai.total_list, bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return True, '查询完成', True
            except Exception as e:  # noqa: BLE001 - 源渲染失败回退文本
                self.ctx.logger.warning('maimaidx 牌子进度图渲染失败: %s', e)
        predicate = mai_extra.plate_predicate(plan)
        played = set()
        unfinished: List[PlayRecord] = []
        for r in records:
            if r.song_id not in plate_ids:
                continue
            if key == '舞' and r.level_index == 4 and r.song_id not in remaster:
                continue
            played.add((r.song_id, r.level_index))
            if predicate(r):
                unfinished.append(r)
        notplayed: List[Tuple[Music, int]] = []
        for m in self.mai.total_list:
            if not m.id.isdigit() or int(m.id) not in plate_ids:
                continue
            rng = range(5) if (key == '舞' and int(m.id) in remaster) else range(4)
            for i in rng:
                if i >= len(m.ds):
                    continue
                if (int(m.id), i) not in played:
                    notplayed.append((m, i))
        per = [0] * 5
        for r in unfinished:
            if r.level_index < 5:
                per[r.level_index] += 1
        for m, i in notplayed:
            per[i] += 1
        diff_count = 5 if key == '舞' else 4
        lines = [f'{display}的「{ver_char}{plan}」剩余进度如下：']
        for i in range(diff_count):
            lines.append(f'{mai_extra.DIFFS[i]}剩余「{per[i]}」首')
        lines.append(f'共剩余「{sum(per)}」首')
        rows = []
        for r in sorted(unfinished, key=lambda x: x.ds, reverse=True)[:10]:
            rows.append(f'「{r.song_id}」「{mai_extra.DIFFS[r.level_index]}」「{r.ds:.1f}」'
                        f'{r.title}（当前 {r.achievements:.2f}%）')
        rest = max(0, 10 - len(rows))
        for m, i in sorted(notplayed, key=lambda x: x[0].ds_at(x[1]) or 0, reverse=True)[:rest]:
            rows.append(f'「{m.id}」「{mai_extra.DIFFS[i]}」「{m.ds_at(i):.1f}」{m.title}（未游玩）')
        if rows:
            lines.append('未完成中定数最高的曲目：')
            lines.extend(rows)
        await self._send_text(stream_id, '\n'.join(lines))
        return True, '查询完成', True

    # ---------- 命令：等级进度 ----------

    @Command(
        'maimaidx_level_process',
        description='查询等级进度（如：14 sss 进度）',
        pattern=(
            r'(?<!\S)/?(?P<level>[0-9]+\+?)\s?'
            r'(?P<plan>sss\+|sss|ss\+|ss|s\+|aaa|aa|a|bbb|bb|fsp|fsdp|fdxp|fsd|fdx|fc\+|ap\+|fcp|app|ap|fs|fc|s|b|c|d)'
            r'\s?进度\s?(?P<page>[0-9]+)?\s*(?P<user>.+?)?\s*$'
        ),
    )
    async def cmd_level_process(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        g = kwargs.get('matched_groups') or {}
        level = g.get('level', '')
        plan = mai_extra.SYNC_ALIAS.get(g.get('plan', '').lower(), g.get('plan', '').lower())
        if level not in mai_extra.LEVEL_LIST:
            await self._send_text(stream_id, '无此等级')
            return True, '无此等级', True
        if plan not in mai_extra.RANK_MIN_ACH and plan not in mai_extra.COMBO_RANK \
                and plan not in mai_extra.SYNC_RANK:
            await self._send_text(stream_id, '无此评价等级')
            return True, '无此评价', True
        if mai_extra.LEVEL_LIST.index(level) < 11 or (
                plan in mai_extra.SCORE_RANK and mai_extra.SCORE_RANK.index(plan) < 8):
            await self._send_text(stream_id, '兄啊，有点志向好不好')
            return True, '要求过低', True
        qqid, username, display = self._parse_user_target(g.get('user') or '', kwargs)
        if not qqid and not username:
            await self._send_text(
                stream_id, '请在水鱼查分器绑定 QQ 后直接使用，或指定用户名：14 sss 进度 查分器用户名')
            return True, '无目标用户', True
        try:
            records = await self._fetch_verlist(qqid, username)
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        # 源渲染：等级进度图（三段视图）
        if self.srender is not None and self._image_enabled():
            try:
                png = self.srender.draw_level_progress(
                    level, plan, records, self.mai.total_list,
                    category='default', bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return True, '查询完成', True
            except Exception as e:  # noqa: BLE001 - 源渲染失败回退列表
                self.ctx.logger.warning('maimaidx 等级进度图渲染失败: %s', e)
        predicate = mai_extra.plan_predicate(plan)
        rec_map: Dict[Tuple[int, int], PlayRecord] = {}
        for r in records:
            rec_map.setdefault((r.song_id, r.level_index), r)
        completed: List[PlayRecord] = []
        unfinished: List[PlayRecord] = []
        notplayed: List[Tuple[Music, int]] = []
        for m in self.mai.total_list:
            if m.is_utage:
                continue
            for i, lv in enumerate(m.level):
                if lv != level:
                    continue
                r = rec_map.get((int(m.id), i))
                if r is None:
                    notplayed.append((m, i))
                elif predicate(r):
                    completed.append(r)
                else:
                    unfinished.append(r)
        total = len(completed) + len(unfinished) + len(notplayed)
        plan_label = plan.upper() if plan in mai_extra.COMBO_RANK + mai_extra.SYNC_RANK else plan
        rows = []
        for r in sorted(unfinished, key=lambda x: x.ds, reverse=True):
            rows.append(f'「{r.song_id}」「{mai_extra.DIFFS[r.level_index]}」「{r.ds:.1f}」'
                        f'{r.title}（当前 {r.achievements:.2f}%）')
        for m, i in sorted(notplayed, key=lambda x: x[0].ds_at(x[1]) or 0, reverse=True):
            rows.append(f'「{m.id}」「{mai_extra.DIFFS[i]}」「{m.ds_at(i):.1f}」{m.title}（未游玩）')
        per = self.config.display.songs_per_page
        page = _to_int(g.get('page')) or 1
        page_rows, page, total_pages = paginate(rows, page, per)
        header = f'{display}的「{level} {plan_label}」进度：完成 {len(completed)} / 共 {total} 首'
        if not rows:
            await self._send_text(stream_id, header + '，全部完成啦！')
            return True, '查询完成', True
        await self._send_list(stream_id, header, page_rows, page, total_pages, len(rows))
        return True, '查询完成', True

    # ---------- 命令：定数表 ----------

    @Command(
        'maimaidx_ds_table',
        description='查询指定等级的定数表（如：14定数表）',
        pattern=r'(?<!\S)/?(?P<level>[0-9]+\+?)定数表\s*$',
    )
    async def cmd_ds_table(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        level = str((kwargs.get('matched_groups') or {}).get('level') or '')
        if level not in mai_extra.LEVEL_LIST:
            await self._send_text(stream_id, '无法识别的定数')
            return True, '无法识别', True
        if mai_extra.LEVEL_LIST.index(level) < 6:
            await self._send_text(stream_id, '只支持查询lv7-15的定数表')
            return True, '等级过低', True
        # 源渲染：定数表
        if self.srender is not None and self._image_enabled():
            try:
                level_data = self.mai.total_list.by_level_list()
                if level not in level_data or not level_data[level]:
                    await self._send_text(stream_id, f'没有找到 Lv{level} 的乐曲。')
                    return True, '无结果', True
                png = self.srender.draw_rating_table(level, level_data, level_text=True,
                                                     bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return True, '查询完成', True
            except Exception:  # noqa: BLE001 - 源渲染失败回退列表图
                pass
        rows_data: List[Tuple[Music, int]] = []
        for m in self.mai.total_list:
            if m.is_utage:
                continue
            for i, lv in enumerate(m.level):
                if lv == level:
                    rows_data.append((m, i))
        if not rows_data:
            await self._send_text(stream_id, f'没有找到 Lv{level} 的乐曲。')
            return True, '无结果', True
        rows_data.sort(key=lambda x: x[0].ds_at(x[1]) or 0, reverse=True)
        rows = [f'「{m.id}」「{mai_extra.DIFFS[i]}」「{m.ds_at(i):.1f}」 {m.title}'
                for m, i in rows_data]
        per = self.config.display.songs_per_page
        page_rows, page, total_pages = paginate(rows, 1, per)
        await self._send_list(stream_id, f'Lv{level} 定数表（{len(rows)} 首）',
                              page_rows, page, total_pages, len(rows))
        return True, '查询完成', True

    # ---------- 命令：等级完成表 ----------

    @Command(
        'maimaidx_level_table',
        description='等级完成表（如：14ap完成表 / 14完成表）',
        pattern=r'(?<!\S)/?(?P<level>[0-9]+\+?)(?P<plan>ap\+|ap|fcp|fc)?完成表\s*$',
    )
    async def cmd_level_table(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        g = kwargs.get('matched_groups') or {}
        level = str(g.get('level') or '')
        plan = str(g.get('plan') or '').lower()
        isfc = plan in ('ap', 'ap+', 'fcp', 'fc')
        if level not in mai_extra.LEVEL_LIST:
            await self._send_text(stream_id, '无法识别的定数')
            return True, '无法识别', True
        if mai_extra.LEVEL_LIST.index(level) < 6:
            await self._send_text(stream_id, '只支持查询lv7-15的完成表')
            return True, '等级过低', True
        if not self.srender or not self._image_enabled():
            await self._send_text(
                stream_id,
                '完成表需要官方素材包支持，请配置 assets_dir 后使用（详见 README）。',
            )
            return True, '无素材', True
        qqid, username, display = self._parse_user_target('', kwargs)
        if not qqid and not username:
            await self._send_text(stream_id, '请在水鱼查分器绑定 QQ 后使用「14完成表」。')
            return True, '无目标用户', True
        try:
            records = await self._fetch_verlist(qqid, username)
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        try:
            level_data = self.mai.total_list.by_level_list()
            png = self.srender.draw_rating_table(
                level, level_data, records, plan=isfc, level_text=False,
                bot_name=self.config.display.bot_name)
            if await self._send_image(stream_id, png):
                return True, '查询完成', True
        except Exception as e:  # noqa: BLE001
            await self._send_text(stream_id, f'完成表渲染失败：{e}')
            return True, '渲染失败', True
        return True, '查询完成', True

    # ---------- 命令：牌子完成表 ----------

    @Command(
        'maimaidx_plate_table',
        description='版本牌子完成表（如：爽将完成表 / 真極完成表）',
        pattern=(
            r'(?<!\S)/?(?P<ver>[真超檄橙暁晓桃櫻樱紫菫堇白雪輝辉舞霸熊華华爽煌星宙祭祝双宴镜彩])'
            r'(?P<plan>極|极|将|神|舞舞)完成表\s*$'
        ),
    )
    async def cmd_plate_table(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        if not self.mai.plate_loaded:
            await self._send_text(stream_id, '牌子数据未加载，请先发送「maimai更新数据」。')
            return True, '牌子数据缺失', True
        g = kwargs.get('matched_groups') or {}
        ver_char = mai_extra.PLATE_CN.get(g.get('ver', ''), g.get('ver', ''))
        plan = str(g.get('plan') or '')
        if f'{ver_char}{plan}' == '真将':
            await self._send_text(stream_id, '真系没有真将哦')
            return True, '无此牌子', True
        if not self.srender or not self._image_enabled():
            await self._send_text(
                stream_id,
                '完成表需要官方素材包支持，请配置 assets_dir 后使用（详见 README）。',
            )
            return True, '无素材', True
        entry = mai_extra.VERSION_MAP.get(ver_char)
        if not entry:
            await self._send_text(stream_id, f'无法识别的牌子「{ver_char}」')
            return True, '无法识别', True
        ver, key = entry
        qqid, username, _display = self._parse_user_target('', kwargs)
        if not qqid and not username:
            await self._send_text(stream_id, '请在水鱼查分器绑定 QQ 后使用「爽将完成表」。')
            return True, '无目标用户', True
        plate_ids = self.mai.total_plate_id_list.get(key, [])
        if not plate_ids:
            await self._send_text(stream_id, f'未找到「{ver_char}{plan}」的牌子数据。')
            return True, '无牌子数据', True
        try:
            records = [PlayRecord.model_validate(x) for x in
                       await self.api.query_user_plate(qqid=qqid, username=username, version=ver)]
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        try:
            remaster_ids = self.mai.total_plate_id_list.get('舞ReMASTER', [])
            png = self.srender.draw_plate_table(
                ver_char, plan, key, plate_ids, remaster_ids, records, self.mai.total_list,
                bot_name=self.config.display.bot_name)
            if await self._send_image(stream_id, png):
                return True, '查询完成', True
        except Exception as e:  # noqa: BLE001
            await self._send_text(stream_id, f'完成表渲染失败：{e}')
            return True, '渲染失败', True
        return True, '查询完成', True

    # ---------- 命令：我要上分 ----------

    @Command(
        'maimaidx_rise',
        description='基于 B50 的推分建议（我要上10分）',
        pattern=r'(?<!\S)/?我要在?(?:上|加|\+)?(?P<target>[0-9]*)分\s*$',
    )
    async def cmd_rise(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        qqid = _to_int(kwargs.get('user_id'))
        if not qqid:
            await self._send_text(stream_id, '请在水鱼查分器绑定 QQ 后使用「我要上分」。')
            return True, '无QQ', True
        try:
            user = await self.api.query_user_b50(qqid=qqid)
        except MaimaiError as e:
            await self._send_text(stream_id, f'查询失败：{e}')
            return True, '查询失败', True
        charts = user.charts
        records = (charts.sd if charts else []) + (charts.dx if charts else [])
        suggestions = []
        for c in records:
            tier = mai_extra.next_tier_ach(c.achievements)
            if tier is None:
                continue
            gain = mai_extra.compute_ra(c.ds, tier) - c.ra
            if gain > 0:
                suggestions.append((c, tier, gain))
        if not suggestions:
            await self._send_text(stream_id, '您的 B50 已经全部推满，去找新歌突破吧！')
            return True, '无建议', True
        suggestions.sort(key=lambda x: x[2], reverse=True)
        total_gain = sum(g for _, _, g in suggestions)
        target = _to_int((kwargs.get('matched_groups') or {}).get('target'))
        picked: List[Tuple[PlayChart, float, int]] = []
        if target:
            acc = 0
            for item in suggestions:
                picked.append(item)
                acc += item[2]
                if acc >= target:
                    break
            note = f'按此顺序推分预计共 +{acc} Ra' + ('，可达成目标' if acc >= target else f'，尚不足 {target}，还需突破 B50 以外的曲目')
        else:
            picked = suggestions[:10]
            note = f'全部推满预计共 +{total_gain} Ra'
        rows = [
            f'《{c.title}》[Lv{c.level}·{c.ds:.1f}] {c.achievements:.4f}% → {tier:g}%  Ra +{gain}'
            for c, tier, gain in picked
        ]
        header = f'{user.nickname or user.username} 的推分建议'
        await self._send_list(stream_id, header, rows, 1, 1, len(rows))
        await self._send_text(stream_id, note)
        return True, '查询完成', True

    # ---------- 命令：别名投票 ----------

    @Command(
        'maimaidx_alias_add',
        description='提交别名申请（添加别名 曲目ID或歌名 别名）',
        pattern=r'(?<!\S)/?添加别名\s+(?P<args>.+?)\s*$',
    )
    async def cmd_alias_add(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        args = str((kwargs.get('matched_groups') or {}).get('args') or '').strip().split(None, 1)
        if len(args) < 2:
            await self._send_text(stream_id, '命令格式：添加别名 「曲目ID或歌名」 「别名」')
            return True, '参数不足', True
        music, candidates, note = await self._resolve_song(args[0])
        if not music:
            if candidates:
                await self._send_candidates(stream_id, candidates, note)
            else:
                await self._send_text(stream_id, f'没有找到乐曲「{args[0]}」。')
            return True, '未找到曲目', True
        alias_name = args[1].strip()
        try:
            result = await self.api.post_alias(
                int(music.id), alias_name,
                user_id=str(kwargs.get('user_id') or ''),
                group_id=str(kwargs.get('group_id') or ''),
                ws_uuid=self._ws_uuid,
            )
        except MaimaiError as e:
            await self._send_text(stream_id, f'提交失败：{e}')
            return True, '提交失败', True
        if isinstance(result, str) and result:
            await self._send_text(stream_id, result)
        else:
            await self._send_text(
                stream_id,
                f'已提交别名申请：《{music.title}》→「{alias_name}」，等待投票通过。',
            )
        return True, '已提交', True

    @Command(
        'maimaidx_alias_agree',
        description='给进行中的别名投票（同意别名 Tag）',
        pattern=r'(?<!\S)/?同意别名\s+(?P<tag>.+?)\s*$',
    )
    async def cmd_alias_agree(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        tag = str((kwargs.get('matched_groups') or {}).get('tag') or '').strip()
        if not tag:
            await self._send_text(stream_id, '命令格式：同意别名 Tag（Tag 见别名投票推送）')
            return True, '参数为空', True
        try:
            result = await self.api.agree_alias(tag, str(kwargs.get('user_id') or ''))
        except MaimaiError as e:
            await self._send_text(stream_id, f'投票失败：{e}')
            return True, '投票失败', True
        if isinstance(result, str) and result:
            await self._send_text(stream_id, result)
        else:
            await self._send_text(stream_id, '投票成功！')
        return True, '已投票', True

    # ---------- 命令：猜歌游戏 ----------

    @Command(
        'maimaidx_guess_start',
        description='开始猜歌（文字提示版）',
        pattern=r'(?<!\S)/?(?:开始猜歌|猜歌)\s*$',
    )
    async def cmd_guess_start(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        game = self._reserve_guess(stream_id)
        if game is None:
            await self._send_text(
                stream_id, '猜歌已经在进行中啦，直接发送「答案 歌名」作答，或「结束猜歌」放弃。')
            return True, '进行中', True
        pool = self.mai.guess_pool()
        if not pool:
            self._end_guess(stream_id)
            await self._send_text(stream_id, '猜歌曲池为空，请先发送「maimai更新数据」。')
            return True, '曲池为空', True
        music = random.choice(pool)
        self._commit_guess(stream_id, game, music, 'hint')
        hints = mai_guess.build_hints(music)
        lines = ['♪ 猜歌开始！根据提示猜猜这是哪首歌：']
        lines += [f'{i}. 这首曲子{h}' for i, h in enumerate(hints, 1)]
        lines.append(f'※ 发送「答案 歌名」作答（也支持「答案是歌名」「答案：歌名」，可用别名/曲名/ID），'
                     f'{self.GUESS_TIMEOUT // 60} 分钟内未猜出自动公布；「结束猜歌」放弃。')
        await self._send_text(stream_id, '\n'.join(lines))
        return True, '已开始', True

    @Command(
        'maimaidx_guess_pic_start',
        description='开始猜曲绘（图片版）',
        pattern=r'(?<!\S)/?(?:开始猜曲绘|猜曲绘)\s*$',
    )
    async def cmd_guess_pic_start(self, **kwargs):
        return await self._cmd_guess_pic(kwargs, grayscale=False)

    @Command(
        'maimaidx_guess_bw_start',
        description='开始猜黑白曲绘（图片版，黑白处理）',
        pattern=r'(?<!\S)/?(?:开始猜黑白曲绘|猜黑白曲绘|开始黑白猜曲绘|黑白猜曲绘)\s*$',
    )
    async def cmd_guess_bw_start(self, **kwargs):
        return await self._cmd_guess_pic(kwargs, grayscale=True)

    async def _cmd_guess_pic(self, kwargs: Dict[str, Any], grayscale: bool) -> Tuple[bool, str, bool]:
        stream_id = str(kwargs.get('stream_id') or '')
        label = '猜黑白曲绘' if grayscale else '猜曲绘'
        mode = 'pic_bw' if grayscale else 'pic'
        if not await self._wait_ready() or not self._data_ready():
            await self._send_data_error(stream_id)
            return True, '数据未加载', True
        game = self._reserve_guess(stream_id)
        if game is None:
            await self._send_text(
                stream_id, '猜歌已经在进行中啦，直接发送「答案 歌名」作答，或「结束猜歌」放弃。')
            return True, '进行中', True
        pool = self.mai.guess_pool()
        if not pool:
            self._end_guess(stream_id)
            await self._send_text(stream_id, '猜歌曲池为空，请先发送「maimai更新数据」。')
            return True, '曲池为空', True
        music = random.choice(pool)
        cover = await self.mai.get_cover(music.id)
        png = mai_guess.crop_cover(cover, grayscale=grayscale) if cover else None
        if not png:
            self._end_guess(stream_id)   # 下载失败释放占位，允许重新开始
            await self._send_text(stream_id, '曲绘获取失败，稍后再试，或先用「开始猜歌」玩文字版。')
            return True, '曲绘失败', True
        self._commit_guess(stream_id, game, music, mode)
        await self._send_image(stream_id, png)
        desc = '这是某首乐曲曲绘的一部分（黑白处理）。' if grayscale else '这是某首乐曲曲绘的一部分。'
        await self._send_text(
            stream_id,
            f'♪ {label}开始！{desc}\n'
            f'※ 发送「答案 歌名」作答（也支持「答案是歌名」「答案：歌名」，可用别名/曲名/ID），'
            f'{self.GUESS_TIMEOUT // 60} 分钟内未猜出自动公布；「结束猜歌」放弃。',
        )
        return True, '已开始', True

    @Command(
        'maimaidx_guess_answer',
        description='猜歌答题（答案 歌名 / 答案是歌名 / 答案：歌名）',
        pattern=r'(?<!\S)/?答案\s*(?:[:：]\s*)?(?:是\s*)?(?:[:：]\s*)?(?P<answer>.+?)\s*$',
    )
    async def cmd_guess_answer(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready() or not self._data_ready():
            return True, '数据未加载', True
        game = self.guess_games.get(stream_id)
        if not game:
            await self._send_text(
                stream_id, '当前没有进行中的猜歌，发送「猜歌」（文字提示）或「猜曲绘」（图片）开始一轮。')
            return True, '无游戏', True
        answer = str((kwargs.get('matched_groups') or {}).get('answer') or '').strip()
        if answer in ('', '是', '：', ':'):
            await self._send_text(
                stream_id, '请在「答案」后面写上歌曲名，如：答案 琪露诺 / 答案是琪露诺 / 答案：琪露诺')
            return True, '参数为空', True
        music: Optional[Music] = game.get('music')
        if music is None:
            await self._send_text(stream_id, '本轮猜歌正在准备中，请稍候再作答～')
            return True, '准备中', True
        game['attempts'] += 1
        if mai_guess.check_answer(music, self.mai.total_alias_list.aliases_of(int(music.id)), answer):
            self._end_guess(stream_id)
            await self._send_text(
                stream_id,
                f'🎉 答对了！正确答案：《{music.title}》（ID {music.id}），'
                f'共猜了 {game["attempts"]} 次。',
            )
            await self._send_song_info(stream_id, music)
            return True, '答对', True
        await self._send_text(stream_id, f'猜错了哦，再想想～（第 {game["attempts"]} 次作答）')
        return True, '答错', True

    @Command(
        'maimaidx_guess_end',
        description='结束当前猜歌并公布答案',
        pattern=r'(?<!\S)/?(?:结束猜歌|放弃猜歌)\s*$',
    )
    async def cmd_guess_end(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if not await self._wait_ready():
            return True, '未就绪', True
        game = self._end_guess(stream_id)
        if not game:
            await self._send_text(stream_id, '当前没有进行中的猜歌。')
            return True, '无游戏', True
        music: Optional[Music] = game.get('music')
        if music is None:
            await self._send_text(stream_id, '本轮猜歌已取消。')
            return True, '已取消', True
        await self._send_text(
            stream_id,
            f'猜歌已结束，正确答案是：《{music.title}》（ID {music.id}）',
        )
        await self._send_song_info(stream_id, music)
        return True, '已结束', True

    # ---------- 命令：帮助菜单 ----------

    @Command(
        'maimaidx_help',
        description='maimaiDX 查分帮助菜单',
        pattern=r'(?<!\S)/?(?:[mM][aA][iI][hH][eE][lL][pP]|maihelp|mai帮助|maimai帮助|查分帮助)\s*$',
    )
    async def cmd_help(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        if self.srender is not None and self._image_enabled():
            try:
                png = self.srender.draw_help(
                    HELP_SECTIONS, bot_name=self.config.display.bot_name)
                if await self._send_image(stream_id, png):
                    return True, '已发送帮助', True
            except Exception:  # noqa: BLE001 - 源渲染失败回退
                pass
        if self._image_enabled():
            try:
                png = mai_render.help_image()
                if png and await self._send_image(stream_id, png):
                    return True, '已发送帮助', True
            except Exception:  # noqa: BLE001
                pass
        await self._send_text(stream_id, _HELP_TEXT)
        return True, '已发送帮助', True

    # ---------- 命令：更新数据 ----------

    @Command(
        'maimaidx_refresh',
        description='刷新 maimai 曲库/别名数据',
        pattern=r'(?<!\S)/?(?:maimai更新数据|maimaidx更新数据|更新maimai数据)\s*$',
    )
    async def cmd_refresh(self, **kwargs):
        stream_id = str(kwargs.get('stream_id') or '')
        now = time.time()
        if now - self._last_refresh < 60:
            await self._send_text(stream_id, '刚刚更新过啦，休息一下再试。')
            return True, '冷却中', True
        if not self.api:
            await self._send_data_error(stream_id)
            return True, '未初始化', True
        self._last_refresh = now
        try:
            assert self.mai is not None
            await self.mai.load_music()
            try:
                await self.mai.load_alias()
            except MaimaiError as e:
                self.ctx.logger.warning('maimaidx 别名刷新失败: %s', e)
            try:
                await self.mai.load_plate()
            except MaimaiError as e:
                self.ctx.logger.warning('maimaidx 牌子数据刷新失败: %s', e)
            for kind in ('artist', 'charter'):
                try:
                    await self.mai.load_name_aliases(kind)
                except Exception:  # noqa: BLE001
                    continue
            await self._send_text(
                stream_id,
                f'maimai 数据更新完成：{len(self.mai.total_list)} 首曲目，'
                f'{len(self.mai.total_alias_list)} 条别名，'
                f'{len(self.mai.total_plate_id_list)} 个版本牌子表。',
            )
            return True, '更新完成', True
        except Exception as e:  # noqa: BLE001
            await self._send_text(stream_id, f'maimai 数据更新失败：{e}')
            return True, '更新失败', True

    # ---------- LLM 工具 ----------

    if Tool is not None:

        @Tool(
            'maimaidx_song_info',
            brief_description='查询 maimai DX 曲目详情（定数、拟合定数、版本、难度、曲师、谱师）',
            detailed_description=(
                '查询 maimai DX 单曲的详细信息，包括各难度的歌曲定数(ds)、全体玩家拟合定数(fit_diff)、'
                '等级、谱师(charter)，以及曲师(artist)、分类、BPM、收录版本。\n'
                '参数 song_id 与 name 至少提供一个：song_id 为曲目数字ID，优先使用；'
                'name 为曲名或别名。\n'
                '仅在用户明确询问某首乐曲的定数、曲师、谱师、版本等信息时调用。'
            ),
            parameters=[
                ToolParameterInfo(name='song_id', param_type=ToolParamType.STRING,
                                  description='曲目数字ID，如 11086', required=False),
                ToolParameterInfo(name='name', param_type=ToolParamType.STRING,
                                  description='曲名或别名', required=False),
            ],
        )
        async def tool_song_info(self, song_id: str = '', name: str = '', **kwargs):
            if not self._data_ready():
                return {'content': 'maimai 曲库数据尚未加载完成，暂时无法查询。'}
            music: Optional[Music] = None
            if str(song_id).strip().isdigit():
                music = self.mai.total_list.by_id(str(song_id).strip())
            if not music and str(name).strip():
                music, candidates, note = await self._resolve_song(str(name))
                if not music and candidates:
                    listing = '；'.join(f'{m.id}:{m.title}' for m in candidates[:10])
                    return {'content': f'{note}，请让用户指定曲目ID：{listing}'}
                if not music:
                    return {'content': f'没有找到乐曲「{name}」' + (f'（{note}）' if note else '')}
            if not music:
                return {'content': '请提供曲目ID或曲名。'}
            return {'content': format_song_info(
                music, self.mai.total_alias_list.aliases_of(int(music.id)))}

        @Tool(
            'maimaidx_search_songs',
            brief_description='按定数/拟合定数/曲师/谱师/关键词搜索 maimai 乐曲列表',
            detailed_description=(
                '搜索 maimai DX 乐曲，返回命中的曲目列表（ID、标题、难度、定数、拟合定数、曲师）。\n'
                '各筛选条件可选：keyword 按曲名/别名；artist 按曲师；charter 按谱师；'
                'ds_min/ds_max 按歌曲定数区间；fit_min/fit_max 按拟合定数区间；'
                'difficulty 可选 Basic/Advanced/Expert/Master/Re:Master；多个条件为"并且"关系。\n'
                '仅在用户明确要求搜索/筛选乐曲（如"查一下定数13.5到14的歌"）时调用。'
            ),
            parameters=[
                ToolParameterInfo(name='keyword', param_type=ToolParamType.STRING,
                                  description='曲名或别名关键词', required=False),
                ToolParameterInfo(name='artist', param_type=ToolParamType.STRING,
                                  description='曲师名称关键词', required=False),
                ToolParameterInfo(name='charter', param_type=ToolParamType.STRING,
                                  description='谱师名称关键词', required=False),
                ToolParameterInfo(name='ds_min', param_type=ToolParamType.NUMBER,
                                  description='定数下限', required=False),
                ToolParameterInfo(name='ds_max', param_type=ToolParamType.NUMBER,
                                  description='定数上限', required=False),
                ToolParameterInfo(name='fit_min', param_type=ToolParamType.NUMBER,
                                  description='拟合定数下限', required=False),
                ToolParameterInfo(name='fit_max', param_type=ToolParamType.NUMBER,
                                  description='拟合定数上限', required=False),
                ToolParameterInfo(name='difficulty', param_type=ToolParamType.STRING,
                                  description='难度名：Basic/Advanced/Expert/Master/Re:Master',
                                  required=False,
                                  enum_values=['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master']),
                ToolParameterInfo(name='limit', param_type=ToolParamType.INTEGER,
                                  description='返回条数上限，默认 15', required=False, default=15),
            ],
        )
        async def tool_search_songs(
            self,
            keyword: str = '',
            artist: str = '',
            charter: str = '',
            ds_min: float = None,
            ds_max: float = None,
            fit_min: float = None,
            fit_max: float = None,
            difficulty: str = '',
            limit: int = 15,
            **kwargs,
        ):
            if not self._data_ready():
                return {'content': 'maimai 曲库数据尚未加载完成，暂时无法查询。'}
            limit = max(1, min(_to_int(limit) or 15, 50))
            total = self.mai.total_list
            results: List[Tuple[Music, int]] = []
            if ds_min is not None or ds_max is not None:
                low = float(ds_min) if ds_min is not None else 1.0
                high = float(ds_max) if ds_max is not None else 16.0
                if low > high:
                    low, high = high, low
                results = list(total.by_ds(low, high))
            elif fit_min is not None or fit_max is not None:
                low = float(fit_min) if fit_min is not None else 1.0
                high = float(fit_max) if fit_max is not None else 16.0
                if low > high:
                    low, high = high, low
                results = [(m, i) for m, i, _ in total.by_fit(low, high)]
            else:
                kw = str(keyword).strip().lower()
                pool_ids: Optional[set] = None
                if kw:
                    pool_ids = ({m.id for m in total.by_title(kw)}
                                | {str(a.SongID) for a in self.mai.total_alias_list.by_alias(kw)})
                for m in sorted(total, key=lambda x: int(x.id) if x.id.isdigit() else 10 ** 9):
                    if pool_ids is not None and m.id not in pool_ids:
                        continue
                    for i in range(len(m.ds)):
                        results.append((m, i))
            diff_idx = DIFF_INDEX.get(str(difficulty).strip().lower())
            if diff_idx is not None:
                results = [(m, i) for m, i in results if i == diff_idx]
            if str(artist).strip():
                allowed = {m.id for m in total.by_artist(str(artist))}
                results = [(m, i) for m, i in results if m.id in allowed]
            if str(charter).strip():
                ckw = str(charter).strip().lower()
                results = [(m, i) for m, i in results
                           if i < len(m.charts) and ckw in (m.charts[i].charter or '').lower()]
            if not results:
                return {'content': '没有符合条件的乐曲。'}
            lines = [f'共 {len(results)} 条（最多展示 {limit} 条）：']
            for m, i in results[:limit]:
                lv = m.level[i] if i < len(m.level) else '-'
                fit = m.fit_diff(i)
                lines.append(f'ID {m.id}｜{_diff_label(i)} Lv{lv}｜定数 {_fmt(m.ds_at(i))}｜'
                             f'拟合 {_fmt(fit, 2)}｜{m.title}（曲师: {m.artist}）')
            if len(results) > limit:
                lines.append(f'……其余 {len(results) - limit} 条已省略，可用更精确的条件再查。')
            return {'content': '\n'.join(lines)}

        @Tool(
            'maimaidx_player_b50',
            brief_description='查询水鱼查分器玩家 B50 成绩概要（Rating、最佳成绩）',
            detailed_description=(
                '通过水鱼查分器查询玩家的 B50 成绩概要：Rating、DX Rating、B35/B15 前几名成绩。\n'
                'username 为查分器用户名，qq 为玩家QQ号（玩家需在查分器绑定并允许查询），二选一。\n'
                '仅在用户明确要求查询成绩/Rating 时调用，不要在闲聊中调用。'
            ),
            parameters=[
                ToolParameterInfo(name='username', param_type=ToolParamType.STRING,
                                  description='查分器用户名', required=False),
                ToolParameterInfo(name='qq', param_type=ToolParamType.STRING,
                                  description='玩家QQ号', required=False),
            ],
        )
        async def tool_player_b50(self, username: str = '', qq: str = '', **kwargs):
            if not self.api:
                return {'content': 'maimaidx 插件尚未初始化完成。'}
            qqid = _to_int(qq)
            if not qqid and not str(username).strip():
                return {'content': '请提供查分器用户名或玩家QQ号。'}
            try:
                user = await self.api.query_user_b50(
                    qqid=qqid, username=str(username).strip() or None)
            except MaimaiError as e:
                return {'content': f'查询失败：{e}'}
            except Exception as e:  # noqa: BLE001
                return {'content': f'查询失败：网络错误（{e}）'}
            lines = [
                f'{user.nickname or user.username}｜Rating: {user.rating}｜'
                f'DX Rating: {user.additional_rating}',
            ]
            charts = user.charts
            if charts and charts.sd:
                lines.append('B35 前5：')
                for c in charts.sd[:5]:
                    lines.append(f'{c.achievements:.4f}% Ra{c.ra} [{c.level}] {c.title}')
            if charts and charts.dx:
                lines.append('B15 前5：')
                for c in charts.dx[:5]:
                    lines.append(f'{c.achievements:.4f}% Ra{c.ra} [{c.level}] {c.title}')
            return {'content': '\n'.join(lines)}


def _diff_label(index: int) -> str:
    return DIFF_NAMES[index] if 0 <= index < len(DIFF_NAMES) else f'Diff{index}'


def _fmt(value: Optional[float], nd: int = 1) -> str:
    return '-' if value is None else f'{value:.{nd}f}'


def _to_int(value: Any) -> Optional[int]:
    try:
        text = str(value).strip()
        return int(text) if text.isdigit() else None
    except Exception:  # noqa: BLE001
        return None


def fmt_range(low: float, high: float) -> str:
    if low == high:
        return f'{low:g}'
    return f'{low:g}~{high:g}'


def create_plugin() -> MaimaidxPlugin:
    """Runner 加载入口。"""
    return MaimaidxPlugin()


# 给所有命令处理器挂上访问控制（保留组件元数据，LLM 工具不做命令级限制）
for _name, _obj in list(vars(MaimaidxPlugin).items()):
    if _name.startswith('cmd_') and callable(_obj) and hasattr(_obj, '__maibot_component_info__'):
        setattr(MaimaidxPlugin, _name, MaimaidxPlugin._access_wrap(_obj))
