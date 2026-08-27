# C006 M2 gen_shots Tasks

## 执行纪律

- 本文件只授权 C006。执行者不得新增 migration、表、列、索引、候选分镜、分镜增删/拆分/合并/排序、clip 创建/视频生成、资产出图、导演台或其他后续能力。
- 一次只执行一个明确 task；每个 checkbox 只有在列出的验收命令和人工检查都取得真实证据后才可勾选。失败不重试、不吞异常、不用 mock/假数据冒充真实外部验收。
- 既有测试不得修改、删除、跳过或弱化；本 change 只允许新增下列明确命名的 C006 测试。若既有测试与 spec 冲突，立即停止并报告，不自行改测试。
- 自动测试只能归属本文件逐项写明的 `openspec/TRACEABILITY.md` 原有行。Luna 不修改 TRACEABILITY；完成后提交实际 pytest node ID 和输出，由 Sol 审计并维护追溯表。
- 执行开始先记录 `git rev-parse HEAD` 为 `C006_BASE`；保留工作区已有非 C006 改动，不回滚、不覆盖。
- 正式模板/真实 vLLM 验收库与干净 pytest 库严格分离。完整 pytest 只跑迁移初始占位模板的全新隔离库；正式库用于模板、真实 vLLM 和浏览器走查。

## 可执行 tasks（按依赖排序）

### T1 正式模板与真实 vLLM 动态 schema gate

