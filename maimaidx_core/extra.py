"""原版插件移植的扩展功能：运势 / RA 计算 / 牌子与等级进度 / 上分建议 / 分数线。"""

import time
from typing import Callable, Dict, List, Optional, Tuple

# ---------- 等级 / 评价表 ----------

LEVEL_LIST: List[str] = [
    '1', '2', '3', '4', '5', '6', '7', '7+', '8', '8+', '9', '9+',
    '10', '10+', '11', '11+', '12', '12+', '13', '13+', '14', '14+', '15',
]

SCORE_RANK: List[str] = ['d', 'c', 'b', 'bb', 'bbb', 'a', 'aa', 'aaa', 's', 's+', 'ss', 'ss+', 'sss', 'sss+']
RANK_MIN_ACH: Dict[str, float] = {
    'd': 0, 'c': 50, 'b': 60, 'bb': 70, 'bbb': 75, 'a': 80, 'aa': 90, 'aaa': 94,
    's': 97, 's+': 98, 'ss': 99, 'ss+': 99.5, 'sss': 100, 'sss+': 100.5,
}
COMBO_RANK: List[str] = ['fc', 'fcp', 'ap', 'app']
SYNC_RANK: List[str] = ['fs', 'fsp', 'fsd', 'fsdp']
SYNC_ALIAS = {'fdx': 'fsd', 'fdxp': 'fsdp'}

DIFFS: List[str] = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master']
COLOR_TO_INDEX: Dict[str, int] = {'绿': 0, '黄': 1, '红': 2, '紫': 3, '白': 4}

# ---------- 版本（牌子）映射 ----------

PLATE_TO_SD_VERSION: Dict[str, str] = {
    '初': 'maimai', '真': 'maimai PLUS', '超': 'maimai GreeN', '檄': 'maimai GreeN PLUS',
    '橙': 'maimai ORANGE', '暁': 'maimai ORANGE PLUS', '晓': 'maimai ORANGE PLUS',
    '桃': 'maimai PiNK', '櫻': 'maimai PiNK PLUS', '樱': 'maimai PiNK PLUS',
    '紫': 'maimai MURASAKi', '菫': 'maimai MURASAKi PLUS', '堇': 'maimai MURASAKi PLUS',
    '白': 'maimai MiLK', '雪': 'MiLK PLUS', '輝': 'maimai FiNALE', '辉': 'maimai FiNALE',
}
PLATE_TO_DX_VERSION: Dict[str, str] = {
    **PLATE_TO_SD_VERSION,
    '熊': 'maimai でらっくす', '華': 'maimai でらっくす PLUS', '华': 'maimai でらっくす PLUS',
    '爽': 'maimai でらっくす Splash', '煌': 'maimai でらっくす Splash PLUS',
    '宙': 'maimai でらっくす UNiVERSE', '星': 'maimai でらっくす UNiVERSE PLUS',
    '祭': 'maimai でらっくす FESTiVAL', '祝': 'maimai でらっくす FESTiVAL PLUS',
    '双': 'maimai でらっくす BUDDiES', '宴': 'maimai でらっくす BUDDiES PLUS',
    '镜': 'maimai でらっくす PRiSM',
}
PLATE_CN = {'晓': '暁', '樱': '櫻', '堇': '菫', '辉': '輝', '华': '華'}
VERSION_MAP: Dict[str, tuple] = {
    '真': ([PLATE_TO_DX_VERSION['真'], PLATE_TO_SD_VERSION['初']], '真'),
    '超': ([PLATE_TO_SD_VERSION['超']], '超'),
    '檄': ([PLATE_TO_SD_VERSION['檄']], '檄'),
    '橙': ([PLATE_TO_SD_VERSION['橙']], '橙'),
    '暁': ([PLATE_TO_SD_VERSION['暁']], '暁'),
    '桃': ([PLATE_TO_SD_VERSION['桃']], '桃'),
    '櫻': ([PLATE_TO_SD_VERSION['櫻']], '櫻'),
    '紫': ([PLATE_TO_SD_VERSION['紫']], '紫'),
    '菫': ([PLATE_TO_SD_VERSION['菫']], '菫'),
    '白': ([PLATE_TO_SD_VERSION['白']], '白'),
    '雪': ([PLATE_TO_SD_VERSION['雪']], '雪'),
    '輝': ([PLATE_TO_SD_VERSION['輝']], '輝'),
    '舞': (list(set(PLATE_TO_SD_VERSION.values())), '舞'),
    '霸': (list(set(PLATE_TO_SD_VERSION.values())), '舞'),
    '熊': ([PLATE_TO_DX_VERSION['熊']], '熊&华'),
    '华': ([PLATE_TO_DX_VERSION['熊']], '熊&华'),
    '華': ([PLATE_TO_DX_VERSION['熊']], '熊&华'),
    '爽': ([PLATE_TO_DX_VERSION['爽']], '爽&煌'),
    '煌': ([PLATE_TO_DX_VERSION['爽']], '爽&煌'),
    '宙': ([PLATE_TO_DX_VERSION['宙']], '宙&星'),
    '星': ([PLATE_TO_DX_VERSION['宙']], '宙&星'),
    '祭': ([PLATE_TO_DX_VERSION['祭']], '祭&祝'),
    '祝': ([PLATE_TO_DX_VERSION['祭']], '祭&祝'),
    '双': ([PLATE_TO_DX_VERSION['双']], '双&宴'),
    '宴': ([PLATE_TO_DX_VERSION['双']], '双&宴'),
    '镜': ([PLATE_TO_DX_VERSION['镜']], '镜'),
    '彩': (['maimai でらっくす PRiSM'], '彩'),
}
ALL_DX_VERSIONS: List[str] = list(set(PLATE_TO_DX_VERSION.values()))

