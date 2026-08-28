# PRD:傻瓜式短剧创作平台 · v1(MVP)

- PRD 版本:1.2(定稿,可派发开发;取代 1.1)
- 角色:单机个人版,无用户系统。操作者即管理员。半年内严格限定:单机、单操作者、本地网络、不开放公网(Q1 定案)。
- 一句话:把「剧本 → 资产 → 分镜 → 视频片段」的 LLM 结构化拆解与 ComfyUI 工作流编排,封装成项目制 Web 应用;用户只输入剧本和点按钮。

## 0. 变更摘要(供 diff)

### v1.2 实施裁决补充(2026-08-26)

1. **R2 非法 existing_id 防丢失**:生成资产输出中的非 null `existing_id` 必须属于当前项目;不属于当前项目或不存在时,该项降级为新增资产并记录 warning,避免因编造 id 被静默忽略。
2. **gen_assets 修订归属**:`episodes.assets_generated_script_revision` 写入任务入队快照中的 `script_revision`,生成期间剧本若被编辑,完成后仍须显示“资产提取基于旧剧本”。
3. **script2assets 调用合同**:现有资产以只含 `id/type/name/description` 的紧凑 JSON 数组注入;无资产时为 `[]`;模板整体作为单条 user message;结构由 guided_json 的封闭 JSON schema 硬约束;默认温度为 `0.2`。

### v1.2 相对 v1.1(导演台补充)

1. 新增 **R5a 同场景约束**:片段内所选分镜的场景类资产去重后至多 1 个;未绑场景的分镜可加入任意片段,全特写的「纯人物片段」合法;绑定 ≥2 个场景的分镜不能组入任何片段;gen_clip_video 入队前复检 R5/R5a。
2. **R7 槽位排序**由「资产创建时间」改为「所选分镜序列中的首次出场先后」:人物在前、场景垫底,同一分镜内并列按 asset_id 升序破,保证确定性(重抽不漂)。
3. **删除 clips.order_index**:片段在时间轴上的位置由其首个分镜的 order_index 派生,只读,不可手动排序。
4. **导演台 UI 定为「一带两轨一板」**:场景带 / 分镜轨 / 片段轨 + 详情面板;未覆盖分镜显示为空洞,不阻断;分镜页对绑定 0 或 ≥2 个场景的分镜挂提示角标。

### v1.1 相对 v1.0

1. 片段创建改为「预检 → 选择参考资产 → 创建」三步,解决 >9 资产死锁(原 R7/R8 重写)。
2. minimaxh3 模板新增 `{{references}}` 槽位语义映射,视频提示词与参考图形成稳定绑定。
3. 提示词缓存判定由「user_note 变更」升级为「input_hash 比对」(R4 重写)。
4. 片段状态拆为 生成态 × 新鲜态 两维;各实体增加 revision;任务入队快照化、完成时按修订比对,杜绝异步竞态污染状态。
5. 定义剧本编辑语义(保留+标记"基于旧剧本");定义风格/模板编辑语义(即时生效于后续生成、不追溯、不版本化)。
6. 重生成分镜保留「覆盖+物理删除」,但增加影响预检、后端确认 token、trash 目录延迟清理三重兜底;且**先生成成功、后执行删除**。
7. 数据模型定案:`clip_shots` 关系表取代 `shot_ids INT[]`;当前版本指针改 `is_current + 部分唯一索引`;`clip_ref_slots.asset_id` 可空 + SET NULL + 名称/类型快照。
8. 时长链路闭环:绑定表增加 `duration_path`;片段增加 `requested_duration / actual_duration`;时长以秒为值直接传给 MiniMax 工作流(Q6 定案)。
9. 生产级硬化:队列以数据库为准(claim + advisory lock + heartbeat + 条件状态转换 + 同目标去重)、文件写入临时目录+原子改名、`/media/{type}/{id}` 取代裸路径、启动时工作流绑定校验与健康诊断。
10. `DEBUG_PROMPTS=true` 时中间提示词可在生成记录详情查看,默认关闭(Q8 定案)。

**范围围栏(对 codex 的硬约束)**:以下机制明确不属于 v1,不得实现、不得预先建表:候选分镜版本、分镜增删/拆分/合并/排序、资产别名与合并、风格/模板版本化、独立 generation_runs 表、continuity 相关字段、context loop、fl2v、音频。唯一预留:`clips.generation_mode` 枚举列(默认 `ref2v`,预留 `fl2v`/`context_loop` 值,v1 不读写其他值)。

---

## 1. 术语表

