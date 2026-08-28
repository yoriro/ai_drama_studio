# C004 M2 队列与 WS 基建 Spec

## 1. 规范边界

本 spec 只授权 ROADMAP `C004`。规范来源为 PRD §2.1(8)、§3.2、§4 tasks、§5 通用与任务、§6.1、§6.4、§9、§10、§11 M2、§12，以及 `AGENTS.md` 的失败/错误/范围纪律。

proposal 原 OQ-1 至 OQ-4 已由用户于 2026-08-25 全部裁决；本 spec 已冻结其任务读取、取消、request_id 和 WS 重连合同。当前没有需要 Luna 自行选择的公开行为。

C004 复用 C001 已有 `tasks` 表和索引，禁止新增或修改迁移。范围围栏中的机制一律不得出现；`clips.generation_mode` 的唯一合法预留也与本 change 无关。

## 2. 可观察交付物

C004 的已冻结范围完成后必须满足：

1. 同一 PostgreSQL 数据库同一时刻只允许一个应用进程持有本项目 worker advisory lock；第二进程拿不到锁时拒绝启动并明确记录原因。
2. 每次成功启动在 worker 消费前，把遗留 running 任务置为 failed、写 `server restarted`；queued 任务保持 queued 并随后可被消费。
3. 单 worker 按 task id 递增顺序 claim queued；并发 claim 不得获得同一任务。
4. running 任务每 10 秒持久化 heartbeat；claim、完成、失败、恢复和取消均为条件状态转换，竞态败者不得覆盖已提交状态。
5. 任一步骤异常立即使仍处于 running 的任务进入 failed，写入完整非空 error_msg，不自动重试、不重新排队、不伪装 done。
6. 入队 payload 是不可变执行快照；worker 全程使用该快照，不重新读取当前实体补足输入。
7. queued 取消直接 canceled；running 取消只先记录 cancel_requested_at，执行器在安全点看到后进入 canceled。
8. active 的 gen_assets/gen_shots 按 type + target_id 去重并形成 409 冲突语义；gen_asset_image/gen_clip_video 允许同目标多条排队。
9. `GET /api/tasks` 返回最新优先、最多 100 条的公开任务数组，`GET /api/tasks/{id}` 返回同一公开 schema；两者永不返回 payload。
10. `POST /api/tasks/{id}/cancel` 无 body、成功返回当前任务；重复取消幂等，done/failed 取消为 409。
11. `/ws/tasks` 只广播已提交的任务变化，不回放历史、不广播 heartbeat-only；任务中心自动断线重连，并在每次连上后以一次 REST 快照补齐断线状态。
12. 显式非生产验收驱动可在专用环境使用 PRD 已有 task type 驱动队列和受控 mock；正常应用不加载 mock handler，不暴露验收 endpoint。

## 3. 数据契约

### 3.1 既有 Task 持久化模型

本 change 不改 schema；以下合同直接复用 PRD §4 和当前 C001 migration：

| 字段 | 必填性与精度 |
|---|---|
| `id` | 数据库生成的正整数主键 |
| `type` | 必填、封闭枚举：`gen_assets`、`gen_shots`、`gen_asset_image`、`gen_clip_video`；不得添加验收/测试类型 |
| `target_id` | 必填整数；前两类指 episode，`gen_asset_image` 指 asset，`gen_clip_video` 指 clip |
| `request_id` | 可空 TEXT；非空时为全局幂等 key，去首尾空白后长度 1..128，并保存规范化值 |
| `payload` | 必填 JSON object；见 §3.3 |
| `status` | 必填、封闭枚举：`queued`、`running`、`done`、`failed`、`canceled` |
| `progress` | 必填双精度数，闭区间 `[0,1]`；queued 初始值为 `0`，done 为 `1`，failed/canceled 保留最后已提交进度 |
| `error_msg` | 可空；failed 时必须为完整、非空错误文本；其他新建状态不得伪造错误 |
| `heartbeat_at` | 可空、UTC 带时区时间；claim 时首次写入，running 期间每 10 秒刷新 |
| `cancel_requested_at` | 可空、UTC 带时区时间；只在 running 收到取消意图时写入 |
| `created_at` | 必填、数据库生成的 UTC 带时区时间 |
| `started_at` | 可空；queued 为 null，首次成功 claim 时写 UTC 时间且不再覆盖 |
| `finished_at` | 可空；queued/running 为 null，进入 done/failed/canceled 时写 UTC 时间 |

