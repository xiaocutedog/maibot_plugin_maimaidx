"""maimaiDX 数据模型（对应水鱼查分器 music_data / chart_stats / query 接口）。"""

from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

DIFF_NAMES: List[str] = ['Basic', 'Advanced', 'Expert', 'Master', 'Re:Master', 'UTAGE']


class BasicInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = ''
    artist: str = ''
    genre: str = ''
    bpm: int = 0
    release_date: str = ''
    version: str = Field(default='', alias='from')
    is_new: bool = False


class Chart(BaseModel):
    notes: List[int] = Field(default_factory=list)
    charter: str = '-'


class Stats(BaseModel):
    cnt: Optional[float] = None
    diff: Optional[str] = None
    fit_diff: Optional[float] = None
    avg: Optional[float] = None
    avg_dx: Optional[float] = None
    std_dev: Optional[float] = None
    dist: Optional[List[int]] = None
    fc_dist: Optional[List[float]] = None


class Music(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str = ''
    type: str = 'SD'
    ds: List[float] = Field(default_factory=list)
    level: List[str] = Field(default_factory=list)
    cids: List[int] = Field(default_factory=list)
    charts: List[Chart] = Field(default_factory=list)
    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    stats: List[Optional[Stats]] = Field(default_factory=list)

    @property
    def is_utage(self) -> bool:
        return self.id.isdigit() and int(self.id) >= 100000

    @property
    def version(self) -> str:
        return self.basic_info.version

    @property
    def artist(self) -> str:
        return self.basic_info.artist

    def ds_at(self, index: int) -> Optional[float]:
        if 0 <= index < len(self.ds):
            return self.ds[index]
        return None

    def fit_diff(self, index: int) -> Optional[float]:
        if 0 <= index < len(self.stats) and self.stats[index] is not None:
            return self.stats[index].fit_diff
        return None

    def charter(self, index: int) -> str:
        if 0 <= index < len(self.charts):
            return self.charts[index].charter or '-'
        return '-'


class AliasItem(BaseModel):
    SongID: int
    Name: str = ''
    Alias: List[str] = Field(default_factory=list)


class APIResult(BaseModel):
    code: int = 0
    content: Union[dict, list, str, None] = None


class PlayChart(BaseModel):
    achievements: float = 0
    fc: str = ''
    fs: str = ''
    level: str = ''
    level_index: int = 0
    title: str = ''
    type: str = ''
    ds: float = 0
    dxScore: int = 0
    ra: int = 0
    rate: str = ''
    level_label: str = ''
    song_id: int = 0


class PlayRecord(BaseModel):
    """查分器 verlist 记录（/query/plate）。"""

    model_config = ConfigDict(populate_by_name=True)

    achievements: float = 0
    fc: str = ''
    fs: str = ''
    level: str = ''
    level_index: int = 0
    title: str = ''
    type: str = ''
    ds: float = 0
    dxScore: int = 0
    ra: int = 0
    rate: str = ''
    song_id: int = Field(default=0, alias='id')


class UserCharts(BaseModel):
    sd: List[PlayChart] = Field(default_factory=list)
    dx: List[PlayChart] = Field(default_factory=list)


class UserInfo(BaseModel):
    additional_rating: Optional[int] = None
    nickname: Optional[str] = None
    plate: Optional[str] = None
    rating: Optional[int] = None
    username: Optional[str] = None
    charts: Optional[UserCharts] = None


class UserInfoDev(UserInfo):
    records: List[PlayChart] = Field(default_factory=list)


class UserRanking(BaseModel):
    username: str = ''
    ra: int = 0