| 术语 | 含义 |
|---|---|
| 项目 Project | 一部短剧。资产在项目级共享。创建时指定风格。 |
| 剧集 Episode | 项目下的一集(约 60s)。剧本、分镜、片段挂在集下。 |
| 资产 Asset | 人物(character)或场景(scene)。v1 不含道具(枚举预留 prop)。人物资产图为单张四视图拼图。 |
| 资产图版本 AssetImage | 资产的一次出图/上传结果(抽卡)。`is_current` 标记当前版本。 |
| 分镜 Shot | 2-3s 最小镜头单元,由 Qwen 拆出,绑定资产。 |
| 片段 Clip | 连续且同场景的若干分镜组成的视频生成单元(≤15s)。时间轴位置由其首个分镜派生,不可手动排序。 |
| 参考资产 | 片段创建时从候选资产并集中选出的、实际作为参考图输入的 ≤9 个资产,与槽位一一对应。 |
| 槽位 Slot | 片段参考图位 ref1..ref9。创建时排定,此后固定不重排。 |
| take / ClipVideo | 片段的一次视频生成结果。`is_current` 标记选用版本。 |
| 生成态 generation_state | 片段是否有产出:empty / queued / generating / ready / failed。 |
| 新鲜态 freshness | 产出与当前输入是否一致:fresh / stale(分镜用 normal / changed 表达同一概念)。 |
| revision | 各实体的整数修订号,内容变更即 +1,用于任务竞态判定与缓存判定。 |
| input_hash | 一次生成的全部输入序列化后的哈希,决定是否复用中间提示词。 |
| 中间提示词 | Qwen 生成、送入 Comfy 的最终 prompt。默认不通过 API 暴露;`DEBUG_PROMPTS=true` 时可在生成记录详情查看;始终落库并写日志。 |
| 回收目录 trash | 被"物理删除"的媒体文件先移入 `{DATA_DIR}/trash/`,延迟清理。 |

---

## 2. 能力边界

### 2.1 v1 完成(本 PRD 全部范围)

1. 项目管理首页:项目 CRUD,创建时选风格。
2. 设置页:风格管理、提示词模板管理、系统诊断面板(vLLM/Comfy 健康、工作流绑定校验结果)。
3. 集级工作区:项目内多集,每集四选项卡(剧本 / 资产 / 分镜 / 导演台);资产页展示项目级资产。
4. 剧本页:剧本输入(字数上限)、「生成资产」(增量合并)、「生成分镜」(强制先有资产;影响预检+确认 token 后覆盖);"基于旧剧本"过期角标。
5. 资产页:资产 CRUD 与手动上传;生成资产图(Qwen→Z-Image,input_hash 缓存,抽卡换 seed,多版本,设当前版本);生成可附加意见。
6. 分镜页:查看、编辑文本字段、增删资产绑定;changed 角标。
7. 导演台(一带两轨一板):场景带 + 分镜轨 + 片段轨 + 详情面板;片段预检(连续性、同场景、时长、参考资产选择)→ 创建;槽位管理(启停/override 上传/已删资产处置);生成视频(MiniMax H3 ref2v,本地);take 画廊与选用版本;两维状态呈现;未覆盖分镜为空洞,不阻断。
8. 任务系统:数据库为准的串行队列、WS 进度、取消、失败直接报错不重试、同目标去重。
9. GPU 分时调度:vLLM sleep/wake + Comfy /free,同卡不并发。
10. 全量 REST API + OpenAPI,前端零业务逻辑。
11. guided_json 硬约束输出;分镜 asset_ids 动态枚举约束。
12. 文件:本地磁盘、`/media` ID 寻址、原子写入、trash 延迟清理。

### 2.2 v1.1(创作可用性,已识别、待排期,不在本次开发范围)

候选分镜版本(生成→预览→应用);最小分镜编辑(插入/删除/拆分/合并/排序);资产别名与合并;独立 generation_runs 表与生成历史界面;风格/模板版本化(待评估);项目导出备份。

### 2.3 v2+

context loop 融合;单 shot 局部重生成;fl2v(首帧用户上传);音频路线;道具资产;成片剪辑(拼接/转场/字幕/BGM/导出);用户系统/多租户;Agent 集成(直接消费 v1 REST API)。

---

## 3. 核心业务规则(强制,后端实现)

### 3.1 生成动作

- **R1 无资产禁止生成分镜**:项目资产数为 0 时 `generate-shots` 返回 409。
- **R2 生成资产 = 增量合并**:注入当前项目现有资产清单;Qwen 输出完整所需清单,每项带 `existing_id` 或 null。后端插入 `existing_id=null` 项;非 null `existing_id` 真实属于当前项目时只视为复用,不更新、不删除;非 null id 不存在或不属于当前项目时,按该项返回的 type/name/description 降级插入为新增资产,并记录包含任务与非法 id 上下文的 warning 日志。已有资产的删改仅限用户手动。成功后写 `episodes.assets_generated_script_revision = 任务入队快照中的 script_revision`;生成期间剧本被编辑时不得写成完成时的较新 revision。
- **R3 生成分镜 = 集内覆盖(带兜底)**:
  1. 前端先调 `POST /episodes/{id}/generate-shots/impact`,返回将被删除的片段数、视频数与 `confirm_token`(TTL 10 分钟,绑定该集当前影响快照;影响为空时 token 可省略)。
  2. `POST /episodes/{id}/generate-shots` 携带 token;token 缺失/过期/不匹配 → 409。
  3. 任务执行顺序:**先** LLM 生成并校验新分镜,**成功后**才在同一事务中删除旧分镜、旧片段(DB),媒体文件移入 trash;LLM 失败则旧数据分毫不动。
  4. 成功后写 `episodes.shots_generated_script_revision`,新分镜 status=normal。
