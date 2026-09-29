"""maimaidx MaiBot 插件本地集成测试：stub SDK + 真实查分器 API。

用法: python tests/test_local.py （需要能访问水鱼查分器与柚子社别名库的网络）
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent

# ---------- stub maibot_sdk ----------
from pydantic import BaseModel as _BaseModel
from pydantic import Field as _Field

sdk = types.ModuleType('maibot_sdk')


class _Component:
    def __init__(self, name, **kw):
        self.name = name
        self.meta = kw

    def __call__(self, fn):
        fn.__maibot_component_info__ = self
        return fn


class Command(_Component):
    def __init__(self, name, description='', pattern='', aliases=None, **kw):
        super().__init__(name, description=description, pattern=pattern, aliases=aliases, **kw)


class Tool(_Component):
    def __init__(self, name, description='', brief_description='', detailed_description='',
                 parameters=None, **kw):
        super().__init__(name, description=description, brief_description=brief_description,
                         detailed_description=detailed_description, parameters=parameters, **kw)


class PluginConfigBase(_BaseModel):
    pass


class MaiBotPlugin:
    def __init__(self):
        self.ctx = None
        self.config = None


sdk.Command = Command
sdk.Tool = Tool
sdk.PluginConfigBase = PluginConfigBase
sdk.MaiBotPlugin = MaiBotPlugin
sdk.Field = _Field

sdk_types = types.ModuleType('maibot_sdk.types')
sdk_types.CONFIG_RELOAD_SCOPE_SELF = 'self'


class ToolParamType:
    STRING = 'string'
    INTEGER = 'integer'
    NUMBER = 'number'
    BOOLEAN = 'boolean'
    ARRAY = 'array'
    OBJECT = 'object'


class ToolParameterInfo:
    def __init__(self, **kw):
        self.__dict__.update(kw)


sdk_types.ToolParamType = ToolParamType
sdk_types.ToolParameterInfo = ToolParameterInfo
sys.modules['maibot_sdk'] = sdk
sys.modules['maibot_sdk.types'] = sdk_types

# ---------- 加载插件 ----------
sys.path.insert(0, str(PLUGIN_DIR))
import importlib.util

spec = importlib.util.spec_from_file_location('maimaidx_plugin_test', PLUGIN_DIR / 'plugin.py')
mod = importlib.util.module_from_spec(spec)
sys.modules['maimaidx_plugin_test'] = mod
spec.loader.exec_module(mod)


class FakeLogger:
    def info(self, *a, **k):
        print('  [INFO]', *a)

    def warning(self, *a, **k):
        print('  [WARN]', *a)

    def error(self, *a, **k):
        print('  [ERR ]', *a)


class FakeSend:
    def __init__(self):
        self.texts = []
        self.images = []
        self.forwards = []

    async def text(self, t, sid, **k):
        self.texts.append(t)

    async def image(self, b, sid, **k):
        self.images.append(b)
        return True  # 模拟宿主发送成功，图片路径到此结束（与真实 ctx.send.image 一致）

    async def forward(self, msgs, sid, **k):
        self.forwards.append(msgs)
        return True


class FakeCtx:
    def __init__(self, data_dir):
        self.logger = FakeLogger()
        self.send = FakeSend()
        self.paths = types.SimpleNamespace(data_dir=data_dir)


async def main():
    tmp = Path(tempfile.mkdtemp(prefix='maimaidx_test_'))
    plugin = mod.create_plugin()
    plugin.ctx = FakeCtx(tmp)
    plugin.config = mod.MaimaidxConfig()
    plugin.config.display.send_cover_image = False  # 在线曲绘默认地址无效，测试时关闭
    plugin.config.resources.auto_download = False  # 显式关闭素材下载（插件默认值即关闭）

    print('=== 1. 数据初始化（真实 API）===')
    await plugin._init_data()
    assert plugin._data_ready(), '曲库数据加载失败'
    print(f'  曲目 {len(plugin.mai.total_list)}，别名 {len(plugin.mai.total_alias_list)}')

    def last_text():
        return plugin.ctx.send.texts[-1] if plugin.ctx.send.texts else '(无输出)'

    def run(pattern, text):
        m = re.search(pattern, text)
        return m.groupdict() if m else None

    print('=== 2. 命令正则抽查 ===')
    p_info = plugin.cmd_song_info.__maibot_component_info__.meta['pattern']
    p_search = plugin.cmd_search.__maibot_component_info__.meta['pattern']
    p_ds = plugin.cmd_search_ds.__maibot_component_info__.meta['pattern']
    p_b50 = plugin.cmd_b50.__maibot_component_info__.meta['pattern']
    p_alias = plugin.cmd_alias_lookup.__maibot_component_info__.meta['pattern']
    assert run(p_info, 'id 199') == {'sid': '199'}
    assert run(p_info, '歌曲信息11086') == {'sid': '11086'}
    assert run(p_info, '这个id 199') is None
    assert run(p_search, '查歌 チルノ')['name'] == 'チルノ'
    assert run(p_ds, '定数查歌 13.5') == {'args': '13.5'}
    assert run(p_ds, '帮我定数查歌 13.5') is None
    assert run(p_b50, 'b50') == {'target': None}
    assert run(p_b50, '查分 someuser') == {'target': 'someuser'}
    assert run(p_b50, '查分器是什么') is None, '查分器是什么 不应触发 b50'
    assert run(p_alias, '会员制餐厅是什么歌') == {'name': '会员制餐厅'}
    print('  正则抽查全部通过')

    print('=== 3. 曲目详情（定数/拟合定数/版本/难度/曲师/谱师，文本回退）===')
    plugin.config.display.use_image_output = False  # 临时关图，验证文本字段完整性
    plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123')
    text = last_text()
    print(text)
    for kw in ['定数', '拟合定数', '版本', '曲师', '谱师', 'BPM']:
        assert kw in text, f'详情缺少字段: {kw}'
    plugin.config.display.use_image_output = False  # 测试 4-15 走文本路径便于断言

    print('=== 4. 别名查歌（是什么歌）===')
    plugin.ctx.send.texts.clear()
    await plugin.cmd_alias_lookup(stream_id='s1', matched_groups={'name': '琪露诺的完美算术教室'}, user_id='123')
    assert 'チルノ' in last_text()
    print(' ', last_text().splitlines()[0])

    print('=== 5. 查歌（标题，多结果分页）===')
    plugin.ctx.send.texts.clear()
    await plugin.cmd_search(stream_id='s1', matched_groups={'name': 'チルノ'}, user_id='123')
    print(' ', last_text().splitlines()[0])

    print('=== 6. 定数查歌（49 首 → 曲目列表卡，无素材走简化列表图）===')
    plugin.config.display.use_image_output = True
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_search_ds(stream_id='s1', matched_groups={'args': '13.5'}, user_id='123')
    assert plugin.ctx.send.images, '多结果应发曲目列表卡'
    print('  定数查歌 → song_list OK')

    print('=== 7. 拟合定数查歌 ===')
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_search_fit(stream_id='s1', matched_groups={'args': '14.6 15.0'}, user_id='123')
    assert plugin.ctx.send.images, '多结果应发曲目列表卡'
    print('  拟合查歌 OK')

    print('=== 8. 曲师查歌（5 首 → 文本）===')
    plugin.config.display.use_image_output = False
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_search_artist(stream_id='s1', matched_groups={'args': 'Yooh'}, user_id='123')
    assert plugin.ctx.send.texts, '≤5 首应发文本'
    print(' ', plugin.ctx.send.texts[-1].splitlines()[0])

    print('=== 9. 谱师查歌（123 首 → 列表卡）===')
    plugin.config.display.use_image_output = True
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_search_charter(stream_id='s1', matched_groups={'args': '某S氏'}, user_id='123')
    assert plugin.ctx.send.images, '多结果应发曲目列表卡'
    print('  谱师查歌 → song_list OK')

    print('=== 10. b50 错误路径（不存在的用户）===')
    plugin.ctx.send.texts.clear()
    await plugin.cmd_b50(stream_id='s1', matched_groups={'target': 'no_such_user_xyz'}, user_id='123')
    print(' ', last_text())

    print('=== 11. 查成绩 错误路径（开发者接口，未配置 token）===')
    plugin.ctx.send.texts.clear()
    await plugin.cmd_record(stream_id='s1', matched_groups={'args': 'no_such_user_xyz 199'}, user_id='123')
    print(' ', last_text())

    print('=== 12. LLM 工具 ===')
    r1 = await plugin.tool_song_info(song_id='199')
    assert '定数' in r1['content']
    print('  tool_song_info OK：', r1['content'].splitlines()[0])
    r2 = await plugin.tool_search_songs(ds_min=14.5, ds_max=14.7, limit=5)
    print('  tool_search_songs OK：', r2['content'].splitlines()[0])
    r3 = await plugin.tool_player_b50(username='no_such_user_xyz')
    print('  tool_player_b50 OK：', r3['content'])

    print('=== 13. 凭据与 OAuth（默认不内置凭据，未配置时给出引导）===')
    assert plugin.config.api.maimaidx_token == '', '插件不应内置开发者 token'
    assert plugin.config.api.divingfish_client_id == '', '插件不应内置 OAuth client_id'
    assert plugin.config.api.divingfish_client_secret == '', '插件不应内置 OAuth client_secret'
    assert plugin.api.oauth_enabled is False, '未配置 OAuth 凭据时不应启用 OAuth'
    plugin.ctx.send.texts.clear()
    await plugin.cmd_bind_divingfish(stream_id='s1', user_id='12345')
    assert 'OAuth' in last_text() and 'client_id' in last_text(), last_text()
    print('  未配置 OAuth 引导 OK：', last_text().splitlines()[0])
    # 未配置开发者 token 时查他人成绩的提示（原「已内置 token」场景）
    plugin.ctx.send.texts.clear()
    await plugin.cmd_record(stream_id='s1', matched_groups={'args': 'no_such_user_xyz 199'}, user_id='123')
    print('  未配置开发者 token 提示：', last_text().splitlines()[0])
    # 有真实凭据时（环境变量提供）才跑端到端，避免把机密写进仓库
    test_cid = os.environ.get('MAIMAIDX_TEST_CLIENT_ID', '').strip()
    test_secret = os.environ.get('MAIMAIDX_TEST_CLIENT_SECRET', '').strip()
    if test_cid and test_secret:
        print('=== 13b. OAuth 真实凭据端到端（MAIMAIDX_TEST_CLIENT_ID/SECRET）===')
        plugin.api.apply_config(
            token=plugin.config.api.maimaidx_token.strip(), timeout=30,
            client_id=test_cid, client_secret=test_secret)
        assert plugin.api.oauth_enabled is True
        plugin.ctx.send.texts.clear()
        await plugin.cmd_bind_divingfish(stream_id='s1', user_id='12345')
        t = last_text()
        assert 'auth.diving-fish.com' in t and '确认码' in t, t
        print('  绑定水鱼 OK，真实授权链接已生成：',
              [l for l in t.splitlines() if 'auth' in l][0][:60] + '...')
        # 未绑定用户自查成绩 → 服务端 consent_required → 友好提示
        plugin.ctx.send.texts.clear()
        await plugin.cmd_record(stream_id='s1', matched_groups={'args': '199'}, user_id='12345')
        print('  查成绩（未绑定）OK：', last_text())
    else:
        print('  [跳过] 未设置 MAIMAIDX_TEST_CLIENT_ID / MAIMAIDX_TEST_CLIENT_SECRET，'
              '跳过真实 OAuth 端到端（假凭据错误路径见第 15 节）')

    print('=== 14. scope 解析 ===')
    from maimaidx_core import parse_scope
    assert parse_scope('prober.records.read') == 'prober.records.read'
    assert 'prober.records.read' in parse_scope('prober.profile.read prober.records.read')
    try:
        parse_scope('bad.scope')
        raise AssertionError('坏 scope 应报错')
    except ValueError:
        pass
    print('  scope 解析通过')

    print('=== 15. OAuth 错误路径（假 client_id/secret 打真实授权服务器）===')
    plugin.api.apply_config(
        token=plugin.config.api.maimaidx_token.strip(),
        timeout=30,
        client_id='test_invalid_client',
        client_secret='test_invalid_secret',
    )
    assert plugin.api.oauth_enabled is True
    plugin.ctx.send.texts.clear()
    await plugin.cmd_bind_divingfish(stream_id='s1', user_id='12345')
    print(' ', last_text())
    assert '失败' in last_text()
    plugin.api.apply_config(token=plugin.config.api.maimaidx_token.strip())  # 还原

    print('=== 16. maihelp 帮助菜单（图片）===')
    plugin.config.display.use_image_output = True  # 从这里开始测试图片路径
    assert mod.mai_render.available(), '字体不可用，无法测试图片输出'
    plugin.ctx.send.images.clear()
    plugin.ctx.send.texts.clear()
    r = await plugin.cmd_help(stream_id='s1')
    assert plugin.ctx.send.images, 'maihelp 应发送图片'
    out_dir = PLUGIN_DIR / 'tests' / 'out'
    out_dir.mkdir(exist_ok=True)
    (out_dir / 'help.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
    print(f'  已保存 {out_dir / "help.png"}')

    print('=== 17. 图片渲染样例（详情卡含曲绘/列表/B50）===')
    plugin.ctx.send.images.clear()
    plugin.ctx.send.texts.clear()
    plugin.config.display.send_cover_image = True  # 默认曲绘源（柚子社资源站）实测可用
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123')
    assert plugin.ctx.send.images, '曲目详情应发送图片'
    (out_dir / 'song_info.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
    plugin.config.display.send_cover_image = False
    plugin.ctx.send.images.clear()
    await plugin.cmd_search_ds(stream_id='s1', matched_groups={'args': '13.5'}, user_id='123')
    assert plugin.ctx.send.images, '列表应发送图片'
    (out_dir / 'list.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
    from maimaidx_core.model import UserInfo as UI, UserCharts as UC
    fake_user = UI.model_validate({
        'nickname': '测试用户', 'rating': 14532, 'additional_rating': 13000, 'plate': 'true 舞 MiLK P',
        'charts': {'sd': [
            {'achievements': 100.5, 'fc': 'ap', 'fs': 'fsdp', 'level': '14+', 'level_index': 3,
             'title': 'Oshama Scramble!', 'type': 'DX', 'ds': 14.6, 'ra': 502, 'dxScore': 2000}
            for _ in range(3)
        ], 'dx': [
            {'achievements': 99.9999, 'fc': 'fc', 'fs': '', 'level': '13+', 'level_index': 3,
             'title': 'Gourmandise', 'type': 'DX', 'ds': 13.7, 'ra': 480, 'dxScore': 1900}
            for _ in range(2)
        ]},
    })
    png = mod.mai_render.b50_image(fake_user)
    assert png
    (out_dir / 'b50.png').write_bytes(png)
    print(f'  已保存 {out_dir}/song_info.png, list.png, b50.png')

    print('=== 18. 原版功能移植：正则抽查 ===')
    p_rand = plugin.cmd_random.__maibot_component_info__.meta['pattern']
    p_plate = plugin.cmd_plate.__maibot_component_info__.meta['pattern']
    p_level = plugin.cmd_level_process.__maibot_component_info__.meta['pattern']
    p_rise = plugin.cmd_rise.__maibot_component_info__.meta['pattern']
    assert run(p_rand, '随个 紫14+') == {'diff': None, 'color': '紫', 'level': '14+'}
    assert run(p_rand, '来个dx 13')['diff'] is not None
    assert run(p_rand, '来个游戏') is None
    g = run(p_plate, '爽将进度')
    assert g['ver'] == '爽' and g['plan'] == '将'
    g = run(p_level, '14 sss 进度 2')
    assert g['level'] == '14' and g['plan'] == 'sss' and g['page'] == '2'
    assert run(p_rise, '我要上10分')['target'] == '10'
    assert run(p_rise, '我要上分') == {'target': ''}
    print('  正则抽查全部通过')

    print('=== 19. 原版功能移植：命令冒烟 ===')
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_random(stream_id='s1', matched_groups={'diff': None, 'color': '紫', 'level': '14+'}, user_id='123')
    assert plugin.ctx.send.images, '随机曲目应发图'
    print('  随机曲目 OK（紫14+）')

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_today(stream_id='s1', user_id='12345')
    assert plugin.ctx.send.texts and '人品值' in plugin.ctx.send.texts[0]
    print('  今日mai OK：', plugin.ctx.send.texts[0].splitlines()[0])

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_what(stream_id='s1', matched_groups={'point': ''}, user_id='12345')
    assert plugin.ctx.send.images
    print('  mai什么 OK（随机）')

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_what(stream_id='s1', matched_groups={'point': '推分'}, user_id='12345')
    assert plugin.ctx.send.images or plugin.ctx.send.texts
    print('  mai什么推分 OK（无绑定QQ回退随机）')

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_ginfo(stream_id='s1', matched_groups={'args': '紫199'}, user_id='123')
    t = last_text()
    assert '拟合难度' in t, t
    print('  ginfo OK：', t.splitlines()[0])

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_score_line(stream_id='s1', matched_groups={'args': '紫199 100'}, user_id='123')
    t = last_text()
    assert '分数线' in t and 'BREAK' in t, t
    print('  分数线 OK：', t.splitlines()[1])

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_ds_table(stream_id='s1', matched_groups={'level': '14'}, user_id='123')
    assert plugin.ctx.send.images, '定数表应发图'
    (out_dir / 'ds_table.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
    print('  14定数表 OK，已保存 ds_table.png')

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_ranking(stream_id='s1', matched_groups={'args': ''}, user_id='123')
    t = last_text() if plugin.ctx.send.texts else '(图片)'
    print('  查看排名 OK：', t.splitlines()[0] if t != '(图片)' else '(列表图)')

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_plate(stream_id='s1', matched_groups={'ver': '爽', 'plan': '将', 'user': 'no_such_user_xyz'}, user_id='123')
    print('  牌子进度错误路径 OK：', last_text())

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_level_process(stream_id='s1', matched_groups={'level': '14', 'plan': 'sss', 'page': None, 'user': 'no_such_user_xyz'}, user_id='123')
    print('  等级进度错误路径 OK：', last_text())

    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_rise(stream_id='s1', matched_groups={'target': ''}, user_id='123')
    print('  我要上分（无QQ引导）OK：', last_text())

    print('=== 20. 随机 变量 值 ===')
    p_rv = plugin.cmd_random_var.__maibot_component_info__.meta['pattern']
    assert run(p_rv, '随机 定数 14.0-14.2') == {'var': '定数', 'value': '14.0-14.2'}
    assert run(p_rv, '随机') == {'var': None, 'value': None}
    assert run(p_rv, '随机 版本 祭') == {'var': '版本', 'value': '祭'}

    async def rv(var, value):
        plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
        await plugin.cmd_random_var(stream_id='s1', matched_groups={'var': var, 'value': value}, user_id='123')
        if plugin.ctx.send.images:
            return f'图片({len(plugin.ctx.send.images)})'
        return last_text()

    r = await rv('定数', '14.0-14.2')
    assert r.startswith('图片'), r
    print('  随机 定数 14.0-14.2 OK')
    r = await rv('定数', '13.5')
    assert r.startswith('图片'), r
    print('  随机 定数 13.5 OK')
    r = await rv('拟合定数', '14.6-15.0')
    assert r.startswith('图片'), r
    print('  随机 拟合定数 OK')
    r = await rv('版本', '祭')
    assert r.startswith('图片'), r
    print('  随机 版本 祭 OK')
    r = await rv('版本', 'fest')
    assert r.startswith('图片'), r
    print('  随机 版本 fest（子串）OK')
    r = await rv('难度', '紫')
    assert r.startswith('图片'), r
    r = await rv('难度', 'remaster')
    assert r.startswith('图片'), r
    r = await rv('难度', '14+')
    assert r.startswith('图片'), r
    print('  随机 难度 紫/remaster/14+ OK')
    r = await rv('曲师', 'Yooh')
    assert r.startswith('图片'), r
    print('  随机 曲师 Yooh OK')
    r = await rv('谱师', '某S氏')
    assert r.startswith('图片'), r
    print('  随机 谱师 某S氏 OK')
    r = await rv('分区', '东方')
    assert r.startswith('图片'), r
    r = await rv('分区', '舞萌')
    assert r.startswith('图片'), r
    r = await rv('分类', 'niconico')
    assert r.startswith('图片'), r
    print('  随机 分区 东方/舞萌/niconico OK')
    r = await rv('分区', '')
    assert '当前曲库包含' in r and '东方Project' in r
    print('  随机 分区（无值列出分区）OK')
    r = await rv('分区', '不存在的分区')
    assert '没有找到分区' in r
    print('  未知分区提示 OK')
    r = await rv('定数差距', '0.5')
    # 单值 = 精确匹配：0.5 不一定有曲，需与"有曲或无曲提示"都兼容
    assert r.startswith('图片') or '没有符合' in r, r
    # 取数据里的真实差值做精确匹配，必须命中
    gap_val = None
    for _m in plugin.mai.total_list:
        if not _m.is_utage:
            _f = _m.fit_diff(3)
            if _f is not None:
                g = round(abs(_m.ds[3] - _f), 2)
                if g > 0:
                    gap_val = g
                    break
    assert gap_val is not None
    r = await rv('定数差距', str(gap_val))
    assert r.startswith('图片'), f'精确差值 {gap_val} 应命中: {r}'
    r = await rv('定数差距', '0.3-0.6')
    assert r.startswith('图片') or '没有符合' in r, r
    print(f'  随机 定数差距 精确(数据值 {gap_val}) / 区间 0.3-0.6 OK')
    r = await rv('不存在的变量', 'x')
    assert '不支持的变量' in r
    print('  未知变量提示 OK')
    r = await rv('定数', 'abc')
    assert '格式错误' in r or '数值' in r
    print('  非法数值提示 OK')

    print('=== 21. 曲师/谱师别名库 ===')
    # 新语义：第一个参数=原名/已有别名，第二个=新增别名
    # 用曲库真实曲师名作为原名：BlackY -> 黑橘
    plugin.ctx.send.texts.clear()
    await plugin.cmd_name_alias_add(stream_id='s1', matched_groups={'kind': '曲师', 'args': 'BlackY 黑橘'}, user_id='123')
    t = last_text()
    assert '已添加' in t and 'BlackY' in t, t
    print(' ', t.splitlines()[0])
    # 用别名随机
    r = await rv('曲师', '黑橘')
    assert r.startswith('图片'), r
    print('  别名「黑橘」随机 OK（命中 BlackY）')
    # 本地持久化文件存在
    local_file = plugin.ctx.paths.data_dir / 'artist_alias_local.json'
    assert local_file.exists(), '别名未持久化'
    import json as _json
    data = _json.loads(local_file.read_text(encoding='utf-8'))
    assert '黑橘' in {k.lower() for k in data}
    print('  别名本地持久化 OK：', data)
    # 链式追加：已有别名（黑橘）作为原名，再挂一个新别名
    plugin.ctx.send.texts.clear()
    await plugin.cmd_name_alias_add(stream_id='s1', matched_groups={'kind': '曲师', 'args': '黑橘 橘子'}, user_id='123')
    t = last_text()
    assert '已添加' in t and 'BlackY' in t, t
    r = await rv('曲师', '橘子')
    assert r.startswith('图片'), r
    print('  链式追加 OK：橘子 -> BlackY（经已有别名黑橘解析）')
    # 重复添加
    plugin.ctx.send.texts.clear()
    await plugin.cmd_name_alias_add(stream_id='s1', matched_groups={'kind': '曲师', 'args': 'BlackY 黑橘'}, user_id='123')
    if '已' not in last_text() or '重复' not in last_text() and '无需' not in last_text():
        raise AssertionError(f'重复添加提示异常，实际输出: {plugin.ctx.send.texts!r}')
    print('  重复添加提示 OK：', last_text())
    # 未知原名提示
    plugin.ctx.send.texts.clear()
    await plugin.cmd_name_alias_add(stream_id='s1', matched_groups={'kind': '曲师', 'args': '不存在的曲师xyz 某别名'}, user_id='123')
    assert '未在曲库' in last_text(), last_text()
    print('  未知原名提示 OK')
    # 别名列表
    plugin.ctx.send.texts.clear()
    await plugin.cmd_name_alias_list(stream_id='s1', matched_groups={'kind': '曲师'}, user_id='123')
    assert '别名' in last_text()
    print('  曲师别名列表 OK：', last_text().splitlines()[0])
    # resolve_name 原值回退
    assert plugin.mai.resolve_name('charter', 'Jack')[0] == 'Jack'
    print('  resolve_name 原值回退 OK')

    print('=== 22. 猜歌游戏 ===')
    assert len(plugin.mai.guess_pool()) > 100, '热门曲池应有大量曲目'
    # 作答指令正则：答案 xxx；旧的 猜歌 xxx 不再作为作答
    p_ans = plugin.cmd_guess_answer.__maibot_component_info__.meta['pattern']
    # 多种作答写法：答案X / 答案是X / 答案：X（中英文冒号）/ 空格可有可无
    assert run(p_ans, '答案 琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '答案琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '答案是琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '答案是 琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '答案：琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '答案:琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '答案是：琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '/答案 琪露诺') == {'answer': '琪露诺'}
    assert run(p_ans, '猜歌 琪露诺') is None
    # 文字提示版
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_start(stream_id='s1', user_id='123')
    t = last_text()
    assert '猜歌开始' in t and '答案 歌名' in t, t
    assert 's1' in plugin.guess_games
    print('  开始猜歌 OK：', t.splitlines()[0])
    # 答错
    plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_answer(stream_id='s1', matched_groups={'answer': '绝对不是这首歌'}, user_id='123')
    assert '猜错了' in last_text()
    print('  答错提示 OK：', last_text())
    # 答对（用真实答案）
    game = plugin.guess_games['s1']
    real_answer = game['answers'][0]
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_answer(stream_id='s1', matched_groups={'answer': real_answer.upper()}, user_id='123')
    assert '答对了' in last_text(), last_text()
    assert 's1' not in plugin.guess_games, '答对后游戏应结束'
    assert plugin.ctx.send.images, '答对应发送详情卡'
    print(f'  答对 OK（答案「{real_answer}」大小写不敏感），详情卡已发')
    # 图片版：开始猜曲绘
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_pic_start(stream_id='s1', user_id='123')
    assert plugin.ctx.send.images, '猜曲绘应发送裁剪图'
    (out_dir / 'guess_pic.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
    assert 's1' in plugin.guess_games and plugin.guess_games['s1']['mode'] == 'pic'
    print('  开始猜曲绘 OK，裁剪图已保存 guess_pic.png')
    # 同一会话只允许一轮：重复「开始猜歌」不重置题目（以第一个为准）
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_start(stream_id='s1', user_id='123')
    assert 's1' in plugin.guess_games
    first_game = plugin.guess_games['s1']
    first_music_id = first_game['music'].id
    plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_start(stream_id='s1', user_id='123')
    assert '已经在进行中' in last_text(), last_text()
    assert plugin.guess_games['s1'] is first_game, '重复开始不应替换对局'
    assert plugin.guess_games['s1']['music'].id == first_music_id, '题目不应被重置'
    print('  重复开始猜歌被拒（保留首轮）OK：', last_text())
    # 跨模式也不覆盖：曲绘版在文字版进行中时被拒
    plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_pic_start(stream_id='s1', user_id='123')
    assert '已经在进行中' in last_text(), last_text()
    assert plugin.guess_games['s1'] is first_game, '曲绘版不应替换文字版对局'
    print('  文字版进行中时猜曲绘被拒 OK')
    # 结束本轮后可以重新开始
    await plugin.cmd_guess_end(stream_id='s1', user_id='123')
    assert 's1' not in plugin.guess_games
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_pic_start(stream_id='s1', user_id='123')
    assert plugin.ctx.send.images and plugin.guess_games['s1']['mode'] == 'pic'
    print('  结束后可重新开始 OK')
    # 猜黑白曲绘：出图确实为灰度，且与猜曲绘互斥
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_bw_start(stream_id='s3', user_id='789')
    assert plugin.ctx.send.images, '黑白曲绘应发图'
    assert plugin.ctx.send.texts and '猜黑白曲绘' in plugin.ctx.send.texts[0], plugin.ctx.send.texts
    assert plugin.guess_games['s3']['mode'] == 'pic_bw', plugin.guess_games['s3']['mode']
    from PIL import Image as _PILImage
    _bw = _PILImage.open(__import__('io').BytesIO(base64.b64decode(plugin.ctx.send.images[-1])))
    assert _bw.mode == 'L', f'黑白模式图片应为灰度(L)，实际 {_bw.mode}'
    (out_dir / 'guess_pic_bw.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
    print('  开始猜黑白曲绘 OK（灰度图 mode=L，已存 guess_pic_bw.png）')
    # 黑白局进行中时，普通猜曲绘被拒
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_pic_start(stream_id='s3', user_id='789')
    assert '已经在进行中' in last_text() and not plugin.ctx.send.images
    print('  黑白局进行中时普通猜曲绘被拒 OK')
    # 黑白局也能正常作答
    _ans = plugin.guess_games['s3']['answers'][0]
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_answer(stream_id='s3', matched_groups={'answer': _ans}, user_id='789')
    assert '答对了' in last_text(), last_text()
    assert 's3' not in plugin.guess_games
    print('  黑白局作答 OK')

    # 不同会话互不影响
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_start(stream_id='s2', user_id='456')
    assert 's2' in plugin.guess_games and plugin.guess_games['s2']['mode'] == 'hint'
    print('  不同会话各自独立的对局 OK')
    await plugin.cmd_guess_end(stream_id='s2', user_id='456')

    # 曲绘版用 ID 作答
    game = plugin.guess_games['s1']
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_answer(stream_id='s1', matched_groups={'answer': game['music'].id}, user_id='123')
    assert '答对了' in last_text()
    print('  曲绘版 ID 作答 OK')
    # 退化输入（只写答案没跟歌名）友好提示
    await plugin.cmd_guess_start(stream_id='s1', user_id='123')
    plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_answer(stream_id='s1', matched_groups={'answer': '是'}, user_id='123')
    assert '请在「答案」后面写上歌曲名' in last_text(), last_text()
    print('  退化输入提示 OK')
    await plugin.cmd_guess_end(stream_id='s1', user_id='123')

    # 无游戏时答题引导
    plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_answer(stream_id='s1', matched_groups={'answer': 'x'}, user_id='123')
    assert '猜歌' in last_text() and '猜曲绘' in last_text(), last_text()
    print('  无游戏引导 OK：', last_text())
    # 结束猜歌
    await plugin.cmd_guess_start(stream_id='s1', user_id='123')
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_guess_end(stream_id='s1', user_id='123')
    assert '猜歌已结束' in last_text()
    assert 's1' not in plugin.guess_games
    print('  结束猜歌 OK：', last_text().splitlines()[0])

    print('=== 22b. 谱面 notes 列映射（防回归）===')
    from maimaidx_core.source_render import notes_columns
    from maimaidx_core.model import Chart as _Chart
    # SD：4 值 [tap, hold, slide, brk] → touch 显示 '-'，brk 取第 4 个值
    _sd = notes_columns(_Chart.model_validate({'notes': [84, 30, 4, 4], 'charter': '-'}))
    assert _sd == [122, 84, 30, 4, '-', 4], _sd
    # DX：5 值 [tap, hold, slide, touch, brk] → touch/brk 各就各位
    _dx = notes_columns(_Chart.model_validate({'notes': [141, 7, 2, 6, 5], 'charter': '-'}))
    assert _dx == [161, 141, 7, 2, 6, 5], _dx
    print('  SD/DX notes 列映射 OK：', _sd, _dx)

    print('=== 23. 源插件渲染（官方素材包）===')
    ASSETS = Path(r'D:\maimaidx_assets\Resource CN1.55\static')
    if not ASSETS.is_dir():
        print('  [跳过] 本机无素材包目录')
    else:
        plugin.config.display.assets_dir = str(ASSETS)
        plugin._init_source_renderer()
        assert plugin.srender is not None, '源渲染器应初始化成功'
        assert plugin.srender.theme == 'prism_plus', 'theme 属性应就绪（init 完整性）'
        # 直接调用源渲染，确保没有静默回退
        _music = plugin.mai.total_list.by_id('199')
        _png = plugin.srender.song_chart_info(_music, None)
        assert _png and len(_png) > 100000, '源渲染应真实出图'
        # id 卡片
        plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
        await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123')
        assert plugin.ctx.send.images, 'id 应走源渲染发图'
        (out_dir / 'src_id.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
        print('  id 源渲染 OK')
        # 定数表
        plugin.ctx.send.images.clear()
        await plugin.cmd_ds_table(stream_id='s1', matched_groups={'level': '14'}, user_id='123')
        assert plugin.ctx.send.images, '定数表应走源渲染发图'
        (out_dir / 'src_ds_table.png').write_bytes(base64.b64decode(plugin.ctx.send.images[-1]))
        print('  定数表源渲染 OK')
        # 无素材回退路径
        plugin.srender = None
        plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
        await plugin.cmd_level_table(stream_id='s1', matched_groups={'level': '14', 'plan': ''}, user_id='123')
        assert '素材' in last_text() or 'assets_dir' in last_text()
        print('  无素材引导 OK：', last_text().splitlines()[0])

    print('=== 24. 黑白名单 ===')
    # 黑名单：用户（user: 前缀条目）
    plugin.config.access.access_mode = 'black'
    plugin.config.access.blacklist = 'user:555 999 group:998'
    plugin.config.access.notify = True
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='555')
    assert '禁止' in last_text() and not plugin.ctx.send.images, '黑名单用户应被拦截'
    print('  黑名单用户拦截 OK：', last_text())
    # 黑名单：群聊（纯数字条目）
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='456', group_id='999')
    assert '本群' in last_text() and not plugin.ctx.send.images, '黑名单群应被拦截'
    print('  黑名单群拦截 OK：', last_text())
    # 黑名单：群聊（group: 前缀条目）
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='456', group_id='998')
    assert '本群' in last_text() and not plugin.ctx.send.images, 'group: 前缀条目应拦截'
    print('  group: 前缀群拦截 OK：', last_text())
    # 新语义核心：纯数字 999 是群聊条目，不再匹配用户；用户 123 未被误拦
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123', group_id='777')
    assert plugin.ctx.send.images, '纯数字条目只匹配群聊，不应拦截用户 123'
    print('  纯数字=群聊语义修正 OK（不再误拦同号用户）')
    # user: 前缀条目拦截指定用户
    plugin.config.access.blacklist = 'user:123 999'
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123', group_id='777')
    assert '禁止' in last_text() and not plugin.ctx.send.images, 'user: 条目应拦截用户'
    print('  user: 前缀用户拦截 OK：', last_text())
    plugin.config.access.blacklist = '999 group:998'
    # 非名单用户正常
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='456', group_id='777')
    assert plugin.ctx.send.images, '非名单用户应正常使用'
    print('  非名单用户放行 OK')
    # 控制台操作员豁免
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123', is_local_operator=True)
    assert not ('禁止' in (plugin.ctx.send.texts[-1] if plugin.ctx.send.texts else '')), '控制台应豁免'
    print('  控制台豁免 OK')
    # 静默拦截（黑名单含 user:123，静默模式下被拦用户 123 无任何输出）
    plugin.config.access.blacklist = 'user:123 999 group:998'
    plugin.config.access.notify = False
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123')
    assert not plugin.ctx.send.texts and not plugin.ctx.send.images, '静默模式应无输出'
    print('  静默拦截 OK')
    plugin.config.access.notify = True
    plugin.config.access.notify = True
    # 白名单
    plugin.config.access.access_mode = 'white'
    plugin.config.access.whitelist = 'user:123'
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='456')
    assert '未对' in last_text(), '白名单外应被拦截'
    print('  白名单外拦截 OK：', last_text())
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='123')
    assert plugin.ctx.send.images, '白名单内应放行'
    print('  白名单内放行 OK')
    # 白名单为空 = 不限制
    plugin.config.access.whitelist = ''
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='456')
    assert plugin.ctx.send.images, '空白名单应不限制'
    print('  空白名单不限制 OK')
    # 还原
    plugin.config.access.access_mode = 'off'
    plugin.config.access.blacklist = ''
    print('  包装后元数据完好：', plugin.cmd_song_info.__maibot_component_info__.meta['pattern'][:24])

    print('=== 25. 素材下载模块（默认关闭 / https / 校验 / zip-slip）===')
    from PIL import Image as _Img
    from maimaidx_core.asset_fetch import (
        AssetFetchError,
        check_member_paths,
        check_url,
        download_archive,
        enough_space,
        extract_archive,
        find_static_dir,
        sha256_file,
    )
    assert plugin.config.resources.auto_download is False, '素材自动下载应默认关闭'
    assert plugin.config.resources.download_url == '', '素材下载地址应默认为空'
    assert plugin._assets_task is None, '默认配置下不应触发素材自动下载任务'
    print('  默认关闭 OK（auto_download=False，未创建下载任务）')
    assert enough_space(Path(tempfile.gettempdir())), '磁盘空间检查应通过'
    # 只接受 https
    assert check_url('https://example.com/a.7z') == 'https://example.com/a.7z'
    for bad_url in ('http://example.com/a.7z', 'ftp://example.com/a.7z', '', 'example.com/a.7z'):
        try:
            check_url(bad_url)
            raise AssertionError(f'非 https 地址应被拒绝: {bad_url}')
        except AssetFetchError:
            pass
    print('  https 限制 OK')
    # http 源直接拒绝，不会发起下载
    plugin.config.resources.download_url = 'http://example.com/a.7z'
    await plugin._ensure_assets()
    assert not (tmp / 'maimaidx_resources.7z').exists(), 'http 源不应下载任何文件'
    plugin.config.resources.download_url = ''
    print('  resources.download_url=http:// 被拒绝且未下载 OK')
    # 包内路径校验（zip-slip）
    good = ['SomePack/static/mai/pic/1.png', 'SomePack/static/font/f.ttf', './a/b.png']
    check_member_paths(good, tmp / 'member_check')
    for evil in ['../evil.txt', '/abs/evil.txt', 'C:/evil.txt', 'a/../../evil.txt',
                 'SomePack/../../evil.txt', '..\\evil.txt']:
        try:
            check_member_paths([evil], tmp / 'member_check')
            raise AssertionError(f'应拒绝非法包内路径: {evil}')
        except AssetFetchError:
            pass
    print('  check_member_paths 拒绝越界路径 OK')
    # 真造一个含 ../ 成员的恶意包，确认解压被拦截（且没有写到 workdir 之外）
    import py7zr
    payload_dir = tmp / 'payload'
    payload_dir.mkdir(exist_ok=True)
    (payload_dir / 'evil_payload.txt').write_text('pwned')
    evil_7z = tmp / 'evil.7z'
    with py7zr.SevenZipFile(str(evil_7z), 'w') as z:
        z.write(str(payload_dir / 'evil_payload.txt'), arcname='../evil_payload.txt')
    evil_work = tmp / 'evil_extract'
    try:
        extract_archive(evil_7z, evil_work)
        raise AssertionError('含 ../ 成员的包应被拒绝')
    except AssetFetchError:
        pass
    assert not (tmp / 'evil_payload.txt').exists(), 'zip-slip：不应写到解压目录之外'
    print('  恶意 7z（../ 成员）解压被拦截 OK')
    # 构造一个迷你素材包 7z 验证解压与定位
    mini_root = tmp / 'mini_pack'
    (mini_root / 'SomePack' / 'static' / 'mai' / 'pic').mkdir(parents=True, exist_ok=True)
    (mini_root / 'SomePack' / 'static' / 'mai' / 'cover').mkdir(parents=True, exist_ok=True)
    (mini_root / 'SomePack' / 'static' / 'font').mkdir(parents=True, exist_ok=True)
    _Img.new('RGBA', (4, 4)).save(mini_root / 'SomePack' / 'static' / 'mai' / 'pic' / 't.png')
    _Img.new('RGBA', (4, 4)).save(mini_root / 'SomePack' / 'static' / 'mai' / 'cover' / '0.png')
    (mini_root / 'SomePack' / 'static' / 'font' / 'f.txt').write_text('font')
    mini_7z = tmp / 'mini.7z'
    with py7zr.SevenZipFile(str(mini_7z), 'w') as z:
        z.writeall(mini_root, 'arc')
    static = extract_archive(mini_7z, tmp / 'mini_extract')
    assert static is not None and (static / 'mai' / 'pic').is_dir(), '应定位到 static'
    print('  extract_archive + find_static_dir OK:', static.name)
    # 验证字体目录布局被 SourceRenderer 认可的路径结构存在
    assert (static / 'font').is_dir() and (static / 'mai' / 'cover').is_dir()
    # 完整性校验：哈希计算正确；全部源为 http 时直接失败且不留文件
    assert sha256_file(payload_dir / 'evil_payload.txt') == hashlib.sha256(b'pwned').hexdigest(), \
        'sha256_file 结果不符'
    try:
        await download_archive(['http://example.com/a.7z'], tmp / 'never.7z')
        raise AssertionError('全部源非 https 时应报错')
    except AssetFetchError:
        pass
    assert not (tmp / 'never.7z').exists() and not (tmp / 'never.part').exists()
    print('  sha256_file + 非 https 源直接失败 OK')
    # 非法压缩包（非 7z：文件头校验失败）
    bad = tmp / 'bad.7z'
    bad.write_bytes(b'not a 7z file')
    try:
        extract_archive(bad, tmp / 'bad_extract')
        raise AssertionError('坏压缩包应报错')
    except AssetFetchError:
        pass
    print('  坏压缩包报错 OK')

    print('=== 26. 回复/引用消息不触发指令 ===')
    cited = {'type': 'reply', 'data': {'target_message_id': '1', 'target_message_content': 'id 199'}}

    async def song_info(text, segments):
        """模拟宿主：回复消息的 text = 被引用原文 + 自己的文本。"""
        plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
        return await plugin.cmd_song_info(
            stream_id='s1', matched_groups={'sid': '199'}, user_id='456',
            text=text, message={'raw_message': segments})

    # 1. 引用别人发过的指令、自己没写指令 → 不触发（原 bug 场景）
    res = await song_info('id 199', [cited])
    assert not plugin.ctx.send.images and not plugin.ctx.send.texts, '被引用原文里的指令不应触发'
    assert res[2] is False, f'应放行给后续流程（intercept=False），实际 {res}'
    print('  引用原文里的指令不触发 OK：', res)

    # 2. 引用别人发过的指令，自己在回复里也写指令 → 照常触发
    await song_info('id 199\nid 11086', [cited, {'type': 'text', 'data': 'id 11086'}])
    assert plugin.ctx.send.images or plugin.ctx.send.texts, '自己写的指令应触发'
    print('  引用原文含指令但自己也写了指令 → 照常触发 OK')

    # 3. 引用无关消息，自己写指令 → 照常触发
    other = {'type': 'reply', 'data': {'target_message_content': '这歌真好听'}}
    await song_info('这歌真好听\nid 199', [other, {'type': 'text', 'data': 'id 199'}])
    assert plugin.ctx.send.images or plugin.ctx.send.texts, '回复无关消息时自己写的指令应触发'
    print('  回复无关消息时指令照常触发 OK')

    # 4. 纯文本消息（非回复）不受影响
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_song_info(stream_id='s1', matched_groups={'sid': '199'}, user_id='456', text='id 199')
    assert plugin.ctx.send.images or plugin.ctx.send.texts, '普通消息应照常触发'
    print('  普通消息回归 OK')

    # 5. 回复段没带原文（适配器未提供 target_message_content）→ 保守不触发
    bare = {'type': 'reply', 'data': {'target_message_id': '1'}}
    await song_info('id 199', [bare])
    assert not plugin.ctx.send.images and not plugin.ctx.send.texts, '取不到被引用原文时应保守忽略'
    print('  取不到被引用原文时保守忽略 OK')

    # 6. 其它指令同样生效（b50 引用了别处的 b50）
    plugin.ctx.send.images.clear(); plugin.ctx.send.texts.clear()
    await plugin.cmd_b50(stream_id='s1', user_id='123', matched_groups={'target': 'no_such_user_xyz'},
                         text='b50 no_such_user_xyz',
                         message={'raw_message': [{'type': 'reply', 'data': {
                             'target_message_content': 'b50 no_such_user_xyz'}}]})
    assert not plugin.ctx.send.images and not plugin.ctx.send.texts, 'b50 被引用时也不应触发'
    print('  b50 引用场景不触发 OK')

    print()
    print('ALL TESTS PASSED')


if __name__ == '__main__':
    asyncio.run(main())
