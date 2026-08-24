# C001 M0 基础设施 Spec

## 1. 规范边界

本 spec 仅授权 ROADMAP C001。PRD §4、§5 通用与系统接口、§9、§10、§11 M0 和 §12 为规范来源；PRD §0 范围围栏始终优先。C001 没有直接对应的 R 规则，不得借全量建表实现任何后续业务行为。

## 2. 可观察交付物

C001 完成后必须同时满足：

1. 后端依赖可安装，FastAPI 应用可用单进程命令启动。
2. `GET /docs` 可打开 Swagger UI，`GET /openapi.json` 可读取 OpenAPI 文档。
3. `GET /api/system/health` 返回本 spec 定义的骨架 JSON，且请求期间不访问 PostgreSQL、vLLM、ComfyUI 或工作流文件。
4. 空 PostgreSQL 数据库可由 Alembic 一次升级到包含 PRD §4 全部 schema 的 head，metadata 与迁移无差异。
5. 前端可安装并生产构建；`/`、`/settings`、`/tasks` 三条空页面共享同一布局且可互相导航。
6. 前端通过真实 HTTP 请求展示后端已连接，并把三个未执行诊断项显示为“未检查”；连接失败时显示明确错误，不重试、不伪装成功。
7. 唯一授权的 C001 API 集成 smoke 测试通过并回填追溯表，完整 pytest 返回成功。

## 3. 后端工程与配置

### 3.1 工程约定

- `backend/pyproject.toml` 是后端依赖与 pytest 配置的唯一来源，不再维护重复的 requirements 文件。
- 运行时依赖必须包含 FastAPI、SQLAlchemy 2、Alembic、asyncpg、httpx、Pydantic Settings 与 Uvicorn；测试依赖只加入 pytest 及运行授权 smoke 所必需的组件。
- `backend/app/main.py` 导出 ASGI `app`；模块按 `openspec/project.md` 的 `api/core/db/models/schemas` 边界组织，不创建空目录占位。
- 仓库 ignore 规则必须排除 `.env`、虚拟环境、Python/pytest 缓存、`node_modules`、前端构建产物和本地 `DATA_DIR`，同时继续跟踪 `.env.example`；生成物不得进入 commit。
- 应用按单进程运行；C001 不获取 advisory lock，也不启动 worker、scheduler 或后台清理器。
- 日志写到标准输出。意外异常必须保留完整 traceback；不得重试、吞异常或转换为成功响应。

### 3.2 配置契约

配置只来自环境变量和可选本地 `.env`；`.env.example` 保持以下 13 项，不增加未被 PRD 授权的业务配置：

| 配置 | 示例/默认值 | C001 行为 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/ai_drama_studio` | SQLAlchemy/Alembic 唯一 DSN；示例不构成验收证据 |
| `DATA_DIR` | `./data` | 仅完成类型化加载，不创建媒体目录 |
| `VLLM_BASE_URL` | `http://localhost:8001` | 仅加载，不连接 |
| `VLLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | 仅加载，不校验远端模型 |
| `COMFY_BASE_URL` | `http://localhost:8188` | 仅加载，不连接 |
| `SCRIPT_CHAR_LIMIT` | `2000` | 正整数 |
| `CLIP_MAX_SECONDS` | `15` | 正整数，且不得小于 `CLIP_MIN_SECONDS` |
| `CLIP_MIN_SECONDS` | `5` | 正整数，且不得大于 `CLIP_MAX_SECONDS` |
| `SLOT_HARD_LIMIT` | `9` | 正整数 |
| `SLOT_SOFT_LIMIT` | `4` | 正整数，且不得大于 hard limit |
| `UPLOAD_MAX_MB` | `20` | 正整数 |
| `TRASH_RETENTION_HOURS` | `24` | 正整数 |
| `DEBUG_PROMPTS` | `false` | 严格布尔值 |