API 中所有时间统一为 ISO 8601 带时区字符串；内部比较使用 UTC。C004 没有金额字段，金额格式不适用。

### 3.2 公开 Task schema

列表、详情和 cancel 成功响应使用同一公开对象：

| 字段 | JSON 类型 | 必填性 |
|---|---|---|
| `id` | integer | 必填 |
| `type` | closed enum string | 必填 |
| `target_id` | integer | 必填 |
| `request_id` | string 或 null | 必填 |
| `status` | closed enum string | 必填 |
| `progress` | number 0..1 | 必填 |
| `error_msg` | string 或 null | 必填；failed 时非空 |
| `heartbeat_at` | ISO 8601 string 或 null | 必填 |
| `cancel_requested_at` | ISO 8601 string 或 null | 必填 |
| `created_at` | ISO 8601 string | 必填 |
| `started_at` | ISO 8601 string 或 null | 必填 |
| `finished_at` | ISO 8601 string 或 null | 必填 |

公开对象禁止包含 `payload`、`input_snapshot`、`input_hash`、`source_revisions` 或其他内部字段。任务列表直接返回该对象的 JSON 数组，不使用 envelope；无结果返回 `[]`。详情与 cancel 返回单个对象。

### 3.3 Payload 快照

`payload` 在入队时一次写入，此后不可修改。它必须是 JSON object，并保留三个顶层成员：

- `input_snapshot`：必填 JSON object，保存该任务执行所需全部输入；具体成员由 C005/C006/C007/C009 各自 spec 定义。
- `input_hash`：必填 string 或 null；只有 R4 适用的图片/视频任务由后续 change 写非空值。
- `source_revisions`：必填 JSON object；键和值的业务结构由拥有该任务的后续 change 定义，C004 允许空 object 但不猜测实体字段。

worker 只能使用已 claim 行中的 payload。当前实体后续编辑不能改变正在运行任务的输入；完成时的 revision 对比及产物回写属于具体生成 change，不在 C004 实现。

### 3.4 枚举、默认、分页、排序与过滤

- type/status 都是封闭枚举，未知值不得透传到数据库。
- C004 不增加配置项；heartbeat 周期固定为 PRD 规定的 10 秒，数据库仍由 `DATABASE_URL` 指定。
- `GET /api/tasks` 只接受可选 `status`、`type`、`limit`：status/type 必须取封闭枚举；同时提供时按 AND 过滤。
- `limit` 默认 50，只接受整数 1..100；超范围或类型错误为 422。
- 结果固定按 `id DESC`，不接受排序参数；不提供 offset/cursor、total、搜索或日期范围。

## 4. 状态机与条件转换

### 4.1 合法转换

| 触发 | 源状态 | 目标状态 | 同步字段 |
|---|---|---|---|
| claim | queued | running | `started_at=now`、`heartbeat_at=now` |
| heartbeat/progress | running | running | 更新 heartbeat；有新进度时更新 `[0,1]` 内 progress |
| 成功完成 | running | done | `progress=1`、`finished_at=now`、`error_msg=null` |
| 执行失败 | running | failed | `finished_at=now`、完整 `error_msg` |
| 启动恢复 | running | failed | `finished_at=now`、`error_msg="server restarted"` |
| 取消 queued | queued | canceled | `finished_at=now`，不写 cancel_requested_at |
| 请求取消 running | running | running | 首次写 `cancel_requested_at=now` |
| 安全点确认取消 | running | canceled | `finished_at=now`，保留最后 progress |

done/failed/canceled 是终态；本 change 不允许终态回到 queued/running，不提供 retry/requeue。除表中转换外，不得写状态。

取消的重复与终态语义：

- running 已有 cancel_requested_at 时再次取消不改库，返回当前任务 200，也不重复触发后续外部 interrupt。
- canceled 再次取消不改库，返回当前任务 200。
- done/failed 不可取消，返回结构化 409；不得改写终态。
- cancel 与完成竞态时以条件更新实际胜者为准：若任务已变 done/failed，cancel 返回 409；若任务已 canceled，返回 200 canceled。

### 4.2 条件更新

每次状态转换都必须同时检查期望源状态。条件不成立时：

- 不再写任何 task 字段；
- 不覆盖另一事务已经完成的结果；
- 不通过重试争夺状态；
- 调用方按已提交的真实状态继续处理或结束。

error_msg 必须保留原始失败的完整因果消息；结构化日志同时记录 task id/type/target 和 traceback。不得吞异常、替换成默认成功或仅写笼统“失败”。

