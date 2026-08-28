# C005 M2 gen_assets Tasks

Luna 一次只领取一个 checkbox；每项只允许实现本 task 明列范围，完成全部验收、运行该 task 的计划测试与后端完整 pytest 后才能勾选并单独 commit。不得修改 proposal/spec/TRACEABILITY/前置依赖清单，不得创建 migration，不得修改、删除、跳过或弱化既有测试。新增测试只能落在本文件列出的 TRACEABILITY 行，必须新建独立测试文件；实际通过的 node ID 由 Luna 报告并由 Sol 在复审时回填。

PRD §12.4 vLLM、PostgreSQL 与正式 `script2assets` 的 C005 gate 已取得合格证据，T1-T9 的首轮执行证据保留。Sol 于 2026-08-27 复审判定 C005 暂不通过；Luna 现在只能按顺序领取 T10、T11、T12、T13，不得重做 T1-T9、顺手扩写 spec 或把审计失败改成测试期望。

## 外部依赖阻塞 task

### T1 核验 vLLM、wake 与正式模板门槛

- [x] 在目标实施环境取得真实 `VLLM_BASE_URL`/端口/模型，验证 OpenAI-compatible 模型读取、`POST /wake_up` 与 guided_json 能力；通过既有设置 API/UI 保存并读回 spec §5.1 的完整 `script2assets`，形成不含凭据的原始证据。
  - **前置 task：** 无。
  - **解除条件：** 用户提供真实地址与端口；`/v1/models`、`/wake_up` 和最小封闭 schema 请求都有真实成功响应；`GET /api/prompt-templates` 读回的 `script2assets` 与 spec §5.1 逐字一致。任一缺失时保持未勾选并停止。
  - **R：** 无；对应 PRD §6.2 gen_assets wake、§7、§12.2、§12.3、§12.4。
  - **范围：** 只核验外部服务和现有设置数据；不写实现、migration、测试、假服务、固定地址、模型输出或业务 fallback；不得把凭据提交进仓库。
  - **覆盖 AC：** AC-02。
  - **验收方式：**
    1. 在 PowerShell 以本机环境变量注入真实地址，不改 `.env.example` 为秘密值；运行 `Invoke-RestMethod "$env:VLLM_BASE_URL/v1/models"`，保存实际状态、模型 id 和时间。
    2. 运行 `Invoke-WebRequest -Method Post "$env:VLLM_BASE_URL/wake_up"`，保存实际状态与响应；若服务约定需先 sleep 才能验证 wake，使用服务方已确认步骤并记录，不得把错误吞成成功。
    3. 直接向 `/v1/chat/completions` 发送一个不含业务数据的最小封闭 `response_format` 请求，核对额外字段被硬约束且输出是单一 JSON object；保存脱敏请求/响应。
    4. 启动既有后端，使用 `PATCH /api/prompt-templates/script2assets` 保存 spec §5.1 正文，再用 `GET /api/prompt-templates` 读回逐字比对；不得用 migration 或代码常量写入。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有外部服务连通性/模板部署独立行，且门槛必须由真实 vLLM 与目标数据库证据裁决。
  - **追溯行：** 不适用。

## 门槛解除后按依赖排序的 tasks

### T2 配置与最小 vLLM 结构化客户端

- [x] 增加 `VLLM_TEMPERATURE` 配置及 `.env.example` 中文说明，默认 `0.2`、非法范围启动失败；建立只承担 wake 和一次 OpenAI-compatible structured chat 的最小 vLLM 边界，调用方必须显式提供消息、模型、温度与封闭 schema。
  - **前置 task：** T1。
  - **R：** 无；对应 PRD §6.2、§6.3、§7、§10。
  - **范围：** 不实现 gen_assets 业务 handler、模板渲染、输出合并或 API；不接 Comfy，不实现 sleep/free、重试、fallback、通用 provider registry、gen_shots schema 或后续模型能力。
  - **覆盖 AC：** AC-01、AC-07、AC-14。
  - **验收方式：**
    1. 在 `backend/` 无显式温度环境变量时运行 `python -c "from app.core.config import settings; assert settings.VLLM_TEMPERATURE == 0.2; print(settings.VLLM_TEMPERATURE)"`，输出必须为 `0.2`；再以越界值启动配置加载，必须明确失败且非零退出。
    2. 对 T1 真实 vLLM 运行客户端最小调用，保存单次 wake 与 chat 请求/响应；确认客户端没有重试且结构错误原样抛出。
    3. 运行 `rg -n -i "retry|backoff|fallback|sleep|free|gen_shots|comfy" app`，人工审查全部命中，确认本 task 未扩范围。
    4. 运行 `python -m compileall -q app`、`python -m pytest -q tests` 与仓库根 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有配置或通用 vLLM transport 独立行；用真实服务、启动失败与完整回归验收，避免为内部接线另造测试。
  - **追溯行：** 不适用。