- **R4 提示词缓存 = input_hash 判定**:每次 gen_asset_image / gen_clip_video 入队时计算 input_hash;与目标实体缓存的上次 hash 一致 → 复用缓存 prompt、仅换 seed;不一致 → 重新调用 Qwen 构建 prompt 并更新缓存。hash 组成:
  - gen_asset_image:资产 name+description+revision、风格内容、zimage 模板内容、user_note、LLM 模型 ID、工作流 hash。
  - gen_clip_video:各分镜完整对象(含 revision)、references 结构(槽位映射、启停、override 文件 hash、各槽位所用图片 ID)、风格内容、minimaxh3 模板内容、user_note、requested_duration、LLM 模型 ID、工作流 hash。

### 3.2 状态模型、修订与竞态

- 片段两维状态:`generation_state ∈ {empty, queued, generating, ready, failed}` × `freshness ∈ {fresh, stale}`;分镜 `status ∈ {normal, changed}` 即其新鲜态。两维互不覆盖:片段可以同时 generating 且 stale。
- 修订号:`episodes.script_revision`、`assets.revision`、`shots.revision`、`clips.revision`,相应内容变更时 +1(资产:名称/描述/当前版本变更;分镜:任何字段或绑定变更;片段:user_note/槽位启停/override/requested_duration 变更)。
- **任务快照**:入队时将全部输入与 `source_revisions`(涉及的各实体 revision)存入 `tasks.payload`;worker 执行一律以快照为准,不重读当前状态。
- **完成判定(反竞态)**:任务成功时逐一比对 `source_revisions` 与实体当前 revision:
  - 全部一致 → 片段 freshness=fresh,涉及分镜 status=normal;
  - 任一不一致 → 产物照常保存为 take/版本,但片段保持 stale、分镜保持 changed,**不得**回写 normal/fresh。
  - generation_state 无条件按结果置 ready / failed。
- **剧本编辑语义(Q5)**:PATCH 剧本仅 `script_revision += 1`,不删除、不重生成任何东西;当 `assets_generated_script_revision < script_revision` 时剧本页与资产页显示"资产提取基于旧剧本"角标,分镜同理;用户明确点击生成才更新。
- **风格/模板编辑语义(Q3)**:修改即时生效于**后续**生成;不追溯、不标记已生成结果、不做版本化。因风格/模板内容参与 input_hash,下次生成会自动重建提示词;产物行落库的 built_prompt/input_snapshot 保证可追溯。

### 3.3 变更级联矩阵

| 用户操作 | 分镜 | 片段 | 文件 |
|---|---|---|---|
| 编辑剧本 | 不动(集级角标提示) | 不动 | 不动 |
| 重新生成资产(增量) | 不动 | 不动 | 不动 |
| 重新生成分镜(R3) | 本集覆盖(生成成功后) | 本集全部删除 | 移入 trash |
| 编辑资产 / 换当前图 | 绑定分镜 → changed | 含这些分镜的片段 → stale | 不删 |
| 删除资产 | 解绑 + changed | 相关片段 → stale;槽位按 R12 处置 | 该资产图片移入 trash |
| 编辑分镜(文本/绑定) | 该分镜 → changed | 含它的片段 → stale | 不删 |
| 编辑风格 / 模板 | 不动 | 不动(hash 失配,下次生成自动重建 prompt) | 不删 |
| 删除片段 | 其分镜释放 | 删除 | 视频移入 trash |
| 片段生成成功且修订未变 | 其分镜 → normal | ready + fresh | 新 take 落盘 |

changed/stale 仅为提醒态,不阻断任何操作。

### 3.4 片段与参考资产

