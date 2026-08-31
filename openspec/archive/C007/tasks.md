# C007 M3 资产出图 Tasks

执行纪律：严格按依赖顺序，一次只执行一个已指定 task；T0 外部门槛已于 2026-08-28 验证完成，Luna 可从 T1 开始。每项完成前须运行其命令并记录原始输出；不得修改任何既有测试，C006 已归档，其一次性测试修正例外已失效。新增测试只能归属本文标注的 TRACEABILITY 行。

- [x] **T0 外部依赖 gate：复核 API workflow 并验证真实 sleep/wake**
  - 依赖：无。
  - 交付/检查：
    1. 复核已转换的 `F:\ComfyUI\user\default\workflows\Z_Image_Turbo_官方工作流_api.json` 可直接作为 `/prompt.prompt`，且 SHA-256 为 `e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa`；原 `F:\ComfyUI\user\default\workflows\Z_Image_Turbo_官方工作流.json` 保持为 UI graph，不得作为 API object。
    2. 复核 API object 的正向 prompt、KSampler seed、唯一目标输出分别为 `6.inputs.text`、`3.inputs.seed`、`9`；任一不符即停止并回报真实节点，不修改 spec 猜测适配。
    3. 确认没有 running 生产 task 后，真实调用 vLLM `/sleep?level=1` 再 `/wake_up`，两次均为 200，且 `/is_sleeping` 分别观测到 true/false；确认 Comfy `/system_stats` 为 200。
    4. 在完成报告保存文件路径、格式判定、节点绑定、Comfy 版本和 HTTP 状态证据；不把 mock 或 OpenAPI“存在 endpoint”替代实际 POST 成功。
  - R：无；PRD §6.3、§8、§12.1、§12.3、§12.4。
  - 验收方式与命令：
    ```powershell
    $workflowPath = 'F:\ComfyUI\user\default\workflows\Z_Image_Turbo_官方工作流_api.json'
    $workflow = Get-Content -Raw -LiteralPath $workflowPath | ConvertFrom-Json -AsHashtable
    if ($workflow.ContainsKey('nodes') -or $workflow.ContainsKey('links')) { throw 'UI workflow is not an API workflow' }
    if (($workflow.Keys | Where-Object { $_ -notmatch '^\d+$' }).Count -ne 0) { throw 'API workflow has non-node top-level keys' }
    $workflow['6']['inputs']['text']
    $workflow['3']['inputs']['seed']
    $workflow['9']['class_type']
    if ((Get-FileHash -LiteralPath $workflowPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa') { throw 'API workflow hash mismatch' }

    $running = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/tasks?status=running' -Method Get
    if (@($running).Count -ne 0) { throw 'Running production tasks must finish before GPU gate verification' }
    (Invoke-WebRequest -Uri 'http://127.0.0.1:8001/sleep?level=1' -Method Post).StatusCode
    $sleepState = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/is_sleeping' -Method Get
    if ($sleepState.is_sleeping -ne $true) { throw 'vLLM did not enter sleeping state' }
    (Invoke-WebRequest -Uri 'http://127.0.0.1:8001/wake_up' -Method Post).StatusCode
    $wakeState = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/is_sleeping' -Method Get
    if ($wakeState.is_sleeping -ne $false) { throw 'vLLM did not leave sleeping state' }
    (Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -Method Get).StatusCode
    ```
    2026-08-28 实际结果：API workflow 结构、hash 与绑定检查通过，Comfy `/system_stats` 为 200；running task 为 0，vLLM `sleep` 为 200/true、`wake_up` 为 200/false，最终恢复 awake。本 task 已完成。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用（PRD §12 真实外部门槛不能由自动测试替代）。

- [x] **T1 交付 Z-Image binding 文件、静态加载器和 workflow hash**
  - 依赖：T0。
  - 改动清单：
    1. 只新增 `backend/workflows/zimage.json` 与仅含 `[comfy.zimage]` 的 binding TOML；API JSON 必须来自 T0 已验证文件，不加入 MiniMax/C009 节点。
    2. 实现单一 Z-Image binding loader：按 spec §2.1 验证 API object、点分 prompt/seed 路径、叶值类型、输出节点，并拒绝 UI graph、数组索引、未知/缺失路径。
    3. 当前 Python 支持下限为 3.10 且依赖清单没有 TOML parser；按 D-001 只在 `backend/pyproject.toml` 增加并直接使用成熟 `tomli>=2,<3`，不增加 requirements 或 stdlib/backport 双路径。
    4. 对原始 workflow bytes 计算 SHA-256 lowercase hex，返回只读 binding snapshot；不加 registry、签名、canonical serializer、热重载或第二份 workflow 副本。
    5. 为 loader 新增纯函数测试文件；不得修改 C001-C006 测试。
  - R：R4；PRD §3.1 R4、§8、§10。
  - 验收方式：有效 API graph 取得精确 hash/绑定；缺文件、非法 JSON、UI graph、坏 prompt/seed/output path、错误叶值类型分别抛出具体错误，无 fallback。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pip install -e '.[dev]'
    python -m pytest -q tests/unit/test_c007_workflow_binding.py
    ```
    2026-08-28 实际结果：editable 安装成功，T1 测试 `13 passed in 0.05s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `45 passed in 17.57s`。
  - 计划测试层级：纯函数。
  - 追溯行：`C007 Comfy 工作流绑定与诊断：API 格式、注入/输出路径、启动失败、workflow hash 与 /system/health`。

- [x] **T2 交付最小 vLLM sleep 与 Comfy HTTP/WS 传输客户端**
  - 依赖：T1。
  - 改动清单：
    1. 在现有 vLLM 传输边界增加精确 `POST /sleep?level=1`；保持 D-011，客户端不读取模板、不计算 hash、不解释业务输出。
    2. 新增最小 Comfy client，显式提供 health、connect WS、submit、history、view stream、targeted interrupt、free；URL 只来自 `COMFY_BASE_URL`，HTTP 非 2xx、超时、畸形 JSON/WS 均抛出真实错误且不重试。
    3. free body 固定 `{"unload_models":true,"free_memory":true}`；interrupt 接受显式 prompt id；客户端不选择业务 workflow/节点或保存数据库。
    4. 新增协议等价独立 HTTP/WS 进程测试，验证请求方法、path/query/body、关联 id、流式 bytes 和错误传播；不新增生产 demo/endpoint。
  - R：无；PRD §5 cancel、§6.2-§6.4、§8。
  - 验收方式：协议测试逐项记录调用；确认没有宽泛吞错、retry/reconnect、业务 prompt/schema 或地址进入客户端默认业务逻辑。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/task_system/test_c007_resource_lifecycle.py -k client_protocol
    ```
    2026-08-28 实际结果：定向测试首次发现协议夹具错误解析无 body 的 sleep 请求，修正夹具后 `1 passed in 0.34s`；新隔离 PostgreSQL 数据库迁移后完整 `pytest` 为 `46 passed in 18.09s`。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 GPU/Comfy 资源生命周期：cache miss wake/chat、提交前 sleep、WS progress/history 输出、取消 interrupt、finally free，且 vLLM/Comfy 不并发`。

