# C002 M1 项目、设置与剧集 Tasks

按顺序执行。Luna 每次只领取一个 checkbox；每个 task 只能完成本项明列改动，完成验收、运行完整 pytest、更新本文件 checkbox 并单独 commit。没有真实证据时不得勾选。所有数据库命令必须通过环境变量指向专用 PostgreSQL 验收库，不得使用 SQLite、mock 或 `.env.example` 示例冒充。

## T1 运行时 async 数据库 session

- [x] 增加 SQLAlchemy async engine、session factory、FastAPI session dependency 与应用关闭 dispose，使后续路由具备单请求事务边界。
  - **R：** 无；对应 PRD §5 通用、§10 技术栈、§11 M1。
  - **范围：** 只新增运行时数据库连接边界并接入 app lifespan；不加业务路由、模型/迁移、startup health probe、重试、SQLite fallback、repository 或测试。
  - **验收方式：**
    1. 在 `backend/` 运行一个使用 `app.db.session` 导出的 engine 执行 `SELECT 1` 的 PowerShell here-string Python 命令，真实输出必须为 `1`；连接失败必须原样失败。
    2. 运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，请求 `/api/system/health`，确认仍返回 C001 的 `not_checked` 精确结构且启动未主动查询数据库。
    3. 运行 `python -m pytest -q tests`，完整 pytest 必须通过；检查日志不含 DSN 密码。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T2 四个占位模板的数据迁移

