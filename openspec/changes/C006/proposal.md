# C006 M2 gen_shots Proposal

## 元数据

- Change：`C006`
- 里程碑：PRD §11 M2 的 `gen_shots` 切片
- 前序 change：`C005`
- ROADMAP 范围：无资产拦截、影响预检与确认 token、vLLM guided_json 分镜生成、成功后覆盖、分镜查看/编辑/绑定、changed 与旧剧本角标
- 直接 R 规则：R1、R3
- 当前状态：实现、真实模型/UI 走查与 Sol 复审均已通过（复审提交 `dd34138`，2026-08-28）；需求方已确认归档

## Gate 报告

### 已核对输入与现状

本 change 已完整读取根目录 `AGENTS.md`、`openspec/ROADMAP.md` 的 C006 行、`openspec/project.md`、`openspec/TRACEABILITY.md`，并完整回看 PRD §0、§2.1(4,6,11)、§3.1-§3.3、§4 shots/shot_assets/clips、§5 生成动作与分镜、§6.1-§6.4、§7、§9-§12。`openspec/archive/` 当前只有 `.gitkeep`，没有可继承的归档 change。

C005 已在提交 `37ea7ea` 后由 Sol 再次复审通过。C006 当前已在 `49d7381..dd34138` 实现并复审：具备 impact/token、`generate-shots` 入队与动态 schema、`gen_shots` 严格校验和 R3 覆盖/trash、分镜 GET/PATCH、Shot/Clip 级联、剧集/项目删除兼容，以及剧本页生成入口、任务完成刷新和分镜页。C006 继续复用 C004 队列/WS 与 C005 vLLM 客户端，未新增 migration、表或后续 change 能力。

C001 已按 PRD §4 创建 `shots`、`shot_assets`、`clips`、`clip_shots`、`clip_ref_slots`、`clip_videos` 和 `tasks` 全量结构，因此 C006 不需要且不得创建 migration。现有外键不足以自动完成 R3 的全部删除顺序：`clip_videos`、`shot_assets` 等依赖必须由业务事务显式处置，clip 视频和 override 文件必须按 §6.4 移入 trash。

### 用户本轮已冻结的 C006 输入

1. `script2shots` 使用本 change spec §5.1 的完整“分镜拆解器”模板，模板是业务规则唯一来源。
2. `{{assets}}` 注入按资产 id 升序的紧凑 JSON 数组，每项只含 `id/type/name/description`；描述不可省略。
3. guided_json schema 在入队时由资产快照动态冻结：`asset_ids.items.enum` 等于该快照全部合法资产 id；`duration_est` 为 1..5；`shot_type`、`camera` 使用封闭枚举；全字段 required，顶层和 item 均 `additionalProperties=false`。
4. 模型输出引用不在快照/项目中的资产 id 属于数据完整性错误，任务直接 failed；不得降级、忽略或近似绑定。
5. 单分镜绑定 0 个或不少于 2 个场景都允许落库。0 场景只显示提示角标；不少于 2 场景显示需修正警示。C006 不因此拒绝生成或 PATCH，也不提前实现 C008 的片段组建裁决。
6. 真实验收继续使用 C005 已生成资产的剧本；另用跨地点转场和纯特写剧本核对转场拆镜与特写零场景。这两项验证真实模型质量，不得用后端修补或 mock 结果冒充。

### 冲突检查结论

未发现 PRD、ROADMAP、用户冻结输入、C005 或当前代码之间会改变行为的冲突：

- 用户要求的动态 enum 是 PRD §2.1(11)、§7 的直接落实。
- “0/多场景允许分镜落库”与 R5a 相容：R5a 约束的是后续片段预检/创建/视频生成，不禁止 Shot 本身存在；PRD §9 还明确要求分镜页为两类情况显示角标。
- R3 明确要求先完成 LLM 生成与校验，再覆盖旧分镜、删除旧片段并移入 trash；C006 将复用 C005 的任务终态原子裁决，不改变 C004 通用队列。
- `prop` 只在 C001 数据库约束中预留，C006 的资产快照、动态 enum、绑定 API 与 UI 只接受 `character/scene`。