- [x] 在明确的 C006 正式验收库通过现有设置 API 保存 spec §5.1 `script2shots` 完整正文并逐字读回；使用当前真实 vLLM 执行 wake 和一条 user message 的 C006 动态 schema 请求，证明模型、温度 `0.2`、封闭枚举与动态 asset id enum 可用。发往 vLLM 的 schema 按 spec §6.2 不含其 grammar 未实现的 `uniqueItems`；重复 asset id 留给 T4 的后端硬校验。不得把模板写进 migration/代码常量，也不得修改干净 pytest 库的占位种子。
  - **前置 task：** 无；直接复用已通过 C005 验收且当前仍可达的正式环境：API `http://127.0.0.1:8000`（连接既有 C005 正式验收库 `ai_drama_studio_c005_acceptance_20260826`，当前有 1 个项目、1 集、5 个资产，`script2assets` 为正式内容而 `script2shots` 仍为占位）、vLLM `http://127.0.0.1:8001`、模型 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`。开始时重新只读核对这些事实；`C006_ACCEPTANCE_DATABASE_URL`、`C006_API_BASE`、`VLLM_BASE_URL`、`VLLM_MODEL` 这些 shell 变量未预设本身不是阻塞，也不得要求需求方重复提供。若真实端点不可达、API 所连库与上述证据不符或模型 id 改变，才保持未勾选并报告外部状态变化。
  - **R：** 无；对应 PRD §7 模板变量/动态 schema、§12.2 正式模板、§12.4 PostgreSQL/vLLM 地址。
  - **范围：** 只部署已冻结的 `script2shots` 和验证外部依赖；不创建业务数据表、不实现 handler、不把真实模板提交进 migration。
  - **覆盖 AC：** AC-02、AC-07。
  - **验收方式：**
    1. 不重启或切换当前正式 API；先对 `http://127.0.0.1:8000` 调用项目、剧集、资产和 `GET /api/prompt-templates`，只读核对上述 C005 环境证据。记录更新前 `script2shots` 占位状态，再 `PATCH /api/prompt-templates/script2shots` 保存 spec §5.1，最后 GET 逐字比较并报告脱敏 database name 与 HTTP 状态。
    2. 调用 `Invoke-RestMethod "http://127.0.0.1:8001/v1/models"`，必须返回 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`；调用现有 wake endpoint 后，以正式库中两条真实资产 id 构造 spec §6.2 schema（不得含 `uniqueItems`），发送且只发送完整 user message，核对返回只含 `shots`、字段齐全、asset_ids 只能取动态 enum、景别/运镜合法、时长 1..5。2026-08-27 已完成的原 schema 诊断请求以 HTTP 400 结束，只作为兼容性证据，不算本 gate 成功；修订后请求是按新合同进行的验收，不得在失败后自动重发。
    3. 读取 vLLM 请求证据，确认温度为 `0.2`、无隐藏业务 system message、无自由文本 fallback；真实请求失败时保留错误并停止，不反复重试。
  - **计划测试层级：** 不新增自动测试；理由：这是 PRD §12 外部配置/真实模型 gate，输出质量和远端协议不能由稳定 pytest mock 证明，且 TRACEABILITY 没有独立的模板部署行。
  - **追溯行：** 不适用。

### T2 impact/token API

- [ ] 实现无 body 的 `POST /api/episodes/{id}/generate-shots/impact` 及 10 分钟进程内不透明 token：先做 episode/输入边界校验，准确快照 clip revision、video id 和 override 媒体引用，按 spec §3.1 返回固定响应；预检只读、重启失效，R1 只由 T3 generate 最终裁决。
  - **前置 task：** T1。
  - **R：** R3；对应 PRD §3.1、§5 生成动作、§11 M2。
  - **范围：** 只实现影响读取与 token 生命周期；不创建 task、不删除数据、不持久化 token、不实现生成 handler。
  - **覆盖 AC：** AC-03、AC-04、AC-17。
  - **验收方式：**
    1. 新增并运行 `Set-Location backend; python -m pytest -q tests/api/test_c006_generate_shots.py::test_generate_shots_impact_token_binds_current_snapshot`：验证 0/0 固定 null 响应、非空计数、TTL=600、非空 body 422、无资产时仍只读返回当前影响、预检无副作用，以及 clip/video/revision 集变化但计数不变时旧 token 409。
    2. 真实 API 获取 token 后重启后端，再提交旧 token，必须 409 且没有 task；不得为测试加入持久 token 表或特殊分支。
  - **计划测试层级：** API 集成。
  - **追溯行：** `R3 生成分镜覆盖：impact/token 校验；新分镜成功后才删除旧数据并移入 trash；LLM 失败旧数据不动`。

### T3 generate-shots 入队、快照与 active 去重

- [ ] 实现 `POST /api/episodes/{id}/generate-shots` 的精确 body/token/前置条件合同；在同一入队真相中渲染正式模板、冻结四字段资产、动态 schema、替换结构与 source revisions，以三键 payload 和 `request_id=null` 入队，并保持同目标 active 冲突 409。
  - **前置 task：** T2。
  - **R：** R1、R3；对应 PRD §2.1(4,11)、§3.1-§3.2、§5、§6.1-§6.2、§7。
  - **范围：** 只到 queued task；请求线程不得调用 vLLM，不执行覆盖，不增加 request_id/hash/If-Match/模板版本。
  - **覆盖 AC：** AC-04、AC-05、AC-06、AC-07、AC-17。
  - **验收方式：**
    1. 新增并运行 `Set-Location backend; python -m pytest -q tests/api/test_c006_generate_shots.py::test_generate_shots_requires_assets`，核对项目无 character/scene 资产时 generate 为固定结构 409、task 数不变；impact 的只读成功不得绕过此裁决。
    2. 新增并运行 `python -m pytest -q tests/api/test_c006_generate_shots.py::test_generate_shots_enqueues_exact_snapshot_and_dynamic_schema`，核对 body 矩阵、202 精确响应、task 字段、payload 精确三键、紧凑四字段资产、单次模板替换、温度、动态 enum、schema 不含 `uniqueItems`、replacement/source revisions 和 `input_hash=null`。
    3. 新增并运行 `python -m pytest -q tests/api/test_c006_generate_shots.py::test_generate_shots_active_conflict`，以真实 PostgreSQL 并发两次合法请求，必须只有一条 active task，败者 409；终态后允许显式新建。
    4. 人工查看 task JSON，确认 token、base URL、绝对路径、模板/风格版本、prop、候选分镜和未知顶层键均不存在；模板/风格缺失或占位符非法为 409，body/类型非法为 422。
  - **计划测试层级：** API 集成。
  - **追溯行：** ``R1 无资产禁止生成分镜：项目资产为 0 时 `generate-shots` 返回 409``；`R3 生成分镜覆盖：impact/token 校验；新分镜成功后才删除旧数据并移入 trash；LLM 失败旧数据不动`；`§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务`。

### T4 gen_shots 外部调用与严格输出校验

- [ ] 注册应用唯一 `gen_shots` handler：只读 claimed payload，在规定安全点 wake，以快照的一条 user message、模型、温度和动态 schema 调用 vLLM；严格解析 JSON、字段/枚举/时长/order/唯一 asset_ids，并在最终提交前做实时项目归属校验。0/多场景不得失败。
  - **前置 task：** T3。
  - **R：** R3；对应 PRD §3.1、§6.1-§6.2、§7、§9；R5a 仅对应“零场景合法/多场景留待修正”的 C006 输入边界。
  - **范围：** 只实现模型调用与硬校验，不在此 task 删除旧结构/文件，不实现 NLP 质量修补、重试或自由文本 fallback。
  - **覆盖 AC：** AC-07、AC-08、AC-10、AC-13。
  - **验收方式：**
    1. 新增并运行 `Set-Location backend; python -m pytest -q tests/task_system/test_c006_gen_shots.py::test_gen_shots_uses_snapshot_prompt_and_dynamic_schema`，mock 只记录一次 wake/chat 请求并返回合法 JSON，核对 task 全程使用快照、单 user message、动态 schema和温度。
    2. 运行 `python -m pytest -q tests/task_system/test_c006_gen_shots.py::test_gen_shots_rejects_invalid_output`，参数化覆盖解释文字/额外字段/非法枚举/越界时长/order 跳号/重复或不存在及跨项目 asset id，逐项 task failed、完整原因、旧数据不动且调用次数为 1。
    3. 同一用例加入合法 `asset_ids=[]` 和合法多场景绑定输出，证明两者进入提交接口而非被 reject；不得加入“自动选场景”分支。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `R3 生成分镜覆盖：impact/token 校验；新分镜成功后才删除旧数据并移入 trash；LLM 失败旧数据不动`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`。

