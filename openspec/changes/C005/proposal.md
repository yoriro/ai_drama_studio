# C005 M2 gen_assets Proposal

## 元数据

- Change：`C005`
- 里程碑：PRD §11 M2 的 `gen_assets` 切片
- 前序 change：`C004`
- ROADMAP 范围：vLLM guided_json 增量资产生成、剧本修订角标、生成按钮与结果呈现
- 直接 R 规则：R2
- 当前状态：C005 已于 2026-08-27 完成 T1-T13；Sol 再次复审通过，可进入归档准备

## Gate 报告

### 已核对输入与现状

本 change 已按要求核对根目录 `AGENTS.md`、`openspec/ROADMAP.md` 的 C005 行、`openspec/project.md`、`openspec/TRACEABILITY.md`、当前代码、现有 change 文档与 `openspec/archive/`，并完整回看 PRD §0、§2.1(4,11)、§3、§5 生成动作、§6.1-§6.4、§7、§9、§11、§12。`openspec/archive/` 当前没有已归档 change 可继承。

C004 最新修复提交 `46eadcc` 已由 Sol 只读复审通过：专用 PostgreSQL 上 Alembic 保持既有 head、`alembic check` 无新操作、队列 lock/events 验收正常、后端完整测试为 `9 passed`、前端生产构建成功，真实浏览器可观察 done/failed 任务的完整终态详情。C005 因而可以依赖其 task 入队、单 worker、失败不重试、同目标 active 去重、REST 任务读取与 WS 观察链路，不假设任何生成处理器已经存在。

截至提交 `37ea7ea`，当前代码已交付 `POST /episodes/{id}/generate-assets`、入队快照、vLLM guided_json 客户端、`gen_assets` handler、R2 增量合并、生成按钮、真实结果呈现和旧剧本角标。提交 `b715ddd`、`d870ddb`、`d19c9b9` 分别修复了超出 PostgreSQL `INTEGER` 范围的伪造 `existing_id`、取消与业务提交竞态、空白字符非空 body；`b0503cb` 修正新增竞态用例的清理。Sol 在全新隔离 PostgreSQL、正式模板验收库、真实 vLLM、真实 API 和浏览器上再次复核后，未发现剩余实现偏差。

### 冲突检查结论

未发现 PRD、ROADMAP、现有代码或 C004 之间会改变行为的冲突。此前缺失的行为已经由用户裁决并写回 PRD/TRACEABILITY：

1. `existing_id` 不存在或不属于当前项目时降级为新增并记录 warning，不得静默忽略。
2. 成功标记写任务入队快照的 `script_revision`，运行中改剧本后仍显示旧剧本角标。
3. `script2assets` 整体作为单条 user message；`existing_assets` 为固定四字段紧凑 JSON 数组；guided_json 使用封闭 schema；默认温度 `0.2`。
4. 用户提供的完整模板是 C005 的业务规则唯一来源；代码不得另藏一份业务 prompt。

当前没有需要执行者自行裁决的 Open Question。外部依赖已经满足 C005 的开工与验收门槛，T10-T13 的修复与回归也已通过；C005 当前无外部依赖或实现阻塞。

## 目标

让用户在集工作区用当前剧本、项目风格和项目已有资产发起一次 `gen_assets`：API 把所有输入固化进 C004 task payload，worker 仅使用该快照调用 vLLM guided_json，按 R2 只新增模型判定为新增的资产，对合法复用项不改不删，对伪造/跨项目 id 降级新增并记录 warning；成功后写入快照剧本修订号。前端提供生成入口、任务反馈、结果呈现和“资产提取基于旧剧本”角标。

## 范围内

1. 增加 vLLM 结构化生成边界，使用项目配置的 vLLM 地址、模型和默认温度 `0.2`。
2. 使用用户已确认的 `script2assets` 模板；把完整渲染结果作为单条 user message，业务规则不得拆到代码或隐藏 system message。
3. `{{existing_assets}}` 固定注入项目当前 `character`/`scene` 资产的紧凑 JSON 数组，字段仅 `id/type/name/description`；空项目注入 `[]`。
4. guided_json 同时使用模板内格式说明和 vLLM 侧封闭 JSON schema；只接受 `character`、`scene`，不接受 `prop`。
5. 增加 `POST /api/episodes/{id}/generate-assets`，以 episode 为 target 创建一条 `gen_assets` task，并沿用 C004 的同目标 active 去重。
6. 入队时快照剧本、剧本修订号、项目风格、模板正文、已有资产、模型与温度；worker 不回读当前值替换生成输入。
7. 落实 R2 增量合并：`existing_id=null` 新增；真实属于当前项目的非 null id 只复用、不更新不删除；不存在或跨项目的非 null id 按新增插入并 warning。
8. 所有新增资产与 `assets_generated_script_revision` 在成功路径的同一数据库事务中提交；任一步骤失败不留下部分新增或成功标记。
9. 集工作区剧本页提供“生成资产”按钮、入队后的 task id/任务中心入口；资产页呈现新入库资产。
10. 当 `assets_generated_script_revision` 非空且小于当前 `script_revision` 时，剧本相关界面显示“资产提取基于旧剧本”角标。
11. 只在 TRACEABILITY 已有行内计划 API 集成与任务系统 mock；实现时回填真实通过的用例 ID。

