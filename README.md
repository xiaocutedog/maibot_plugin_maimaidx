# maimaiDX 查分 MaiBot 插件

由 NoneBot 插件 `nonebot_plugin_maimaidx` 移植的 MaiBot 查分插件，并自己添加了猜歌的功能。

## 数据来源

- **水鱼查分器** `https://maimai.diving-fish.com/api/maimaidxprober`：曲目数据（定数、曲师、谱师、版本、难度）、谱面统计（拟合定数 fit_diff）、玩家 B50 / 成绩
- **水鱼账号服务** `https://auth.diving-fish.com`：新版 OAuth 授权（client_id/client_secret，代绑定用户查询成绩）
- **柚子社别名库** `https://www.yuzuchan.moe/api/maimaidx`：曲目别名

## 水鱼认证（两套机制，二选一或同时）

1. **开发者 token**（旧版，配置项 `api.maimaidx_token`）：用于「查成绩 用户名/QQ号 曲目」查他人成绩。
2. **OAuth client_id + client_secret**（新版，配置项 `api.divingfish_client_id` / `api.divingfish_client_secret`，两者都填写后自动启用）：
   - 用户发送「**绑定水鱼**」→ 机器人给出授权链接 → 用户在水鱼账号页确认后拿到一串确认码；
   - 用户发送「**水鱼确认码 XXXX**」完成绑定；
   - 之后发送「**查成绩 曲目ID或别名**」（不带用户名）即以 OAuth 代查方式查自己的成绩；
   - 机器人只保管 client_id/client_secret，不保存用户令牌；代查令牌 5 分钟有效并缓存在内存。
   - 「**解绑水鱼**」清除本地缓存令牌；彻底取消授权请到水鱼账号页操作。

## 可查询的字段（已实测验证）

| 字段 | 来源接口 | 字段名 |
|---|---|---|
| 歌曲定数 | music_data | `ds[]`（按难度下标） |
| 拟合定数 | chart_stats | `charts[id][i].fit_diff` |
| 版本 | music_data | `basic_info.from` |
| 难度 | music_data | `level[]` + 难度下标（Basic/Advanced/Expert/Master/Re:Master） |
| 曲师 | music_data | `basic_info.artist` |
| 谱师 | music_data | `charts[].charter` |

## 安装

1. 把 `maibot_plugin_maimaidx` 整个目录放进 MaiBot 的 `plugins/` 下，重启 MaiBot。
2. 插件自动完成初始化：
   - 拉取曲库/别名/牌子数据并缓存到数据目录（`data/plugins/maibot.plugin.maimaidx/`）；
   - 检测到未安装官方素材包时，**后台自动下载**（约 445MB，来源柚子社官方发布，需 2GB 磁盘空间）并解压启用，下载期间查询功能正常（简化渲染），完成后自动切换为源插件同款渲染；