配置解析或交叉校验失败时应用必须启动失败并输出具体配置错误；不得替换成静默默认。日志不得打印 DSN 密码或完整环境变量。

### 3.3 HTTP 边界

- REST 前缀固定为 `/api`；FastAPI 文档保留在根路径 `/docs`，OpenAPI JSON 保留在 `/openapi.json`。
- CORS 只允许 HTTP loopback origins：`localhost` 与 `127.0.0.1` 的本地开发端口；不得使用允许公网 origin 的通配符。
- 不实现鉴权或 HTTPS 终止。
- 所有 API 错误使用 `{"detail":{"code":"<machine_code>","message":"<human_message>"}}`；不得增加与该结构并列的第二种错误体。
- 通用 code：不存在为 `not_found`，方法不允许为 `method_not_allowed`，请求校验失败为 `validation_error`，前置/冲突为 `conflict`，未预期服务端错误为 `internal_error`。
- 409 只用于前置条件或冲突；422 只用于输入/业务校验。C001 没有主动产生 409 的业务端点，但必须保留这一全局语义。
- 未预期异常只允许在最外层框架错误边界统一记录 traceback 并返回结构化 500；路由和内部模块不得使用宽泛捕获、fallback 或重试。

### 3.4 `/api/system/health` 骨架

成功响应固定为 HTTP 200：

```json
{
  "vllm": { "status": "not_checked" },
  "comfy": { "status": "not_checked" },
  "workflow_bindings": {
    "status": "not_checked",
    "hashes": {}
  }
}
```

C001 只允许 `not_checked`，不得根据配置项存在就返回 healthy，不得请求外部 URL、读取尚未提供的 workflow 文件或计算假 hash。C007 可以在保持字段职责清晰的前提下扩展真实诊断状态。

## 4. 数据库与 Alembic

### 4.1 通用约定

- 只支持 PostgreSQL，应用连接使用 SQLAlchemy 2 async engine + asyncpg；不得提供 SQLite fallback。
- 主键使用自增 `INTEGER`；时间字段使用带时区时间戳并以 UTC 写入；JSON 字段使用 `JSONB`；PRD 中的 FLOAT 使用双精度浮点。
- PRD 明确标为 `NULL` 的字段可空；其余业务字段非空。`created_at` 使用数据库默认当前时间；带 `updated_at` 的实体同时设置初始当前时间，后续更新语义由拥有该行为的 change 实现。
- 枚举集合必须由数据库约束，不得只在 Python 层校验；约束和索引使用稳定、可读名称。
- 只实现 PRD 明写的 `ON DELETE` 行为；其余删除编排留给对应业务 change，不在 C001 猜测级联。
- 不创建触发器、存储过程、seed 数据、审计表、迁移锁、内容签名或 §4 之外的表/列。

### 4.2 表、字段与约束

以下 13 张表必须全部进入同一 SQLAlchemy metadata；列名与集合不得偏离 PRD §4：

