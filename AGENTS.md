# AGENTS.md

## 最高需求真相

- [`docs/PRD-v1.2.md`](docs/PRD-v1.2.md) 是本项目唯一、最高的产品需求真相；任何 proposal、spec、task、实现与测试都不得与其冲突。
- [`openspec/`](openspec/) 保存项目约定、ROADMAP、测试追溯表，以及每个 change 的 proposal、spec、tasks 与归档。
- 每次会话开始时，先读本文件，再读 `openspec/project.md`、当前 change 文档与 PRD 相关章节；不得凭记忆补需求。

## 范围围栏（PRD §0 原文）

> **范围围栏(对 codex 的硬约束)**:以下机制明确不属于 v1,不得实现、不得预先建表:候选分镜版本、分镜增删/拆分/合并/排序、资产别名与合并、风格/模板版本化、独立 generation_runs 表、continuity 相关字段、context loop、fl2v、音频。唯一预留:`clips.generation_mode` 枚举列(默认 `ref2v`,预留 `fl2v`/`context_loop` 值,v1 不读写其他值)。

上段是逐字引用的硬围栏。任何 change、迁移、接口、字段、组件、占位逻辑或测试都不得绕过它；唯一允许的预留仅为原文所述的 `clips.generation_mode` 枚举列。

## Change 纪律

- 任何实现只允许覆盖当前 change 的 `proposal.md`、`spec.md` 与 `tasks.md` 明确授权的范围；不得顺手实现后续 ROADMAP 项，也不得预建其表、字段、接口或 UI。
- 发现 spec 缺失、互相冲突或存在会改变行为的歧义时，必须立即停止并报告；不得自行选择语义、补需求或用默认行为掩盖问题。
- 一次只执行被明确指定的 task；未完成验收前不得勾选 task，不得把部分完成描述为完成。
- 不保留旧格式兼容层，不引入未被当前 spec 要求的版本化、重试、fallback、注册表或预留抽象。

## 失败与 API 错误语义

- 任务任一步骤失败即进入 `failed`，记录完整 `error_msg`，**不重试**；不得吞异常、静默降级或返回伪成功。
- API 错误体格式固定为 `{"detail":{"code","message"}}`；实际响应中 `code` 与 `message` 都必须有值，前端直显 `detail.message`。
- HTTP `409` 只表示前置条件不满足或资源/任务冲突，例如确认 token 无效、同目标任务冲突、被引用资源或当前版本禁止删除。
- HTTP `422` 只表示请求内容未通过业务或输入校验，例如片段不连续、跨场景、时长或参考资产数量不合法。
- 相同语义在所有端点保持同一状态码；不得用 `200` 包装错误，也不得用 `409`/`422` 互相替代。

## 测试与证据

