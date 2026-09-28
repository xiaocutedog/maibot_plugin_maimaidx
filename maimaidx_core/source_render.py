"""源插件（nonebot-plugin-maimaidx 新版 core/image/*）渲染逻辑 1:1 移植。

配套官方素材包 Resource CN 1.55+（static/font、static/mai/{pic,cover,plate_version,shougou}）。
布局、坐标、素材与源插件一致；唯一差异：文字过长时自动缩小字号完整显示（源插件为
截断加 "..."），极长文本才回退截断。

实现并暴露五类渲染：
- song_chart_info  —— id 指令谱面信息卡（含宴会场变体）
- song_play_data   —— minfo 指令谱面游玩数据
- draw_b50         —— b50 成绩单
- 定数表            —— render_rating_table_bg + draw_rating_table（level_text/plain/完成表）
- 完成表            —— render_plate_table_bg + draw_plate_table / draw_plate_progress
"""

import base64
import math
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .extra import LEVEL_LIST, PLATE_CN, VERSION_MAP
from .model import Music, PlayChart, PlayRecord, UserInfo

# ---------- 常量（与源插件 constants.py 一致） ----------

RANK_SP = ['d', 'c', 'b', 'bb', 'bbb', 'a', 'aa', 'aaa', 's', 'sp', 'ss', 'ssp', 'sss', 'sssp']
RANK_MAP = {k: (k[:-1].upper() + 'p' if k.endswith('p') else k.upper()) for k in RANK_SP}
COMBO_SP = ['fc', 'fcp', 'ap', 'app']
COMBO_MAP = {k: (k.upper()[:-1] + 'p' if len(k) > 2 and k.endswith('p') else k.upper()) for k in COMBO_SP}
SYNC_D_SP = ['fs', 'fsp', 'fsd', 'fsdp']
SYNC_MAP = {'fs': 'FS', 'fsp': 'FSp', 'fsd': 'FSD', 'fdx': 'FSD', 'fsdp': 'FSDp', 'fdxp': 'FSDp', 'sync': 'Sync'}
DIFFS = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master']
ACHIEVEMENT_LIST = [50.0, 60.0, 70.0, 75.0, 80.0, 90.0, 94.0, 97.0, 98.0, 99.0, 99.5, 100.0, 100.5]
BASE_RA_SPP = [7.0, 8.0, 9.6, 11.2, 12.0, 13.6, 15.2, 16.8, 20.0, 20.3, 20.8, 21.1, 21.6, 22.4]
STATISTICS_KEYS = ['clear', 's', 'sp', 'ss', 'ssp', 'sss', 'sssp', 'sync',
                   'fc', 'fcp', 'ap', 'app', 'fs', 'fsp', 'fsd', 'fsdp']
CATEGORY = {
    '流行&动漫': 'anime', '舞萌': 'maimai', 'niconico & VOCALOID': 'niconico',
    '东方Project': 'touhou', '其他游戏': 'game', '音击&中二节奏': 'ongeki',
    'POPSアニメ': 'anime', 'maimai': 'maimai', 'niconicoボーカロイド': 'niconico',
    '東方Project': 'touhou', 'ゲームバラエティ': 'game', 'オンゲキCHUNITHM': 'ongeki',
    '宴会場': '宴会场',
}
THEMES = {'circle': 'circle', 'prism_plus': 'prism_plus'}
NOTE_FIELDS = ['total', 'tap', 'hold', 'slide', 'touch', 'brk']


class SourceRenderError(Exception):
    """素材缺失等渲染环境错误。"""


# ---------- 计算函数（与源插件 utils/calc.py 一致） ----------


def compute_rating(ds: float, achievement: float, *, onlyrate: bool = False, israte: bool = False):
    if achievement < 50:
        base_ra, rate = 7.0, 'd'
    elif achievement < 60:
        base_ra, rate = 8.0, 'c'
    elif achievement < 70:
        base_ra, rate = 9.6, 'b'
    elif achievement < 75:
        base_ra, rate = 11.2, 'bb'
    elif achievement < 80:
        base_ra, rate = 12.0, 'bbb'
    elif achievement < 90:
        base_ra, rate = 13.6, 'a'
    elif achievement < 94:
        base_ra, rate = 15.2, 'aa'
    elif achievement < 97:
        base_ra, rate = 16.8, 'aaa'
    elif achievement < 98:
        base_ra, rate = 20.0, 's'
    elif achievement < 99:
        base_ra, rate = 20.3, 'sp'
    elif achievement < 99.5:
        base_ra, rate = 20.8, 'ss'
    elif achievement < 100:
        base_ra, rate = 21.1, 'ssp'
    elif achievement < 100.5:
        base_ra, rate = 21.6, 'sss'
    else:
        base_ra, rate = 22.4, 'sssp'

    value = math.floor(ds * (min(100.5, achievement) / 100) * base_ra)
    if israte:
        return (value, rate)
    if onlyrate:
        return rate
    return value


def dx_score(dx: float) -> int:
    if dx < 85:
        return 0
    if dx < 90:
        return 1
    if dx < 93:
        return 2
    if dx < 95:
        return 3
    if dx < 97:
        return 4
    return 5


# ---------- 工具（与源插件 base.py / tools.py 一致） ----------


def get_char_width(o: int) -> int:
    widths = [
        (126, 1), (159, 0), (687, 1), (710, 0), (711, 1), (727, 0), (733, 1), (879, 0), (1154, 1), (1161, 0),
        (4347, 1), (4447, 2), (7467, 1), (7521, 0), (8369, 1), (8426, 0), (9000, 1), (9002, 2), (11021, 1),
        (12350, 2), (12351, 1), (12438, 2), (12442, 0), (19893, 2), (19967, 1), (55203, 2), (63743, 1),
        (64106, 2), (65039, 1), (65059, 0), (65131, 2), (65279, 1), (65376, 2), (65500, 1), (65510, 2),
        (120831, 1), (262141, 2), (1114109, 1),
    ]
    if o == 0xE or o == 0xF:
        return 0
    for num, wid in widths:
        if o <= num:
            return wid
    return 1


def coloum_width(s: str) -> int:
    res = 0
    for ch in s:
        res += get_char_width(ord(ch))
    return res


def change_column_width(s: str, length: int) -> str:
    res = 0
    out = []
    for ch in s:
        res += get_char_width(ord(ch))
        if res <= length:
            out.append(ch)
    return ''.join(out)


def _hex_to_rgb(hex_str: str) -> Tuple[int, ...]:
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))


def tricolor_gradient_prism_plus(width: int, height: int) -> Image.Image:
    colors_list = [
        (0.0, _hex_to_rgb('#ffffff')),
        (0.14, _hex_to_rgb('#ffffff')),
        (0.24, _hex_to_rgb('#ffd5cf')),
        (0.46, _hex_to_rgb('#ffd5cf')),
        (0.56, _hex_to_rgb('#ffc5d5')),
        (0.67, _hex_to_rgb('#eaabff')),
        (0.85, _hex_to_rgb('#72bcfe')),
        (0.95, _hex_to_rgb('#65f2df')),
        (1.0, _hex_to_rgb('#65f2df')),
    ]
    line = Image.new('RGBA', (1, height))
    for y in range(height):
        t = 1.0 - (y / (height - 1)) if height > 1 else 0
        for i in range(len(colors_list) - 1):
            p1, c1 = colors_list[i]
            p2, c2 = colors_list[i + 1]
            if p1 <= t <= p2:
                rel_t = (t - p1) / (p2 - p1)
                rgb = tuple(int(c1[j] + (c2[j] - c1[j]) * rel_t) for j in range(3))
                line.putpixel((0, y), rgb + (255,))
                break
    return line.resize((width, height), resample=Image.Resampling.BICUBIC)


def generate_frosted_card(
    im: Image.Image,
    box: Tuple[int, int, int, int],
    shadow_offset: Tuple[int, int] = (10, 10),
    alpha: float = 0.4,
) -> Image.Image:
    roi = im.crop(box)
    roi_w, roi_h = roi.size
    frosted = roi.filter(ImageFilter.GaussianBlur(4))
    white_layer = Image.new('RGBA', (roi_w, roi_h), (255, 255, 255, int(255 * alpha)))
    card = Image.alpha_composite(frosted, white_layer)
    mask = Image.new('L', (roi_w, roi_h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, roi_w, roi_h), radius=25, fill=255)
    shadow_w = roi_w + 5 * 2 + abs(shadow_offset[0])
    shadow_h = roi_h + 5 * 2 + abs(shadow_offset[1])
    shadow = Image.new('RGBA', (shadow_w, shadow_h), (0, 0, 0, 0))
    draw_shadow = ImageDraw.Draw(shadow)
    draw_shadow.rounded_rectangle((15, 15, 15 + roi_w, 15 + roi_h), radius=25, fill=(0, 0, 0, 50))
    shadow_layer = shadow.filter(ImageFilter.GaussianBlur(3))
    temp_layer = Image.new('RGBA', im.size, (0, 0, 0, 0))
    shadow_pos = (box[0] + shadow_offset[0] - 15, box[1] + shadow_offset[1] - 15)
    temp_layer.paste(shadow_layer, shadow_pos)
    temp_layer.paste(card, (box[0], box[1]), mask=mask)
    return Image.alpha_composite(im, temp_layer)


class FontChain:
    """字体回退链：主字体缺字（日文汉字/音符/emoji 等）时逐级换备用字体。"""

    _cmap_cache: Dict[str, Optional[set]] = {}

    # 所有字体都缺的字符 → 用可渲染的同形字符替代
    SUBSTITUTES = {
        '✪': '★', '✯': '★', '✭': '★', '✰': '★', '⭐': '★',
        '❂': '★', '✷': '★', '✶': '★', '✵': '★', '✴': '★',
        '❋': '☆', '❆': '☆', '❅': '☆', '❄': '☆',
        '➤': '→', '➜': '→', '➔': '→', '⇒': '→',
        '♭': 'b', '♯': '#',
    }

    def __init__(self, primary: str, fallbacks: Optional[List[Tuple[str, bool]]] = None) -> None:
        self.primary = str(primary)
        # (字体路径, 是否彩色 emoji 字体)
        self.fallbacks: List[Tuple[str, bool]] = list(fallbacks or [])
        self._fonts: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}

    def _cmap(self, path: str) -> Optional[set]:
        if path not in FontChain._cmap_cache:
            try:
                from fontTools.ttLib import TTFont

                ft = TTFont(path, fontNumber=0, lazy=True)
                FontChain._cmap_cache[path] = set(ft.getBestCmap().keys())
                ft.close()
            except Exception:  # noqa: BLE001 - fontTools 缺失或字体异常时禁用该级回退
                FontChain._cmap_cache[path] = None
        return FontChain._cmap_cache[path]

    def _supports(self, path: str, ch: str) -> bool:
        cm = self._cmap(path)
        return cm is not None and ord(ch) in cm

    def _resolve(self, ch: str) -> Tuple[str, str, bool]:
        """返回 (实际绘制字符, 字体路径, 是否emoji字体)。"""
        if self._supports(self.primary, ch):
            return ch, self.primary, False
        for path, is_emoji in self.fallbacks:
            if self._supports(path, ch):
                return ch, path, is_emoji
        # 所有字体都缺：尝试同形替代字符
        sub = self.SUBSTITUTES.get(ch)
        if sub and sub != ch:
            return self._resolve(sub)
        return ch, self.primary, False

    def _pick(self, ch: str) -> Tuple[str, bool]:
        _char, path, is_emoji = self._resolve(ch)
        return path, is_emoji

    def font(self, size: int, path: str) -> ImageFont.FreeTypeFont:
        key = (path, size)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(path, size)
        return self._fonts[key]

    def segment(self, text: str, size: int) -> List[Tuple[str, bool, str]]:
        """把文本按所用字体切成连续片段：[(片段, 是否emoji字体, 字体路径)]。"""
        runs: List[Tuple[str, bool, str]] = []
        for ch in text:
            dch, path, is_emoji = self._resolve(ch)
            if runs and runs[-1][2] == path:
                runs[-1] = (runs[-1][0] + dch, runs[-1][1], path)
            else:
                runs.append((dch, is_emoji, path))
        return runs

    def run_width(self, run: str, path: str, size: int, draw: ImageDraw.ImageDraw) -> float:
        return draw.textlength(run, font=self.font(size, path))


