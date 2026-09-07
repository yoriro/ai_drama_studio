# 跨 Change 实现决策

本文件只记录已经在已验收 change 中确立、会约束后续多个 change，且未由 `AGENTS.md` 或 `docs/PRD-v1.2.md` 直接规定的实现层决定。单个 change 的行为仍以其 spec 为准。

## D-001 每个运行时只维护一套依赖清单

- 决定：后端依赖与 pytest 配置只维护在 `backend/pyproject.toml`，不得再增加并行的 `requirements*.txt`；前端只使用 npm 的 `package.json` 与 `package-lock.json`，不得同时引入 Yarn、pnpm 或第二份 lockfile。新增依赖必须修改对应的既有清单。
- 理由：同一运行时存在两套依赖来源时，开发、测试和部署会解析出不同环境，无法判断哪一套代表仓库真实状态。
- 影响：所有后端、前端 change 的依赖增加、安装流程和持续集成配置。
- 来源：C001 规划时在 spec §3.1 确立，并由 T1、T4 的安装与构建验收固化。

## D-002 浏览器访问后端一律使用同源相对地址

- 决定：前端 HTTP API 使用 `/api`，媒体使用 `/media`，任务 WebSocket 使用当前页面 origin 派生的 `/ws`，业务代码不得硬编码后端主机或端口；Vite 开发代理必须同时覆盖当前已使用的这三个命名空间，生产构建继续按同源部署工作。
- 理由：同一份前端构建才能在开发代理和生产同源部署中复用，也避免浏览器绕过后端公开边界直接接触本地存储路径或环境地址。
- 影响：`frontend/src/api/`、Vite 配置，以及以后新增的 API、媒体和任务页面。
- 来源：C001 spec §5.3/T5 先确立 API 与 WS 的相对地址；C003 复审后的 T12 把遗漏的 `/media` 纳入同一规则；C004 OQ-4/T12 将规则用于真实任务 WS。

## D-003 请求会话只管生命周期，业务服务显式拥有事务

- 决定：每个 HTTP 请求取得独立 `AsyncSession`；请求依赖只负责创建和关闭会话，不隐式提交。读取用例不得产生提交，mutation 由 service 直接使用该会话开启一个明确事务并决定提交或回滚；在出现新的明确跨 change 裁决前，不在 service 与 SQLAlchemy 之间增加 repository 或 unit-of-work 包装层。
- 理由：事务的开始、提交和回滚必须在实施业务规则的同一层可见，否则依赖层的隐式提交或额外抽象会隐藏部分写入边界。
- 影响：所有 REST mutation、后续级联服务，以及需要与任务状态共同提交的生成 handler。
- 来源：C002 spec §3.1 与 T1 确立；C002-C006 的 service、级联和生成事务均沿用该边界。

## D-004 JSON 响应与 204 无响应体使用不同客户端入口

- 决定：前端传输层保留“解析 JSON”和“成功后不解析响应体”两个明确入口；任何声明返回 204 的 DELETE 都必须走 no-content 入口，不得先调用通用 JSON 解码器再用特殊值掩盖空响应。
- 理由：204 的合法响应体为空，把它交给 JSON 解码器会把成功请求误报为协议错误；独立入口能让返回类型与 HTTP 合同一致。
- 影响：现有及后续所有 DELETE API 客户端、页面 mutation 与错误呈现。
- 来源：C002 spec §7 和前端 T7-T9 走查时确立；C003 T9 继续复用到资产及图片删除。

## D-005 通用队列只管理任务生命周期，业务 handler 只管理任务类型步骤

- 决定：`backend/app/tasks/` 的通用队列负责入队、claim、heartbeat、取消检查、条件终态裁决和事件发布；各生成 change 只注册对应 task type 的 handler，handler 从已 claim task 读取持久化 payload，并通过通用上下文报告进度、检查取消和请求终态裁决。handler 不实现第二个 worker 循环，不复制 claim/heartbeat/取消状态机，也不自行建立另一套任务事件通道。
- 理由：任务生命周期只有一个所有者，才能让不同生成类型遵守同一套并发、取消和可观察语义，同时让队列基础设施不依赖任何具体生成服务。
- 影响：C005-C009 的全部生成 handler、应用 lifespan、任务 API/WS，以及 C011 的任务中心。
- 来源：C004 spec §5.4 和 T1、T8 确立执行器边界；C005 `gen_assets` 与 C006 `gen_shots` 的接线均按该边界实现。

## D-006 任务 payload 顶层固定为三个职责分离的成员

- 决定：所有 task payload 顶层必须且只能是 `input_snapshot`、`input_hash`、`source_revisions`。task type 专属的可回放执行输入放入 `input_snapshot`；R4 缓存键只放 `input_hash`，不适用时为 `null`；完成判定所需的实体标识和修订放入 `source_revisions`。运行地址、凭据、一次性确认 token、当前时间和 ORM 对象不得成为额外顶层键。
- 理由：固定顶层能让队列基础设施保持与 task type 无关，并把执行输入、缓存身份和来源修订三种不同职责分开，避免后续 change 各自发明不可兼容的 payload 形状。
- 影响：C005-C009 的入队 API、handler、任务 mock、调试详情与后续任务迁移判断。
- 来源：C004 spec §3.3 确立三成员组织方式；C005 spec §4.1/T3 与 C006 spec §4.1/T3 将“只能三键”作为精确合同复用。