# ---------- 运势 ----------

FORTUNE_LIST = ['拼机', '推分', '越级', '下埋', '夜勤', '练底力', '练手法', '打旧框', '干饭', '抓绝赞', '收歌']


def qqhash(qq: int) -> int:
    days = int(time.strftime('%d', time.localtime())) + 31 * int(time.strftime('%m', time.localtime())) + 77
    return (days * qq) >> 8


def today_fortune(qq: int) -> Dict[str, object]:
    """按原版 qqhash 算法生成当日运势与推荐歌曲下标。"""
    h = qqhash(qq)
    rp = h % 100
    fortune: List[str] = []
    for i in range(11):
        value = h & 3
        h >>= 2
        if value == 3:
            fortune.append(f'宜 {FORTUNE_LIST[i]}')
        elif value == 0:
            fortune.append(f'忌 {FORTUNE_LIST[i]}')
    return {'rp': rp, 'lines': fortune, 'music_index': h}


# ---------- 随机功能的数值/条件解析 ----------

DIFF_VALUE_MAP: Dict[str, int] = {
    '绿': 0, '黄': 1, '红': 2, '紫': 3, '白': 4,
    'basic': 0, 'advanced': 1, 'expert': 2, 'master': 3,
    'remaster': 4, 're:master': 4, 're master': 4, 're': 4,
}


def parse_range(value: str) -> Tuple[float, float]:
    """解析数值或区间：'14.0-14.2' / '14.0~14.2' / '14' -> (low, high)。

    非法数值抛 ValueError。
    """
    text = (value or '').strip().replace('～', '-').replace('—', '-').replace('–', '-')
    if not text:
        raise ValueError('空数值')
    idx = text.find('-', 1)
    if idx > 0:
        low, high = float(text[:idx]), float(text[idx + 1:])
    else:
        low = high = float(text)
    if low > high:
        low, high = high, low
    return low, high


def parse_difficulty(value: str) -> Optional[Tuple[str, object]]:
    """解析难度值 -> ('diff', 难度下标) 或 ('level', 等级字符串)。"""
    text = (value or '').strip().lower()
    if not text:
        return None
    if text in DIFF_VALUE_MAP:
        return ('diff', DIFF_VALUE_MAP[text])
    if text in LEVEL_LIST:
        return ('level', text)
    return None


def resolve_versions(value: str, all_versions: List[str]) -> List[str]:
    """解析版本值 -> 命中的版本名（小写）列表。

    支持牌子单字（如 祭/爽/熊/彩）与版本名子串（如 fest/辉）。
    """
    v = (value or '').strip()
    if not v:
        return []
    if v in VERSION_MAP:
        return [x.lower() for x in VERSION_MAP[v][0]]
    vl = v.lower()
    matched = [ver.lower() for ver in all_versions if vl in ver.lower()]
    # 牌子简写逐字匹配（如 "festi" 已含在上面的子串匹配中，这里兜底繁体/简写）
    if not matched:
        for ch in v:
            if ch in VERSION_MAP:
                matched.extend(x.lower() for x in VERSION_MAP[ch][0])
    return list(dict.fromkeys(matched))



