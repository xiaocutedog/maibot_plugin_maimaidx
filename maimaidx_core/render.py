"""PIL 图片渲染：曲目详情卡 / 查歌列表 / B50 成绩单 / 帮助菜单。

Pillow 缺失或找不到中文字体时，所有函数返回 None，由调用方回退纯文本输出。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Optional, Sequence

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_OK = True
except ImportError:  # pragma: no cover - Pillow 为可选依赖
    PILLOW_OK = False

from .format import FC_MAP, FS_MAP
from .model import DIFF_NAMES, Music, UserInfo

DIFF_COLORS = {
    0: (34, 197, 0),      # Basic 绿
    1: (251, 150, 0),     # Advanced 橙
    2: (246, 72, 97),     # Expert 红
    3: (186, 109, 230),   # Master 紫
    4: (235, 64, 220),    # Re:Master 品红
    5: (128, 128, 128),   # UTAGE 灰
}

_FONT_PATH: Optional[str] = None
_FONT_CACHE = {}


def _detect_font() -> Optional[str]:
    import os

    # MiSans 随插件分发，覆盖假名/生僻字/符号最全，优先于系统字体
    misans = Path(__file__).resolve().parent.parent / 'fonts' / 'MiSans-Regular.ttf'
    candidates = [
        os.environ.get('MAIMAIDX_FONT', ''),
        str(misans),
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/msyh.ttf',
        'C:/Windows/Fonts/simhei.ttf',
        'C:/Windows/Fonts/deng.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def init_fonts(font_path: str = '', extra_dirs: Optional[Sequence] = None) -> bool:
    """初始化字体，返回是否可用。extra_dirs 中名为 font.ttf/.otf/.ttc 的文件优先。"""
    global _FONT_PATH
    if not PILLOW_OK:
        return False
    path = font_path.strip()
    if not path:
        for d in (extra_dirs or []):
            for name in ('font.ttf', 'font.otf', 'font.ttc'):
                candidate = f'{str(d)}/{name}'
                import os
                if os.path.exists(candidate):
                    path = candidate
                    break
            if path:
                break
    if not path:
        path = _detect_font() or ''
    if not path:
        return False
    try:
        ImageFont.truetype(path, 20)
    except Exception:  # noqa: BLE001
        return False
    _FONT_PATH = path
    _FONT_CACHE.clear()
    return True


def available() -> bool:
    return PILLOW_OK and bool(_FONT_PATH)


def _font(size: int):
    key = (_FONT_PATH, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(_FONT_PATH, size)
    return _FONT_CACHE[key]


def _measure(text: str, size: int) -> float:
    img = Image.new('RGB', (10, 10))
    draw = ImageDraw.Draw(img)
    return draw.textlength(text, font=_font(size))


def _truncate(draw: ImageDraw.ImageDraw, text: str, size: int, max_w: float) -> str:
    if draw.textlength(text, font=_font(size)) <= max_w:
        return text
    while text and draw.textlength(text + '…', font=_font(size)) > max_w:
        text = text[:-1]
    return text + '…'


def _wrap(text: str, size: int, max_w: float, max_lines: int = 0) -> List[str]:
    lines: List[str] = []
    current = ''
    for ch in text:
        if ch == '\n':
            lines.append(current)
            current = ''
            continue
        if _measure(current + ch, size) > max_w:
            lines.append(current)
            current = ch
        else:
            current += ch
    if current or not lines:
        lines.append(current)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip('…') + '…'
    return lines


def _gradient(w: int, h: int, top=(124, 129, 255), bottom=(193, 247, 225)) -> Image.Image:
    img = Image.new('RGB', (w, h), 'white')
    draw = ImageDraw.Draw(img)
    for y in range(h):
        ratio = y / max(h - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _panel(w: int, h: int) -> Image.Image:
    img = _gradient(w, h)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([10, 10, w - 11, h - 11], radius=18, fill=(255, 255, 255))
    return img


def _badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color,
           fg=(255, 255, 255), size: int = 18) -> int:
    tw = draw.textlength(text, font=_font(size))
    pad_x, pad_y = 10, 6
    draw.rounded_rectangle(
        [x, y, x + tw + pad_x * 2, y + size + pad_y * 2],
        radius=8, fill=color)
    draw.text((x + pad_x, y + pad_y - 1), text, font=_font(size), fill=fg)
    return tw + pad_x * 2


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def song_info_image(music: Music, aliases: Optional[List[str]] = None,
                    cover_bytes: Optional[bytes] = None) -> Optional[bytes]:
    """曲目详情卡。"""
    if not available():
        return None
    W, pad = 780, 32
    bi = music.basic_info
    img = _panel(W, 2200)
    draw = ImageDraw.Draw(img)
    y = pad

    # ---- 头部：曲绘 + 标题 ----
    cover_h = 0
    cover = None
    if cover_bytes:
        try:
            cover = Image.open(io.BytesIO(cover_bytes)).convert('RGB')
            cover = cover.resize((150, 150))
        except Exception:  # noqa: BLE001
            cover = None
    if cover:
        img.paste(cover, (pad, y))
        draw.rounded_rectangle([pad - 2, y - 2, pad + 152, y + 152], radius=10, outline=(210, 210, 210), width=2)
        text_x = pad + 170
        cover_h = 150
    else:
        text_x = pad

    title_max = W - pad - text_x
    title_lines = _wrap(music.title, 34, title_max, max_lines=3)
    ty = y
    for line in title_lines:
        draw.text((text_x, ty), line, font=_font(34), fill=(40, 40, 40))
        ty += 46
    ty += 10
    bx = text_x
    bx += _badge(draw, bx, ty, f'ID {music.id}', (90, 200, 250)) + 8
    bx += _badge(draw, bx, ty, bi.genre or '未知分类', (255, 140, 105)) + 8
    bx += _badge(draw, bx, ty, 'DX谱面' if music.type == 'DX' else '标准谱面',
                 (255, 176, 32) if music.type == 'DX' else (150, 150, 150))
    ty += 36
    draw.text((text_x, ty), _truncate(draw, f'版本: {bi.version or "未知"}', 22, title_max),
              font=_font(22), fill=(90, 90, 90))
    ty += 32
    head_bottom = max(y + cover_h, ty) + 18
    if not cover:
        head_bottom = ty + 18
    y = head_bottom

    # ---- 曲师 / BPM ----
    draw.text((pad, y), _truncate(draw, f'曲师: {bi.artist or "-"}', 24, W - pad * 2 - 160),
              font=_font(24), fill=(60, 60, 60))
    bpm_text = f'BPM: {bi.bpm or "-"}'
    draw.text((W - pad - _measure(bpm_text, 24), y), bpm_text, font=_font(24), fill=(60, 60, 60))
    y += 36

    # ---- 别名 ----
    if aliases:
        alias_text = '别名: ' + '、'.join(aliases[:10])
        for line in _wrap(alias_text, 21, W - pad * 2, max_lines=3):
            draw.text((pad, y), line, font=_font(21), fill=(140, 140, 140))
            y += 29
        y += 6

    # ---- 分隔线 ----
    draw.line([(pad, y), (W - pad, y)], fill=(225, 225, 225), width=2)
    y += 16

    # ---- 难度表 ----
    col_lv, col_ds, col_fit, col_ch = 250, 370, 500, 640
    header = [('难度', pad), ('等级', col_lv), ('定数', col_ds), ('拟合定数', col_fit), ('谱师', col_ch)]
    for text, x in header:
        draw.text((x, y), text, font=_font(22), fill=(150, 150, 150))
    y += 34
    count = max(len(music.level), len(music.ds), len(music.charts))
    for i in range(count):
        chip_text = DIFF_NAMES[i] if i < len(DIFF_NAMES) else f'Diff{i}'
        color = DIFF_COLORS.get(i, (128, 128, 128))
        fg = (60, 60, 60) if i == 4 else (255, 255, 255)
        _badge(draw, pad, y, chip_text, color, fg=fg, size=19)
        lv = music.level[i] if i < len(music.level) else '-'
        dsv = f'{music.ds[i]:.1f}' if i < len(music.ds) else '-'
        fit = music.fit_diff(i)
        fitv = f'{fit:.2f}' if fit is not None else '-'
        ch = music.charter(i)
        row_y = y + 1
        draw.text((col_lv, row_y), lv, font=_font(22), fill=(70, 70, 70))
        draw.text((col_ds, row_y), dsv, font=_font(22), fill=(70, 70, 70))
        draw.text((col_fit, row_y), fitv, font=_font(22),
                  fill=(230, 120, 30) if fit is not None else (170, 170, 170))
        draw.text((col_ch, row_y), _truncate(draw, ch, 22, W - pad - col_ch),
                  font=_font(22), fill=(70, 70, 70))
        y += 44
    y += 6
    draw.text((pad, y), '※ 定数/拟合定数数据来自水鱼查分器（fit_diff 为全体玩家拟合值）',
              font=_font(18), fill=(170, 170, 170))
    y += 30

    img = img.crop((0, 0, W, y + pad))
    return _png_bytes(img)


def list_image(header: str, rows: Sequence[str], footer: str) -> Optional[bytes]:
    """查歌结果列表图。"""
    if not available():
        return None
    W, pad = 1000, 28
    row_h, size = 40, 23
    head_h = 64
    H = head_h + pad + len(rows) * row_h + 40 + pad
    img = _panel(W, max(H, 200))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([10, 10, W - 11, head_h], radius=18, fill=(98, 126, 244))
    draw.rectangle([10, head_h - 30, W - 11, head_h], fill=(98, 126, 244))
    draw.text((pad, 18), _truncate(draw, header, 28, W - pad * 2),
              font=_font(28), fill=(255, 255, 255))
    y = head_h + pad
    for idx, row in enumerate(rows):
        if idx % 2 == 1:
            draw.rounded_rectangle([pad - 8, y - 5, W - pad + 8, y + row_h - 11],
                                   radius=8, fill=(243, 246, 252))
        draw.text((pad, y), _truncate(draw, row, size, W - pad * 2),
                  font=_font(size), fill=(55, 55, 55))
        y += row_h
    y += 8
    draw.text((pad, y), _truncate(draw, footer, 19, W - pad * 2),
              font=_font(19), fill=(150, 150, 150))
    return _png_bytes(img.crop((0, 0, W, y + 34)))


def b50_image(user: UserInfo) -> Optional[bytes]:
    """B50 成绩单。"""
    if not available():
        return None
    W, pad = 1080, 30
    row_h, size = 38, 21

    def count_rows() -> int:
        charts = user.charts
        n = 0
        if charts and charts.sd:
            n += 1 + len(charts.sd)
        if charts and charts.dx:
            n += 1 + len(charts.dx)
        return n

    head_h = 120
    H = head_h + pad + count_rows() * row_h + 70 + pad
    img = _panel(W, max(H, 300))
    draw = ImageDraw.Draw(img)

    # 头部
    draw.rounded_rectangle([10, 10, W - 11, head_h], radius=18, fill=(72, 96, 226))
    draw.rectangle([10, head_h - 34, W - 11, head_h], fill=(72, 96, 226))
    name = user.nickname or user.username or '未知用户'
    draw.text((pad, 18), _truncate(draw, f'maimaiDX B50 — {name}', 30, W - pad * 2 - 320),
              font=_font(30), fill=(255, 255, 255))
    ra_text = f'Ra {user.rating if user.rating is not None else "-"}'
    dx_text = f'DX Rating {user.additional_rating if user.additional_rating is not None else "-"}'
    draw.text((W - pad - _measure(dx_text, 24), 22), dx_text, font=_font(24), fill=(255, 255, 255))
    draw.text((W - pad - _measure(dx_text, 24) - _measure(ra_text, 24) - 30, 24), ra_text,
              font=_font(24), fill=(255, 226, 110))
    if user.plate:
        draw.text((pad, 66), f'牌子: {user.plate}', font=_font(20), fill=(214, 224, 255))
    y = head_h + pad - 8

    charts = user.charts
    has_data = False

    def block(title: str, data: Sequence[PlayChart]) -> None:
        nonlocal y, has_data
        if not data:
            return
        has_data = True
        draw.text((pad, y), title, font=_font(24), fill=(98, 126, 244))
        y += 40
        for i, c in enumerate(data, 1):
            if i % 2 == 0:
                draw.rounded_rectangle([pad - 8, y - 4, W - pad + 8, y + row_h - 10],
                                       radius=8, fill=(243, 246, 252))
            marks = FC_MAP.get(c.fc, c.fc if c.fc else '')
            sync = FS_MAP.get(c.fs, c.fs if c.fs else '')
            badge = '/'.join(x for x in (marks, sync) if x)
            line = (f'{i:>2}. {c.achievements:.4f}%  Ra {c.ra:>4}  '
                    f'[{c.level}·{c.ds:.1f}] {c.title}' + (f'  {badge}' if badge else ''))
            draw.text((pad, y), _truncate(draw, line, size, W - pad * 2),
                      font=_font(size), fill=(55, 55, 55))
            y += row_h
        y += 6

    if charts and charts.sd:
        block('【旧版本 B35】', charts.sd)
    if charts and charts.dx:
        block('【新版本 B15】', charts.dx)
    if not has_data:
        draw.text((pad, y), '（无成绩数据，请确认该用户已在查分器上传成绩）',
                  font=_font(22), fill=(150, 150, 150))
        y += 40
    return _png_bytes(img.crop((0, 0, W, y + pad)))


def help_image() -> Optional[bytes]:
    """maihelp 帮助菜单。"""
    if not available():
        return None
    W, pad = 860, 30
    size, line_h = 22, 36
    sections: List[tuple] = [
        ('查歌 / 随机', (98, 126, 244), [
            ('查歌 关键词 [页码]', '按曲名/别名查歌'),
            ('xxx是什么歌', '通过别名反查乐曲'),
            ('id 曲目ID', '定数/拟合定数/版本/难度/曲师/谱师'),
            ('随机 变量 值', '按条件随机：定数/拟合定数/版本/难度/分区/曲师/谱师/定数差距'),
            ('随机 定数 14.0-14.2', '区间用 - 连接；难度：随机 难度 紫'),
            ('随机 分区 东方', '分区：舞萌/流行&动漫/niconico/东方/其他游戏/音击/宴会场'),
            ('随个 [dx/sd] [颜色] 等级', '随机曲目，如：随个紫14+'),
            ('今日mai', '今日运势与推荐歌曲'),
            ('mai什么', '随机来一首（mai什么推分）'),
        ]),
        ('筛选查歌', (255, 140, 105), [
            ('定数查歌 定数 [上限] [页码]', '按歌曲定数筛选'),
            ('拟合查歌 定数 [上限] [页码]', '按拟合定数筛选'),
            ('曲师查歌 / 谱师查歌 / bpm查歌', '名称 [页码]'),
            ('14定数表', '该等级定数列表'),
        ]),
        ('查分', (72, 96, 226), [
            ('b50 [用户名/QQ号]', 'B50 成绩单（不填查自己）'),
            ('minfo 曲目', '查自己的单曲成绩'),
            ('查成绩 用户名/QQ号 曲目', '查他人单曲成绩'),
            ('查看排名 [用户名] [页码] / 我的排名', 'Rating 排行'),
            ('我要上10分', '基于 B50 的推分建议'),
            ('分数线 紫799 100', '分数线容错（分数线 帮助）'),
        ]),
        ('猜歌游戏', (255, 108, 152), [
            ('开始猜歌', '文字提示猜歌（热门曲）'),
            ('猜曲绘', '裁剪曲绘猜歌'),
            ('猜黑白曲绘', '曲绘黑白化后猜歌'),
            ('答案 歌名', '也支持 答案是歌名 / 答案：歌名'),
            ('结束猜歌', '放弃并公布答案（5 分钟超时）'),
        ]),
        ('进度查询', (186, 109, 230), [
            ('爽将进度 / 真極进度', '版本牌子进度'),
            ('14 sss 进度', '等级进度（10+ 起，s 起）'),
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
    rows = sum(len(items) + 1 for _, _, items in sections)
    H = 96 + rows * line_h + len(sections) * 14 + pad * 2
    img = _panel(W, H)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([10, 10, W - 11, 88], radius=18, fill=(255, 108, 152))
    draw.rectangle([10, 60, W - 11, 88], fill=(255, 108, 152))
    draw.text((pad, 24), 'maimaiDX 查分帮助', font=_font(32), fill=(255, 255, 255))
    draw.text((W - pad - _measure('数据来源：水鱼查分器', 18), 46), '数据来源：水鱼查分器',
              font=_font(18), fill=(255, 228, 238))
    y = 96 + pad
    for title, color, items in sections:
        draw.rounded_rectangle([pad, y + 2, pad + 10, y + 26], radius=4, fill=color)
        draw.text((pad + 20, y), title, font=_font(25), fill=color)
        y += 42
        for cmd, desc in items:
            draw.text((pad + 16, y), f'· {cmd}', font=_font(size), fill=(55, 55, 55))
            desc_x = pad + 420
            draw.text((desc_x, y), _truncate(draw, desc, 20, W - pad - desc_x),
                      font=_font(20), fill=(150, 150, 150))
            y += line_h
        y += 8
    return _png_bytes(img.crop((0, 0, W, y + pad)))