## 范围外

- 不实现 `gen_shots`、影响预检、confirm token、分镜覆盖/编辑/绑定或 changed；延后至 C006。
- 不实现资产参考图、Z-Image、ComfyUI、input_hash 缓存、GPU sleep/free 调度或图片版本画廊新增能力；延后至 C007。
- 不实现 clip 预检、创建、槽位与 R5-R12；延后至 C008。
- 不实现 `gen_clip_video`、MiniMax H3、视频 take、actual_duration 或两维状态；延后至 C009。
- 不实现导演台；延后至 C010。
- 不完善任务中心取消/历史/过滤或全局视觉设计；延后至 C011。
- 不做完整生产 E2E、发布级重启/竞态总回归；延后至 C012。
- 不为人物/场景做别名、合并、候选版本或模板/风格版本化；不预建任何后续表、字段、接口或 UI。
- 不在后端复制模板中的实体识别、2-8 字命名、60-150 字描述、场景拆分等语义规则；本 change 的硬校验边界仅为已确认的 JSON schema、项目归属和现有持久化约束。
- 不新增自动轮询；结果与角标通过现有页面进入/切换时刷新及 C004 任务观察链路呈现。

## 现状与预期影响

- 后端配置会新增 `VLLM_TEMPERATURE`，默认 `0.2`；不新增表或 Alembic revision。
- 后端增加 episode 生成动作、快照构造、vLLM 结构化调用和 `gen_assets` handler；C004 队列/状态机本身不改变。
- 生成成功只可能新增项目资产并更新该 episode 的资产生成剧本修订标记；既有资产、图片、shots、clips、媒体文件均不改动。
- 前端集工作区增加生成动作和旧剧本角标，并复用现有任务中心与资产列表；不进行全局 UI 重构。
- `openspec/TRACEABILITY.md` 只在实施完成时回填 C005 实际新增且通过的用例 ID。

## 依赖

### 前序 change

C004 是唯一直接前序 change，已通过复审。C005 依赖其不可变 payload、worker handler 接线、失败不重试、状态条件转换、同 episode active 去重、任务 REST/WS 可观察性。C005 不修改 C004 的 schema、advisory lock、claim、heartbeat、取消或 WS 重连合同。

### 外部依赖