class DrawText:
    """与源插件一致；draw_fit 超宽时自动缩小字号而非截断；
    缺字字符自动切换回退字体（MiSans / 彩色 emoji 等）。"""

    def __init__(self, image: ImageDraw.ImageDraw, font_path: str,
                 chain: Optional[FontChain] = None) -> None:
        self._img = image
        self._font = str(font_path)
        self._cache: Dict[int, ImageFont.FreeTypeFont] = {}
        self.chain = chain or FontChain(self._font)

    def _f(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._cache:
            self._cache[size] = ImageFont.truetype(self._font, size)
        return self._cache[size]

    def measure(self, text, size: int) -> float:
        text = str(text)
        if len(text) <= 1:
            return self._img.textlength(text, font=self._f(size))
        total = 0.0
        for run, path, fsize in self._runs(text, size):
            total += self._img.textlength(run, font=self.chain.font(fsize, path))
        return total

    def _runs(self, text: str, size: int) -> List[Tuple[str, str, int]]:
        """[(片段, 字体路径, 字号)]，回退字符保持原字号。"""
        out: List[Tuple[str, str, int]] = []
        for run, is_emoji, path in self.chain.segment(text, size):
            out.append((run, path, size))
        return out

    def fit_size(self, text, size: int, max_width: float, min_ratio: float = 0.55) -> int:
        text = str(text)
        if self.measure(text, size) <= max_width:
            return size
        s = size - 1
        floor = max(int(size * min_ratio), 8)
        while s > floor and self.measure(text, s) > max_width:
            s -= 1
        return s

    def draw(
        self,
        pos_x: int,
        pos_y: int,
        size: int,
        text,
        color=(255, 255, 255, 255),
        anchor: str = 'lt',
        stroke_width: int = 0,
        stroke_fill=(0, 0, 0, 0),
        multiline: bool = False,
    ) -> None:
        text = str(text)
        if multiline:
            self._img.multiline_text((pos_x, pos_y), text, color, self._f(size), anchor,
                                     stroke_width=stroke_width, stroke_fill=stroke_fill)
            return
        runs = self._runs(text, size)
        if len(runs) == 1 and runs[0][1] == self._font and runs[0][0] == text:
            # 全部字符主字体可绘制且无替代：整串绘制，保留字距
            self._img.text((pos_x, pos_y), text, color, self._f(size), anchor,
                           stroke_width=stroke_width, stroke_fill=stroke_fill)
            return
        # 混合字体：按片段横向拼接，手动实现水平锚点（垂直锚点沿用原语义）
        widths = [self._img.textlength(run, font=self.chain.font(rsize, path))
                  for run, path, rsize in runs]
        total = sum(widths)
        hz = anchor[0] if len(anchor) >= 2 else 'l'
        vt = anchor[1] if len(anchor) >= 2 else 'a'
        if hz == 'm':
            cursor = pos_x - total / 2
        elif hz == 'r':
            cursor = pos_x - total
        elif hz == 's':
            cursor = pos_x
        else:
            cursor = pos_x
        run_anchor = 'l' + vt
        for (run, path, rsize), w in zip(runs, widths):
            font = self.chain.font(rsize, path)
            is_emoji_font = any(path == fp and flag for fp, flag in self.chain.fallbacks)
            try:
                if is_emoji_font and not stroke_width:
                    self._img.text((cursor, pos_y), run, color, font, run_anchor,
                                   embedded_color=True)
                else:
                    self._img.text((cursor, pos_y), run, color, font, run_anchor,
                                   stroke_width=stroke_width, stroke_fill=stroke_fill)
            except Exception:  # noqa: BLE001 - 个别字体渲染失败时退回主字体
                self._img.text((cursor, pos_y), run, color, self._f(rsize), run_anchor,
                               stroke_width=stroke_width, stroke_fill=stroke_fill)
            cursor += w

    def draw_fit(
        self,
        pos_x: int,
        pos_y: int,
        size: int,
        text,
        max_width: float,
        color=(255, 255, 255, 255),
        anchor: str = 'lt',
        stroke_width: int = 0,
        stroke_fill=(0, 0, 0, 0),
    ) -> None:
        s = self.fit_size(text, size, max_width)
        text = str(text)
        if s <= max(int(size * 0.55), 8) and self.measure(text, s) > max_width:
            budget = max(int(max_width / (s * 0.5) * 2) - 1, 4)
            text = change_column_width(text, budget) + '...'
        self.draw(pos_x, pos_y, s, text, color, anchor, stroke_width, stroke_fill)


# ---------- 渲染器 ----------


class SourceRenderer:
    """加载官方素材（Resource CN 1.55+）并按源插件新版布局绘图。"""

    def __init__(self, static_dir: Path, theme: str = 'prism_plus') -> None:
        import os

        self.static = Path(static_dir)
        if not self.static.is_dir():
            raise SourceRenderError(f'素材目录不存在：{self.static}')
        self.pic = self.static / 'mai' / 'pic'
        self.cover_dir = self.static / 'mai' / 'cover'
        self.font_dir = self.static / 'font'
        self.shougou_dir = self.static / 'mai' / 'shougou'
        self.plate_version_dir = self.static / 'mai' / 'plate_version'
        self.plate_table_dir = self.static / 'mai' / 'plate_table'
        self.rating_table_dir = self.static / 'mai' / 'rating_table'
        for d in (self.plate_table_dir, self.rating_table_dir):
            d.mkdir(parents=True, exist_ok=True)

        if not self.pic.is_dir() or not self.cover_dir.is_dir():
            raise SourceRenderError(f'素材不完整：{self.static}')
        self.font_sy = self.font_dir / 'ResourceHanRoundedCN-Bold.ttf'
        self.font_tb = self.font_dir / 'Torus SemiBold.otf'
        self.font_fot = self.font_dir / 'FOT-NewRodin Pro EB.otf'
        for f in (self.font_sy, self.font_tb, self.font_fot):
            if not f.is_file():
                raise SourceRenderError(f'缺少字体：{f}')

        # 字体回退链：MiSans（用户指定备用字体）→ 系统中日字体 → 彩色 emoji
        self.fallback_fonts: List[Tuple[str, bool]] = []
        misans_candidates = [
            Path(__file__).resolve().parent.parent / 'fonts' / 'MiSans-Regular.ttf',
            self.static / 'font' / 'MiSans-Regular.ttf',
        ]
        for cand in misans_candidates:
            if cand.is_file():
                self.fallback_fonts.append((str(cand), False))
                break
        for sys_cjk in (
            'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyh.ttf',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        ):
            if os.path.exists(sys_cjk):
                self.fallback_fonts.append((sys_cjk, False))
                break
        for sys_emoji in (
            'C:/Windows/Fonts/seguiemj.ttf',
            '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf',
        ):
            if os.path.exists(sys_emoji):
                self.fallback_fonts.append((sys_emoji, True))
                break
        self._chains: Dict[str, FontChain] = {}
        self.theme = THEMES.get(theme, 'prism_plus')
        self._cache: Dict[str, Image.Image] = {}
        self._themed: Dict[str, Image.Image] = {}
        self._load_assets()

    def _chain(self, font_path: Path) -> FontChain:
        key = str(font_path)
        if key not in self._chains:
            fallbacks = [(p, e) for p, e in self.fallback_fonts if p != key]
            self._chains[key] = FontChain(key, fallbacks)
        return self._chains[key]

        self.theme = THEMES.get(theme, 'prism_plus')
        self._cache: Dict[str, Image.Image] = {}
        self._themed: Dict[str, Image.Image] = {}
        self._load_assets()

    # ----- 基础 -----

    def _open(self, path: Path) -> Image.Image:
        with Image.open(path) as image:
            return image.convert('RGBA')

    def _asset(self, name: str) -> Image.Image:
        if name not in self._cache:
            self._cache[name] = self._open(self.pic / name)
        return self._cache[name]

    def _themed_asset(self, name: str) -> Image.Image:
        key = f'{self.theme}/{name}'
        if key not in self._themed:
            self._themed[key] = self._open(self.pic / self.theme / name)
        return self._themed[key]

    def song_chart(self, song_id: Union[int, str]) -> Path:
        song_id = int(song_id) % 10000
        path = self.cover_dir / f'{song_id}.png'
        return path if path.exists() else self.cover_dir / '0.png'

    def _drawers(self, im: Image.Image) -> Tuple[DrawText, DrawText, DrawText]:
        dr = ImageDraw.Draw(im)
        return (DrawText(dr, self.font_sy, self._chain(self.font_sy)),
                DrawText(dr, self.font_tb, self._chain(self.font_tb)),
                DrawText(dr, self.font_fot, self._chain(self.font_fot)))

    def _draw_footer(self, im: Image.Image, bot_name: str, y: int, size: int, color,
                     stroke_width: int = 0, stroke_fill=(0, 0, 0, 0), font: str = 'fot') -> None:
        """底部两行署名：美术作者一行、Bot 一行（自动缩字防溢出）。"""
        fnt = {'sy': 0, 'tb': 1, 'fot': 2}[font]
        drawer = self._drawers(im)[fnt]
        line1 = 'Designed by Yuri-YuzuChaN & BlueDeer233'
        line2 = f'Generated by {bot_name} BOT'
        gap = int(size * 1.4)
        drawer.draw_fit(im.width // 2, y - gap // 2, size, line1, im.width - 40, color, 'mm',
                        stroke_width, stroke_fill)
        drawer.draw_fit(im.width // 2, y + gap // 2, size, line2, im.width - 40, color, 'mm',
                        stroke_width, stroke_fill)

    def _while_score_cards(self, im: Image.Image, data: List[PlayChart], list_y: int,
                           service: str = '', bot_name: str = 'MaiBot', total_list=None) -> None:
        """B50 同款成绩卡网格（b50 / 等级进度共用）。"""
        sy, tb, _fn = self._drawers(im)
        gap, dx_step, start_x = 114, 276, 16
        for num, info in enumerate(data):
            row, col = divmod(num, 5)
            x = start_x + col * dx_step
            y = list_y + row * gap

            cover = self._open(self.song_chart(info.song_id)).resize((75, 75))
            rate_name = RANK_MAP.get(info.rate, info.rate.upper()) if info.rate.islower() else info.rate
            im.alpha_composite(self.diff_bg[info.level_index], (x, y))
            im.alpha_composite(cover, (x + 12, y + 12))
            type_png = self.pic / f'{info.type.upper()}.png'
            if type_png.exists():
                im.alpha_composite(self._open(type_png).resize((37, 14)), (x + 51, y + 91))
            rank_png = self.pic / self.theme / f'UI_TTR_Rank_{rate_name}.png'
            if rank_png.exists():
                im.alpha_composite(self._open(rank_png).resize((63, 28)), (x + 92, y + 78))
            if info.fc:
                fc_png = self.pic / f'UI_MSS_MBase_Icon_{COMBO_MAP.get(info.fc, info.fc.upper())}.png'
                if fc_png.exists():
                    im.alpha_composite(self._open(fc_png).resize((34, 34)), (x + 154, y + 77))
            if info.fs:
                fs_png = self.pic / f'UI_MSS_MBase_Icon_{SYNC_MAP.get(info.fs, info.fs.upper())}.png'
                if fs_png.exists():
                    im.alpha_composite(self._open(fs_png).resize((34, 34)), (x + 185, y + 77))

            song = total_list.by_id(str(info.song_id)) if total_list else None
            dxscore = 0
            if song and info.level_index < len(song.charts):
                dxscore = sum(song.charts[info.level_index].notes) * 3
            star = dx_score(info.dxScore / dxscore * 100) if dxscore else 0
            if star != 0:
                im.alpha_composite(self.dx_star_bg[star - 1].resize((47, 26)), (x + 217, y + 80))

            tb.draw(x + 26, y + 98, 13, info.song_id, self.id_text_color[info.level_index], 'mm')
            sy.draw_fit(x + 93, y + 14, 14, info.title, 174,
                        self.diff_text_color[info.level_index], 'lm')
            tb.draw(x + 93, y + 38, 30, f'{info.achievements:.4f}%',
                    self.diff_text_color[info.level_index], 'lm')
            tb.draw(x + 219, y + 65, 15, f'{info.dxScore}/{dxscore}',
                    self.diff_text_color[info.level_index], 'mm')
            tb.draw(x + 93, y + 65, 15, f'{info.ds} -> {info.ra}',
                    self.diff_text_color[info.level_index], 'lm')

    def to_bytes(self, im: Image.Image) -> bytes:
        buf = BytesIO()
        im.save(buf, 'PNG')
        return buf.getvalue()

    def _load_assets(self) -> None:
        self.table_type_bg = {'SD': self._asset('SD.png'), 'DX': self._asset('DX.png')}
        self.dx_star_bg = [self._asset(f'UI_GAM_Gauge_DXScoreIcon_0{n}.png') for n in range(1, 6)]
        self.diff_bg = [self._asset(f'b50_score_{n}.png') for n in
                        ('basic', 'advanced', 'expert', 'master', 'remaster')]
        self.rise_bg = [self._asset(f'rise_score_{n}.png') for n in
                        ('basic', 'advanced', 'expert', 'master', 'remaster')]
        self.diff_pg_bg = [self._asset(f'border_progress_{n}.png') for n in
                           ('basic', 'advanced', 'expert', 'master', 'remaster')]
        self.table_dx_small_bg = self.table_type_bg['DX'].resize((44, 16))
        self.table_complete_bg = self._asset('complete.png')
        self.rating_unfinished_bg = self._asset('unfinished_1.png')
        self.rating_complete_bg = self._asset('complete_1.png')
        self.plate_finished_bg = [self._asset(f't_{i}.png') for i in range(5)]
        self.plate_complete_bg = self._asset('complete_2.png')
        self.plate_progress_bottom_bg = self._asset('progress_bg.png')
        self.plate_progress_big = self._asset('progress_big.png')
        self.plate_progress_bg = self._asset('plate_progress.png')
        self.plate_progress_2 = self._asset('plate_progress_2.png')
        self.plate_progress_wu_bg = self._asset('plate_progress_wu.png')
        self.plate_progress_small = self._asset('progress_small.png')
        self.plate_progress_small_wu = self._asset('progress_small_wu.png')
        self.table_id_bg = self._asset('border_table_base.png')
        self.table_wu_rms_id_bg = self._asset('border_table_remaster.png')
        self.table_diff_bg = [self._asset(f'border_{n}.png') for n in
                              ('basic', 'advanced', 'expert', 'master', 'remaster')]
        self.separator_bg = self._asset('separator.png')
        self.chart_white_bg = self._asset('chart_white.png')
        self.sl_diff_bg = self._asset('sl_diff.png')
        self.sl_diff_utg = self._asset('sl_diff_utg.png')
        self.card_bg = self._asset('song_card.png')
        self.rainbow_bg = self._asset('rainbow.png')
        self.rainbow_bottom_bg = self._asset('rainbow_bottom.png')
        self.aurora_bg = self._asset('aurora.png')
        self.shines_bg = self._asset('bg_shines.png')
        self.pattern_bg = self._asset('pattern.png')
        self.moon_bg = self._asset('moon.png')

        self.default_text_color = (124, 129, 255, 255)
        self.diff_text_color = [(255, 255, 255, 255)] * 4 + [(138, 0, 226, 255)]
        self.id_text_color = [(129, 217, 85, 255), (245, 189, 21, 255), (255, 129, 141, 255),
                              (159, 81, 220, 255), (138, 0, 226, 255)]
        self.bg_color = [(111, 212, 61, 255), (248, 183, 9, 255), (255, 129, 141, 255),
                         (159, 81, 220, 255), (219, 170, 255, 255)]
        self.circle_text_color = (249, 62, 172, 255)

    def text_color(self) -> Tuple[int, int, int, int]:
        return self.circle_text_color if self.theme == 'circle' else self.default_text_color

    # ================= id：谱面信息 =================

    def _get_best_rating(self, rating: float) -> List[int]:
        last_item = ACHIEVEMENT_LIST[-1]
        ra = [compute_rating(rating, r) for r in ACHIEVEMENT_LIST[-6:]]
        ra.append(compute_rating(rating, last_item) + 1)
        ra.sort(reverse=True)
        return ra

    def _new_best_score(self, song_id: str, level_index: int, value: int,
                        bestlist: List[PlayChart]) -> int:
        for v in bestlist:
            if song_id == str(v.song_id) and level_index == v.level_index:
                return value - v.ra if value >= v.ra else 0
        return value - bestlist[-1].ra

    def song_chart_info(self, music: Music, player: Optional[UserInfo] = None,
                        bot_name: str = 'MaiBot') -> bytes:
        calc = bool(player and player.charts)
        is_full = True
        bestlist: List[PlayChart] = []
        if calc:
            if music.basic_info.version == 'maimai でらっくす PRiSM':
                bestlist = player.charts.dx
                is_full = len(bestlist) == 15
            else:
                bestlist = player.charts.sd
                is_full = len(bestlist) == 35
            if not bestlist:
                calc = False

        im = self._themed_asset('chart_info.png').copy()
        mr, _tb, fn = self._drawers(im)
        text_color = self.text_color()

        im.alpha_composite(self._themed_asset('logo.png').resize((249, 120)), (65, 25))
        if music.basic_info.is_new:
            im.alpha_composite(self._asset('UI_CMN_TabTitle_NewSong.png').resize((249, 120)), (842, 100))
        im.alpha_composite(self._open(self.song_chart(music.id)).resize((242, 242)), (133, 197))
        version_png = self.pic / f'{music.basic_info.version}.png'
        if version_png.exists():
            im.alpha_composite(self._open(version_png).resize((182, 90)), (800, 370))
        type_png = self.pic / f'{music.type}.png'
        if type_png.exists():
            im.alpha_composite(self._open(type_png).resize((80, 30)), (295, 410))

        fn.draw_fit(405, 220, 28, music.title, 560, text_color, 'lm')
        fn.draw_fit(407, 265, 20, music.basic_info.artist, 620, text_color, 'lm')
        fn.draw(460, 345, 24, music.basic_info.bpm, text_color, 'lm')
        fn.draw(405, 435, 22, f'ID {music.id}', text_color, 'lm')
        mr.draw(665, 435, 24, music.basic_info.genre, text_color, 'mm')

        for index in range(len(music.level)):
            spacing = 70 * index
            fn.draw(120, 590 + spacing, 22, f'{music.level[index]}({music.ds[index]})', (255, 255, 255, 255), 'mm')
            fit = music.fit_diff(index)
            fitting = f'擬 - {fit:.2f}' if fit is not None else '-'
            fn.draw(120, 613 + spacing, 15, fitting, (255, 255, 255, 255), 'mm')
            fn.draw_fit(310, 590 + spacing, 20, music.charts[index].charter, 220, text_color, 'mm')
            for n, value in enumerate(notes_columns(music.charts[index])):
                fn.draw(480 + 122 * n, 590 + spacing, 25, value, text_color, 'mm')

            if index > 1:
                ra = self._get_best_rating(music.ds[index])
                for _n, value in enumerate(ra):
                    size = 22
                    if not calc:
                        rating = value
                    elif not is_full:
                        size = 17
                        rating = f'{value}(↑{value})'
                    elif value > bestlist[-1].ra:
                        new = self._new_best_score(music.id, index, value, bestlist)
                        if new == 0:
                            rating = value
                        else:
                            size = 17
                            rating = f'{value}(↑{new})'
                    else:
                        rating = value
                    fn.draw(295 + 125 * _n, 1017 + 46 * (index - 2), size, rating, text_color, 'mm')
        mr.draw(295, 985, 12, '*未实装', anchor='mm')
        self._draw_footer(im, bot_name, 1222, 22, text_color, 3, (255, 255, 255, 255))
        return self.to_bytes(im)

    def song_chart_banquet_info(self, music: Music, bot_name: str = 'MaiBot') -> bytes:
        im = self._open(self.pic / 'chart_info_enkaijou.png')
        fn, = [self._drawers(im)[2]]
        stroke_color = (210, 57, 174, 255)
        is_buddy = music.type == 'BUDDY' if hasattr(music, 'is_buddy') else False

        kanji_bg = self._asset('utg_kanji.png')
        im.alpha_composite(kanji_bg, (140, 660 if is_buddy else 730))
        if is_buddy:
            player_path = self.pic / 'utg_2p.png'
            p_y, base_y, step_y = 715, 820, 100
            im.alpha_composite(self._asset('utg_buddy.png'), (255, 660))
        else:
            player_path = self.pic / 'utg_1p.png'
            p_y, base_y, step_y = 785, 890, 0
        im.alpha_composite(self._open(player_path), (98, p_y))

        im.alpha_composite(self._themed_asset('logo.png').resize((249, 120)), (10, 35))
        if music.basic_info.is_new:
            im.alpha_composite(self._asset('UI_CMN_TabTitle_NewSong.png').resize((249, 120)), (950, 165))
        im.alpha_composite(self._open(self.song_chart(music.id)).resize((242, 242)), (133, 246))
        version_png = self.pic / f'{music.basic_info.version}.png'
        if version_png.exists():
            im.alpha_composite(self._open(version_png).resize((182, 90)), (800, 415))

        kanji = getattr(music, 'kanji', '') or ''
        fn.draw(216, p_y - 28, 18, kanji, anchor='mm')
        fn.draw_fit(405, 265, 28, music.title, 560, (255, 255, 255, 255), 'lm', 3, stroke_color)
        fn.draw_fit(407, 320, 20, music.basic_info.artist, 620, (255, 255, 255, 255), 'lm', 3, stroke_color)
        fn.draw(460, 393, 24, music.basic_info.bpm, (255, 255, 255, 255), 'lm', 3, stroke_color)
        fn.draw(405, 475, 22, f'ID {music.id}', (255, 255, 255, 255), 'lm', 3, stroke_color)
        fn.draw(680, 475, 22, music.basic_info.genre, (255, 255, 255, 255), 'mm', 3, stroke_color)
        description = getattr(music, 'description', '') or ''
        fn.draw(595, 595, 25, description, (255, 255, 255, 255), 'mm')
        fn.draw(180, p_y + 28, 24, f'Lv. {music.level[0]}', (255, 255, 255, 255), 'mm', 3, stroke_color)
        for index in range(len(music.charts)):
            for n, value in enumerate(notes_columns(music.charts[index])):
                fn.draw(330 + 140 * n, base_y + step_y * index, 25, value,
                        (255, 255, 255, 255), 'mm', 3, stroke_color)
        self._draw_footer(im, bot_name, 1102, 22, (255, 255, 255, 255), 3, stroke_color)
        return self.to_bytes(im)

    # ================= minfo：谱面游玩 =================

    def song_play_data(self, music: Music, play_result: List[Optional[PlayRecord]],
                       service: str = '水鱼查分器', bot_name: str = 'MaiBot') -> bytes:
        color = self.text_color()
        im = self._themed_asset('play_info.png').copy()
        sy, tb, fn = self._drawers(im)

        im.alpha_composite(self._themed_asset('logo.png').resize((249, 120)), (42, 34))
        im.alpha_composite(self._open(self.song_chart(music.id)).resize((300, 300)), (100, 260))
        cat_key = CATEGORY.get(music.basic_info.genre)
        if cat_key:
            info_png = self.pic / f'info_{cat_key}.png'
            if info_png.exists():
                im.alpha_composite(self._open(info_png), (100, 260))
        version_png = self.pic / f'{music.basic_info.version}.png'
        if version_png.exists():
            im.alpha_composite(self._open(version_png).resize((183, 90)), (295, 205))
        type_png = self.pic / f'{music.type}.png'
        if type_png.exists():
            im.alpha_composite(self._open(type_png).resize((55, 20)), (350, 560))

        tb.draw(1140, 737, 18, f'Data from {service}', color, 'rm')
        sy.draw_fit(255, 595, 12, music.basic_info.artist, 400, color, 'mm')
        sy.draw_fit(255, 622, 18, music.title, 430, color, 'mm')
        fn.draw(160, 720, 22, music.id, color, 'mm')
        fn.draw(380, 720, 22, music.basic_info.bpm, color, 'mm')

        y = 100
        for num in range(len(music.ds)):
            im.alpha_composite(self._asset(f'd_{num}.png'), (650, 235 + y * num))
            info = play_result[num] if num < len(play_result) else None
            if info is not None:
                im.alpha_composite(self._themed_asset('ra_dx.png').resize((102, 44)), (850, 272 + y * num))
                _dxscore = sum(music.charts[num].notes) * 3
                dxscore = info.dxScore or 0
                dxnum = dx_score(dxscore / _dxscore * 100) if _dxscore else 0
                rating, rate = info.ra, RANK_MAP.get(info.rate, info.rate.upper())
                if dxnum != 0:
                    im.alpha_composite(self.dx_star_bg[dxnum - 1].resize((32, 19)), (851, 296 + y * num))
                tb.draw(916, 304 + y * num, 13, f'{dxscore}/{_dxscore}', color, 'mm')

                im.alpha_composite(self._asset('fcfs.png'), (965, 265 + y * num))
                if info.fc:
                    fc_png = self.pic / f'UI_CHR_PlayBonus_{COMBO_MAP.get(info.fc, info.fc.upper())}.png'
                    if fc_png.exists():
                        im.alpha_composite(self._open(fc_png).resize((65, 65)), (960, 261 + y * num))
                if info.fs:
                    fs_png = self.pic / f'UI_CHR_PlayBonus_{SYNC_MAP.get(info.fs, info.fs.upper())}.png'
                    if fs_png.exists():
                        im.alpha_composite(self._open(fs_png).resize((65, 65)), (1025, 261 + y * num))
                rank_png = self.pic / self.theme / f'UI_TTR_Rank_{rate}.png'
                if rank_png.exists():
                    im.alpha_composite(self._open(rank_png).resize((100, 45)), (737, 272 + y * num))

                fn.draw(500, 295 + y * num, 30, f'{info.achievements:.4f}%', color, 'lm')
                fn.draw(685, 248 + y * num, 20, music.level[num], anchor='mm')
                tb.draw(915, 283 + y * num, 18, rating, color, 'mm')
            else:
                fn.draw(685, 248 + y * num, 25, music.level[num], anchor='mm')
                sy.draw(800, 302 + y * num, 30, '未游玩', color, 'mm')
        if len(music.ds) == 4:
            sy.draw(800, 302 + y * 4, 30, '没有该难度', color, 'mm')

        self._draw_footer(im, bot_name, 832, 22, color, 3, (255, 255, 255, 255))
        return self.to_bytes(im)

    # ================= b50 =================

    def _find_ra_pic(self, rating: int) -> str:
        thresholds = [(1000, '01'), (2000, '02'), (4000, '03'), (7000, '04'), (10000, '05'),
                      (12000, '06'), (13000, '07'), (14000, '08'), (14500, '09'), (15000, '10')]
        for limit, num in thresholds:
            if rating < limit:
                return f'UI_CMN_DXRating_{num}.png'
        if self.theme == 'circle':
            return 'UI_CMN_DXRating_11.png' if rating < 16000 else 'UI_CMN_DXRating_12.png'
        return 'UI_CMN_DXRating_11.png'

    def draw_b50(self, user: UserInfo, total_list, qq_logo: Optional[bytes] = None,
                 bot_name: str = 'MaiBot', service: str = 'DIVINGFISH') -> bytes:
        im = self._themed_asset('b50.png').copy()
        sy, tb, _fn = self._drawers(im)
        color = self.text_color()
        rating_value = user.rating or 0

        im.alpha_composite(self._themed_asset('logo.png').resize((249, 120)), (14, 60))

        # plate：大牌背景先铺（顺序与源插件一致，否则会盖住名牌底）
        plate_path = self.pic / 'UI_Plate_550101.png'
        if user.plate:
            candidate = self.plate_version_dir / f'{user.plate}.png'
            if candidate.exists():
                plate_path = candidate
        im.alpha_composite(self._open(plate_path).resize((800, 130)), (300, 60))

        # icon
        icon = None
        if qq_logo:
            try:
                icon = Image.open(BytesIO(qq_logo)).convert('RGBA').resize((120, 120))
            except Exception:  # noqa: BLE001
                icon = None
        if icon is None:
            icon_png = self.pic / 'UI_Icon_509506.png'
            if icon_png.exists():
                icon = self._open(icon_png).resize((120, 120))
        if icon is not None:
            im.alpha_composite(icon, (305, 65))

        # dx_rating
        dx_rating = self._open(self.pic / self.theme / self._find_ra_pic(rating_value)).resize((186, 35))
        im.alpha_composite(dx_rating, (435, 72))
        for n, i in enumerate(f'{rating_value:05d}'):
            num_png = self.pic / f'UI_NUM_Drating_{i}.png'
            if num_png.exists():
                im.alpha_composite(self._open(num_png).resize((17, 20)), (520 + 15 * n, 80))

        # 名牌底、段位、阶级（压在牌子之上）
        im.alpha_composite(self._asset('Name.png'), (435, 115))
        add_rating = user.additional_rating or 0
        _num = f'{add_rating if add_rating <= 10 else add_rating + 1:02d}'
        match_png = self.pic / f'UI_DNM_DaniPlate_{_num}.png'
        if match_png.exists():
            im.alpha_composite(self._open(match_png).resize((80, 32)), (625, 120))
        class_png = self.pic / 'UI_FBR_Class_00.png'
        if class_png.exists():
            im.alpha_composite(self._open(class_png).resize((90, 54)), (620, 60))

        name = user.nickname or user.username or '未知用户'
        sy.draw_fit(445, 135, 20, name, 320, (0, 0, 0, 255), 'lm')
        sdrating = sum(c.ra for c in (user.charts.sd if user.charts else []))
        dxrating = sum(c.ra for c in (user.charts.dx if user.charts else []))
        # 称号彩条先铺底，再把 B35+B15=Ra 文字压在彩条上（顺序与源插件一致）
        shougou = self.shougou_dir / 'UI_CMN_Shougou_Rainbow.png'
        if shougou.exists():
            im.alpha_composite(self._open(shougou).resize((270, 27)), (435, 160))
        tb.draw(570, 172, 14,
                f'B35: {sdrating} + B15: {dxrating} = {rating_value}', (0, 0, 0, 255), 'mm')
        self._draw_footer(im, f'{service} · {bot_name}', 1572, 20, color, 5, (255, 255, 255, 255), font='sy')

        if user.charts:
            self._while_score_cards(im, user.charts.sd, 235, total_list=total_list)
            self._while_score_cards(im, user.charts.dx, 1085, total_list=total_list)
        return self.to_bytes(im)

    # ================= 背景生成（update_table 移植） =================

    def _generate_bg(self, height: int, separator_height: int) -> Image.Image:
        im = tricolor_gradient_prism_plus(1400, height)
        im.alpha_composite(self.aurora_bg)
        im.alpha_composite(self.shines_bg, (11, 6))
        im.alpha_composite(self.rainbow_bg, (318, height - 545))
        im.alpha_composite(self.rainbow_bottom_bg, (122, height - 305))
        for h in range((height // 358) + 1):
            im.alpha_composite(self.pattern_bg, (0, (358 + 7) * h))
        im.alpha_composite(self.separator_bg, (100, separator_height))
        return im

    def render_rating_table_bg(self, lv: str, level_data: Dict[str, Dict[str, list]],
                               bot_name: str = 'MaiBot') -> bytes:
        """定数表底图（update_rating_table 单级别版）。"""
        lvlist = level_data[lv]
        if lv == '15':
            count = len(lvlist.get('15.0', []))
            lines = (count // 3) + (1 if count % 3 else 0)
            height = 650 + lines * 450
            im = self._generate_bg(height, 360)
            _sy, _tb, fot = self._drawers(im)
            self._draw_footer(im, bot_name, height - 88, 24, (114, 188, 254, 255))
            unknown_chart = self._open(self.song_chart(0)).resize((330, 330))
            for i in range(lines * 3):
                row, col = divmod(i, 3)
                x = 100 + col * 425
                y = 500 + row * 450
                im.alpha_composite(self.chart_white_bg, (x, y))
                if i < count:
                    song = lvlist['15.0'][i]
                    im.alpha_composite(self._open(self.song_chart(song.id)).resize((330, 330)), (x + 10, y + 10))
                    im.alpha_composite(self.table_type_bg[song.type], (x + 200, y + 345))
                    version_png = self.pic / f'{song.basic_info.version}.png'
                    if version_png.exists():
                        im.alpha_composite(self._open(version_png).resize((332, 160)), (x + 9, y - 80))
                    fot.draw(x + 100, y + 370, 35, song.id, (114, 188, 254, 255), 'mm')
                else:
                    im.alpha_composite(unknown_chart, (x + 10, y + 10))
                    im.alpha_composite(self.table_type_bg['DX'], (x + 200, y + 345))
                    fot.draw(x + 100, y + 370, 35, '????', (114, 188, 254, 255), 'mm')
                    fot.draw(x + 175, y + 280, 30, 'UNKNOWN', (114, 188, 254, 255), 'mm', 8, (255, 255, 255, 255))
            return self.to_bytes(im)

        GRID_STEP, START_X = 85, 140
        current_y = 450
        for songs in lvlist.values():
            if not songs:
                continue
            rows = (len(songs) - 1) // 14 + 1
            current_y += rows * GRID_STEP + 30
        height = current_y + 230

        _im = self._generate_bg(height, 360)
        im = generate_frosted_card(_im, (50, 404, 1350, current_y))
        _sy, tb, fot = self._drawers(im)
        self._draw_footer(im, bot_name, height - 88, 24, (114, 188, 254, 255))

        START_Y = 450
        for ds, songs in lvlist.items():
            if not songs:
                continue
            _ds = ds.split('.')[-1]
            fot.draw(70, START_Y + 35, 40, f'.{_ds}', (114, 188, 254, 255), 'lm', 4, (255, 255, 255, 255))
            max_row = 0
            for num, music in enumerate(songs):
                row, col = divmod(num, 14)
                max_row = max(max_row, row)
                x = START_X + col * GRID_STEP
                y = START_Y + row * GRID_STEP
                im.alpha_composite(self._open(self.song_chart(music.id)).resize((75, 75)), (x, y))
                im.alpha_composite(self.table_diff_bg[music.lv], (x - 5, y - 5))
                tb.draw(x + 56, y + 4, 13, music.id,
                        self.diff_text_color[music.lv], 'mm')
            START_Y += (max_row + 1) * GRID_STEP + 30
        return self.to_bytes(im)

    def ensure_rating_table_bg(self, lv: str, level_data: Dict[str, Dict[str, list]],
                               bot_name: str = 'MaiBot') -> Path:
        path = self.rating_table_dir / f'{lv}.png'
        if not path.exists():
            path.write_bytes(self.render_rating_table_bg(lv, level_data, bot_name))
        return path

    def render_plate_table_bg(self, name: str, plate_ids: List[int], remaster_ids: List[int],
                              total_list, bot_name: str = 'MaiBot') -> bytes:
        """完成表底图（update_plate_table / update_wu_plate_table 单牌子版）。"""
        song_list = total_list.by_id_list(plate_ids)
        remaster_set = {int(i) for i in remaster_ids}
        all_level_dict: Dict[str, list] = {lv: [] for lv in reversed(LEVEL_LIST)}
        if name in ('舞', '霸'):
            for s in song_list:
                if s.id in remaster_set and len(s.ds) > 4:
                    all_level_dict[s.level[4]].append(s)
                else:
                    all_level_dict[s.level[3]].append(s)
        else:
            for s in song_list:
                all_level_dict[s.level[3]].append(s)

        GRID_STEP, START_X = 96, 180
        current_y = 490
        for songs in all_level_dict.values():
            if not songs:
                continue
            rows = (len(songs) - 1) // 12 + 1
            current_y += rows * GRID_STEP + 30
        height = current_y + 180

        _im = self._generate_bg(height, 400)
        im = generate_frosted_card(_im, (50, 444, 1350, current_y))
        _sy, tb, fot = self._drawers(im)
        self._draw_footer(im, bot_name, height - 88, 24, (114, 188, 254, 255))

        START_Y = 490
        for ds, songs in all_level_dict.items():
            if not songs:
                continue

            def sort_key(m: Music):
                if m.id in remaster_set and len(m.ds) > 4:
                    return m.ds[4]
                return m.ds[3]

            songs.sort(key=sort_key, reverse=True)
            fot.draw(72, START_Y + 40, 40, ds, (114, 188, 254, 255), 'lm', 4, (255, 255, 255, 255))
            max_row = 0
            for num, m in enumerate(songs):
                row, col = divmod(num, 12)
                max_row = max(max_row, row)
                x = START_X + col * GRID_STEP
                y = START_Y + row * GRID_STEP
                im.alpha_composite(self._open(self.song_chart(m.id)).resize((80, 80)), (x, y))
                if m.id in remaster_set:
                    id_bg = self.table_wu_rms_id_bg
                    id_color = (138, 0, 226, 255)
                else:
                    id_bg = self.table_id_bg
                    id_color = (255, 255, 255, 255)
                im.alpha_composite(id_bg, (x - 5, y - 5))
                tb.draw(x + 56, y + 4, 16, m.id, id_color, 'mm')
            START_Y += (max_row + 1) * GRID_STEP + 30
        return self.to_bytes(im)

    def ensure_plate_table_bg(self, name: str, plate_ids: List[int], remaster_ids: List[int],
                              total_list, bot_name: str = 'MaiBot') -> Path:
        if name in ('舞', '霸'):
            # 舞/霸 分两页
            paths = []
            for page in (1, 2):
                p = self.plate_table_dir / f'舞-{page}.png'
                if not p.exists():
                    p.write_bytes(self.render_plate_table_bg(name, plate_ids, remaster_ids, total_list, bot_name))
                paths.append(p)
            return paths[0]
        path = self.plate_table_dir / f'{name}.png'
        if not path.exists():
            path.write_bytes(self.render_plate_table_bg(name, plate_ids, remaster_ids, total_list, bot_name))
        return path

    # ================= 定数表 / 完成表（等级） =================

    def draw_rating_table(self, lv: str, level_data: Dict[str, Dict[str, list]],
                          play_result: Optional[List[PlayRecord]] = None, *,
                          plan: bool = False, level_text: bool = False,
                          bot_name: str = 'MaiBot') -> bytes:
        bg_path = self.ensure_rating_table_bg(lv, level_data, bot_name)
        im = self._open(bg_path)
        _sy, tb, fot = self._drawers(im)
        font_color = (114, 188, 254, 255)

        if level_text:
            fot.draw(495, 220, 70, 'Level.', font_color, 'ld', 8, (255, 255, 255, 255))
            fot.draw(750, 220, 100, lv, font_color, 'ld', 8, (255, 255, 255, 255))
            final = im.resize((int(im.width * 0.8), int(im.height * 0.8)), Image.Resampling.LANCZOS)
            return self.to_bytes(final)

        fot.draw(495, 160, 70, 'Level.', font_color, 'ld', 8, (255, 255, 255, 255))
        fot.draw(750, 160, 100, lv, font_color, 'ld', 8, (255, 255, 255, 255))

        statistics = {k: 0 for k in STATISTICS_KEYS}
        played_map: Dict[int, Dict[int, PlayRecord]] = {}
        rank_sp = RANK_SP[-6:]
        lvlist = level_data[lv]
        ds_of = {}
        for songs in lvlist.values():
            for m in songs:
                ds_of[(m.id, m.lv)] = m.ds
        for d in (play_result or []):
            if d.level != lv:
                continue
            played_map.setdefault(d.song_id, {})[d.level_index] = d
            ds = ds_of.get((str(d.song_id), d.level_index), d.ds)
            rate = compute_rating(ds, d.achievements, onlyrate=True)
            if d.achievements >= 80:
                statistics['clear'] += 1
            if rate in rank_sp:
                for r in rank_sp[: rank_sp.index(rate) + 1]:
                    statistics[r] += 1
            if d.fc and d.fc in COMBO_SP:
                for f in COMBO_SP[: COMBO_SP.index(d.fc) + 1]:
                    statistics[f] += 1
            if d.fs:
                if d.fs == 'sync':
                    statistics['sync'] += 1
                elif d.fs in SYNC_D_SP:
                    for s in SYNC_D_SP[: SYNC_D_SP.index(d.fs) + 1]:
                        statistics[s] += 1

        total_songs_count = sum(len(v) for v in lvlist.values())
        im.alpha_composite(self.table_complete_bg, (251, 190))
        tb.draw(394, 238, 30, f"{statistics['clear']}/{total_songs_count}",
                self.default_text_color, 'mm', 5, (255, 255, 255, 255))
        for n, key in enumerate(STATISTICS_KEYS[1:]):
            if n < 6:
                x = 534 + (n % 6) * 102
                y = 238
            else:
                x = 292 + ((n - 6) % 9) * 102
                y = 323
            tb.draw(x, y, 30, statistics[key], self.default_text_color, 'mm', 2, (255, 255, 255, 255))

        achievements_or_fc_list: List[Union[float, int]] = []
        if lv == '15':
            for num, song in enumerate(lvlist.get('15.0', [])):
                row, col = divmod(num, 3)
                x = 100 + col * 425
                y = 500 + row * 450
                record = played_map.get(int(song.id), {}).get(song.lv)
                if record is None:
                    continue
                if not plan:
                    achievements_or_fc_list.append(record.achievements)
                    rate = compute_rating(song.ds, record.achievements, onlyrate=True)
                    rank_png = self.pic / self.theme / f'UI_TTR_Rank_{RANK_MAP.get(rate, rate.upper())}.png'
                    if rank_png.exists():
                        im.alpha_composite(self._open(rank_png), (x + 55, y + 115))
                    continue
                if record.fc:
                    achievements_or_fc_list.append(COMBO_SP.index(record.fc))
                    fc_png = self.pic / f'UI_CHR_PlayBonus_{COMBO_MAP[record.fc]}.png'
                    if fc_png.exists():
                        im.alpha_composite(self._open(fc_png).resize((200, 200)), (x + 75, y + 80))
        else:
            current_y = 450
            for songs in lvlist.values():
                for num, song in enumerate(songs):
                    row, col = divmod(num, 14)
                    x = 140 + col * 85
                    y = current_y + row * 85
                    record = played_map.get(int(song.id), {}).get(song.lv)
                    if record is None:
                        continue
                    if not plan:
                        achievements_or_fc_list.append(record.achievements)
                        bg = self.rating_complete_bg if record.achievements >= 100 else self.rating_unfinished_bg
                        im.alpha_composite(bg, (x + 1, y + 1))
                        rate = compute_rating(song.ds, record.achievements, onlyrate=True)
                        rank_png = self.pic / self.theme / f'UI_TTR_Rank_{RANK_MAP.get(rate, rate.upper())}.png'
                        if rank_png.exists():
                            im.alpha_composite(self._open(rank_png).resize((78, 35)), (x, y + 20))
                        continue
                    if record.fc:
                        achievements_or_fc_list.append(COMBO_SP.index(record.fc))
                        im.alpha_composite(self.rating_complete_bg, (x + 1, y + 1))
                        fc_png = self.pic / f'UI_MSS_MBase_Icon_{COMBO_MAP[record.fc]}.png'
                        if fc_png.exists():
                            im.alpha_composite(self._open(fc_png).resize((50, 50)), (x + 15, y + 13))
                group_rows = (len(songs) - 1) // 14 + 1
                current_y += group_rows * 85 + 30

        if achievements_or_fc_list and len(achievements_or_fc_list) == total_songs_count:
            r = -1
            thresholds = range(4) if plan else ACHIEVEMENT_LIST[-6:]
            for t in thresholds:
                count = sum(1 for s in achievements_or_fc_list if s >= t)
                if count == total_songs_count:
                    r += 1
                else:
                    break
            if r != -1:
                pic = COMBO_MAP[COMBO_SP[r]] if plan else RANK_MAP[RANK_SP[-6:][r]]
                allclear = self.pic / f'UI_MSS_Allclear_Icon_{pic}.png'
                if allclear.exists():
                    im.alpha_composite(self._open(allclear), (40, 40))

        final = im.resize((int(im.width * 0.8), int(im.height * 0.8)), Image.Resampling.LANCZOS)
        return self.to_bytes(final)

    # ================= 曲目列表（查歌结果） =================

    def song_list(self, songs: List[Music], page: int = 1, bot_name: str = 'MaiBot') -> bytes:
        """源插件 song_list：查歌结果列表卡（每页 14 首，两列）。"""
        PAGE_SIZE = 14
        total_page = max(1, (len(songs) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, total_page))
        start = (page - 1) * PAGE_SIZE
        page_songs = songs[start:start + PAGE_SIZE]

        rows, rest = divmod(len(page_songs), 2)
        lines = rows + rest
        height = 200 + lines * 145 + 200

        _im = tricolor_gradient_prism_plus(1000, height)
        _im.alpha_composite(self.aurora_bg.resize((1000, 174)))
        _im.alpha_composite(self.shines_bg.resize((1000, 442)))
        pattern = self.pattern_bg.resize((1000, 256))
        for h in range((height // 256) + 1):
            _im.alpha_composite(pattern, (0, (256 + 6) * h))
        _im.alpha_composite(self.rainbow_bg.resize((550, 288)), (225, height - 435))
        _im.alpha_composite(self.rainbow_bottom_bg.resize((786, 164)), (107, height - 260))

        im = generate_frosted_card(_im, (50, 150, 950, 150 + lines * 145 + 100), alpha=0.2)
        sy, _tb, fot = self._drawers(im)
        text_color = self.default_text_color

        chara = self._themed_asset('chara_left.png').resize((156, 187))
        im.alpha_composite(chara, (800, 0))
        im.alpha_composite(self.moon_bg.resize((120, 120)), (60, 20))
        version_header = self.pic / 'maimai でらっくす PRiSM PLUS.png'
        if version_header.exists():
            im.alpha_composite(self._open(version_header).resize((210, 101)), (15, 20))

        for num, song in enumerate(page_songs):
            row, col = divmod(num, 2)
            x = 70 + col * 450
            y = 200 + row * 145

            im.alpha_composite(self.card_bg, (x, y))
            cover = self._open(self.song_chart(song.id)).resize((80, 80))
            version_png = self.pic / f'{song.basic_info.version}.png'
            if version_png.exists():
                im.alpha_composite(self._open(version_png).resize((104, 50)), (x + 315, y - 30))
            type_png = self.pic / f'{song.type.upper()}.png'
            if type_png.exists():
                im.alpha_composite(self._open(type_png).resize((40, 15)), (x + 50, y + 75))

            im.alpha_composite(cover, (x + 10, y + 10))
            im.alpha_composite(self.sl_diff_utg if song.is_utage else self.sl_diff_bg,
                               (x + 100, y + 95))

            fot.draw(x + 50, y + 105, 15, song.id, text_color, 'mm')
            fot.draw_fit(x + 100, y + 25, 20, song.title, 330, text_color, 'lm')
            fot.draw_fit(x + 100, y + 50, 12, song.basic_info.artist, 330, text_color, 'lm')
            fot.draw(x + 100, y + 80, 15, f'BPM: {song.basic_info.bpm}', text_color, 'lm')
            sy.draw_fit(x + 230, y + 80, 12, song.basic_info.genre, 200, text_color, 'lm')
            if song.is_utage:
                if song.level:
                    fot.draw(x + 125, y + 105, 15, song.level[0], (255, 255, 255, 255), 'mm')
            else:
                for diff_idx, lv in enumerate(song.level):
                    color = (138, 0, 226, 255) if diff_idx == 4 else (255, 255, 255, 255)
                    fot.draw(x + 125 + 50 * diff_idx, y + 105, 15, lv, color, 'mm')

        fot.draw(500, 70, 55, '曲目列表', text_color, 'mm', 3, (255, 255, 255, 255))
        fot.draw(500, height - 100, 35, f'Page {page}/{total_page}', text_color, 'mm', 3, (255, 255, 255, 255))
        self._draw_footer(im, bot_name, height - 44, 15, text_color, 3, (255, 255, 255, 255))
        return self.to_bytes(im)

    # ================= 等宽文本图（排行榜等） =================

    def text_image(self, text: str) -> bytes:
        """源插件 text_to_image：等宽字体文本图（带缺字回退）。"""
        shanggu = self.font_dir / 'ShangguMonoSC-Regular.otf'
        primary = str(shanggu) if shanggu.is_file() else str(self.font_sy)
        probe = Image.new('RGB', (10, 10))
        probe_draw = ImageDraw.Draw(probe)
        dt = DrawText(probe_draw, primary, self._chain(Path(primary)))
        size = 24
        padding, margin = 10, 4
        lines = text.strip().splitlines()
        widths = [dt.measure(line, size) for line in lines]
        bboxes = [ImageFont.truetype(primary, size).getbbox(line or ' ') for line in lines]
        line_h = [bb[3] for bb in bboxes]
        max_width = max(widths) if widths else 1
        wa = int(max_width) + padding * 2
        ha = int(sum(line_h) + margin * (len(lines) - 1) + padding * 2)
        im = Image.new('RGB', (max(wa, 1), max(ha, 1)), color=(255, 255, 255))
        real_draw = ImageDraw.Draw(im)
        dt2 = DrawText(real_draw, primary, self._chain(Path(primary)))
        offset = padding
        for line, h in zip(lines, line_h):
            dt2.draw(padding, offset, size, line, (0, 0, 0, 255), 'lt')
            offset += h + margin
        return self.to_bytes(im)

    # ================= 帮助菜单（主题风格排版） =================

    def draw_help(self, sections: List[Tuple[str, Tuple[int, int, int], List[Tuple[str, str]]]],
                  bot_name: str = 'MaiBot') -> bytes:
        """PRiSM PLUS 风格帮助菜单：双栏卡片、每组彩色标题章、命令+说明两行排版。"""
        W = 1240
        margin, col_gap = 44, 36
        col_w = (W - margin * 2 - col_gap) // 2
        header_h = 200
        item_h = 58
        title_h = 88
        pad = 20
        sec_gap = 24
        footer_h = 150

        def section_height(items: List[Tuple[str, str]]) -> int:
            return title_h + len(items) * item_h + 14

        # 按阅读顺序寻找最均衡的分列点
        heights = [section_height(items) for _, _, items in sections]
        best_split, best_diff = 1, None
        for split in range(1, len(sections)):
            left = sum(heights[:split]) + (split - 1) * sec_gap
            right = sum(heights[split:]) + (len(sections) - split - 1) * sec_gap
            diff = abs(left - right)
            if best_diff is None or diff < best_diff:
                best_split, best_diff = split, diff
        left_secs = sections[:best_split]
        right_secs = sections[best_split:]
        body_h = max(
            sum(heights[:best_split]) + (best_split - 1) * sec_gap,
            sum(heights[best_split:]) + (len(sections) - best_split - 1) * sec_gap,
        )
        height = header_h + body_h + footer_h

        _im = tricolor_gradient_prism_plus(W, height)
        _im.alpha_composite(self.aurora_bg.resize((W, 174)))
        _im.alpha_composite(self.shines_bg.resize((W, 442)))
        pattern = self.pattern_bg.resize((W, 256))
        for h in range((height // 256) + 1):
            _im.alpha_composite(pattern, (0, (256 + 6) * h))
        _im.alpha_composite(self.rainbow_bg.resize((550, 288)), (330, height - 420))
        _im.alpha_composite(self.rainbow_bottom_bg.resize((786, 164)), (222, height - 246))

        im = _im
        sy, _tb, fot = self._drawers(im)
        text_color = self.default_text_color
        dr = ImageDraw.Draw(im)

        # 顶部：月亮 + 版本横幅 + 标题 + 看板娘
        im.alpha_composite(self.moon_bg.resize((110, 110)), (margin, 16))
        version_header = self.pic / 'maimai でらっくす PRiSM PLUS.png'
        if version_header.exists():
            im.alpha_composite(self._open(version_header).resize((210, 101)), (margin + 130, 20))
        chara = self._themed_asset('chara_right.png').resize((132, 197))
        im.alpha_composite(chara, (W - margin - 130, 0))
        fot.draw(W - margin - 220, 96, 48, '帮助菜单', text_color, 'mm', 3, (255, 255, 255, 255))

        def draw_column(x: int, col_sections: List[Tuple[str, Tuple[int, int, int], List[Tuple[str, str]]]]) -> None:
            y = header_h - 10
            for title, color, items in col_sections:
                panel_h = section_height(items)
                # 白色圆角面板
                dr.rounded_rectangle((x, y, x + col_w, y + panel_h), radius=18,
                                     fill=(255, 255, 255, 236),
                                     outline=(255, 255, 255, 255), width=2)
                # 彩色标题章
                tw = fot.measure(title, 24)
                chip_w = tw + 34
                dr.rounded_rectangle((x + 18, y + 16, x + 18 + chip_w, y + 16 + 40),
                                     radius=12, fill=tuple(color) + (255,))
                fot.draw(x + 18 + chip_w / 2, y + 36, 24, title, (255, 255, 255, 255), 'mm')
                iy = y + title_h
                for cmd, desc in items:
                    sy.draw_fit(x + 24, iy, 20, cmd, col_w - 48, (52, 52, 52, 255), 'lm')
                    sy.draw_fit(x + 44, iy + 27, 15, desc, col_w - 68, (140, 140, 140, 255), 'lm')
                    iy += item_h
                y += panel_h + sec_gap

        draw_column(margin, left_secs)
        draw_column(margin + col_w + col_gap, right_secs)
        self._draw_footer(im, bot_name, height - 62, 15, text_color, 2, (255, 255, 255, 255))
        return self.to_bytes(im)

    # ================= 完成表（牌子） =================

    PLAN_CRITERIA = {
        '者': ('achievements', None),
        '极': ('fc', COMBO_SP),
        '極': ('fc', COMBO_SP),
        '将': ('achievements', None),
        '神': ('fc', ['ap', 'app']),
        '舞舞': ('fs', ['fsd', 'fsdp']),
    }

    def _plate_qualified(self, play: Optional[PlayRecord], plan: str) -> bool:
        if not play:
            return False
        attr, values = self.PLAN_CRITERIA[plan]
        val = getattr(play, attr)
        if plan == '将':
            return val >= 100
        if plan == '者':
            return val >= 80
        if plan == '舞舞':
            return SYNC_MAP.get(val, val) in ('FSD', 'FSDp')
        return val in values

    def draw_plate_table(self, version: str, plan: str, version_name: str,
                         plate_ids: List[int], remaster_ids: List[int],
                         records: List[PlayRecord], total_list,
                         bot_name: str = 'MaiBot') -> bytes:
        is_wu = version in ('舞', '霸')
        plate_name = f'舞-1' if is_wu else version
        slot_num = 5 if is_wu else 4

        song_list = total_list.by_id_list(plate_ids)
        song_id_to_level = {s.id: s.level[4] if (s.id in remaster_ids and len(s.level) > 4)
                            else s.level[3] for s in song_list} if is_wu else \
            {s.id: s.level[3] for s in song_list}

        played_map: Dict[str, Dict[int, List[Optional[PlayRecord]]]] = {}
        songs_by_id = {s.id: s for s in song_list}
        # 行顺序必须与底图一致（reversed(LEVEL_LIST)），否则标记会贴错行
        for lv in reversed(LEVEL_LIST):
            if lv in set(song_id_to_level.values()):
                played_map[lv] = {}
        for s in sorted(song_list, key=lambda m: (m.ds[4] if (m.id in remaster_ids and len(m.ds) > 4) else m.ds[3]),
                        reverse=True):
            lv = song_id_to_level[s.id]
            slot = 5 if (is_wu and s.id in remaster_ids) else 4
            played_map[lv][s.id] = [None] * slot
        for d in records:
            if str(d.song_id) not in song_id_to_level:
                continue
            if slot_num == 4 and d.level_index == 4:
                continue
            lv = song_id_to_level[str(d.song_id)]
            slots = played_map.get(lv, {}).get(str(d.song_id))
            if slots is not None and d.level_index < len(slots):
                slots[d.level_index] = d

        # 组装每首歌的槽位与达成判定
        levels_order = list(played_map.keys())
        display_levels = levels_order

        finished_bg = self.plate_finished_bg
        complete_bg = self.plate_complete_bg
        progress_bg = self.plate_progress_wu_bg if is_wu else self.plate_progress_bg

        bg_path = self.ensure_plate_table_bg(version, plate_ids, remaster_ids, total_list, bot_name)
        im = Image.open(bg_path).convert('RGBA')
        _sy, _tb, fot = self._drawers(im)

        im.alpha_composite(progress_bg, (175, 20))
        plan_char = '極' if plan == '极' else plan
        plate_title = self.plate_version_dir / f'{version}{plan_char}.png'
        if not plate_title.exists():
            plate_title = self.plate_version_dir / f'{version}{plan}.png'
        if plate_title.exists():
            im.alpha_composite(self._open(plate_title).resize((1000, 161)), (200, 45))

        start_y = 490
        finished_songs = 0
        slot_counts = [0] * slot_num
        slot_totals = [0] * slot_num
        for lv in levels_order:
            is_current = lv in display_levels
            songs_dict = played_map[lv]
            rows = (len(songs_dict) - 1) // 12 + 1 if songs_dict else 0
            for idx, (sid, results) in enumerate(songs_dict.items()):
                row, col = divmod(idx, 12)
                x = 180 + col * 96
                y = start_y + row * 96
                if not is_current:
                    continue
                qualified_slots = [i for i, p in enumerate(results) if self._plate_qualified(p, plan)]
                for i in qualified_slots:
                    slot_counts[i] += 1
                if len(qualified_slots) == len(results) and results:
                    finished_songs += 1
                index = len(results) - 1
                if index in qualified_slots:
                    play = results[index]
                    im.alpha_composite(complete_bg, (x + 1, y + 1))
                    if plan in ('将', '者'):
                        ds = songs_by_id[sid].ds[index] if index < len(songs_by_id[sid].ds) else play.ds
                        rate = compute_rating(ds, play.achievements, onlyrate=True)
                        rate_name = RANK_MAP.get(rate, rate.upper())
                        rank_png = self.pic / self.theme / f'UI_TTR_Rank_{rate_name}.png'
                        if rank_png.exists():
                            im.alpha_composite(self._open(rank_png).resize((80, 36)), (x, y + 22))
                    else:
                        val = play.fc if plan in ('极', '極', '神') else play.fs
                        icon_name = COMBO_MAP.get(val) or SYNC_MAP.get(val) or val
                        prefix = 'UI_CHR_PlayBonus_'
                        icon_png = self.pic / f'{prefix}{icon_name}.png'
                        if icon_png.exists():
                            im.alpha_composite(self._open(icon_png).resize((60, 60)), (x + 10, y + 12))
                for s_idx in qualified_slots:
                    if is_wu and len(results) == 5:
                        im.alpha_composite(finished_bg[s_idx].resize((14, 14)), (x + 1 + 16 * s_idx, y + 64))
                    else:
                        im.alpha_composite(finished_bg[s_idx], (x + 4 + 19 * s_idx, y + 63))
            if is_current:
                start_y += rows * 96 + 30

        total_count = len(plate_ids)
        text = 'COMPLETED!!!' if finished_songs == total_count else f'{finished_songs}/{total_count}'
        progress = finished_songs / total_count if total_count else 0
        if progress != 0:
            bar = self.plate_progress_big.crop((0, 0, int(993 * progress), 92))
            im.alpha_composite(bar, (204, 219))
        fot.draw(700, 240, 30, text, self.default_text_color, 'mm', 3, (255, 255, 255, 255))
        fot.draw(1190, 240, 30, f'{round(progress * 100, 2)}%', self.default_text_color, 'rm', 3, (255, 255, 255, 255))

        stats_start_y = 300
        stats_start_x = 292 if is_wu else 320
        stats_gap_x = 204 if is_wu else 253
        for _l in range(slot_num):
            x = stats_start_x + _l * stats_gap_x
            plate_count = len(remaster_ids) if (_l == 4 and is_wu) else total_count
            progress_group = (slot_counts[_l] / plate_count) if plate_count else 0
            if progress_group != 0:
                small = self.plate_progress_small_wu if is_wu else self.plate_progress_small
                width = 176 if is_wu else 230
                bar = small.crop((0, 0, int(width * progress_group), 46))
                im.alpha_composite(bar, (x - (89 if is_wu else 115), 326))
            fot.draw(x, stats_start_y, 40, slot_counts[_l], self.id_text_color[_l], 'mm', 4, (255, 255, 255, 255))
            fot.draw(x + (115 if not is_wu else 89), stats_start_y + 20, 14, f'/{plate_count}',
                     self.id_text_color[_l], 'rd', 3, (255, 255, 255, 255))
            fot.draw(x + (115 if not is_wu else 89), 343, 20, f'{round(progress_group * 100, 2)}%',
                     self.default_text_color, 'rm', 2, (255, 255, 255, 255))
        return self.to_bytes(im)

    # ================= 等级进度（DrawScore 移植） =================

    def _decorate_score_bg(self, im: Image.Image) -> None:
        """进度图背景装饰（DrawScore.__init__ 同款）。"""
        im.alpha_composite(self.aurora_bg)
        im.alpha_composite(self.shines_bg, (11, 6))
        im.alpha_composite(self.rainbow_bg, (318, im.height - 545))
        im.alpha_composite(self.rainbow_bottom_bg, (122, im.height - 305))
        for h in range((im.height // 358) + 1):
            im.alpha_composite(self.pattern_bg, (0, (358 + 7) * h))

    def _level_progress_data(self, level: str, plan: str, play_result: List[PlayRecord],
                             total_list):
        """按评价等级划分 已完成/未完成/未游玩。"""
        p = normalize_plan(plan)
        if p in RANK_SP:
            plan_type, plan_value = 0, ACHIEVEMENT_LIST[max(RANK_SP.index(p) - 1, 0)]
        elif p in COMBO_SP:
            plan_type, plan_value = 1, COMBO_SP.index(p)
        else:
            plan_type, plan_value = 2, SYNC_D_SP.index(p)

        played_map = {(r.song_id, r.level_index): r for r in play_result if r.level == level}
        predicate = _score_plan_predicate(p)

        completed: List[PlayRecord] = []
        unfinished: List[PlayRecord] = []
        notplayed: List[Tuple[int, int, float]] = []
        for m in total_list:
            if m.is_utage:
                continue
            for i, lv in enumerate(m.level):
                if lv != level:
                    continue
                res = played_map.get((int(m.id), i))
                if res is not None and predicate(res):
                    completed.append(res)
                elif res is not None:
                    unfinished.append(res)
                else:
                    notplayed.append((int(m.id), i, m.ds[i]))

        key0 = lambda r: r.achievements
        if plan_type == 1:
            completed.sort(key=lambda r: COMBO_SP.index(r.fc) if r.fc in COMBO_SP else -1, reverse=True)
        elif plan_type == 2:
            completed.sort(key=lambda r: SYNC_D_SP.index(r.fs) if r.fs in SYNC_D_SP else -1, reverse=True)
        else:
            completed.sort(key=key0, reverse=True)
        if plan_type == 1:
            unfinished.sort(key=lambda r: COMBO_SP.index(r.fc) if r.fc in COMBO_SP else -1, reverse=True)
        elif plan_type == 2:
            unfinished.sort(key=lambda r: SYNC_D_SP.index(r.fs) if r.fs in SYNC_D_SP else -1, reverse=True)
        else:
            unfinished.sort(key=key0, reverse=True)
        notplayed.sort(key=lambda t: t[2], reverse=True)
        return completed, unfinished, notplayed

    def _while_pic(self, im: Image.Image, data: List[Tuple[int, int]], start_y: int = 200) -> None:
        """未游玩谱面小图网格（20 个一行）。"""
        _sy, tb, _fn = self._drawers(im)
        step, start_x = 65, 55
        for num, (song_id, level_index) in enumerate(data):
            row, col = divmod(num, 20)
            x = start_x + col * step
            y = start_y + row * step
            im.alpha_composite(self._open(self.song_chart(song_id)).resize((55, 55)), (x, y))
            im.alpha_composite(self.diff_pg_bg[level_index], (x - 4, y - 4))
            tb.draw(x + 36, y + 3, 12, song_id, self.diff_text_color[level_index], 'mm')

    def draw_level_progress(self, level: str, plan: str, play_result: List[PlayRecord],
                            total_list, *, category: str = 'default', page: int = 1,
                            bot_name: str = 'MaiBot') -> bytes:
        """源插件 DrawScore：等级进度图（默认三段视图 / 已完成 / 未完成 / 未游玩）。"""
        completed, unfinished, notplayed = self._level_progress_data(level, plan, play_result, total_list)

        def rows(count: int, per: int) -> int:
            return (count + per - 1) // per if count else 0

        if category in ('已完成', '未完成'):
            data = completed if category == '已完成' else unfinished
            per_page = 80
            total_page = max(1, (len(data) - 1) // per_page + 1)
            page = max(1, min(page, total_page))
            display = data[(page - 1) * per_page: page * per_page]
            y_size = max(4, rows(len(display), 5)) * 109
            height = 240 + y_size + 120
            im = tricolor_gradient_prism_plus(1400, height)
            self._decorate_score_bg(im)
            sy, _tb, _fn = self._drawers(im)
            im.alpha_composite(self._themed_asset('title_lengthen.png'), (475, 30))
            sy.draw(700, 77, 28, f'{category}谱面', self.default_text_color, 'mm')
            self._while_score_cards(im, display, 140, total_list=total_list)
            im.alpha_composite(self._themed_asset('design.png'), (200, height - 133))
            pagemsg = (f'{category}谱面共计「{len(data)}」个，'
                       f'当前第「{(page - 1) * per_page + 1}-{(page - 1) * per_page + len(display)}」个，'
                       f'第「{page} / {total_page}」页')
            sy.draw(700, height - 90, 25, pagemsg, self.default_text_color, 'mm')
            self._draw_footer(im, bot_name, height - 32, 22, self.default_text_color)
            return self.to_bytes(im)

        if category in ('未开始', '未游玩'):
            y_size = max(4, rows(len(notplayed), 20)) * 65
            height = max(240 + y_size + 120, 600)
            im = tricolor_gradient_prism_plus(1400, height)
            self._decorate_score_bg(im)
            sy, _tb, _fn = self._drawers(im)
            im.alpha_composite(self._themed_asset('title_lengthen.png'), (475, 30))
            sy.draw(700, 77, 28, '未游玩谱面', self.default_text_color, 'mm')
            self._while_pic(im, [(sid, li) for sid, li, _ds in notplayed])
            im.alpha_composite(self._themed_asset('design.png'), (200, height - 113))
            sy.draw(700, height - 70, 25, f'未游玩谱面共计「{len(notplayed)}」个',
                    self.default_text_color, 'mm')
            self._draw_footer(im, bot_name, height - 28, 22, self.default_text_color)
            return self.to_bytes(im)

        # 默认三段视图
        comp_limit = 60 if not unfinished and not notplayed else 30
        c_y = max(4, rows(len(completed[:comp_limit]), 5)) * 109 + 140
        u_y = max(4, rows(len(unfinished[:30]), 5)) * 109 + 140
        n_y = max(4, rows(len(notplayed[:100]), 20)) * 65 + 140
        height = 150 + c_y + u_y + n_y
        im = tricolor_gradient_prism_plus(1400, height)
        self._decorate_score_bg(im)
        sy, _tb, _fn = self._drawers(im)

        im.alpha_composite(self._themed_asset('title_lengthen.png'), (475, 30))
        im.alpha_composite(self._themed_asset('title_lengthen.png'), (475, 30 + c_y))
        im.alpha_composite(self._themed_asset('title_lengthen.png'), (475, 30 + c_y + u_y))

        sy.draw(700, 77, 25, f'已完成谱面「{len(completed)}」个', self.default_text_color, 'mm')
        sy.draw(1300, 77, 20, f'可使用「{level}{plan.upper()}已完成进度」\n指令查询详细列表',
                self.default_text_color, 'rm', 2, (255, 255, 255, 255), True)
        sy.draw(700, 77 + c_y, 25, f'未完成谱面「{len(unfinished)}」个', self.default_text_color, 'mm')
        sy.draw(1300, 77 + c_y, 20, f'可使用「{level}{plan.upper()}未完成进度」\n指令查询详细列表',
                self.default_text_color, 'rm', 2, (255, 255, 255, 255), True)
        sy.draw(700, 77 + c_y + u_y, 25, f'未游玩谱面「{len(notplayed)}」个', self.default_text_color, 'mm')

        self._while_score_cards(im, completed[:comp_limit], 140, total_list=total_list)
        self._while_score_cards(im, unfinished[:30], 140 + c_y, total_list=total_list)
        self._while_pic(im, [(sid, li) for sid, li, _ds in notplayed[:100]], 140 + c_y + u_y)

        im.alpha_composite(self._themed_asset('design.png'), (200, height - 133))
        pagemsg = (f'「{level}」共计「{len(completed) + len(unfinished) + len(notplayed)}」个谱面，'
                   f'剩余「{len(unfinished) + len(notplayed)}」个谱面未完成「{plan.upper()}」')
        sy.draw(700, height - 90, 22, pagemsg, self.default_text_color, 'mm')
        self._draw_footer(im, bot_name, height - 32, 22, self.default_text_color)
        return self.to_bytes(im)

    # ================= 牌子进度图（DrawPlateProgress 移植） =================

    def draw_plate_progress(self, version: str, plan: str, version_name: str,
                            plate_ids: List[int], remaster_ids: List[int],
                            records: List[PlayRecord], total_list,
                            bot_name: str = 'MaiBot') -> bytes:
        """源插件 DrawPlateProgress：牌子进度图（各难度进度条 + 未完成曲绘网格）。"""
        if plan == '舞':
            plan = '舞舞'
        is_wu = version in ('舞', '霸')
        slot_num = 5 if is_wu else 4

        song_list = total_list.by_id_list(plate_ids)
        remaster_set = {int(i) for i in remaster_ids}
        song_id_to_level = {
            s.id: (s.level[4] if (s.id in remaster_set and len(s.level) > 4) else s.level[3])
            for s in song_list
        } if is_wu else {s.id: s.level[3] for s in song_list}
        songs_by_id = {s.id: s for s in song_list}

        played_map: Dict[str, Dict[str, List[Optional[PlayRecord]]]] = {}
        for lv in sorted(set(song_id_to_level.values()), key=lambda x: LEVEL_LIST.index(x) if x in LEVEL_LIST else 99):
            played_map[lv] = {}
        for s in sorted(song_list, key=lambda m: (m.ds[4] if (m.id in remaster_set and len(m.ds) > 4) else m.ds[3]),
                        reverse=True):
            slot = 5 if (is_wu and s.id in remaster_set) else 4
            played_map[song_id_to_level[s.id]][s.id] = [None] * slot
        for d in records:
            if str(d.song_id) not in song_id_to_level:
                continue
            if slot_num == 4 and d.level_index == 4:
                continue
            slots = played_map.get(song_id_to_level[str(d.song_id)], {}).get(str(d.song_id))
            if slots is not None and d.level_index < len(slots):
                slots[d.level_index] = d

        # 各难度未完成列表 + 计数
        difficulty_results: Dict[int, List[Tuple[float, int, Optional[PlayRecord], bool]]] = {
            i: [] for i in range(slot_num)}
        slot_counts = [0] * slot_num
        finished_songs = 0
        for lv in played_map:
            for sid, results in played_map[lv].items():
                m = songs_by_id[sid]
                qualified_slots = [i for i, p in enumerate(results) if self._plate_qualified(p, plan)]
                for i, q in enumerate(qualified_slots):
                    slot_counts[i] += 1
                if results and len(qualified_slots) == len(results):
                    finished_songs += 1
                for i in range(slot_num):
                    ds = m.ds[i] if i < len(m.ds) else 0
                    difficulty_results[i].append((ds, int(sid), results[i], i in qualified_slots))
        for i in range(slot_num):
            difficulty_results[i].sort(key=lambda t: t[0], reverse=True)
        total_count = len(plate_ids)

        results = {i: [t for t in difficulty_results[i] if not t[3]] for i in range(slot_num)}
        total_counts = [len(difficulty_results[i]) for i in range(slot_num)]
        display_counts = [len(results[i]) for i in range(slot_num)]

        def disp_rows(count: int) -> int:
            return 1 if count <= 0 else min((count - 1) // 13 + 1, 4)

        current_y = 395
        for c in display_counts:
            current_y += disp_rows(c) * 96 + 100
        height = current_y + 180

        _im = self._generate_bg(height, 305)
        im = generate_frosted_card(_im, (50, 349, 1350, current_y))
        sy, _tb, fot = self._drawers(im)
        color = self.text_color()

        im.alpha_composite(self.plate_progress_2, (175, 20))
        plan_char = '極' if plan == '极' else plan
        plate_title = self.plate_version_dir / f'{version}{plan_char}.png'
        if plate_title.exists():
            im.alpha_composite(self._open(plate_title).resize((1000, 161)), (200, 35))

        START_X, START_Y = 84, 455
        end = None if slot_num == 5 else -1
        new_slot_counts = slot_counts[::-1]
        new_color = self.id_text_color[:end][::-1] if end else self.id_text_color[::-1]
        new_diffs = DIFFS[:end][::-1] if end else DIFFS[::-1]
        for n, unfinished_list in enumerate(list(results.values())[::-1]):
            im.alpha_composite(self.plate_progress_bottom_bg, (198, START_Y - 85))
            complete_sum_group = new_slot_counts[n]
            plate_count = total_counts[n]
            progress_group = complete_sum_group / plate_count if plate_count else 0
            if progress_group != 0:
                bar = self.plate_progress_big.crop((0, 0, int(993 * progress_group), 92))
                im.alpha_composite(bar, (204, START_Y - 79))
            c_text = 'COMPLETED!!!' if complete_sum_group == plate_count else f'{complete_sum_group}/{plate_count}'
            fot.draw(220, START_Y - 57, 34, new_diffs[n], new_color[n], 'lm', 4, (255, 255, 255, 255))
            fot.draw(700, START_Y - 57, 36, c_text, new_color[n], 'mm', 4, (255, 255, 255, 255))
            fot.draw(1190, START_Y - 57, 20, f'{round(progress_group * 100, 2)}%',
                     new_color[n], 'rm', 2, (255, 255, 255, 255))

            max_row = 0
            for num, (_ds, sid, _res, _q) in enumerate(unfinished_list):
                row, col = divmod(num, 13)
                max_row = max(max_row, row)
                x = START_X + col * 96
                y = START_Y + row * 96
                if num >= 51 and len(unfinished_list[num:]) != 1:
                    fot.draw(x, y + 35, 20, f'余「{len(unfinished_list[num:])}」\n个未完成',
                             self.default_text_color, 'lm', multiline=True)
                    break
                im.alpha_composite(self._open(self.song_chart(sid)).resize((80, 80)), (x, y))
                im.alpha_composite(self.table_id_bg, (x - 5, y - 5))
                _tb.draw(x + 56, y + 4, 16, sid, anchor='mm')
            START_Y += (max_row + 1) * 96 + 100

        text = 'COMPLETED!!!' if finished_songs == total_count else f'{finished_songs}/{total_count}'
        progress = finished_songs / total_count if total_count else 0
        if progress != 0:
            bar = self.plate_progress_big.crop((0, 0, int(993 * progress), 92))
            im.alpha_composite(bar, (204, 219))
        fot.draw(700, 240, 30, text, self.default_text_color, 'mm', 3, (255, 255, 255, 255))
        fot.draw(1190, 240, 30, f'{round(progress * 100, 2)}%', self.default_text_color, 'rm', 3, (255, 255, 255, 255))
        self._draw_footer(im, bot_name, height - 75, 24, color)
        return self.to_bytes(im)


# ---------- 等级进度辅助 ----------

PLAN_NORMALIZE = {
    's+': 'sp', 'ss+': 'ssp', 'sss+': 'sssp',
    'fc+': 'fcp', 'ap+': 'app', 'fs+': 'fsp',
    'fdx': 'fsd', 'fdxp': 'fsdp',
}


def normalize_plan(plan: str) -> str:
    p = (plan or '').lower().strip()
    return PLAN_NORMALIZE.get(p, p)


def _score_plan_predicate(p: str):
    """评价等级 -> 谱面是否达标。"""
    if p in RANK_SP:
        value = ACHIEVEMENT_LIST[max(RANK_SP.index(p) - 1, 0)]
        return lambda r: r.achievements >= value
    if p in COMBO_SP:
        idx = COMBO_SP.index(p)
        return lambda r: bool(r.fc) and r.fc in COMBO_SP and COMBO_SP.index(r.fc) >= idx
    if p in SYNC_D_SP:
        idx = SYNC_D_SP.index(p)
        return lambda r: bool(r.fs) and r.fs in SYNC_D_SP and SYNC_D_SP.index(r.fs) >= idx
    return lambda r: False


def notes_columns(chart) -> List:
    """把谱面 notes 规范成 [total, tap, hold, slide, touch, brk] 六列。

    diving-fish 的 notes 数组：SD 为 4 值 [tap, hold, slide, brk]，
    DX 为 5 值 [tap, hold, slide, touch, brk]；SD 无 touch，显示 '-'。
    """
    notes = list(chart.notes)
    if len(notes) >= 5:
        tap, hold, slide, touch, brk = notes[0], notes[1], notes[2], notes[3], notes[4]
    elif len(notes) == 4:
        tap, hold, slide, touch, brk = notes[0], notes[1], notes[2], '-', notes[3]
    else:
        tap, hold, slide, touch, brk = (notes + ['-'] * 4)[:4] + ['-']
    total = sum(n for n in notes if isinstance(n, int))
    return [total, tap, hold, slide, touch, brk]


def to_base64_data(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, 'PNG')
    return base64.b64encode(buf.getvalue()).decode()
