# maimaiDX 查分 MaiBot 插件

由 NoneBot 插件 `nonebot_plugin_maimaidx` 移植的 MaiBot 查分插件。

## 数据来源与外部请求

插件需要联网访问以下第三方服务。下表列出每个出口会发出什么内容，便于部署前评估；除此之外不会上传聊天记录或其他用户数据。

| 出口 | 地址 | 发出的内容 | 触发时机 |
|---|---|---|---|
| 水鱼查分器 | `https://maimai.diving-fish.com/api/maimaidxprober` | 曲目/谱面数据拉取；查询成绩时的查分器用户名或 QQ 号；开发者 token（配置后随请求头发送） | 初始化、`maimai更新数据`、`b50` / `查成绩` 等 |
| 水鱼账号服务 | `https://auth.diving-fish.com` | OAuth client_id / client_secret、用户确认码、代查令牌请求 | `绑定水鱼` / `水鱼确认码` 及 OAuth 代查 |
| 柚子社别名库 | `https://www.yuzuchan.moe/api/maimaidx` | 曲目别名数据拉取；**别名投票会把曲目ID、别名、申请者 QQ 号（ApplyUID）、群号（GroupID）、客户端 UUID（WSUUID）提交给柚子社** | 初始化/更新数据；`添加别名` / `同意别名` |
| 柚子社资源站 | `https://www.yuzuchan.moe/assets/maimaidx/cover` | 按曲目ID请求曲绘图片 | 曲目详情附带曲绘时（可用 `api.cover_base_url` 关掉或换源） |
| 柚子社反代 | `https://proxy.yuzuchan.site` | 与水鱼查分器/别名库相同的请求（含对应凭据） | 仅当 `api.use_prober_proxy` / `api.use_alias_proxy` 开启 |
| 腾讯 QQ 头像 | `https://q1.qlogo.cn/g` | 被查询者的 QQ 号（用于 B50 成绩单上的头像） | `b50 QQ号` 且素材包源渲染可用时 |
| 素材下载源 | 见下方「官方素材包」 | 不含用户数据，仅下载素材包 | `resources.auto_download` 开启时 |
| 自定义地址 | `api.artist_alias_url` / `api.charter_alias_url` / `resources.download_url` | 由管理员填写，请求内容取决于该地址运营方 | 对应配置非空时 |

客户端 UUID（别名投票上报，WSUUID）每次启动用 `uuid4` 随机生成，不含 MAC 地址等设备信息。

## 水鱼认证（两套机制，二选一或同时；凭据均需自行申请）

插件**不内置任何凭据**，以下两项都需要部署者自己向水鱼申请并填入配置，留空则对应功能不可用。