- [x] 在 C001 head 后新增一条 Alembic 数据 revision，精确插入 spec §3.2 的四个 key/content，并提供对称删除；不得修改 schema 或运行时补数据。
  - **R：** R11；对应 PRD §3.5、§4 `prompt_templates`、§5 模板接口、§11 M1、§12.2。
  - **范围：** 只新增一条数据迁移；不 seed 风格/项目/剧集，不上正式模板，不用 upsert/fallback 吞掉冲突。
  - **验收方式：**
    1. 在指向专用空库的 `backend/` 运行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`，分别保存真实成功输出。
    2. 使用 SQLAlchemy/asyncpg 只读查询 `SELECT key, content FROM prompt_templates ORDER BY id`，核对恰好四行且内容逐字等于 spec §3.2；再核对 13 张业务表及 C001 schema 未变化。
    3. 运行 `python -m pytest -q tests`，完整 pytest 必须通过。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot
  - **覆盖说明：** 本 task 只迁移固定数据，R11 的 C002 API 行为由 T6 测试。

## T3 风格 CRUD API 与引用删除保护

- [x] 实现 Style 输入输出 schema、service 和 `GET/POST /api/styles`、`GET/PATCH/DELETE /api/styles/{id}`，包含实际变化更新时间、名称唯一冲突与被项目引用时 409。
  - **R：** 无；对应 PRD §2.1(2)、§3.2“风格/模板编辑语义”、§3.3“编辑风格/模板”、§5 项目与设置、§11 M1。
  - **范围：** 只做风格 API；不做项目 API、风格版本化、默认风格、hash、生成副作用或自动测试。只捕获预期 not-found/完整性冲突。
  - **验收方式：**
    1. 启动后端，用 `Invoke-RestMethod` 依次 POST、GET list、GET item、PATCH、DELETE，核对 201/200/204、字段和持久值；空白输入为 422，同名创建/改名为 409。
    2. 在专用库直接插入一个引用该 style 的最小 project，再用 `Invoke-WebRequest -SkipHttpErrorCheck` 请求 DELETE，核对 409 与精确错误体且两行均未改变；清理验收数据。
    3. 运行 `python -m pytest -q tests`，完整 pytest 必须通过；运行 `git diff --check`。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** §3.3 编辑风格或模板：分镜与片段不动、文件不删，下次生成因 hash 失配重建 prompt
  - **覆盖说明：** 本 task 不新增用例，C002 可验证部分由 T6 的授权用例覆盖。

## T4 项目 CRUD API 与当前级联

- [x] 实现 Project 输入输出 schema、service 和 `GET/POST /api/projects`、`GET/PATCH/DELETE /api/projects/{id}`，校验 style_id，并在一个事务内级联删除当前项目的 C002 剧集。
  - **R：** 无；对应 PRD §2.1(1)、§4 projects、§5 项目与设置、§11 通用级联原则及 M1。
  - **范围：** 只做项目 API 与 project→episodes 当前级联；不删除 style，不实现资产/分镜/片段/任务/media/trash 级联，不增加分页、搜索或自动测试。
  - **验收方式：**
    1. 先通过风格 API 创建 style，再用 `Invoke-RestMethod` 完成项目 POST/list/item/PATCH，核对字段和状态码；不存在的 body style_id、空白 name、空 PATCH 为 422，未知 path id 为 404。
    2. 在专用库给项目插入两个最小 episode 后请求 DELETE；只读查询确认 project 与两 episode 同时消失、style 保留。另造一个会被后续外键阻止的专用验收状态，确认返回 409 且事务无部分删除，随后清理。
    3. 运行 `python -m pytest -q tests`，完整 pytest 必须通过；运行 `git diff --check`。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T5 剧集 CRUD、剧本修订与授权测试

- [x] 实现 Episode 输入输出 schema、service 和剧集全部路由，落实 seq 冲突、字数上限、同值 PATCH、实际剧本变化原子 revision+1 及下游完全不动；添加唯一对应“编辑剧本”追溯行的 API 集成测试并回填 node ID。
  - **R：** 无；对应 PRD §2.1(3-4)、§3.2“剧本编辑语义”、§3.3“编辑剧本”、§4 episodes、§5 剧集、§10 `SCRIPT_CHAR_LIMIT`、§11 M1。
  - **范围：** 只做剧集/剧本 API 与该追溯场景；不加旧剧本角标、生成按钮、资产/分镜逻辑、其他 CRUD 测试或任务系统 mock。
  - **验收方式：**
    1. 用 `Invoke-RestMethod` 完成 episode POST/list/item/PATCH/DELETE，核对排序、201/200/204、初始 revision=1 和 generated revisions=null；重复 seq 为 409，超限/空 PATCH/非法 seq 为 422。
    2. 运行计划 API 用例，证明实际 script 变化每次只 +1，标题/seq 和同值 script 不增加，超限请求不写入；预置的 shot/clip/产物行、状态及临时哨兵文件均不变。
    3. 在 `backend/` 运行 `python -m pytest -q tests`，保存完整输出；把真实 node ID 回填追溯表准确行并注明 C002 只覆盖 API 语义、角标待 C005/C006。
    4. 运行 `git diff --check`，确认没有修改 C001 smoke 的意图或扩大测试场景。
  - **计划测试层级：** API 集成
  - **追溯行：** §3.3 编辑剧本：分镜、片段、文件均不动，只出现集级旧剧本角标

## T6 固定模板 API、R11 与编辑不追溯测试

- [x] 实现 `GET /api/prompt-templates` 与 `PATCH /api/prompt-templates/{key}`，固定顺序/固定 key/实际变化更新时间；添加一个同时覆盖模板可见可编辑及风格/模板不追溯的 API 集成测试，并准确回填两行追溯。
  - **R：** R11；对应 PRD §2.1(2)、§3.2“风格/模板编辑语义”、§3.3“编辑风格/模板”、§3.5、§4、§5、§11 M1、§12.2。
  - **范围：** 不提供模板单项 GET/POST/DELETE/改 key，不实现 DEBUG_PROMPTS 产物详情、hash、prompt 渲染、生成、版本化或任务系统 mock。
  - **验收方式：**
    1. 用 `Invoke-RestMethod` 请求模板列表，核对四 key、固定顺序和占位内容；PATCH 后立即 GET 可见，同值 PATCH 不改 updated_at，未知 key 404，空白 content/未知字段为 422。
    2. 运行授权 API 用例：先建立带下游行和临时哨兵文件的场景，再分别 PATCH style 与 template，核对自身内容变化、shots/clips/产物状态/文件不变；核对 C002 默认响应无 built_prompt/input_snapshot。
    3. 在 `backend/` 运行 `python -m pytest -q tests`，保存完整输出；把真实 node ID 回填两条准确追溯行，并分别注明 hash/task mock 与 DEBUG_PROMPTS 详情分支待 C007/C009。
    4. 运行 `git diff --check`，人工确认未加入风格/模板 revision/history/generation_runs。
  - **计划测试层级：** API 集成
  - **追溯行：** R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot；§3.3 编辑风格或模板：分镜与片段不动、文件不删，下次生成因 hash 失配重建 prompt

## T7 C002 前端 API 客户端与真实 ID 工作区路由

- [x] 增加 Style/Project/PromptTemplate/Episode 类型化客户端、JSON mutation 与 DELETE 204 处理，并建立 spec §7.1 的项目/剧集/四选项卡路由壳。
  - **R：** R11；对应 PRD §2.1(1-4)、§5 项目与剧集、§9、§11 M1；本 task 仅构建模板客户端。
  - **范围：** 只做传输层、路由和无业务数据的工作区壳；不实现 CRUD 页面、前端业务裁决、自动重试、WS、生成按钮或资产/分镜/导演台能力。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`，TypeScript strict 与 Vite 构建必须成功。
    2. 人工审查每个 client 使用相对 `/api`、JSON 请求头和统一 ApiError；DELETE 204 不调用 JSON 解析，非 2xx 仍保留 status/code/message，任何方法均无重试。
    3. 运行 dev server，直接访问/刷新项目、项目剧集及四个 tab URL，确认路由不白屏、ID 参数真实传递、三个后续 tab 只有未交付空态。
    4. 在 `backend/` 运行 `python -m pytest -q tests`；运行 `git diff --check`。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot
  - **覆盖说明：** 本 task 不新增用例，C002 可验证部分由 T6 的授权用例覆盖。

