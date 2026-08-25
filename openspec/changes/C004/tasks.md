# C004 M2 队列与 WS 基建 Tasks

以下 T1-T13 按依赖顺序执行。Luna 一次只领取一个 checkbox；每项完成其全部验收并运行完整 pytest 后才能勾选和 commit。C004 不创建或修改 migration。原 OQ-1 至 OQ-4 已全部裁决并写入 spec，当前没有裁决阻塞 task。

## 按依赖排序的可执行 tasks

### T1 队列领域合同、快照边界与非生产验收入口

- [x] 建立最小任务队列模块边界、封闭 type/status、payload 快照校验和显式非生产验收命令；验收命令只使用既有 task type，正常应用不加载受控 mock，也不暴露 HTTP endpoint。
  - **前置 task：** 无。
  - **R：** 无；对应 PRD §3.2“任务快照”、§4 tasks、§6.1、§11 M2。
  - **范围：** 不实现数据库 claim、worker、API、WS 或具体生成 handler；不改 ORM/migration；不增加测试 task type、payload 特判、重试或 fallback。
  - **覆盖 AC：** AC-01、AC-07、AC-11。
  - **验收方式：**
    1. 在 `backend/` 运行 `python -m app.tasks.acceptance contract`，输出四个封闭 type、五个封闭 status、payload 三个顶层成员，并证明命令须显式调用。
    2. 运行 `python -m compileall -q app` 与 `python -m pytest -q tests`，均须成功。
    3. 运行 `rg -n "acceptance|mock|test_task" app/main.py app/api app/models`，确认正常 app 没有验收 endpoint、假 type 或按测试数据分支；人工核对 Alembic 无改动。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有队列模块脚手架或 payload schema 独立行，本 task 只用命令验收。
  - **追溯行：** 不适用。

### T2 PostgreSQL advisory lock 生命周期

