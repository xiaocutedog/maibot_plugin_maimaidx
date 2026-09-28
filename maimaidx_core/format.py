"""查询结果文本格式化。"""

from typing import List, Optional, Sequence, Tuple

from .model import DIFF_NAMES, Music, PlayChart, UserInfo

FC_MAP = {'fc': 'FC', 'fcp': 'FCp', 'ap': 'AP', 'app': 'APp'}
FS_MAP = {'fs': 'FS', 'fsp': 'FSp', 'fsd': 'FSD', 'fdx': 'FSD', 'fsdp': 'FSDp', 'fdxp': 'FSDp', 'sync': 'Sync'}


def diff_name(index: int) -> str:
    return DIFF_NAMES[index] if 0 <= index < len(DIFF_NAMES) else f'Diff{index}'


def fmt_num(value: Optional[float], nd: int = 1) -> str:
    if value is None:
        return '-'
    return f'{value:.{nd}f}'


def paginate(items: Sequence, page: int, per_page: int) -> Tuple[List, int, int]:
    total = max(1, (len(items) + per_page - 1) // per_page)
    page = max(1, min(page, total))
    return list(items[(page - 1) * per_page: page * per_page]), page, total


def format_song_info(music: Music, aliases: Optional[List[str]] = None) -> str:
    """曲目详情：曲名 / 分类 / 版本 / 曲师 / 各难度定数 / 拟合定数 / 谱师。"""
    bi = music.basic_info
    lines: List[str] = [f'♪ {music.title}（ID: {music.id}）']

    tags = [f'分类: {bi.genre or "未知"}']
    tags.append('DX谱面' if music.type == 'DX' else '标准谱面')
    if bi.version:
        tags.append(f'版本: {bi.version}')
    if bi.release_date:
        tags.append(f'收录: {bi.release_date}')
    lines.append('｜'.join(tags))
    lines.append(f'曲师: {bi.artist or "-"}｜BPM: {bi.bpm or "-"}')

    if aliases:
        show = '、'.join(aliases[:6])
        more = f' 等{len(aliases)}个' if len(aliases) > 6 else ''
        lines.append(f'别名: {show}{more}')

    lines.append('―' * 20)
    lines.append('难度        等级   定数    拟合定数   谱师')
    count = max(len(music.level), len(music.ds), len(music.charts))
    for i in range(count):
        lv = music.level[i] if i < len(music.level) else '-'
        dsv = fmt_num(music.ds_at(i), 1)
        fit = music.fit_diff(i)
        fitv = fmt_num(fit, 2) if fit is not None else '-'
        lines.append(
            f'{diff_name(i):<10} {lv:<5} {dsv:<7} {fitv:<9} {music.charter(i)}'
        )
    lines.append('※ 定数/拟合定数数据来自水鱼查分器（fit_diff 为全体玩家拟合值）')
    return '\n'.join(lines)


def format_song_brief(music: Music, index: int, ds: Optional[float] = None,
                      fit: Optional[float] = None) -> str:
    """列表中的一行。"""
    lv = music.level[index] if index < len(music.level) else '-'
    parts = [f'「{music.id}」', f'「{diff_name(index)}」', f'「Lv{lv}」']
    if ds is not None:
        parts.append(f'「定数{fmt_num(ds, 1)}」')
    if fit is not None:
        parts.append(f'「拟合{fmt_num(fit, 2)}」')
    return f'{"".join(parts)} {music.title}'


def format_search_list(
    header: str,
    rows: List[str],
    page: int,
    total_pages: int,
    total_count: int,
) -> str:
    lines = [header, '―' * 20, *rows]
    lines.append(f'第「{page}」页，共「{total_pages}」页（{total_count} 条）。请使用「id 曲目ID」查询详情。')
    return '\n'.join(lines)


def format_b50(user: UserInfo) -> str:
    """B50 文本成绩单。"""
    name = user.nickname or user.username or '未知用户'
    lines = [
        f'♪ maimaiDX B50 — {name}',
        f'Rating: {user.rating if user.rating is not None else "-"}｜'
        f'DX Rating: {user.additional_rating if user.additional_rating is not None else "-"}'
        + (f'｜牌子: {user.plate}' if user.plate else ''),
    ]

    def block(title: str, data: List[PlayChart], offset: int = 1) -> None:
        lines.append('―' * 20)
        lines.append(title)
        for i, c in enumerate(data, offset):
            marks = FC_MAP.get(c.fc, c.fc if c.fc else '')
            sync = FS_MAP.get(c.fs, c.fs if c.fs else '')
            badge = '｜'.join(x for x in (marks, sync) if x)
            lines.append(
                f'{i:>2}. {c.achievements:.4f}%  Ra {c.ra}  '
                f'[{c.level}/{fmt_num(c.ds, 1)}] {c.title}'
                + (f'  {badge}' if badge else '')
            )

    charts = user.charts
    if charts and charts.sd:
        block('【旧版本 B35】', charts.sd)
    if charts and charts.dx:
        block('【新版本 B15】', charts.dx)
    if not charts or (not charts.sd and not charts.dx):
        lines.append('（无成绩数据，请确认该用户已在查分器上传成绩）')
    return '\n'.join(lines)


def format_player_record(
    username: str,
    music: Music,
    records: List[PlayChart],
) -> str:
    lines = [f'♪ {username} 的成绩 — {music.title}（ID: {music.id}）', '―' * 20]
    for c in sorted(records, key=lambda x: x.level_index):
        marks = FC_MAP.get(c.fc, c.fc if c.fc else '')
        sync = FS_MAP.get(c.fs, c.fs if c.fs else '')
        badge = '｜'.join(x for x in (marks, sync) if x)
        lines.append(
            f'{diff_name(c.level_index):<10} {c.achievements:.4f}%  Ra {c.ra}  '
            f'[{c.level}/{fmt_num(c.ds, 1)}]  DX分 {c.dxScore}'
            + (f'  {badge}' if badge else '')
        )
    if not lines[2:]:
        lines.append('（暂无该曲目成绩记录）')
    return '\n'.join(lines)