| 表 | 必须实现的字段与约束 |
|---|---|
| `projects` | `id`, `name`, `style_id` FK→styles, `created_at` |
| `styles` | `id`, `name` UNIQUE, `prompt_fragment`, `created_at`, `updated_at` |
| `prompt_templates` | `id`, `key` UNIQUE 且限 `script2assets/script2shots/zimage/minimaxh3`, `content`, `updated_at` |
| `episodes` | `id`, `project_id` FK, `seq`, `title`, `script_text`, `script_revision` default 1, `assets_generated_script_revision`/`shots_generated_script_revision` 可空, `created_at`, `updated_at`, UNIQUE(`project_id`,`seq`) |
| `assets` | `id`, `project_id` FK, `type` 限 `character/scene/prop`, `name`, `description`, `source` 限 `generated/manual`, `revision` default 1, `image_prompt_cache`/`image_prompt_hash` 可空, `created_at`, `updated_at` |
| `asset_images` | `id`, `asset_id` FK, `file_path`, `sha256`, `seed` 可空, `source` 限 `generated/uploaded`, `is_current` default false, `built_prompt`/`input_hash`/`input_snapshot`/`user_note` 可空, `created_at`；部分唯一索引保证每个 asset 至多一个 current |
| `shots` | `id`, `episode_id` FK, `order_index`, `duration_est`, `shot_type`, `camera`, `description`, `dialogue`, `status` 限 `normal/changed`, `revision` default 1, `created_at`, `updated_at`；UNIQUE(`episode_id`,`order_index`) |
| `shot_assets` | `shot_id` FK, `asset_id` FK `ON DELETE CASCADE`, 复合主键；不增加 surrogate id |
| `clips` | `id`, `episode_id` FK, `generation_mode` 限 `ref2v/fl2v/context_loop` 且 default `ref2v`, `user_note` 可空, `requested_duration`, `prompt_cache`/`prompt_input_hash` 可空, `generation_state` 限五态且 default `empty`, `freshness` 限 `fresh/stale` 且 default `fresh`, `revision` default 1, `created_at`, `updated_at`；**无 `order_index`** |
| `clip_shots` | `clip_id` FK `ON DELETE CASCADE`, `shot_id` FK, `position`, 复合主键；UNIQUE(`shot_id`) 与 UNIQUE(`clip_id`,`position`)；**无 shot_ids 数组列** |
| `clip_ref_slots` | `id`, `clip_id` FK `ON DELETE CASCADE`, `slot_no` 1..9, `asset_id` 可空 FK `ON DELETE SET NULL`, `asset_name_snapshot`, `asset_type_snapshot`, `override_image_path`/`override_sha256` 可空, `enabled` default true；UNIQUE(`clip_id`,`slot_no`) |
| `clip_videos` | `id`, `clip_id` FK, `file_path`, `sha256`, `seed`, `requested_duration`, `actual_duration` 可空, `is_current` default false, `built_prompt`/`input_hash`/`input_snapshot` 可空, `created_at`；部分唯一索引保证每个 clip 至多一个 current |
| `tasks` | `id`, `type` 限 `gen_assets/gen_shots/gen_asset_image/gen_clip_video`, `target_id`, `request_id` 可空, `payload` JSONB, `status` 限 `queued/running/done/failed/canceled`, `progress` 约束 0..1, `error_msg`/`heartbeat_at`/`cancel_requested_at`/`started_at`/`finished_at` 可空, `created_at`；同目标 active 唯一仅覆盖 `gen_assets/gen_shots`，active `request_id` 部分唯一 |

必须特别核对：

- `clips.generation_mode` 是唯一范围外值预留，C001 之后的 v1 代码不得读写 `fl2v/context_loop`。
- 不存在 `clips.order_index`、`shot_ids` 数组、`generation_runs`、continuity 或音频字段/表。
- `is_current` 使用 PostgreSQL 部分唯一索引，不以普通 UNIQUE 阻止多个 false。
- task 同目标 active 索引的 predicate 同时限制 active 状态和 `gen_assets/gen_shots` 类型；`request_id` 索引排除 NULL 并只限制 active 状态。

### 4.3 初始迁移

- Alembic 只有一个语义明确的初始 revision，从空数据库创建上述 schema；不得把表拆成带 `v2/new/final` 命名的迁移。
- `upgrade()` 按外键依赖顺序创建；`downgrade()` 仅做对称逆序删除，不含数据迁移、兼容逻辑或备份机制。
- `alembic upgrade head`、`alembic current` 和 `alembic check` 必须在需求方提供的专用 PostgreSQL 上成功；仅生成 SQL、使用 SQLite 或 mock 不算验收。

## 5. 前端工程与交互

### 5.1 工程和组件边界