当前没有需要执行者自行裁决的 Open Question。实现不得自行改变 token TTL、空/多场景语义、模板正文、动态 schema、覆盖顺序或错误码。

## 目标

让用户从集工作区用当前剧本、项目风格和当前项目资产发起一次安全的 `gen_shots`：先查看会删除的片段/视频影响并在需要时确认；API 把剧本、风格、模板、资产、动态 schema 与待覆盖结构固化进任务 payload；worker 只用该快照调用真实 vLLM，完整校验新分镜后才覆盖旧结构并把 clip 媒体移入 trash。用户可在分镜页查看和编辑文本/资产绑定，看到 changed、场景绑定质量和“分镜基于旧剧本”角标。

## 范围内

1. 增加 `POST /api/episodes/{id}/generate-shots/impact`，返回 R3 的片段数、视频数、10 分钟确认 token；token 绑定该集当前完整破坏性影响快照。
2. 增加 `POST /api/episodes/{id}/generate-shots`，执行 R1、token、模板/风格、同目标 active 去重与请求边界校验，返回 queued `gen_shots` task。
3. 入队时快照剧本、剧本修订、风格、完整 `script2shots`、四字段资产清单、渲染后单条 user prompt、模型、温度、动态 guided_json schema、当前旧分镜/片段/视频影响和 source revisions；`input_hash=null`。
4. 使用 spec §5.1 完整模板；代码不得复制其中的拆镜、绑定、描述、台词或镜头语义，也不得隐藏第二份 system 业务 prompt。
5. 严格解析 `shots` 输出，强制结构、类型、枚举、1..5 秒、order 从 1 连续递增、asset_ids 唯一且属于入队快照及执行时当前项目；任何非法 id 或结构错误使整任务 failed。
6. 按 R3 先完成 vLLM 与全部校验，再在最终提交阶段覆盖本集旧 shots/shot_assets，删除本集 clips 及其关系、槽位和 clip_videos，相关 clip 视频与 override 文件移入 trash，写入快照 `shots_generated_script_revision`，新 Shot 为 `status=normal/revision=1`。
7. 复用 C005 的“业务写入与 done 同一数据库事务”裁决：取消先赢时结构和文件不变；业务提交先赢时新结构、marker 与 done 为同一胜方；失败不重试。
8. 增加按 order_index 排序的分镜读取和 Shot PATCH。PATCH 只允许 `shot_type/camera/description/dialogue/asset_ids`，不允许修改 order、duration、status、revision 或归属；实际变化使该 Shot revision+1/status=changed，并把包含它的 Clip 标为 stale，文件不删。
9. 补齐 C006 可达级联：资产名称/描述或 current 实际变化时，绑定 Shot→changed、含这些 Shot 的 Clip→stale；删除资产时先识别受影响 Shot/Clip，再解绑、changed/stale 并保持 C003 图片 trash。完整 R12 槽位处置仍留给 C008-C009。
10. 让现有 episode/project 删除能够清理 C006 已可达的 Shot 结构，并复用 R3 clip 媒体清理，避免生成分镜后既有删除能力退化；不新增删除 API。
11. 在剧本页增加“生成分镜”入口、影响确认弹窗、task id/任务中心反馈和分镜旧剧本角标；把分镜选项卡升级为真实列表/编辑/绑定页，显示 changed、0 场景提示和多场景警示。
12. 只在 TRACEABILITY 已有 R1、R3、R5a、§3.3 相关级联、§6.1 取消/去重行内计划自动测试；UI、外部服务、模板部署和现有删除兼容采用命令/真实浏览器验收。

## 范围外