- [x] **T3 把静态校验接入启动并交付真实 health API**
  - 依赖：T1、T2。
  - 改动清单：
    1. 在 app lifespan 的 worker 恢复/启动与 ASGI yield 前加载一次 binding snapshot；失败时保留具体日志、释放已有 advisory lock，并拒绝启动。
    2. 启动时各执行一次 vLLM/Comfy health 探测；外部 unhealthy 不阻止启动，不调用推理/sleep/free/submit。
    3. 替换 C001 `not_checked` skeleton 为 spec §2.3 精确 schema；每次 GET 单次实时探测并返回 `healthy|unhealthy`、安全 message、`valid` 和只含 zimage 的 hash。
    4. 通过 app 显式注入 binding path/transport 的测试 seam 验证错误分支；不得按测试数据分支，也不得在生产创建验收模式。
    5. 按 AGENTS.md 的 C007 一次性窄例外，仅修正 `backend/tests/api/test_system.py::test_infrastructure_smoke`：保留 `/docs`、`/openapi.json`、404/错误体和禁止真实网络 guard，将 C001 `not_checked` 阶段断言演进为注入 transport 后的 C007 精确健康响应与各一次逻辑探测；不得修改其他既有测试。该用例不替代本 task 新增的错误矩阵测试。
  - R：无；PRD §2.1(2)、§5 system、§8、§9、§11 M3。
  - 验收方式：API 测试覆盖健康/不可达/非 2xx/畸形响应与精确 keys；启动测试证明坏 binding 时 worker 未 claim，health 路由无 GPU mutation。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_system.py::test_infrastructure_smoke tests/api/test_c007_health.py
    ```
    2026-08-28 实际结果：首次使用默认数据库执行时发现 8000 端口后端已持有 advisory lock，且测试辅助函数直接读取未导出的 `DATABASE_URL`；未停止运行进程，改用 `Settings` 读取 DSN 与新隔离数据库后，定向测试 `6 passed in 1.52s`，完整 `pytest` 为 `51 passed in 22.84s`，完整原始输出见 `.work/c007/T3-test.log`。
  - 计划测试层级：API 集成。
  - 追溯行：`C001 基础设施 smoke（C007 合法演进）：FastAPI 应用可启动，/docs 可访问，/system/health 返回 C007 当前诊断且测试不连接真实外部网络，通用 API 错误体符合约定`；`C007 Comfy 工作流绑定与诊断：API 格式、注入/输出路径、启动失败、workflow hash 与 /system/health`。

- [x] **T4 交付模板渲染、封闭 schema、R4 hash、workflow 注入和 seed/id 纯函数**
  - 依赖：T1。
  - 改动清单：
    1. 实现 `{{asset}}/{{style}}/{{user_note}}` 一次渲染与未知/缺失变量拒绝；asset 注入精确三字段 compact JSON，null note 注入空串。
    2. 实现 spec §4.2 精确 schema 与非空白 prompt 校验；不加 system 业务 prompt或自由文本解析。
    3. 实现固定八成员数组 JSON bytes 与 SHA-256 `input_hash`；测试逐成员变化和仅 seed 变化。
    4. 实现只修改 workflow 深拷贝两条叶路径的注入函数，证明原 payload object 不变。
    5. 实现无 request id 的 random 63-bit seed/UUID4；有 request id 时只按 spec §3.4：`UUID("27e66eeb-4d70-597c-8f24-fb984fab13c3")` + 规范化 key 执行标准库 UUIDv5，prompt id 为 canonical string，seed 为 UUID integer 低 63 bits。不得 lowercase/NFC、拼入其他字段、读取配置、二次 hash、碰撞处理或依赖当前时间。
  - R：R4；PRD §3.1 R4、§6.2、§7、§8。
  - 验收方式：表驱动纯函数用例精确比较渲染 string、schema object、hash bytes、workflow diff、无 id seed/id 范围与独立性；固定向量 `" abc " → "abc" → f0faf273-5fe9-5726-98be-3d449efdbe8d / 1782929867419795085` 必须逐值相等，并覆盖大小写、内部空白与 Unicode 不被额外规范化；异常不 fallback。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/unit/test_c007_asset_image_inputs.py
    ```
  - 2026-08-28 实际结果：定向测试最终 `17 passed in 0.23s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `68 passed in 23.71s`；原始输出见 `.work/c007/T4-test.log`。
  - 计划测试层级：纯函数。
  - 追溯行：`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`；`§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务，并按冻结的 UUIDv5 映射复用 seed/prompt id`。

- [x] **T5 交付 generate-image 请求边界与单请求入队合同**
  - 依赖：T3、T4。
  - 改动清单：
    1. 新增严格 request/response schema 和 `POST /api/assets/{asset_id}/generate-image`；只接受 JSON object 的 `user_note/request_id`，成功精确 202/task_id。
    2. 在一个显式事务中锁定 Asset/Project/Style/zimage template，复制启动 binding snapshot，计算 cache 判定与 spec §3.3 精确三键 payload，再调用现有通用 queue；API 请求线程不探测/调用外部服务。
    3. 映射 404/409/422/500 精确语义，包括 template 变量前置与 hash/cache 内部不一致；不捕获未预期异常伪装 409。
    4. 新增 API 集成测试覆盖 body matrix、task type/target/status、payload 精确字段与同步零外部调用；不注册伪 handler。
  - R：R4；PRD §3.1 R4、§5 generate-image、§6.1-§6.2、§7。
  - 验收方式：通过真实 PostgreSQL/FastAPI 边界读取 task row 并逐字段比较；不存在 asset 404，缺/null/array/未知字段 422，配置前置 409，所有错误固定 body。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c007_generate_asset_image.py -k request_contract
    ```
  - 2026-08-28 实际结果：定向测试 `2 passed in 1.31s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `70 passed in 24.55s`；原始输出见 `.work/c007/T5-test.log`。
  - 计划测试层级：API 集成。
  - 追溯行：`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`。

- [x] **T6 完成 request_id 并发幂等、多抽卡与 payload 快照竞态**
  - 依赖：T5。
  - 改动清单：
    1. 实现 D-007 规范化 key 的任意状态预查：同 type/target/user_note 返回既有冻结 payload/task，任一不一致 409。
    2. 保证真正并发的 `" abc "`/`"abc"` 按 spec §3.4 固定 UUIDv5 映射构造相同 seed/prompt id/payload，由现有 request_id 唯一索引裁决后返回一个 task；不得插入重试、内容签名或新锁机制。
    3. 证明无 request id 的同资产并发请求可创建多条 active `gen_asset_image`，各自 seed/prompt id 不共享；不得错误复用 `uq_tasks_active_target`。
    4. 以真实队列/DB 保持入队锁定，验证入队后资产、风格、模板、磁盘 workflow 变化不改已 claim payload；worker seam 只读取冻结内容。
    5. 新增独立 task-system mock 竞态用例；不得把并发要求塞回基础 API 用例或修改 C004 tests。
  - R：R4；PRD §3.2 task snapshot、§6.1 request_id/多任务。
  - 验收方式：并发 barrier 后断言 task 行数/id/payload及固定 prompt id/seed 向量；终态重放仍返回原 task和原冻结 payload；变更 target/note 为结构化 409；无 id 并发产物独立；快照对象不被回写。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/task_system/test_c007_enqueue_races.py
    ```
  - 2026-08-28 实际结果：定向测试 `3 passed in 1.56s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `73 passed in 25.70s`；原始输出见 `.work/c007/T6-test.log`。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务，并按冻结的 UUIDv5 映射复用 seed/prompt id`；`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`。