- 使用 React 18、Vite、TypeScript strict mode 和 React Router；使用 npm 并提交 `package-lock.json`，不并存第二种包管理器锁文件。
- `src/api/` 只处理传输、错误解析与 URL；`src/components/` 放跨页面展示组件；`src/pages/` 放路由页面；不在前端实现业务裁决。
- 最小共享组件为 AppShell、主导航、PageTitle/EmptyState 和 BackendStatus；不建立完整设计系统或后续业务组件占位。

### 5.2 路由与空页面

| 路径 | 页面 | C001 可见内容 |
|---|---|---|
| `/` | 项目首页空壳 | 页面标题与“暂无项目”空态，不提供 CRUD 按钮 |
| `/settings` | 设置空壳 | 页面标题与“暂无可用设置”空态，不展示伪诊断数据 |
| `/tasks` | 任务中心空实现 | 页面标题与“暂无任务”空态，无过滤、取消、历史或 WS 连接 |

项目/剧集工作区路由需要真实实体 ID，留给 C002；C001 不创建临时 `/workspace` 或假 ID 路由。

### 5.3 API 与 WS 客户端

- HTTP 客户端以相对 `/api` 为 base，发送/解析 JSON；开发期由 Vite proxy 转发到本地后端，生产假设同源部署。
- 非 2xx 响应必须解析统一错误体并抛出包含 HTTP status、code、message 的类型化错误；解析失败必须明确报协议错误，不回退到伪成功或默认数据。
- 客户端不自动重试。页面可以展示错误，但不得吞掉 code/message。
- WS 基础设施仅提供从当前页面 origin 构造 `ws/wss` URL 和显式 open/close 的薄封装；C001 不连接 `/ws/tasks`，不实现自动重连、消息协议或 mock 事件。

### 5.4 前后端互通状态

AppShell 首次加载请求一次 `/api/system/health`，状态只允许：

- `loading` → 请求进行中；
- `connected` → HTTP 200 且响应符合 schema，显示“后端已连接”，三个组件均显示“未检查”；
- `error` → 网络、非 2xx 或协议错误，显示 `detail.message` 或明确的连接/协议错误。

状态转换后不自动重试；用户刷新页面才发起新请求。C001 没有任务状态机，任务中心始终是真实空态。

## 6. 测试与追溯

唯一允许新增的自动测试对应追溯行：

> C001 基础设施 smoke：FastAPI 应用可启动，`/docs` 可访问，`/api/system/health` 返回明确的未检查骨架且不调用外部服务，通用 API 错误体符合约定

层级为“API 集成”。测试必须覆盖应用创建、`/docs`、health 精确 schema、未知 API 的结构化错误，并证明 health 路由不依赖外部服务；实现后回填真实 pytest node ID。数据库 schema、前端构建和人工导航使用命令验收，不新增追溯表之外的测试。

## 7. 验收标准

1. 后端从干净环境安装成功；授权 smoke 与完整 pytest 均为成功退出。
2. Uvicorn 启动后 `/docs` 与 `/openapi.json` 为 200，health 返回 §3.4 的精确 JSON，未知 API 返回统一错误体。
3. 无 vLLM/Comfy/workflow 请求、无 retry/fallback；日志不泄露 DSN 密码。
4. 真实 PostgreSQL 从空库 `upgrade head` 成功，`current` 位于 head，`alembic check` 无新操作。
5. 13 张表、枚举/check、外键动作、唯一约束和四类部分唯一索引与 §4 一致，且围栏禁止表/列不存在。
6. `npm install` 与 `npm run build` 成功；三条路由可导航，任务中心无假数据或 WS 行为。
7. 前端连接运行中的后端时显示 connected/not_checked；后端不可达时进入 error 且不自动重试。
8. `git diff --check` 无错误，diff 只包含 C001 spec/tasks 授权的基础设施与追溯回填。
9. PostgreSQL DSN 未提供或任一真实命令未执行时，必须报告未验收，不得勾选 C001 完成。
