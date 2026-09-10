# C012 M6 E2E 与发布验收

## 目标与边界

### 目标

以已归档 C011 为前序，完成 PRD §11 M6。先关闭会破坏真实生成的锁顺序风险，落实需求方于 2026-09-10 批准的 R2 资产唯一性，再提供有界的任务观察通路，最后在全新生产等价库完成四份正式模板部署、真实一集资产/分镜与两个片段视频、全级联、恢复、trash 和竞态验收。本文件是待实施合同，文中的期望值不是已取得结果。

### 范围内

1. 同一生成提交与 API 入队/编辑之间的锁顺序诊断、必要的既有锁排序修复及独立 PostgreSQL 回归；保留快照、取消和提交原子性。
2. 同项目名称唯一的旧库预检与最小迁移、手动创建/重命名 409、生成候选去重/warning/类型冲突失败。此项是用户批准的 PRD R2 演进，不是对旧 R2 的追溯性否定。
3. EventBus 订阅积压上限、慢 WS 连接显式关闭与子任务释放；沿用生产 REST 重建，不加事件表或任务重试。
4. 四份已批准模板的部署输入整理、通过正式设置 API 部署及安装后/重启后逐字回读；不重新创作模板。
5. 本文规定的真实剧本、两段视频、真实三次资产提取、§3.3 九行全矩阵、§3.2 修订竞态、§6.1 取消/恢复/互斥与 §6.4 文件/trash 验收。
6. 必要的正式回归、一次性验收装置、发布操作说明与证据。装置先独立验收，再消费其结果。

### 范围外

- PRD §0 全部围栏：资产别名/合并、候选分镜版本、分镜增删/拆分/合并/排序、风格/模板版本、generation_runs、continuity、音频、context loop、fl2v；generation_mode 仍只使用 ref2v。
- 拼接成片、字幕、配音、口型对齐、童年回忆段、任意剧本/seed 的审美保证、模型训练、工作流重设计与时长误差校准。
- 自动重试任务、心跳数据库故障宽限期、后台补偿队列、新全局锁/锁表/锁文件、依赖容器化改造、事件持久化、分页/搜索、认证或公网部署。
- 清理用户原有数据库、媒体、GPU 进程或 C011 历史证据；本轮规划仅改文档，不执行迁移、生成或测试。

### 现状与影响

规划核对基线 `c0830c3`，最后 C011 实现为 `e4605bb`，归档提交 `7597d47`。AGENTS 用户既有改动与未跟踪 `.work/` 不属于本 change。

| 当前代码/文档证据 | 影响 |
|---|---|
| `generate_clip_video.py` 在 `_discover_and_lock_enabled_assets` 后锁 Clip；`clip_video_commit.py` 在 Task/Clip 后锁 Shot/Asset | 存在反向取锁条件；尚未运行本 change 的死锁探针，不宣称已经复现 |
| `assets.py` 更新先 Asset 后更新 Shot/Clip；`shots.py` 与 `clips.py::_load_selection` 先 Shot 后 Asset；`gen_shots.py` 覆盖也涉及相同实体 | 不能只交换两个查询。修复须覆盖本文 §2 的相邻路径与真实锁等待，不顺手重构业务服务 |
| `gen_assets.py::_merge_generated_assets` 只按 existing_id 判断插入；`assets.py::create_asset/update_asset` 无名称冲突合同；当前两条 Alembic 迁移与 ORM 无资产名称唯一约束 | 必须分别交付 API/worker/迁移；不能只用前端校验或先查再插代替数据库竞争保护 |
| `schemas/assets.py` 手动名称已经 strip；`services/gen_assets.py` 模型名称仅 StrictStr | 在模型输入边界补同一规范化；不把模板的“2–8 字”擅自变成 API 新限制 |
| `tasks/events.py` 为无界 Queue + put_nowait；`api/tasks.py` 每轮建立 receive/get 子任务并等待 send_json | 需要容量、溢出通知、发送阻塞取消和同时完成时的完整处理；不得只加 maxsize 后让 QueueFull 反向打失败任务 |
| `main.py` 已有单 worker advisory lock、running 恢复、启动及每日 trash；`queue.py` 心跳异常导致 handler 取消/失败 | 复用生产生命周期；本 change 验证现有失败规则，不新增心跳重试 |
| 正式模板 GET/PATCH、四条生成入口、媒体 ID 路由、Director/TasksPage 均存在；仓库未发现四模板完整部署输入包或 C012 部署驱动 | 后续 task 交付部署输入与单一驱动；迁移占位和 C011 人工模板不能作为正式模板 |
| `TRACEABILITY.md` 已有两条 C012 模板行、九条 §3.3 行、恢复/取消/快照行及 C007–C011 回归 | 使用现有覆盖，缺口新增 C012 行。旧 R2 行注明演进，不把旧通过结果当新去重证据 |
| NOTES 有 C007/C009 正式模板和真实 GPU 历史事实；前置依赖清单仍含 C006 时期旧“待提供” | 以 PRD、D-014 和原批准正文为准；历史通过不等于本轮环境已就绪 |

### 风险

- 锁排序修复若丢失锁后重读，会以旧引用/修订错误标记 fresh；若新增项目级串行锁，会改变设置/其他项目的并发行为。
- 同名约束可能使旧库升级失败；自动改名或合并会损坏资产引用，故必须显式预检、无数据自动修复。
- 有界队列若静默丢事件、阻塞 publisher 或遗漏发送子任务，会造成观察错误、内存/任务泄漏甚至业务任务误报 failed。
- 手工摘要、mock GPU、直接 DB 种业务数据、旧库结果、viewport 等效缩放均不能冒充真实发布证据。
- 模型输出可能产生同义不同名、额外人物或错误动作；本 change 没有别名机制，真实失败如实阻塞该项，不循环抽取直到通过。

