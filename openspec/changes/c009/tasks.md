# C009 执行任务

## 执行规则

- 一次只执行需求方点名的 task；该 task 的实现、计划测试、追溯回填与原始日志全部通过后才可勾选。任一命令失败、外部门槛不满足或出现会改变可见行为的歧义，立即停止并报告，不继续后续 task。
- 开始实现前以 T0 记录的 commit 为 C009 baseline。不得把 Sol 已有文档 diff、`.work/`、下载目录文件或无关工作区改动夹入实现 commit。
- 除 T2 的三文件窄授权外，不得修改、删除、skip、改名或改弱既有测试；新增测试前先确认归属本文件标注的 TRACEABILITY 准确行名，实现后回填真实 pytest node ID。
- 所有 PostgreSQL 集成/任务测试使用按 NOTES.md 创建的全新隔离数据库并显式导出 `DATABASE_URL`；原始命令与退出码保存到 `.work/c009/Txx-*.log`。测试 mock 不得连接真实 8001/8188。
- C009 不新增 migration、前端实现、demo/验收 endpoint、长期 driver 或兼容层。临时 Sol/Luna 诊断脚本只能放 `.work/c009/probe-*.py`，不提交、不得替代计划测试。
- 实现失败直接 failed 并保留完整 error_msg；不得增加重试、静默 fallback、preset 填图、默认 prompt、requested_duration 伪造 actual_duration 或吞异常。

## 任务

- [x] **T0 — 锁定 C009 baseline 与外部依赖开工证据**

  - **依赖：** C008 已归档且 C009 spec/tasks/PRD/TRACEABILITY 规划提交完成；无实现 task 先于本项。
  - **交付：** 在 `.work/c009/` 保存 baseline commit、`git status --short`、C008 archive/changes 位置、两个需求方工件路径/字节数/SHA256，以及 Comfy/vLLM/DB 当前仅“可达/不可达”的现场结果；不启动模型、不提交 workflow、不修改仓库。
  - **R：** 无；PRD §11 M4、§12.1-§12.4。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`；`C009 真实 MiniMax workflow/template 视频闭环`。
  - **验收方式与命令：** 在仓库根执行并把完整输出与 `$LASTEXITCODE` 写入 `.work/c009/T00-baseline.log`：

    ```powershell
    New-Item -ItemType Directory -Force .work/c009 | Out-Null
    $c009BaselineSha = (git rev-parse HEAD).Trim()
    $c009BaselineSha | Set-Content .work/c009/baseline-sha.txt
    $c009BaselineSha
    git status --short
    git log -1 --oneline -- openspec/archive/C008
    Test-Path openspec/archive/C008/spec.md
    Test-Path openspec/changes/c008
    Get-Item 'C:\Users\Administrator\Downloads\Minimax_H3_api_c009.json' | Select-Object FullName,Length
    Get-Item 'C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md' | Select-Object FullName,Length
    Get-FileHash -Algorithm SHA256 'C:\Users\Administrator\Downloads\Minimax_H3_api_c009.json'
    Get-FileHash -Algorithm SHA256 'C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md'
    ```

    期望：baseline 是单一 SHA；archive spec 存在、active c008 不存在；workflow hash 精确 `bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780`，模板 hash 精确 `e2a1638cf13e2853a263ebe7db383d2c7ce222780bc4a937ca38845c48d63f7a`。任一不符立即阻塞，不自行重做工件。

- [x] **T1 — 入仓唯一 MiniMax API workflow 与独立闭合绑定快照**

  - **依赖：** T0。
  - **交付：** 新增且只新增一个 `backend/workflows/minimax_h3_ref2v.json`，与需求方 API JSON 字节一致；保留现有 zimage-only `bindings.toml`、`load_binding_snapshot()` 和全部断言原样，新增唯一 `backend/workflows/minimaxh3.toml`（只含 `[comfy.minimaxh3]`）及显式 MiniMax snapshot loader，复用现有底层读取/路径/API object校验并增加 spec §6.2 的 prompt/seed/duration、九对 ref image/consumer、optional_refs=false 与 output node。不得按默认/临时路径特判，不建集合registry/version/兼容入口。
  - **R：** 无；PRD §8、§12.1、§0 范围围栏。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C009 MiniMax H3 工作流绑定、双 hash health 与既有测试窄演进`；`C007 Comfy 工作流绑定与诊断：API 格式、注入/输出路径、启动失败、workflow hash 与 /system/health`。
  - **验收方式与命令：** 新增 `backend/tests/unit/test_c009_workflow_binding.py`，逐项断言正确 MiniMax 快照及缺 section/字段、UI graph、路径逃逸、wrong leaf、ref 数量/唯一性/consumer 关联/output 的拒绝，并断言现有 zimage loader 仍拒绝额外 section；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/unit/test_c007_workflow_binding.py tests/unit/test_c009_workflow_binding.py
    Get-FileHash -Algorithm SHA256 workflows/minimax_h3_ref2v.json
    ```

    期望：pytest 全绿；仓库 workflow hash 精确为 T0 值；错误 fixture 均抛明确 WorkflowBindingError；未改既有 C007 test。

- [x] **T2 — 启动加载双绑定并演进 health 双 hash**

  - **依赖：** T1。
  - **交付：** lifespan 在 worker claim 前分别加载现有 zimage 快照与新增 MiniMax 快照；保留现有 `app.state.workflow_binding_snapshot` 指向 zimage，并增加明确的 MiniMax state，不建立通用 registry。health service/route 显式接收两个 hash，成功响应 `hashes` key 精确 `zimage,minimaxh3`，其他 vLLM/Comfy status/message 与一次探测合同不变。坏任一 binding 均拒绝启动。
  - **既有测试窄授权：** 只可在 `backend/tests/api/test_system.py`、`backend/tests/api/test_c007_health.py`、`backend/tests/api/test_c007_health_transport.py` 中修改 zimage-only hashes fixture/精确断言；每个文件其他断言逐条保留。新增 C009 行为写入新 `backend/tests/api/test_c009_health.py`，不得用窄授权文件替代专用测试。
  - **R：** 无；PRD §5 `/system/health`、§8 启动校验、§12.1。
  - **计划测试层级：** API 集成。
  - **追溯行：** `C009 MiniMax H3 工作流绑定、双 hash health 与既有测试窄演进`；“C001 基础设施 smoke（C007/C009 合法演进）：FastAPI 应用可启动，`/docs` 可访问，`/api/system/health` 返回当前双工作流诊断且测试不连接真实外部网络，通用 API 错误体符合约定”。
  - **验收方式与命令：** 先用 `git diff --` 人工逐断言比较三文件，再运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/api/test_system.py tests/api/test_c007_health.py tests/api/test_c007_health_transport.py tests/api/test_c009_health.py
    ```

    期望：全部通过；专用测试证明 minimaxh3 坏绑定在 claim 前失败；三既有文件 diff 只涉及 hashes fixture/断言且没有 skip/改名/删除/弱断言。