### T3 生成 API、一次渲染与完整入队快照

- [x] 实现无 body 的 `POST /api/episodes/{id}/generate-assets`：验证 episode/项目风格/模板前置条件，按 spec §4-§5 构造一次渲染的不可变 payload，以 `request_id=null` 入队，并落实 202/404/409/422 与并发 active 去重。
  - **前置 task：** T2。
  - **R：** R2；对应 PRD §2.1(4)、§3.1、§3.2、§5 生成动作、§6.1、§7、§11 M2。
  - **范围：** 只交付 API 到 queued task；不调用 vLLM、不注册 handler、不写资产/marker、不接受 request_id/If-Match、不新增表或 endpoint。
  - **覆盖 AC：** AC-03、AC-04、AC-05、AC-06、AC-14。
  - **验收方式：**
    1. 新增并运行 `python -m pytest -q tests/api/test_c005_generate_assets.py::test_generate_assets_enqueues_exact_snapshot_and_errors`，核对 202 精确响应、三键 payload、紧凑资产数组、空数组、单次占位替换、404/409/422 和固定错误体。
    2. 运行 `python -m pytest -q tests/api/test_c005_generate_assets.py::test_generate_assets_active_conflict`，用真实 PostgreSQL 并发两次请求，必须只有一条 active task，败者为 409；终态后允许新 task。
    3. 人工查看数据库 task，确认 `type=gen_assets`、target 为 episode、`request_id IS NULL`、`input_hash` 为 null，payload 不含 base URL、版本字段或未知顶层键。
    4. 运行 `python -m pytest -q tests` 与仓库根 `git diff --check`；此时只回填实际通过的 API 用例 ID，不回填尚未覆盖的 R2 worker 部分。
  - **计划测试层级：** API 集成。
  - **追溯行：** R2 生成资产增量合并：现有资产按项目快照注入；`existing_id=null` 项新增，真实属于本项目的非 null 项不改不删，伪造/跨项目非 null id 降级新增并记录 warning；成功后记录入队快照剧本修订，运行中改剧本仍保留旧剧本角标；§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务。

### T4 gen_assets handler 与真实 guided_json 请求

- [x] 注册正常应用唯一的 `gen_assets` handler：只读 claimed payload，按安全点执行 wake，使用一条完整 user message、快照模型/温度和 spec §6.2 封闭 schema调用 vLLM，严格解析单一 JSON object；所有外部/解析错误向 worker 抛出。
  - **前置 task：** T3。
  - **R：** R2；对应 PRD §3.1、§3.2、§6.2-§6.4、§7、§11 M2。
  - **范围：** 本 task 只把任务执行到通过 schema 校验的内存结果；落库合并由 T5；不回读当前剧本/风格/模板/资产重建 prompt，不实现自由文本解析、重试、system 业务规则、gen_shots 或 Comfy 调用。
  - **覆盖 AC：** AC-05、AC-06、AC-07、AC-09、AC-13。
  - **验收方式：**
    1. 新增并运行 `python -m pytest -q tests/task_system/test_c005_gen_assets.py::test_gen_assets_uses_snapshot_prompt_and_closed_schema`；受控 vLLM seam 必须捕获 wake、单条 user message、模型、温度 0.2 与精确 schema，并证明执行中修改当前数据库不改变请求。
    2. 同一用例覆盖 `prop`、缺字段、额外字段、Markdown 围栏与非 JSON 响应均抛错；不得返回空数组 fallback 或产生第二次调用。
    3. T1 真实 vLLM 上发起一个真实生成任务，保存脱敏请求元数据和 task 状态；不得在日志打印完整剧本、凭据或伪造模型响应。
    4. 运行 `python -m pytest -q tests`、`python -m compileall -q app` 与仓库根 `git diff --check`。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** R2 生成资产增量合并：现有资产按项目快照注入；`existing_id=null` 项新增，真实属于本项目的非 null 项不改不删，伪造/跨项目非 null id 降级新增并记录 warning；成功后记录入队快照剧本修订，运行中改剧本仍保留旧剧本角标。

