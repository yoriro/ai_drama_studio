# 测试追溯表

本表是“测全且不过度”的唯一裁决依据。用例 ID 在对应 change 实施时回填；同一用例可以回填多行，以避免重复测试，但不得存在不归属本表任一行的测试。

| 规则 / 场景 | 计划测试层级 | 用例 ID（待填） |
|---|---|---|
| C001 基础设施 smoke：FastAPI 应用可启动，`/docs` 可访问，`/api/system/health` 返回明确的未检查骨架且不调用外部服务，通用 API 错误体符合约定 | API 集成 | `backend/tests/api/test_system.py::test_infrastructure_smoke` |
| R1 无资产禁止生成分镜：项目资产为 0 时 `generate-shots` 返回 409 | API 集成 | 待填 |
| R2 生成资产增量合并：只插入 `existing_id=null` 项，既有资产不改不删，成功后记录剧本修订 | 任务系统 mock + API 集成 | 待填 |
| R3 生成分镜覆盖：impact/token 校验；新分镜成功后才删除旧数据并移入 trash；LLM 失败旧数据不动 | 任务系统 mock + API 集成 | 待填 |
| R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存 | 纯函数 + 任务系统 mock | 待填 |
| R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422 | 纯函数 + API 集成 | 待填 |
| R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检 | 纯函数 + API 集成 + 任务系统 mock | 待填 |
| R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH | 纯函数 + API 集成 | 待填 |
| R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排 | 纯函数 + API 集成 | 待填 |
| R8 数量提示：候选或选择超过 9 阻止创建，启用槽位超过 4 只给软提示 | API 集成 | 待填 |
| R9 槽位取图优先级：override 图优先于资产当前图 | 纯函数 + API 集成 | 待填 |
| R10 缺图即失败：任一启用槽位无可用图时任务失败并指出槽位与原因 | 任务系统 mock | 待填 |
| R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot | API 集成 | `backend/tests/api/test_c002_prompt_templates.py::test_prompt_templates_and_edits_preserve_downstream_rows`（C002 覆盖模板可见可编辑及默认响应无中间字段；DEBUG_PROMPTS 详情待 C007/C009） |
| R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10 | API 集成 + 任务系统 mock | 待填 |
| §3.3 编辑剧本：分镜、片段、文件均不动，只出现集级旧剧本角标 | API 集成 | `backend/tests/api/test_c002_script.py::test_script_revision_preserves_downstream_rows`（C002 覆盖 API 语义；旧剧本角标待 C005/C006） |
| §3.3 重新生成资产（增量）：分镜、片段、文件均不动 | 任务系统 mock | 待填 |
| §3.3 重新生成分镜：成功后覆盖本集分镜、删除本集片段并将文件移入 trash | 任务系统 mock + API 集成 | 待填 |
| §3.3 编辑资产或换当前图：绑定分镜 changed、相关片段 stale、文件不删 | API 集成 | `backend/tests/api/test_c003_assets.py::test_asset_edit_and_current_image_preserve_downstream_rows`（C003 部分覆盖：资产名称/描述与当前图 revision、同值不增、文件不删；绑定分镜 changed 与片段 stale 待 C006/C008-C009） |
| §3.3 删除资产：解绑并 changed、相关片段 stale、槽位按 R12 处置、资产图片入 trash | API 集成 | `backend/tests/api/test_c003_assets.py::test_delete_asset_moves_all_images_to_trash`（C003 部分覆盖：资产/图片行删除与全部图片入 trash；changed/stale、槽位快照与完整 R12 待 C006/C008-C009） |
| §3.3 编辑分镜文本或绑定：该分镜 changed、包含它的片段 stale、文件不删 | API 集成 | 待填 |
| §3.3 编辑风格或模板：分镜与片段不动、文件不删，下次生成因 hash 失配重建 prompt | API 集成 + 任务系统 mock | `backend/tests/api/test_c002_prompt_templates.py::test_prompt_templates_and_edits_preserve_downstream_rows`（C002 覆盖 API 即时可读及下游不变；hash 失配与任务 mock 待 C007/C009） |
| §3.3 删除片段：其分镜释放、片段删除、视频移入 trash | API 集成 | 待填 |
| §3.3 片段生成成功且修订未变：相关分镜 normal、片段 ready + fresh、新 take 落盘 | 任务系统 mock | 待填 |
| §3.2 完成判定反竞态：source_revisions 全一致时回写 fresh/normal；任一不一致时产物仍保存且 ready，但不得覆盖 stale/changed | 任务系统 mock | 待填 |
| §6.1 重启恢复：遗留 running 任务变为 failed("server restarted")，queued 任务保留并继续消费 | 任务系统 mock | `backend/tests/task_system/test_task_queue.py::test_restart_fails_running_and_continues_queued` |
| §6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断 | 任务系统 mock + API 集成 | `backend/tests/task_system/test_task_queue.py::test_queued_cancel_is_terminal`; `backend/tests/task_system/test_task_queue.py::test_running_cancel_stops_at_safe_point`; `backend/tests/api/test_tasks.py::test_cancel_task_states` |
| §6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务 | API 集成 | 待填 |