- [x] **T3 — 实现 shots/references/template/hash/seed 的纯函数合同**

  - **依赖：** T1。
  - **交付：** 新增单一职责的 C009 input 模块，交付 spec §5-§6.1：shots 全量快照与公开投影、enabled references 压实编号、活值/删除快照规则所需的纯数据验证、紧凑模板渲染、封闭 minimaxh3 schema/输出校验、R4 八成员序列化/hash；按 `GEN_CLIP_VIDEO_NAMESPACE=17c124be-f03e-5a69-b4e5-e3a63f62994b` 与仅含规范化 request_id 的 name 生成 UUIDv5 prompt id并取同一 UUID 低 63 bits 为 seed，无 request_id 使用随机 63-bit seed/UUID4。不要访问数据库、文件或网络。
  - **R：** R4、R9、R12；PRD §3.1、§3.4、§7。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C009 MiniMax prompt、完整 input_hash 与 cache`；`C009 references 活值/删除快照/压实编号与 R9`；`R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`。
  - **验收方式与命令：** 新增 `backend/tests/unit/test_c009_clip_video_inputs.py`，至少包含 slot1/3→subject1/2、三种资产存活分支、每个 hash member 单变、所有成员精确恢复得同hash而文本恢复但revision变化仍异hash、null/空串/空白区分、模板 placeholder/输出敌意矩阵；固定 UUIDv5 向量必须断言原始 `request_id=" abc "` → normalized `"abc"` → prompt id `3088d9e1-4253-5fff-896e-87e5f5312d20`、seed `679630015510424864`，并覆盖随机 seed 上下界；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/unit/test_c009_clip_video_inputs.py
    ```

    期望：全部通过；断言精确 JSON bytes/字段/顺序/值，不只判非空或 hash 不相等。