## D-007 request_id 是规范化后的全局幂等标识

- 决定：接受 `request_id` 的任务入口必须先去除首尾空白，并要求规范化后长度为 1..128；它在全部 task type 和全部状态之间是全局 key。幂等比较只包含 task type、`target_id` 和该任务类型明确列出的客户端请求身份字段，不比较完整服务端执行 payload。`gen_asset_image` 的唯一身份字段是 `user_note`，按原值比较；`null`、空字符串和空白字符串互不等价。身份一致时返回原 task 与原冻结 payload，资产、风格、模板、缓存或 workflow 后续变化不影响重放；任一身份字段不同则返回结构化 409。
- 理由：数据库现有部分唯一索引只覆盖 active task，不能定义终态重复提交；客户端请求身份与服务端执行快照职责不同，不能因后续环境快照变化破坏同一请求的全局幂等重放。
- 影响：C007 `gen_asset_image`、C009 `gen_clip_video` 及任何复用通用入队服务的后续客户端。
- 来源：C004 proposal 的用户裁决 OQ-3、spec §6.2 与 T9 确立；2026-08-30 Sol 对 C007 最终修复的裁决。

## D-008 WS 是提交后的非持久观察流，REST 是重建状态的权威来源

- 决定：任务事件只能在对应数据库事务成功提交后发布，不建事件表、不做服务端历史回放，单独 heartbeat 变化不发布。客户端首次连接和每次重连都先建立 WS 并缓冲事件，再读取一次 REST 任务快照，先应用快照、后按序应用缓冲事件；收到快照中未知的 task 时只发起一个在途详情 GET，合并时不得让较旧 REST 数据覆盖较新的 WS 状态。socket 保持连接期间，WS 事件推进客户端观测 revision 而使在途 REST 重建响应失效时，失效响应不得写入业务数据、加载状态或错误；只要该次刷新仍对应待完成的 mutation 或 terminal 同步，客户端就必须在最新 revision 上合并或补发 REST 快照，直至最新快照成功应用或最新失败形成可见错误。terminal task id 去重不得抑制补刷新，成功提示不得早于最新快照应用，全部有效刷新结束后必须解除刷新状态；不得用轮询、自动重发 mutation 或应用旧响应代替补刷新。页面 mutation 也必须绑定发起时的资源 identity：迟到的成功或失败只能刷新其发起资源，用户已切换到另一资源时不得改写当前草稿、详情或成功通知；结构化 404/409 必须逐字显示错误并按影响面刷新正式 REST page/detail reader，不得重放原 mutation，最新列表不再包含选中资源时必须清空 selection/detail。
- 理由：提交后发布可避免广播数据库中不存在的状态；“先缓冲再取快照”同时补齐断线窗口并关闭快照覆盖新事件的竞态，而无需引入第二事实源或持久事件日志。只丢弃被 WS 事件失效的 REST 响应会让已提交 mutation 的页面重建永久停在旧状态，绑定最新 revision 的替代快照才能继续以 REST 为权威真相并关闭这一竞态窗口。绑定 mutation 的发起资源还能阻止 Clip A 的迟到响应污染当前 Clip B，并避免 404/409 后继续展示已不存在的幽灵资源。
- 影响：通用任务事件发布器、`/ws/tasks`、任务 REST 客户端、C005-C009 的进度呈现、C007 资产画廊、C010 导演台，以及后续所有同时使用 REST 状态重建、异步 mutation 与任务 WS 观察流的页面（包括 C011 任务中心）。
- 来源：C004 proposal 的用户裁决 OQ-4、spec §7.2-§7.3 与 T12 确立；Sol 复审后的 T15、T16 补齐 claim 提交时机和未知任务合并规则；C007 spec §6.2/AC-15 与 T21-T22 的修复前后生产通路探针补齐保持连接时的替代快照规则，需求方于 2026-08-31 确认纳入跨 change 决策；C010 spec §8/AC-22/AC-24 与 T23、T25、T28、T30 固化 mutation 发起资源、权威刷新和资源消失规则，需求方于 2026-09-07 确认提升为跨 change 决策。

## D-009 外部调用在最终事务外执行，业务写入与 done 共享一个数据库胜方

- 决定：vLLM、ComfyUI 和其他长耗时外部调用必须在最终数据库 mutation 事务之前完成；进入最终事务前执行最后一个取消安全点，事务内不插入外部调用或新的可取消等待。成功时，本次全部业务数据库写入、修订标记以及 task 的条件 `done/progress=1` 必须在同一事务提交；取消与成功竞争时只能有一个已提交胜方。
- 理由：外部调用放进事务会长时间占用连接和锁；业务写入与 done 分开提交则会出现 `canceled + 已写产物` 或 `done + 业务数据缺失` 的不可恢复状态。
- 影响：C005-C009 的生成 handler、通用条件终态原语、取消竞态测试和事务设计。
- 来源：C005 首轮复审发现最终取消窗口后由 T11 确立；C006 proposal 范围内第 7 项、spec §7.1 与 T5 明确复用。