### T5 R2 三路增量合并与 warning

- [x] 在 T4 handler 中落实 R2 合并：null id 新增 generated 资产；当前项目合法非 null id 不增不改不删；不存在/跨项目 id 降级新增并记录带 task/episode/project/id 的 warning；输出为空时允许只写 marker。
  - **前置 task：** T4。
  - **R：** R2；对应 PRD §3.1 R2、§4 assets、§6.2 gen_assets、§7。
  - **范围：** 只新增 character/scene 资产并更新 episode marker；不创建图片、不更新既有资产、不做别名/合并/语义去重、不修改 shots/clips/files，不改变数据库 schema。
  - **覆盖 AC：** AC-08、AC-09、AC-11。
  - **验收方式：**
    1. 新增并运行 `python -m pytest -q tests/task_system/test_c005_gen_assets.py::test_gen_assets_incremental_merge_handles_existing_and_invalid_ids`，同一受控输出覆盖 null、同项目、伪造和跨项目 id；核对新增行/source、既有行逐字段不变、warning 上下文和无图片。
    2. 在专用 PostgreSQL 运行真实任务前后查询项目资产和 marker；输出 `assets=[]` 时资产数不变但 marker 更新为快照修订。
    3. 运行 `python -m pytest -q tests` 与仓库根 `git diff --check`；只回填真实通过用例 ID。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** R2 生成资产增量合并：现有资产按项目快照注入；`existing_id=null` 项新增，真实属于本项目的非 null 项不改不删，伪造/跨项目非 null id 降级新增并记录 warning；成功后记录入队快照剧本修订，运行中改剧本仍保留旧剧本角标。

### T6 原子失败、快照修订竞态、取消与下游无损

- [x] 把本次所有新增资产与快照 marker 放入同一事务，并完成失败、运行中改剧本、最终事务前取消和重新生成不触碰下游的行为；异常必须交回 C004 置 failed 且无重试。
  - **前置 task：** T5。
  - **R：** R2；对应 PRD §3.2、§3.3“编辑剧本/重新生成资产”、§6.1、§6.2、§6.4、§11 M2。
  - **范围：** 只收紧 C005 handler 的事务/安全点；不改变 C004 通用状态机，不实现轮询、补偿任务、部分成功、trash 或任何下游级联。
  - **覆盖 AC：** AC-09、AC-10、AC-11、AC-13。
  - **验收方式：**
    1. 新增并运行 `python -m pytest -q tests/task_system/test_c005_gen_assets.py::test_gen_assets_failure_rolls_back_and_preserves_downstream`，分别在 schema/数据库写入失败，核对 task failed、完整错误、零部分新增、marker 未变、既有资产/图片/shots/clips/files 不变、无重试。
    2. 运行 `python -m pytest -q tests/task_system/test_c005_gen_assets.py::test_gen_assets_uses_enqueued_script_revision_after_edit`，入队 N 后改剧本至 N+1，核对请求仍为 N、成功 marker=N，下一次成功才写 N+1。
    3. 运行 `python -m pytest -q tests/task_system/test_c005_gen_assets.py::test_gen_assets_cancel_before_commit_writes_no_assets`，核对最终事务前取消后为 canceled 且资产/marker 不变。
    4. 运行 `python -m pytest -q tests` 与仓库根 `git diff --check`；把实际 node ID 分别回填到对应 TRACEABILITY 行。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** R2 生成资产增量合并：现有资产按项目快照注入；`existing_id=null` 项新增，真实属于本项目的非 null 项不改不删，伪造/跨项目非 null id 降级新增并记录 warning；成功后记录入队快照剧本修订，运行中改剧本仍保留旧剧本角标；§3.3 重新生成资产（增量）：分镜、片段、文件均不动；§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断。