- [x] **T4 — 实现 1..9 references 的工作流深拷贝注入与裁剪**

  - **依赖：** T1、T3。
  - **交付：** 在 C009 input/workflow 模块按 binding 深拷贝并注入 built_prompt、整数 seed、requested_duration 秒、前 N 个安全 upload 路径；删除 k>N 的 LoadImage nodes 和逐项 consumer keys，submit 前验证无 sentinel/orphan/preset，原 snapshot 不变。不得用空串、第一张图或预设图填未用位置；不得在后端把秒换成帧。
  - **R：** R9；PRD §3.4、§6.2、§8。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C009 Comfy references 上传、动态工作流与敌意返回值`。
  - **验收方式与命令：** 新增 `backend/tests/unit/test_c009_workflow_inputs.py`，对 N=1/2/9 精确断言保留/删除 node IDs、consumer keys、三条注入值、upload 顺序、无 sentinel及原对象未变，并覆盖错 path/count/value；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/unit/test_c009_workflow_inputs.py
    ```

    期望：全部通过；1/2/9 三种输出都满足真实 workflow 结构，而不是仅构造最小假 JSON。

- [x] **T5 — 扩展 Comfy client 的图片上传并封闭视频输出解析**

  - **依赖：** T4。
  - **交付：** 在现有 ComfyClient 增加 multipart `/upload/image`，复用既有 submit/WS/history/view/interrupt/free；新增 C009 upload/history parser，按 spec §6.3 校验字段类型、数量、路径 segments、长度、type/format/output node，系统生成 task/reference 文件名，不读取 fullpath。HTTP/JSON/stream 异常原样抛出，无 retry/fallback。
  - **R：** R9、R10；PRD §6.2、§6.4、§8。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C009 Comfy references 上传、动态工作流与敌意返回值`；`C009 GPU/Comfy 资源生命周期、取消与失败`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_comfy_protocol.py`，通过正式 transport seam 精确断言 multipart 字段、每图一次、合法 response，并覆盖 null/穿越/U+0000/超长/扩展漂移/错 type、0/2 gifs、错 node/format/type/字段；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/task_system/test_c007_resource_lifecycle.py::test_client_protocol tests/task_system/test_c009_comfy_protocol.py
    ```

    期望：全部通过；所有敌意返回值在 submit/view 前被拒绝，测试不连接真实 8188。

- [x] **T6 — 引入成熟视频容器解析依赖与本地 MP4 临时文件合同**

  - **依赖：** T0。
  - **交付：** 在 `backend/pyproject.toml` 增加唯一成熟 Python 视频容器依赖（PyAV/`av`）；把 C008 `clips.py` 中已存在的 ClipVideo canonical relative/formal/trash path 逻辑原样提取为共享 video file 模块，并让 C008 delete 与 C009 共用这一个来源；在同模块增加系统 temp 路径、流式写入、至少一个 video stream、单一 container duration→finite positive seconds与sha256。不得复制第二套path规则、调用 PATH ffprobe/ffmpeg、手写容器解析或以 requested_duration fallback。
  - **R：** R6；PRD §3.4、§6.2、§6.4、§13.1。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 MP4 探测、文件/数据库事务与同步补偿`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_video_files.py`，用该库创建最小真实 MP4 fixture，覆盖正常/损坏/无 video stream/duration 缺失或非正/sha/path/temp cleanup；运行：

    ```powershell
    Set-Location backend
    python -c "import av; print(av.__version__)"
    python -m pytest -q tests/task_system/test_c009_video_files.py tests/api/test_c008_clip_delete.py tests/api/test_c008_review_trash_lifecycle.py
    ```

    期望：依赖可从干净 backend 环境导入；全部测试通过；测试主动清空 PATH 中 ffprobe 可见性后仍能解析；无 temp/orphan。

- [x] **T7 — 为全局 request_id 增加统一 transaction-scoped 临界区**

  - **依赖：** T0。
  - **交付：** 在 TaskQueue 暴露一个 PostgreSQL transaction-scoped request-id lock helper；既有公开入口中只有 gen_asset_image 接受 request_id，令其在首次 `find_request`/业务 mutation 前调用，C009 后续复用。gen_assets/gen_shots 没有该字段，不修改。使用数据库对 normalized 完整字符串+固定命名空间计算 lock key，不新增 migration/lock table/Python hash/重试；无 request_id 不加锁。保持既有可见身份语义。
  - **R：** 无；PRD §6.1 去重与幂等、§3.2 快照；D-007。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 generate-video 入队快照、user_note 与全局 request_id 并发幂等`；`§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务，并按冻结的 UUIDv5 映射复用 seed/prompt id`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_request_id_lock.py`，以至少两个独立连接直接命中生产lock helper，验证相同id阻塞至前一事务提交、不同id不互相等待，并验证既有gen_asset_image同身份一行与terminal后重放；C009跨type身份竞争在T9服务存在后补入T9新测试；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/task_system/test_c009_request_id_lock.py tests/task_system/test_c007_enqueue_races.py
    ```

    期望：全部通过；探针明确观察锁前/等待/提交后顺序，不以 sleep-only 或最终行数替代锁屏障。

