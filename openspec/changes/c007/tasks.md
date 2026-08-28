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
    5. 实现无 request id 的 random 63-bit seed/UUID4，以及有 request id 的固定 namespace 确定性 seed/canonical UUID；不依赖当前时间。
  - R：R4；PRD §3.1 R4、§6.2、§7、§8。
  - 验收方式：表驱动纯函数用例精确比较渲染 string、schema object、hash bytes、workflow diff、seed 范围与同 key 稳定性；异常不 fallback。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/unit/test_c007_asset_image_inputs.py
    ```
  - 2026-08-28 实际结果：定向测试最终 `17 passed in 0.23s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `68 passed in 23.71s`；原始输出见 `.work/c007/T4-test.log`。
  - 计划测试层级：纯函数。
  - 追溯行：`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`。

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
    2. 保证真正并发相同 key 构造相同 seed/prompt id/payload，由现有 request_id 唯一索引裁决后返回一个 task；不得插入重试、内容签名或新锁机制。
    3. 证明无 request id 的同资产并发请求可创建多条 active `gen_asset_image`，各自 seed/prompt id 不共享；不得错误复用 `uq_tasks_active_target`。
    4. 以真实队列/DB 保持入队锁定，验证入队后资产、风格、模板、磁盘 workflow 变化不改已 claim payload；worker seam 只读取冻结内容。
    5. 新增独立 task-system mock 竞态用例；不得把并发要求塞回基础 API 用例或修改 C004 tests。
  - R：R4；PRD §3.2 task snapshot、§6.1 request_id/多任务。
  - 验收方式：并发 barrier 后断言 task 行数/id/seed/payload；终态重放仍返回原 task；变更 target/note 为结构化 409；快照对象不被回写。
  - 应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/task_system/test_c007_enqueue_races.py
    ```
  - 2026-08-28 实际结果：定向测试 `3 passed in 1.56s`；在新建隔离 PostgreSQL 数据库完成迁移后，完整 `pytest` 为 `73 passed in 25.70s`；原始输出见 `.work/c007/T6-test.log`。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有 task`；`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`。

- [ ] **T7 交付生成 PNG 的正式落盘、最终事务和同步补偿服务**
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
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C007 资产出图事务与文件一致性：生成 PNG 校验/sha256/原子落盘、首版 current、修订竞态保存非 current、缓存/图片/done 同事务、失败补偿入 trash`。

- [ ] **T8 组装并注册 gen_asset_image handler 的完整 GPU/Comfy 流水线**
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

- [ ] **T9 接通 running cancel 的 targeted Comfy interrupt 与最终竞态**
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
  - 计划测试层级：任务系统 mock。
  - 追溯行：`§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断`；`C007 GPU/Comfy 资源生命周期：cache miss wake/chat、提交前 sleep、WS progress/history 输出、取消 interrupt、finally free，且 vLLM/Comfy 不并发`。

- [ ] **T10 交付 R11 图片调试字段的条件 API 合同**
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
  - 计划测试层级：API 集成。
  - 追溯行：`R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot`。

- [ ] **T11 在设置页交付系统诊断面板**
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
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用（仓库没有前端自动测试框架；后端 health 运行时合同已由 T3 对应追溯行覆盖）。

- [ ] **T12 在资产页交付意见、生成、terminal 刷新、抽卡画廊与 debug 展示**
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

- [ ] **T13 完成真实 M3 纵向验收、全量回归与追溯回填**
  - 依赖：T0-T12 全部完成。
  - 改动/证据清单：
    1. 使用新建隔离 PostgreSQL 数据库和隔离 DATA_DIR 跑全部定向/完整测试；任何已有 uvicorn 必须先停止或切换 DSN，避免 advisory lock/历史数据污染。
    2. 真实环境通过设置 API 写入需求方提供/确认的含三个变量 `zimage` 内容；读回逐字一致。占位未获确认时明确报告真实语义验收未完成，不勾选本 task。
    3. 选择已有 current 图片的资产：相同意见连续成功两次，证明第二次 hash hit/chat=0、seed/版本不同；编辑描述后第三次 hash 改变/chat=1。另用无 current 资产证明安全首版 current。
    4. 用真实 vLLM/Comfy 记录 wake/chat/sleep/submit/progress/history/view/free 顺序和任务日志；执行期间采样 GPU 进程/显存，确认无 LLM/Comfy 推理重叠。
    5. 验证真实 `/system/health`、资产页、设置页、任务中心、媒体 URL、debug false/true；不得用 mock/占位图冒充。
    6. 回填本 change 新增测试的真实 pytest node ID 到准确 TRACEABILITY 行；不得修改/弱化任何既有测试。
    7. 运行 full pytest、frontend build、Alembic current/check、diff/check/范围扫描，保留原始输出；发现失败不得勾选或提交。
  - R：R4、R11；PRD §2.1(5,9)、§3.1-§3.3、§3.5、§5、§6.1-§6.4、§7-§9、§11 M3、§12。
  - 验收方式与应运行命令：
    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m alembic current
    python -m alembic check
    python -m pytest -q tests/unit/test_c007_workflow_binding.py tests/unit/test_c007_asset_image_inputs.py tests/api/test_c007_health.py tests/api/test_c007_generate_asset_image.py tests/api/test_c007_prompt_visibility.py tests/task_system/test_c007_enqueue_races.py tests/task_system/test_c007_asset_image_commit.py tests/task_system/test_c007_gen_asset_image.py tests/task_system/test_c007_cancel_interrupt.py tests/task_system/test_c007_resource_lifecycle.py
    python -m pytest -q

    Set-Location D:\ai_drama_studio\frontend
    npm run build

    Set-Location D:\ai_drama_studio
    git diff --check
    git status --short
    rg -n -i "generation_runs|continuity|context_loop|fl2v|audio|candidate shot|候选分镜|资产别名|模板版本" backend frontend/src
    ```
    真实浏览器/HTTP/GPU证据按 spec AC-02、AC-04、AC-09、AC-10、AC-15、AC-16 保存；命中既有合法 `clips.generation_mode` 预留时只核对未新增读写，不把单纯文本命中误报为失败。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：本 change 使用的 `R4 input_hash 缓存...`、`R11 提示词可见性...`、`§3.3 编辑风格或模板...`、`§6.1 取消...`、`§6.1 去重与幂等...` 以及三条 `C007 ...` 新增行；只回填实际覆盖的 node ID。

- [ ] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）
  - R：无；PRD 章节：不适用，依据 AGENTS §7 的真实环境与命令证据纪律。
  - 验收方式与命令：对照 T0/T13 原始输出更新地址、版本、启动命令、真实测试结果与新坑；若无持久事实，在完成报告精确写“无”。运行 `git diff -- NOTES.md` 核对只记录真实事实。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用。

- [ ] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）
  - R：无；PRD 章节：§6-§8；依据 `DECISIONS.md` 的跨 change 收录边界。
  - 验收方式与命令：对照实现是否形成 PRD/AGENTS 未直接规定且约束 C009+ 的长期决定；只在完成报告列候选，不擅自修改 `DECISIONS.md`。运行 `git diff -- DECISIONS.md` 必须为空。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用。

- [ ] change 文档与 commit 状态一致
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