- [x] 在应用 lifespan 最前置取得并持有项目专属 PostgreSQL advisory lock，拿不到则应用拒绝启动；关闭时在 worker/后台任务停止后释放锁和连接。
  - **前置 task：** T1。
  - **R：** 无；对应 PRD §6.1 第 1 条、§10“单进程 + advisory lock”、§11 M2。
  - **范围：** 只实现进程级锁和有序释放；不建锁表/锁文件、不新增配置、不实现恢复/worker，不把锁失败映射为 HTTP 409。
  - **覆盖 AC：** AC-02。
  - **验收方式：**
    1. 在两个 `backend/` PowerShell 终端为 `DATABASE_URL` 注入同一 C004 专用 DSN。终端 A 运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，须启动成功。
    2. 终端 B 运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8002`，须因 lock 已持有明确失败并非零退出；A 的 API 仍正常。
    3. 正常停止 A 后重跑终端 B 同一命令，须成功启动；记录三段原始日志。
    4. 运行 `python -m pytest -q tests` 与 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有 advisory lock 独立行，且关键证据必须来自两个真实 PostgreSQL 进程。
  - **追溯行：** 不适用。

### T3 启动恢复原语

- [x] 在持锁成功后、worker 启动前原子恢复遗留任务：所有 running → failed(`server restarted`)，写 finished_at；queued 原样保留；同时为非生产验收入口增加 `recover` 场景。
  - **前置 task：** T2。
  - **R：** 无；对应 PRD §6.1“启动恢复”、§6.4、§11 M2/M6。
  - **范围：** 不 claim queued、不实现业务 handler、不把 running 重排为 queued、不重试；完整“queued 继续消费”测试在 T8 worker 可达后新增。
  - **覆盖 AC：** AC-03。
  - **验收方式：**
    1. 在 C004 专用 PostgreSQL 预置一条 running 和一条 queued，启动应用后核对 running 的 status/error_msg/finished_at 与 queued 全部字段；保存查询输出。
    2. 运行 `python -m app.tasks.acceptance recover`，输出须与数据库查询一致，且没有 claim 或新建 task。
    3. 运行 `python -m pytest -q tests`，须全部通过；本 task 不回填 TRACEABILITY。
  - **计划测试层级：** 不新增自动测试；理由：追溯行还要求 queued 继续消费，T3 尚未交付 worker，提前写测试会固化不可达的半场景；完整 task-system mock 留到 T8。
  - **追溯行：** §6.1 重启恢复：遗留 running 任务变为 failed("server restarted")，queued 任务保留并继续消费。

### T4 单任务 claim 与条件转换原语

- [x] 实现按 id 获取最早 queued、跳过已锁行、queued→running 的单次 claim，以及以期望源状态为条件的 running→done/failed/canceled 转换；竞态败者不得覆盖结果；同时增加 `claim` 与 `transition-race` 验收场景。
  - **前置 task：** T3。
  - **R：** 无；对应 PRD §6.1 第 2 条、§6.4、§11 M2。
  - **范围：** 只实现数据库原语；不启动 worker 循环、不实现 heartbeat/cancel endpoint、API/WS 或自动重试。
  - **覆盖 AC：** AC-04、AC-05。
  - **验收方式：**
    1. 对 C004 专用 PostgreSQL 运行 `python -m app.tasks.acceptance claim --count 3 --claimers 2`；输出须证明按 id 顺序、三条恰好各 claim 一次、从未同时把同一 id 交给两个 claimant。
    2. 运行 `python -m app.tasks.acceptance transition-race`；输出须证明终态竞态只有一个条件更新成功，败者受影响行数为 0 且最终状态未被覆盖。
    3. 运行 `python -m pytest -q tests` 与 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有 claim/条件更新独立行，本 task 使用真实 PostgreSQL 并发命令验收。
  - **追溯行：** 不适用。

### T5 Heartbeat 与失败不重试

- [x] 为已 claim 的 running 执行增加每 10 秒 heartbeat/progress 条件更新和统一失败落库：异常时写完整 error_msg、finished_at 并进入 failed，一次失败不重排、不重试；同时增加 `heartbeat` 与 `fail-once` 验收场景。
  - **前置 task：** T4。
  - **R：** 无；对应 PRD §2.1(8)、§6.1 heartbeat、§6.4 第 1 条、§11 M2。
  - **范围：** 只实现 running 生命周期支撑；不实现具体生成步骤、外部调用、取消或 WS。
  - **覆盖 AC：** AC-05、AC-06。
  - **验收方式：**
    1. 运行 `python -m app.tasks.acceptance heartbeat --seconds 22`，保存至少三次 heartbeat 时间，间隔应约 10 秒且 task 始终 running。
    2. 运行 `python -m app.tasks.acceptance fail-once`，核对唯一 task 为 failed、error_msg 完整非空、finished_at 非空、没有新增 queued 行；日志包含原始 traceback 和 task 上下文。
    3. 运行 `python -m pytest -q tests`；用 `rg -n -i "retry|重试|backoff" app` 审核所有命中，确认没有自动重试路径。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有 heartbeat/通用失败独立行，必须用可计时的真实命令与日志验收。
  - **追溯行：** 不适用。

### T6 入队快照与同目标 active 去重

- [x] 实现内部入队边界：一次写入不可变 payload；gen_assets/gen_shots 同 type+target active 冲突，gen_asset_image/gen_clip_video 同目标允许多条；同时增加 target 去重、多抽卡与快照验收场景。request_id 的已裁决合同由 T9 独立完成。
  - **前置 task：** T4。
  - **R：** 无；对应 PRD §3.2“任务快照”、§4 tasks 两个部分索引、§6.1“同目标去重”、§11 M2。
  - **范围：** 不新增通用创建 API、不提前实现 T9 request_id 合同、不读取当前业务实体补 payload、不捕获冲突后重试插入。
  - **覆盖 AC：** AC-07、AC-09。
  - **验收方式：**
    1. 运行 `python -m app.tasks.acceptance dedupe-target --concurrency 2`；gen_assets 与 gen_shots 每组只能有一条 active，败者报告 conflict，数据库无重复 active。
    2. 运行 `python -m app.tasks.acceptance allow-draws --count 2`；gen_asset_image 和 gen_clip_video 各可产生同目标两条 active。
    3. 运行 `python -m app.tasks.acceptance snapshot`，入队后修改验收源数据，输出须证明已保存 payload 不变且执行读取保存快照。
    4. 运行 `python -m pytest -q tests` 与 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：追溯表把完整去重/幂等计划为 API 集成，但 C004 禁止通用创建 API，公开生成 endpoint 到 C005-C009 才可测试；本 task 只用真实 PostgreSQL 并发证据验证基础。
  - **追溯行：** §6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务。

### T7 内部取消状态与安全点

- [x] 实现 queued 直接 canceled、running 首次写 cancel_requested_at、执行器安全点转 canceled 的内部语义，增加 `cancel-race` 验收场景，并新增且仅新增该追溯行的 task-system mock 覆盖；公开 cancel endpoint 由 T11 完成。
  - **前置 task：** T5。
  - **R：** 无；对应 PRD §5 任务 cancel、§6.1“取消”、§6.4、§11 M2。
  - **范围：** 只实现内部条件转换；重复/终态 HTTP 响应由 T11 实现。不调用 Comfy `/interrupt`，不实现取消 UI，不重试取消。
  - **覆盖 AC：** AC-08。
  - **验收方式：**
    1. 运行 `python -m pytest -q tests/task_system/test_task_queue.py::test_queued_cancel_is_terminal tests/task_system/test_task_queue.py::test_running_cancel_stops_at_safe_point`，两用例须通过。
    2. 运行 `python -m app.tasks.acceptance cancel-race`，核对 cancel 与 complete 竞态只有合法条件转换胜出，终态不会被覆盖。
    3. 运行 `python -m pytest -q tests`；核对 TRACEABILITY 取消行只回填实际通过的 node ID。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** §6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断。

### T8 单 worker 循环与应用生命周期接线

- [x] 在 lock 获取和恢复成功后启动一个 worker 循环，把 claim、heartbeat、执行、失败和安全点取消串成最小生命周期；关闭时停止新 claim、结束后台任务并释放 lock/engine；增加 `worker` 验收场景，并新增且仅新增完整重启恢复追溯行的 task-system mock。
  - **前置 task：** T5、T6、T7。
  - **R：** 无；对应 PRD §6.1、§6.4、§10“单进程”、§11 M2。
  - **范围：** 正常 app 不注册生成 handler；受控 mock 只由显式验收命令注入。不实现 API、WS、具体任务流水线或 GPU 调度。
  - **覆盖 AC：** AC-04、AC-05、AC-06、AC-08、AC-10、AC-11。
  - **验收方式：**
    1. 运行 `python -m app.tasks.acceptance worker --tasks 3`，核对最多一条 running、按 id 串行、成功/失败/取消各按 spec 落库且进程无 retry。
    2. 运行 `python -m pytest -q tests/task_system/test_task_queue.py::test_restart_fails_running_and_continues_queued`，须覆盖 running 恢复与 queued 继续消费并通过。
    3. 启动正常 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，在无后续 handler/无任务时保持空闲；停止后核对 worker 已结束且 advisory lock 可被另一进程取得。
    4. 运行 `python -m pytest -q tests` 与 `git diff --check`；只在 TRACEABILITY 准确行回填上述 node ID。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** §6.1 重启恢复：遗留 running 任务变为 failed("server restarted")，queued 任务保留并继续消费。

### T9 Request id 幂等合同

- [x] 实现 spec §6.2 的全局 request_id 规范化、任意状态重复返回和不同请求冲突，增加 `dedupe-request` 验收场景；不得使用内容 hash、canonical serialization、签名、migration 或插入重试。
  - **前置 task：** T6。
  - **R：** 无；对应 PRD §4 tasks、§5 生成动作的 request_id、§6.1 去重与幂等。
  - **范围：** 只实现内部幂等边界；C004 不新增生成或通用任务创建 API，API 422/409 映射由拥有 request_id 的后续生成 endpoint 复用。
  - **覆盖 AC：** AC-12。
  - **验收方式：**
    1. 运行 `python -m app.tasks.acceptance dedupe-request --states all`，证明同 key + 同 type/target/payload 在 queued/running/done/failed/canceled 均返回同一 task id。
    2. 运行 `python -m app.tasks.acceptance dedupe-request-conflicts`，分别改变 type、target、payload，均须报告 conflict；空白与 129 字符 key 须报告 validation_error，带首尾空格的合法 key 须按规范化值复用。
    3. 运行 `python -m app.tasks.acceptance dedupe-request --concurrency 2`，证明只创建一行，败者读取胜者且日志无再次插入。
    4. 运行 `python -m pytest -q tests` 与 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 指定 API 集成，但 C004 没有且不得新增任务创建 API，自动覆盖留给 C005-C009 的生成 endpoint。
  - **追溯行：** §6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务。

### T10 任务列表与详情 API

- [x] 实现 spec §3.2/§3.4 的公开 Task schema、`GET /api/tasks` 与 `GET /api/tasks/{id}`：数组、id 降序、AND 过滤、limit 默认 50/范围 1..100、精确字段、永不暴露 payload，并落实 404/422。
  - **前置 task：** T1、T3。
  - **R：** 无；对应 PRD §4 tasks、§5 任务、§9、§11 M2。
  - **范围：** 不增加创建/更新 task API，不实现 UI、WS、取消、offset/cursor、total、搜索、日期范围或可选排序。
  - **覆盖 AC：** AC-13。
  - **验收方式：**
    1. 启动 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，使用 C004 专用 PostgreSQL 预置不同 type/status 的 101 条任务。
    2. 运行 `Invoke-RestMethod 'http://127.0.0.1:8000/api/tasks'`，核对 50 条、id 严格降序、每项字段与 spec 精确一致且没有 payload；运行带 `status`、`type`、`limit=1` 的组合查询核对 AND 过滤。
    3. 用 `Invoke-WebRequest` 检查 `limit=0`、`limit=101`、非整数 limit、非法 status/type 均为结构化 422；未知详情为结构化 404；合法无结果为 `[]`。
    4. 运行 `python -m pytest -q tests` 与 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有任务读取/分页独立行，只能以真实 PostgreSQL 和 HTTP 命令验收。
  - **追溯行：** 不适用。

### T11 Cancel API 与错误语义

- [x] 实现 `POST /api/tasks/{id}/cancel` 的无 body、200 当前对象、重复 running/canceled 幂等、done/failed 409 和未知 404，并新增且仅新增取消追溯行的 API 集成覆盖。
  - **前置 task：** T7、T10。
  - **R：** 无；对应 PRD §5 任务 cancel、§6.1、§6.4、§11 M2。
  - **范围：** 不实现前端取消按钮，不调用尚未交付的 Comfy `/interrupt`，不增加任务读取/取消以外的 API。
  - **覆盖 AC：** AC-14。
  - **验收方式：**
    1. 运行 `python -m pytest -q tests/api/test_tasks.py::test_cancel_task_states`，覆盖 queued、running、重复 running、canceled、done、failed、未知 id 与非空 body，并须通过。
    2. 使用 `Invoke-RestMethod`/`Invoke-WebRequest` 在真实 PostgreSQL 重复上述场景，核对 200/404/409/422、统一错误体和公开对象无 payload。
    3. 运行 `python -m pytest -q tests`；核对 TRACEABILITY 取消行只回填实际通过的 node ID。
  - **计划测试层级：** API 集成。
  - **追溯行：** §6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断。

### T12 WS 广播、自动重连与最小任务中心

- [x] 实现 `/ws/tasks` 提交后事件、Vite `/ws` 转发、前端 Task REST/WS 客户端、1s/2s/5s/10s 自动重连、每次连上后的“WS 缓冲→REST 快照→缓冲事件”同步、`demo` 验收场景，以及 loading/empty/ready/REST error/reconnecting 可见的最小任务中心。
  - **前置 task：** T8、T10、T11。
  - **R：** 无；对应 PRD §2.1(8)、§5 WS `/ws/tasks`、§9、§11 M2/M5。
  - **范围：** 页面只显示真实列表和实时变化；不提供取消按钮、历史分组、过滤/分页控件、服务端事件回放、heartbeat-only 广播、假任务或前端业务裁决。自动重连不得重发任何 mutation。
  - **覆盖 AC：** AC-15。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`；启动后端和前端，运行 `python -m app.tasks.acceptance demo`，在浏览器 Network/WS 核对五字段 frame、固定中文 message、提交后才推送、无 heartbeat-only frame、初次连接无历史回放。
    2. 任务运行中断开后端或 WS proxy，使断线期间任务在数据库进入终态；核对页面保留旧列表并显示“实时连接已断开，正在重连”，重连尝试间隔为 1s、2s、5s、其后 10s。
    3. 恢复连接后核对只执行一次任务 GET 同步，先应用快照再应用缓冲事件，页面最终状态与数据库一致；浏览器 Network 中不得出现重复生成/cancel 等 mutation。
    4. 离开任务页面，确认 socket 和重连计时器停止；返回页面重新执行首次同步。随后运行 `python -m pytest -q tests` 与 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有 WS/UI 独立行，使用真实浏览器、WS frame、计时记录和生产构建验收。
  - **追溯行：** 不适用。

