# C002 M1 项目、设置与剧集 Spec

## 1. 规范边界

本 spec 只授权 ROADMAP `C002`。规范来源为 PRD §2.1(1-4)、§3.2、§3.3 对应行、§3.5 R11、§4、§5“项目与设置/剧集”、§9、§11 M1 与 §12；PRD §0 范围围栏始终优先。

PRD §11 规定级联在下游实体所在里程碑落地。因此 C002 的“项目 DELETE 级联”只覆盖 C002 可创建的剧集；资产、分镜、片段、任务及文件级联不得在本 change 提前实现。固定模板管理以 PRD §5 的 GET/PATCH 为准，不因 ROADMAP 的概括性“CRUD”增加模板 POST/DELETE。

## 2. 可观察交付物

C002 完成后必须同时满足：

1. FastAPI 使用真实 PostgreSQL async session 提供项目、风格、模板与剧集 API，所有 mutation 在单一事务内成功或整体回滚。
2. Alembic head 比 C001 多一条数据 revision；迁移后的 `prompt_templates` 恰有四个固定 key 及本 spec 的占位内容，表结构与其余业务数据不变。
3. 用户能从前端创建风格，创建选择该风格的项目，在项目中创建剧集，通过明确的“进入集工作区”入口进入真实 ID 的工作区；剧本页默认展示最近一次持久化剧本，由页内“编辑剧本”按钮进入编辑态，保存成功后得到可见反馈；工作区可用按钮返回当前项目详情，项目详情可用按钮返回项目首页。
4. 剧本实际变化时 `script_revision` 每个成功请求增加一次；标题/集序修改和同值剧本 PATCH 不增加；任何剧本编辑都不修改下游实体、状态或文件。
5. 风格或模板实际变化后读取立即返回新内容，但既有分镜、片段、产物与文件不变，不生成版本或 hash。
6. 设置页可见并可编辑风格与四个模板；项目/剧集 CRUD 页面可用；集工作区展示四个选项卡，但资产/分镜/导演台不含后续业务能力。
7. 所有失败都使用统一错误体，409/422 语义符合本 spec；HTTP 客户端不重试。

## 3. 数据与事务约束

### 3.1 运行时数据库边界

- 使用 C001 的 `DATABASE_URL`、SQLAlchemy 2 async engine 与 asyncpg；不得加入 SQLite、同步 engine、连接失败 fallback 或自动重试。
- 每个请求取得独立 `AsyncSession`。读取不得隐式写入；mutation 在一个明确事务内提交，失败整体回滚。
- 应用关闭时显式 dispose engine。`/api/system/health` 保持 C001 的 `not_checked` 骨架，不因 C002 session 存在而连接数据库或外部服务。
- API/service 只捕获预期的不存在、校验和特定数据库完整性冲突；其他异常传播到现有最外层错误边界并记录 traceback。
- 不添加 repository、unit-of-work、缓存、审计、锁文件或第二套数据库抽象；service 直接编排当前用例。

### 3.2 固定模板数据迁移

C002 实施时在 C001 head 之后增加一条只包含数据的 Alembic revision。`upgrade()` 插入下列四行，`downgrade()` 删除这四个 key；不更新或吞掉已存在 key 的冲突，冲突必须使迁移失败并报告真实原因。

| key | 初始 content |
|---|---|
| `script2assets` | `[占位] script2assets 初始内容待需求方提供` |
| `script2shots` | `[占位] script2shots 初始内容待需求方提供` |
| `zimage` | `[占位] zimage 初始内容待需求方提供` |
| `minimaxh3` | `[占位] minimaxh3 初始内容待需求方提供` |

不得修改 C001 的表、列、约束、索引或初始 revision；不得在应用启动或 GET 请求中“补齐”缺失模板，不 seed 风格、项目、剧集或任何生成数据。

### 3.3 实体与字段

API 只公开下列 C001 已有字段；列表响应为 JSON array，单项响应为 JSON object，时间戳为带时区 ISO 8601 字符串，不返回 ORM 内部状态或未列字段。

| 实体 | 响应字段 | 可写字段 |
|---|---|---|
| Style | `id,name,prompt_fragment,created_at,updated_at` | create：`name,prompt_fragment`；patch：二者任一或全部 |
| Project | `id,name,style_id,created_at` | create：`name,style_id`；patch：二者任一或全部 |
| PromptTemplate | `id,key,content,updated_at` | patch：仅 `content`；key/id 不可改 |
| Episode | `id,project_id,seq,title,script_text,script_revision,assets_generated_script_revision,shots_generated_script_revision,created_at,updated_at` | create：`seq,title,script_text?`；patch：`seq,title,script_text` 任一或全部 |

输入约束：