### T7 集工作区生成按钮与任务反馈

- [x] 在集工作区剧本只读页增加“生成资产”按钮，调用 T3 endpoint；请求期间防连点，202 后显示真实 task id 和任务中心入口，错误直显 `detail.message`，编辑未保存剧本时不发送生成请求。
  - **前置 task：** T3。
  - **R：** R2；对应 PRD §2.1(4,8,11)、§5 生成动作、§9、§11 M2。
  - **范围：** 不新增任务轮询、取消/历史/过滤、自动跳转、假 task、视觉专题或 gen_shots 按钮；不在前端裁决同目标冲突。
  - **覆盖 AC：** AC-04、AC-12、AC-14。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`，必须成功。
    2. 启动真实前后端，在浏览器 Network 中点击一次，核对只有一个无 body POST、202 响应只含 task_id、页面显示同一 id 和任务中心入口且不跳走。
    3. 快速双击并制造 active 冲突，核对后端仅一条 active，页面直接显示 409 的 `detail.message`；制造结构化 422/500 时同样不吞错、不自动重发。
    4. 进入剧本编辑状态后人工检查按钮不可发起；保存后生成使用服务器最新修订。随后在 `backend/` 运行 `python -m pytest -q tests`，仓库根运行 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有前端按钮/导航独立行，API 与并发已经由 T3 的授权 API 集成覆盖；本 task 用生产构建、真实浏览器和 Network 验收。
  - **追溯行：** 不适用。

### T8 结果刷新与旧剧本角标

- [x] 让集工作区资产页在进入/标签切换时读取真实项目资产，剧本页与资产页按 marker 非空且小于当前 revision 显示固定旧剧本角标；marker 为空或相等时不显示，不增加轮询。
  - **前置 task：** T6、T7。
  - **R：** R2；对应 PRD §2.1(4,5,11)、§3.2“剧本旧角标”、§9、§11 M2。
  - **范围：** 只做 C005 结果呈现和角标；不缓存假资产、不在 WS frame 传资产、不新增后台轮询、分镜 changed、clip stale 或 UI 全局改版。
  - **覆盖 AC：** AC-10、AC-12。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`，必须成功。
    2. 浏览器走通：修订 N 生成完成后资产页出现真实新增项且无角标；编辑剧本至 N+1 后剧本页和资产页都显示“资产提取基于旧剧本”；再次成功生成 N+1 后两处角标消失。
    3. 对从未成功生成的 episode 核对 marker=null 且不显示“旧剧本”；刷新页面/切换标签后状态仍来自 API。Network 中不得出现周期轮询或资产假写入。
    4. 在 `backend/` 运行 `python -m pytest -q tests`，仓库根运行 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 的修订/marker 数据竞态由 T6 任务系统 mock 覆盖，没有独立前端自动测试层级；本 task 仅以生产构建和真实浏览器呈现验收。
  - **追溯行：** §3.3 编辑剧本：分镜、片段、文件均不动，只出现集级旧剧本角标。

### T9 C005 首轮全链路、追溯与范围收口