def ra_base(ach: float) -> float:
    if ach >= 100.5:
        return 22.4
    if ach >= 100:
        return 21.6
    if ach >= 99.5:
        return 21.1
    if ach >= 99:
        return 20.8
    if ach >= 98:
        return 20.3
    if ach >= 97:
        return 20.0
    if ach >= 94:
        return 16.8
    if ach >= 90:
        return 15.2
    if ach >= 80:
        return 13.6
    if ach >= 75:
        return 12.0
    if ach >= 70:
        return 11.2
    if ach >= 60:
        return 9.6
    if ach >= 50:
        return 8.0
    return 7.0


def compute_ra(ds: float, ach: float) -> int:
    return int(ds * ra_base(ach) * ach / 100)


def next_tier_ach(ach: float) -> Optional[float]:
    """下一个达成率档位（用于上分建议）。"""
    for tier in (100.5, 100, 99.5, 99, 98, 97):
        if ach < tier:
            return tier
    return None


# ---------- 进度判定 ----------

def plan_predicate(plan: str) -> Optional[Callable]:
    """等级进度：评价等级 -> 判定函数（verlist 记录）。"""
    p = SYNC_ALIAS.get(plan.lower(), plan.lower())
    if p in RANK_MIN_ACH:
        value = RANK_MIN_ACH[p]
        return lambda r: r.achievements >= value
    if p in COMBO_RANK:
        index = COMBO_RANK.index(p)
        return lambda r: bool(r.fc) and COMBO_RANK.index(SYNC_ALIAS.get(r.fc, r.fc)) >= index
    if p in SYNC_RANK:
        index = SYNC_RANK.index(p)
        return lambda r: bool(r.fs) and SYNC_RANK.index(SYNC_ALIAS.get(r.fs, r.fs)) >= index
    return None


def plate_predicate(plan: str) -> Optional[Callable]:
    """牌子进度：目标 -> 判定函数（True = 未完成）。"""
    if plan in ['将', '者']:
        achievement = 100 if plan == '将' else 80
        return lambda r: r.achievements < achievement
    if plan in ['極', '极']:
        return lambda r: not r.fc
    if plan in ['舞', '舞舞']:
        return lambda r: SYNC_ALIAS.get(r.fs, r.fs) not in ['fsd', 'fsdp']
    if plan == '神':
        return lambda r: r.fc not in ['ap', 'app']
    return None


# ---------- 分数线 ----------

def score_line(title: str, diff_label: str, line: float, notes: List[int]) -> Optional[str]:
    """分数线容错计算。notes = [tap, hold, slide, (touch), brk]。"""
    if len(notes) >= 5:
        tap, hold, slide, touch, brk = notes[0], notes[1], notes[2], notes[3], notes[4]
    else:
        tap, hold, slide, touch, brk = notes[0], notes[1], notes[2], 0, notes[3]
    if brk <= 0:
        return '该谱面没有 BREAK，无法计算'
    reduce = 101 - line
    if reduce <= 0 or reduce >= 101:
        return None
    total_score = tap * 500 + slide * 1500 + hold * 1000 + touch * 500 + brk * 2500
    break_bonus = 0.01 / brk
    break_50_reduce = total_score * break_bonus / 4
    return (
        f'{title}「{diff_label}」\n'
        f'分数线「{line:g}%」\n'
        f'允许的最多「TAP」「GREAT」数量为\n'
        f'「{total_score * reduce / 10000:.2f}」(每个-{10000 / total_score:.4f}%),\n'
        f'「BREAK」50落(一共「{brk}」个)\n'
        f'等价于「{break_50_reduce / 100:.3f}」个「TAP」「GREAT」(-{break_50_reduce / total_score * 100:.4f}%)'
    )


SCORE_LINE_HELP = (
    '此功能为查找某首歌分数线设计。\n'
    '命令格式：分数线 「难度色+歌曲id」 「分数线」\n'
    '例如：分数线 紫799 100\n'
    '命令将返回分数线允许的「TAP」「GREAT」容错，\n'
    '以及「BREAK」50落等价的「TAP」「GREAT」数。\n'
    '难度色：绿=Basic 黄=Advanced 红=Expert 紫=Master 白=Re:Master\n'
    '「TAP」「GREAT」的对应表：\n'
    '        GREAT / GOOD / MISS\n'
    'TAP         1 / 2.5  / 5\n'
    'HOLD        2 / 5    / 10\n'
    'SLIDE       3 / 7.5  / 15\n'
    'TOUCH       1 / 2.5  / 5\n'
    'BREAK       5 / 12.5 / 25 (外加200落)'
)
