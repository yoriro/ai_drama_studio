# C004 M2 队列与 WS 基建 Proposal

## 元数据

- Change：`C004`
- 里程碑：PRD §11 M2 的“队列 + WS”前置切片
- 前序 change：`C003`
- ROADMAP 范围：数据库任务队列、claim、advisory lock、heartbeat、条件状态转换、重启恢复、取消、去重、payload 快照与 WS 进度
- 直接 R 规则：无
- 当前状态：规划完成；OQ-1 至 OQ-4 已由用户于 2026-08-25 裁决，尚未实现、迁移或新增测试

## Gate 报告

### 输入与优先级

本次已完整阅读根目录 `AGENTS.md`、`openspec/ROADMAP.md`、`openspec/project.md`、`openspec/TRACEABILITY.md`，以及 PRD §0、§3、§4 tasks、§5 任务、§6.1、§6.4、§11、§12，并回看了 PRD 其余章节以确认后续 change 边界。还核对了当前 ORM、初始迁移、应用 lifespan、错误边界、WS 薄客户端、任务中心空页、C001-C003 change 文档、git 历史与 `openspec/archive/`。

有效优先级以 `AGENTS.md` 为首；而 `AGENTS.md` 又明确把 `docs/PRD-v1.2.md` 定为唯一、最高产品需求真相。因此，本指令只在不改变 PRD 产品语义的前提下约束文档结构、缺失处理和 task 标注，ROADMAP 只负责 change 边界。`AGENTS.md` 与 `openspec/project.md` 均约定 change 目录为 proposal/spec/tasks 三文件，与“只创建三文件”没有差异。

### 冲突检查结论

未发现会改变行为、因而触发“停止且不落文件”的冲突：

1. C003 的 T1-T14 均已勾选，proposal 有 2026-08-25 Sol 增量复审通过记录；它已提供 C004 所依赖的项目、剧集、资产与媒体闭环。
2. `openspec/archive/` 只有 `.gitkeep`，没有可继承的归档 change，也没有隐藏能力可假设存在。
3. C001 已按 PRD §4 建立 `tasks` 表、封闭 type/status、progress 约束和两个部分唯一索引；当前代码没有 queue service、worker、任务 API、任务 WS 或任务 UI 数据流，正好是 C004 的待交付现状。
4. C001 明确把 advisory lock、worker、取消、去重和 `/ws/tasks` 延后到 C004；这不是现有 spec 冲突。
5. 当前工作树已有 C001-C003 proposal/spec 和前置依赖清单的 Sol 维护改动；C004 不修改、覆盖或回退这些文件。

PRD 未定义的四项公开合同细节曾按 gate 规则进入 Open Questions；用户已全部裁决，现已转为本 proposal 的正式输入并写入 spec/AC/tasks。当前没有未决行为问题或裁决阻塞 task。

## 背景与现状

C001 已交付 PostgreSQL `tasks` 表及约束；C002/C003 没有写入任务。FastAPI lifespan 目前只管理 trash 清理，数据库 engine 没有进程级 advisory lock，也没有启动恢复或 worker。前端已有 `/tasks` 路由、空任务中心和 WS URL/open/close 薄封装，但 Vite 尚未转发 `/ws`，页面不会请求任务列表或建立连接。

C004 是后续 C005 `gen_assets`、C006 `gen_shots`、C007 `gen_asset_image` 和 C009 `gen_clip_video` 的执行底座。本 change 只交付任务基础设施和可观察的最小任务中心，不实现任何生成流水线或外部模型调用。

## 目标

交付以 PostgreSQL 为唯一事实源的单 worker 队列：应用进程以 advisory lock 保证单实例消费，启动时恢复遗留状态，按 id claim queued 任务，运行期间 heartbeat，所有状态变更使用条件转换，失败立即记录完整错误且不重试；提供取消、同目标去重、request_id 幂等基础、不可变 payload 快照、任务读取与 WS 进度广播。

同时提供一个显式调用、非生产的重复验收入口，使 C004 在尚无生成处理器时也能在专用 PostgreSQL 中驱动真实队列状态并由任务中心/WS 可见；该入口不得成为生产 API、不得新增 task type、不得根据测试数据走生产特殊分支。

## 范围内