## 外部依赖

本节是唯一外部依赖阻塞清单。规划可进行；任何尚缺证据的实施门槛只能由对应 task 的现场结果解除，不能预填通过。

| 依赖与来源 | 开工/验收门槛 | 当前证据 | 缺失项与状态 |
|---|---|---|---|
| PostgreSQL，PRD §12.4 | DB task 前可创建隔离库；独立连接与 Alembic 可用；真实发布库/回归库/迁移旧库夹具彼此分离 | NOTES 有历史显式 DSN/新库流程；源码 SQLAlchemy/asyncpg 已存在 | 本轮未连接；**阻塞 DB 验收，待 T01 现场核验**。不得默认使用 backend/.env 的业务库 |
| Z-Image、MiniMax API workflow/绑定，PRD §12.1 | 非 GPU 开工仅需本地 loader；真实生成前 `/object_info` 精确支持当前绑定节点、模型/LoRA、duration 和可变参考数 | 仓库 `backend/workflows/zimage.json`、`minimax_h3_ref2v.json`、两份 TOML 存在；C010 已批准 LoRA 单叶变化 | 未现场核验 Comfy 节点/权重；**阻塞真实生成**。不猜地址、模型文件或修 hash 常量 |
| 四份正式模板，PRD §12.2/§7，D-014 | T17 交付前恢复并核对批准原文；T21 完成正式 API 安装及两次逐字回读后方可进入 T22 | C005 `openspec/changes/C005/spec.md` §5.1 有 script2assets 正文；C006 `openspec/archive/C006/spec.md` §5.1 有 script2shots；C007 spec/NOTES 记录单一 zimage 2770 字符；本机 `C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md` 存在，C009 spec 指明此批准来源 | zimage 的完整批准正文尚未恢复/逐字核对；其余正文与部署文件也未完成本轮比较。**阻塞正式模板输入交付及真实验收**；字符数不是内容证据，不重新创作替代 |
| vLLM sleep/wake/structured chat，PRD §12.3 | 真模型步骤前核对实际模型/进程、sleep mode、health、sleep(level1)/wake/is_sleeping；无其他推理工作 | NOTES 有历史模型与启动命令及成功记录 | 本轮未运行；**阻塞真实模型步骤**，不调整显存参数碰运气 |
| Comfy/vLLM 地址与占用，PRD §12.4 | 真链路前确认实际配置/HTTP health/Comfy queue 及归属；记录后端库名/DATA_DIR/DEBUG/工作流 | 只有配置机制与历史端口证据 | **阻塞真实链路**；健康端口不能替代模型注册与队列归属检查 |
| C011 前序（非 §12 新依赖） | 归档且最后实现受测 | `openspec/archive/c011/spec.md` 与当前代码，52 项已归档；任务重连/双主题已交付 | 已满足前序。原生全页 200% 与动态 reduced-motion 沿用其明确未验证边界，不新增 M6 视觉硬门槛 |
| 剧本/验收工具（非 §12 新依赖） | 使用 §6 原文；T02/T19 装置必须先完成 | 用户已确认“宿舍＋球馆”和两个动作段；已有 pytest/Vitest/httpx/websockets/asyncpg/PyAV 可复用 | 本文规划的 C012 驱动尚不存在；**阻塞其消费者，待前置 task 交付**；工具安全层拒绝时不可换通路绕过 |

## 1. 约定与证据边界

- PRD（含本轮批准的 R2 补充）优先；遵守 DECISIONS D-001–D-015。复用既有依赖清单、同源 API/media/WS、显式事务、Task 三成员 payload、全局 request_id、REST 权威重建、事务后事件、原子 done 与同步文件补偿。
- C012 只新增资产名称约束所需 migration；不改两条历史 migration 的 seed/正文，不做模板版本化。旧 C005 插入语义仅在本轮新 R2 覆盖的名称冲突分支演进。
- 正式回归文件保留；没有修改既有测试的授权。新增用例先登记追溯。若现有断言与新 PRD 确实冲突，保留失败并上报具体用例，不改弱、不特判测试输入。
- 本地 `.work/c012/acceptance.py` 是计划交付的唯一验收 CLI；不复用 C011 库/fixture，不再建第二套 PowerShell 启动器。应用不增加验收 endpoint、debug mutation 或 production-only bypass。
- 命令默认根目录 `D:\ai_drama_studio`；pytest/Alembic 在 `backend`。环境由 T01 明确提供 DATABASE_URL/DATA_DIR，日志不打印凭据。本文列出的新命令/测试路径均为计划交付，当前不存在不算实施通过。
- 每个 task 只跑受影响检查；阶段 G1 与最终 G2 才跑完整前端 test/build、隔离完整 pytest、Alembic。同输入证据按 AGENTS 复用；若中途广泛修改 DB/队列/lifespan/公共协议，提前完整回归并记录理由。失败保留 raw stdout/stderr/真实 exit；修复装置根因后可另批运行相关检查，不把 stderr 非空当失败，不静默过滤、不重放失败生成。

### 1.1 T22 阻塞期间的独立工作（需求方本轮批准）

T22/AC-17 仍是发布必过项：同剧本第二次新增0、第三次仅新增陈宁人物一项且原集合不变。task #1–#3 的失败证据保留；单次诊断成功不代替三次正式验收。不得为放行而修改剧本、正式模板、R2或验收断言，也不得循环生成直到通过。

本轮只解除无业务依赖的串行排队，不豁免验收：