- **R5 连续与独占**:片段的分镜按 order_index 严格连续;一个分镜同时至多属于一个片段,由 `clip_shots.shot_id UNIQUE` 数据库约束保证;违规 422。
- **R5a 同场景**:所选分镜绑定的场景类资产去重后至多 1 个,否则 422。未绑定场景的分镜不参与判定,可加入任意片段;全部未绑场景的「纯人物片段」合法(无场景槽位,R10 只检查启用槽位)。绑定 ≥2 个场景的分镜不能组入任何片段(preview 列入 violations),须先在分镜页修正绑定。**生成复检**:创建后用户可能修改绑定破坏约束,故 gen_clip_video 入队前复检 R5/R5a,违规任务直接失败并指明原因。
- **R6 时长**:Σ duration_est ≤ `CLIP_MAX_SECONDS`(默认 15,硬校验);< `CLIP_MIN_SECONDS`(默认 5)仅软提醒。`requested_duration = clamp(ceil(Σ duration_est), MIN, MAX)` 为默认值,预检时展示("分镜估算 11.4s → 实际请求 12s"),用户可在创建面板或 PATCH 中修改(整数秒,范围内)。生成时按秒传入工作流 duration 输入(Q6 定案);产出后探测真实时长写入 `actual_duration`。
- **R7 参考资产选择与槽位(取代 v1.0 的"创建前停用槽位")**:
  1. `POST /episodes/{id}/clips/preview` 提交 shot_ids,返回:连续/占用校验结果、Σ duration_est 与建议 requested_duration、候选参考资产列表(所选分镜绑定资产并集,**人物按其在所选分镜序列中的首次出场先后排序、场景垫底**,同一分镜内多个人物并列时按 asset_id 升序;默认全选,>9 时默认预选前 9 个)、violations/warnings。
  2. 正式创建 `POST /episodes/{id}/clips` 提交 `{shot_ids, reference_asset_ids, requested_duration?, user_note?}`;`reference_asset_ids` 必须 ⊆ 候选并集且 1..9 个,否则 422。
  3. 槽位号按最终 `reference_asset_ids` 依「人物首次出场先后、场景垫底、同镜并列按 asset_id 升序」排定 ref1..refN,写入 `clip_ref_slots`(含名称/类型快照),**此后固定不重排**;重抽视频不变。
  4. 未入选的资产仍保留在分镜语义(其信息仍出现在 shots 描述中),只是不作为参考图输入。
- **R8 数量提示**:候选 >9 必须精简至 ≤9 才能创建(后端校验);启用槽位 >4 时界面黄色提示"建议 4 张以内"(软)。
- **R9 槽位取图优先级**:override 图 > 该资产 is_current 版本图;人物四视图整图直接作为参考图。
- **R10 缺图即失败**:生成视频时任一**启用**槽位无可用图 → 任务失败,error_msg 指明槽位号与原因。
- **R12 资产删除后的槽位处置(Q7)**:`clip_ref_slots.asset_id` 置 NULL(ON DELETE SET NULL),槽位号与名称/类型快照保留,前端显示"原资产已删除";该片段 → stale;再次生成前用户必须停用该槽位或上传 override,否则触发 R10 失败。不自动压缩、不重排槽位号。

### 3.5 提示词可见性

- **R11**:模板在设置页可见可编辑;中间提示词不经任何默认 API 返回,DB 存 built_prompt、完整写日志;当环境变量 `DEBUG_PROMPTS=true` 时,`asset_images` / `clip_videos` 详情接口额外返回 built_prompt 与 input_snapshot 供调试(Q8)。

---

## 4. 数据模型(Postgres,SQLAlchemy 2 + Alembic)

```
projects         id PK, name, style_id FK, created_at
styles           id PK, name UNIQUE, prompt_fragment TEXT, created_at, updated_at
prompt_templates id PK, key UNIQUE ∈ {script2assets, script2shots, zimage, minimaxh3},
                 content TEXT, updated_at

episodes         id PK, project_id FK, seq INT, title, script_text TEXT,
                 script_revision INT DEFAULT 1,
                 assets_generated_script_revision INT NULL,
                 shots_generated_script_revision INT NULL,
                 created_at, updated_at, UNIQUE(project_id, seq)

assets           id PK, project_id FK, type ∈ {character, scene, prop},
                 name, description TEXT, source ∈ {generated, manual},
                 revision INT DEFAULT 1,
                 image_prompt_cache TEXT NULL, image_prompt_hash TEXT NULL,
                 created_at, updated_at
asset_images     id PK, asset_id FK, file_path, sha256, seed BIGINT NULL,
                 source ∈ {generated, uploaded}, is_current BOOL DEFAULT false,
                 built_prompt TEXT NULL, input_hash TEXT NULL,
                 input_snapshot JSONB NULL, user_note TEXT NULL, created_at
                 部分唯一索引:UNIQUE(asset_id) WHERE is_current

shots            id PK, episode_id FK, order_index INT, duration_est FLOAT,
                 shot_type, camera, description TEXT, dialogue TEXT,
                 status ∈ {normal, changed}, revision INT DEFAULT 1,
                 created_at, updated_at, UNIQUE(episode_id, order_index)
shot_assets      shot_id FK, asset_id FK ON DELETE CASCADE, PK(shot_id, asset_id)

clips            id PK, episode_id FK,
                 generation_mode ∈ {ref2v, fl2v, context_loop} DEFAULT 'ref2v',
                 user_note TEXT NULL,
                 requested_duration INT, 
                 prompt_cache TEXT NULL, prompt_input_hash TEXT NULL,
                 generation_state ∈ {empty, queued, generating, ready, failed} DEFAULT 'empty',
                 freshness ∈ {fresh, stale} DEFAULT 'fresh',
                 revision INT DEFAULT 1, created_at, updated_at
clip_shots       clip_id FK ON DELETE CASCADE, shot_id FK,
                 position INT, PK(clip_id, shot_id),
                 UNIQUE(shot_id), UNIQUE(clip_id, position)
clip_ref_slots   id PK, clip_id FK ON DELETE CASCADE, slot_no INT(1-9),
                 asset_id FK NULL ON DELETE SET NULL,
                 asset_name_snapshot, asset_type_snapshot,
                 override_image_path NULL, override_sha256 NULL,
                 enabled BOOL DEFAULT true, UNIQUE(clip_id, slot_no)
clip_videos      id PK, clip_id FK, file_path, sha256, seed BIGINT,
                 requested_duration INT, actual_duration FLOAT NULL,
                 is_current BOOL DEFAULT false,
                 built_prompt TEXT NULL, input_hash TEXT NULL,
                 input_snapshot JSONB NULL, created_at
                 部分唯一索引:UNIQUE(clip_id) WHERE is_current

tasks            id PK, type ∈ {gen_assets, gen_shots, gen_asset_image, gen_clip_video},
                 target_id INT, request_id TEXT NULL,
                 payload JSONB(含 input_snapshot, input_hash, source_revisions),
                 status ∈ {queued, running, done, failed, canceled},
                 progress FLOAT 0-1, error_msg TEXT NULL,
                 heartbeat_at NULL, cancel_requested_at NULL,
                 created_at, started_at NULL, finished_at NULL
                 部分唯一索引:UNIQUE(type, target_id) WHERE status IN ('queued','running')
                   —— 仅对 gen_assets / gen_shots 生效(应用层区分或用两个部分索引)
                 部分唯一索引:UNIQUE(request_id) WHERE status IN ('queued','running')
```