### T5 R3 成功替换与 trash 原子业务提交

- [ ] 实现 spec §7.1 的最终提交：锁定并复核替换快照，在取消/提交条件裁决后删除本集 clip videos/关系/槽位/clips 和旧 shot assets/shots、移动 clip video/override 文件到 trash、写入新分镜/绑定与快照剧本 marker，并让业务变化与 task done 同事务胜出。
  - **前置 task：** T4。
  - **R：** R3；对应 PRD §3.1、§3.3“重新生成分镜”、§6.2、§6.4。
  - **范围：** 只做 gen_shots 的成功替换；不创建 clip、不保留候选/历史、不实现后台补偿任务或自动重试。
  - **覆盖 AC：** AC-09、AC-10。
  - **验收方式：**
    1. 新增并运行 `Set-Location backend; python -m pytest -q tests/task_system/test_c006_gen_shots.py::test_gen_shots_success_replaces_episode_and_trashes_clip_media`，夹具含旧 shots、shot_assets、clips、关系、slots、videos 和真实临时媒体，核对只替换目标 episode、全部依赖行顺序正确、媒体进入已有 trash、新 Shot 字段/status/revision/绑定及 marker 准确、task done。
    2. 夹具同时保留另一 episode 的完整结构与媒体，逐项比较其行和文件不变；确认生成输出为空数组时仍按 R3 清空目标结构并写 marker。
    3. 模拟数据库提交错误，核对数据库回滚且本次文件恢复到原路径；恢复失败必须显式失败并记录完整原因，不能报告旧数据无损或 done。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `R3 生成分镜覆盖：impact/token 校验；新分镜成功后才删除旧数据并移入 trash；LLM 失败旧数据不动`；`§3.3 重新生成分镜：成功后覆盖本集分镜、删除本集片段并将文件移入 trash`。

