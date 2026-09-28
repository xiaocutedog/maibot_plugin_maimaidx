"""曲库数据管理：从查分器拉取曲目/拟合定数/别名数据并落盘缓存，提供检索。"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .api import MaimaiAPI, MaimaiError
from .model import AliasItem, Music

MUSIC_CACHE_FILE = 'music_data.json'
CHART_CACHE_FILE = 'chart_stats.json'
ALIAS_CACHE_FILE = 'alias.json'
PLATE_CACHE_FILE = 'plate.json'
NAME_ALIAS_FILES = {
    # kind: (远端缓存文件, 本地用户别名文件)
    'artist': ('artist_alias_remote.json', 'artist_alias_local.json'),
    'charter': ('charter_alias_remote.json', 'charter_alias_local.json'),
}


def _sort_key(music: Music) -> int:
    return int(music.id) if music.id.isdigit() else 10 ** 9


class RaMusic:
    """定数表条目：Music + 难度下标（对应源插件 RaMusic）。"""

    __slots__ = ('id', 'ds', 'lv', 'type', 'level', 'basic_info', 'title', 'music')

    def __init__(self, music: Music, index: int) -> None:
        self.id = music.id
        self.ds = music.ds[index]
        self.lv = index
        self.type = music.type
        self.level = music.level
        self.basic_info = music.basic_info
        self.title = music.title
        self.music = music


class MusicList(list):
    """曲目列表，附带按 ID 索引与常用检索。"""

    def __init__(self, iterable=()):
        super().__init__(iterable)
        self._by_id: Dict[str, Music] = {m.id: m for m in self}

    def by_id(self, music_id: Any) -> Optional[Music]:
        return self._by_id.get(str(music_id).strip())

    def by_title(self, keyword: str, exact: bool = False) -> List[Music]:
        kw = keyword.strip().lower()
        if not kw:
            return []
        if exact:
            result = [m for m in self if m.title.strip().lower() == kw]
        else:
            result = [m for m in self if kw in m.title.lower()]
        return sorted(result, key=_sort_key)

    def by_artist(self, keyword: str) -> List[Music]:
        kw = keyword.strip().lower()
        if not kw:
            return []
        return sorted((m for m in self if kw in m.artist.lower()), key=_sort_key)

    def by_charter(self, keyword: str) -> List[Music]:
        kw = keyword.strip().lower()
        if not kw:
            return []
        result = []
        for m in sorted(self, key=_sort_key):
            if any(kw in (c.charter or '').lower() for c in m.charts):
                result.append(m)
        return result

    def by_bpm(self, low: int, high: int) -> List[Music]:
        return sorted(
            (m for m in self if low <= m.basic_info.bpm <= high),
            key=lambda m: m.basic_info.bpm,
        )

    def by_id_list(self, music_id_list: List[int]) -> List[Music]:
        wanted = {int(i) for i in music_id_list}
        return [m for m in self if m.id.isdigit() and int(m.id) in wanted]

    def by_level_list(self) -> Dict[str, Dict[str, List[RaMusic]]]:
        """按等级分组，再按定数分组（对应源插件 total_level_data）。"""
        result: Dict[str, Dict[str, List[RaMusic]]] = {
            lv: {} for lv in [
                '1', '2', '3', '4', '5', '6', '7', '7+', '8', '8+', '9', '9+',
                '10', '10+', '11', '11+', '12', '12+', '13', '13+', '14', '14+', '15',
            ]
        }
        for m in self:
            if m.is_utage:
                continue
            for index, lv in enumerate(m.level):
                if lv not in result or m.ds[index] < 7:
                    continue
                result[lv].setdefault(f'{lv.rstrip("+")}.{m.ds[index]}', []).append(RaMusic(m, index))
        return result

    def by_ds(self, low: float, high: float, include_utage: bool = False) -> List[Tuple[Music, int]]:
        """按歌曲定数区间检索，返回 (曲目, 难度下标) 列表。"""
        result: List[Tuple[Music, int]] = []
        for m in sorted(self, key=_sort_key):
            if not include_utage and m.is_utage:
                continue
            for i, ds in enumerate(m.ds):
                if low <= ds <= high:
                    result.append((m, i))
        return result

    def by_fit(
        self,
        low: float,
        high: float,
        include_utage: bool = False,
    ) -> List[Tuple[Music, int, float]]:
        """按拟合定数区间检索，返回 (曲目, 难度下标, 拟合定数) 列表。"""
        result: List[Tuple[Music, int, float]] = []
        for m in sorted(self, key=_sort_key):
            if not include_utage and m.is_utage:
                continue
            for i in range(max(len(m.ds), len(m.stats))):
                fit = m.fit_diff(i)
                if fit is not None and low <= fit <= high:
                    result.append((m, i, fit))
        return result


class AliasList(list):
    """别名列表，附带小写别名 -> 曲目条目索引。"""

    def __init__(self, iterable=()):
        super().__init__(iterable)
        self._by_alias: Dict[str, List[AliasItem]] = {}
        for item in self:
            for name in {item.Name.lower(), *(a.lower() for a in item.Alias)}:
                self._by_alias.setdefault(name, []).append(item)

    def by_id(self, song_id: int) -> List[AliasItem]:
        return [item for item in self if item.SongID == int(song_id)]

    def by_alias(self, name: str) -> List[AliasItem]:
        return self._by_alias.get(name.strip().lower(), [])

    def aliases_of(self, song_id: int) -> List[str]:
        merged: List[str] = []
        for item in self.by_id(song_id):
            for name in [item.Name, *item.Alias]:
                if name and name not in merged:
                    merged.append(name)
        return merged


class MaiMusic:
    """曲库 + 别名数据，负责从查分器拉取并缓存到 data_dir。"""

    def __init__(
        self,
        data_dir: Path,
        api: MaimaiAPI,
        cover_base_url: str = 'https://www.diving-fish.com/covers',
        artist_alias_url: str = '',
        charter_alias_url: str = '',
    ) -> None:
        self.data_dir = Path(data_dir)
        self.cover_dir = self.data_dir / 'covers'
        self.cover_base_url = cover_base_url.rstrip('/')
        self.artist_alias_url = artist_alias_url
        self.charter_alias_url = charter_alias_url
        self.api = api
        self.total_list: MusicList = MusicList()
        self.total_alias_list: AliasList = AliasList()
        self.total_plate_id_list: Dict[str, List[int]] = {}
        self.artist_aliases: Dict[str, List[str]] = {}
        self.charter_aliases: Dict[str, List[str]] = {}
        self.music_loaded = False
        self.alias_loaded = False
        self.plate_loaded = False
        self.music_updated_at = 0.0
        self.alias_updated_at = 0.0
        self._guess_pool: Optional[List[Music]] = None

    def guess_pool(self) -> List[Music]:
        """猜歌曲目池（游玩次数 > 1 万），随曲库刷新重建。"""
        if self._guess_pool is None:
            from .guess import guess_pool as build_pool

            self._guess_pool = build_pool(self.total_list)
        return self._guess_pool

    # ---------- 缓存 ----------

    def _cache_path(self, name: str) -> Path:
        return self.data_dir / name

    def _save_cache(self, name: str, data: Any) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(name).write_text(
                json.dumps(data, ensure_ascii=False), encoding='utf-8'
            )
        except OSError:
            pass

    def _read_cache(self, name: str) -> Any:
        path = self._cache_path(name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None

    # ---------- 加载 ----------

    async def load_music(self) -> None:
        """拉取曲目 + 谱面统计（失败时回退本地缓存）。"""
        music_data: Optional[List[Dict[str, Any]]] = None
        chart_stats: Optional[Dict[str, Any]] = None
        error: Optional[Exception] = None
        try:
            music_data = await self.api.music_data()
            self._save_cache(MUSIC_CACHE_FILE, music_data)
        except Exception as e:  # noqa: BLE001 - 网络失败时回退本地
            error = e
        try:
            chart_stats = await self.api.chart_stats()
            self._save_cache(CHART_CACHE_FILE, chart_stats)
        except Exception as e:  # noqa: BLE001
            error = error or e
        if not music_data:
            music_data = self._read_cache(MUSIC_CACHE_FILE)
        if not chart_stats:
            chart_stats = self._read_cache(CHART_CACHE_FILE)
        if not music_data:
            if error:
                raise MaimaiError(
                    f'曲目数据获取失败（{error}）且本地无缓存，请检查网络后使用「maimai更新数据」重试'
                )
            raise MaimaiError('本地无曲目缓存，请使用「maimai更新数据」拉取数据')
        self.total_list = self._build_music_list(music_data, chart_stats or {'charts': {}})
        self.music_loaded = True
        self._guess_pool = None
        self.music_updated_at = self._cache_time(MUSIC_CACHE_FILE)

    async def load_alias(self) -> None:
        """拉取别名数据（失败时回退本地缓存）。"""
        alias_data: Optional[List[Dict[str, Any]]] = None
        error: Optional[Exception] = None
        try:
            alias_data = await self.api.get_alias()
            self._save_cache(ALIAS_CACHE_FILE, alias_data)
        except Exception as e:  # noqa: BLE001
            error = e
            alias_data = self._read_cache(ALIAS_CACHE_FILE)
        if not alias_data:
            if error:
                raise MaimaiError(f'别名数据获取失败（{error}）且本地无缓存')
            raise MaimaiError('本地无别名缓存')
        valid = [a for a in alias_data if self.total_list.by_id(a.get('SongID'))]
        self.total_alias_list = AliasList(AliasItem.model_validate(a) for a in valid)
        self.alias_loaded = True
        self.alias_updated_at = self._cache_time(ALIAS_CACHE_FILE)

    async def load_all(self) -> None:
        await self.load_music()
        await self.load_alias()
        try:
            await self.load_plate()
        except MaimaiError:
            # 牌子表加载失败不影响其他功能（牌子进度查询会提示重试）
            self.total_plate_id_list = {}
            self.plate_loaded = False
        for kind in NAME_ALIAS_FILES:
            try:
                await self.load_name_aliases(kind)
            except Exception:  # noqa: BLE001 - 别名库加载失败不影响主功能
                continue

    async def load_plate(self) -> None:
        """拉取版本牌子曲目 ID 表（失败时回退本地缓存）。"""
        plate_data: Optional[Dict[str, List[int]]] = None
        error: Optional[Exception] = None
        try:
            plate_data = await self.api.get_plate_json()
            self._save_cache(PLATE_CACHE_FILE, plate_data)
        except Exception as e:  # noqa: BLE001
            error = e
            plate_data = self._read_cache(PLATE_CACHE_FILE)
        if not plate_data:
            raise MaimaiError(f'牌子数据获取失败（{error}）且本地无缓存')
        self.total_plate_id_list = plate_data
        self.plate_loaded = True

    # ---------- 曲师/谱师别名库 ----------

    @staticmethod
    def _merge_alias_store(target: Dict[str, List[str]], source: Dict) -> None:
        """合并别名表，source 支持 {'别名': '全名'} 或 {'别名': ['全1', '全2']}。"""
        for key, value in (source or {}).items():
            k = str(key).strip().lower()
            if not k:
                continue
            names = [str(value)] if isinstance(value, str) else [str(x) for x in (value or [])]
            bucket = target.setdefault(k, [])
            for n in names:
                n = n.strip()
                if n and n not in bucket:
                    bucket.append(n)

    async def load_name_aliases(self, kind: str) -> None:
        """加载曲师/谱师别名：远端 URL（可配置）+ 本地文件，本地优先。

        kind: 'artist' | 'charter'
        """
        if kind not in NAME_ALIAS_FILES:
            raise ValueError(f'未知别名类型: {kind}')
        remote_cache, local_file = NAME_ALIAS_FILES[kind]
        store: Dict[str, List[str]] = {}
        url = self.artist_alias_url if kind == 'artist' else self.charter_alias_url
        if url:
            try:
                async with httpx.AsyncClient(timeout=15) as session:
                    res = await session.get(url)
                if res.status_code == 200:
                    data = res.json()
                    self._save_cache(remote_cache, data)
                    self._merge_alias_store(store, data)
            except Exception:  # noqa: BLE001 - 远端失败回退缓存
                data = self._read_cache(remote_cache)
                if data:
                    self._merge_alias_store(store, data)
        local = self._read_cache(local_file)
        if local:
            self._merge_alias_store(store, local)
        if kind == 'artist':
            self.artist_aliases = store
        else:
            self.charter_aliases = store

    def add_name_alias(self, kind: str, alias: str, canonical: str) -> bool:
        """添加别名并持久化到本地文件，返回是否为新别名。"""
        if kind not in NAME_ALIAS_FILES:
            raise ValueError(f'未知别名类型: {kind}')
        _, local_file = NAME_ALIAS_FILES[kind]
        store = self.artist_aliases if kind == 'artist' else self.charter_aliases
        key = alias.strip().lower()
        canonical = canonical.strip()
        if not key or not canonical:
            return False
        bucket = store.setdefault(key, [])
        if canonical in bucket:
            return False
        bucket.append(canonical)
        local = self._read_cache(local_file) or {}
        self._merge_alias_store(local, {key: [canonical]})
        self._save_cache(local_file, local)
        return True

    def resolve_name(self, kind: str, value: str) -> List[str]:
        """别名 -> 候选全名列表（原值排在首位，供子串匹配）。"""
        store = self.artist_aliases if kind == 'artist' else self.charter_aliases
        value = value.strip()
        names = list(store.get(value.strip().lower(), []))
        if value and value not in names:
            names.insert(0, value)
        return names

    def _cache_time(self, name: str) -> float:
        path = self._cache_path(name)
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _build_music_list(
        music_data: List[Dict[str, Any]],
        chart_stats: Dict[str, Any],
    ) -> MusicList:
        charts: Dict[str, Any] = chart_stats.get('charts', {}) if isinstance(chart_stats, dict) else {}
        items: List[Music] = []
        for item in music_data:
            stats_raw = charts.get(str(item.get('id')))
            if stats_raw:
                stats = [s if s else None for s in stats_raw]
            else:
                stats = []
            try:
                items.append(Music.model_validate({**item, 'stats': stats}))
            except Exception:  # noqa: BLE001 - 单条脏数据不影响整体
                continue
        return MusicList(items)

    # ---------- 曲绘 ----------

    async def get_cover(self, music_id: str) -> Optional[bytes]:
        """曲绘：优先本地 covers 目录，其次在线地址（失败返回 None）。"""
        for suffix in ('.png', '.jpg', '.webp'):
            path = self.cover_dir / f'{music_id}{suffix}'
            if path.exists():
                try:
                    return path.read_bytes()
                except OSError:
                    return None
        if not self.cover_base_url:
            return None
        for suffix in ('.png', '.jpg'):
            try:
                async with httpx.AsyncClient(timeout=15) as session:
                    res = await session.get(f'{self.cover_base_url}/{music_id}{suffix}')
                if res.status_code == 200 and res.content:
                    return res.content
            except Exception:  # noqa: BLE001 - 曲绘失败不影响查询
                continue
        return None