1. **开发者 token**（旧版，配置项 `api.maimaidx_token`）：用于 `查成绩 用户名/QQ号 曲目` 查他人成绩。
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
2. 插件自动完成初始化：拉取曲库/别名/牌子数据并缓存到数据目录（`data/plugins/xiaocutedog.maibot_plugin_maimaidx/`）。未找到官方素材包时使用内置简化渲染，**不会自动下载素材包**（默认关闭，见下方「官方素材包」）。
3. 想要源插件同款渲染：手动下载素材包（[官方发布](https://github.com/Yuri-YuzuChaN/nonebot-plugin-maimaidx)），解压后把 `static` 目录放到数据目录 `assets/static`，或在配置 `resources.assets_dir` 指向任意位置；曲库数据也可手动放入 `music_data.json` / `chart_stats.json`。
4. 也可以把 `resources.auto_download` 设为 `true`，由插件在后台下载并解压官方素材包（约 445MB，需 2GB 磁盘空间；下载期间查询功能正常，完成后自动启用源渲染）。

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

## 官方素材包（自动下载）

`resources.auto_download` 默认 **关闭**：装好插件不会自动拉取 445MB 素材包，需要时由部署者主动开启。开启后插件在后台下载并解压（不阻塞聊天命令），完成后自动切换到源插件同款渲染。

**下载源**（`resources.download_url` 留空时按顺序尝试，仅接受 https 直链）：

- `https://cloud.yuzuchan.moe/f/34s7/Resource%20CN1.55.7z` —— 柚子社官方发布，主源；
- `https://share.yuzuchan.moe/d/downloads/Resource%20CN1.55.7z?sign=...` —— 官方分享直链，`sign` 会过期，只作备用。

素材包由柚子社（Yuri-YuzuChaN）发布，内容是 nonebot-plugin-maimaidx 的 `static` 资源（曲绘 / 字体 / 模板）。插件只负责下载与解压，不会检查素材内容本身，请自行确认来源可信。

**完整性校验**：下载完成后会校验

- 体积下限与 7z 文件头，拦截错误页和截断文件；
- SHA-256：可把期望值填在 `resources.download_sha256`，或由源站提供 `<下载地址>.sha256` 旁挂文件（自动读取）。不符即丢弃该源并尝试下一个源。旁挂文件只能发现损坏或源站意外改动，**要抵御恶意源站请用 `resources.download_sha256` 固定哈希**；日志中的实际 SHA-256 可作固定值参考。
  注意：两个下载源的包并非同一份文件（实测体积 467150820 / 467136848 字节），固定哈希只对应其中一个；多源配置下若主源失效，备用源会因哈希不符被拒绝（日志会写明原因），此时改填该源对应的哈希或清空该配置即可。

**解压安全**：解压前逐个校验包内成员路径，拒绝绝对路径、盘符、`..` 跳转以及解压后落在目标目录之外的条目（防 Zip-Slip），并拒绝缺少 `static/mai/pic` 的包。定位到的 `static` 会搬到数据目录 `assets/static`（同路径旧目录会被删除）。

**风险提示**：`resources.download_url` 可以指向任意 https 地址，插件会下载并解压其内容到数据目录，请只填写你信任的地址。

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
| `api.maimaidx_token` | 空 | 水鱼开发者 token（旧版认证，查他人成绩用）。**插件不内置，需自行申请**；留空则该功能不可用 |
| `api.divingfish_client_id` | 空 | 水鱼 OAuth client_id，与 secret 同时填写后启用新版授权。**插件不内置，需自行申请** |
| `api.divingfish_client_secret` | 空 | 水鱼 OAuth client_secret，属真实机密，请勿提交到版本库 |
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
| `display.font_path` | 空 | 自定义中文字体路径（.ttf/.ttc/.otf），留空自动探测系统字体 |
| `resources.auto_download` | **false** | 未找到素材包时是否自动下载（约 445MB，需 2GB 磁盘空间）。默认关闭，开启前请阅读「官方素材包」一节 |
| `resources.assets_dir` | 空 | 素材包 `static` 目录路径；留空则用数据目录 `assets/static` |
| `resources.download_url` | 空 | 自定义素材包下载地址（**仅接受 https** 的 .7z 直链），留空使用内置官方源 |
| `resources.download_sha256` | 空 | 素材包 SHA-256 校验值（可选），填写后校验不通过即拒绝解压 |
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

## 注意

- **凭据不由插件内置**：开发者 token 与 OAuth client_id/client_secret 都需要部署者自行申请后填入配置，只在配置中保存，不会通过任何命令参数传入。
  - 如果你的配置是从 **1.2.0 之前的版本**（内置了水鱼凭据）沿用或导入的，配置里可能还留着旧的 token / client_secret。这些值曾随插件公开分发，**建议到水鱼重新申请/重置后替换**，并顺手清空配置中的旧值。
- **回复/引用消息不触发指令**：宿主会把回复消息的文本拼成「被引用原文 + 你自己的文字」，为避免"引用别人的指令导致重复执行"，插件只在**你自己写的那段文字**里匹配指令——引用原文里的指令不会触发；拿不到被引用原文时（适配器未提供）同样保守忽略。直接发送指令不受影响；在回复里自己手写指令也照常生效。
- 拟合定数（fit_diff）来自水鱼全体玩家数据拟合，仅供参考，与游戏内实际的 Rating 单曲定数可能略有差异。
- 曲绘默认走柚子社资源站（`www.yuzuchan.moe/assets/maimaidx/cover`，已实测全量可用）；也可把图片（`{曲目ID}.png`）放入数据目录 `covers/` 文件夹优先使用，或改配置指向其他源。
- **曲师/谱师别名库**：社区暂无公开 API，插件提供两种方式积累：聊天命令 `添加曲师别名 原名 新别名`（原名支持已有别名，可链式追加）（存到数据目录 `artist_alias_local.json` / `charter_alias_local.json`），或在配置中填 `artist_alias_url` / `charter_alias_url` 导入任意社区 JSON 别名表（`maimai更新数据` 会重新拉取）。