约束补充:is_current 版本禁止删除(须先切换,409);current 切换与置位在事务内完成(先清后设);删除实体时其媒体文件移入 trash。**不建 shot_ids 数组列**,片段-分镜关系唯一来源是 clip_shots。片段无 order_index:其时间轴位置由首个分镜(clip_shots 中 position 最小对应的 shot)的 order_index 派生,只读。

---

## 5. API 规范(FastAPI,前缀 /api)

通用:JSON;错误体 `{"detail": {"code", "message"}}`;409=前置/冲突,422=校验失败;生成动作返回 `{"task_id"}`。

```
项目与设置
  GET/POST            /projects
  GET/PATCH/DELETE    /projects/{id}            DELETE 级联删除,文件入 trash
  GET/POST/PATCH/DELETE /styles/{id?}           被引用禁止删除(409)
  GET                 /prompt-templates
  PATCH               /prompt-templates/{key}
  GET                 /system/health            vLLM/Comfy 状态、工作流绑定校验、workflow hash

剧集
  GET/POST            /projects/{id}/episodes
  GET/PATCH/DELETE    /episodes/{id}            PATCH 改剧本 → script_revision+1;超上限 422

生成动作
  POST /episodes/{id}/generate-assets                      R2;同目标去重 409
  POST /episodes/{id}/generate-shots/impact                返回 {clips_count, videos_count, confirm_token, expires_in}
  POST /episodes/{id}/generate-shots                       body: {confirm_token?};R1/R3;同目标去重 409
  POST /assets/{id}/generate-image                         body: {user_note?, request_id?};R4
  POST /clips/{id}/generate-video                          body: {user_note?, request_id?};R4/R9/R10

资产
  GET/POST            /projects/{id}/assets
  GET/PATCH/DELETE    /assets/{id}                         触发 3.3 级联与 R12
  GET/POST            /assets/{id}/images                  POST=multipart 上传(source=uploaded)
  DELETE              /asset-images/{id}                   is_current 禁删(409)
  PUT                 /assets/{id}/current-image           body: {image_id}

分镜
  GET  /episodes/{id}/shots
  PATCH /shots/{id}                                        文本字段与 asset_ids;revision+1;级联

片段(导演台)
  POST /episodes/{id}/clips/preview                        body: {shot_ids};R5/R5a/R6/R7.1
  GET/POST            /episodes/{id}/clips                 POST body: {shot_ids, reference_asset_ids,
                                                             requested_duration?, user_note?};R5-R8
  GET/PATCH/DELETE    /clips/{id}                          PATCH: user_note/requested_duration
  GET                 /clips/{id}/slots                    含已删资产快照展示
  PATCH               /clips/{id}/slots/{slot_no}          {enabled?} 或 multipart override 上传/清除
  GET                 /clips/{id}/videos
  PUT                 /clips/{id}/current-video            body: {video_id}
  DELETE              /clip-videos/{id}                    is_current 禁删(409)

任务
  GET  /tasks?status=&type=&limit=      GET /tasks/{id}
  POST /tasks/{id}/cancel               queued→canceled;running→写 cancel_requested_at + Comfy /interrupt(尽力)
  WS   /ws/tasks                        广播 {task_id, type, status, progress, message}

媒体(取代 v1.0 的 /files/{path})
  GET /media/asset-images/{id}
  GET /media/clip-videos/{id}
  GET /media/slot-overrides/{slot_id}
  按 ID 查库得真实路径后流式返回;不接受任何用户路径输入。
```