### T13 C004 全链路与范围收口

- [x] 完成 C004 专用 PostgreSQL、队列并发、授权测试、REST/WS 自动重连、任务中心和范围围栏的全链路验收，只回填实际覆盖的追溯行。
  - **前置 task：** T1-T12。
  - **R：** 无；对应 PRD §0、§3.2、§4 tasks、§5 任务、§6.1、§6.4、§9-§12。
  - **范围：** 只收集和复核证据；不新增业务能力、自动测试、migration、生成 handler 或临时修复。
  - **覆盖 AC：** AC-01 至 AC-16。
  - **验收方式：**
    1. 在 `backend/` 对 C004 专用 DSN 运行 `python -m alembic current` 与 `python -m alembic check`；须保持 C003 head 且无新操作。
    2. 运行 `python -m pytest -q tests/task_system/test_task_queue.py`、`python -m pytest -q tests/api/test_tasks.py` 和 `python -m pytest -q tests`，全部通过并保存原始输出。
    3. 在 `frontend/` 运行 `npm run build`；启动前后端并运行 `python -m app.tasks.acceptance demo`，浏览器核对任务列表、WS frame、progress、failed error、断线节奏、REST 补状态和无 mutation 重提。
    4. 重跑双进程 advisory lock、启动恢复、两 claimant、target/request_id 并发、queued/running 取消与 fail-once 场景，保存数据库查询和日志证据。
    5. 在仓库根运行 `git diff --check`、`git status --short`，并运行 `rg -n -i "generation_runs|continuity|context_loop|fl2v|audio|音频|候选分镜|资产别名|版本化|retry|重试|POST.*/tasks" backend frontend`，逐项审查合法命中；WS transport reconnect 只允许出现在已裁决的观察通道实现中。
  - **计划测试层级：** 不新增自动测试；理由：本 task 只复跑授权用例和人工/命令验收，不得扩张 TRACEABILITY。
  - **追溯行：** 不适用。

## 外部依赖阻塞 tasks

当前无。PRD §12.4 的 PostgreSQL 开工门槛已有既往真实证据；C004 收口仍必须在本 change 专用 PostgreSQL 上产生新证据，但这属于 T13 的验收工作，不是当前外部依赖缺失。Z-Image/MiniMax 工作流、正式模板、vLLM sleep/wake 与 Comfy/vLLM 地址均不是 C004 门槛，禁止提前接入或伪造。