- T22 线：继续已授权的一次被动采集诊断，保存真实请求/响应、解析资产、合并前后数据与任务关联；根因未定或产品规则需改时保持未完成并报告。不因其他线推进而追加诊断次数。
- 示范线：T21 完成且当前真实外部依赖满足后可进入 T23；T23→T24→T25→T26 的内部依赖不变，使用独立示范项目，不修改 T22 检验项目。若真实提取缺失该线所需人物/场景，该线仍停止，不手工补资产冒充真实提取。
- 受控线：T02、T16、T19 已完成后可独立进入 T27，再按 T27→T28→T29→T30 验收；使用独立隔离 PostgreSQL、DATA_DIR、端口及外部服务 stub，不依赖 T22 的新增角色或 T26 的视频。受控 fixture 不进入真实 M6 数据库。
- T31 明确等待 T22、T26、T30 均完成；T32–T36 按原收口顺序继续。T22 未通过不能勾选 AC-17、T31 或最终收尾，也不能发布/归档 C012。

Luna 负责协调，最多另派一名执行者负责受控线；每位执行者同一时刻只执行其明确分配的一个 task。此授权仅是本 change 的任务调度例外，不放宽单 task 范围、失败保存、测试和安全规则。一条线失败只阻断其依赖后继；若证据指向两线共用的生产、模板、外部资源或数据隔离缺陷，暂停所有受影响线。

所有真实 vLLM/Comfy 调用（含 preflight sleep/wake/free）只能由 Luna 统一串行安排；不得让两个数据库的 worker 同时使用真实 GPU。诊断采集器结束后恢复并核验正式服务连接，才能记录示范链路的生产通路证据。CPU/受控线不得连接、重启、清理或更改真实服务。

并行时划分文件责任：Luna 独占 spec/tasks/TRACEABILITY/NOTES 的回填、共享 acceptance.py 修改、真实服务与 git 提交；受控执行者只拥有 T27–T30 明列的新测试文件和其独立批次证据，不修改生产代码、共享装置或他人文件。需要这些共享改动时先交还 Luna 串行处理。共用装置的固定输出文件须串行生成并立即另存至各 task/batch 证据目录，不并发覆盖；提交只暂存本 task 的明确文件，不使用 git add -A。不得新增调度框架、锁文件或第二验收 runner。

## 2. 锁顺序修复

### 2.1 必须关闭的交错

L1：上一视频任务进入正式提交、另一会话对同 Clip 入队；L2：提交与资产改名/描述/切 current/删除（含仅槽位引用资产）；L3：提交与分镜文本/绑定编辑；L4：片段 create/槽位修改/删除与关联资产或分镜编辑；L5：gen_shots 覆盖与上述 API。每类都验证两种先持锁方向，不以串行调用代替并发。

默认采用现有行锁的共同偏序：需要 Episode 的操作先 Episode；随后需要的 Asset 按 id 升序、Shot 按 id 升序、Clip 按 id 升序，再获取该目标关系/媒体行。只对实际需要的行取锁，不把不存在的依赖加入路径。视频提交保留其 Task 条件终态保护，但把源 Asset/Shot 取锁移到 Clip 之前；原视频入队 Asset→Clip 及设置快照锁合同保留。Task claim/cancel/projection 的 Task→Clip 与业务提交一并核对；不在持 Clip 时追加等待另一条已有 Task 的排他锁。

受影响模块限定为 `services/clip_video_commit.py`、`services/assets.py`、`services/shots.py`、`services/clips.py`、`tasks/gen_shots.py`，以及为这些路径消除同一锁环直接必需的 `tasks/gen_assets.py` 和 `services/generate_clip_video.py`。不改 GPU core、工作流、缓存算法或队列调度策略。涉及 JOIN 的 FOR UPDATE 必须明确锁哪些表，不能误把关系行提前纳入反序。

锁前只能发现候选 ID，取得锁后仍须读回并校验归属/引用/修订；不得用锁前 ORM identity map 值生成快照或完成判断。合法的先后提交结果服从现有 404/409/422、stale/changed 或失败语义，不增加静默重试。若发现此偏序之外会改变公开行为的冲突，停止报告，不能扩大成全局锁方案。

### 2.2 证据

锁后结果按下表逐项判定，不能只验证“未报错”。每次比较相同输入分别串行执行两种顺序所得的业务结果；并发结果必须完整等于其中一个合法顺序，不能拼接两个顺序的部分结果。UUID/时间等新生成值不参与跨批相等比较，但同批的 ID 引用、行数与文件内容必须闭合。

| 交错 | 业务结果观测 |
|---|---|
| L2 资产编辑/换图 | 编辑恰一次 revision+1，绑定 Shot changed、关联 Clip stale；旧快照 take 可保存，不能清除此状态；非当前媒体不被误删 |
| L2 资产删除 | 在产物已生成且目标 Clip 仍存在的本交错中，两种顺序均保留该 take/formal；删除后 asset_id 置 null、槽位快照/override 保留且 Clip stale，提交不得将其清回 fresh；资产图片进入 trash、与该资产无关的媒体不动 |
| L3 分镜编辑/绑定 | 实际改动恰一次 revision+1、Shot changed、相关 Clip stale；提交的旧快照不改写新绑定/文本，失败无部分 take |
| L4 片段/槽位/删除 | create 成功恰一 Clip 且 Shot 占用不重复，冲突响应保持 409/422；slot 更新只改变请求字段及既定修订；删除成功则该 Clip/关系/媒体全移除且源 Shot 保留，失败不留半组关系 |
| L5 分镜覆盖 | 覆盖成功时仅本集旧结构完整删除、新结构完整写入且 marker 为快照修订；结构在锁前已改变导致现有检查失败时，保留该时刻结构及媒体、无新分镜/marker；不得成功返回混合旧新结构 |

T03 先记录完整锁边、包含条件及现有测试断言；T04–T08 分模块修复。诊断必须调用实际生产 service/commit，在真实 PostgreSQL 独立连接/进程下用确定性屏障暂停在真实取锁语句之后，以 `pg_stat_activity/pg_locks/pg_blocking_pids` 只读观测。允许为该测试连接设置有界 statement/lock timeout 使坏实现确定退出，不能修改生产 timeout 或用超时通过冒充无死锁。L1 成功目标是两业务操作完成、前一产物完整、后一任务精确一条；其余按合法业务赢家判定，SQLSTATE 40P01、连接泄漏、无原始结果均不通过。