### T6 R3 失败、替换竞态与取消胜方

- [ ] 补齐 gen_shots 的失败/取消边界：LLM 或校验失败发生在替换前；待替换结构变化时最终提交失败；running 取消与业务提交只能有一个原子胜方，任何失败不重试且不覆盖先到终态。
  - **前置 task：** T5。
  - **R：** R3；对应 PRD §3.1、§3.2 任务快照、§6.1、§6.4。
  - **范围：** 只覆盖 gen_shots handler 的既有 C004 状态语义，不改通用队列协议、不新增 retry/backoff/补偿 worker。
  - **覆盖 AC：** AC-04、AC-08、AC-10。
  - **验收方式：**
    1. 新增并运行 `Set-Location backend; python -m pytest -q tests/task_system/test_c006_gen_shots.py::test_gen_shots_failures_preserve_existing_structure`，覆盖 wake/HTTP/schema/资产删除/替换快照行集或 revision 漂移/文件错误，核对 task failed、完整 error_msg、旧结构/marker/文件不变、无第二次调用。
    2. 新增并运行 `python -m pytest -q tests/task_system/test_c006_cancel_commit_race.py::test_cancel_and_gen_shots_commit_have_one_atomic_winner`，强制交错取消与最终提交：取消先赢时 canceled+旧结构，提交先赢时 done+完整新结构；不得出现 canceled+新结构或 done+半结构。
    3. 运行已有 `python -m pytest -q tests/task_system/test_task_queue.py::test_running_cancel_stops_at_safe_point tests/task_system/test_task_queue.py::test_restart_fails_running_and_continues_queued`，确认通用取消/重启没有被改弱。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `R3 生成分镜覆盖：impact/token 校验；新分镜成功后才删除旧数据并移入 trash；LLM 失败旧数据不动`；`§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断`。

### T7 分镜 GET/PATCH 与编辑级联

