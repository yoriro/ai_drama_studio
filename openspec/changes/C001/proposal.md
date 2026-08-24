# C001 M0 基础设施 Proposal

## 元数据

- Change：`C001`
- 里程碑：PRD §11 M0
- 前序 change：无
- 当前状态：可规划、可开始不依赖数据库连接的工作；在真实 PostgreSQL DSN 到位并完成迁移验证前不可验收

## 背景与现状

仓库当前只有冷启动文档、`.env.example` 和 `backend/`、`frontend/` 空目录，没有应用代码、依赖声明、迁移、测试或已归档 change。基线提交为 `8d716fe`。因此 C001 必须先建立最小可运行的前后端纵向切片，再创建 PRD §4 定稿的完整数据库结构；不能假设任何框架能力、数据库对象或外部服务已经存在。

经用户确认，`openspec/TRACEABILITY.md` 已增加唯一一条 C001 基础设施 smoke 行，用于建立首个合法 pytest 基线；除该行外，不扩张业务测试范围。

## 目标

交付一个可安装、可启动、前后端可互通、空页面可导航的 M0 基线：后端具备配置、统一 API 边界、OpenAPI 文档和明确标为“未检查”的系统健康骨架；数据库可从空 PostgreSQL 升级到 PRD §4 的完整 schema；前端具备路由壳、基础组件约定、相对路径 API/WS 客户端和空任务中心。

## 范围内

1. 建立 FastAPI 后端工程、单一依赖声明、环境配置加载、localhost CORS、日志入口和统一错误响应边界。
2. 提供根路径 `/docs`、`/openapi.json`，以及 `/api/system/health` 骨架；骨架只报告 vLLM、ComfyUI 与工作流绑定“未检查”，不得尝试连接这些服务。
3. 使用 SQLAlchemy 2 声明 PRD §4 的全部 13 张表、显式约束和索引，并以一个 Alembic 初始迁移从空 PostgreSQL 建到 head。
4. 建立 React 18 + Vite + TypeScript 前端工程、应用布局壳、首页/设置/任务中心空页面、最小共享组件约定。
5. 建立相对路径 JSON API 客户端和 WebSocket URL 构造器；前端通过 health 骨架展示后端连接状态，不建立任务 WS 连接。
6. 添加追溯表授权的最小 API 集成 smoke 测试，并以构建命令、迁移命令和人工导航完成其余验收。

## 范围外

- 不实现 M1 及后续任何 CRUD、生成动作、媒体上传/读取、trash 文件处理或业务页面。
- `tasks` 表仅按 §4 建表；不实现 claim、worker、advisory lock、heartbeat、取消、去重或 `/ws/tasks`，这些属于 C004。
- 不连接 vLLM/ComfyUI，不加载工作流、不计算 workflow hash、不做 sleep/wake/free；这些属于 C005/C007/C009。
- 不写入四个提示词模板的初始记录，不创建 seed 数据；模板管理属于 C002，正式模板内容是后续外部依赖。
- 不实现项目工作区、剧本/资产/分镜/导演台路由或占位业务交互；有实体 ID 后由后续 change 建立。
- 不实现鉴权、HTTPS 或公网配置；PRD 明确限定本地单操作者。
- 不实现或预建范围围栏中的候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格/模板版本化、`generation_runs`、continuity、context loop、fl2v 或音频能力；仅按 PRD 在 `clips.generation_mode` 约束中保留三个枚举值，应用不读写非 `ref2v` 值。

## 预期影响

- `backend/`：新增 Python 工程、FastAPI 应用、配置、SQLAlchemy metadata、Alembic 和一条授权的 API smoke 测试。
- `frontend/`：新增 Vite/React/TS 工程、三条空路由、AppShell、空态组件、API/WS 基础客户端和 health 状态展示。
- `openspec/TRACEABILITY.md`：实施 smoke 测试后回填真实用例 ID；不得增加其他 C001 测试行。
- 不修改 PRD、ROADMAP、全局范围围栏或后续 change 文档。

## 外部依赖

| PRD §12 项 | 与 C001 的门槛 | 当前证据 | 缺失项与处理 |
|---|---|---|---|
| §12.1 Z-Image、MiniMax H3 工作流与绑定 | 非 C001 开工或验收门槛 | `docs/前置依赖清单.md` 状态为“待提供” | C001 不创建绑定文件、不探测工作流；分别留待 C007/C009 |
| §12.2 四个提示词模板初始内容 | 非 C001 开工或验收门槛 | 状态为“待提供”，PRD 允许先用占位示例 | C001 不 seed 占位内容；C002 以后按其 spec 处理 |
| §12.3 vLLM sleep/wake | 非 C001 开工或验收门槛 | 状态为“待提供” | C001 不调用 vLLM；C007 开工前必须补齐验证证据 |
| §12.4 PostgreSQL DSN | **C001 验收前必须到位**；ORM 声明和迁移文件可先编写，实际 upgrade/check 不可跳过 | `.env.example` 只有本地示例，依赖清单仍为“待提供”，没有可达性或权限证据 | 需提供可连接的专用 PostgreSQL 数据库、DSN 与建表权限；未提供时 C001 保持未验收，禁止用 SQLite 或 mock 代替 |
| §12.4 Comfy/vLLM 地址端口 | 非 C001 门槛，分别属于 C005/C007 | `.env.example` 只有示例地址，不能视为服务已到位 | health 骨架必须返回 `not_checked`，不得把示例地址报告为 healthy |

## 风险与控制

- **全量 schema 易越界**：M0 明确要求 §4 全量建表，但本 change 只创建结构，不附带后续业务服务、接口或任务逻辑。
- **健康骨架被误解为真实诊断**：响应固定使用 `not_checked`，前端显示“未检查”，不做成功推断；C007 才实现探测与 binding hash。
- **数据库实现漂移**：迁移必须与 SQLAlchemy metadata 一致，显式检查所有部分唯一索引、枚举值约束、`SET NULL` 和围栏禁止字段。
- **无真实 DSN 导致伪验收**：示例 DSN、SQLite、mock 或仅生成 SQL 都不能替代在 PostgreSQL 上执行 `upgrade head` 与 `alembic check`。
- **前端壳演变成伪业务**：空页面不放 mock 数据、假按钮或临时工作区 URL；只提供稳定的顶层导航和真实 health 连接状态。

## 完成定义

`spec.md` 的全部验收标准满足、真实 PostgreSQL 迁移证据到位、授权 smoke 测试与完整 pytest 通过、前端生产构建成功、前后端互通且三条空路由可导航后，C001 才可提交审查；任何缺项均保持未完成。