## T8 项目、剧集与剧本页面

- [ ] 把首页升级为项目 CRUD，增加项目剧集 CRUD 页面与可保存剧本页，完整处理 loading/error/empty/ready、删除确认、关系不匹配和后端校验消息。
  - **R：** 无；对应 PRD §2.1(1,3-4)、§3.2“剧本编辑语义”、§5、§9、§11 M1。
  - **范围：** 只实现项目/剧集/剧本 UI；不展示旧剧本角标或生成按钮，不实现资产/分镜/导演台业务，不新增前端自动测试。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`；在 `backend/` 运行 `python -m pytest -q tests`，两者必须成功。
    2. 同时启动前后端，在浏览器人工完成“无风格提示→建风格→建项目→编辑项目→建两集→编辑集信息→保存并再次修改剧本→删集→删项目”；刷新后数据与 API 一致。
    3. 人工制造 404/409/422 和后端不可达，确认页面保留输入、直显 `detail.message`、不伪装空态、不自动重试；确认嵌套 project/episode 不匹配时禁止 mutation。
    4. 确认项目删除文案只说明当前项目及剧集，不声称 C002 已实现资产/media/trash 级联；运行 `git diff --check`。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** §3.3 编辑剧本：分镜、片段、文件均不动，只出现集级旧剧本角标
  - **覆盖说明：** 本 task 不新增用例，API 语义由 T5 的授权用例覆盖。

## T9 设置页与 C002 全链路收口

- [ ] 把设置页升级为风格和四模板管理界面，完成 C002 全链路、范围围栏、迁移、错误语义、追溯和前端构建的最终验收。
  - **R：** R11；对应 PRD §2.1(2)、§3.2、§3.3“编辑风格/模板”、§3.5、§5、§9、§11 M1、§12.2。
  - **范围：** 设置页只含风格/模板；不含系统诊断、正式模板伪证据、hash/提示词详情、生成、任务、媒体或后续业务。除勾选本 task 和必要追溯回填外不增加新测试。
  - **验收方式：**
    1. 在 `backend/` 运行 `python -m alembic current`、`python -m alembic check`、`python -m pytest -q tests`；在 `frontend/` 运行 `npm run build`，保存全部真实输出。
    2. 浏览器完成设置页风格创建/编辑/删除、引用风格 409、四模板查看/编辑和刷新持久化；错误直接展示且无自动重试，页面没有诊断面板。
    3. 从空业务数据完成“建风格→建项目→建集→录入/修改剧本→编辑模板→删除剧集/项目”的真实链路；核对后端数据库状态与 spec 一致。
    4. 逐项审查追溯表只新增 T5/T6 真实 node ID，且 R11、风格/模板、剧本行明确标注后续未覆盖部分；不得写其他测试。
    5. 运行 `git diff --check` 并审查完整 diff：无资产/media/trash/任务/WS/生成/诊断实现，无候选分镜版本、分镜增删拆并排序、资产别名合并、风格/模板版本化、generation_runs、continuity、context loop、fl2v 或音频能力。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot；§3.3 编辑风格或模板：分镜与片段不动、文件不删，下次生成因 hash 失配重建 prompt
  - **覆盖说明：** 本 task 只运行 T5/T6 的 API 集成测试与完整 pytest，不增加新用例。