- [x] **T8 — 增加 Clip generation_state 的事务内生命周期聚合**

  - **依赖：** T7。
  - **交付：** 新增单一生产聚合函数与一个明确 queue lifecycle callback/协调入口；为后续R5/R5a/R10增加queue拥有的“直接记录terminal failed”方法（payload仍精确三键、progress0、started null、finished/error非空、同事务事件），并在queued enqueue、立即failed、claim、done、worker failed、cancel、restart recovery的当前事务中，按running>queued>最新non-canceled terminal>empty锁Clip并投影。只改值时updated_at，不增Clip revision/不改freshness；不 `FOR UPDATE` 全部Task，不建projection/generation_runs/registry。
  - **R：** 无；PRD §3.2 状态模型、§6.1 claim/cancel/recovery 与 C009 2026-09-01 裁决。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 多任务 generation_state 聚合与重启恢复`；`§6.1 重启恢复：遗留 running 任务变为 failed("server restarted")，queued 任务保留并继续消费`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_generation_state.py`，用独立连接覆盖所有优先级、finished_at/id tie、cancel ignored/回退、restart、Task mutation 与 Clip state 同 commit visibility、Clip revision/freshness不变；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/task_system/test_c009_generation_state.py tests/task_system/test_task_queue.py::test_restart_fails_running_and_continues_queued tests/task_system/test_task_queue.py::test_queued_cancel_is_terminal
    ```

    期望：全部通过；每个 transition 在另一连接只能同时看到旧旧或新新，不出现新 Task+旧 Clip。

- [x] **T9 — 交付 generate-video API 与完整 enqueue/立即失败合同**

  - **依赖：** T2、T3、T7、T8。
  - **交付：** 增加严格 request/response schema、route 与 enqueue service；实现 user_note 三态/identity-first、R5/R5a/R10 复检、立即 failed Task、成功 payload 三键、活 assets/references、template/style/workflow快照、R4 cache判定、seed/prompt_id及 post-commit event。当前 task 只接受单事务确定性/任务 mock，不在此项宣称跨连接锁屏障（由 T10）。按 TRACEABILITY 窄授权只在既有 C008 contract 用例的精确 `expected_paths` 增加 `/api/clips/{clip_id}/generate-video`；本项不得提前加入 `gen_clip_video` handler或 T15 take paths，其他断言逐字不动。
  - **R：** R4、R5、R5a、R6、R9、R10、R12；PRD §3.1-§3.4、§5、§6.1-§6.2、§7。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`；`C009 generate-video 入队快照、user_note 与全局 request_id 并发幂等`；`C009 立即 failed Task 与结构化错误`；`C009 references 活值/删除快照/压实编号与 R9`；`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`；`R10 缺图即失败：任一启用槽位无可用图时任务失败并指出槽位与原因`。
  - **验收方式与命令：** 新增 `backend/tests/api/test_c009_generate_video.py` 与 `backend/tests/task_system/test_c009_enqueue_video.py`；精确覆盖 `{}`、三态 note、replay/no-id、成功 payload、cache hit/miss、slot分支、与gen_asset_image同request_id跨type竞争，以及每种 R5/R5a/R10 failed task 的 status/timestamps/error/无 claim/无外调；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/api/test_c008_contract_errors.py tests/api/test_c009_generate_video.py tests/task_system/test_c009_enqueue_video.py
    ```

    期望：全部通过；R5/R5a/R10 route 精确 202而非409/422，Task从未 queued；同步404/409/422/500分流与 spec 一致。

- [x] **T10 — 加固 enqueue 与源 mutation 的 Clip 行提交屏障**

  - **依赖：** T9。
  - **交付：** 只读发现 enabled 槽位活 asset ids后先按id锁 Asset，再锁目标 Clip作为 C006/C008 正式 Clip/Slot/Shot/Asset mutation 的提交屏障，随后重读关系/Shot/绑定/Slot/current Image并复检；仅对不会回写 Clip 的 Project/Style/Template 行在 Clip 后加锁。不得锁 Shot/AssetImage/全部Task，也不得先持Clip再等待Asset而形成与既有 Asset→Clip mutation 的反向锁序；不改 C008 mutation语义、不建新锁层。确认 explicit user_note mutation 与 failed/queued Task 同事务。
  - **R：** R4、R5、R5a、R9、R10、R12；PRD §3.2 任务快照、§3.4 生成复检。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 generate-video 入队快照、user_note 与全局 request_id 并发幂等`；`C009 references 活值/删除快照/压实编号与 R9`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_enqueue_locks.py`，以独立连接和明确 barrier 分别竞争 Shot PATCH、slot enabled/override、仍绑定及已从Shot解绑但槽位保留的 Asset PATCH/current/delete、Style/Template PATCH；活Asset竞争在Asset锁串行，其余会级联Clip的mutation在Clip屏障串行，并证明无反向死锁；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/task_system/test_c009_enqueue_locks.py
    ```

    期望：全部通过；每条竞态只得到两个可串行化结果之一，payload/worker 只用一份冻结副本，无混合字段、死锁或额外重试。