## D-010 媒体文件与数据库之间使用同步显式补偿

- 决定：新增媒体在正式文件已落位但数据库插入失败时，必须在当前操作中把无人引用的正式文件移入 trash；破坏性替换先把旧媒体移入 trash，若随后数据库事务失败，必须在当前操作中恢复本次移动的文件到原路径。补偿失败必须与原始失败一起上报，不得留下伪成功；不得用后台补偿任务代替这两个同步动作。
- 理由：文件系统与 PostgreSQL 没有共同事务，只有记录本次文件动作并同步逆转，才能让失败后的数据库引用与磁盘状态尽量回到同一个可诊断边界。
- 影响：资产图片、clip video、槽位 override，以及 C007/C009 的新媒体落库和以后扩展既有删除/覆盖的 change。
- 来源：C003 spec §5.2 确立新增媒体数据库失败后的 orphan 处理；C006 spec §7.1/T5 将同一原则扩展为覆盖失败时恢复旧媒体。

## D-011 vLLM 传输层不拥有业务提示词或 schema

- 决定：共享 vLLM integration 只接收调用方显式给出的 messages、model、temperature、schema name 和封闭 schema，并完成一次 structured-chat HTTP 交换；模板读取、占位符渲染、动态 schema 构造和业务输出校验属于具体入队服务/handler。传输层不得按 task type 选择模板、拼接业务规则、改写 schema 或解释领域输出。
- 理由：模板和动态约束由对应 change 的业务输入决定；把它们藏进共享客户端会形成第二份不可见规则，并使入队快照无法准确复现实际请求。
- 影响：C005/C006 已有结构化 LLM 调用，以及 C007/C009 后续 prompt 构建和任何新增 vLLM task。
- 来源：C005 T2 确立最小 structured client、T3-T4 分离渲染与传输；C006 依赖该客户端并继续由自身构造动态 schema。

## D-012 资产图片 seed 内部保持整数、公开表示为十进制字符串

- 决定：数据库、task payload、UUIDv5 映射和提交给 Comfy 的资产图片 seed 始终使用 `[0, 2^63-1]` integer；所有公开 AssetImage JSON 的 `seed` 以及 `DEBUG_PROMPTS` 下 `input_snapshot.seed` 投影为十进制 string 或 `null`。不增加迁移、第二字段、通用 bigint 框架或双类型兼容合同。
- 理由：后端与 Comfy 需要完整 63-bit 整数语义，JavaScript `number` 无法无损表示全部公开值；边界投影隔离内部计算与前端显示精度。
- 影响：C007 资产图片 API、debug 响应和前端 `AssetImage.seed` 类型；内部 worker 与数据库合同不变。
- 来源：2026-08-30 Sol 对 C007 最终修复的 seed 表示裁决。

## D-013 健康检查遵循各真实上游协议

- 决定：vLLM `/health` 任意 2xx 都是 `healthy/null`，完全忽略响应体；连接失败、超时、无法形成合法 HTTP 响应和非 2xx 是 `unhealthy`。Comfy `/system_stats` 必须同时满足 2xx 与 JSON object；畸形 JSON 是 Comfy 协议错误。不存在 vLLM 畸形 JSON 分支。
- 理由：两个上游的健康端点协议不同，健康检查只验证各自真实合同，避免用另一服务的响应体要求污染诊断语义。
- 影响：C007 `/api/system/health`、启动探测和设置页诊断；health 不触发 GPU mutation。
- 来源：2026-08-30 Sol 对 C007 最终修复的 health 协议裁决。

## D-014 正式提示词模板是显式部署的运行配置

- 决定：Alembic 只建立 `prompt_templates` 的四个固定 key 并保留明确占位正文；正式模板不进入 migration、生产代码常量或隐藏 system prompt。四份已批准内容的来源分别为 C005 spec §5.1 `script2assets`、C006 spec §5.1 `script2shots`、C007 T13 经设置 API 验收的单一 `zimage`、C009 经设置 API 验收的流水线适配版 `minimaxh3`。C012 负责把这些既有内容整理为生产部署输入，在全新生产等价库迁移后通过正式设置 API 一次性安装四份模板，并在安装后及一次后端重启后分别 GET 逐字核对；M6 E2E 还必须让四条生成链路实际消费对应模板。缺失、占位或不一致时发布验收失败。
- 理由：spec 与旧数据库不是 Alembic 的可执行输入，过去逐 change 的 PATCH 只改变当时环境；将可编辑模板写进 migration 会混淆 schema 与运行配置并可能覆盖环境编辑，但只保留人工操作又无法复现生产部署。显式、可重复且走正式 API 的 bootstrap 同时保持两条边界。
- 影响：C012 spec/tasks、生产部署步骤、发布验收和灾难恢复演练；C010 及此前 change 不新增 migration/schema，也不要求重新提供模板正文。
- 来源：PRD §7、§11 M6、§12.2；C005-C009 正式模板证据；需求方于 2026-09-03 确认在 C012 补齐四模板生产部署。