- [x] **T7 交付生成 PNG 的正式落盘、最终事务和同步补偿服务**
  - 依赖：T4、T6。
  - 改动清单：
    1. 流式写 `DATA_DIR/tmp`，要求 Pillow 完整 decode 且真实 PNG，计算原始 bytes sha256；拒绝 0/多输出在上游，服务不转码或生成占位图。
    2. 最终事务锁定 task/Asset/current，按 source revision + current 判定 `is_current`；只在安全首版 current 时 revision+1 并复用现有 Shot changed/Clip stale 级联。
    3. 插入 generated AssetImage 的 seed/built_prompt/input_hash/完整 input_snapshot/user_note/path；cache miss 更新 Asset cache；所有业务写与条件 done/progress=1 同事务。
    4. 正式 rename 后事务失败时同步 move to trash；temp 总清理；补偿失败与主错误共同上报，不建后台任务/pending 行。
    5. 新增资源生命周期测试覆盖 current/no-current、revision match/mismatch、asset 删除、DB commit 失败、trash 补偿失败和 cancel/done 胜方。
  - R：R4；PRD §3.2、§3.3 current 级联、§6.2、§6.4、§10 文件布局；D-009、D-010。
  - 验收方式：使用真实 PostgreSQL 与隔离 DATA_DIR 对照 DB、正式路径、trash、sha256、revision/status/task；任一失败无部分成功。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/task_system/test_c007_asset_image_commit.py
    ```
  - 2026-08-28 实际结果：定向首轮 `6 passed, 1 failed`（新增测试读取 asyncpg JSONB 未解码）；修正测试夹具后最终 `7 passed in 3.23s`，隔离 PostgreSQL 数据库完整 `pytest` 为 `80 passed in 35.29s`；原始输出见 `.work/c007/T7-test.log`。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 资产出图事务与文件一致性：生成 PNG 校验/sha256/原子落盘、首版 current、修订竞态保存非 current、缓存/图片/done 同事务、失败补偿入 trash`。

- [x] **T8 组装并注册 gen_asset_image handler 的完整 GPU/Comfy 流水线**
  - 依赖：T2、T4、T7。
  - 改动清单：
    1. 仅在 cache miss 调 wake + 一次 structured chat；cache hit 直接使用 payload cached prompt。两支都记录完整 built prompt/input_hash。
    2. 严格执行取消点→sleep→深拷贝 workflow 注入→先 WS 后 submit→按 prompt id 过滤 progress/executing/terminal→history 绑定输出→view→PNG 服务→最终提交。
    3. progress 映射 `[0.25,0.90]` 且非递减，继续走现有 task event/WS；不创建第二事件通道或业务成功 progress。
    4. 从 Comfy submit 起 finally 始终单次 free；只有 free 成功且无主错误才进入最终取消点/事务，主错误/free 错误共同保留；无 retry、WS reconnect、history poll fallback 或其他输出节点扫描。
    5. 在现有 app handler map 注册 `gen_asset_image`；不实现 `gen_clip_video`，不复制 worker/heartbeat/终态状态机。
    6. 新增完整 task-system mock/资源生命周期用例覆盖合法成功、cache hit/miss、vLLM/schema/sleep/WS/history/view/PNG/free 错误和调用顺序，并断言 free 先于图片/cache/done 提交。
  - R：R4；PRD §3.1、§6.1-§6.4、§7、§8、§11 M3；D-005、D-009、D-011。
  - 验收方式：对外部调用序列、次数、prompt/schema/workflow精确值、task进度/终态、图片/cache/file逐项断言；失败均只一条 task 且不重试。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/task_system/test_c007_gen_asset_image.py
    python -m pytest -q tests/task_system/test_c007_resource_lifecycle.py -k pipeline
    ```
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 GPU/Comfy 资源生命周期：cache miss wake/chat、提交前 sleep、WS progress/history 输出、取消 interrupt、finally free，且 vLLM/Comfy 不并发`；`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`。

- [x] **T9 接通 running cancel 的 targeted Comfy interrupt 与最终竞态**
  - 依赖：T8。
  - 改动清单：
    1. 扩展既有 cancel route 的提交后副作用：仅 running `gen_asset_image` 第一次写 cancel intent 后，用 payload prompt id 调一次 targeted interrupt。
    2. queued、重复 running、canceled、其他 task type 不调 interrupt；done/failed 继续既有 409。
    3. interrupt HTTP/网络失败只按 PRD“尽力”记录含 task/prompt id 的 warning，已提交 cancel response 保持 200；不得静默或回滚取消意图。
    4. handler 对 execution_interrupted 先核对数据库取消意图；无意图则 failed。补齐 Comfy运行中取消、Comfy完成后最终事务前取消、最终提交先赢三种竞态测试。
  - R：无；PRD §5 cancel、§6.1、§6.4；D-009。
  - 验收方式：真实 TaskQueue + Comfy mock barrier 精确断言 interrupt 次数、取消响应、图片/cache/files 与单一终态胜方。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/task_system/test_c007_cancel_interrupt.py
    ```
  - 2026-08-28 实际结果：定向测试 `5 passed in 2.44s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `99 passed in 35.21s`；原始输出见 `.work/c007/T9-test.log`。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断`；`C007 GPU/Comfy 资源生命周期：cache miss wake/chat、提交前 sleep、WS progress/history 输出、取消 interrupt、finally free，且 vLLM/Comfy 不并发`。

- [x] **T10 交付 R11 图片调试字段的条件 API 合同**
  - 依赖：T7。
  - 改动清单：
    1. `DEBUG_PROMPTS=false` 时保持 C003 图片列表精确字段，无 built_prompt/input_snapshot/file_path/input_hash/user_note。
    2. `DEBUG_PROMPTS=true` 时只额外返回 built_prompt/input_snapshot；generated 非 null，uploaded 为 null；不新增单图 endpoint。
    3. 确认其他 asset/project/episode/task/health/media API 不因 debug 泄露中间提示词或路径。
    4. 新增 API 集成测试，使用两种 settings/app 实例隔离验证实际 JSON keys；不修改 C002/C003 既有用例。
  - R：R11；PRD §3.5、§5 asset images、§9。
  - 验收方式：对 false/true、generated/uploaded 和其他 API 的 JSON key set 作精确断言。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c007_prompt_visibility.py
    ```
  - 2026-08-28 实际结果：定向测试 `1 passed in 0.98s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `100 passed in 34.64s`；原始输出见 `.work/c007/T10-test.log`。
  - 计划测试层级：API 集成。
  - 追溯行：`R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot`。

- [x] **T11 在设置页交付系统诊断面板**
  - 依赖：T3。
  - 改动清单：
    1. 更新前端 health 类型/解析器到 spec §2.3 精确状态与 message/hash，不宽容吞掉畸形 200。
    2. 设置页初次进入并行但独立读取 style/template/health，分别显示 vLLM、Comfy、Z-Image binding 与完整 hash；提供手动刷新诊断。
    3. component unhealthy 或 health 请求级失败都保留已成功读取的设置数据并直显对应 message/API 错误；不自动重试、不定时轮询。
    4. 浏览器继续只调用同源 `/api/system/health`，不接触 Comfy/vLLM 地址。
  - R：无；PRD §2.1(2)、§5 system、§8、§9、§11 M3。
  - 验收方式：生产 build；真实浏览器分别观察 healthy 和停止单个外部服务后的 unhealthy/message，确认设置编辑仍可用且刷新只在点击发生。
  - 应运行命令或人工检查：
    ```powershell
    Set-Location D:\ai_drama_studio\frontend
    npm run build
    ```
    人工访问 `/settings`，记录初次诊断、手动刷新、单组件 unhealthy、请求级失败四种截图/文字证据。
    2026-08-28 实际结果：生产 build 成功（55 modules transformed，vite built in 536ms）；隔离数据库完整 pytest 为 `100 passed in 34.35s`；真实浏览器完成 healthy、ComfyUI 停止后的 unhealthy/message、后端停止后的请求级错误、设置编辑保留与恢复刷新走查；原始输出见 `.work/c007/T11-test.log`。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用（仓库没有前端自动测试框架；后端 health 运行时合同已由 T3 对应追溯行覆盖）。

- [x] **T12 在资产页交付意见、生成、terminal 刷新、抽卡画廊与 debug 展示**
  - 依赖：T8、T10。
  - 改动清单：
    1. 前端 API 新增严格 generate-image request/response；资产卡加入意见与生成按钮，空白发送 null，202 后展示 task id/任务中心入口并恢复按钮。
    2. AssetPage 复用现有 task WS 与 D-008 的 1/2/5/10 秒重连；terminal gen_asset_image 通过 task GET 确认 target 后刷新真实画廊，重连成功后一次刷新补断线窗口；错误明确显示，不做周期轮询或 mutation 重发。
    3. 画廊标出 source/seed/current，保留上传/current/删除能力；debug 字段存在时可展开 prompt/snapshot，不存在时完全不渲染调试区。
    4. 不增加生成历史页、候选版本、prop、clip/slot/video/导演台 UI，也不把 Comfy/VLLM 地址写入浏览器。
  - R：R4、R11；PRD §2.1(5,9)、§3.1、§3.5、§5、§9、§11 M3。
  - 验收方式：生产 build；真实浏览器完成同资产两次提交、task id、terminal 自动刷新、两版本/seed、设 current、删非 current、同步错误保留意见、debug false/true 展示。
  - 应运行命令或人工检查：
    ```powershell
    Set-Location D:\ai_drama_studio\frontend
    npm run build
    ```
    人工按 spec AC-15/AC-16 逐项记录 API/页面真相，不用 DevTools 伪造 task event 或图片。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用（R4/R11 后端行为已有 T4-T10 自动覆盖；当前前端无测试框架，以 build + 真实浏览器验收 UI）。
  - 2026-08-30 实际结果：设置 API 写入并逐字读回人物四视图模板（`READBACK_MATCH=True`，三处占位符精确）；真实浏览器任务 `#233/#234` 均 `done`，产生版本 `29/30` 两个不同 seed，切换 current 并删除非 current 后页面/API/正式目录与 trash 一致；同步错误保留意见；debug false/true 字段与可展开展示符合约定；隔离库完整 pytest `100 passed in 33.90s`，生产 build 成功；原始命令输出见 `.work/c007/T12-test.log`。