上传约束:≤ `UPLOAD_MAX_MB`(默认 20);MIME 白名单 png/jpg/webp;落盘文件名由系统生成,用户文件名不进路径;记录 sha256。

---

## 6. 任务系统与 GPU 分时调度

### 6.1 队列(数据库为准)

- 单后端进程,启动时获取 PostgreSQL advisory lock,拿不到即拒绝启动(防双 worker)。
- 进程内单 worker 循环:以 `SELECT ... WHERE status='queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED` claim 任务;状态转换一律条件更新(`UPDATE ... WHERE status='running'` 式),避免重复完成/取消竞态。
- 运行中每 10s 更新 heartbeat_at;检测 cancel_requested_at 后在安全点中断。
- 启动恢复:遗留 running → failed("server restarted");queued 保留继续消费。
- 同目标去重:gen_assets/gen_shots 同集同类型至多一条 active(部分唯一索引,冲突 409);gen_asset_image/gen_clip_video 允许排队多条(连点抽卡),客户端可带 request_id 幂等(重复 request_id 返回既有 task)。

### 6.2 任务流水线(输入一律取 payload 快照)

| 任务 | 步骤 |
|---|---|
| gen_assets | wake vLLM → script2assets 模板(剧本快照+风格+现有资产清单)→ guided_json → 仅插入新增 → 写 assets_generated_script_revision → done |
| gen_shots | wake vLLM → script2shots(剧本快照+风格+资产清单)→ guided_json(asset_ids 枚举)→ **成功后**事务内覆盖旧分镜/删片段、文件入 trash → 写 shots_generated_script_revision → done |
| gen_asset_image | input_hash ≠ 缓存 → wake vLLM 重建 prompt 并更新缓存;→ vLLM /sleep → Comfy Z-Image(prompt+随机 seed)→ 进度转发 → 临时文件→sha256→原子改名→落库为新版本(首版自动 is_current)→ 按 3.2 完成判定 |
| gen_clip_video | 复检 R5/R5a → 校验 R10 → input_hash 判定同上(minimaxh3 注入 shots+references+style+user_note)→ vLLM /sleep → 按槽位上传参考图(/upload/image)→ 提交工作流(prompt+seed+duration=requested_duration+槽位图映射)→ 进度转发 → 原子落盘、探测 actual_duration → 新 take(首个自动 is_current)→ 按 3.2 完成判定 |

### 6.3 显存分时(同卡 4090)

- vLLM 启动含 `--enable-sleep-mode`;任何 Comfy 提交前调 vLLM `POST /sleep`(level 1);Comfy 任务结束调 `POST /free`;下次 LLM 步骤前 lazy `POST /wake_up`。
- LLM 推理与 Comfy 推理永不并发(单 worker 串行保证)。
- vLLM 在 WSL 仅 HTTP;Comfy 与后端同在 Windows,路径直通。

### 6.4 失败、取消与文件纪律

- 任何步骤异常 → failed + 完整 error_msg,不重试;`finally` 中清理临时文件并调用 Comfy /free。
- 文件写入流程:临时目录生成 → 校验可读(图片可解码/视频可探测)→ sha256 → 原子 rename 至正式路径 → 落库。DB 删除与磁盘删除不做"假想事务":库删即移 trash,trash 由后台在启动时与每日清理超过 `TRASH_RETENTION_HOURS`(默认 24)的内容。

## 7. LLM 集成规范

- OpenAI 兼容 `/v1/chat/completions` + guided_json(xgrammar);模型 ID、温度进配置,模型 ID 参与 input_hash;`VLLM_TEMPERATURE` 默认 `0.2`。
- 模板变量:
  - script2assets:`{{script}} {{style}} {{existing_assets}}`
  - script2shots:`{{script}} {{style}} {{assets}}`
  - zimage:`{{asset}} {{style}} {{user_note}}`
  - minimaxh3:`{{shots}} {{references}} {{style}} {{user_note}}`
- `script2assets` 调用与注入合同:
  - 模板渲染后的完整内容作为单条 user message;若客户端必须提供 system message,只允许通用一句“你是结构化数据生成器,只输出 JSON”,不得把任何业务规则藏入代码侧 system message。
  - `{{script}}` 注入任务入队时的剧本文本快照;`{{style}}` 注入任务入队时项目风格内容快照。
  - `{{existing_assets}}` 注入按 asset id 升序的紧凑 JSON 数组,每项只含 `id`、`type`、`name`、`description`;无现有资产时注入 `[]`,不得改成自然语言。
  - response_format 的 guided_json schema:顶层 object 只含必填 `assets` 数组且 `additionalProperties=false`;每项 object 的 `existing_id` 类型为 `["integer","null"]`,`type` 为封闭 enum `["character","scene"]`,`name`/`description` 为 string,四字段全部 required,每项 `additionalProperties=false`;v1 schema 不允许 `prop`。