1. 复用现有 `tasks` 表，不新增或修改表、列、索引和 Alembic revision。
2. 应用启动时取得稳定的 PostgreSQL advisory lock；同一数据库已有持锁进程时，新进程拒绝启动。
3. 启动恢复遗留 `running` 为 `failed` 且 `error_msg="server restarted"`；`queued` 保留并继续消费。
4. 单 worker 按 id 递增 claim 一条 queued 任务；claim、完成、失败和取消均以当前状态为条件，竞态败者不得覆盖胜者结果。
5. running 每 10 秒更新 heartbeat；任一步骤异常进入 failed、保留完整 error_msg、不重试。
6. 入队时持久化不可变 payload 快照；worker 只消费该快照，不回读当前业务实体补输入。
7. `gen_assets`/`gen_shots` 同 type + target 仅允许一条 active；图片/视频任务允许同目标多条；实现 PRD 的 request_id 幂等基础。
8. 提供 PRD §5 的任务读取、取消 API 和 `/ws/tasks` 广播；错误体继续使用 `{"detail":{"code","message"}}`。
9. 把任务中心从固定空态升级为最小的真实任务列表和 WS 状态/进度可见性；WS 断线按 1s/2s/5s/10s 上限节奏自动重连，并在每次连上后以一次 REST 同步补齐断线状态；取消按钮、历史体验和过滤控件留给 C011。
10. 交付显式、非生产的一次性验收驱动，并以真实 PostgreSQL 并发命令、授权的 task-system mock/API 集成测试、浏览器/WS 人工检查完成验收。

## 范围外

- 不实现 `gen_assets` 的 vLLM/guided_json/增量合并；延后至 C005。
- 不实现 `gen_shots`、impact/confirm token、覆盖与 trash；延后至 C006。
- 不实现 Z-Image、ComfyUI、GPU sleep/wake/free、`gen_asset_image`；延后至 C007。
- 不实现 clip 创建、槽位或 R5-R12；延后至 C008。
- 不实现 MiniMax H3、Comfy `/interrupt`、`gen_clip_video` 或视频进度适配；延后至 C009。
- 不实现导演台 UI；延后至 C010。
- 不实现任务中心取消控件、历史/过滤完整交互和全局视觉收口；延后至 C011。C004 只实现已裁决的 WS 自动重连与重连后一次 REST 同步，不扩展为通用网络重试框架。
- 不完成全链路 E2E、发布级重启/竞态回归；延后至 C012。
- 不增加通用任务创建 API、测试专用 HTTP endpoint、虚构 task type、生产 no-op handler、自动重试、fallback 或第二套队列事实源。
- 不实现或预建候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格/模板版本化、`generation_runs`、continuity、context loop、fl2v 或音频；这些不属于任何 v1 change。

## 现状与预期影响

- `backend/app/tasks/`：新增最小队列、状态转换、worker 与事件发布职责；具体生成处理器仍为空。
- `backend/app/api/`、`schemas/`：增加任务读取、取消和 WS 边界；不增加任务创建 endpoint。
- `backend/app/main.py`、数据库连接生命周期：在现有 trash 清理之外加入 advisory lock、恢复、worker 与有序关闭。
- `frontend/src/api/`、`pages/TasksPage.tsx`、Vite proxy：增加任务读取、WS 事件消费、自动重连/REST 补状态和最小真实列表。
- `backend/tests/task_system/` 与 `backend/tests/api/`：只允许覆盖 TRACEABILITY 的重启恢复、取消场景；去重 API 集成的完整覆盖在具体生成 endpoint 可达后回填。
- `openspec/TRACEABILITY.md`：实施时只回填本 change 实际新增且通过的授权用例；不得为 claim、heartbeat、advisory lock、WS 或 UI 另造测试行。
- `backend/alembic/`、现有 ORM schema：零变化。

## 依赖

### 前序 change

唯一前序 change 为 C003。其 tasks 已全部完成，提交 `50c8148` 后 Sol 复审记录为“通过”；C004 可依赖现有应用、真实 PostgreSQL async session、统一错误边界、任务中心空路由和 WS 薄客户端。C001-C003 尚未 archive 不扩大 C004 范围。

### 外部依赖

| 来源（PRD §12） | C004 开工/验收门槛 | 当前证据 | 缺失项与处理 |
|---|---|---|---|
| §12.1 Z-Image、MiniMax H3 工作流与绑定 | 非 C004 开工或验收门槛 | `docs/前置依赖清单.md` 仍为“待提供” | C004 不读取、不校验、不伪造；分别留待 C007/C009，C012 前全部到位 |
| §12.2 四个提示词模板初始内容 | 非 C004 门槛 | C002 已提供四个固定 key 的占位内容；正式内容仍待提供 | C004 不读取模板；正式内容留待 C012 验收前补齐 |
| §12.3 vLLM `--enable-sleep-mode` 与 sleep/wake 验证 | 非 C004 门槛 | 当前状态“待提供” | C004 不访问 vLLM；C007 开工前必须取得真实验证证据 |
| §12.4 PostgreSQL DSN | **开工与验收门槛**；advisory lock、claim、条件更新和并发去重必须使用真实 PostgreSQL | 前置依赖清单记录本机 PostgreSQL `5432` 已提供；C003 专用库已验证当前 head、`alembic check` 与完整 pytest，足以证明 C004 开工环境可达 | 开工门槛已满足；C004 验收仍缺专用数据库上的本 change 新证据，包括两进程锁竞争、并发 claim、恢复/取消/去重和完整回归。不得以旧输出、默认 DSN、SQLite 或 mock 代替 |
| §12.4 Comfy/vLLM 地址端口 | 非 C004 门槛 | 尚待对应 change 提供；`.env.example` 仅是示例 | C004 不连接外部服务，不把示例地址报告为 healthy |