## 3. 资产名称唯一性与 R2

### 3.1 数据/API

名称采用 Python `str.strip()` 的首尾空白语义，内部空格、大小写和 Unicode 字符原样保留；不做 casefold、NFKC、同义词/人物别名推断。同项目跨类型也不得同名，不同项目可以同名。schema 使用 `UNIQUE(project_id,name)`；API 与生成边界负责规范化，数据库处理并发竞争。

旧库迁移前按规范化值扫描：列出 `(project_id, asset_id, 原name, 规范化name)` 冲突组；空白或尚未规范化名称也报告，迁移不写回它们。操作者使用既有正式 PATCH 显式处理后，重新执行迁移；预检失败时 alembic version、全部资产及引用/媒体不变。无冲突且已规范化的库保留所有 ID/内容，只新增唯一约束；空库正常升级。回退只删除本次约束，不删业务数据。并发升级要求停止该库写入者，不声称在线无锁迁移。

POST/PATCH 撞同项目另一资产名称统一 HTTP 409，body 精确 `{"detail":{"code":"conflict","message":"资产名称已存在"}}`；无部分 revision/changed/stale/引用/文件变动。自身规范化后同名是 no-op，沿用已有 description 变化规则。空名、类型/请求形状错误、U+0000 或数据库唯一索引不能存储的超长名称为结构化 422，不暴露原始 DB 异常；生成侧新增候选的相同不可存储名称使任务 failed；合法 existing_id 的返回名称不参与改名或名称冲突判定，封闭响应结构与字段类型校验仍执行。只识别预期名称约束/索引错误，不把所有 IntegrityError 都伪装成撞名。

### 3.2 生成事务

1. 完整模型响应经现有封闭 schema 验证；真实属于本项目的 existing_id 优先复用，不按返回名字重命名，不改变类型/描述/revision/cache/下游。
2. null/非法/跨项目/超出 PostgreSQL INTEGER 的 existing_id 进入新增候选；非法 ID 不用于越界 SQL，仍记录原 ID warning。
3. 候选按原响应顺序决定胜者；规范化同名同类型相对已有行或本批首项跳过，保留首项内容；同名不同类型则整批失败。warning 至少包含 task_id、episode_id、project_id、响应位置、规范化名称、被复用 asset_id（本批行在 flush 后可得）、原因；不得只有“发生错误”。失败时已发 warning 是诊断记录，不宣称相应业务已提交。
4. 手动写入与生成竞争由唯一约束收敛；生产使用 PostgreSQL 已有原子冲突插入能力（例如指定该唯一约束的 `ON CONFLICT DO NOTHING RETURNING`）再读既有行判定类型，不做整任务重试、不用新项目全局锁。UPDATE 改名冲突直接 409。不能只“查不存在→裸插→吞唯一异常”。
5. 新资产、快照 script_revision 成功标记与 task done 为同一提交胜方；中途类型冲突/异常/取消回滚所有本批新资产和 marker。已有资产与下游不动。队列 Task failed/error 的保存沿用既有失败通路。

## 4. 有界任务观察与失败纪律

- 每个 EventBus 订阅队列最多保存 **256 条待消费事件**；正常顺序与五字段事件体不变。向已满订阅发布下一事件时将该订阅标记溢出、从发布集合移除并通知其 WS owner；其他订阅照常收到事件，publish 不等待慢网络。最多允许 owner 另持一条正在发送的事件，不新增无界积压容器。
- WS owner 在溢出或单次发送超过 **10 秒**时取消并 await 该连接的 send/receive/get 等子任务，记录含原因的 warning，显式关闭 WS `1013`；不能让 QueueFull/发送超时使已经提交的业务 Task failed。断开后的 backlog 可随订阅释放，不在仍声称健康的连接中静默丢弃；不做服务器历史重放。
- 同一轮 receive/get 同时完成时，两者都要观察：disconnect 优先清理；正常 receive 不能吃掉已取出的事件。unsubscribe 幂等，正常断开/溢出/发送异常/应用退出均没有孤儿任务或未取回异常。
- 前端继续使用现有断线提示和重连策略；重连先 socket+buffer 再 REST 列表/展开详情恢复，不重发取消/生成 POST。无需新 WS schema、新 banner 系统或轮询。
- 心跳 DB 错误仍执行现有 handler 取消/任务失败纪律，不引入重试/宽限。DB 不可用时不伪造已持久化 failed；恢复连通后通过生产重启恢复 running→failed("server restarted")。所有相关资源清理均需真实结果。

## 5. 四模板部署

计划文件：`backend/deployment/templates/{script2assets,script2shots,zimage,minimaxh3}.txt`，UTF-8 正文；另有 `backend/deployment/README.md` 说明批准来源和安装命令。禁止提取 Markdown 外围说明混进模板；换行/末尾换行采用批准正文，不在比较前 strip。长度、文件名或 hash 相同不能替代逐字比较。批准正文缺失时按外部依赖阻塞，不重新写一份“等价模板”。

生产部署入口计划为 `python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode install|verify`（backend CWD）。它是显式部署 CLI，不在 lifespan 自动覆盖设置。CLI 使用已有 httpx 与现有模板变量/封闭校验能力，不增加配置框架、版本表或第二清单。