- `style.name`、`project.name`、`episode.title` 去除首尾空白后必须非空，并保存去除后的值；不增加 PRD 未定义的长度上限。
- `prompt_fragment` 与模板 `content` 必须至少包含一个非空白字符；保留其原始换行和首尾空白，不擅自重排提示词。
- `episode.seq` 必须为正整数；同一项目内重复 seq 是冲突。
- 新剧集未传 `script_text` 时保存空字符串，`script_revision=1`，两个 generated revision 均为 `null`；空剧本合法。
- `script_text` 原样保存，以后端 Python 字符串长度校验 `len(script_text) <= SCRIPT_CHAR_LIMIT`；超限消息必须包含当前配置的数值。
- PATCH body 至少包含一个允许字段；未知字段、客户端写 id/时间戳/revision/generated revision、空 PATCH 或字段类型错误均为 422。
- `updated_at` 只在 Style、PromptTemplate 或 Episode 的持久值实际变化时更新；同值 PATCH 返回现有资源，不伪造更新时间。

## 4. REST API

所有路径均以 `/api` 为前缀。POST 创建成功返回 201，GET/PATCH 返回 200，DELETE 成功返回 204 且无响应体。

### 4.1 风格

| 方法与路径 | 行为 |
|---|---|
| `GET /styles` | 按 id 升序返回全部风格；无数据返回 `[]` |
| `POST /styles` | body `{name,prompt_fragment}`；创建并返回 Style |
| `GET /styles/{id}` | 返回 Style；不存在为 404 |
| `PATCH /styles/{id}` | 修改提供且实际变化的字段；不存在为 404 |
| `DELETE /styles/{id}` | 未被项目引用时删除；任一项目引用时 409，且不改任何数据 |

风格名按数据库现有 case-sensitive UNIQUE 约束判定；重复创建、改名冲突及并发唯一冲突均为 409。不得增加风格版本、历史快照或默认风格。

### 4.2 项目

| 方法与路径 | 行为 |
|---|---|
| `GET /projects` | 按 id 升序返回全部项目；无数据返回 `[]` |
| `POST /projects` | body `{name,style_id}`；style_id 必须指向现有风格 |
| `GET /projects/{id}` | 返回 Project；不存在为 404 |
| `PATCH /projects/{id}` | 修改 name 和/或 style_id；路径项目不存在为 404，body 中 style_id 无效为 422 |
| `DELETE /projects/{id}` | 同一事务先删除该项目的全部剧集，再删除项目，返回 204；风格不删除 |

C002 不查询或删除资产、分镜、片段、任务或文件。若数据库被 API 外部注入后续实体并导致外键阻止删除，返回 409、整体回滚；不得转成 500、部分删除或静默跳过。C003 及后续 change 再按各自 spec 扩展完整级联。

### 4.3 固定提示词模板

| 方法与路径 | 行为 |
|---|---|
| `GET /prompt-templates` | 按 `script2assets,script2shots,zimage,minimaxh3` 固定顺序返回四条模板 |
| `PATCH /prompt-templates/{key}` | body `{content}`；更新对应固定 key 并返回 PromptTemplate；未知 key 为 404 |

不提供单项 GET、POST、DELETE、改 key、复制或版本接口。模板内容本身按 R11 对设置页可见可编辑；C002 的其他响应不得包含 `built_prompt`、`input_snapshot` 或任何中间提示词字段。`DEBUG_PROMPTS` 在 C002 不扩展任何响应，因为拥有这些字段的详情接口尚未交付。

### 4.4 剧集与剧本

| 方法与路径 | 行为 |
|---|---|
| `GET /projects/{id}/episodes` | 项目存在时按 `seq,id` 升序返回剧集；项目不存在为 404 |
| `POST /projects/{id}/episodes` | body `{seq,title,script_text?}`；项目不存在为 404，创建后返回 Episode |
| `GET /episodes/{id}` | 返回 Episode；不存在为 404 |
| `PATCH /episodes/{id}` | 修改 seq/title/script_text 中提供的字段并返回 Episode；遵守 §5.1 修订语义 |
| `DELETE /episodes/{id}` | 删除当前 C002 剧集并返回 204；不存在为 404 |

同项目重复 seq 的创建、修改和并发唯一冲突均为 409。若 API 外部注入的后续实体阻止 episode 删除，返回 409 并整体回滚；C002 不提前删除其分镜、片段或文件。

## 5. 状态转换与编辑语义

### 5.1 剧本修订

一次成功 `PATCH /episodes/{id}` 按实际持久值执行：

| 输入结果 | `script_revision` | 其他行为 |
|---|---|---|
| `script_text` 未提供 | 不变 | 只更新实际变化的 seq/title 与 `updated_at` |
| `script_text` 提供但与当前值相同 | 不变 | 不因同值请求更新 `updated_at` |
| `script_text` 与当前值不同且合法 | 原子 `+1` 一次 | 新文本、revision、`updated_at` 在同一事务提交 |
| 任一字段失败校验或发生冲突 | 不变 | 整个 PATCH 回滚 |

