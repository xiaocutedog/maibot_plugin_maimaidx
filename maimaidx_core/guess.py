"""猜歌游戏：文字提示生成、答案校验、曲绘频域加权裁剪（移植原版算法）。

裁剪无 numpy 时退化为随机裁剪，不影响游戏进行。
"""

import random
from typing import List, Optional

from .model import Music

try:
    import numpy as np
    NUMPY_OK = True
except ImportError:  # pragma: no cover
    NUMPY_OK = False

try:
    from PIL import Image
    PIL_OK = True
except ImportError:  # pragma: no cover
    PIL_OK = False


def guess_pool(music_list) -> List[Music]:
    """猜歌曲目池：游玩次数超过 1 万次的热门曲（排除宴会场）。"""
    pool = []
    for m in music_list:
        if m.is_utage or not m.stats:
            continue
        cnt = sum((s.cnt or 0) for s in m.stats if s is not None)
        if cnt > 10000:
            pool.append(m)
    return pool


def build_hints(music: Music) -> List[str]:
    """8 个候选提示中随机抽 6 个（与原版一致）。"""
    def _lv(i: int, name: str) -> str:
        return f'的 {name} 难度是 {music.level[i]}' if i < len(music.level) else f'没有 {name} 难度'

    options = [
        _lv(2, 'Expert'),
        _lv(3, 'Master'),
        f'的分类是 {music.basic_info.genre}',
        f'的版本是 {music.basic_info.version}',
        f'的曲师是 {music.basic_info.artist}',
        f'{"不" if music.type == "SD" else ""}是 DX 谱面',
        f'{"没" if len(music.ds) == 4 else ""}有白谱（Re:Master）',
        f'的 BPM 是 {music.basic_info.bpm}',
    ]
    return random.sample(options, 6)


def build_answers(music: Music, aliases: List[str]) -> List[str]:
    """归一化答案集合：别名 + 曲名 + 曲目 ID。"""
    answers = set()
    for a in list(aliases) + [music.title, str(music.id)]:
        a = ''.join(str(a).split()).strip().lower()
        if a:
            answers.add(a)
    return sorted(answers)


def check_answer(music: Music, aliases: List[str], text: str) -> bool:
    """答题文本归一化（去空白、转小写）后与答案集合比对。"""
    norm = ''.join(str(text).split()).lower()
    return norm in build_answers(music, aliases)


def crop_cover(cover_bytes: bytes, grayscale: bool = False) -> Optional[bytes]:
    """曲绘频域加权随机裁剪，返回 PNG bytes；失败返回 None。

    思路与原版一致：对灰度图做 FFT，按频率幅值平方作为权重，
    在高信息密度区域中加权随机选取裁剪窗口（尺寸 15%~40%），
    避免总是裁到画面中心或纯色区域。

    Params:
        `grayscale`: 为 True 时输出黑白图（猜黑白曲绘模式）
    """
    if not PIL_OK:
        return None
    import io

    try:
        image = Image.open(io.BytesIO(cover_bytes)).convert('RGB')
    except Exception:  # noqa: BLE001
        return None
    w, h = image.size
    scale = random.uniform(0.15, 0.4)
    w2, h2 = int(w * scale), int(h * scale)
    if w2 < 10 or h2 < 10 or w2 >= w or h2 >= h:
        cropped = image
    elif not NUMPY_OK:
        x = random.randint(0, w - w2)
        y = random.randint(0, h - h2)
        cropped = image.crop((x, y, x + w2, y + h2))
    else:
        gray = np.array(image.convert('L'))
        magnitude = np.abs(np.fft.fftshift(np.fft.fft2(gray)))
        max_mag = magnitude.max()
        if max_mag <= 0:
            x = random.randint(0, w - w2)
            y = random.randint(0, h - h2)
            cropped = image.crop((x, y, x + w2, y + h2))
        else:
            weights = (magnitude / max_mag) ** 2
            valid = weights[:h - h2 + 1, :w - w2 + 1]
            flat = valid.flatten()
            top_p = min(1.3 - float(np.power(scale, 0.4)), 0.95) * 100
            threshold = np.percentile(flat, top_p)
            indices = np.where(flat >= threshold)[0]
            probs = flat[indices]
            probs = probs / probs.sum()
            chosen = int(np.random.choice(indices, p=probs))
            top_left_y = chosen // valid.shape[1]
            top_left_x = chosen % valid.shape[1]
            cropped = image.crop((top_left_x, top_left_y, top_left_x + w2, top_left_y + h2))
    if grayscale:
        cropped = cropped.convert('L')
    buf = io.BytesIO()
    cropped.save(buf, format='PNG')
    return buf.getvalue()