- install 在任何 PATCH 前读全四文件，检查精确 key 集、非空/非 `[占位]`、各自必需变量集合；缺失/重复/未知 key 或解码失败即非零且 PATCH=0。
- 基线 GET 必须精确四 key；按 script2assets→script2shots→zimage→minimaxh3 各 PATCH 一次，再集合 GET 逐字比较。单步 HTTP/协议失败立即非零、不重试、不补默认正文，不运行后续 PATCH；已经成功的独立提交如实留在库中，并报告成功 key/失败 key，不谎称四项原子回滚。
- verify 只 GET，逐字比较四 key、content，无 PATCH；安装完成后、同一库后端重启后各执行一次。重复显式 install 是操作者的部署动作，不能在失败后由装置自动调用。
- 模板在任务入队快照中精确可追溯；不得因安装驱动存在就宣称四链路已经消费。真实 M6 使用默认 `create_app/app.main:app`、生产 handlers、真实客户端和绑定；不启用 C011 人工模板或 handler barrier。

## 6. 真实 M6 输入与验收路径

### 6.1 冻结首轮剧本

下列为需求方提供剧本的“宿舍＋球馆”范围，止于乔彦茜僵住，童年回忆不纳入；不为追求自动测试通过重写人物名或动作。T19 将其逐字保存为 `backend/deployment/m6-script.txt` 并检查当前 SCRIPT_CHAR_LIMIT，超限时明确报错而非截断。首轮无需完整 60 秒成片，只要求从该集选择两个合法片段。

```text
下午五点多。光丰大学女生宿舍302房。
芳嘉蔓（从外面走进宿舍大嚷）：喂，我的彦茜小姐，你就不能吃快点吗？球赛就要开始了，看不到我的偶像为你是问！
乔彦茜瞥了一眼从外面奔进来的芳嘉蔓，没声好气地说：拜托，才几点，我的姑奶奶，八点的球赛现在才五点多！
乔彦茜继续吃饭。
睡在芳嘉蔓上铺的舍友：什么球赛？
芳嘉蔓：羽毛球。
宿舍里七嘴八舌：那个高富帅出场吗？
如果高帅才出的话，他肯定出。
人帅球技好，不晒晒咋行！
芳嘉蔓：听说这次是决赛，高富帅对高帅才！
睡在芳嘉蔓左边床的舍友：太有看头了，简直堪比演唱会！
乔彦茜：我看那高富帅也没啥了不起的，帅又不能当饭吃，钱是他老爸又不是他自己的，女朋友一大堆，也不缺你一个。每次看球回来，输了，你比别人女朋友哭的还厉害；赢了，你比别人还高兴。真不知你图个啥！非典久了，人都会有免疫力，可你看球这么久了，不但没免疫力连抵抗力都降低了。
芳嘉蔓：你这宅女，我估计你一睹他的风采后比我还激动。
乔彦茜：我才没你那么疯呢！这种人换女朋友像换衣服那么快，跟着他他呀流眼泪多过喝水！只有你才那么痴情，天天都在打听他的踪迹。直接去表白嘛，这样落得多辛苦，别人又不知道。
芳嘉蔓：切，你是吃不到葡萄说葡萄酸！我可是情愿坐在宝马里哭也不愿在自行车后笑！至于表白嘛，还酝酿不够。
乔彦茜：好了好了，你的妆化好没？那么多人，他看不到你的，除非你是凤姐。给赶快走吧，再不走比赛开始了，错过你的杰哥哥可别怨我！
两人边说边笑走出宿舍，往羽毛球馆前进。
羽毛球馆里，人声鼎沸。
“啊— —”
“啊— —”球场里爆发出一声声的尖叫，这些女的声音从开场到现在没有一刻是停下来的。加油声一浪高过一浪。
乔彦茜：天啊！比赛结束后估计耳朵已经不是自己的了。这些女生的哪根神经搭错了，什么球都尖叫，安静一会儿会死啊！
芳嘉蔓：你终于发现问题的严重性了啊？这些女生根本不是来看球的。你看看球场上，哪里找得着几个男生啊？
乔彦茜：听你这么一说，还真是啊，整个球馆里挤满的几乎是清一色的女生，进不来的还有爬栏杆的。汗啊！
芳嘉蔓（不停的挥舞着胳膊）：哇，你看，快看啊，高富帅出场了，哇塞，真帅呆了！
乔彦茜却定格了，任凭嘉蔓怎么推她都没反应。
芳嘉蔓（转头对着乔彦茜）：说你看了高富帅比我还激动没错吧，激动得连反应都没了！
乔彦茜没在意芳嘉蔓在说什么。
```

### 6.2 真实操作

1. T21 在全新生产等价库仅迁移后部署四模板，安装后/重启后核验通过。T23 从实际浏览器创建项目、选择明确记录的风格、创建一集并录入全文；正常业务输入/按钮操作允许，后台直接 SQL 种资产/分镜/片段、手改模板或补媒体不允许。
2. 完整剧本生成资产。真实模型三连跑在独立的同剧本检验项目执行：第一次得到集合 A；第二次原文不变，要求 ID/name/type/description/revision 集合与 A 相同且新增数 0；第三次仅追加“球馆内，工作人员陈宁走到芳嘉蔓身边递给她一张入场券。”，要求原集合 A 不变、只新增人物陈宁一项。记录三次不同实际任务与逐字模型请求快照；失败不重跑旧任务或用预置模型 JSON 替代。该检验项目不混进发布示范集。
3. 为示范集实际需要的参考人物和两个场景通过正式生成按钮出图；至少人物、场景各一条真实 Z-Image 任务。选择 current 图，通过正式生成分镜按钮生成整集，人工核对分镜包含两个指定动作段、资产引用可区分、每个入选片段连续且同场景。若模型缺失所需动作，本轮记录失败，不使用数据库补分镜。
4. 在导演台选择两段连续分镜并 preview/create：A 为芳嘉蔓进门催促、乔彦茜抬眼回应后继续吃饭；B 为芳嘉蔓指向出场球员、乔彦茜由平静变为僵住。每段参考 1..9，默认建议时长按 R6，actual_duration 记录真实值。两条任务都经生产 queue→真实 vLLM/Comfy→正式 MP4→take/current；任务中心 UI、REST、独立只读 DB 与媒体一致。
5. 视觉判定人工逐项写“操作→观测值→通过/失败”：人物 A/B 与所选参考可区分、服装/身份无互换；片段 A 按先后出现入门/催促姿态、抬眼、继续吃饭；片段 B 出现指向球员与乔彦茜静止反应；两个地点分别可识别为宿舍/羽毛球馆。额外肢体、主体消失、地点错误、缺失规定动作任何一项均记失败。无配音/字幕/精确口型要求，不把无音频判失败。审美偏好另外记录，不保证每个 seed。
6. 选择任一 take，切 current 后再读回；记录资源结束状态、Comfy queue 空、vLLM sleeping、临时目录无本轮残留。保留示范集及最终媒体，不执行业务库清空。