- [x] **T11 — 实现 gen_clip_video worker core 的 prompt/GPU/Comfy/取消主流水线**

  - **依赖：** T4、T5、T6、T9。
  - **交付：** 新增可直接测试但尚不加入 main handler map 的唯一 gen_clip_video handler core；只读 ClaimedTask payload，实现 cache miss wake/chat/严格 prompt、cache hit skip chat、两路均 sleep、按序 upload、动态 workflow submit、WS progress/history/view 到 temp、各安全点 cancel、`finally free` 与主/cleanup双错误。扩展 cancel API 对 running gen_clip_video 使用 snapshot prompt_id best-effort interrupt；最终 ClipVideo DB commit 与正式 handler 注册由 T13 一次接通，T11 结束时不得暴露一个会 done 但无 take 的生产 handler。
  - **R：** R4、R9、R10、R11；PRD §6.1-§6.4、§7、§8。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C009 MiniMax prompt、完整 input_hash 与 cache`；`C009 GPU/Comfy 资源生命周期、取消与失败`；`§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_gen_clip_video.py`，精确断言 miss/hit 调用序列、一次调用、progress、snapshot值、敌意 vLLM/Comfy failure、每个安全点 cancel、interrupt失败意图不回滚、free双错误；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/task_system/test_c009_gen_clip_video.py tests/task_system/test_c007_cancel_interrupt.py
    ```

    期望：全部通过；测试不连接真实外部端口；失败均一次 failed且无 retry/fallback/cache/take/formal。

