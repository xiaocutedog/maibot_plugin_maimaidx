"""水鱼查分器 / 柚子社别名库 API 封装（不依赖 MaiBot SDK）。

水鱼新版认证体系（auth.diving-fish.com OAuth）：
- BOT 只保管 client_id / client_secret，不保存任何用户令牌；
- 用户发送「绑定水鱼」发起绑定（device_authorization），在水鱼账号页确认后
  拿到一次性确认码，回填给 BOT（confirmation-code 兑换）完成绑定；
- 之后每次代查，BOT 用 on-behalf-of grant 换取该用户 5 分钟有效的 access_token，
  请求 /player/* 接口时携带 `Authorization: Bearer`；
- 未配置 client_id/client_secret 时，回退旧的 developer-token 开发者模式。
"""

import hashlib
import time
from enum import IntFlag
from typing import Any, Dict, List, Optional, Union

import httpx

from .model import APIResult, UserInfo, UserInfoDev


class MaimaiError(Exception):
    """maimai 查分相关错误基类。"""


class ServerError(MaimaiError):
    """服务端错误。"""


class UnknownError(MaimaiError):
    """未知错误。"""


class TokenError(MaimaiError):
    """开发者 token 有误 / OAuth 客户端配置有误。"""


class TokenDisableError(MaimaiError):
    """开发者 token 被禁用。"""


class UserNotFoundError(MaimaiError):
    """查无此人。"""


class UserNotExistsError(MaimaiError):
    """用户不存在（未绑定查分器）。"""


class UserDisabledQueryError(MaimaiError):
    """用户禁止查询。"""


class MusicNotPlayError(MaimaiError):
    """未查到该曲目的游玩记录。"""


class TooManyRequestsError(MaimaiError):
    """请求过于频繁（HTTP 429）。"""


class OAuthError(MaimaiError):
    """水鱼 OAuth 流程错误。"""


class OAuthNotBoundError(OAuthError):
    """用户尚未绑定/授权（consent_required）。"""


class OAuthConfirmationCodeError(OAuthError):
    """确认码无效/过期/已使用（invalid_grant）。"""


class OAuthBindingMismatchError(OAuthError):
    """确认码不是发给这个用户的（subject_mismatch）。"""


class DivingFishScope(IntFlag):
    """水鱼 OAuth scope 位标志。"""

    PROFILE = 1 << 0
    PROBER_PROFILE_READ = 1 << 1
    PROBER_RECORDS_READ = 1 << 2
    PROBER_RECORDS_WRITE = 1 << 3
    CHUNITHM_RECORDS_READ = 1 << 4
    CHUNITHM_RECORDS_WRITE = 1 << 5


SCOPE_NAMES = {
    DivingFishScope.PROFILE: 'profile',
    DivingFishScope.PROBER_PROFILE_READ: 'prober.profile.read',
    DivingFishScope.PROBER_RECORDS_READ: 'prober.records.read',
    DivingFishScope.PROBER_RECORDS_WRITE: 'prober.records.write',
    DivingFishScope.CHUNITHM_RECORDS_READ: 'chunithm.records.read',
    DivingFishScope.CHUNITHM_RECORDS_WRITE: 'chunithm.records.write',
}
SCOPE_VALUES = {name: scope for scope, name in SCOPE_NAMES.items()}


def parse_scope(value: str) -> str:
    """把空格分隔的 scope 名称串规范化（未知名称直接报错）。"""
    text = (value or '').strip()
    if not text:
        text = 'prober.records.read'
    result = DivingFishScope(0)
    for name in text.split():
        scope = SCOPE_VALUES.get(name)
        if scope is None:
            raise ValueError(f'未知的查分器 scope: {name}；可选值：{", ".join(SCOPE_VALUES)}')
        result |= scope
    return ' '.join(name for scope, name in SCOPE_NAMES.items() if result & scope)


ON_BEHALF_OF_GRANT = 'urn:diving-fish:params:oauth:grant-type:on-behalf-of'
CONFIRMATION_CODE_GRANT = 'urn:diving-fish:params:oauth:grant-type:confirmation-code'