- [x] **T13 通过设置 API 固化单一 `zimage` 人物/场景双分支正式模板**
  - 依赖：T0-T12 全部完成。
  - 改动/证据清单：
    1. 以需求方 2026-08-30 提供的人物模板为人物分支，保留其七段四视图正文、填写规则、默认值和林晚示例；只作 spec §4.1 明确要求的合同修正：`3:2` 改为 `1344×1024`，把裸正文输出改为唯一 JSON object 的 `prompt` 字段，并增加按注入资产 JSON `type` 二选一的总入口。
    2. 在同一模板加入 spec §4.1 场景分支：四段 prompt 必须依次覆盖单幅连续空间、观察位置/方向及前中后景、建筑或地貌/陈设/时间/天气/光照/材质/项目风格、排除可辨识人物与多格/四视图/分镜/平面图/文字/标志/水印；不新增第二模板 key、模板版本、fallback 或代码侧业务 prompt。
    3. 正文末尾按 `资产：{{asset}}`、`风格：{{style}}`、`用户补充：{{user_note}}` 顺序各保留一次且仅一次，不含其他或未闭合占位符；用户意见优先级不得覆盖类型、画幅、分支构图和 JSON 硬约束。
    4. 先 GET 记录当前 `zimage` 内容，再通过既有 `PATCH /api/prompt-templates/zimage` 写入合并后的正式正文，随后 GET 并与提交字符串逐字比较；只改变现有运行数据，不新增仓库模板文件、不把测试输入写进生产代码。API 未成功写入或读回不一致时不勾选。
  - R：R4、R11；PRD §3.1 R4、§3.2 风格/模板即时生效、§3.5、§5 设置 API、§7、§11 M3、§12.2。
  - 验收方式与应运行命令：使用真实设置 API 保存和读回，不直接改数据库。`$approvedTemplate` 必须是按上述 1-3 合并后的完整正文，不得用摘要代替。
    ```powershell
    $apiBase = 'http://127.0.0.1:8000/api'
    $before = Invoke-RestMethod -Method Get -Uri "$apiBase/prompt-templates"
    $approvedTemplate = @'
    <粘贴完整的已确认单模板正文；执行时不得保留本占位行>
    '@
    $placeholderNames = [regex]::Matches($approvedTemplate, '\{\{([^{}]+)\}\}') | ForEach-Object { $_.Groups[1].Value }
    if (($placeholderNames -join ',') -cne 'asset,style,user_note') { throw "unexpected placeholders: $($placeholderNames -join ',')" }
    if ($approvedTemplate -match '3:2|只输出填好的提示词正文') { throw 'template still conflicts with workflow or JSON response contract' }
    if ($approvedTemplate -notmatch '1344×1024' -or $approvedTemplate -notmatch 'character' -or $approvedTemplate -notmatch 'scene' -or $approvedTemplate -notmatch 'JSON' -or $approvedTemplate -notmatch 'prompt') { throw 'template is missing a required branch/output marker' }
    $body = @{ content = $approvedTemplate } | ConvertTo-Json
    Invoke-RestMethod -Method Patch -Uri "$apiBase/prompt-templates/zimage" -ContentType 'application/json' -Body $body
    $after = Invoke-RestMethod -Method Get -Uri "$apiBase/prompt-templates"
    $stored = ($after | Where-Object { $_.key -eq 'zimage' }).content
    if ($stored -cne $approvedTemplate) { throw 'zimage template readback differs from submitted content' }
    ```
    保存 before/PATCH/after 的真实 HTTP 状态与逐字相等结果；不得声称静态关键字检查已经证明图片语义，图片语义只由 T14 验收。
  - 计划测试层级：不新增自动测试（正式模板是需求方确认并经既有设置 API 管理的运行数据；API 编辑合同已有 C002 覆盖，人物/场景输出语义由 T14 真实资源通路验收）。
  - 追溯行：`C007 Z-Image 类型语义：单一 zimage 模板按 asset.type 生成 1344×1024 人物四视图或单幅连续场景，并使用封闭 prompt JSON`；`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`；`R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot`。
  - 2026-08-30 实际结果：真实 `GET /api/prompt-templates` 读取后通过 `PATCH /api/prompt-templates/zimage` 写入完整正式模板，再次 GET 逐字比对；两次 PATCH 均返回 `200`，最终 `READBACK_MATCH=True`、长度 `2770`，占位符顺序为 `asset,style,user_note`；同一模板包含人物/场景分支、`1344×1024` 和唯一 `prompt` JSON 输出约束；隔离库全量 pytest `100 passed in 34.39s`，原始输出见 `.work/c007/T13-test.log`。图片语义留待 T14。