- [ ] 增加 spec §3.3-§3.4 的 Shot schema、GET 列表和 PATCH：固定排序/字段/封闭枚举，五类字段部分更新，资产 id 项目归属与去重校验，no-op 不增 revision；实际变化 changed/revision+1 并把相关 Clip stale。0/多场景合法。
  - **前置 task：** T6。
  - **R：** 无；对应 PRD §2.1(6)、§3.2 修订、§3.3“编辑分镜”、§5 分镜 API、§9 场景角标；零场景边界关联 R5a。
  - **范围：** 只提供查看及文本/绑定编辑，不提供 DELETE/POST、duration/order 编辑、拆分/合并/排序、clip 预检或 If-Match。
  - **覆盖 AC：** AC-11、AC-13、AC-17。
  - **验收方式：**
    1. 新增并运行 `Set-Location backend; python -m pytest -q tests/api/test_c006_shots.py::test_shot_get_and_patch_contract`，核对排序、精确字段、空列表、404/422、枚举、未知/只读字段、跨项目/prop/重复 id、no-op 与正常部分更新。
    2. 运行 `python -m pytest -q tests/api/test_c006_shots.py::test_shot_patch_changes_revision_and_stales_clips`，核对一次实际变化只 revision+1/changed，多个命中 Clip 只 stale、不改 generation_state/revision、不删文件。
    3. 运行 `python -m pytest -q tests/api/test_c006_shots.py::test_shot_patch_accepts_zero_and_multiple_scene_bindings`，证明零场景和多场景都返回 200 并准确持久化，不提前执行 C008 片段裁决。
  - **计划测试层级：** API 集成。
  - **追溯行：** `§3.3 编辑分镜文本或绑定：该分镜 changed、包含它的片段 stale、文件不删`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`。

### T8 资产编辑/换图/删除对 Shot/Clip 的 C006 级联

- [ ] 扩展现有资产 mutation：name/description/current image 实际变化使绑定 Shot 各 revision+1/changed、相关 Clip stale；删除前定位关系，解绑后 changed/stale，并保留 C003 图片 trash。no-op 与重复命中不重复递增。
  - **前置 task：** T7。
  - **R：** 无；对应 PRD §3.2 修订、§3.3“编辑资产/换当前图”“删除资产”、§6.4；R12 完整槽位行为明确不在本 task。
  - **范围：** 只增加 C006 可达 Shot/Clip 状态级联；不实现槽位启停/override/快照 UI，不删 clip 视频，不改变 generation_state。
  - **覆盖 AC：** AC-12。
  - **验收方式：**
    1. 新增并运行 `Set-Location backend; python -m pytest -q tests/api/test_c006_asset_cascade.py::test_asset_edit_and_current_image_mark_bound_shots_and_clips`，核对实际变化、no-op、多个 Shot/Clip 去重、revision/status/freshness 与所有文件不删。
    2. 运行 `python -m pytest -q tests/api/test_c006_asset_cascade.py::test_asset_delete_unbinds_and_marks_downstream`，核对删除前关系识别、解绑、changed/stale、资产图片入 trash；只断言现有 SET NULL 数据完整性，不把未实现 R12 当作完成。
    3. 复跑 `python -m pytest -q tests/api/test_c003_assets.py`，既有上传/current/delete 顺序与错误语义不得漂移。
  - **计划测试层级：** API 集成。
  - **追溯行：** `§3.3 编辑资产或换当前图：绑定分镜 changed、相关片段 stale、文件不删`；`§3.3 删除资产：解绑并 changed、相关片段 stale、槽位按 R12 处置、资产图片入 trash`。

### T9 episode/project 既有删除的 C006 数据兼容

- [ ] 扩展现有 episode/project DELETE 的当前可达删除顺序，使存在 C006 Shot/ShotAsset 时仍可删除；对夹具中属于目标 episode 的现有 Clip/媒体复用 R3 trash 清理；外部注入的未授权后续实体仍按既有 409 回滚。
  - **前置 task：** T5、T8。
  - **R：** 无；对应 PRD §2.1(1,5,12)、§3.3、§5 项目/剧集 DELETE、§6.4、§11 M1“已有实体级联”。
  - **范围：** 只维护既有 DELETE 在 C006 数据可达后的正确性；不新增删除 API、不实现后续实体级联、不修改数据库 schema。
  - **覆盖 AC：** AC-18。
  - **验收方式：**
    1. 在专用 PostgreSQL 验收库创建项目→episode→C006 shots/bindings，再分别调用 episode DELETE 和 project DELETE，核对目标行清空、其他项目不动、固定 204/错误体语义保持。
    2. 加入目标 clip video/override 实体和真实临时文件，删除后核对 DB 行清理且文件在 trash；加入未授权后续依赖时核对 409、数据库回滚和文件不动。
    3. 运行已有 `Set-Location backend; python -m pytest -q tests/api/test_c002_script.py tests/api/test_c002_prompt_templates.py`，确认 C002 剧集/项目相关 API 与下游保留语义无回归；不得修改既有测试。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有 episode/project 删除兼容行，C002 既有测试已裁决原行为；本 task 只对 C006 新可达数据做人工 PostgreSQL/文件验收，避免为追溯表外场景新增测试。
  - **追溯行：** 不适用。

### T10 剧本页 impact/确认/任务反馈 UI

- [ ] 在现有集工作区剧本页增加“生成分镜”：未保存编辑态不可发起，点击先 impact，非空影响显示准确删除数量并明确确认，0/0 直接提交；202 呈现 task id/任务中心，错误直显 `detail.message`。
  - **前置 task：** T3。
  - **R：** R1、R3；对应 PRD §2.1(4)、§3.1、§9、§11 M2。
  - **范围：** 只做按钮、弹窗和既有任务观察入口；不做自动重发、周期轮询、分镜页或导演台。
  - **覆盖 AC：** AC-03、AC-04、AC-05、AC-15、AC-17。
  - **验收方式：**
    1. `Set-Location frontend; npm run build` 必须成功。
    2. 真实浏览器走查：无资产时 impact 可正常只读返回，但随后的 generate 显示 R1 的 409 message且不创建 task；0/0 时不弹破坏性确认并发送 `{}`；非零时弹窗准确显示 clip/video 数，取消不创建 task，确认只提交一次并携 token。
    3. 快速双击、过期 token、影响变化和 active 冲突均显示 API message且 task 数正确；不得用按钮禁用冒充后端并发裁决。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有独立 UI 交互行，R1/R3 的最终业务裁决已在 T2-T6 API/任务测试覆盖，本 task 用生产构建和真实浏览器验收，避免重复测试。
  - **追溯行：** 不适用。

### T11 分镜页编辑、绑定与角标 UI

- [ ] 把集工作区“分镜”标签接入真实 GET/PATCH：按 order 展示只读时长和五类可编辑内容，支持项目 character/scene 绑定，显示 changed、零场景/多场景和旧剧本角标；保留既有返回导航与其他标签行为。
  - **前置 task：** T7、T8。
  - **R：** 无；对应 PRD §2.1(6)、§3.2 剧本编辑语义、§9 分镜页；场景角标对应 R5a 的输入质量边界。
  - **范围：** 只做 C006 分镜列表/编辑/角标；不提供新增/删除/拆分/合并/排序/duration 编辑、clip 创建或导演台。
  - **覆盖 AC：** AC-11、AC-13、AC-14、AC-15。
  - **验收方式：**
    1. `Set-Location frontend; npm run build` 必须成功。
    2. 真实浏览器走查正常分镜、空列表、changed、零场景、多场景：提示等级和文案准确，零/多场景都能保存；资产候选不出现 prop/跨项目资产。
    3. 编辑剧本使 revision 增加后确认 shots 不动且两页显示“分镜基于旧剧本”；下一次成功生成当前 revision 后角标消失。PATCH 422/404 直显 message并保留编辑态。
    4. 人工确认没有出现新增、删除、拆分、合并、拖拽排序、时长编辑、clip 或导演台控件。
  - **计划测试层级：** 不新增自动测试；理由：字段/级联/场景合法性已由 T7 API 集成覆盖，TRACEABILITY 没有独立 UI 行；本 task 以生产构建和真实浏览器证明呈现与交互，不重复编写前端自动测试。
  - **追溯行：** 不适用。

### T12 正式库真实 gen_shots 质量验收

- [ ] 在 T1 正式模板验收库从 UI/API 跑通真实 vLLM gen_shots：先复用 C005 已生成资产的同一段剧本逐镜核对；再用含跨地点转场和纯特写的专用剧本核对拆镜与零场景。只记录真实模型输出，不允许后端或测试夹具修补结果。
  - **前置 task：** T5、T10、T11。
  - **R：** R3；边角质量对应 R5a；对应 PRD §3.1、§6.2、§7、§9、§11 M2。
  - **范围：** 只验收正式模板+真实 vLLM+真实数据库/UI；不把模型语义规则复制为后端 validator，不接入 Comfy。
  - **覆盖 AC：** AC-02、AC-07、AC-08、AC-09、AC-13、AC-14、AC-15、AC-16。
  - **验收方式：**
    1. 记录正式库脱敏名称、episode/asset/task ids；用 C005 已生成资产的同一剧本发起 gen_shots，观察 queued→running→done，逐镜记录 order、时长、description、dialogue、asset_ids，并人工核对只绑定实际出镜人物和正确场景。
    2. 保存一段明确的“地点 A → 地点 B”转场及纯特写剧本，先确保两个场景和出镜人物资产真实存在，再生成；转场必须成为两镜且各绑对应场景，纯特写可为零场景并在页面显示提示。
    3. 真实制造一次 impact 非空重生成，核对确认计数、成功后旧 clip/视频 trash；再制造一次 vLLM/schema 失败，核对旧 shots/clips/media/marker 不变、task failed 和完整原因。不得为了通过而改模型输出、数据库结果或模板正文后隐瞒。
  - **计划测试层级：** 不新增自动测试；理由：跨地点拆镜、实际出镜绑定与纯视觉描述是正式 prompt/真实模型质量，非确定性语义不适合 mock 或稳定 pytest；硬数据完整性已由 T4-T7 自动测试覆盖。
  - **追溯行：** `R3 生成分镜覆盖：impact/token 校验；新分镜成功后才删除旧数据并移入 trash；LLM 失败旧数据不动`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`。