- [x] **T12 — 定向证明跨进程 GPU/Comfy 资源生命周期**

  - **依赖：** T11。
  - **交付：** 新增跨进程/真实 HTTP stub 测试，不新增生产 demo；运行生产 handler/clients，记录 wake/chat/sleep 与 Comfy upload/submit/history/view/free 的真实时间区间、cache hit路径和中途 transport failure。若测试暴露实现问题，只修生产根因并重跑。
  - **R：** 无；PRD §6.2-§6.4、§8。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 GPU/Comfy 资源生命周期、取消与失败`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_resource_lifecycle.py`；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/task_system/test_c009_resource_lifecycle.py
    ```

    期望：stub 确实收到请求；vLLM/Comfy活跃区间无重叠；hit不chat但sleep；所有分支free且本地服务/子进程/端口退出；只看 mock method list 不算通过。

- [x] **T13 — 完成 MP4 探测、ClipVideo/cache/freshness 与 done 的原子提交并注册 handler**

  - **依赖：** T6、T8、T11。
  - **交付：** 新增 C009 commit service：验证 temp MP4/actual_duration/sha、锁 Task/Clip/source/current takes、插 row取 id、canonical rename、首 take current、cache miss更新、source revision反竞态、调用 queue.complete与聚合；数据库失败移 formal 到 canonical trash，temp总清理，主/补偿错误同时保留。保留 T11 `gen_clip_video_handler` 为返回 `GeneratedClipVideo | None` 的可测试生成 core；新增唯一正式队列适配器 `gen_clip_video_task_handler`，顺序执行 core → commit service → committed event并阻止 outer complete 重复副作用。只有本项成功后才把该适配器以 `gen_clip_video` key 加入 main handler map，使公开 route 首次形成完整端到端执行路径。按 TRACEABILITY 窄授权仅在此时向既有 C008 contract 用例的精确 handler 列表增加 `gen_clip_video`，不得改动 path集合或其他断言；同时只把 C007 `test_pipeline_handler_registration` 的视频 handler 不存在断言替换为生产 `gen_clip_video_task_handler` identity，保留资产 handler identity及该文件其他测试原样。
  - **R：** R4、R11；PRD §3.2、§3.3、§6.2、§6.4。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`；`C007 GPU/Comfy 资源生命周期：cache miss wake/chat、提交前 sleep、WS progress/history 输出、取消 interrupt、finally free，且 vLLM/Comfy 不并发`；`C009 MP4 探测、文件/数据库事务与同步补偿`；`§3.3 片段生成成功且修订未变：相关分镜 normal、片段 fresh、新 take 落盘；无其他 active 视频任务时 ready，有 active 时按 C009 聚合`；`§3.2 完成判定反竞态：source_revisions 全一致时回写 fresh/normal；任一不一致时产物仍保存且不得覆盖 stale/changed；generation_state 始终按 C009 聚合`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_clip_video_commit.py`，覆盖首/后续 take、全等/Clip/Shot/Asset drift或删除、actual偏差、每个DB写阶段失败、formal/trash补偿和补偿失败；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/api/test_c008_contract_errors.py tests/task_system/test_c007_resource_lifecycle.py::test_pipeline_handler_registration tests/task_system/test_c009_video_files.py tests/task_system/test_c009_clip_video_commit.py
    ```

    期望：全部通过；C008 精确 handler 集合与 C007 两个生产 handler identity 同时成立；另一连接只见旧整体或 ClipVideo/cache/status/done/聚合新整体；失败无未报告 temp/formal/orphan row。

- [x] **T14 — 验证 cancel 与视频最终提交的原子胜方及多任务交错**

  - **依赖：** T13。
  - **交付：** 新增竞态回归测试，覆盖 cancel marker在最终事务前/中/后、多任务 active优先与 immediate failed 插队；如失败只修 queue/commit/aggregate根因。不得通过 sleep碰运气或放宽为“任一状态”。
  - **R：** 无；PRD §3.2、§6.1、§6.4。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C009 GPU/Comfy 资源生命周期、取消与失败`；`C009 多任务 generation_state 聚合与重启恢复`；`§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断`。
  - **验收方式与命令：** 新增 `backend/tests/task_system/test_c009_cancel_commit_race.py`，使用显式 barrier 定向控制两事务；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/task_system/test_c009_cancel_commit_race.py tests/task_system/test_c009_generation_state.py
    ```

    期望：取消胜方=canceled且无 take/cache/formal；提交胜方=done且完整 take，后 cancel 409；任一时刻聚合优先级精确且不改 freshness/revision。

- [x] **T15 — 交付 take list/current/delete 与 ID 媒体生命周期**

  - **依赖：** T13。
  - **交付：** 增加 ClipVideoResponse 与 list/current schemas/routes/services、current no-op/跨Clip校验/唯一切换、current禁删、noncurrent canonical trash/DB补偿，以及 `/media/clip-videos/{id}` canonical重算/`video/mp4`。不改Clip/Shot状态，不返回file_path。按 TRACEABILITY 窄授权仅在此时向既有 C008 contract 用例的精确 `expected_paths` 增加 `/api/clips/{clip_id}/videos` 与 `/api/clips/{clip_id}/current-video`，不得改动 handler集合或其他断言。
  - **R：** 无；PRD §5 片段/媒体 API、§3.3、§6.4。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`；`C009 take 列表、current、删除与媒体生命周期`。
  - **验收方式与命令：** 新增 `backend/tests/api/test_c009_clip_videos.py` 与 `backend/tests/api/test_c009_clip_video_lifecycle.py`，覆盖id ASC、唯一current/no-op/跨Clip、current409、noncurrent204、坏path/缺文件、DB失败/恢复失败、同名canonical trash；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/api/test_c008_contract_errors.py tests/api/test_c009_clip_videos.py tests/api/test_c009_clip_video_lifecycle.py
    ```

    期望：全部通过；每条错误精确 status/code/message；文件与DB在正常/失败/双失败路径均与spec一致。