剧本变化不得修改 `assets_generated_script_revision`、`shots_generated_script_revision`、assets、shots、clips、tasks 或任何媒体文件；不得自动生成、删除或标记 stale/changed。C002 不显示“基于旧剧本”角标，该 UI 属于 C005/C006。

### 5.2 风格与模板

- Style 或 PromptTemplate 的实际内容变化只更新自身字段与 `updated_at`，后续 GET 立即可见。
- 不修改现有 shots、clips、asset_images、clip_videos、generation_state、freshness 或 status，不删除文件。
- 不创建 revision、版本表、历史记录或 generation_runs，不计算/保存 input_hash，不回填 built_prompt/input_snapshot。
- “下次生成因 hash 失配重建 prompt”由拥有生成流水线的后续 change 实现；C002 只确保当前内容可被后续读取。

## 6. 错误协议与 409/422

所有 API 错误体精确保持：

```json
{"detail":{"code":"<machine_code>","message":"<human_message>"}}
```

- 404：路径所指项目、风格、模板 key 或剧集不存在；`code=not_found`。
- 409：重复风格名、同项目重复 episode seq、删除被引用风格、数据库级并发/外键冲突；`code=conflict`。
- 422：请求结构/类型/未知字段、空 PATCH、空白必填文本、非正 seq、无效 body `style_id`、剧本超过 `SCRIPT_CHAR_LIMIT` 等输入或业务校验；`code=validation_error`。
- 500：数据库不可达或其他未预期异常；`code=internal_error`，日志保留 traceback。不得把基础设施失败伪装成 409/422。

同一失败不得返回另一种错误体。后端和前端均不自动重试；前端直接展示 `detail.message`。只捕获具体预期异常，不用宽泛捕获、默认对象或空列表掩盖失败。

## 7. 前端行为

### 7.1 路由

| 路径 | C002 可见行为 |
|---|---|
| `/` | 项目列表；创建、编辑、删除项目；创建时必须选已有风格；没有风格时明确引导到设置页，不伪造默认风格 |
| `/projects/:projectId` | 项目详情与按 seq 排序的剧集列表；顶部提供按钮外观的“返回项目首页”入口；可创建、编辑、删除剧集；每个剧集提供文字明确的“进入集工作区”入口，不在本页提供“编辑剧本”动作 |
| `/projects/:projectId/episodes/:episodeId` | 规范化跳转到同一路径的 `/script` |
| `/projects/:projectId/episodes/:episodeId/script` | 显示项目/集上下文、按钮外观的返回当前项目入口与四选项卡导航；默认以只读方式展示 API 返回的最近一次持久化剧本及 revision，并提供页内“编辑剧本”按钮；编辑态展示 textarea、当前字符数、保存进行中/成功状态及后端校验消息 |
| `/projects/:projectId/episodes/:episodeId/assets` | 只显示资产选项卡真实未交付空态，无列表、按钮、mock 数据或上传行为 |
| `/projects/:projectId/episodes/:episodeId/shots` | 只显示分镜选项卡真实未交付空态，无列表、按钮或角标 |
| `/projects/:projectId/episodes/:episodeId/director` | 只显示导演台选项卡真实未交付空态，无轨道、片段或生成交互 |
| `/settings` | 风格列表/创建/编辑/删除与四模板内容编辑；不显示系统诊断 |
| `/tasks` | 保持 C001 空任务中心，不连接 WS |

嵌套路由中的 episode 若不属于 URL 中的 project，页面显示明确 not-found/关系错误并禁止 mutation，不把它当成该项目的剧集。

### 7.2 交互纪律