- `{{references}}` 结构(仅含启用槽位,按 slot_no 升序):

```jsonc
[ { "slot_no": 1, "reference_name": "subject1",
    "asset_type": "character", "asset_name": "林夏",
    "asset_description": "...", 
    "image_source": "asset_current | override" } ]
```

- 输出 schema(硬约束):

```jsonc
// script2assets
{ "assets": [ { "existing_id": "int|null", "type": "character|scene",
                "name": "string", "description": "string" } ] }
// script2shots(asset_ids.items 动态 enum=项目现存资产 id)
{ "shots": [ { "order": "int", "duration_est": "number(1-5)",
               "shot_type": "string", "camera": "string",
               "description": "string", "dialogue": "string",
               "asset_ids": [ "int(enum)" ] } ] }
// zimage / minimaxh3
{ "prompt": "string" }
```

- 模板初始内容由需求方提供并经设置页维护,仓库仅放占位示例。

## 8. ComfyUI 集成规范

- 工作流为 API 格式 JSON,由需求方提供;绑定表声明注入路径:

```toml
[comfy.zimage]
workflow = "workflows/zimage.json"
prompt_path = "6.inputs.text"
seed_path   = "3.inputs.seed"
output_node = "9"

[comfy.minimaxh3]
workflow = "workflows/minimax_h3_ref2v.json"
prompt_path     = "12.inputs.text"
seed_path       = "7.inputs.seed"
duration_path   = "7.inputs.duration"     # 秒,整数,直接传 requested_duration(Q6)
ref_image_paths = ["21.inputs.image", "22.inputs.image", "..."]  # 按槽位号顺序
optional_refs   = true                     # 声明多余参考位可留空;若工作流不支持,由需求方提供支持可变参考数的版本(§12)
output_node = "30"
```

- **启动校验(诊断)**:应用启动时加载各工作流,校验所有绑定路径与输出节点存在、参考位数量与配置一致,计算 workflow hash(参与 input_hash),探测 vLLM/Comfy 健康;结果经 `GET /system/health` 暴露并在设置页展示。绑定错误在启动阶段暴露,不留到生成中途。
- 交互:`POST /prompt` 提交;WS 监听 progress/executing 换算 0-1 推 /ws/tasks;`GET /history/{prompt_id}` 取输出;参考图先 `POST /upload/image`。

## 9. 前端规范(React 18 + Vite + TS)

- 页面与 v1.0 一致,增补:
  - 剧本页:资产/分镜"基于旧剧本"角标;生成分镜前的影响确认弹窗(展示 impact 返回的删除数量,确认后携 token 提交)。
  - 分镜页:对绑定 0 或 ≥2 个场景资产的分镜显示提示角标(0 个仅提示,≥2 个为需修正的警示)。
  - 导演台 = 一带两轨一板:**场景带**(按场景着色分段,勾选时跨段分镜置灰不可选,绑定 0/≥2 场景的镜头显示为灰段/警示段);**分镜轨**(块宽∝duration_est,显示镜号/景别/时长,changed 角标;唯一的选择交互轨);**片段轨**(片段色条横跨其分镜正下方,颜色编码 generation_state,stale 为独立叠加角标;未覆盖区为虚线空洞,不阻断;预留音频轨位置给 v2);**详情面板**(槽位、take 画廊与选用、意见、请求时长、生成按钮;操作全部在面板,轨道只负责查看与选择)。创建片段 = 预检面板(连续性/同场景/时长校验结果、估算与请求时长、候选参考资产按出场顺序勾选,>9 强制精简、>4 黄色提示)→ 提交;槽位面板对已删资产显示快照名+"原资产已删除"并引导处置。前端置灰仅为体验,最终裁决在后端。
  - 设置页:新增诊断面板(/system/health)。
  - `DEBUG_PROMPTS=true` 时,资产图/视频 take 详情展示 built_prompt 与输入快照。
- 纪律:前端不做业务最终裁决,一律以 API 为准;错误 toast 直显 detail.message。

## 10. 非功能与配置