- [x] 只汇总并复跑 T1-T8 的真实证据，回填实际通过的 TRACEABILITY node ID，完成真实 vLLM、PostgreSQL、API、task/WS、浏览器与范围围栏收口；失败项保持未完成并原样报告。
  - **前置 task：** T1-T8。
  - **R：** R2；对应 PRD §0、§2.1(4,11)、§3.1-§3.3、§5、§6.1-§6.4、§7、§9-§12。
  - **范围：** 只复跑验收、回填追溯表和记录证据；不新增实现、测试、migration、临时修复、后续 handler 或伪造外部结果。发现失败必须回到对应未完成 task，不能在 T9 顺手修。
  - **覆盖 AC：** AC-01 至 AC-15。
  - **双数据库验收边界：**
    1. **干净 pytest 库**：使用一个全新空 PostgreSQL 数据库，只执行仓库现有 `alembic upgrade head` 后运行自动测试。该库在 pytest 启动前的四个模板应保持迁移初始值，其中 `script2assets` 以 `[占位]` 开头；不得在此库执行 T1 的正式模板部署，也不得由操作者在 pytest 前后为通过测试临时 PATCH、恢复或特判模板。授权测试内部对模板 API 的调用及其清理仍按既有用例执行。
    2. **正式模板验收库**：使用与 pytest 库不同的 PostgreSQL 数据库，保留 T1 已保存并读回的正式 `script2assets`，只用于真实 vLLM、API、task/WS、资产入库和浏览器走查。不得把正式模板改回占位，也不得在此库运行依赖“空库迁移初始值”的 C002 全量测试。
    3. 两个 DSN 必须解析到不同 database name；只报告脱敏后的 host/port/database name，不提交密码。任一数据库证据缺失、两个变量实际指向同一库，或任一链路失败，T9 均保持未勾选。
  - **验收方式：**
    1. 由操作者分别提供不含占位值的 `$env:C005_PYTEST_DATABASE_URL` 与 `$env:C005_ACCEPTANCE_DATABASE_URL`；人工核对两者的 database name 不同。不得打印完整 DSN。
    2. 在 `backend/` 指向全新空 pytest 库运行 `$env:DATABASE_URL=$env:C005_PYTEST_DATABASE_URL`，随后依次运行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、T3-T6 明列的全部 C005 测试 node 和 `python -m pytest -q tests`；保存实际 stdout/stderr。全量 pytest 必须成功，且不得修改既有 C002 测试或由操作者在测试前后改写迁移初始模板。
    3. 切换到正式模板验收库：运行 `$env:DATABASE_URL=$env:C005_ACCEPTANCE_DATABASE_URL`，再运行 `python -m alembic current` 与 `python -m alembic check`；通过 `GET /api/prompt-templates` 读回并逐字核对 `script2assets` 仍为 spec §5.1 正式正文，而非 `[占位]`。
    4. 在正式模板验收库使用 T1 真实 vLLM 从集工作区完成：保存剧本→生成资产→任务 queued/running/done→资产页呈现；再验证运行中改剧本的旧角标、active 双击 409、非法 existing_id warning 与失败无部分写入。
    5. 在 `frontend/` 运行 `npm run build`；浏览器保存 POST、任务 REST/WS、结果刷新、角标出现/消失和失败 `detail.message` 的证据。
    6. 核对 TRACEABILITY 仅回填 T3-T6 实际通过的 node ID，不为 UI/配置另造用例；运行 `git diff --name-status 46eadcc -- backend/tests`，输出只允许新增本文件授权的 C005 测试；再运行 `git diff --exit-code --diff-filter=DMRTUXB 46eadcc -- backend/tests`，必须无输出且退出码 0，以证明既有测试未修改/删除/重命名/弱化。
    7. 在仓库根运行 `git diff --check`、`git status --short`，并运行 `rg -n -i "generation_runs|continuity|context_loop|fl2v|audio|音频|候选分镜|资产别名|版本化|retry|重试|gen_shots|generate-image|generate-video|comfy|sleep|free" backend frontend`，逐项审查合法命中；vLLM transport 自动 retry、业务 fallback、后续能力或围栏违规必须为零。
  - **计划测试层级：** 不新增自动测试；理由：本 task 只复跑 T3-T6 已授权测试与真实全链路，不产生新场景或新用例。
  - **追溯行：** 不适用。

## Sol 复审后的增量修复 tasks

### T10 超范围伪造 existing_id 仍按 R2 降级新增