## 5. 单进程锁、恢复与 worker

### 5.1 Advisory lock 生命周期

- 使用稳定、项目专属的 PostgreSQL session advisory lock 标识；不新增锁表、锁文件或配置项。
- 应用在启动其他后台工作、执行恢复或接受请求前取得锁，并以独立数据库会话持有到整个 lifespan 结束。
- 同一数据库已有持锁进程时，新应用进程必须启动失败、输出明确日志并以非零退出；不得只禁用 worker 后继续提供 API。
- 正常关闭先停止 worker，再释放 lock，最后释放数据库资源。进程异常中止由 PostgreSQL 会话断开自动释放。

### 5.2 启动恢复

取得 lock 后、首次 claim 前，在单一数据库事务内完成恢复：所有遗留 running → failed(`server restarted`)，所有 queued 不变。恢复失败使应用启动失败；不得跳过恢复后继续消费。

### 5.3 Claim 与 heartbeat

- 仅一个进程内 worker 循环；每次按 id 最小的 queued task claim 一条。
- claim 必须锁住候选行并跳过其他事务已锁行；提交 running 后才交给执行器。
- running 时每 10 秒 heartbeat。heartbeat 条件更新失败表示任务已被另一合法转换终结，当前执行器必须停止后续 task 状态回写。
- worker 串行执行，不并发运行两个 task；C004 不引入第二 worker 数配置。

### 5.4 执行器边界

C004 只定义一个接收已持久化 payload、报告 progress、检查取消安全点并返回成功/失败的执行边界，不实现四类生成任务的步骤。正常应用在没有后续 handler 时只等待队列；若出现无法执行的合法 task，必须显式 failed 并记录缺少执行器的完整原因，不得假 done 或永远占用 running。

非生产验收驱动可以显式注入受控执行器验证 queue/WS，但不得注册进正常 application lifespan，也不得按 payload 值触发生产特殊路径。

## 6. 去重、幂等与并发

### 6.1 同目标 active 去重

- `gen_assets`、`gen_shots`：同一 type + target_id 在 queued/running 中至多一条；并发败者得到既有冲突语义，未来生成 API 映射为 HTTP 409。
- `gen_asset_image`、`gen_clip_video`：同目标允许多条 queued/running；不得复用前一条结果来伪装新抽卡。
- 现有 PostgreSQL 部分唯一索引是并发最终防线；服务层先查不能替代数据库约束，也不得用捕获冲突后重试插入来掩盖竞态。

### 6.2 Request id

request_id 为可选的全局幂等 key：去除首尾空白后必须为 1..128 字符，空白或超长由未来接受该字段的生成 API 返回 422。规范化值写入 task。

入队判定顺序固定为：

1. 若 request_id 已存在于任意状态的 task，且 type、target_id、payload JSON 结构均相同，直接返回该既有 task，不创建新行。
2. 若 request_id 已存在但上述任一内容不同，返回冲突语义，未来生成 API 映射为 409。
3. request_id 不存在时，再执行同目标 active 去重并尝试创建。
4. 并发请求由现有 active request_id 唯一索引裁决；冲突败者读取胜者行并执行第 1/2 项，不重试插入。

比较使用已有 type/target 和 JSON 结构相等，不计算内容 hash、不做 canonical serialization、不新增签名或 migration。terminal task 的重复 key 同样返回既有 task；不能依赖只覆盖 active 的现有索引代替服务合同。

### 6.3 HTTP 幂等与版本

- C004 不引入 `Idempotency-Key` header；request_id 是后续生成请求 body/内部入队合同的一部分。
- Task 没有公开 version 字段，不使用 `If-Match`、ETag 或自增版本号。
- 并发安全由数据库条件状态转换和既有唯一索引保证，不引入自研乐观锁字段。
- 客户端、API 和 worker 均不自动重试任务或 mutation；重复提交只按已冻结的去重/幂等合同处理。WS 传输重连只恢复观察通道，不属于任务重试，且不得重发任何 POST/PATCH/PUT/DELETE。

## 7. API 与 WS 边界

### 7.1 路径

PRD 只授权：

| 方法与路径 | 已冻结行为 |
|---|---|
| `GET /api/tasks?status=&type=&limit=` | 200 + §3.2 对象数组；过滤/limit/排序见 §3.4 |
| `GET /api/tasks/{id}` | 200 + §3.2 单对象；未知 task 为 404 |
| `POST /api/tasks/{id}/cancel` | 不接受 body；成功 200 + §3.2 当前对象；状态行为见 §4.1 |
| `WS /ws/tasks` | 服务端广播 §7.2 事件；C004 前端不发送业务消息 |