- 不实现候选分镜版本、分镜新增/删除/拆分/合并/排序、单 Shot 重生成或生成历史；这些能力被 PRD §0 排除。
- 不实现 clip preview、创建、连续/独占/同场景最终裁决、时长裁决、参考资产选择、槽位编排或 R5-R9/R12 完整行为；延后至 C008。
- 不实现 `gen_clip_video`、生成前 R5/R5a/R10 复检、MiniMax、take、actual_duration 或完成反竞态；延后至 C009。
- 不实现 Z-Image/Comfy、资产出图、input_hash 缓存、GPU sleep/free；延后至 C007。
- 不实现导演台一带两轨一板；延后至 C010。
- 不做全局视觉专题、任务中心历史/过滤完善或周期轮询；延后至 C011。
- 不做完整发布 E2E 与级联矩阵总回归；延后至 C012。
- 不把模板中的 20-30 镜、30-80 字、纯视觉、台词格式、场景连续、跨地点拆镜等模型质量规则复制成第二套 NLP/启发式校验器；真实模型质量由正式模板和真实验收裁决。
- 不新增表、列、索引、migration、token 表、generation_runs、模板/风格版本、continuity、context loop、fl2v 读写或音频。

## 现状与预期影响

- 后端会新增 impact/generate-shots/shot API、进程内短期确认 token 状态、动态 schema 构造、`gen_shots` handler、R3 覆盖/trash 与 Shot/Asset 级联服务；不改变数据库 schema。
- 确认 token 是单进程、短 TTL 的破坏性操作确认凭据，不是鉴权、幂等键、版本表或生成记录；服务重启后旧 token 安全失效，用户重新预检。
- 前端只增加 C006 所需生成确认和分镜管理，不改变 C005 资产生成、任务中心协议或后续导演台。
- C006 会让此前只存在于 schema 的 shots/shot_assets 成为正常可达数据；clips 仅为 R3 删除、级联 stale 和验收夹具所读取，不提供创建/编辑 UI/API。
- `openspec/TRACEABILITY.md` 只在实施通过后由 Sol 回填 C006 实际 node ID；Luna 不修改该文件。

## 依赖

### 前序 change

C005 是唯一直接前序 change，已通过 Sol 再次复审。C006 依赖其真实 vLLM structured-chat 客户端、温度配置、单 user message、快照输入、失败不重试和任务/业务同事务终态裁决；依赖 C004 的 active 去重、取消、heartbeat、重启恢复和 WS。C006 不重构这些通用能力，只增加 `gen_shots` 的调用方与 handler。

### 外部依赖