- [x] **T14 完成真实 M3 人物/场景纵向验收、全量回归与追溯回填**
  - 依赖：T13。
  - 改动/证据清单：
    1. 使用新建隔离 PostgreSQL 数据库和隔离 DATA_DIR 跑全部定向/完整测试；任何已有 uvicorn 必须先停止或切换 DSN，避免 advisory lock/历史数据污染。
    2. 真实环境 GET `zimage` 并与 T13 提交正文逐字一致；模板、workflow hash 或外部服务状态漂移时停止，不以旧 cache 或临时 prompt 继续。
    3. 选择已有 current 图片的 `character` 资产：以相同意见连续成功两次，证明首次为 template 内容变化后的 cache miss/chat=1，第二次 hash hit/chat=0 且 seed/版本不同；编辑描述后第三次 hash 改变/chat=1。检查首次 built prompt 只含 1344×1024 人物四视图语义，PNG 为 1344×1024 单张四栏同一人物且无额外人物、文字、标志或水印。
    4. 创建或选择一个无 current 的 `scene` 资产，其描述明确给出前景、中景、背景、时间、天气和光照；执行一次真实 cache miss，检查 snapshot/rendered/built prompt 不含人物四视图指令，PNG 为 1344×1024 单幅连续环境且无可辨识人物、多格、分镜、文字、标志或水印，并证明该安全首版自动 current。任一人工检查项为假时本 task 失败，不用另一 seed 冒充本次通过。
    5. 用真实 vLLM/Comfy 记录人物 miss/hit、场景 miss 的 wake/chat/sleep/submit/progress/history/view/free 顺序和任务日志；执行期间采样 GPU 进程/显存，确认无 LLM/Comfy 推理重叠。
    6. 验证真实 `/system/health`、资产页、设置页、任务中心、两类媒体 URL、debug false/true；保存两类 input snapshot/rendered prompt/built prompt、task 终态、PNG 尺寸、页面/图片截图和 AC-19 逐项真假表，不得用 mock/占位图冒充。
    7. 回填本 change 新增测试的真实 pytest node ID 到准确 TRACEABILITY 行；AC-19 保持 T13/T14 的非自动真实验收记录，不为图像语义新增固定像素测试，不得修改/弱化任何既有测试。
    8. 运行 full pytest、frontend build、Alembic current/check、diff/check/范围扫描，保留原始输出；发现失败不得勾选或提交。
  - R：R4、R11；PRD §2.1(5,9)、§3.1-§3.3、§3.5、§5、§6.1-§6.4、§7-§9、§11 M3、§12。
  - 验收方式与应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m alembic current
    python -m alembic check
    python -m pytest -q tests/unit/test_c007_workflow_binding.py tests/unit/test_c007_asset_image_inputs.py tests/api/test_c007_health.py tests/api/test_c007_generate_asset_image.py tests/api/test_c007_prompt_visibility.py tests/api/test_c007_review_health.py tests/task_system/test_c007_enqueue_races.py tests/task_system/test_c007_asset_image_commit.py tests/task_system/test_c007_gen_asset_image.py tests/task_system/test_c007_cancel_interrupt.py tests/task_system/test_c007_resource_lifecycle.py tests/task_system/test_c007_review_regressions.py
    python -m pytest -q

    Set-Location D:\ai_drama_studio\frontend
    npm run build

    Set-Location D:\ai_drama_studio
    git diff --check
    git status --short
    rg -n -i "generation_runs|continuity|context_loop|fl2v|audio|candidate shot|候选分镜|资产别名|模板版本" backend frontend/src
    ```
    真实浏览器/HTTP/GPU证据按 spec AC-02、AC-04、AC-09、AC-10、AC-15、AC-16、AC-19 保存；命中既有合法 `clips.generation_mode` 预留时只核对未新增读写，不把单纯文本命中误报为失败。
  - 2026-08-30 实际结果：真实模板 GET 200、唯一占位符顺序为 asset,style,user_note，workflow hash 与 debug false health 均稳定；人物任务 #235/#248/#249 和场景任务 #250 均 done，人物图片 31/32/33、场景图片 34 均为 PNG 1344×1024，场景首版 34 自动 current。人物相同意见第二次命中缓存，描述修改后第三次重建 prompt；debug false 不返回中间字段，debug true 返回 built_prompt/input_snapshot；真实 vLLM/Comfy、媒体 URL、资产页、设置页和任务中心证据见 .work/c007/T14-test.log 及截图。
  - 2026-08-30 Sol 审查修复实际结果：在隔离数据库 `ai_drama_studio_c007_review_repair_20260830` 上新增 API 边界、真实并发快照、AC-08/AC-11 完整 handler、health timeout 和跨进程资源生命周期回归；新增回归定向 `9 passed in 4.21s`，C007 定向（含新增用例）`77 passed in 14.96s`，完整 backend `109 passed in 68.02s`。最新 frontend `npm run build` 为 55 modules、`215.70 kB` JS、`7.90 kB` CSS、`426ms`；Alembic current 为 `6b8e3f0a1d24 (head)`，check 为 `No new upgrade operations detected.`；原始输出见 `.work/c007/C007-sol-review-*.log`。vLLM 按用户裁决保持停止，依赖真实 vLLM 的复验待外部验证。
  - 2026-08-30 人工偏离记录：人物图片 31 与 33 的第一栏未呈现放大头肩近景，但仍为四栏同一角色 PNG；用户已明确接受 Z-Image 结果不可预测，并裁决本次所有资产以成功生成、任务完成、资产落盘和合同状态可验证为验收门槛。该裁决不改写 spec 字面，未将该视觉项静默记为满足。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`；`R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot`；`§3.3 编辑风格或模板：分镜与片段不动、文件不删，下次生成因 hash 失配重建 prompt`；`§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断`；`§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务，并按冻结的 UUIDv5 映射复用 seed/prompt id`；`C007 Z-Image 类型语义：单一 zimage 模板按 asset.type 生成 1344×1024 人物四视图或单幅连续场景，并使用封闭 prompt JSON`；`C007 Comfy 工作流绑定与诊断：API 格式、注入/输出路径、启动失败、workflow hash 与 /system/health`；`C007 GPU/Comfy 资源生命周期：cache miss wake/chat、提交前 sleep、WS progress/history 输出、取消 interrupt、finally free，且 vLLM/Comfy 不并发`；`C007 资产出图事务与文件一致性：生成 PNG 校验/sha256/原子落盘、首版 current、修订竞态保存非 current、缓存/图片/done 同事务、失败补偿入 trash`。只回填实际覆盖的 node ID，AC-19 不虚构 pytest node ID。

- [x] T15 修复 generate-image 的 PostgreSQL `INTEGER` 双向边界
  - 依赖：T14 已有实现；本 task 只处理 Sol 裁决列出的 API 边界 BLOCK。
  - 改动范围：`backend/app/api/assets.py` 的 `asset_id` path 校验同时声明 `ge=-2147483648` 与 `le=2147483647`；不得进入数据库/队列后才失败。新增独立 API 回归用例，覆盖下界外 `-2147483649` 的结构化 422 与 enqueue 未调用；不得修改既有边界用例。
  - R：无新增产品字段；PRD §5.2；spec §3.1、AC-05。
  - 验收命令：在隔离 PostgreSQL 上运行 `python -m pytest -q tests/api/test_c007_final_repair.py::test_generate_asset_image_rejects_postgresql_int32_lower_bound_before_enqueue`。
  - 计划测试层级：API 集成。
  - 追溯行：`C007 generate-image API 下界输入边界：asset_id=-2147483649 在数据库/队列前返回结构化 422`。
  - 2026-08-31 实际结果：隔离库定向测试 `1 passed in 0.60s`；HTTP 422、固定 `detail.code/message`、enqueue 未调用均断言通过；原始输出见 `.work/c007/final-repair-t15.log`。