- [x] **T16 — 收紧 C009 API 敌意输入、seed/DEBUG 与错误体**

  - **依赖：** T9、T15。
  - **交付：** 对 generate/list/current/delete/media 的 path/body/content type/unknown/U+0000/request_id 边界做统一校验；public ClipVideo seed及DEBUG snapshot seed投影十进制string；DEBUG false/true字段精确；默认不泄露prompt/snapshot/path。不得修改通用409/422语义或吞内部错误。
  - **R：** R11；PRD §5、§6.4、§7，C009 seed裁决。
  - **计划测试层级：** API 集成。
  - **追溯行：** `C009 API 敌意输入、公开 seed、DEBUG 与媒体错误体`；`R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot`；`C009 立即 failed Task 与结构化错误`。
  - **验收方式与命令：** 新增 `backend/tests/api/test_c009_contract_errors.py` 与 `backend/tests/api/test_c009_seed_debug.py`，用SQL计数器证明边界前拒绝，并精确断言外层/内层key集合、code/message、2^63-1字符串、DB JSON仍整数；运行：

    ```powershell
    Set-Location backend
    python -m pytest -q tests/api/test_c009_contract_errors.py tests/api/test_c009_seed_debug.py tests/api/test_c007_prompt_visibility.py tests/api/test_c007_seed_contract.py
    ```

    期望：全部通过；无恒真、只判非空/存在性或未校验数量内容的弱断言。

- [x] **T17 — 真实生产通路验收给定模板与 MiniMax workflow**

  - **依赖：** T0-T16；PRD §12 四项现场门槛全部满足。任一不满足立即阻塞并列当前证据，不修改代码伪造通过。
  - **交付：** 用 NOTES 隔离库、生产 Uvicorn、真实 vLLM/Comfy，先确认queue空；通过正式 `PATCH /api/prompt-templates/minimaxh3` 写入给定模板并 GET逐字读回；用正式API分别生成1-reference与至少2-reference视频（其中一条requested_duration=5），观察WS/task/DB/log/history/media/MP4；再触发一条真实可控异常。结束确认vLLM sleeping、Comfy free/queue空。所有原始证据写 `.work/c009/`，不新增driver。
  - **R：** R4、R5、R5a、R6、R9、R10、R11、R12；PRD §3.1-§3.4、§5-§8、§11 M4、§12。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C009 真实 MiniMax workflow/template 视频闭环`。
  - **验收方式与命令/人工检查：** 使用 PowerShell 直接调用生产 API，不创建 repo脚本：

    ```powershell
    $api = 'http://127.0.0.1:8000/api'
    $template = Get-Content -Raw 'C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md'
    Invoke-RestMethod -Method Patch -Uri "$api/prompt-templates/minimaxh3" -ContentType 'application/json' -Body (@{content=$template} | ConvertTo-Json -Compress)
    Invoke-RestMethod -Method Get -Uri "$api/prompt-templates"
    Invoke-RestMethod -Method Get -Uri "$api/system/health"
    Invoke-RestMethod -Method Post -Uri "$api/clips/<clip_id>/generate-video" -ContentType 'application/json' -Body '{}'
    Invoke-RestMethod -Method Get -Uri "$api/tasks/<task_id>"
    Invoke-RestMethod -Method Get -Uri "$api/clips/<clip_id>/videos"
    Invoke-WebRequest -Uri "http://127.0.0.1:8000/media/clip-videos/<video_id>" -OutFile '.work/c009/accepted-<video_id>.mp4'
    ```

    将占位 id 换为本次真实 API 返回值并在日志记录映射。期望：health精确双hash；模板content逐字相等；两任务done、MP4可播放、seed string、actual_duration>0、上传/Subject顺序一致、无preset/音频；异常Task failed且完整原因/无retry/副作用；最终外部资源空闲。完成报告明确区分“合同/通路已证明”与“审美未自动证明”。

- [x] **T18 — 回填 TRACEABILITY 并执行隔离库全量验证与范围审计**

  - **依赖：** T1-T17 全部计划验收通过。
  - **交付：** 把所有 C009 `待填` 回填为真实 pytest node ID或T17原始证据路径；每个新增测试至少归属一行，删除阶段性重复/无归属新测试（不得删改既有测试）；在全新库跑 migration/完整pytest/前端build；审计 baseline..HEAD 每个文件对应task、零migration/UI/围栏/重试/versioning；不在失败时勾选。
  - **R：** R4、R5、R5a、R6、R9、R10、R11、R12；PRD §0、§3、§5-§8、§11 M4。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`；本 change 所有 C009 专用追溯行。
  - **验收方式与命令：** 按 NOTES 的隔离数据库块创建全新 DB并显式导出URL，然后保存每条原始输出/exit code：

    ```powershell
    Set-Location backend
    python -m alembic upgrade head
    python -m alembic current
    python -m alembic check
    python -m pytest -q
    Set-Location ..
    npm --prefix frontend run build
    git diff --name-status $(Get-Content .work/c009/baseline-sha.txt)..HEAD
    git diff --name-only $(Get-Content .work/c009/baseline-sha.txt)..HEAD -- backend/alembic backend/app/models frontend
    rg -n "\| 待填 \||C009 专用新增用例待填" openspec/TRACEABILITY.md
    ```

    T0 必须把纯SHA另存 `.work/c009/baseline-sha.txt` 供命令读取。期望：upgrade/current/check唯一既有head且check无操作；完整pytest/build均exit0；migration/frontend无C009 diff；最后一条 rg 无输出（exit 1，表示没有未回填数据行）；范围外关键字只能出现在既有围栏/枚举预留或spec/tasks否定说明，不得出现在新增实现。