- `openspec/TRACEABILITY.md` 是“测全且不过度”的唯一裁决依据；不得编写追溯表之外的测试。
- 新增测试前必须定位对应追溯行；实现 change 时回填用例 ID。一个用例可覆盖多行，但每个用例必须至少归属一行。
- 不得修改、删除、跳过或弱化既有测试来换取通过；不得对测试数据做特殊分支。
- **C006 一次性窄例外（需求方于 2026-08-27 明确授权）**：仅允许在 T5 中修正提交 `88258d8` 新增的 `backend/tests/task_system/test_c006_gen_shots.py::test_gen_shots_uses_snapshot_prompt_and_dynamic_schema`。修正范围只限：让媒体快照夹具符合 C006 spec §4.5 的真实 `kind/id/path` 合同，并把“T4 成功后结构保持不变”的阶段性断言替换为符合 T5 最终成功覆盖行为的断言。必须保留单次 wake/chat、快照 user message、model、temperature、schema name、精确动态 schema、无隐藏 system 业务 prompt 的全部断言；不得 skip/删除该用例、修改其他既有测试、弱化路径漂移校验或在生产代码中识别测试数据。T5 专用成功用例仍须独立覆盖完整 R3 替换与 trash。本例外在 C006 archive 时自动失效，不得类推。
- **C007 一次性窄例外（需求方于 2026-08-28 明确授权）**：仅允许在 T3 中修正提交 `60dfc3d3` 新增的 `backend/tests/api/test_system.py::test_infrastructure_smoke`，把 C001 阶段性的“不访问外部服务且精确返回 `not_checked` skeleton”替换为 C007 spec §2.3 的当前 health 合同。必须保留原用例对 `/docs`、`/openapi.json`、未知 API 404 与精确结构化错误体的断言，保留禁止测试进程连接真实外部网络的 guard，并通过正式 transport 注入 seam 验证 vLLM/Comfy 各一次逻辑健康探测、精确 `healthy|unhealthy`/`message`、binding `valid` 与唯一 Z-Image hash；不得 skip/删除/改名该用例、修改任何其他既有测试、削弱上述断言或在生产代码中识别测试环境。T3 新增的 C007 health 用例仍须独立覆盖不可达、非 2xx、畸形响应、启动绑定失败与无 GPU mutation。本例外在 C007 archive 时自动失效，不得类推。
- **C007 一次性窄例外（需求方于 2026-08-30 明确授权）**：本轮仅允许修正 `backend/tests/api/test_c007_health.py::test_health_reports_expected_component_failures` 的参数归属，将不可达的 vLLM `ValueError/invalid JSON` 参数改为 Comfy 畸形 JSON；不得修改、删除、改名或弱化其他既有测试。seed 公共 API 字符串合同只能通过新增追溯行和独立 API 用例覆盖，内部 seed 整数断言保持不变。本例外仅限本轮。
- **C009 对 C008 范围基线的一次性分阶段窄演进（需求方于 2026-09-01 授权 Sol 裁决）**：仅允许修改 `backend/tests/api/test_c008_contract_errors.py::test_c008_openapi_paths_handlers_and_error_contract` 的阶段性范围集合，并严格分三步：T9 只在精确 `expected_paths` 增加 `/api/clips/{clip_id}/generate-video`；T13 只在精确 handler 列表增加 `gen_clip_video`；T15 只在精确 `expected_paths` 增加 `/api/clips/{clip_id}/videos` 与 `/api/clips/{clip_id}/current-video`。每步均须保留集合精确相等，不得改为子集/只判存在；必须逐字保留全部 C008 path、slot content type/schema、slot media、未知资源 404、输入 422 和闭合错误体断言，以及 public path 不含内部 `gen_clip_video`/`minimax` 名称的断言。不得修改该函数其他断言、改名、skip、删除、修改其他既有测试或用它取代 C009 专用测试；每步到达对应 task 前不得提前加入后续 path/handler。本例外在 C009 归档时失效，不得类推。
- **C009 对 C007 handler 注册基线的一次性窄演进（需求方于 2026-09-01 授权 Sol 裁决）**：仅允许在 T13 修改 `backend/tests/task_system/test_c007_resource_lifecycle.py::test_pipeline_handler_registration`：保留现有 `gen_asset_image_handler` import 与精确 identity 断言，新增生产队列适配器 `gen_clip_video_task_handler` import，并把 `gen_clip_video` 不存在断言替换为该 key 精确 `is gen_clip_video_task_handler`。T11 的 `gen_clip_video_handler` 是返回 `GeneratedClipVideo | None` 的生成 core，不是正式 `TaskHandler` identity。不得修改该函数其他内容、该文件其他测试或任何资源顺序/请求断言，不得改为只判 key 存在、skip、改名、删除或使用测试特判/延迟注册；C009 T13 专用提交测试仍须独立证明适配器只调用一次 core并完成原子提交。本例外在 C009 归档时失效，不得类推。
- **C009 生命周期跨进程断言的一次性窄修正（需求方于 2026-09-02 明确授权）**：仅允许在 T20A 修改 `backend/tests/task_system/test_c009_resource_lifecycle.py` 的 `_assert_no_overlapping_intervals` helper及其三处调用：把“所有事件两两不重叠”收窄为只断言 `component=vllm` 与 `component=comfy` 的跨组件活跃区间不重叠，并允许据此准确重命名 helper。必须继续逐项断言每个区间 `end_ns >= start_ns`，并保留精确操作顺序、cache miss/hit、cache hit 无 chat、transport failure 与 finally free 的全部既有断言；不得引入时间容差，不得修改该文件其他内容、任何生产代码或其他测试，不得 skip、删除、改名测试或弱化其他断言。本例外在 C009 归档时失效，不得类推。
- **C009 PyAV 按需导入的一次性窄修正（需求方于 2026-09-02 明确授权）**：仅允许在 T22A 修改 `backend/tests/task_system/test_c009_video_files.py::test_probe_rejects_missing_or_invalid_container_duration`，把 monkeypatch 目标从 `video_files.av` 精确改为该测试文件已经直接导入的 `av`。必须保留全部参数、错误消息与断言；不得修改该用例其他内容、该文件其他测试或任何其他既有测试，不得 skip、删除、改名或弱化断言。本例外只为适配 `backend/app/services/video_files.py` 将 PyAV 导入从模块顶层移动到 `probe_clip_video_duration()` 内部的 T22A 生产边界，不授权兼容属性、lazy proxy、测试特判或其他生产改动；本例外在 C009 归档时失效，不得类推。
- **C009 全路径 Comfy `/free` 既有断言的一次性窄演进（需求方于 2026-09-02 明确授权）**：仅允许在 T25 修改 `backend/tests/task_system/test_c009_gen_clip_video.py` 的三个既有断言：`test_c009_gen_clip_video_rejects_hostile_vllm_response` 中 `comfy.free_calls == 0` 精确改为 `== 1`；`test_c009_gen_clip_video_vllm_transport_error_is_not_retried` 中 `comfy.free_calls == 0` 精确改为 `== 1`；`test_c009_gen_clip_video_cancels_at_every_worker_safe_point` 中按 `cancel_at` 判定 0/1 的表达式精确改为所有安全点 `comfy.free_calls == 1`。必须保留这些用例的参数、vLLM 调用顺序、upload/submit 断言、原始异常、无重试、temp 清理、安全点数量及其他全部断言；不得修改三个断言之外的该文件内容或任何其他既有测试，不得 skip、删除、改名或弱化断言。生产实现必须以单一 cleanup owner 保证每条失败/取消路径 `/free` 精确一次，不得使用测试特判、双重 free、fallback 或吞异常；本例外在 C009 归档时失效，不得类推。
- 完成 task 后运行其计划测试与完整 `pytest`，报告真实命令和原始结果；失败或未运行时必须明确说明，不能勾选完成。