不得新增 `POST /tasks` 或其他通用创建接口。任务只能由 C005/C006/C007/C009 的生成动作入队，C004 验收驱动不暴露 HTTP endpoint。

### 7.2 已冻结消息字段

WS 事件是 JSON object，且五个字段全部必填：`task_id` 为正整数，`type`/`status` 取 §3.1 封闭枚举，`progress` 在 `[0,1]`，`message` 为非空中文 string。

只在下列数据库变化成功提交后广播：任务创建、状态改变、progress 实际改变、首次 cancel_requested_at 写入。heartbeat_at 单独变化不广播；服务端不在新连接时回放历史。

message 合同：queued=`任务已排队`，running/进度=`任务执行中`，首次取消请求=`已请求取消`，done=`任务完成`，canceled=`任务已取消`，failed=`任务失败：{error_msg}`。WS 不是第二事实源；数据库提交失败时不得广播伪事件。

### 7.3 前端连接、补状态与重连

首次连接和每次重连成功后使用同一同步流程：

1. 建立 WS，并立即缓冲同步期间收到的新事件。
2. 请求一次 `GET /api/tasks` 快照。
3. 先用快照替换任务列表，再按接收顺序应用缓冲事件，随后进入实时模式。

这样既补回断线窗口，也避免较旧 REST 快照覆盖较新 WS 事件。同步完成后不轮询。

WS 断开时保留最后任务列表并显示“实时连接已断开，正在重连”；重连等待依次为 1 秒、2 秒、5 秒，之后每次 10 秒，成功完成 WS + REST 同步后重置退避。页面卸载时关闭 socket、取消计时器并停止重连。重连期间绝不重发生成、取消或其他 mutation。

## 8. 错误码矩阵

### 8.1 固定 schema

所有 REST 非 2xx 响应必须为：

```json
{"detail":{"code":"<non-empty>","message":"<non-empty>"}}
```

前端只直显 `detail.message`；不得自动重试。启动失败和 worker task failure 不是 REST 响应：前者以进程非零退出和日志呈现，后者写 task failed/error_msg 并经任务读取/WS 呈现。

### 8.2 状态码与 code

| HTTP | code | 触发条件 | 不得替代为 |
|---|---|---|---|
| 400 | `validation_error` | 既有 localhost CORS preflight 协议不合法；任务内容/业务校验仍使用 422 | 409、422 |
| 404 | `not_found` | `GET /api/tasks/{id}` 或 cancel 的 task id 在当前数据库不存在，或 API 路径不存在 | 403、409、422 |
| 403 | 不使用 | v1 无用户/权限系统；不存在“有资源但无权限查看”的任务场景 | 不得用来隐藏 404 |
| 405 | `method_not_allowed` | 已知路径使用未授权 HTTP 方法 | 404、422 |
| 409 | `conflict` | gen_assets/gen_shots 同 type + target 已有 active；同 request_id 被不同请求复用；对 done/failed 任务取消 | 422 或 200 伪成功 |
| 422 | `validation_error` | path/query/body 类型不合法；status/type 不在封闭枚举；limit 非 1..100 整数；request_id 为空白或超过 128；cancel 携带非空 body | 409 |
| 500 | `internal_error` | API 边界发生未预期服务端错误；必须记录 traceback | 200、409、422 |

404 与 403 的判定只看鉴权：本地单操作者无鉴权，所以资源不存在一律 404，403 永不使用。409 与 422 的判定只看“请求本身是否合法”：合法请求被当前任务/资源状态阻止为 409；请求内容、枚举、类型或范围非法为 422。

advisory lock 获取失败不能映射为 HTTP 409，因为应用不得启动到可服务状态。

## 9. 前端可观察边界

任务中心初始读取真实任务，展示 type/status/progress/error 和时间，并消费 `/ws/tasks` 更新可见状态。loading、empty、ready、REST error、WS reconnecting 必须可区分，错误直显 `detail.message`；重连成功后断线提示消失。

C004 不提供任务中心取消按钮、历史分组、过滤控件、分页控件或视觉专题；这些延后至 C011。前端不得自行判断任务冲突、取消是否合法或篡改服务端状态。

## 10. 向后兼容与迁移影响