# 提前一点过期，避免令牌在请求途中失效
_EXPIRES_MARGIN = 30


def binding_label(user_id: str) -> str:
    """展示在授权页面上的绑定身份，用户凭它确认不是在给别人授权。"""
    qq = str(user_id)
    if len(qq) <= 4:
        return f'QQ {qq}'
    return f'QQ {qq[:2]}{"*" * (len(qq) - 4)}{qq[-2:]}'


class TokenCache:
    """代查令牌缓存：subject_ref -> (access_token, 过期时刻)。"""

    def __init__(self) -> None:
        self._tokens: Dict[str, tuple] = {}

    def get(self, ref: str) -> Optional[str]:
        cached = self._tokens.get(ref)
        if cached is None:
            return None
        token, expires_at = cached
        if expires_at <= time.monotonic():
            del self._tokens[ref]
            return None
        return token

    def set(self, ref: str, token: str, expires_in: int) -> None:
        self._tokens[ref] = (token, time.monotonic() + max(expires_in - _EXPIRES_MARGIN, 0))

    def discard(self, ref: str) -> None:
        self._tokens.pop(ref, None)


class DivingFishOAuth:
    """水鱼账号服务（auth.diving-fish.com）OAuth 客户端。"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        auth_url: str = 'https://auth.diving-fish.com',
        scope: str = 'prober.records.read',
        timeout: int = 30,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url.rstrip('/')
        self.scope = scope
        self.timeout = timeout
        self.tokens = TokenCache()

    def subject_ref(self, user_id: Union[str, int]) -> str:
        """用户标识摘要；QQ 号不以明文离开 BOT。"""
        return hashlib.sha256(f'{self.client_id}:{user_id}'.encode()).hexdigest()

    async def _request(self, endpoint: str, data: Dict[str, str]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as session:
            res = await session.post(self.auth_url + endpoint, data=data)
        if res.status_code == 200:
            return res.json()
        try:
            error = res.json().get('error', '')
        except Exception:  # noqa: BLE001
            error = ''
        if error == 'consent_required':
            raise OAuthNotBoundError('该用户尚未在水鱼账号页完成授权，请先发送「绑定水鱼」')
        if error == 'subject_mismatch':
            raise OAuthBindingMismatchError('这串确认码不是发给你的（多半是转发了别人的），请本人重新绑定')
        if error == 'invalid_grant':
            raise OAuthConfirmationCodeError('确认码无效、已过期或已使用，请重新发送「绑定水鱼」走一遍绑定')
        if error == 'invalid_client':
            raise TokenError('查分器 client_id/client_secret 有误，请检查插件配置')
        raise OAuthError(f'水鱼授权服务错误（HTTP {res.status_code}）')

    async def device_authorization(self, user_id: Union[str, int]) -> Dict[str, Any]:
        """发起绑定，返回授权信息（含用户点开的链接）。"""
        ref = self.subject_ref(user_id)
        return await self._request('/oauth/device_authorization', data={
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': self.scope,
            'subject_ref': ref,
            'binding_label': binding_label(user_id),
            # handoff=code：改由用户回填确认码收尾，防止伪造绑定链接
            'handoff': 'code',
        })

    async def redeem(self, user_id: Union[str, int], confirmation_code: str) -> Dict[str, Any]:
        """用用户回填的确认码完成绑定，兑换一次令牌。"""
        return await self._request('/oauth/token', data={
            'grant_type': CONFIRMATION_CODE_GRANT,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'confirmation_code': confirmation_code,
            'subject_ref': self.subject_ref(user_id),
        })

    async def fetch_token(self, user_id: Union[str, int]) -> str:
        """代该用户访问前换取 access_token。"""
        result = await self._request('/oauth/token', data={
            'grant_type': ON_BEHALF_OF_GRANT,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'subject': f'ref:{self.subject_ref(user_id)}',
            'scope': self.scope,
        })
        return result.get('access_token', '')

    async def get_access_token(self, user_id: Union[str, int], *, refresh: bool = False) -> str:
        """取该用户的令牌，命中缓存则直接复用。"""
        ref = self.subject_ref(user_id)
        if refresh:
            self.tokens.discard(ref)
        else:
            token = self.tokens.get(ref)
            if token:
                return token
        token = await self.fetch_token(user_id)
        # fetch_token 成功但未回 expires_in 时给一个保守值
        self.tokens.set(ref, token, 300)
        return token

    def discard_token(self, user_id: Union[str, int]) -> None:
        self.tokens.discard(self.subject_ref(user_id))


class MaimaiAPI:
    """查分器通用请求封装。"""

    MaiProxyAPI = 'https://proxy.yuzuchan.site'
    MaiProberAPI = 'https://maimai.diving-fish.com/api/maimaidxprober'
    MaiAliasAPI = 'https://www.yuzuchan.moe/api/maimaidx'

    def __init__(
        self,
        token: str = '',
        timeout: int = 30,
        prober_proxy: bool = False,
        alias_proxy: bool = False,
        client_id: str = '',
        client_secret: str = '',
        auth_url: str = 'https://auth.diving-fish.com',
        scope: str = 'prober.records.read',
    ) -> None:
        self.apply_config(token, timeout, prober_proxy, alias_proxy,
                          client_id, client_secret, auth_url, scope)

    def apply_config(
        self,
        token: str = '',
        timeout: int = 30,
        prober_proxy: bool = False,
        alias_proxy: bool = False,
        client_id: str = '',
        client_secret: str = '',
        auth_url: str = 'https://auth.diving-fish.com',
        scope: str = 'prober.records.read',
    ) -> None:
        """配置热更新时重建请求参数。"""
        self.token = token
        self.timeout = timeout
        self.prober_api = self.MaiProxyAPI + '/maimaidxprober' if prober_proxy else self.MaiProberAPI
        self.alias_api = self.MaiProxyAPI + '/maimaidxaliases' if alias_proxy else self.MaiAliasAPI
        self.oauth: Optional[DivingFishOAuth] = None
        if client_id.strip() and client_secret.strip():
            try:
                normalized_scope = parse_scope(scope)
            except ValueError:
                normalized_scope = 'prober.records.read'
            self.oauth = DivingFishOAuth(
                client_id=client_id.strip(),
                client_secret=client_secret.strip(),
                auth_url=auth_url.strip() or 'https://auth.diving-fish.com',
                scope=normalized_scope,
                timeout=timeout,
            )

    @property
    def oauth_enabled(self) -> bool:
        return self.oauth is not None

    @property
    def headers(self) -> Optional[Dict[str, str]]:
        return {'developer-token': self.token} if self.token else None

    # ---------- 基础请求 ----------

    async def _requestmai(
        self,
        method: str,
        endpoint: str,
        extra_headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Union[Dict[str, Any], List[Any]]:
        headers = self.headers or {}
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(timeout=self.timeout) as session:
            res = await session.request(method, self.prober_api + endpoint,
                                        headers=headers or None, **kwargs)
        self._handle_prober_error(res)
        return res.json()

    def _handle_prober_error(self, res: httpx.Response, *, oauth: bool = False) -> None:
        if res.status_code == 200:
            return
        if res.status_code == 400:
            self._handle_400(res, oauth=oauth)
            return
        if res.status_code == 401:
            raise TokenError('查分器认证失败（401），请检查开发者 token 或 OAuth 配置')
        if res.status_code == 403:
            if oauth:
                raise OAuthNotBoundError('该用户未授权或授权范围不足，请重新「绑定水鱼」')
            raise UserDisabledQueryError('该玩家关闭了成绩查询权限，请对方在查分器网站开启')
        if res.status_code == 429:
            raise TooManyRequestsError('查分器请求过于频繁，请稍后再试')
        raise UnknownError(f'查分器接口错误: HTTP {res.status_code}')

    def _handle_400(self, res: httpx.Response, *, oauth: bool = False) -> None:
        error: Dict[str, Any] = {}
        try:
            error = res.json()
        except Exception:  # noqa: BLE001
            pass
        message = error.get('message')
        msg = error.get('msg')
        if message == 'no such user':
            raise UserNotFoundError('未找到该用户，请确认查分器用户名或QQ号是否正确')
        if message == 'user not exists':
            raise UserNotExistsError('该用户不存在，可能尚未在查分器绑定数据')
        if message:
            raise UserNotFoundError(str(message))
        if msg == '开发者token有误':
            raise TokenError('查分器开发者token有误，请检查插件配置 maimaidx_token')
        if msg == '开发者token被禁用':
            raise TokenDisableError('查分器开发者token被禁用，请联系水鱼')
        if msg == '请先联系水鱼申请开发者token':
            raise TokenError('未配置查分器开发者token，请在插件配置中填写，或配置 OAuth 的 client_id/client_secret')
        if msg:
            raise TokenError(str(msg))
        if oauth:
            raise OAuthError(f'查分器请求失败（HTTP 400）')
        raise UserNotFoundError('未找到该用户')

    async def _request_oauth(
        self,
        method: str,
        endpoint: str,
        user_id: Union[str, int],
        retried: bool = False,
        **kwargs,
    ) -> Union[Dict[str, Any], List[Any]]:
        """代用户请求：Authorization 由按用户签发的短期令牌提供。"""
        assert self.oauth is not None
        token = await self.oauth.get_access_token(user_id)
        async with httpx.AsyncClient(timeout=self.timeout) as session:
            res = await session.request(
                method, self.prober_api + endpoint,
                headers={'Authorization': f'Bearer {token}'}, **kwargs)
        if res.status_code == 401 and not retried:
            # 令牌过期/被撤销：刷新一次重试
            await self.oauth.get_access_token(user_id, refresh=True)
            return await self._request_oauth(method, endpoint, user_id, retried=True, **kwargs)
        self._handle_prober_error(res, oauth=True)
        return res.json()

    # ---------- 公开数据 ----------

    async def music_data(self) -> List[Dict[str, Any]]:
        """获取曲目数据（含定数、曲师、谱师、版本）。"""
        return await self._requestmai('GET', '/music_data')

    async def chart_stats(self) -> Dict[str, Any]:
        """获取谱面统计数据（含拟合定数 fit_diff）。"""
        return await self._requestmai('GET', '/chart_stats')

    # ---------- 用户成绩 ----------

    async def query_user_b50(
        self,
        *,
        qqid: Optional[int] = None,
        username: Optional[str] = None,
    ) -> UserInfo:
        """获取玩家 B50（公开接口，目标用户需允许查询）。"""
        json_data: Dict[str, Any] = {'b50': True}
        if qqid:
            json_data['qq'] = int(qqid)
        if username:
            json_data['username'] = username
        return UserInfo.model_validate(await self._requestmai('POST', '/query/player', json=json_data))

    async def query_user_plate(
        self,
        *,
        qqid: Optional[int] = None,
        username: Optional[str] = None,
        version: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """获取玩家指定版本的成绩列表（公开接口 verlist）。"""
        json_data: Dict[str, Any] = {}
        if qqid:
            json_data['qq'] = int(qqid)
        if username:
            json_data['username'] = username
        if version:
            json_data['version'] = version
        result = await self._requestmai('POST', '/query/plate', json=json_data)
        return result.get('verlist', []) if isinstance(result, dict) else []

    async def rating_ranking(self) -> List[Dict[str, Any]]:
        """获取查分器 Rating 排行榜（按 ra 降序）。"""
        result = await self._requestmai('GET', '/rating_ranking')
        return sorted(result, key=lambda x: x.get('ra', 0), reverse=True)

    async def query_user_records(
        self,
        *,
        oauth_user: Optional[str] = None,
        qqid: Optional[int] = None,
        username: Optional[str] = None,
    ) -> UserInfoDev:
        """获取用户全部成绩。

        配置 OAuth 且给了 oauth_user（BOT 侧用户标识）时走代查接口 /player/records；
        否则走开发者接口 /dev/player/records（需要开发者 token）。
        """
        if self.oauth_enabled and oauth_user:
            result = await self._request_oauth('GET', '/player/records', oauth_user)
        else:
            params: Dict[str, Any] = {}
            if qqid:
                params['qq'] = int(qqid)
            if username:
                params['username'] = username
            result = await self._requestmai('GET', '/dev/player/records', params=params)
        return UserInfoDev.model_validate(result)

    async def query_user_record(
        self,
        *,
        oauth_user: Optional[str] = None,
        qqid: Optional[int] = None,
        username: Optional[str] = None,
        music_id: Union[str, int, List[Union[str, int]]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """获取用户指定曲目成绩（OAuth 代查优先，其次开发者接口）。"""
        if not isinstance(music_id, list):
            music_id = [music_id]
        if self.oauth_enabled and oauth_user:
            result = await self._request_oauth(
                'POST', '/player/record', oauth_user, json={'music_id': music_id})
        else:
            json_data: Dict[str, Any] = {}
            if qqid:
                json_data['qq'] = int(qqid)
            if username:
                json_data['username'] = username
            json_data['music_id'] = music_id
            result = await self._requestmai('POST', '/dev/player/record', json=json_data)
        return result or {}

    # ---------- OAuth 绑定流程 ----------

    async def start_binding(self, user_id: Union[str, int]) -> Dict[str, Any]:
        """发起「绑定水鱼」，返回授权信息 dict。"""
        if not self.oauth:
            raise TokenError('未配置查分器 OAuth（divingfish_client_id / divingfish_client_secret）')
        return await self.oauth.device_authorization(user_id)

    async def complete_binding(self, user_id: Union[str, int], confirmation_code: str) -> None:
        """用确认码完成绑定。"""
        if not self.oauth:
            raise TokenError('未配置查分器 OAuth（divingfish_client_id / divingfish_client_secret）')
        await self.oauth.redeem(user_id, confirmation_code.strip())

    def unbind(self, user_id: Union[str, int]) -> None:
        """丢弃本地缓存的代查令牌（真正取消授权需在水鱼账号页操作）。"""
        if self.oauth:
            self.oauth.discard_token(user_id)

    # ---------- 别名库 ----------

    async def _requestalias(self, method: str, endpoint: str, **kwargs) -> APIResult:
        async with httpx.AsyncClient(timeout=self.timeout) as session:
            res = await session.request(method, self.alias_api + endpoint, **kwargs)
        if res.status_code == 200:
            return APIResult.model_validate(res.json())
        if res.status_code == 500:
            raise ServerError('别名库服务错误，请稍后再试')
        raise UnknownError(f'别名库接口错误: HTTP {res.status_code}')

    async def get_alias(self) -> List[Dict[str, Any]]:
        """获取全部曲目别名。"""
        result = await self._requestalias('GET', '/maimaidxalias')
        if result.code == 0 and isinstance(result.content, list):
            return result.content
        raise UnknownError(f'获取别名数据失败: code={result.code}')

    async def get_songs(self, name: str) -> APIResult:
        """按别名实时查询曲目。code=0 命中，code=3006 为正在投票的别名。"""
        return await self._requestalias('GET', '/getsongs', params={'name': name})

    async def get_plate_json(self) -> Dict[str, List[int]]:
        """获取所有版本牌子的曲目 ID 列表。"""
        result = await self._requestalias('GET', '/maimaidxplate')
        if result.code == 0 and isinstance(result.content, dict):
            return result.content
        raise UnknownError(f'获取牌子数据失败: code={result.code}')

    async def post_alias(
        self,
        song_id: int,
        alias_name: str,
        user_id: str,
        group_id: str = '',
        ws_uuid: str = '',
    ) -> Any:
        """提交别名申请（别名投票）。"""
        json_data = {
            'SongID': int(song_id),
            'ApplyAlias': alias_name,
            'ApplyUID': user_id,
            'GroupID': group_id,
            'WSUUID': ws_uuid,
        }
        result = await self._requestalias('POST', '/applyalias', json=json_data)
        return result.content

    async def agree_alias(self, tag: str, user_id: str) -> Any:
        """给进行中的别名投票同意。"""
        json_data = {'Tag': tag, 'AgreeUser': user_id}
        result = await self._requestalias('POST', '/agreeuser', json=json_data)
        return result.content