- [x] **T19 — 形成可审查的 C009 完成报告与走查证据索引**

  - **依赖：** T18。
  - **交付：** 创建不提交的 `.work/c009/completion-report.md`，固定五节：1) baseline/commit范围与文件→task映射；2) checkbox/TRACE用例ID；3)隔离库 migration/完整pytest/build原始结果；4)真实外部依赖与资源最终态；5)“操作 → 观测值”走查。第5节覆盖1-reference、多-reference、take切换/媒体与至少一条异常（R10立即failed或真实外部failed），逐项引用原始日志；未验证项明确写未验证。
  - **R：** 无；PRD §11 M4 验收、§12。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`；`C009 真实 MiniMax workflow/template 视频闭环`。
  - **验收方式与人工检查：** 执行 `Get-Content -Raw .work/c009/completion-report.md`，逐条反查 T00-T18 log、git commits、TRACE IDs、DB/task/media记录；期望五节齐全，第5节每条同时有操作、原始观测值、期望真假结论，不能只有“页面/任务正常”“测试全绿”。

- [x] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）

  - **R：** 无；PRD §12 外部环境与运行事实。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`。
  - **验收方式与命令：** `git diff -- NOTES.md`；只写 T17/T18 实际验证且仍有复用价值的命令、端口、版本与坑，历史/未验证事实明确标注。确无内容时保持文件不变，并在完成报告写“NOTES.md：无”。

- [x] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）

  - **R：** 无；PRD §3.2、§6.1 与需求方 2026-09-01 C009 裁决。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C009 多任务 generation_state 聚合与重启恢复`；`C009 generate-video 入队快照、user_note 与全局 request_id 并发幂等`。
  - **验收方式与人工检查：** 完成报告逐项列“立即failed任务、多任务聚合、user_note三态、public seed、全局request-id事务锁”是否应进入 DECISIONS及理由；本 task 不自行修改 DECISIONS。无候选时精确写“DECISIONS.md 候选项：无”。

- [x] change 文档与 commit 状态一致

  - **R：** 无；PRD §11 M4，AGENTS Change纪律。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C009 范围、零 migration 与完整回归/完成证据`。
  - **验收方式与命令：** 执行 `git status --short`、`git diff --check`、`git diff --name-status <T0-baseline>..HEAD`、`git log --oneline <T0-baseline>..HEAD`，并逐项对照spec/tasks checkbox/完成报告；期望仓库提交包含全部已勾选交付且不含`.work/`/下载文件/无关改动，未勾选项未被宣称完成。