- [x] 修复模型返回的非 null `existing_id` 超出 PostgreSQL `INTEGER` 可查询范围时整任务失败的问题：该 id 必须与其他不存在/跨项目 id 一样，不进入会溢出的数据库查询，按模型返回的 type/name/description 新增 generated 资产并记录完整 warning 上下文；同一输出内其他项仍按原顺序和 R2 处理。
  - **前置 task：** T9。
  - **R：** R2；对应 PRD §3.1 R2、§4 assets、§6.2 gen_assets、§7。
  - **范围：** 只修复 C005 对外部模型整数的项目归属防御；不收窄 guided_json 的 `existing_id` schema、不把超范围值改为 422、不新增数据库列或 migration、不吞数据库异常、不改变合法同项目/普通不存在/跨项目/null 四条既有路径。
  - **覆盖 AC：** AC-08、AC-09。
  - **验收方式：**
    1. 新建且只新建本场景的测试文件，运行 `python -m pytest -q tests/task_system/test_c005_invalid_existing_id.py::test_out_of_range_existing_id_is_downgraded_to_new_asset`；输入至少含一个大于 PostgreSQL int32 上界的 `existing_id`，核对 task done、该项新增、marker 写快照修订、warning 含 task/episode/project/非法 id，且同批合法复用项不变。
    2. 同一用例必须证明未发生数据库 `DataError`、没有自动重试、没有第二次 vLLM 调用；不得用测试专用分支或改动现有 C005 测试。
    3. 在 `backend/` 运行 `python -m pytest -q tests`，随后在仓库根运行 `git diff --check` 与 `git diff --name-status 934d02a -- backend/tests`；测试 diff 只允许新增本 task 的独立测试文件。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** R2 生成资产增量合并：现有资产按项目快照注入；`existing_id=null` 项新增，真实属于本项目的非 null 项不改不删，伪造/跨项目非 null id 降级新增并记录 warning；成功后记录入队快照剧本修订，运行中改剧本仍保留旧剧本角标。

### T11 原子裁决最终取消与资产提交

- [x] 消除最终取消安全点与资产事务之间的竞争窗口：取消先赢时 task 必须 canceled 且本次资产/marker 均不写；业务提交先赢时资产、marker 与成功终态必须形成同一可观察胜方，随后到达的取消不得把已提交成功改成 canceled。失败仍完整回滚并由 C004 置 failed，不重试。
  - **前置 task：** T10。
  - **R：** R2；对应 PRD §3.1 R2、§6.1 条件状态转换与取消安全点、§6.2 gen_assets、§6.4。
  - **范围：** 只修复 C005 最终业务提交的终态裁决；复用 C004 已有 task 行与条件转换，不新增锁表、补偿任务、任务阶段字段、自动重试或第二队列，不改变其他 task handler、queued 取消、WS frame、heartbeat 或取消 API 合同。若在该范围内无法同时满足两种胜方语义，必须停止并报告，不得自行扩大 C004 spec。
  - **覆盖 AC：** AC-09、AC-13。
  - **验收方式：**
    1. 新建且只新建本场景的测试文件，运行 `python -m pytest -q tests/task_system/test_c005_cancel_commit_race.py::test_cancel_and_gen_assets_commit_have_one_atomic_winner`；用受控屏障分别强制“取消先提交”和“业务提交先取得胜方”两种顺序，不得靠随机 sleep 碰竞态。
    2. 取消先赢必须断言 canceled、资产数/marker 不变；业务先赢必须断言 done、资产与快照 marker 同时存在，后续取消返回既有终态冲突且不能改写 done。两条路径均不得产生 `canceled + 已写资产/marker`。
    3. 运行现有 `python -m pytest -q tests/task_system/test_c005_gen_assets.py::test_gen_assets_cancel_before_commit_writes_no_assets`，确认既有安全点行为不漂移；不得修改该文件。
    4. 在 `backend/` 运行 `python -m pytest -q tests`，随后在仓库根运行 `git diff --check` 与 `git diff --name-status 934d02a -- backend/tests`；测试 diff 只允许 T10、T11 新增的独立文件。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** §6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断；R2 生成资产增量合并：现有资产按项目快照注入；`existing_id=null` 项新增，真实属于本项目的非 null 项不改不删，伪造/跨项目非 null id 降级新增并记录 warning；成功后记录入队快照剧本修订，运行中改剧本仍保留旧剧本角标。

### T12 严格拒绝任何非空 generate-assets body

