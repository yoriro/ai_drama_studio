# C001 M0 基础设施 Tasks

按顺序执行。Luna 每次只领取一个 checkbox；每个 task 完成其验收、运行完整 pytest、更新本文件并单独 commit。没有真实证据时不得勾选。

## T1 后端可运行骨架、health 与首个 smoke

- [x] 创建仓库 ignore 规则、后端依赖声明、FastAPI 应用、类型化配置、localhost CORS、统一错误边界和 `/api/system/health`；同时实现唯一授权的 API 集成 smoke，并回填追溯表用例 ID。
  - **R：** 无；对应 PRD §5 通用与 `/system/health`、§10、§11 M0。
  - **范围：** 只建立可运行 HTTP 基线；不创建 ORM 模型、迁移、业务路由、外部客户端调用、后台任务或 WS endpoint。
  - **验收方式：**
    1. 在仓库根目录运行 `python -m pip install -e "./backend[dev]"`，必须成功。
    2. 运行 `python -m pytest -q backend/tests`，必须收集并通过 smoke；记录完整输出。
    3. 运行 `python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`；在另一终端运行 `Invoke-WebRequest http://127.0.0.1:8000/docs` 与 `Invoke-RestMethod http://127.0.0.1:8000/api/system/health | ConvertTo-Json -Depth 4`，核对 200 与 spec 精确响应。
    4. 请求不存在的 `/api/not-found`，核对结构化 404；确认启动/请求日志没有 DSN 密码，也没有 vLLM/Comfy 网络调用。
  - **计划测试层级：** API 集成。
  - **追溯行：** C001 基础设施 smoke：FastAPI 应用可启动，`/docs` 可访问，`/api/system/health` 返回明确的未检查骨架且不调用外部服务，通用 API 错误体符合约定。

## T2 SQLAlchemy 2 全量 metadata

- [x] 按 spec §4 声明全部 13 张表、字段、约束、外键动作和部分唯一索引，并建立单一 metadata 导入入口。
  - **R：** 无；对应 PRD §4、§0 范围围栏、§11 M0。
  - **范围：** 只写 ORM/schema 声明；不创建迁移、不连接数据库、不添加 repository/service、seed 或删除逻辑。
  - **验收方式：**
    1. 在 `backend/` 工作目录运行 `python -c "from app.db.base import Base; import app.models; print(sorted(Base.metadata.tables))"`；输出必须恰好包含 spec 的 13 张表。
    2. 人工逐项核对 `clips` 无 `order_index`、无 `shot_ids`、无 `generation_runs`/continuity/音频字段，且 generation_mode 仅有 PRD 三个值。
    3. 核对四类部分唯一索引和显式 `ON DELETE` 行为；运行 `python -m pytest -q tests`，已有 smoke 必须继续通过。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** 不适用。

## T3 Alembic 初始迁移与真实 PostgreSQL 验证

- [x] 建立 Alembic 配置和单一初始 revision，使空 PostgreSQL 升级到与 metadata 一致的 head。
  - **R：** 无；对应 PRD §4、§10、§11 M0、§12.4。
  - **前置门槛：** 需求方提供可连接的专用 PostgreSQL DSN 与建表权限；`.env.example` 示例、SQLite、mock 或仅离线 SQL 均不满足。
  - **范围：** migration 只创建/逆序删除 spec §4 schema；不 seed 数据、不加入业务级联代码、不创建额外基础设施表。
  - **验收方式：**
    1. 在 `backend/` 工作目录、加载真实 `DATABASE_URL` 后运行 `python -m alembic upgrade head`，必须成功。
    2. 运行 `python -m alembic current`，输出必须标记当前 revision 为 head。
    3. 运行 `python -m alembic check`，实际输出必须为无待生成操作；人工核对数据库中的 13 张表、约束与索引。
    4. 运行 `python -m pytest -q tests`，已有 smoke 必须继续通过；保存全部命令输出作为验收证据。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** 不适用。

## T4 React/Vite/TS 路由与组件壳

- [x] 建立 React 18 + Vite + TypeScript strict 工程、AppShell、共享空态组件，以及 `/`、`/settings`、`/tasks` 三条真实空路由。
  - **R：** 无；对应 PRD §9、§10、§11 M0。
  - **范围：** 只做布局、导航和真实空态；不创建 CRUD 表单、项目工作区、诊断面板、业务状态或 mock 数据。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm install`，确认只生成 npm 的 `package-lock.json`。
    2. 运行 `npm run build`，TypeScript 检查和 Vite 生产构建必须成功。
    3. 运行 `npm run dev -- --host 127.0.0.1`，浏览三条 URL，确认共享导航可达、刷新不白屏、文案与 spec 一致。
    4. 在 `backend/` 运行 `python -m pytest -q tests`，完整 pytest 必须继续通过。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** 不适用。

## T5 API/WS 客户端、前后端互通与 C001 收口

- [ ] 建立相对路径 JSON API 客户端、统一错误解析、WS URL/生命周期薄封装和 Vite proxy；用 health 请求驱动 AppShell 的 loading/connected/error 状态并完成全 change 验收。
  - **R：** 无；对应 PRD §5 通用与系统接口、§9、§10、§11 M0、§12.4。
  - **前置门槛：** T1-T4 完成，且 T3 已在真实 PostgreSQL 上取得成功证据。
  - **范围：** 不打开任务 WS、不自动重连/重试、不实现任务协议、诊断探测或任何业务 API client。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`；在 `backend/` 运行 `python -m pytest -q tests`，两者必须成功。
    2. 同时运行 backend 与 frontend，打开三条前端路由，确认 health 为 connected 且 vLLM/Comfy/workflow 均显示“未检查”。
    3. 停止 backend 后刷新前端，确认进入 error、显示明确消息且没有自动重试；重新启动只通过手动刷新恢复。
    4. 运行 `git diff --check`；用 `rg -n -i "generation_runs|continuity|context_loop|fl2v|audio|音频|候选分镜|资产别名|版本化|retry|重试" backend frontend` 审核每个命中，`context_loop/fl2v` 只能出现在 generation_mode schema 约束，retry/重试只能出现在明确禁用重试的配置或文案中，其他围栏能力不得存在。
    5. 汇总 `alembic upgrade/current/check`、pytest、frontend build 与人工导航的真实输出；任何缺项都不得勾选本 task 或声明 C001 完成。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** 不适用。