3. 无网络环境：手动下载素材包（[官方发布](https://github.com/Yuri-YuzuChaN/nonebot-plugin-maimaidx)），解压后把 `static` 目录放到数据目录 `assets/static`，或在配置 `resources.assets_dir` 指向任意位置；曲库数据也可手动放入 `music_data.json` / `chart_stats.json`。
4. 若自动下载失败（源失效），可在配置 `resources.download_url` 填入新的素材包直链后重启。

## 聊天命令

| 命令 | 说明 |
|---|---|
| `查歌 关键词` / `search 关键词` | 按曲名或别名查歌，多个结果分页 |
| `xxx是什么歌` / `xxx是啥歌` | 通过别名反查乐曲 |
| `id 曲目ID` / `歌曲信息 曲目ID` | 曲目详情（定数、拟合定数、版本、难度、曲师、谱师、别名） |
| `随个 [dx/sd] [绿黄红紫白] 等级` | 随机曲目，如：`随个 紫14+`、`来个dx 13` |
| `随机 变量 值` | 按条件随机。变量：`定数`（如 `14.0-14.2` 或 `13.5`）、`拟合定数`、`版本`（牌子单字如 `祭` 或版本名关键词如 `fest`）、`难度`（绿/黄/红/紫/白 或等级 `14+`）、`分区`/`分类`（如 `东方`、`舞萌`、`niconico`、`流行`、`音击`、`其他游戏`、`宴会`）、`曲师`、`谱师`、`定数差距`（定数与拟合定数差值，单个值表示精确相等（保留两位小数），如 `0.5`；区间 `0.3-0.6`）。发 `随机 分区` 可列出全部可用分区 |
| `今日mai` / `今日舞萌` | 今日运势 + 推荐歌曲 |
| `mai什么` | 随机来一首；`mai什么推分` 按 B50 边缘推荐 |
| `猜歌` / `开始猜歌` | 文字提示猜歌（游玩过万的热门曲，随机 6 条提示） |
| `猜曲绘` / `开始猜曲绘` | 曲绘随机裁剪猜歌（频域加权裁剪，移植原版算法） |
| `猜黑白曲绘` / `开始猜黑白曲绘` | 同上，但曲绘转为黑白，难度更高 |
| `答案 歌名` | 猜歌作答。也支持 `答案歌名`、`答案是歌名`、`答案：歌名`（中英文冒号均可）；答案可用别名/曲名/ID，忽略大小写与空格 |
| `结束猜歌` | 放弃本轮并公布答案（5 分钟超时自动公布） |
| `定数查歌 13.5` | 定数查歌，支持 `定数查歌 13.0 13.6 页码` |
| `拟合查歌 13.5` | 按拟合定数查歌，格式同上 |
| `曲师查歌 名称 页码` | 按曲师查歌 |
| `谱师查歌 名称 页码` | 按谱师查歌 |
| `bpm查歌 180` | 按 BPM 查歌 |
| `14定数表` | 查看该等级全部曲目定数列表 |
| `b50` | 查自己的 B50（需在查分器绑定 QQ）；`b50 用户名` 或 `b50 QQ号` 查别人 |
| `minfo 曲目ID或别名` | 查自己的单曲成绩（绑定水鱼走 OAuth） |
| `查成绩 用户名/QQ号 曲目ID或别名` | 查指定玩家单曲成绩（需开发者 token） |
| `查看排名 [用户名] [页码]` | 查分器 Rating 排行榜 |
| `我的排名` | 自己的 Rating 排名 |
| `我要上10分` | 基于 B50 的推分建议（`我要上分` 看全部） |
| `分数线 紫799 100` | 分数线容错计算（`分数线 帮助`） |
| `爽将进度` / `真極进度` | 版本牌子完成进度 |
| `14 sss 进度` | 等级进度（等级 10+ 起，评价 s 起） |
| `添加别名 曲目ID或歌名 别名` | 提交别名申请（柚子社投票） |
| `同意别名 Tag` | 给进行中的别名投票 |
| `添加曲师别名 原名 新别名` / `添加谱师别名 原名 新别名` | 添加曲师/谱师别名：第一个参数可用原名或已有别名，第二个为新增别名（持久化到本地） |
| `曲师别名` / `谱师别名` | 查看曲师/谱师别名列表 |
| `绑定水鱼` / `水鱼确认码 XXXX` / `解绑水鱼` | 水鱼 OAuth 绑定流程 |
| `maihelp` / `mai帮助` / `查分帮助` | 帮助菜单（图片） |
| `maimai更新数据` | 重新拉取曲库/别名/牌子数据 |

## 猜歌游戏

- **文字提示版**：`猜歌` → 机器人从游玩过万的热门曲中随机选一首，给出 6 条提示（Expert/Master 等级、分类、版本、曲师、是否 DX、是否有白谱、BPM 中随机）；
- **图片版**：`猜曲绘` → 发送随机裁剪的曲绘局部（频域加权选区，与原版算法一致）；`猜黑白曲绘` → 同样流程但图片转为黑白；
- **作答**：通过 `答案` 指令作答（支持 `答案歌名`、`答案是歌名`、`答案：歌名`）（别名/曲名/ID 均可，忽略大小写和空格），其它消息不受影响；答对后公布成绩并发详情卡；
- `结束猜歌` 放弃并公布答案；5 分钟未猜出自动公布。每个聊天流同时只有一轮猜歌。

## 源插件同款渲染（官方素材包）

配置 `display.assets_dir` 指向官方素材包（Resource CN 1.55+，[下载地址](https://www.yuzuchan.moe)）解压后的 `static` 目录后，以下输出与源插件渲染完全一致：

- `id 曲目ID` —— 谱面详情卡（PRiSM PLUS 主题，含各难度 notes、拟合定数、RA 预测表）
- `minfo 曲目` / `查成绩` —— 谱面游玩数据卡
- `b50` —— B50 成绩单
- `14定数表` —— 定数表（按需现场渲染并缓存）
- `14完成表` / `14ap完成表` —— 等级完成表（新增）
- `爽将完成表` / `真極完成表` 等 —— 牌子完成表（新增）
- `爽将进度` 等牌子进度 —— 源插件同款进度图（进度条 + 未完成曲绘网格）
- `14 sss 进度` 等级进度 —— 源插件同款三段进度图（已完成/未完成成绩卡 + 未游玩小图）
- 查歌/筛选结果 ≤5 首发文本、>5 首发源插件同款「曲目列表」卡（新增）
- `查看排名` —— 源插件同款等宽字体文本图，50 名一页（新增）
- `maihelp` —— PRiSM PLUS 主题风格帮助菜单

主题可选 `prism_plus` / `circle`（配置 `display.render_theme`）。未配置素材包时自动回退到内置简化渲染。
文字过长时自动缩小字号完整显示（源插件为截断加 "..."）。
缺字回退：主字体（素材包字体）缺字时自动按 **MiSans**（随插件 `fonts/` 目录分发）→ 系统中日字体 → 彩色 emoji 字体 的顺序逐字回退，日文汉字、音符、emoji 等不再显示为方框（回退匹配依赖 `fonttools`）。

## 图片输出

查询结果默认用 Pillow 绘制成图片发送（与原版 NoneBot 插件类似）：

- **曲目详情**（`id xxx`）：曲名、分类/谱面/版本徽章、曲师、BPM、别名、各难度定数/拟合定数/谱师表，有曲绘时自动嵌入曲绘；
- **查歌/筛选列表**（查歌、定数查歌、拟合查歌、曲师查歌、谱师查歌、bpm查歌）：带表头的分页列表图；
- **B50 成绩单**（`b50`）：完整 B35/B15 成绩图；
- **帮助菜单**（`maihelp`）。

字体自动探测（Windows 微软雅黑 / Linux Noto CJK / macOS 苹方），也可在配置 `display.font_path` 指定；或把字体文件命名为 `font.ttf` 放进插件数据目录。Pillow 未安装或找不到字体时自动回退纯文本；配置 `display.use_image_output = false` 可整体关闭图片输出。

## LLM 工具（供 MaiBot 大模型调用）

- `maimaidx_song_info`：查询单曲详情（定数/拟合定数/版本/难度/曲师/谱师）
- `maimaidx_search_songs`：按定数/拟合定数/曲师/谱师/关键词筛选乐曲
- `maimaidx_player_b50`：查询玩家 B50 概要

## 配置（WebUI 或 config.toml）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `api.maimaidx_token` | （已内置） | 水鱼开发者 token（旧版认证，查他人成绩用） |
| `api.divingfish_client_id` | （已内置） | 水鱼 OAuth client_id，与 secret 同时填写后启用新版授权 |
| `api.divingfish_client_secret` | （已内置） | 水鱼 OAuth client_secret |
| `api.divingfish_auth_url` | auth.diving-fish.com | 水鱼账号服务地址 |
| `api.divingfish_scope` | prober.records.read | OAuth 授权范围（空格分隔可多个） |
| `api.request_timeout` | 30 | 请求超时（秒） |
| `api.use_prober_proxy` / `api.use_alias_proxy` | false | 接口走 yuzuchan 反代 |
| `api.cover_base_url` | yuzuchan 资源站（默认可用） | 在线曲绘地址；留空关闭。也可把曲绘图片放进数据目录 `covers/` |
| `api.artist_alias_url` / `api.charter_alias_url` | 空 | 曲师/谱师别名库 JSON 导入地址（格式 `{"别名": "全名"}` 或 `{"别名": ["全名1","全名2"]}`），留空仅用本地别名 |
| `display.songs_per_page` | 25 | 列表每页条数 |
| `display.send_cover_image` | true | 曲目详情附带曲绘（嵌入详情卡） |
| `display.long_output_forward` | true | 纯文本模式下的长输出用合并转发 |
| `display.use_image_output` | true | 图片输出总开关（失败自动回退文本） |
| `display.bot_name` | 苏涂二舟(xiaocutedog) | 图片 Generated by 署名（美术作者 Designed by 署名按素材条款保留） |
| `access.access_mode` | off | 访问控制：off 不限制 / black 黑名单 / white 白名单 |
| `access.blacklist` | 空 | 黑名单条目：`user:QQ`=用户，纯数字或 `group:群号`=群聊，空格/逗号分隔 |
| `access.whitelist` | 空 | 白名单条目，格式同上；**为空表示暂不限制** |
| `access.notify` | true | 拒绝时是否提示（关闭则静默拦截） |

## 黑白名单

`access.access_mode` 三种模式：

- **off**：不限制（默认）；
- **black**：名单内的用户/群**不可用**，其他人正常；
- **white**：**仅名单内**的用户/群可用，其他人收到提示。

条目格式：`user:123456` = 用户；纯数字 `654321` 或 `group:654321` = 群聊；多个条目用空格或逗号分隔。本地控制台操作员始终不受限。拦截对插件全部聊天命令生效（含 b50/猜歌/完成表等）；LLM 工具不受命令级限制。
| `display.font_path` | 空 | 自定义中文字体路径，留空自动探测 |

## 注意

- 开发者 token / OAuth client_secret 仅保存在插件配置中，不会通过任何命令参数传入。
- 拟合定数（fit_diff）来自水鱼全体玩家数据拟合，仅供参考，与游戏内实际的 Rating 单曲定数可能略有差异。
- 曲绘默认走柚子社资源站（`www.yuzuchan.moe/assets/maimaidx/cover`，已实测全量可用）；也可把图片（`{曲目ID}.png`）放入数据目录 `covers/` 文件夹优先使用，或改配置指向其他源。
- **曲师/谱师别名库**：社区暂无公开 API，插件提供两种方式积累：聊天命令 `添加曲师别名 原名 新别名`（原名支持已有别名，可链式追加）（存到数据目录 `artist_alias_local.json` / `charter_alias_local.json`），或在配置中填 `artist_alias_url` / `charter_alias_url` 导入任意社区 JSON 别名表（`maimai更新数据` 会重新拉取）。