### T13 全量回归、范围证据与 Sol 追溯交接

- [ ] 在全新隔离 pytest 数据库完成后端全量、Alembic、前端生产构建、静态编译、diff/围栏扫描；汇总本 change 新增测试的真实 node ID、各 task 命令输出和正式库证据交给 Sol。不得由 Luna修改 PRD、TRACEABILITY、前置依赖清单或 change spec。
  - **前置 task：** T6、T8、T9、T10、T11、T12。
  - **R：** R1、R3；对应 PRD §0、§3.1-§3.3、§6.1-§6.4、§11 M2、§12。
  - **范围：** 只做验收与证据收口；发现失败回到对应未完成 task，不改测试、不放宽 spec、不顺手重构。
  - **覆盖 AC：** AC-01 至 AC-19。
  - **验收方式：**
    1. 新建全新 PostgreSQL pytest 库，设置 `$env:DATABASE_URL=$env:C006_PYTEST_DATABASE_URL`；`Set-Location backend; python -m alembic upgrade head; python -m alembic current; python -m alembic check`，确认 head 且无新 migration，迁移种子 `script2shots` 仍为占位。
    2. 运行所有本文件列出的 C006 node 后，再运行 `python -m pytest -q tests`，报告完整原始 summary；任何失败保持 T13 未勾选。
    3. 运行 `python -m compileall -q app tests`；随后 `Set-Location ../frontend; npm run build`。
    4. 回到仓库根运行 `git diff --check`；设置 `$env:C006_BASE='<T0记录的commit>'` 后运行 `git diff --name-status $env:C006_BASE -- backend/tests`，既有测试不得出现 `M/D/R`，新增文件只能是本 tasks 明列的 C006 测试。
    5. 运行 `git diff --name-only $env:C006_BASE` 和 `rg -n "candidate|generation_runs|continuity|context_loop|fl2v|audio|retry|backoff" backend frontend openspec/changes/C006`，逐个解释命中；核对无新 migration、范围外表/字段/API/UI、自动重试、compat/fallback。
    6. 向 Sol 提交：C006 commit 范围、逐 AC 的代码/测试/人工证据、真实 pytest/build/Alembic 输出、外部 gate 脱敏证据，以及本 change 全部新 node ID。只有 Sol 回填追溯并复审后才能判定 C006 通过。
  - **计划测试层级：** 不新增自动测试；理由：本 task 只运行前述授权测试和全量回归、收集证据，不创建新行为用例。
  - **追溯行：** 不适用。

## 外部依赖阻塞规则

当前没有必须预先编号但无法执行的独立 task。T1 直接复用上文已验证的 C005 正式环境，四个同名 shell 变量未设置不是阻塞。只有重新只读核对发现正式验收库/API、真实 vLLM/model/wake 已不可用或证据不匹配时，T1 及依赖它的 tasks 才保持未勾选，并按 proposal“外部依赖”报告实际状态变化；不得创建假地址、伪造响应、把占位模板当正式模板或跳过到 T12。