| 来源（PRD §12） | 开工或验收门槛 | 当前证据 | 缺失项与处理 |
|---|---|---|---|
| §12.1 Z-Image、MiniMax H3 工作流与绑定 | 非 C006 门槛 | `docs/前置依赖清单.md` 仍为待提供 | C006 不访问 ComfyUI/工作流；分别留待 C007/C009，禁止伪造 |
| §12.2 `script2shots` 正式模板 | 文档与非真实链路实现可开始；真实 `gen_shots` 验收前必须通过设置 API 保存 spec §5.1 正文并逐字读回 | 2026-08-28 正式验收 API 返回 200；`script2shots` 与 spec §5.1 逐字一致（1181 字符），三个占位符齐全且不再是占位内容 | 门槛已满足；正式模板只存在于验收库设置数据，migration 仍保留占位种子 |
| §12.2 其他模板 | 非 C006 门槛 | `script2assets` 已在 C005 正式库部署；`zimage/minimaxh3` 待提供 | C006 只读取 `script2shots`，不得因其他模板占位而扩大范围 |
| §12.3 vLLM sleep/wake | C006 只要求 LLM 前 wake；完整 sleep/free 是 C007 开工门槛 | C005 已真实验证 `/wake_up` 和封闭 schema；用户明确说明同一 vLLM 已提供给 Luna并完成测试 | C006 可沿用 wake 能力；不得把它外推为 C007 的完整 sleep/free 证据 |
| §12.4 PostgreSQL DSN | C006 自动测试与真实验收前必须有独立可验证数据库 | 2026-08-28 Sol 复审在全新隔离库 `ai_drama_c006_reaudit_acd92530` 从空库迁移至 `6b8e3f0a1d24 (head)`；`alembic check` 无新增操作，完整后端 `32 passed in 18.12s`，验收后隔离库已删除 | C006 门槛已满足；正式模板/真实模型继续使用独立正式验收库，不与干净 pytest 库混用 |
| §12.4 vLLM 地址与端口 | 沿用 C005；真实 C006 schema/模板验收前需仍可达 | 2026-08-28 `/v1/models` 返回 200 和 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`；正式库已有两条真实 `gen_shots` done，输出 order、duration 与资产 id 完整性复核通过；动态 schema 不含不受支持的 `uniqueItems`，重复 id 仍由后端拒绝 | C006 门槛已满足；Comfy 与完整 sleep/free 仍分别留待 C007/C009 |
| §12.4 ComfyUI 地址与端口 | 非 C006 门槛 | 待提供 | 留待 C007，不得接入 |

## 风险与控制

- **破坏性覆盖误删**：impact token 绑定精确 clip/video/override 影响而不只绑定数量；enqueue 后最终提交再核对待覆盖 Shot/Clip revisions 与行集合。快照变化时任务 failed，旧数据不动，不静默采用新快照。
- **token 被误当持久凭据**：token 仅用于 10 分钟确认，进程重启即失效；它不是认证、If-Match、request_id 或版本机制。过期/跨集/影响不匹配统一 409，前端要求重新预检。
- **动态 enum 漂移**：完整 schema 与资产四字段快照在入队时冻结；worker 不用执行时新增资产扩展 enum。落库仍复核资产属于当前项目，非法 id 使整任务失败。
- **模型质量与数据完整性混淆**：非法结构/id/order 失败；0 或多场景绑定照常保存并显式提示。跨地点拆镜、描述质量和镜数由模板与真实模型验收，不写后端猜测器。
- **文件系统与数据库无共同事务**：最终阶段在任何移动前锁定并验证全部数据库行和路径，取消胜方在文件移动前确定；成功路径同步移 trash 后提交数据库。仍不得宣称跨系统 ACID，也不得用后台补偿、重试或伪成功掩盖 I/O 失败。
- **级联越界**：C006 只处理 Shot 可达 changed/stale、R3 删除及既有删除兼容；槽位选择/处置、clip 创建和视频生成语义留待 C008-C009。
- **正式模板污染全量 pytest**：沿用 C005 双数据库边界。干净 pytest 库保持迁移占位模板；正式验收库保存正式 `script2assets/script2shots`，真实 vLLM/UI 只在正式库走查。
- **grammar 关键字能力边界**：当前正式 vLLM 明确不实现 `uniqueItems`。动态 enum 等结构约束仍由 guided_json 承担，重复 asset id 在任何写入前由后端严格拒绝；禁止退回自由文本、静默去重或自动修补。
- **测试过量**：自动测试只落在追溯表已有行；真实模型的两段剧本质量、UI 角标、模板部署、外部连通和删除兼容只做明确的人工/命令验收。

## 完成定义

只有在正式 `script2shots` 已保存并逐字读回、真实 vLLM 使用冻结单 user prompt 与动态封闭 schema 成功、R1/impact/token/active 去重正确、R3 在 LLM 失败时旧数据无损且成功时完整覆盖并 trash、非法 id failed 而 0/多场景落库、分镜编辑与资产级联状态正确、两个真实剧本质量场景通过、前端按钮/确认/列表/编辑/角标可走通、授权测试与完整 pytest/前端 build/Alembic check/范围扫描全部通过后，C006 才可交付 Sol 审查。

2026-08-28 上述门槛已取得证据并由 Sol 复审通过。审计后修复还以隔离并发探针证明：确认期间修改既有 Clip 和新增 Clip 均被锁阻止，确认快照与最终 replacement snapshot 保持一致。需求方已于 2026-08-28 确认归档。