- 技术栈:FastAPI + SQLAlchemy 2 + Alembic + asyncpg;httpx;React 18 + Vite + TS。
- 配置:`DATABASE_URL, DATA_DIR, VLLM_BASE_URL, VLLM_MODEL, VLLM_TEMPERATURE=0.2, COMFY_BASE_URL, SCRIPT_CHAR_LIMIT=2000, CLIP_MAX_SECONDS=15, CLIP_MIN_SECONDS=5, SLOT_HARD_LIMIT=9, SLOT_SOFT_LIMIT=4, UPLOAD_MAX_MB=20, TRASH_RETENTION_HOURS=24, DEBUG_PROMPTS=false` + §8 绑定表。
- 文件布局:`{DATA_DIR}/projects/{pid}/assets/{aid}/{image_id}.png`;`{DATA_DIR}/projects/{pid}/episodes/{eid}/clips/{cid}/{video_id}.mp4`;`{DATA_DIR}/trash/...`。
- 日志:任务级结构化日志,含渲染后完整中间提示词与 input_hash。
- 单进程 + advisory lock;无鉴权无 HTTPS;CORS 放开 localhost。

## 11. 里程碑(纵向切片,前后端一体,每步可运行可验收)

通用原则:每里程碑同交付 API 与 UI,从真实用户操作验收;级联规则在其下游实体所在里程碑落地,M6 全表回归;视觉一致性 M5 收口。

1. **M0 基础设施**:后端骨架、配置、Alembic 全量建表(§4 定稿模型)、/docs;前端工程、路由布局壳、API/WS 客户端、组件约定、任务中心空实现;`/system/health` 骨架。验收:前后端互通,空页可导航。
2. **M1 项目/设置/剧集/手动资产闭环**:项目、风格、模板、剧集 CRUD 与页面;资产手动路径(CRUD/上传/画廊/is_current 切换);`/media` 服务与上传约束;文件原子写入与 trash 机制;已有实体级联(删资产删文件入 trash、is_current 禁删)。验收:手工完成 建项目→建集→录资产→传图→切版本;删除后文件在 trash。
3. **M2 剧本与结构化生成闭环**:任务表+DB claim 队列+advisory lock+heartbeat+WS;vLLM 客户端+guided_json;gen_assets(R2)/gen_shots(R1/R3 全流程:impact+token+成功后覆盖+trash);剧本页(角标/双按钮/影响确认)+分镜页(编辑/绑定/changed);revision 与快照机制落地;同目标去重。**内部强制顺序:队列+WS → gen_assets → gen_shots**。验收:剧本→按钮→数据入库呈现;改剧本出角标;重生成需确认且 LLM 失败时旧数据无损;双击不产生重复任务。
4. **M3 资产出图闭环**:Comfy 客户端+绑定表+启动校验+分时调度(sleep/free);gen_asset_image(input_hash 缓存/换 seed/意见/版本画廊);诊断面板。验收:点生成出图入廊;连点两次得不同 seed 两版本;改描述后再生成可见 prompt 重建(hash 变更,日志可证);vLLM 与 Comfy 不并发;改坏绑定表启动即报。前置:§12 第 3 条须在本里程碑开工前完成。
5. **M4 导演台与视频闭环**:preview→选择参考资产→创建的全流程(R5/R5a-R8)+槽位管理(R9/R12)+gen_clip_video(入队前复检、references 注入、duration 传参、take 画廊、actual_duration);两维状态与竞态判定(3.2);级联"编辑分镜/资产→stale";导演台一带两轨一板 UI。验收:勾 3 个连续同场景分镜→预检→建片段→槽位按出场顺序正确编排→出视频→take 可切换选用;跨场景勾选被拒;含双场景绑定的分镜无法组入任何片段;建片段后修改绑定破坏同场景→生成任务失败并报因;>9 强制精简;生成中编辑分镜,完成后片段仍 stale;删除被引用资产后槽位显示快照并要求处置。
6. **M5 全局 UI/UX 收尾**:导航视觉一致、响应式、任务中心完善(取消/历史/过滤)、异常与空态、changed/stale 全局一致呈现。不新增业务能力。
7. **M6 E2E 与发布验收**:一集剧本→资产→出图→分镜→两个片段视频全链路无后台手工干预;级联矩阵(3.3)全表回归;重启恢复(6.1)、trash 清理、竞态场景(3.2)逐项验证。

## 12. 前置依赖(开发前到位)

1. Z-Image、MiniMax H3 ref2v 两个 API 格式工作流 JSON + 节点绑定信息(§8),MiniMax 工作流须含可注入的 duration 输入(秒),并明确参考图输入数量与留空行为(不支持留空则提供可变参考数版本)。
2. 4 个提示词模板初始内容(可后补,先用占位示例)。
3. vLLM 以 `--enable-sleep-mode` 启动并验证 sleep/wake 可用。
4. Postgres DSN、Comfy 与 vLLM 地址端口。

## 13. 开放问题(不阻塞 v1)

1. duration_est 与 actual_duration 的偏差校准 —— v2 观察后定。
2. 风格/模板是否版本化 —— v1.1 评估(v1 语义已定为即时生效不追溯)。
3. 候选分镜版本机制 —— v1.1。
4. 单 shot 局部重生成与 context loop 形态 —— v2。
5. 音频路线 —— v2。