| 来源（PRD §12） | 开工或验收门槛 | 当前证据 | 缺失项与处理 |
|---|---|---|---|
| §12.1 Z-Image 与 MiniMax H3 工作流/绑定 | 非 C005 开工或验收门槛 | 前置依赖清单仍为待提供 | C005 不访问 ComfyUI、不读取工作流；分别留待 C007/C009，禁止伪造 |
| §12.2 `script2assets` 正式模板 | 实现可依据本 spec 开始；真实生成验收前必须把本 spec 冻结的完整模板保存到目标环境的 `script2assets` 并读回核对 | 2026-08-27 在正式模板验收库通过 `GET /api/prompt-templates` 读回，与 spec §5.1 正文逐字一致且不以 `[占位]` 开头 | C005 门槛已满足；其余三个模板仍留待对应 change/C012，不得用迁移、代码常量或隐藏 system prompt 替代设置值 |
| §12.2 其余 `script2shots`、`zimage`、`minimaxh3` 模板 | 非 C005 门槛 | 可继续占位 | C005 不读取；留待对应 change/C012 |
| §12.3 vLLM `--enable-sleep-mode` 与 sleep/wake 验证 | C005 的真实流水线验收前，已配置实例必须能执行 PRD gen_assets 的 wake 步骤 | 2026-08-27 对本机 vLLM 实例实际调用 `/wake_up` 返回 200，随后封闭 JSON schema 请求成功解析 | C005 所需 wake 门槛已满足；完整 sleep/free 分时能力仍须在 C007 开工前另行验证，当前证据不得外推 |
| §12.4 PostgreSQL DSN | 开工与验收门槛 | 2026-08-27 再次复审使用全新隔离库 `ai_drama_studio_c005_reaudit_20260827` 与独立正式库 `ai_drama_studio_c005_acceptance_20260826`；隔离库从空库升级至 `6b8e3f0a1d24 (head)`，`alembic check` 无新增操作，C005 定向用例 `9 passed`、完整后端 `18 passed`，测试后 projects/episodes/assets/tasks 均为 0；正式库同为 head 且已有 15 条真实 done `gen_assets` 任务和 5 条 generated 资产 | C005 外部数据库门槛与修复后验收均已满足；默认库状态不作为本 change 的验收替代 |
| §12.4 vLLM 地址与端口 | **C005 开工前必须到位** | 2026-08-27 已验证 `http://localhost:8001`：`/v1/models` 返回 200，模型为 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`，`/wake_up` 返回 200，温度 `0.2` 的封闭 schema 调用成功 | C005 门槛已满足；地址不写入业务 payload，不把示例值或一次成功外推为 C007 的 Comfy/sleep 验收 |
| §12.4 ComfyUI 地址与端口 | 非 C005 门槛 | 尚待提供 | 留待 C007，不得在 C005 接入 |

## Open Questions

无。若实施时发现 vLLM 的真实 OpenAI-compatible structured-output 参数与已冻结合同不兼容，或现有队列 handler 接线要求改变 payload/状态语义，必须停下并附真实请求/响应或代码证据报告，不得自行改 schema、增加解析 fallback 或把问题藏进 prompt。

## 2026-08-27 Sol 再次复审结论

C005 通过。此前三项偏差均已关闭：超范围 `existing_id` 会 warning 后降级新增；取消与资产/marker/done 提交由同一数据库事务裁决且两种胜方均有受控屏障用例；任何非零字节请求 body（含空白字符）均返回结构化 422 且不入队。

再次复审的独立证据为：全新隔离库迁移到 `6b8e3f0a1d24 (head)` 且 `alembic check` 无新增操作；9 个 C005 定向用例全部通过，完整后端为 `18 passed`；前端生产构建成功；正式模板通过 API 与 spec §5.1 逐字一致；真实 vLLM `/wake_up` 成功并以模型 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`、温度 `0.2` 返回可由封闭 schema 校验的 `{"assets":[]}`；真实 API 已核对零字节 404、空白/`{}`/`null`/文本 422、非法 path 422、错误方法 405，错误体均为固定结构；浏览器可见生成按钮、5 条真实资产及最新 done 任务；C005 未新增 migration，既有测试未修改，范围围栏扫描无违规命中。

`openspec/TRACEABILITY.md` 已回填 T10/T11 的真实 node ID，T1-T13 checkbox 与复审结果一致。C005 可以进入文档提交与 archive 工作流；归档动作本身不在本次审计范围内。

## 风险与控制

- **模板与硬 schema 漂移**：模板负责提取质量，response_format 负责结构；二者必须同时发送。运行时模板缺关键占位符属于前置冲突，不能用代码内默认模板补上。
- **快照被绕过**：worker 只读任务 payload；运行中编辑剧本、风格、模板或资产不得改变本次请求。完成标记必须写快照剧本修订号而非当前修订号。
- **模型编造 existing_id**：每个非 null id 都按当前项目归属复核；无效时新增并带上下文 warning，避免资产静默丢失。
- **半成功**：JSON 解析、schema 校验、vLLM、数据库任一步失败，新增资产和修订标记均不提交；task 记录完整错误且不重试。
- **重复点击**：后端 C004 active 去重是最终裁决；前端按钮状态仅改善体验，不得把双击安全寄托在 UI。
- **隐藏业务规则**：system message 若客户端协议确实要求，只能使用已冻结的一句通用说明；不得把业务规则拆到 system、客户端常量或第二模板。
- **结果陈旧**：C005 不增加轮询；用户进入/切换资产页时读取数据库真相，任务终态由 C004 任务中心可观察。
- **测试越界**：只覆盖 R2、§3.3 增量无损与 §6.1 gen_assets 去重的既有追溯行；UI、配置接线与纯客户端形状用构建和人工检查，不另造自动测试。

## 完成定义

只有在外部 gate 满足后，全部 tasks 按顺序完成，真实 vLLM 请求同时包含完整单条 user prompt 与封闭 guided_json schema，R2 三类 existing_id 路径和快照竞态均可观察，失败无部分写入且不重试，双击只有一条 active task，前端按钮/任务反馈/结果/旧剧本角标可人工走通，授权测试、完整 pytest、前端构建、Alembic 无变更与范围扫描全部通过，C005 才可提交 Sol 审查。