- [x] T16 修复 AssetPage 刷新请求失效后的状态清理
  - 依赖：T14、T15；无外部服务依赖。
  - 改动范围：`frontend/src/pages/AssetPage.tsx`。WS connect/reconnect 使旧 REST 请求失效时，清理旧请求留下的 `refreshing`；仅当前有效请求可写入 entries/load state/error，最终不存在有效刷新请求时 `refreshing=false`。
  - R：R11；PRD §9；spec §6.2、AC-15。
  - 验收命令：`npm run build`；并按 AC-15 记录真实浏览器延迟 REST→WS 重连→按钮状态。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 AssetPage REST/WS 刷新竞态：失效旧请求不覆盖状态且不遗留 refreshing`。
  - 2026-08-31 实际结果：生产 build 成功；真实浏览器在 set-current 同步操作分发约 30ms 后中断后端，页面保留资产且 `创建资产` 按钮 `enabled=true`；本轮又在版本 31 切换时安排 Vite 250ms 后中断，恢复后页面仍保留画廊。浏览器控制面未提供可读取的 REST 延迟响应事件，未将这些操作冒充为完整延迟 REST 窗口证据，故本 task 保持未勾选；原始记录见 `.work/c007/final-repair-browser.log`。
  - 2026-08-31 Sol 定向复验：真实 PostgreSQL `asset_images` 锁使生产图片 REST 请求保持等待；WS 断开后旧 request generation 失效，`创建资产` 按钮观测为 `disabled=false`；释放锁并恢复连接后四张资产卡 ready，未出现旧请求覆盖。原始输出见 `.work/c007/probe-t16-t17-sol.log`；该证据补足延迟 REST→WS 重连窗口，本 task 已解除阻塞并勾选。

- [x] T17 修复 AssetPage 初始快照失败后的 socket 重连同步
  - 依赖：T16；无新增 endpoint、polling、fallback 或测试特判。
  - 改动范围：`frontend/src/pages/AssetPage.tsx`。快照失败保留可见错误并关闭当前 socket，沿用既有 WS reconnect 调度；下一连接重复 WS 缓冲→REST 快照→按序合并，恢复后不丢 terminal 更新。
  - R：R11；PRD §9；spec §6.2、AC-15。
  - 验收命令：`npm run build`；并按 AC-15 记录真实浏览器快照失败→恢复服务→下一连接同步事件与 REST 的逐步观测。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 AssetPage 初始快照失败恢复：socket 关闭、可见错误、既有重连后重新按序同步`。
  - 2026-08-31 实际结果：首次页面请求失败时真实浏览器显示 `protocol_error：API response was not valid JSON`，但该次是 `EpisodeWorkspacePage` 父级请求失败，不能作为 AssetPage 快照失败证据。补充的同一路由、已挂载 AssetPage 走查中，停止 Vite 使真实 WS close；恢复 Vite 后未手动 reload，页面自动重连并通过新的 REST 快照将临时版本 31 显示为 `current: true`，随后恢复版本 30。自动重连路径已观察，但 AssetPage 自身“快照失败→可见错误”的独立窗口和 terminal 事件窗口仍未同时观测，故本 task 保持未勾选；原始记录见 `.work/c007/final-repair-browser.log`。
  - 2026-08-31 Sol 定向复验：一次性验收代理仅令首个 AssetPage 快照返回 500；生产前端连续观测到 `loading 26ms → 可见 controlled snapshot failure 541ms → reconnect loading 1537ms → 4 asset cards ready 1586ms`。失败 socket 已关闭，既有 1 秒重连调度重新执行 WS 缓冲→REST 快照→按序合并；恢复数据来自真实 REST/WS 通路。原始输出见 `.work/c007/probe-t16-t17-sol.log`；该证据补足快照失败可见、关闭、重连与恢复窗口，本 task 已解除阻塞并勾选。

- [x] T18 增加 AC-07 三类资源独立连接锁证据
  - 依赖：T14；不得修改 `test_enqueue_snapshot_wins_concurrent_source_edit_and_worker_uses_copy`。
  - 改动范围：新增任务系统回归测试。Asset、Style、Template 更新各使用独立数据库连接和并发任务；三 writer 全部启动后，证明入队事务提交前分别被对应行锁阻塞，提交后全部完成；断言 payload 保留编辑前值且生产 worker 使用同一冻结副本。测试层级必须为跨进程/资源生命周期，不得用一个连接顺序 UPDATE 冒充三类覆盖。
  - R：R4；PRD §3.1-§3.3、§6.1；spec §3.3、AC-07。
  - 验收命令：`python -m pytest -q tests/task_system/test_c007_lock_evidence.py::test_enqueue_holds_asset_style_template_locks_until_commit_and_worker_uses_copy`。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 AC-07 独立锁屏障：Asset/Style/Template 分别由独立连接并发编辑并在入队提交后解除阻塞`。
  - 2026-08-31 实际结果：隔离库定向测试 `1 passed in 0.88s`；三独立连接均在入队提交前被对应行锁阻塞，提交后完成，冻结 payload 与 worker 副本断言通过；原始输出见 `.work/c007/final-repair-t18.log`。

- [x] T19 增加真实 transport health 协议回归
  - 依赖：T14；仅使用真实本地 HTTP transport seam，不访问生产 vLLM/Comfy，不修改既有测试。
  - 改动范围：新增 API 回归测试，经过生产 `/api/system/health` 路径分别覆盖 vLLM 200 空 body、vLLM 200 非 JSON body、vLLM 非 2xx、Comfy 200 畸形 JSON；保留本轮唯一授权的既有 health 测试修改，不再修改其他既有测试。
  - R：无新增产品字段；PRD §8；spec §2.3、AC-04。
  - 验收命令：`python -m pytest -q tests/api/test_c007_health_transport.py`。
  - 计划测试层级：API 集成。
  - 追溯行：`C007 health 真实 transport 协议矩阵：按 vLLM/Comfy 各自上游合同判定 healthy/unhealthy`。
  - 2026-08-31 实际结果：隔离本地 HTTP transport seam 定向测试 `4 passed in 3.41s`，覆盖 vLLM 空 body、非 JSON body、非 2xx 及 Comfy 畸形 JSON；原始输出见 `.work/c007/final-repair-t19.log`。

- [x] T20 按 0.91 显存参数完成 vLLM 真实复验并保持 level-1 sleep
  - 依赖：T15、T19；重新勾选还依赖 T24。先确认无生产任务且 Comfy `queue_running`/`queue_pending` 均为 0，只有该前提成立才允许 `/free`。
  - 改动范围：仅按 NOTES.md 既有命令把 `gpu-memory-utilization` 改为 `0.91`，保留 `max-model-len=16384`、`enable-sleep-mode`、原模型/served name/generation-config 与 `VLLM_USE_FLASHINFER_SAMPLER=0`。真实记录 `/health`、sleep、wake、最小 structured chat、后端 health，最后保持进程运行且 engine level-1 sleep；0.91 失败即保存日志停止。
  - R：PRD §7、§8、§12；spec §2.2-§2.3、AC-02、AC-04、AC-10。
  - 验收命令：按 T24 顺序执行并只引用 `.work/c007/T24-vllm-preconditions.log`、`.work/c007/T24-vllm-http.log`、`.work/c007/T24-vllm-final-state.log` 的本次原始输出；不以 mock、旧日志或补写文件代替。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 vLLM 0.91 真实复验：health、sleep/wake、structured chat、后端 health 与最终 level-1 sleep`。
  - 2026-08-31 实际结果：第一次按 0.91 启动因当时可用显存 21.31/23.99 GiB 小于所需 21.83 GiB 失败并按规则停止；随后再次确认生产任务为空、Comfy `queue_running=0`、`queue_pending=0`，按同一启动合同仅使用 `gpu-memory-utilization=0.91` 成功启动。真实 `/health` 为 HTTP 200 空 body；sleep/wake 状态依次为 true/false；structured chat 为 HTTP 200，封闭输出 `{"answer":"ok"}`；后端 health 为 HTTP 200 且 `vllm.status=healthy`、`vllm.message=null`；最终 `/is_sleeping` 为 `{"is_sleeping":true}`，vLLM 进程保持运行。原始日志见 `.work/c007/final-repair-vllm-091.out.log`、`.work/c007/final-repair-vllm-091.err.log`、`.work/c007/final-repair-vllm-retry-091.out.log`、`.work/c007/final-repair-vllm-retry-091.err.log`、`.work/c007/final-repair-vllm-retry-http.log`、`.work/c007/final-repair-vllm-retry-preconditions.log`。
  - 2026-08-31 Sol 最终审查：上述 `final-repair-vllm-retry-http.log` 实际不存在；server log 只能证明各 endpoint 返回 200，不能证明 structured chat 的完整响应体。T20 因证据链不成立而重新开放，只有 T24 产生新的真实请求/响应日志并满足全部门槛后才能重新勾选；不得补写或追认缺失日志。
  - 2026-08-31 T24 收口实际结果：操作→观测：读取 `.work/c007/T24-vllm-preconditions.log` 得到生产 queued/running 均为 HTTP 200 空数组、Comfy `/queue` 为 HTTP 200 且 running/pending 为空、vLLM 初始 sleeping=true；按 0.91 启动合同读取 `.work/c007/T24-vllm-http.log`，`/health` 为 200 空 body、sleep/wake 为 200 且状态 true→false、structured chat 为 200 且解析为 `{"answer":"ok"}`、后端 health 为 vLLM healthy/null，随后 `/sleep?level=1` 为 200；读取 `.work/c007/T24-vllm-final-state.log` 得到最终 sleeping=true、Comfy/生产任务队列仍为空，WSL 命令保留原模型、served name、max-model-len=16384、gpu-memory-utilization=0.91 与 enable-sleep-mode。三份日志均为本次新执行原始输出。