C004 当前没有因外部依赖而不能开工的 task；最终收口 task 只有在真实 C004 PostgreSQL 验收证据产生后才能勾选。

## 已确认裁决

| 编号 | 正式裁决 | 直接影响 |
|---|---|---|
| OQ-1 任务读取合同 | `GET /tasks` 返回 JSON 数组，按 `id DESC`；`limit` 默认 50、范围 1..100；列表与详情公开 id/type/target_id/request_id/status/progress/error_msg 和全部任务时间戳，永不公开 payload | 任务 schema、列表/详情 API、任务中心初始同步、404/422 矩阵 |
| OQ-2 取消合同 | POST 无 body，成功返回 200 + 当前任务；queued 立即 canceled；running 首次写 cancel_requested_at；重复 running/canceled 取消幂等返回 200；done/failed 返回 409 | cancel API、条件竞态、API 集成测试、409 语义 |
| OQ-3 request_id | 全局 key，去首尾空白后 1..128 字符；任意状态下相同 type/target/payload 返回既有任务；同 key 但请求不同返回 409；只比较已有 JSON 结构，不增加 hash/签名 | 内部入队幂等、并发冲突、未来 C007/C009 请求合同 |
| OQ-4 WS 与重连 | WS 不回放；只广播数据库提交后的创建/状态/progress/cancel-request，heartbeat-only 不广播；message 为非空中文说明。首次连接及每次重连均建立 WS、缓冲新事件、GET 一次任务快照、先应用快照再应用缓冲；断线按 1s、2s、5s、其后每 10s 自动重连，页面卸载即停止 | WS 服务端、前端一致性、断线补状态和浏览器验收；重连只恢复观察通道，绝不重提 mutation/task |

## Open Questions

无。OQ-1 至 OQ-4 已全部裁决；若实施中发现新的行为缺失或冲突，仍须按 `AGENTS.md` 停止并报告，不得自行扩展本表。

## 风险与控制

- **双 worker**：锁必须绑定真实 PostgreSQL 会话并贯穿应用 lifespan；拿不到时整个应用启动失败，不只静默停 worker。
- **状态竞态**：所有 claim/完成/失败/取消只允许从指定源状态条件转换；受影响行数为 0 即表示竞态败北，不得再次写或重试。
- **快照被绕过**：worker 接收队列 payload 后不重新读取当前业务实体补全输入；具体 payload 成员由后续生成 change 扩展。
- **幂等与唯一索引边界**：现有 request_id 唯一索引只覆盖 active 行；任意状态重复返回与不同请求冲突必须由已裁决的服务合同保证，不能假装由索引已覆盖，也不得新增 migration。
- **WS 断线窗口**：单纯重连会漏掉断线期间事件；每次连上必须通过一次 REST 快照修复，并在快照期间缓冲新 WS 事件，避免旧快照覆盖较新事件。
- **无生成 handler 难验收**：只用显式非生产驱动注入受控 mock，任务类型仍取 PRD 四种之一；不把 mock 注册进生产 app，不新增 HTTP 后门。
- **测试越界**：advisory lock、claim、heartbeat、payload、WS/UI 使用真实命令和人工证据；只为三条现有 TRACEABILITY 场景写对应层级测试。
- **Comfy cancel 越界**：C004 只落实数据库取消请求与安全点；Comfy `/interrupt` 随实际 Comfy handler 在 C007/C009 接入，且仍为尽力调用，不得在 C004 伪造服务。

## 完成定义

只有全部 task 通过真实 PostgreSQL、授权测试、完整 pytest、前端构建和浏览器/WS 验收，任务中心可观察一次性驱动产生的真实状态及断线恢复，范围扫描无后续生成能力、额外 migration、任务重试或围栏违规，且 C004 专用证据被记录后，C004 才可提交 Sol 审查。