## 7. M6 矩阵与异常

每一格独立记录精确初始实体 ID/数量、revision/status/freshness/current、媒体路径与 bytes；失败格不得依靠上一格的污染状态继续。受控矩阵只使用隔离库，可重复构建合法 fixture；至少一次真实示范集的编辑→stale→新 take 分支见 AC-23。

| PRD §3.3 操作 | 必须观测的变化与不变量 |
|---|---|
| 编辑剧本 | script_revision +1，生成修订 marker 保留；Shots/Clips/Files 逐项相同；UI 两类基于旧剧本角标 |
| 重新生成资产 | 按新 R2 只新增候选；原资产不改；Shots/Clips/Files 逐项相同 |
| 重新生成分镜 | 有影响时先预检/确认；只有生成成功后本集旧 Shots/Clips/Video 行删除、对应媒体移 trash，新 Shots 与模型返回一一对应；其他集不变；模型失败旧结构/文件完全不变 |
| 编辑资产/换 current 图 | 名称/描述/current 三个触发分别验证；资产 revision +1，绑定 Shots changed、相关 Clips stale；旧文件不删；no-op不增加修订 |
| 删除资产 | 该资产/图片行删除，绑定解除/Shots changed、Clips stale；Slots 的 id/no/name/type 快照及 enabled 不变，asset_id=null；资产图移 trash；无 override 的启用槽位触发 R10 |
| 编辑分镜文本/绑定 | 分别验证文本、加绑定、删绑定；目标 revision +1/changed，相关 Clips stale；其他实体内容/文件不变 |
| 编辑风格/模板 | 资产图/视频下次入队按 R4 改变 input_hash 并重建对应 prompt；资产/分镜提取下次入队使用新正文而 input_hash 仍为 null；在途 payload 不变，现有 Shots/Clips/Files 不追溯改变；不以 install 重置用户编辑 |
| 删除片段 | 目标 Clips/ClipShot/Slot/Video 行删除，原 Shots 保留并可再选；视频/override移 trash，其他片段/文件不变 |
| 片段成功且修订未变 | 一条新 take/formal，source Shots normal/Clip fresh；无其他 active 时 ready，有 queued/running 时按既有聚合；不覆盖原 current，首 take 才自动 current |

完成反竞态覆盖 Clip、Shot、Asset 任一 revision 变更：旧快照产物保存，changed/stale不清除；资产运行中被删除的路径服从该任务类型现有失败/已删槽位规则，不能伪装成 revision 未变。

错误矩阵保留既有约定：R1 409；impact token 缺失/过期/不匹配 409；preview/create 的连续、跨场、双场景、时长、>9引用为422；生成复检 R5/R5a/R10 为 **202 +立即failed Task**、未claim/外调，不能改成409/422；current删除409、未知资源404；模型/Comfy错误使Task failed且完整原因、无retry。Task三成员payload、ID/seed范围、默认DEBUG隐藏、启用DEBUG逐字段投影和路径穿越防线均复跑对应既有用例，不扩展接口。

恢复/资源：真实 backend 进程退出后，同库重启使遗留 running failed("server restarted")，queued只消费一次；第二进程拿不到同库advisory lock必须退出且无第二worker。运行中取消使用正式无body POST，Comfy interrupt只允许确认本轮唯一owned prompt后执行；取消与完成只有一个持久化胜方，不能 canceled且有本批业务产物。

trash 使用生产启动清理与 `run_trash_cleanup_loop`，保留恰好cutoff与较新的文件，删除 mtime严格小于cutoff的文件；清理不触碰trash外有效媒体，错误可见且不重试。定时分支可在受控装置仅替换计时等待，不改生产清理函数/文件通路；真实启动分支另用独立进程验证，不能把加速定时器称为真实等待24小时。

## 8. 验收装置与命令合同

T02 交付 `.work/c012/acceptance.py` 的 `selfcheck`、`locks --case L1|L2|L3|L4|L5|all`、`migration`、`names`、`ws`、`cascade`、`recovery`、`trash`。T19 扩展同一文件的 `preflight --real`、`verify-inputs`、`observe --real`，不创建第二个runner。各命令失败非零、成功0，证据写 `.work/c012/<task>-<batch>.*`；保存 command/cwd/实际受测commit/显式非敏感环境/子进程PID/原始stdout/stderr/exit及资源结束状态，不新增hash或审计注册系统。