- [x] 收紧 `POST /api/episodes/{id}/generate-assets` 的 body 边界：原始请求字节长度大于 0 时一律返回固定结构 422，包括只含空格、换行或 Tab 的 body；真正零字节 body 保持现有合同，不改变 202/404/409 语义。
  - **前置 task：** T11。
  - **R：** 无；对应 PRD §5 生成动作、§10 API 错误；具体 body 合同见 C005 spec §3.1、§10。
  - **范围：** 只修改该 endpoint 的原始 body 判定；不引入通用中间件、不解析/trim JSON、不接受 `{}` 或 `null`、不改错误体 handler、前端请求形状或其他 endpoint。
  - **覆盖 AC：** AC-03、AC-14。
  - **验收方式：**
    1. 在专用 PostgreSQL 验收库记录目标 episode 的 task 数；先运行 `$whitespaceBody = ' ' + [Environment]::NewLine + [char]9`，再对真实后端运行 `Invoke-WebRequest -Method Post -ContentType 'application/json' -Body $whitespaceBody "$env:API_BASE/api/episodes/{id}/generate-assets"`，核对 HTTP 422、`detail.code=validation_error`、message 可直显，且前后 task 数不变。
    2. 继续人工核对零字节无 body 请求仍按当前状态返回 202 或 active 409，`{}`、`null`、`text` 仍为 422；不得为验收临时改模板、任务状态或测试数据。
    3. 运行现有 `python -m pytest -q tests/api/test_c005_generate_assets.py::test_generate_assets_enqueues_exact_snapshot_and_errors` 与 `python -m pytest -q tests`，随后运行仓库根 `git diff --check`。
  - **计划测试层级：** 不新增自动测试；理由：TRACEABILITY 没有独立的空请求 body 行，现有 R2 API 集成已覆盖 `{}`/`null`/普通非空 body，本 task 只补一个相同 422 语义的 HTTP 边界值，以真实 API 和任务数不变证据验收，避免越出追溯表另造用例。
  - **追溯行：** 不适用。

### T13 修复后全量复跑与交付 Sol 复审

- [x] 在 T10-T12 各自单独 commit 后，重新执行 C005 双数据库、真实 vLLM/API、任务/WS、浏览器、完整回归与范围收口；把新增测试的真实 node ID 和全部原始结果交给 Sol，未通过项不得勾选或描述为完成。
  - **前置 task：** T10、T11、T12。
  - **R：** R2；对应 PRD §0、§3.1-§3.3、§5、§6.1-§6.4、§7、§9-§12。
  - **范围：** 只复跑 T9 既定双数据库边界并增加 T10-T12 的定向验收；不再修改实现、测试、proposal/spec/TRACEABILITY/前置依赖清单，不创建临时兼容层或后续 change 能力。任何失败必须回到对应 task 新 commit 修复后再重跑。
  - **覆盖 AC：** AC-01 至 AC-15。
  - **验收方式：**
    1. 在干净 pytest 库运行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、T3-T6 既有 7 个 node、T10/T11 新增 node 与 `python -m pytest -q tests`；迁移初始模板保持 `[占位]`，不得运行时 PATCH 帮测试通过。
    2. 在独立正式模板验收库读回 spec §5.1 正式正文，复跑真实 vLLM wake/guided_json、无 body 入队、R2 合并、超范围 id warning 降级、两种取消/提交胜方、空白 body 422、旧剧本角标和资产结果呈现。
    3. 在 `frontend/` 运行 `npm run build`；在仓库根运行 `git diff --check`、`git status --short`、既有测试未改动检查和 T9 的完整范围围栏扫描。
    4. 报告脱敏数据库 host/port/database name、真实 vLLM model、所有命令原始结果、浏览器可观察结果和新增 node ID；由 Sol 负责 TRACEABILITY、proposal 与前置依赖清单的最终通过态维护并执行只读复审。
  - **计划测试层级：** 不新增自动测试；理由：本 task 只复跑 T3-T6、T10-T11 已授权自动用例与 T7-T8/T12 的人工验收，不产生新场景。
  - **追溯行：** 不适用。