- 没有 Alembic migration；现有 C001 task schema 和数据保持原结构。
- C001 的固定“暂无任务”页面被真实数据流替换，这是预期的可观察行为升级；无旧接口需要兼容。
- 首次运行 C004 时，数据库中任何遗留 running 行会被可观察地改为 failed(`server restarted`)；queued 保留。该恢复是 PRD 要求，不提供兼容开关。
- C001 WS 薄封装继续复用并扩展为已裁决的自动重连/补状态；不保留另一套事件格式或旧路径。
- 项目不承诺向后兼容，不增加双路径、deprecated alias 或数据 shim。

## 11. Non-Goals 与后续归属

| Non-Goal | 后续归属 |
|---|---|
| gen_assets 实际执行、vLLM guided_json、R2、剧本按钮 | C005 |
| gen_shots、R1/R3、impact/token、成功后覆盖 | C006 |
| gen_asset_image、Comfy/Z-Image、GPU 分时与实际 Comfy cancel | C007 |
| clip preview/create/槽位 | C008 |
| gen_clip_video、Comfy 视频进度与 actual_duration | C009 |
| 导演台业务 UI | C010 |
| 任务中心取消/历史/过滤完整交互与视觉收口 | C011 |
| 全链路重启、竞态、trash 发布回归 | C012 |
| 候选分镜版本、分镜结构编辑、资产别名/合并、模板版本化、generation_runs、continuity | 不属于任何 v1 change；PRD §0/§2.2 围栏 |
| context loop、fl2v、音频 | 不属于任何 v1 change；PRD §0/§2.3 围栏 |

## 12. 验收标准

- **AC-01 Schema 零漂移**：真实 PostgreSQL 的 current 仍为 C003 head，`alembic check` 无操作；diff 没有 migration、task 表/字段/索引改动或额外配置。
- **AC-02 单进程锁**：同一 DSN 的首进程可启动；第二进程明确拒绝启动；首进程退出释放锁后第二进程可启动。
- **AC-03 重启恢复**：预置 running/queued 后启动，running 精确变 failed(`server restarted`)并有 finished_at，queued 不变且可继续被 claim；授权 task-system mock 与真实 PostgreSQL证据均通过。
- **AC-04 Claim 串行性**：按 id claim，两个并发 claimant 不得到同一行，单 worker 同时最多一条 running。
- **AC-05 Heartbeat 与条件转换**：running 约每 10 秒更新 heartbeat；竞态条件不满足时不覆盖已提交终态。
- **AC-06 失败不重试**：受控执行异常后任务只进入一次 failed，error_msg 完整非空，日志有 traceback，无新 queued 行、无 retry。
- **AC-07 快照执行**：验收期间改变对应当前实体或外部输入，不改变 worker 已取得的 payload；payload 行本身不被回写。
- **AC-08 取消核心**：queued 直接 canceled；running 先写 cancel_requested_at，受控执行器在安全点停止并 canceled；授权 task-system mock 通过。
- **AC-09 同目标去重**：并发 gen_assets/gen_shots 同 type+target 仅一条 active；图片/视频同目标可有多条 active；不靠应用重试取得结果。
- **AC-10 Worker 生命周期**：worker 只在 lock 与恢复成功后启动，串行消费；关闭时停止 claim、释放资源；没有真实生成 handler 时不产生伪成功。
- **AC-11 验收驱动隔离**：显式驱动可让真实任务状态经数据库和后续 WS/UI 可见，但正常 app 无验收 endpoint、假 task type、生产 mock handler或测试数据分支。
- **AC-12 Request id**：同 key 同 type/target/payload 在 queued/running/terminal 均返回原 task；同 key 不同请求为 409；空白/超长为 422；并发只创建一行且没有 hash、签名、migration 或插入重试。
- **AC-13 任务读取 API**：列表为 id 降序 JSON 数组、默认 50/最大 100，过滤为 AND；详情/列表字段精确符合 §3.2 且没有 payload；未知为 404、非法查询为 422。
- **AC-14 Cancel API**：无 body；queued、running、重复 running/canceled 均按 §4.1 返回 200 当前对象，done/failed 为 409，未知为 404；错误体统一。
- **AC-15 WS 与重连**：只推提交后业务变化、不推 heartbeat-only、不回放；首次和重连按“WS 缓冲→REST 快照→缓冲事件”同步，按 1/2/5/10 秒节奏恢复，断线期间终态不丢且不重发 mutation。
- **AC-16 回归与范围**：授权测试、完整 pytest、前端 build、真实浏览器/WS、`git diff --check` 和围栏扫描全部通过；只有实际覆盖的 TRACEABILITY 行回填用例 ID。