| 装置 | 事件/存储/进程通路 | 与生产的差异及证明边界 |
|---|---|---|
| 锁与名称并发 probe | 真实service/commit、PostgreSQL独立连接/原事务、真实临时PNG/MP4；真实SQL之后的观测屏障，独立DB只读核验 | 调度被屏障控制、媒体可离线生成，证明锁等待/提交/文件一致性；不证明真实GPU或浏览器 |
| 受控任务/矩阵 | 生产create_app/lifespan/queue/handlers、独立后端、正式HTTP/WS和DATA_DIR；本地HTTP/WS stub仅代替vLLM/Comfy端点 | 不替换业务handler或EventBus，不手填Task事件账本；证明真实调用/存储/进程链，不能证明远端模型质量 |
| WS慢消费者 | 生产EventBus与实际ASGI websocket route；受控ASGI send阻塞精确触发发送背压；另有原生网络WS重连检查 | ASGI发送闸门不等于TCP拥塞；只证明应用容量、超时与子任务释放，网络检查证明真实路由/客户端恢复，两者必须分别记录 |
| migration旧库 | 独立DB迁移到旧head后构造旧schema允许的数据，调用真实Alembic迁移并独立回读 | 仅旧库兼容预检fixture可直接SQL写入；不得作为M6业务创建或正式模板部署证据 |
| 恢复/清理 | 生产lifespan、真实进程终止/重启、advisory连接及文件树 | 可控handler客户端和mtime/计时等待仅用于确定性失败/边界；不能宣称真实GPU复苏或24小时长跑 |
| 真实M6 | 默认app/handlers、正式UI/API/WS、真实PostgreSQL/vLLM/Comfy/工作流/DATA_DIR；observer仅被动读取/记录 | **不替换任何生产事件/存储/生成通路**。只有这个通路和人工播放能支持真实模板消费/视频结果；独立DB回读不代替页面真正发起的详情GET |

装置自检必须证明失败会非零、子进程启动失败不继续、stderr+exit0不被误判、数据源身份可从独立DB与后端配置对应、shutdown后本轮端口关闭/连接和子任务释放。跨 asyncio.run 不能复用未dispose的engine；同一个fixture动作的异步工作在同一loop内完成。OpenAPI只核HTTP paths，WS以实际连接验证。没有浏览器能力不得伪造操作或通过DevTools受阻后旁路注入。

## 9. 验收标准

每条均需标注实际用例ID或人工证据；下列只有期望。多条件为全部满足才通过。

| AC | 风险 | 触发条件 | 观测点与期望值 |
|---|---|---|---|
| AC-01 | [常规] | 完成本轮实现与计划范围核对 | diff每项归属task；仅资产唯一约束新增迁移；无§0围栏/新队列/模板版本；既有测试无M/D；spec、checkbox、trace、commit一致 |
| AC-02 | [跨进程] | T02装置自检各成功/失败/清理分支 | 实际命令/exit对应，失败非零无后续动作；stderr+0成功；DSN不泄露；生产通路与替代边界分别记录，owned进程/监听/连接全部释放 |
| AC-03 | [跨进程] | L1同Clip提交与新入队，两种持锁方向 | 真实锁等待可见；无40P01/无timeout；前task done、恰1新take和formal，后请求202且恰1queued任务；无误入trash/丢产物；payload为锁后快照 |
| AC-04 | [跨进程] | L2–L5逐类双向交错 | 按§2现有业务赢家形成串行等价结果；无死锁/泄漏；修改后旧产物不得清stale/changed；删除/覆盖路径无部分引用或孤儿文件；request_id/取消合同保持 |
| AC-05 | [事务一致性] | 旧库分别有精确重名、strip后撞名、空白/非规范名；另有合法旧库/空库 | 前四类迁移非零、冲突ID/名称可定位、所有数据与version不变；合法库升级成功且ID/内容不变、UNIQUE生效；downgrade仅移除本约束 |
| AC-06 | [外部输入] | 创建/改名同名、自身no-op、不同项目、大小写/内部空格、空白/NUL/超长索引输入 | 同项目跨类型同名409精确错误体；自身no-op修订不变；不同项目及大小写/内部空格差异可创建；不可存储输入422且无副作用 |
| AC-07 | [外部输入] | 生产gen_assets消费合法ID、null/非法/跨项目/整数越界ID、响应内同名同类型与跨类型矩阵 | 合法ID原行完全不变；无冲突候选各新增1；同名同类型新增0并warning；首项内容保留；跨类型整批failed、marker与下游不变；每次逻辑调用1且无retry |
| AC-08 | [跨进程] | 两独立请求同名创建/改名，及手动写与gen_assets并发 | 数据库最终每项目同名≤1；手动竞争精确一胜一409；生成遇同类型不新增、异类型failed；无unique异常泄露/整任务重试/半批marker |
| AC-09 | [跨进程] | 新R2去重成功/失败/取消与最终提交屏障交错 | 只有done+全部新资产+快照marker或canceled/failed+零本批资产+原marker；既有资产/下游不变；任务与文件/连接无残留 |
| AC-10 | [并发] | 单订阅停止消费，依次发布256和第257事件，同时另一订阅持续消费 | qsize从不>256；慢订阅被注销并显式通知owner；健康订阅按序收到全部257；publisher不等待慢send且不抛QueueFull污染业务 |
| AC-11 | [跨进程] | WS发送阻塞超过10秒、溢出、disconnect/get同时完成、正常关闭/应用退出 | 异常连接1013或已断开的既有关闭态；原因日志可定位；其send/receive/get全await结束、subscriber_count恢复基线；生产Task状态不因传输失败改变 |
| AC-12 | [并发] | 真实TasksPage展开详情后遭遇慢连接关闭，期间任务到终态，再自动重连 | 页面出现既有连接异常状态；socket-first后REST重建列表及详情与DB字段一致；生成/取消POST数不增加；无缓存running覆盖终态 |
| AC-13 | [常规] | 恢复四模板批准原文并交付部署输入 | 精确四key文件，正文与各批准来源逐字相同；来源可追到原文而非长度/摘要；未改历史seed/工作流；真实原文缺失时保持依赖阻塞 |
| AC-14 | [外部输入] | 部署CLI遇缺key、额外key、非法UTF8/占位/缺变量、HTTP失败或GET内容不一致 | 输入失败PATCH0；HTTP失败停止后续PATCH且非零；部分成功key如实列出；无retry/DB直写/default；verify全程PATCH0 |
| AC-15 | [跨进程] | 全新仅迁移库执行install、verify、同库后端重启、再次verify | 安装前4个占位key；随后两次GET精确4正式key/全文相等、无占位；实际后端库/DATA_DIR一致；重启没有自动覆盖模板 |
| AC-16 | [跨进程] | preflight --real及真实M6前/后的外部资源观测 | 当前模型、binding/节点/LoRA、地址及库身份有现场证据；sleep/wake可用；推理不跨组件重叠；无其他owned不明任务；结束queue空/vLLM睡眠/本轮temp0 |
| AC-17 | [跨进程] | 独立检验项目真实模型三次提取§6.2输入 | 首次集合A完整记录；第二次A逐字段不变新增0；第三次仅新增陈宁character一行、A不变；三个不同实际task done、真实请求/DB/warning可查，无手工补值或重跑掩盖 |
| AC-18 | [跨进程] | 示范集从真实UI录剧本至两视频 | 四task类型均由生产入口执行并实际消费各正式模板；至少人物/场景各一生成图，整集分镜含两动作段；恰2选定Clip各有≥1真实take、MP4可解码/通过ID媒体读取、actual_duration>0；UI/DB/REST一致 |
| AC-19 | [常规] | 人工播放AC-18两段并比较所选参考图 | §6.2第5项所有身份/场景/动作检查逐项真假记录，任一缺失即失败；无音频不判错，不拿mock/任务done替代视觉结论 |
| AC-20 | [事务一致性] | §7九行矩阵及其明确子分支逐格执行 | 对每格对比完整相关行/ID/revision/status/current和文件bytes，精确满足§7变化与不变量；无一个格以“已有全绿”跳过 |
| AC-21 | [外部输入] | §7错误矩阵及敌意ID/模型/媒体/DEBUG输入 | 409/422/404与202立即failed各按合同；错误体code/message都有值；非法输入无越界SQL/路径逃逸/部分副作用；完整task错误且无retry |
| AC-22 | [跨进程] | queued/running取消、成功抢先、心跳DB错误与进程崩溃后恢复 | 取消/完成一胜方；DB错误不伪报持久化成功；重启running全部failed(server restarted)，queued保留且每条claim/副作用一次；第二后端无锁退出/无worker；清理无连接/文件泄漏 |
| AC-23 | [跨进程] | 真实视频running后通过UI编辑相关Shot，再等旧任务完成 | 旧payload不变，新take存在；Shot changed且Clip stale；UI双维状态与REST/DB一致。另用受控用例覆盖Clip/Asset修订及无变更分支 |
| AC-24 | [跨进程] | 生产启动清理与受控每日分支面对过期/恰cutoff/新trash、IO错误 | 只删除严格早于cutoff项，trash外有效媒体bytes不变；IO错误有完整日志/失败不重试；应用退出停止loop；加速等待差异如实标明 |
| AC-25 | [常规] | G1阶段/G2最终回归、§1.1调度与报告 | 前端test/build、隔离完整pytest、Alembic upgrade/current/check、diff check都有真实0；实际计数不预设348/174；复用列受测commit和输入差异；报告含操作→观测、异常分支、限制及收尾三项；T22未通过时T31及收尾未勾选，独立线只按自身证据勾选，GPU串行及批次隔离记录可核对 |