- [x] T21 交付 AC-15 保持连接事件/REST 竞态的一次性验收装置
  - 依赖：T16、T17；本 task 必须先于 T22 完成，不修改生产实现、测试、spec 或生产 endpoint。
  - 改动范围：仅在 `.work/c007/probe-assetpage-ws-refresh.py` 交付一次性验收驱动并保存原始日志。驱动启动生产前端构建、由生产 `create_app` 创建的隔离 app、真实 PostgreSQL、资产 REST、任务入队 API/EventBus 与 `/ws/tasks`；本地代理只延迟一次画廊 REST，隔离 worker 在 queued 事件发布后保持停止，不调用 vLLM/Comfy。浏览器在创建、切换 current 或删除触发的刷新等待期间，经真实 API 为另一资产入队并收到无关非终态 WS 事件，再释放旧响应。
  - R：R11；PRD §9；spec §6.2、§9、AC-15。
  - 验收方式与命令：运行 `python .work/c007/probe-assetpage-ws-refresh.py` 并按脚本提示完成真实浏览器操作；原始输出必须记录旧 REST 的 request/release 时间、真实 queued WS 事件、后续 REST 请求次数、API 真相、DOM、成功提示与按钮状态。修复前允许报告 `contract_met=false`，但必须证明窗口真实发生且旧代码没有补发快照；装置自身启动失败、使用伪造 WS 消息或触发外部 worker 时本 task 不通过。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 AssetPage 保持连接的事件/REST 竞态：旧响应失效后补发最新快照且成功提示不早于应用`。
  - 2026-08-31 实际结果（修复前装置）：操作→观测：运行 `python .work/c007/probe-assetpage-ws-refresh.py` 并按提示经生产前端创建第三资产，`.work/c007/T21-pre-fix-contract-false.log` 记录一次延迟 `/api/assets/1/images`、真实 queued `gen_asset_image` WS 事件、延迟响应释放后旧代码 `post_event_rest_requests=0`、API 真相 3 资产且 `contract_met=false`；同页 DOM 观测见 `.work/c007/T21-browser-dom.log`（Gamma=0、成功提示=1、创建按钮 enabled=true）。装置使用生产前端构建、`create_app`、真实 PostgreSQL、资产 REST、任务 API/EventBus 和 `/ws/tasks`；本地代理只延迟一次 gallery REST，隔离 worker 在 queued 事件发布后停止，未调用 vLLM/Comfy。

- [x] T22 修复 AssetPage 保持连接时事件使 REST 刷新失效后不补刷
  - 依赖：T21；只修复 T21 已复现的 AC-15 分支，不改变 T16/T17 已验收的断线重连和快照失败行为。
  - 改动范围：仅 `frontend/src/pages/AssetPage.tsx`。任何因更新 WS revision 而失效的画廊响应不得写状态；仍有待完成的创建、切换 current、删除或 terminal 同步时，必须合并或补发绑定最新 revision 的快照。terminal task 去重不得吞掉补刷新，成功提示不得早于最新快照应用，全部有效刷新结束后 `refreshing=false`。不得增加 polling、自动重发 mutation、fallback、兼容层或后续 change 能力。
  - R：R11；PRD §9；spec §6.2、AC-15。
  - 验收方式与命令：在 `frontend` 运行 `npm run build`；随后重跑 `python .work/c007/probe-assetpage-ws-refresh.py` 与同一浏览器步骤。必须观测旧响应未写入、事件后至少一个新 REST 快照成功应用、DOM 与 API 真相一致、成功提示不早于应用、最终按钮可用且无定时轮询；原始输出保存到 `.work/c007/T22-assetpage-ws-refresh.log`。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 AssetPage 保持连接的事件/REST 竞态：旧响应失效后补发最新快照且成功提示不早于应用`。
  - 2026-08-31 实际结果：操作→观测：在 `frontend` 运行 `npm.cmd run build` 成功（55 modules），重跑同一生产前端/`create_app`/PostgreSQL/REST/任务 API/EventBus/WS 代理装置后，`.work/c007/T22-assetpage-ws-refresh.log` 记录延迟响应与 queued WS 事件、事件后 `post_event_rest_requests=4`、API 真相为 3 资产且 `contract_met=true`；`.work/c007/T22-browser-dom.log` 记录 Gamma=1、成功提示=1、创建按钮 enabled=true。代理未调用 vLLM/Comfy，未增加 polling 或 mutation 重发。

- [x] T23 按需求方窄授权修正 health timeout 测试装置
  - 依赖：T22；生产 health 实现已经由 `.work/c007/probe-final-health-timeout.log` 证明符合合同，本 task 只修复环境依赖的验收用例。
  - 改动范围：仅允许修改 `backend/tests/api/test_c007_review_health.py::test_health_timeout_is_unhealthy_without_gpu_mutation` 函数体：让 `_TimeoutVLLM` 连接该用例创建的 `127.0.0.1:{server.server_port}` 慢服务，并在函数内用事件或计数断言慢服务确实收到请求。必须保留精确 timeout status/message、Comfy healthy、workflow valid、vLLM/Comfy 无 GPU mutation 的全部断言；不得修改其他函数、文件或测试，不得连接生产 8001，不得 skip、改名或削弱用例。
  - 授权记录：需求方于 2026-08-31 明确授权上述唯一函数修改；该授权不适用于任何其他既有测试。被修正并增加“本地慢服务确实命中”断言的同一用例就是本 BLOCK 的 API 回归，不新增测试测试自身的重复用例。
  - R：无；PRD §8；spec §2.3、AC-04。
  - 验收方式与命令：在隔离 PostgreSQL 环境运行 `python -m pytest -q tests/api/test_c007_review_health.py::test_health_timeout_is_unhealthy_without_gpu_mutation`；再运行 `git diff --name-only 74eeabe..HEAD -- backend/tests`，输出必须精确只有 `backend/tests/api/test_c007_review_health.py`，并逐行检查该文件 diff 只落在授权函数体。
  - 计划测试层级：API 集成。
  - 追溯行：`C007 health transport timeout：本地随机端口慢服务被命中，vLLM 超时返回 unhealthy 与可展示 message，health 请求不触发 wake/sleep/free 等 GPU mutation，且不连接生产 8001`。
  - 2026-08-31 实际结果：操作→观测：隔离 PostgreSQL 运行 `python -m pytest -q tests/api/test_c007_review_health.py::test_health_timeout_is_unhealthy_without_gpu_mutation` 得 `1 passed in 1.19s`；用例内本地慢服务事件已命中，health 返回约定 timeout status/message，Comfy healthy、workflow valid 且 vLLM/Comfy mutation 为空。`git diff --name-only 74eeabe -- backend/tests` 仅为授权文件；原始输出见 `.work/c007/T23-health-timeout.log`。