- 列表具备 loading、error、empty、ready 四种真实状态；失败保留 code/message，不用空态掩盖请求失败。
- 删除项目前需明确确认将同时删除其剧集；删除风格前需确认，409 后保留页面数据并展示原因。
- 创建/编辑成功后以 API 返回对象更新或重新读取列表；不得预先伪造成功。无自动重试。
- 集工作区四个选项卡顶部均提供文字明确、以按钮外观呈现的“返回项目”导航控件，目标精确为 `/projects/:projectId`；导航语义可使用 React Router `Link`，但视觉上不得呈现为普通正文链接，也不得用依赖浏览器历史的后退操作代替。
- 项目详情顶部提供文字明确、以按钮外观呈现的“返回项目首页”导航控件，目标精确为 `/`；不得依赖浏览器历史。每个剧集卡片提供文字明确的“进入集工作区”入口，目标精确为 `/projects/:projectId/episodes/:episodeId/script`；不在项目详情显示“编辑剧本”按钮或以该名称表达进入工作区。
- 剧本页默认处于查看态：以 API 返回的 `episode.script_text` 显示最近一次持久化剧本，保留原始换行和空白，并同时显示 `script_revision`；空字符串显示明确的“尚未保存剧本内容”空态，不伪造示例。查看态不显示 textarea 或保存按钮，只显示页内“编辑剧本”按钮。
- 点击剧本页“编辑剧本”后进入编辑态，textarea 必须以最近一次持久化 `script_text` 预填；提供“保存剧本”和“取消编辑”。取消不得发请求、不得改变 revision，并恢复查看态的持久化内容。提交期间保存按钮显示“保存中…”并禁用；成功后以 API 返回对象更新持久化展示、退出编辑态并留在当前 `/script` 路由，同时显示持续可见的 `role=status` 消息“剧本已保存，当前修订：{script_revision}”。失败时保持编辑态和原输入、清除旧成功消息并直显 `detail.message`；无自动保存、自动跳转、乐观伪成功或重试。
- 剧本文本原样提交。前端可显示字符数，但不得替代后端的动态 `SCRIPT_CHAR_LIMIT` 最终校验；收到超限 422 时原输入保留。
- DELETE 204 使用明确的无响应体客户端方法；不得让现有 JSON 解析器把合法空响应误报为协议错误。
- 前端不渲染生成资产/分镜按钮、旧剧本角标、资产数据、分镜数据、导演台、诊断或中间提示词。

## 8. 测试与追溯

C002 只允许新增 API 集成测试，且只对应以下准确追溯行：

1. `§3.3 编辑剧本：分镜、片段、文件均不动，只出现集级旧剧本角标`
   - C002 覆盖 API 侧：剧本实际变化仅增加 revision，既有下游行/状态/文件不动；同值、非剧本字段和超限失败不误增 revision。
   - “旧剧本角标”UI 留给 C005/C006，回填时必须注明 C002 只覆盖 API 语义。
2. `§3.3 编辑风格或模板：分镜与片段不动、文件不删，下次生成因 hash 失配重建 prompt`
   - C002 覆盖 API 侧：编辑立即可读且既有下游行/状态/文件不动。
   - hash 失配与任务系统 mock 留给 C007/C009，回填不得声称整行已闭环。
3. `R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot`
   - C002 只覆盖模板在设置 API 可见可编辑，以及本 change 的默认响应不增加中间提示词字段。
   - `DEBUG_PROMPTS=true` 的产物详情分支留给 C007/C009。

测试使用真实 PostgreSQL，通过 FastAPI 边界执行，只在 vLLM/Comfy/媒体不可控边界存在时才可 mock；C002 没有这些调用，不得引入任务系统 mock。CRUD 完整性、UI 和迁移采用命令/人工验收，不新增无追溯行的测试。实施后把真实 pytest node ID 回填对应行，并注明部分覆盖边界。

## 9. 验收标准

1. 在专用空 PostgreSQL 上从 C001 head 执行 `alembic upgrade head` 成功；四 key/内容精确，`alembic current` 为新 head，`alembic check` 无操作，schema 无漂移。
2. `/docs` 展示 §4 的全部路由；项目、风格、模板、剧集 API 的状态码、字段、顺序及 404/409/422 与本 spec 一致。
3. 项目删除在同一事务删除其 C002 剧集；风格被引用时删除返回 409；任何失败无部分写入。
4. 剧本成功变化恰好 revision+1，标题/seq 或同值 PATCH 不增加；超限返回 422；下游数据库行、状态和测试哨兵文件不变。
5. 风格/模板修改立即可读取，既有下游行、状态和测试哨兵文件不变；无版本、hash、任务或生成副作用。
6. 授权 API 集成用例及完整 `python -m pytest -q tests` 成功，追溯表回填真实 node ID 且标注未覆盖的后续部分。
7. `npm run build` 成功；浏览器可完成“建风格→建项目→由‘进入集工作区’进入剧本页→看到最近一次持久化剧本及 revision→点击页内‘编辑剧本’→取消后内容/revision 不变→再次编辑并保存→回到查看态且看到 API revision 成功反馈→用按钮返回当前项目→用按钮返回项目首页→编辑模板→删除剧集/项目”；四个工作区选项卡均显示按钮外观的返回项目入口，错误直接可见且无自动重试。
8. 四选项卡存在且只有剧本可操作；资产/分镜/导演台为无假数据的未交付空态，任务中心保持空实现，设置页无诊断。
9. 无 vLLM/Comfy/workflow/WS/media/trash 调用；无范围围栏能力；`git diff --check` 成功，diff 只包含 C002 spec/tasks 授权的实现、测试和追溯回填。