AC-13 来源逐字核验与 AC-19 人物/动作视觉不新增自动测试：批准事实与语义视觉不能由相同实现自生成 expected 或固定像素证明。替代为原批准正文对照、实际PNG/MP4播放、截图/时间点和逐项人工签注。AC-01/25为审计，无新自动测试；其他专项不能因不适合UI自动化而免除对应层级回归。真实GPU命令也不并入普通pytest，以免全量测试耗GPU或修改示范集。

## 10. 追溯覆盖检查（spec 定稿后、tasks 编写前）

准确行名如下；本轮已先在 TRACEABILITY 登记新行，均是“计划，待实施”，不预填用例ID/通过结果。各AC一对一或明确复用；既有矩阵/协议行保留原测试ID，仅在实施后追加新证据。

| AC | TRACEABILITY准确行名 |
|---|---|
| AC-01、AC-25 | C012 范围与阶段回归及交付一致性 |
| AC-02 | C012 验收装置生产通路与生命周期 |
| AC-03、AC-04 | C012 生成提交与入队及编辑锁顺序 |
| AC-05 | C012 资产名称唯一约束迁移与旧库预检 |
| AC-06 | C012 手动资产名称冲突与输入边界 |
| AC-07 | C012 R2 生成候选去重与冲突失败 |
| AC-08、AC-09 | C012 资产名称并发与任务原子提交 |
| AC-10、AC-11 | C012 EventBus 有界订阅与慢连接释放 |
| AC-12 | C012 慢连接后的页面权威重建 |
| AC-13、AC-14、AC-15 | C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位 |
| AC-16 | C012 真实外部依赖与GPU资源归属 |
| AC-17 | C012 真模型三次资产提取 |
| AC-18、AC-19 | C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback |
| AC-20 | C012 M6 全级联矩阵 |
| AC-21 | C012 M6 错误与敌意输入回归 |
| AC-22 | C012 取消心跳失败与重启资源恢复 |
| AC-23 | C012 真实生成中的修订竞态 |
| AC-24 | C012 trash 启动与定时清理 |

AC-20同时回填已有九条`§3.3`行；AC-22同时引用既有`§6.1`恢复/取消/去重行，AC-23引用`§3.2 完成判定反竞态`行的完整行名与已有节点（以TRACEABILITY原文为准）。新聚合行是M6跨链路证据归属，不重写既有单位规则，也不重复制造已被schema阻止的非法状态。