- [x] T24 重做 T20 的真实 vLLM HTTP 证据并恢复 level-1 sleep
  - 依赖：T23；执行前必须重新确认生产 queued/running task 均为 0、Comfy `queue_running`/`queue_pending` 均为 0，任一不为空立即停止。若 vLLM 未按 T20 的 0.91 合同运行或模型、served name、参数漂移，保存证据并停止，不自行换参数、模型或地址。
  - 改动范围：不改实现、测试、模型、workflow 或模板。把本次新执行的完整请求/响应分别保存到 `.work/c007/T24-vllm-preconditions.log`、`.work/c007/T24-vllm-http.log`、`.work/c007/T24-vllm-final-state.log`；不得创建缺失旧日志来冒充前一轮证据。
  - R：PRD §7、§8、§12；spec §2.2-§2.3、AC-02、AC-04、AC-10。
  - 验收方式与命令：按顺序记录真实 `GET /health`、初始 `GET /is_sleeping`、`POST /wake_up`、醒后状态、最小 structured chat 的 HTTP 状态与完整 JSON body、后端 `/api/system/health`、`POST /sleep?level=1` 和最终 `GET /is_sleeping`；structured chat 必须得到 HTTP 200 与封闭输出 `{"answer":"ok"}`，后端 vLLM 为 healthy/null，最终必须为 `{"is_sleeping":true}`。任何中途失败也必须在 finally 路径尝试恢复 level-1 sleep 并如实报告，不重试业务请求；成功后更新 T20 与对应追溯行只引用这三个真实存在的新日志。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 vLLM 0.91 真实复验：health、sleep/wake、structured chat、后端 health 与最终 level-1 sleep`。
  - 2026-08-31 实际结果：操作→观测：T24 前置、完整请求/响应和最终状态分别记录于 `.work/c007/T24-vllm-preconditions.log`、`.work/c007/T24-vllm-http.log`、`.work/c007/T24-vllm-final-state.log`；三份日志的最终 marker 分别为 `T24_PRECONDITIONS_PASS`、structured parsed `{"answer":"ok"}`/sleep 200、`T24_FINAL_STATE_PASS`，最终 `/is_sleeping` 为 `{"is_sleeping":true}`，Comfy/生产任务队列为空。

- [x] T25 完成 repair 范围审计、全量回归与证据回填
  - 依赖：T21、T22、T23、T24；任一前置 task 未通过时不得勾选。
  - 改动范围：不新增实现或测试，只验证并回填本轮修复证据。使用全新隔离 PostgreSQL 数据库，不让生产 8000 的 worker/advisory lock 污染 pytest；不得为通过测试停止或改变 vLLM 最终 level-1 sleep 状态。
  - R：无；PRD §0、§11；spec AC-01、AC-18。
  - 验收方式与命令：在隔离数据库依次运行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`；收集 `backend/tests/**/*c007*.py` 后运行全部 C007 测试，再运行 `python -m pytest -q`；在 `frontend` 运行 `npm run build`；运行 `git diff --check`、spec T14 的围栏 `rg` 命令及 `git diff --name-only 74eeabe..HEAD -- backend/tests`。预期 Alembic 为单一 head 且无新操作、两轮 pytest 零失败、构建成功、范围扫描无禁项、测试 diff 精确只有 T23 授权文件。原始输出逐项保存到 `.work/c007/T25-*.log`，TRACEABILITY 只回填真实通过证据。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用；AC-18 按 spec §9 的替代验收命令覆盖。
  - 2026-08-31 实际结果：操作→观测：全新隔离库 `alembic upgrade/current/check` 成功（单一 `6b8e3f0a1d24 (head)`、无新操作）；收集 17 个 C007 测试文件运行得 `85 passed in 18.95s`，完整 backend 得 `117 passed in 42.80s`；frontend build 成功（55 modules）；`git diff --check` 通过，范围扫描仅命中既有 `clips.generation_mode` 预留，测试工作树 diff 仅授权 T23 文件。逐项原始输出见 `.work/c007/T25-*.log`。

- [x] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）
  - R：无；PRD 章节：不适用，依据 AGENTS §7 的真实环境与命令证据纪律。
  - 验收方式与命令：对照 T0/T14 原始输出更新地址、版本、启动命令、真实测试结果与新坑；若无持久事实，在完成报告精确写“无”。运行 `git diff -- NOTES.md` 核对只记录真实事实。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用。
  - 2026-08-31 实际核对：`d3ab197` 已在 `NOTES.md` 记录本轮 vLLM 0.91 启动、health、sleep/wake、structured chat 与最终 level-1 sleep 的真实证据；本收口不再修改该文件。
  - 2026-08-31 Sol 最终审查后重新开放：T24/T25 可能产生新的持久运行事实与测试结果，必须在其完成后重新核对；无新增内容时在完成报告精确写“无”。
  - 2026-08-31 收口实际结果：本轮形成新的 ComfyUI 启动命令与未提交 workflow 的运行事实，已以最小一行追加到 `NOTES.md`；T24 vLLM 状态和队列事实已由既有条目与本轮三份新日志共同核对。

- [x] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）
  - R：无；PRD 章节：§6-§8；依据 `DECISIONS.md` 的跨 change 收录边界。
  - 验收方式与命令：对照实现是否形成 PRD/AGENTS 未直接规定且约束 C009+ 的长期决定；只在完成报告列候选，不擅自修改 `DECISIONS.md`。运行 `git diff -- DECISIONS.md` 必须为空。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用。
  - 2026-08-31 实际核对：`git diff -- DECISIONS.md` 为空；本 change 无新增候选项，在完成报告中列出“无”。
  - 2026-08-31 Sol 最终审查后重新开放：T22 完成后重新判断 AC-15 的合并刷新语义是否形成跨 change 候选；未经需求方授权仍不得直接修改 `DECISIONS.md`。
  - 2026-08-31 收口实际结果：`git diff -- DECISIONS.md` 为空；本 change 未形成需跨 change 固化的候选项，完成报告列“无”。

- [x] change 文档与 commit 状态一致
  - R：无；PRD 章节：不适用，依据 `openspec/project.md` change 工作流。
  - 验收方式与命令：逐项核对本文件 checkbox 只勾选已有真实证据的 task；`spec.md`、`tasks.md`、TRACEABILITY 回填、实现与当前 commit 同步，无部分完成冒充完成。
    ```powershell
    Set-Location D:\ai_drama_studio
    git status --short
    git diff --check
    git diff -- openspec/changes/c007 openspec/TRACEABILITY.md
    git log -1 --oneline --decorate
    ```
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用。
  - 2026-08-31 实际核对：本收口仅更新 `tasks.md` 与 `TRACEABILITY.md`，未改 `spec.md`、实现、测试、AGENTS、NOTES 或 DECISIONS；提交前后的限定 diff、工作区状态与 commit 将按上述命令核对。
  - 2026-08-31 Sol 最终审查后重新开放：只有 T21-T25、T20 与三个收尾项的 checkbox、TRACEABILITY、原始证据和 commit 内容完全一致时才能再次勾选。
  - 2026-08-31 收口实际结果：操作→观测：T22 生产实现提交 `45d1801`、T23 授权测试提交 `2895c71`；tasks/TRACEABILITY/NOTES 仅在两项实现提交后按本轮真实日志回填，`.work/c007` 从未 stage。最终 docs commit 与当前状态将在本收口提交后按本 task 命令核对。
