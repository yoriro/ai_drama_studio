# C009 — MiniMax H3 片段视频生成与 take 后端闭环

## 目标与边界

### 目标

C009 在 C008 已落库的 Clip、ClipShot、ClipRefSlot 与 ClipVideo 模型之上，交付可由正式 API 入队、由现有单 worker 执行、经 vLLM 与 MiniMax H3 ComfyUI 工作流生成 MP4、保存为 take 并可读取/切换/删除的后端闭环。实现必须把入队快照、R4 缓存、R5/R5a/R9/R10/R11/R12、requested/actual duration、任务取消、文件补偿、两维状态与完成反竞态接成一条可验收的生产通路。

### 范围内

1. `POST /api/clips/{clip_id}/generate-video`，包括严格输入、全局 request_id 幂等、可选 user_note 的“未提供/显式 null/空串/空白”语义、入队事务快照与立即失败任务。
2. gen_clip_video handler 注册及完整流水线：R4 prompt 缓存、MiniMax H3 封闭 JSON prompt、vLLM wake/sleep、参考图 `/upload/image`、动态 1..9 张参考图工作流、Comfy WS/history/view、取消安全点、`finally /free`、无重试。
3. C008 槽位事实到 `{{references}}` 的唯一序列化合同：只取 enabled，按 slot_no 升序，压实为 subject1..subjectN；活资产读取入队时当前 name/type/description，已删资产按 R12 快照/null 规则；R9 决定图片来源。
4. 生成结果的 MP4 临时写入、可探测性与 actual_duration、sha256、原子改名、ClipVideo 落库、首个 take 自动 current、完成反竞态和文件/数据库同步补偿。
5. `GET /api/clips/{clip_id}/videos`、`PUT /api/clips/{clip_id}/current-video`、`DELETE /api/clip-videos/{video_id}` 与 `GET /media/clip-videos/{video_id}`。
6. 多个 gen_clip_video 任务同时存在时，Clip.generation_state 的聚合规则；enqueue/claim/done/failed/canceled/restart 每次转换与聚合状态同事务提交。
7. MiniMax H3 API 工作流绑定、启动校验及 `/api/system/health` 同时暴露 zimage/minimaxh3 两个真实 workflow hash。
8. 既有表、索引与列足够，本 change 为零 migration；允许增加成熟 Python 视频容器解析依赖，不允许手写 MP4/ffprobe 解析器。

### 范围外

1. C010 的 `/director` 一带两轨一板、take 画廊 UI、槽位面板、按钮与浏览器交互；C009 完成后浏览器不会出现新的导演台能力。
2. 候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格或模板版本化、独立 generation_runs、continuity 字段或逻辑、音频、fl2v/context_loop 执行路径；`clips.generation_mode` 仍只读写 `ref2v`。
3. 自动重试、静默 fallback、兼容旧工作流/旧模板、工作流注册表、提示词版本表、媒体历史文件后缀、Comfy 参考图清理服务或新后台进程。
4. 视频审美质量、角色跨 take 一致性优化、duration_est 与 actual_duration 偏差校准；PRD §13 将偏差校准留给后续观察，本 change 只记录真实值。
5. 修改 C008 的槽位 schema、创建排序、slot_no、快照写入或资产删除级联；C009 只消费这些事实。

### 现状与影响

- 当前模型与初始迁移已经包含 Clip prompt cache/hash、五态 generation_state、freshness/revision、ClipVideo 全部字段、`gen_clip_video` Task 枚举及 current 部分唯一索引，因此不得新增或修改 migration/schema。
- 当前代码没有 generate-video API、handler、视频 take CRUD/media、Comfy image upload 或视频解析；`bindings.toml`、binding loader、startup health 与 handler map 目前都只有 zimage。
- 当前队列允许 image/video 同目标多任务，但 task 终态直接写单一结果不足以表达多个视频任务；本 change 必须按 §8 的聚合规则更新 Clip，不能用“最后一行代码写 wins”。
- C008 已固定槽位顺序、R9 解析与 R12 快照。C009 不反向改变它们，只在同一入队事务中锁定并读取生成所需当前事实。
- 提示词模板是设置数据，不做 migration seed/version。真实验收环境须通过现有 PromptTemplate API 把需求方给定内容写入 `minimaxh3` 并逐字读回。

### 风险

1. **并发与幂等**：立即 failed 的 terminal Task 不受现有 active request_id 部分唯一索引保护；必须用同一 PostgreSQL transaction-scoped request-id lock 串行化“查找既有任务 → 可能变更 user_note → 生成任务记录”，且所有生成入口使用同一锁规则，不能只锁 C009。
2. **状态竞态**：同 Clip 可有多条 queued/running/terminal 任务，cancel、restart、成功和失败都可能改变聚合值；状态投影漏掉任一转换会产生 task 与 Clip 不一致。
3. **事务/文件一致性**：Comfy 输出、临时 MP4、formal MP4、ClipVideo、prompt cache、freshness/Shot 状态与 Task done 跨越外部调用和文件系统；最终业务写必须单事务，失败必须同步补偿且保留主错误与补偿错误。
4. **敌意外部输入**：vLLM JSON、Comfy upload/history 字段、文件名/子目录、WS 事件与视频 bytes 均不可直接信任；范围、类型、路径与数量验证失败即 failed，不重试、不使用 `fullpath`。
5. **工作流可变参考数**：给定工作流不能把未用 LoadImage 留空；1..9 张输入必须删掉未使用的 LoadImage 节点和对应 H3 动态输入，不能保留 sentinel、预设图或复制第一张图填空。
6. **外部环境**：结构校验不能证明模型节点、权重、显存调度或真实 MP4 成功；真实 vLLM/Comfy/MiniMax 验收仍是完成门槛。

## 外部依赖

| 外部依赖 | 来源 | 开工门槛 | 验收门槛 | 当前证据 | 缺失项 / 状态 |
|---|---|---|---|---|---|
| MiniMax H3 ref2v API workflow 与节点绑定 | PRD §12.1、§8 | 必须是 API object；prompt、seed、duration 秒、1..9 references、输出节点路径明确；多余参考位的处理可执行 | 仓库工作流与给定文件字节一致、启动校验通过；真实 Comfy 接受 1 张与多张引用；history 的绑定 output node 产生唯一可下载 MP4 | 需求方已给出转换后的 `C:\Users\Administrator\Downloads\Minimax_H3_api_c009.json`；SHA256=`bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780`，30 个 API 节点；prompt=`138.inputs.value`、seed=`129.inputs.noise_seed`、duration=`132.inputs.value`、refs=`137,139,146,400..405.inputs.image`、H3 refs=`186.inputs.ref_images.ref_image_0..8`、output=`168`。本机 Comfy 结构校验已证明完整/裁剪图除 sentinel 图片外无其他 prompt validation error | **开工门槛已满足**。尚缺仓库 intake/binding、真实参考图上传、真实模型执行、history/MP4/actual_duration 成功证据；这些是验收阻塞项，不能用结构校验代替 |
| minimaxh3 提示词模板 | PRD §12.2、§7 | 内容可读，变量集合为 `shots/references/style/requested_duration/user_note`，输出合同为唯一非空 prompt | 通过正式 PromptTemplate PATCH/GET 逐字一致；真实 vLLM 以单条 user message 与封闭 schema 返回唯一 prompt；该 prompt 被送入同一生产 Comfy workflow | `C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md` 可读，SHA256=`e2a1638cf13e2853a263ebe7db383d2c7ce222780bc4a937ca38845c48d63f7a`；PRD §7 变量清单已同步为五项 | **开工门槛已满足**。当前数据库仍可能是占位内容；缺正式 API 写入/读回和真实 vLLM 输出证据，验收前不得宣称模板已安装 |
| vLLM sleep/wake 与 structured output | PRD §12.3、§6.2-6.3、§7 | vLLM 以 `--enable-sleep-mode` 启动，health、level-1 sleep、wake 与当前模型的 guided_json 可用 | C009 真实任务证明 wake/chat → sleep → Comfy，两个推理活跃区间不重叠；最终 vLLM/Comfy 状态可诊断 | NOTES 记录 2026-08-31 当前模型曾以 0.91、sleep mode 成功，真实 health/sleep/wake/structured chat 已通过，最终 sleeping=true | 历史证据可作为开工依据但会漂移；C009 验收必须重新探测当前进程、模型、端口和最终 sleep/free 状态 |
| PostgreSQL DSN、Comfy 与 vLLM 地址 | PRD §12.4、§6.1、§10 | 可创建独立空 PostgreSQL 数据库并升级到唯一 head；配置指向可探测的 Comfy/vLLM | 完整 pytest 使用全新数据库；真实任务使用生产配置地址，开始/结束 queue 均无遗留；advisory lock 与跨连接探针通过 | 根 `.env`/backend 配置与 NOTES 给出隔离数据库流程；历史地址为 vLLM `127.0.0.1:8001`、Comfy `127.0.0.1:8188`，不得把历史进程状态当当前事实 | 开工可进行。验收前须现场确认 DSN/端口、空 queue、唯一 worker lock；不得伪造地址可用或复用含历史数据的测试库 |

## 3. 已裁决合同与既有约定

1. 遵守 D-003：API session 由 route 注入，service 显式开启事务；外部 HTTP 不持有数据库事务。
2. 遵守 D-005/D-006：queue 负责通用 Task 生命周期，gen_clip_video handler 负责业务步骤；payload 顶层精确为 `input_snapshot/input_hash/source_revisions`，worker 只读冻结副本。
3. 遵守 D-007：request_id trim 后 1..128 字符、大小写/内部空白/Unicode code point 保留，全任务类型全局绑定一个请求身份；终态也可重放。同 id 不同 type/target/user_note“是否提供+原值”返回 409。
4. 遵守 D-008：task/Clip 状态与事件都先提交后广播；REST 是最终事实，WS 不携带未提交状态。
5. 遵守 D-009/D-010：外部调用在最终事务外；ClipVideo、cache、freshness/Shot 状态、Task done 与 Clip 聚合态在一个最终事务；formal 文件失败用同步 trash 补偿，不做假事务。
6. 遵守 D-011：模板渲染后的完整内容作为单条 user message；不在 system message 或代码中藏 MiniMax 业务 prompt。
7. 延续 D-012 的 public seed 安全合同：ClipVideo API 与 DEBUG input_snapshot 的 seed 为十进制字符串；任务 payload、工作流注入与 BIGINT 列为 `0 <= seed < 2^63` 的整数。
8. 需求方 2026-09-01 已裁决：R5/R5a/R10 复检失败走“202 + 立即 failed Task”；多任务 generation_state 按 §8 聚合；generate-video 的 user_note 按 §4.2；公开 seed 按上一条。PRD 同步不得改出其他语义。
9. 需求方 2026-09-01 对既有 health 测试给出窄授权：仅可在 `backend/tests/api/test_system.py`、`backend/tests/api/test_c007_health.py`、`backend/tests/api/test_c007_health_transport.py` 中，把原先精确 zimage-only workflow hashes 的 fixture/断言改为精确 `zimage + minimaxh3`；必须保留每个文件的其他状态、message、探测次数、无 GPU mutation、错误体与网络隔离断言，禁止改名、skip、删用例或改弱。除此之外既有测试仍不得修改。
10. 需求方 2026-09-02 已裁决两个生成前置条件：新请求面对“零个 enabled 槽位”或持久化 `generation_mode` 为 `fl2v/context_loop` 时均返回 409/`conflict`，不创建 Task；前者 message 精确为 `At least one reference slot must be enabled`，后者精确为 `Clip generation mode is not supported in v1`。零 enabled 不扩写为 R10，保留模式也不得进入 ref2v 快照或 worker。

## 4. Generate API 与入队事务

### 4.1 请求边界

`POST /api/clips/{clip_id}/generate-video` 请求体是严格 JSON object：

```json
{
  "user_note": "string | null (optional)",
  "request_id": "string | null (optional)"
}
```

- `{}` 合法；null body、数组、未知字段、错误类型为 422。
- path clip_id 必须先限制在 PostgreSQL signed INTEGER 范围；范围外 422，范围内不存在（含非正数）404。
- user_note 只接受 string/null，拒绝 U+0000，不 trim；空串和只含空白的字符串合法。
- request_id 为 null/省略表示不幂等；非 null 按 D-007 normalize，空白、超过 128 或含 U+0000 为 422。
- 新建成功或合法重放均返回 HTTP 202 与精确 `{"task_id": <positive int>}`。

### 4.2 user_note 三态

1. `user_note` **未提供**：读取 Clip 当前 user_note 作为 effective value，不改 Clip。
2. `user_note` **显式提供**（含 null、`""`、空白串）：在入队同一事务、快照之前执行与 `PATCH /clips/{id}` 相同的写入；与当前值不同则只 `revision += 1` 一次并置 freshness=stale，与当前值相同为 no-op。
3. request_id 查找和身份比较必须先于上述 mutation；合法重放直接返回原 Task，不能再次写 Clip、增加 revision 或按当前 Clip 重建 payload。
4. 请求身份保存 `{user_note_provided: bool, user_note: exact value}`；未提供与显式 null 不同，null/空串/空白互不相等。effective null 在模板文本中替换为空文本，但 DB、请求身份、快照与 input_hash 仍与空串不同。
5. 若随后 R5/R5a/R10 失败，已裁决的 user_note 实际变更与 failed Task 在同一事务一起提交；不能为了任务失败回滚用户明确提交的意见修改。

### 4.3 全局 request_id 临界区

- 非 null request_id 在事务中首先获取项目统一的 PostgreSQL transaction-scoped advisory lock，再查找任意状态的 Task；锁 key 由数据库对 normalize 后完整字符串和固定命名空间计算，碰撞最多额外串行，不能改变身份。
- 所有公开接受非 null request_id 的生成入口必须在首次查找/业务 mutation 前使用同一 helper；当前范围是既有 gen_asset_image 与新增 gen_clip_video。gen_assets/gen_shots API 没有 request_id 字段，不为本 change 修改；不新增 schema 或第二套锁。
- 同 id 并发同请求只产生一条 Task；不同请求精确一个胜方，其他为 409。无 request_id 的视频请求允许独立多任务。

### 4.4 锁定、复检与快照

在一个显式入队事务中先用只读 identity discovery 得到 enabled 槽位仍存活的 asset ids，按 id 锁这些 Asset 行，再锁目标 Clip `FOR UPDATE`，随后重读 ClipShot/Shot/ShotAsset、ClipRefSlot、current AssetImage 与 Episode 事实。Asset 锁覆盖“槽位仍引用但 Shot 已解绑”的活值变化；Clip row 则是 C006/C008 正式 Clip/Slot/Shot/Asset 级联提交屏障：mutation 先提交则入队读新值，入队先持锁则读旧已提交值且相关 mutation 随后把 Clip 标 stale。Style/Template/Project style 不按 PRD 追溯标 stale，须在 Clip 后分别锁其当前行再快照。不得 `FOR UPDATE` Shot/AssetImage/全部 Task，也不得先持 Clip 再等待 Asset，避免与既有 Asset→Clip mutation 形成反向锁序；锁前 discovery 不参与业务裁决，所有关系与存活性都必须在 Asset→Clip 屏障后重读并复检，不能读取一半旧一半新事实。

1. 非 null request_id 仍按 §4.3 先锁定并查找；合法重放直接返回原 Task，不按当前 generation_mode、enabled 数或其他当前事实重新裁决。
2. 对新请求，在锁定 Clip 并重读当前事实后、任何 user_note/Clip mutation 之前，要求 `clip.generation_mode == "ref2v"`。持久化值为 `fl2v` 或 `context_loop` 时返回 409/`conflict`，message 精确为 `Clip generation mode is not supported in v1`；不创建 Task、不写 user_note/revision/freshness、不渲染或外调。
3. 对新请求，在重读全部 ClipRefSlot 后、任何 user_note/Clip mutation 之前，要求 enabled 槽位数在 1..9。零 enabled 时返回 409/`conflict`，message 精确为 `At least one reference slot must be enabled`；不创建 Task、不写 user_note/revision/freshness、不渲染或外调。该状态不是 R10，不得伪造立即 failed Task。
4. 通过上述两个前置条件后，按 §4.2 裁决 effective user_note。
5. 复用 C008 的 closed rules 重新验证 R5 连续/独占与 R5a 至多一场景；创建后被编辑成双场景或跨场景时失败。
6. 只对 enabled 槽位执行 R9/R10。任一槽位不能解析到一份路径在 DATA_DIR 内、扩展受支持、文件可读且 bytes sha256 与数据库相符的图片，即 R10 失败；disabled 槽位不阻断。
7. R5/R5a/R10 失败时不渲染 template、不计算生成 input_hash、不生成 seed/prompt_id、不入 queued、不由 worker claim、不调用 vLLM/Comfy。queue 在当前事务记录 terminal Task：status=failed、progress=0、started_at=null、finished_at 非 null、input_hash=null、error_msg 为完整可展示原因；R10 原因至少包含 `R10`、slot_no 和“资产已删无 override / 活资产无 current / 路径、文件或 hash 不可用”之一。route 仍返回 202/task_id，提交后广播一次 failed 事件。
8. failed Task 的最小 input_snapshot 只含请求身份、Clip id/revision/effective user_note/requested_duration 与精确 precheck rule/reason；source_revisions 保存已观察到的 Clip/Shot/Asset revision。不得伪造 workflow、references 或成功 hash。
9. 其他前置条件：缺 Clip 为 404；request identity 冲突为 409；缺/非法 Style 或 minimaxh3 Template 为 409；persisted cache/path/关系不一致且不属于 R10 为 500。以上同步错误不创建 Task。

## 5. 成功入队 payload、references 与 R4

### 5.1 shots

`input_snapshot.shots` 按 `clip_shots.position ASC`，每项精确保存：`id/order/duration_est/shot_type/camera/description/dialogue/revision/asset_ids`；其中 `order=Shot.order_index`，asset_ids 数字升序。注入 `{{shots}}` 时使用同一顺序的紧凑 JSON 数组，但每项只含模板公开字段 `order/duration_est/shot_type/camera/description/dialogue`，不得注入数据库路径或隐藏业务文字。

### 5.2 references

只序列化 enabled=true 槽位，先按 slot_no ASC 得列表；第 k 项（1 起）固定：

```json
{
  "slot_no": 3,
  "reference_name": "subject2",
  "asset_type": "character",
  "asset_name": "陈默",
  "asset_description": "string | null",
  "image_source": "asset_current | override",
  "image_id": "integer | null",
  "override_sha256": "64 lowercase hex | null"
}
```

规则如下：

0. 成功序列化只允许 1..9 项；零 enabled 已在 §4.4 以同步 409 截止，serializer/worker 不得接收或排队零项 references。
1. reference_name 只由启用序列位次 k 得到，与 slot_no 解耦；slot 1、3 启用时第二项是 subject2。启停会让后续项重新编号，这是期望行为。
2. asset_id 非 null：在入队同一事务读取 Asset 当前 type/name/description；即使 image_source=override 也使用活值，不消费快照 name/type。
3. asset_id null 且有 override：type/name 取 C008 快照，asset_description=null，image_id=null。
4. asset_id null 且无 override 不可进入成功序列化，必须先命中 R10 failed Task。
5. override 优先：image_source=override、image_id=null、override_sha256 为槽位 override hash；活资产 current 次之：image_source=asset_current、image_id 为 current AssetImage id、override_sha256=null。prompt 的 `{{references}}` 只投影 PRD §7 的六个字段，image_id/override_sha256 是生成身份，不暴露给模板。
6. `input_snapshot.reference_media` 逐项保存系统相对 file_path、扩展和 expected sha256，worker 以此副本读文件，不回查当前 Slot/Asset/Image；不得保存/使用用户文件名或绝对路径。

### 5.3 input_hash 与 cache

R4 序列化使用 UTF-8、无 NaN 的确定性紧凑 JSON，成员精确为：

1. §5.1 全量 shots（含 revision 与 asset_ids）；
2. §5.2 完整 references 生成身份（含编号后 reference_name、活 name/type/description、image_source，以及二选一的 image_id/override_sha256）；
3. Style.prompt_fragment 当前内容；
4. minimaxh3 Template.content 当前内容；
5. effective user_note 原值（null/空串/空白不同）；
6. requested_duration integer；
7. `VLLM_MODEL`；
8. MiniMax workflow 原始 bytes 的 SHA256。

sha256 结果与 `clips.prompt_input_hash` 相同且 prompt_cache 为非空文本时，payload.cached_prompt 使用其快照并跳过 vLLM chat；不同则 cached_prompt=null 并重建。hash 相同但 cache 为空是 persisted inconsistency，API 500 且不创建 Task。每个成功请求仍生成新的 63-bit seed 与 Comfy prompt UUID；无 request_id 使用 `[0,2^63-1]` 安全随机 seed 与 UUID4 prompt id；非 null request_id 的确定性映射冻结为：

```python
GEN_CLIP_VIDEO_NAMESPACE = UUID("17c124be-f03e-5a69-b4e5-e3a63f62994b")
prompt_uuid = uuid5(GEN_CLIP_VIDEO_NAMESPACE, normalized_request_id)
comfy_prompt_id = str(prompt_uuid)
seed = prompt_uuid.int & 0x7FFF_FFFF_FFFF_FFFF
```

namespace 字面值的审计来源是 `uuid5(NAMESPACE_URL, "ai-drama-studio:gen_clip_video")`，运行时以该 UUID 字面常量为准，不读取配置且不得复用 C007 `gen_asset_image` namespace。`normalized_request_id` 只使用既有 `normalize_request_id()` 的结果，即原始值去首尾空白后保留大小写、内部空白与其余 Unicode；UUIDv5 name 不拼 task type、Clip id、user_note、当前时间或第二次 hash。`str(prompt_uuid)` 为 canonical lowercase hyphenated UUID，seed 取同一 UUID 的低 63 bits。固定测试向量：原始 `request_id=" abc "` 规范化为 `"abc"`，必须得到 `comfy_prompt_id="3088d9e1-4253-5fff-896e-87e5f5312d20"`、内部 `seed=679630015510424864`。

payload 顶层精确三键；成功入队的 `source_revisions` 精确为 `{"clip":{"id","revision"},"shots":[{"id","revision"},...],"assets":[{"id","revision"},...]}`，shots 按 clip position、assets 按 id 且只含仍存活并被启用 reference 使用者。Style/Template 修改按 PRD §3.3 不追溯现有任务，不纳入完成 freshness 比对，但内容已冻结且参与 hash。

## 6. 模板、vLLM 与工作流绑定

### 6.1 minimaxh3 template

- Template.key 精确为 `minimaxh3`；placeholder 名集合必须精确是 `shots/references/style/requested_duration/user_note`，每个至少出现一次，不允许未知或未闭合 `{{...}}`。
- shots/references 按 §5 注入紧凑 JSON；style 为快照文本；duration 为十进制整数；effective null user_note 注入空文本，非 null 原样注入且不 trim。
- 渲染后的完整字符串是唯一 user message；model、temperature、模板内容、guided schema 全部来自 payload 快照。
- guided_json 名为 `minimaxh3`，schema 顶层仅必填 string `prompt` 且 `additionalProperties=false`。vLLM 返回必须是仅含 prompt 的 JSON object，prompt 必须为非空非纯空白 string；任何额外键、null、错误类型、空值、非法 JSON 或 transport error 使 Task failed，Comfy submit 次数为 0，不重试。
- built_prompt 始终完整落 ClipVideo 并写 task 关联日志；默认 API 隐藏，DEBUG 规则见 §9。

### 6.2 binding 与启动诊断

生产 workflow 固定为 `backend/workflows/minimax_h3_ref2v.json`，必须与外部依赖表给定 API JSON 字节一致。当前 `backend/workflows/bindings.toml` 与 `load_binding_snapshot()` 的 zimage-only 闭合合同被既有不可修改测试锁定，C009 不把第二个 section 塞入该文件，也不按默认路径/测试路径做特判；新增唯一 `backend/workflows/minimaxh3.toml`，只含精确 `[comfy.minimaxh3]` section，并由显式 MiniMax loader 读取。该 section 包含：workflow、prompt_path、seed_path、duration_path、按 1..9 顺序的 ref_image_paths、与之逐项对应的 ref_consumer_paths、`optional_refs=false`、output_node。两文件是两个现役工作流的明确配置，不是版本、registry或旧格式兼容层。

loader 在启动时同时验证：

1. zimage 与 minimaxh3 各自文件/section 字段闭合，路径相对 backend 且不逃逸，workflow 为非空 API object；
2. prompt/seed/duration/ref image/ref consumer 的每个路径都必须是至少三段的精确 `node_id.inputs.input_key`：node_id 为十进制节点 ID，第二段逐字等于 `inputs`，后续非空段按 Comfy dotted input key 合并；不得接受 `node_id.<其他段>.input_key`、空段、数组语法或路径逃逸。prompt/seed/duration 解析后的 `(node_id, input_key)` 必须两两不同，且不得与 ref image/ref consumer 叶子重叠；
3. prompt leaf 为 string、seed leaf 为非 bool integer、duration leaf 为 finite number；9 对 ref paths 唯一且逐项存在，consumer leaf 确实引用对应 LoadImage node，output node 存在；
4. workflow 中 `LoadImage` 节点集合必须精确等于配置的 9 个 sentinel 节点，不允许未绑定或预设图片节点；不得存在参考视频加载节点或业务视频文件输入；绑定 output 必须为 `VHS_VideoCombine` 且 inputs 不含 `audio`。给定 H3 节点为满足模型签名保留的内部 `audio_vae` 连接只可作为工作流模型 plumbing，应用不得读取、生成、落库或返回音频；
5. 原始 bytes hash，不做重新序列化 hash。

任一绑定错误在 worker 启动/claim 之前拒绝应用启动。health 成功结构保持既有 schema，`workflow_bindings={status:"valid",message:null,hashes:{zimage:<64hex>,minimaxh3:<64hex>}}`，hash key 集合精确为两项；vLLM/Comfy health 语义与探测次数不变。

### 6.3 工作流注入与可变 references

1. 在 Comfy submit 前调用 vLLM level-1 sleep；cache hit 也必须 sleep。
2. 按 references 顺序逐张把 snapshot 文件以 multipart `image` 上传至 `/upload/image`；filename/subfolder 由系统用 task_id 与 reference_name 生成，不使用数据库或用户 basename。每项精确上传一次。
3. upload response 必须是 object，`name` 为 1..255 字符的单一 basename且扩展与本次上传的 png/jpg/webp snapshot 扩展相同，`subfolder` 为不含空/`.`/`..`/绝对根的安全相对 segments 且总长不超过 1024、`type="input"`；拒绝 null、错误类型、U+0000、`/`/`\` filename、扩展漂移、路径穿越与超长值。允许忽略不参与决策的额外键，但不得读取服务端 `fullpath`。
4. 深拷贝冻结 workflow，分别注入 built_prompt、整数 seed、requested_duration 秒和上传返回的 `subfolder/name`。N 张 reference 时只保留前 N 个 LoadImage 节点与 H3 consumer inputs；删除 k>N 的对应节点/consumer key。不能留空、留 sentinel、复制图片、保留 preset 或改变前 N 顺序。
5. submit 前重新按启动时同一精确路径规则解析 workflow，验证 prompt/seed/duration 三个物理叶子仍两两不同且值分别精确等于 built_prompt、seed、requested_duration；LoadImage 节点集合精确等于前 N 项，引用节点均存在且不再含 `__C009_REFERENCE_` sentinel，output inputs 仍无 audio。requested_duration 不在后端换算帧数；给定 workflow 内部公式负责 24fps 合法长度，后端只传秒。
6. 沿用生产 WS progress/executing 与 prompt_id 过滤，安全点检查 cancel。history 必须在绑定 output node `168` 的 `gifs` 中恰有一项，且 filename 是满足同上 1..255 限制的 `.mp4` basename、subfolder 满足同上安全/1024 限制、type=`output`、format=`video/h264-mp4`；0/多项、错 node、错类型、超长/穿越或缺字段均 failed。只用 filename/subfolder/type 调 `/view`，绝不使用 history `fullpath`。
7. 任一步失败记录完整 error_msg，不重试、不改 prompt、不中途降级参考图；`finally` 清理本地 temp 并调用 Comfy `/free`。若主错误与 free/cleanup 同时失败，error_msg/log 同时保留两者且 Task 仍 failed。

## 7. 视频文件、actual_duration 与最终提交

1. `/view` bytes 流入 `DATA_DIR/tmp/clip-videos/{task_id}.mp4`；临时路径由系统生成且限定在 DATA_DIR。
2. 使用项目声明的成熟 Python 媒体容器库打开完整文件，要求至少一个 video stream，container duration 存在、可转为有限且 `>0` 的秒数；该单一值写 actual_duration。无流、不可解析、duration 缺失/NaN/inf/非正均 failed；不调用 PATH 中偶然存在的 ffprobe，不从 requested_duration 猜值，不做 fallback。
3. actual_duration 与 requested_duration 不要求相等，也不因偏差失败；保留原始 float。随后计算原文件 bytes sha256。
4. 最终事务锁定 stored Task、Clip、相关 Shot/Asset 与当前 ClipVideo，确认 Task 仍 running 且无 cancel request，再插入 ClipVideo 取得 id。formal 相对路径精确为 `projects/{project_id}/episodes/{episode_id}/clips/{clip_id}/{video_id}.mp4`，temp 原子 replace 到该路径后更新 file_path。
5. Clip 无既有 current take 时新行 `is_current=true`，否则 false；不得自动替换已有 current。
6. cache miss 只在本次成功最终事务更新 Clip.prompt_cache/prompt_input_hash；cache hit 不改。失败/取消不留下新 cache/hash。
7. 逐项比对 source_revisions：全一致时 Clip.freshness=fresh、snapshot 中全部 Shot.status=normal；任一实体不存在或 revision 不同，take 仍保存，但 Clip 不得从 stale 改 fresh、Shot 不得从 changed 改 normal。该判断不覆盖其他任务的 generation_state 聚合。
8. ClipVideo、cache、freshness/Shot、Task done 与 §8 聚合 generation_state 同一数据库事务提交。Task cancel marker 与成功提交精确一个胜方；取消胜出时无 ClipVideo/cache/formal 文件，成功胜出后 cancel API 为 409。
9. 最终数据库事务失败时 formal MP4 同步移入对应 canonical trash；补偿成功则 DB/正式路径回到调用前，补偿失败与主错误都可诊断。temp 在所有路径清理。无 retry、历史后缀或 orphan formal。

## 8. generation_state 聚合与状态转换

### 8.1 聚合函数

对同一 Clip 的全部 `type=gen_clip_video` Task，在每次 Task 生命周期 mutation 后计算：

1. 存在 running → `generating`；
2. 否则存在 queued → `queued`；
3. 否则取 `status in (done, failed)` 中最新终结者，按 `finished_at DESC, id DESC`；done → `ready`，failed → `failed`；
4. 若没有非 canceled Task（从未请求或只有 canceled）→ `empty`。

canceled 不作为终态结果，也不抹掉更早 done/failed。freshness 与该聚合完全正交。

### 8.2 原子投影

- enqueue queued、立即 precheck failed、claim running、complete done、worker fail、queued/running cancel、startup recovery running→failed 都必须在改变 Task 的同一事务调用同一生产聚合函数。
- 聚合函数锁 Clip `FOR UPDATE`，在当前 mutation 后读取 Task 状态但不额外 `FOR UPDATE` 全部 Task；所有投影写者通过同一 Clip lock 串行，等待者在 READ COMMITTED 新语句中看到已提交前驱，避免与 claim 的 Task row lock 形成反向死锁。
- 只有值实际变化时更新 `Clip.generation_state/updated_at`；generation_state 是派生态，不增加 Clip.revision、不改变 freshness。
- queue 仍保持通用生命周期；通过一个明确的事务内 lifecycle callback/协调入口调用 C009 聚合，不建立 handler registry、projection table 或 generation_runs。

### 8.3 可观察转换

| 事件 | Task | Clip generation_state（无更高优先级任务时） | freshness/Shot |
|---|---|---|---|
| 成功入队 | queued | queued | 不变，除显式 user_note 实际变化先置 stale |
| R5/R5a/R10 立即失败 | failed | failed | 不因失败改变；user_note mutation 仍保留 |
| worker claim | running | generating | 不变 |
| 运行失败 | failed | 按最新终态为 failed | 不变 |
| queued cancel | canceled | 回退到其他 active/既有终态/empty | 不变 |
| running cancel 安全点 | canceled | 同上 | 不变且无 take/cache |
| 成功提交 | done | 若无其他 active，按最新终态 ready | 按 source_revisions 判 fresh/normal 或保持 stale/changed |
| startup recovery | 原 running→failed | active 优先，否则最新终态 failed | 不变 |

## 9. take API、公开字段与媒体

### 9.1 ClipVideoResponse

默认 item 精确为：

```json
{
  "id": 1,
  "clip_id": 2,
  "sha256": "64 lowercase hex",
  "seed": "9223372036854775807",
  "requested_duration": 12,
  "actual_duration": 12.04,
  "is_current": true,
  "media_url": "/media/clip-videos/1",
  "created_at": "RFC3339"
}
```

- seed 必须是十进制 string；DB、payload 与 workflow 内仍为 int。公开 actual_duration 允许既有 nullable schema 的 null，但 C009 生成的新行必须为有限正数。
- 默认不返回 file_path、built_prompt、input_hash、input_snapshot 或任何绝对路径。
- `DEBUG_PROMPTS=true` 时每项额外且只额外返回 `built_prompt` 与深拷贝 `input_snapshot`；snapshot 顶层 seed 投影为十进制 string，不修改 DB JSON。false 时两键不存在而非 null。

### 9.2 list/current/delete

1. `GET /api/clips/{clip_id}/videos`：未知 Clip 404；按 ClipVideo.id ASC 返回全部 takes，每项按 §9.1；至多一项 current。
2. `PUT /api/clips/{clip_id}/current-video`：严格 body 仅 `{"video_id": positive PostgreSQL INTEGER}`；未知 Clip/Video 404，Video 属于其他 Clip 为 422。锁 Clip 与该 Clip 全部 Video，目标已 current 为 no-op；否则原 current=false、目标=true 同事务。成功 200 返回 §9.1 item；不改 Clip revision/freshness/generation_state、Shot 或文件。
3. `DELETE /api/clip-videos/{video_id}`：未知 404；current 为 409；非 current 把精确 canonical formal MP4 移到 canonical trash 并删 row，成功 204 空 body。文件/path/hash 不一致为 500且 DB 不变；DB 失败恢复文件，恢复失败保留双错误。不改 Clip/Shot/state。

### 9.3 media

`GET /media/clip-videos/{video_id}` 先按受限 signed INTEGER id 查库，再由 Episode/Clip/Video ids 重算唯一 canonical 相对路径，要求 DB file_path 精确相等、`.mp4`、路径位于 DATA_DIR、文件存在且可读；成功 `video/mp4`。未知 Video 404；路径逃逸、错误扩展、缺失/不可读为结构化 500。接口不接受 query path、filename 或绝对路径。

## 10. 失败、取消与 409/422 语义

所有非 2xx 响应体由全局 handler 保持精确 `{"detail":{"code":"<non-empty>","message":"<可直接展示>"}}`；Task 运行错误通过 `TaskResponse.error_msg` 保留完整原因，不把异步失败包装为 HTTP 200 error。

| HTTP / code | 触发 | 不得替代为 |
|---|---|---|
| 202 | 新建 queued Task、R5/R5a/R10 立即 failed Task、合法 request_id 重放 | 对这三类复检失败同步 409/422；伪造 queued |
| 404 / `not_found` | 范围内 clip/video/task 不存在；media row 不存在 | 409/422 |
| 409 / `conflict` | request_id 已绑定不同请求；新请求的 Clip 为 `fl2v/context_loop`（精确 message `Clip generation mode is not supported in v1`）；新请求零 enabled 槽位（精确 message `At least one reference slot must be enabled`）；缺/非法 Style/Template 等生成前置条件；删除 current take；对已 done/failed Task cancel | R5/R5a/R10；body 输入校验；跨 Clip video_id；为 mode/零 enabled 两类创建 Task或写 Clip |
| 422 / `validation_error` | JSON/path/body 类型或未知字段、超 PostgreSQL INTEGER、U+0000、request_id 长度/空白、PUT current body、video 属于其他 Clip | 409；创建 failed Task；500 |
| 500 / `internal_error` | persisted 关系/cache/path/file 不一致（R10 明确覆盖者除外）、数据库/文件 mutation 或同步补偿失败 | fallback、部分 2xx、409/422 |

vLLM/Comfy/视频解析/worker source drift 均为 Task failed，不是 generate-video route 的同步 5xx；完整 error_msg 可经 GET task 观察。任何失败均不重试、不吞异常、不改用 cached/default/preset 图片或 requested_duration 伪造 actual_duration。

## 11. 验收装置与证明范围

C009 不交付生产 demo、额外验收 endpoint、长期 driver 或第二套存储/事件通路，也不依赖项目自建 demo 才能验收。

- **纯函数测试**直接调用生产 serializer/template/binding/workflow injection，只证明确定性结构、hash 成员、严格输出和 dynamic pruning，不证明数据库锁、真实上传或模型可运行。
- **API 集成测试**走生产 FastAPI router/service、真实 PostgreSQL 与隔离 DATA_DIR；外部 HTTP 用正式 client seam 的 mock，证明 HTTP、公开字段、DEBUG、错误体与 take CRUD，不证明 GPU/Comfy 模型。
- **任务系统 mock**走生产 enqueue、queue、handler、final commit，mock vLLM/Comfy transport，并以竞态屏障验证快照、cancel、重复提交、聚合态与完成判定；它证明调用顺序和副作用边界，不证明工作流节点真实安装。
- **跨进程/资源生命周期测试**使用至少两个独立 PostgreSQL 连接/应用进程、生产 advisory/claim/文件/补偿通路与本地真实 HTTP stub，证明 request-id lock、Task/Clip 同事务、restart、DB/file 生命周期及外部字段敌意输入；stub 不能证明真实模型质量。
- **真实外部验收**不新增自建 driver；使用生产 Uvicorn、隔离 PostgreSQL、现有 REST/WS、真实 vLLM、真实 Comfy、仓库工作流与设置 API 模板。该通路与生产事件、存储、进程、上传、history、view、媒体读取完全相同。它能证明一条真实 1-reference 和一条多-reference MP4 闭环、duration/seed/hash/状态/资源次序；不能客观证明画面审美或长期角色一致性。
- **真实工作流异常探针**不新增仓库脚本或代理：在隔离库、Comfy queue 初始为空且只运行本次 prompt 的前提下，用正式 generate-video API 让生产 worker 完成真实 vLLM、上传和 Comfy submit；确认该 prompt 已 running 后，从验收端直接调用真实 Comfy `/interrupt`，但不调用应用 cancel API。其余 Task/WS/history/free/temp/DB/file 均走生产通路。差异仅是异常由验收端主动中断真实 Comfy execution；它能证明“已 claim 且已外调的真实工作流异常”进入 failed、无 retry/take/cache/formal、finally free并恢复 queue/sleeping，不能证明所有模型内部错误或自然故障。若 queue 中出现其他任务，必须停止，不得中断未知任务。

真实模型输出与视觉内容不适合稳定自动测试：模型/显卡/权重具有非确定性，固定像素断言会把外部模型特征误当产品合同。替代验收必须在 `.work/c009/` 保存原始 HTTP/WS/task/DB/log/hash/duration/媒体元数据，并人工逐项确认 prompt 使用实际 Subject/Picture 编号、无 preset/音频、视频可播放；这不是“追溯表无行”跳过，见 AC-21 与对应追溯行。

若执行者选择新增可复用脚本/demo/验收 driver，必须先回写 tasks 单列“验收装置”前置 task并说明生产同路/隔离差异；当前计划只允许 `.work/c009/probe-*.py` 一次性诊断证据，不纳入提交且不能代替 pytest。

## 12. 验收标准

每条均包含触发、观测点与可判定期望；风险标签供审查定向探针使用。

| ID | 风险 | 触发条件 | 观测点 | 期望值 |
|---|---|---|---|---|
| AC-01 | [常规] | 检查 C009 diff、Alembic current/check、前端与围栏关键字 | git diff、migration head、OpenAPI、handler map、前端 diff | 零 migration/schema；只新增 C009 backend/workflow/dependency/docs；无 C010 UI、generation_runs、版本化、continuity、音频、fl2v/context_loop 执行、retry/fallback；gen_clip_video 正式注册 |
| AC-02 | [外部输入] | 分别加载正确 MiniMax binding，以及缺字段、UI graph、路径逃逸、第二段不是 inputs、错 leaf、prompt/seed/duration 物理叶子别名、重复/少于 9 ref、错 consumer/output、额外 preset LoadImage、参考视频节点、VHS audio 输入的 binding | 应用 startup、worker claim 数、health JSON、submit workflow | 正确 binding 启动，hashes key 精确 zimage/minimaxh3 且值为原始 bytes hash；任一错误在 claim 前拒绝启动；注入后 prompt/seed/duration 三叶子和值精确且互不覆盖；health 的 vLLM/Comfy status/message/探测次数不漂移 |
| AC-03 | [外部输入] | 用给定模板及缺/未知/未闭合 placeholder，向 vLLM 返回正常、额外键、null、空白、错误类型、非法 JSON | 单条 messages、guided schema、Comfy 调用、Task/error | shots/references 为紧凑有序 JSON，五变量来自快照，无隐藏 system 业务 prompt；只有精确非空 prompt 继续；其他均 failed、Comfy submit=0、无 retry/副作用 |
| AC-04 | [事务一致性] | 槽位 1/3 enabled，分别覆盖活资产+current、活资产+override、删资产+override、删资产无 override、disabled 无图，并在活资产 name/description/current image 改后入队 | payload references/media/hash、Task、SQL snapshot | 成功列表按 slot_no 且命名 subject1/subject2；活资产取当前 name/type/description，override 仍带活 description；删资产 override 用快照 name/type+null description；disabled 排除；删资产无 override 产生 202 failed R10 且不序列化/外调 |
| AC-05 | [并发] | 显式 user_note 分别省略/null/空串/空白/相同值，并让两连接并发 PATCH/slot/asset mutation 与 enqueue | Clip revision/note/freshness、payload/source revisions、worker 使用值 | 省略不写且取锁内当前值；显式值精确持久化，实际变化只 revision+1/stale、no-op 不变；快照是一个可串行化胜方而非混合事实；worker 不回读新值 |
| AC-06 | [并发] | 相同 request_id 同时从同/不同进程提交相同请求、不同 clip/user_note presence/value，并与 gen_asset_image 同 id 竞争；终态后重放；以原始 `" abc "` 验证固定映射 | advisory lock、Task rows、Clip revision、HTTP、冻结 payload | 所有接受request_id的生成入口使用同一transaction lock；同身份精确一行且均202同task_id；不同身份精确一胜方其余409；重放不再mutation/重算；无id可创建多条；固定向量得到 prompt id `3088d9e1-4253-5fff-896e-87e5f5312d20` 与 seed `679630015510424864` |
| AC-07 | [事务一致性] | 在入队时分别制造 R5 不连续/独占漂移、R5a 跨场/单镜双场、R10 各缺图原因，并带/不带实际 user_note mutation | HTTP/task/payload/Clip/queue/vLLM/Comfy | HTTP 均 202；Task 直接 failed、progress0、started null、finished/error 非空、input_hash null且理由含规则/slot；从未 queued/claimed/外调；user_note 实际变化与 failed Task 同事务；只有 canceled/failed 历史时聚合符合 §8 |
| AC-08 | [外部输入] | 对 clip/video path、request/current body 提交 signed INTEGER 上下界外、bool/float/string、未知字段、U+0000、空白/超长 request_id、错误 content type | HTTP body、SQL 计数、Task/DB副作用 | 所有边界错误在 SQL/入队前 422/validation_error 且字段集合精确；范围内未知资源 404/not_found；合法空串/空白 user_note 原样保存；无 task/文件副作用 |
| AC-09 | [常规] | 对 R4 八类成员逐项改变，分别恢复所有序列化成员、只恢复 Shot 文本但保留新 revision，并只换 seed | serialized bytes/hash、vLLM call/cache/payload | 每个成员变化 hash 变化；所有成员含 revision 精确恢复才 hash 相同；文本恢复但 revision 不同仍 hash 不同；cache hit 跳过 chat但 seed/prompt_id 新；hash不同chat一次；hash相同cache空同步500；失败不更新cache，成功才与done同事务更新 |
| AC-10 | [外部输入] | N=1、2、9 references 注入，并伪造 upload name/subfolder/type 的 null、穿越、超长、U+0000、扩展漂移、错类型/错 type | upload 次序、提交 workflow、Task/error | 每张按 subject 顺序上传一次；前 N paths 精确，k>N LoadImage/consumer 删除且无 sentinel/preset；prompt/seed/duration 秒精确；敌意 upload 返回均 failed、submit=0、不使用 fullpath/首图填空 |
| AC-11 | [外部输入] | history 返回 0/2 gifs、错 output node、错 format/type、缺字段、穿越/超长 filename/subfolder，以及唯一合法 MP4 | view 请求、temp/DB/Task、error_msg | 只有 node168 唯一安全 `video/h264-mp4`/output 项触发一次 view；其余 failed且无 temp/formal/ClipVideo/cache、无 retry；view 只传验证后的 filename/subfolder/type |
| AC-12 | [跨进程] | cache miss/hit 各跑完整 handler，并在 wake/chat/sleep/upload/submit/WS/history/view 阶段注入失败 | 两服务事件时间线、Task/error、Comfy queue、GPU mutation | miss 顺序 wake→chat→sleep→upload→submit，hit 无 wake/chat但有 sleep；vLLM 与 Comfy 活跃区间不重叠；每个失败一次 failed并 finally free/temp cleanup；主+free错误同时可见 |
| AC-13 | [跨进程] | 生成合法 MP4、无 video stream、损坏、duration 缺失/NaN/inf/<=0 与 requested/actual 明显偏差 | parser、actual_duration、sha/temp/formal/DB/Task | 只有含 video stream 且 finite positive duration 成功；actual 保存探测值而非 requested 猜值，偏差不失败；所有非法文件 failed无 take/cache/formal；不依赖 PATH ffprobe或 fallback |
| AC-14 | [事务一致性] | 成功任务分别遇到 source revisions 全等、Clip/Shot/Asset 任一变化/删除，并有既有 current take | ClipVideo/current/cache/Clip/Shot/Task | 每次成功都保存 take；仅首个 current；全等才 fresh+全部 snapshot Shot normal，任一不等保持 stale/changed；已有 current 不换；ClipVideo/cache/status/done/聚合同事务 |
| AC-15 | [并发] | 多任务按 queued/running/done/failed/canceled 的不同交错顺序转换，含后提交先立即 failed、相同 finished_at 与 startup recovery | Tasks、Clip state/updated_at/revision、WS/REST | running>queued>最新 non-canceled terminal(`finished_at,id`)>empty；cancel 忽略但不抹旧终态；每次 Task 与 Clip 状态同事务且提交后事件；派生态不增 Clip revision、不改 freshness |
| AC-16 | [并发] | running cancel 分别发生在 chat 前、上传中、Comfy后/最终提交前、最终提交后；interrupt/free 分别成功/失败 | Task/marker/interrupt、安全点、temp/formal/DB/cache/Clip | queued 直接 canceled；running 先提交 marker并 best-effort interrupt；取消胜方无 take/cache/formal且聚合回退，成功胜方原子 done/take且后续 cancel 409；interrupt失败不撤销意图；全部路径 finally free且不重试 |
| AC-17 | [事务一致性] | 在 formal rename 后注入 ClipVideo/cache/Shot/Task 任一 DB 失败，并再注入 trash 补偿失败 | formal/temp/trash/DB/Task/log | 正常补偿使 DB/formal 回到调用前、失败 Task 保留完整原因；补偿失败同时记录主错误与补偿错误，不返回 done/伪成功；不留未报告 orphan或历史后缀 |
| AC-18 | [事务一致性] | 列出多个 take，切换 current/no-op/跨 clip，删除 non-current/current，并注入文件缺失、坏路径、DB失败/恢复失败 | API JSON/order、唯一 current、Clip/Shot/state、formal/trash | list id ASC且字段精确、seed string；切换同事务唯一 current且不改 Clip/Shot；跨 clip 422；current delete 409；noncurrent 204+canonical trash；失败无部分 DB/文件真相，双错误可诊断 |
| AC-19 | [外部输入] | DEBUG false/true 读取 videos，读取正常/未知/坏 path/缺文件媒体，并构造 2^63-1 seed | JSON keys/types、DB JSON、HTTP/MIME | false 无 prompt/snapshot/path；true 只多 built_prompt/input_snapshot且两个公开 seed 都是精确十进制字符串，DB仍int；media正常video/mp4，未知404，坏存储500，错误体精确且不泄露绝对路径 |
| AC-20 | [常规] | 打开并运行三个获窄授权 health 测试、分阶段演进的 C008 contract 测试、T13 演进的 C007 handler 注册测试及所有新增测试，检查 git diff 与 TRACEABILITY | 测试断言、用例名、diff、追溯行 | health 三文件只把 hashes 精确集合演进为 zimage+minimaxh3；C008 contract 用例只按 T9/T13/T15 实际阶段向精确集合加入获授权 path/handler，既有 C008 行为/错误断言逐字保留且不改为子集/存在性；C007 注册用例只把视频 handler 不存在替换为生产 handler identity且保留资产 handler identity；除这五个获授权文件外既有测试零修改；每个新增用例归属追溯行且无恒真/只非空弱断言 |
| AC-21 | [跨进程] | 在全新库与真实生产 vLLM/Comfy 中安装给定模板，分别生成 1-reference 与至少 2-reference 视频，其中一条 duration=5；另建一条唯一在跑的真实任务，待 Comfy prompt running 后由验收端直接 `/interrupt`，不调用应用 cancel | PromptTemplate GET、health、HTTP/WS/task、started_at、外部调用日志、Comfy queue/history、MP4/hash/duration/media、temp/formal/cache、最终 GPU/queue | 模板逐字与 hash 来源一致；health 双 hash；真实 prompt 的 Picture/Subject 与上传顺序一致、无 preset/音频；两条 MP4 可播放且 requested秒注入、actual>0、take/media/state正确；中断任务已 claim且实际 submit，随后精确 failed、完整原因、无 retry/take/cache/formal/temp，finally free；结束 vLLM sleeping、Comfy free且queue空。R5/R5a/R10 立即 failed 或 mock/stub 不得替代该异常证据；视觉审美只人工记录，不宣称自动证明 |
| AC-22 | [常规] | 运行隔离库完整 pytest、Alembic、前端 build、范围/文档/commit 审计并读取完成报告第5节 | 原始命令日志、git diff、TRACEABILITY、NOTES/DECISIONS、completion report | 全部计划测试与完整套件通过；Alembic零漂移；前端 build通过且无C009 UI diff；c009目录只含spec/tasks；完成报告五节，第5节以“操作 → 观测值”覆盖真实主路径、R10 与 AC-21 真实工作流中断异常；TRACEABILITY 无待填；未验证项不宣称完成，收尾三项可核对 |
| AC-23 | [事务一致性] | 对新请求分别把全部槽位停用、把 Clip generation_mode 置为 fl2v/context_loop，并各自携带会实际改变的 user_note；另先创建带 request_id 的合法 Task，再改变当前槽位/mode 后重放同 id | HTTP/error body、Task 行数、Clip user_note/revision/freshness、payload、worker/vLLM/Comfy | 两个新请求均精确 409/conflict与裁决 message，Task 行数不变、Clip 不变且无 worker/外调；零 enabled 不标 R10；fl2v/context_loop 不进入 ref2v snapshot。合法重放仍 202 同 task_id，返回原冻结 payload且不按当前前置条件重算或 mutation |

## 13. 追溯覆盖

spec 定稿后、tasks 编写前的逐条覆盖结果如下；TRACEABILITY 中缺失的 C009 行须先新增为“待填”，实现时再回填真实 pytest node ID或真实外部证据。

| AC | TRACEABILITY 准确行名 |
|---|---|
| AC-01、AC-22 | C009 范围、零 migration 与完整回归/完成证据 |
| AC-02、AC-20 | C009 MiniMax H3 工作流绑定、双 hash health 与既有测试窄演进；C009 复审 MiniMax binding 路径别名、preset 与 audio 启动闭合 |
| AC-03、AC-09 | C009 MiniMax prompt、完整 input_hash 与 cache |
| AC-04 | C009 references 活值/删除快照/压实编号与 R9；R10 缺图即失败；R12 删除资产后的槽位 |
| AC-05、AC-06 | C009 generate-video 入队快照、user_note 与全局 request_id 并发幂等；§6.1 去重与幂等；C009 复审跨进程真实生成入口 request_id 竞争 |
| AC-07 | R5 连续与独占；R5a 同场景；R10 缺图即失败；C009 立即 failed Task 与结构化错误；C009 复审 R5/R5a/R10 立即失败完整矩阵 |
| AC-08、AC-19 | C009 API 敌意输入、公开 seed、DEBUG 与媒体错误体；R11 提示词可见性 |
| AC-10、AC-11 | C009 Comfy references 上传、动态工作流与敌意返回值 |
| AC-12、AC-16 | C009 GPU/Comfy 资源生命周期、取消与失败；§6.1 取消；C009 复审 wake/sleep/WS 失败资源生命周期 |
| AC-13、AC-17 | C009 MP4 探测、文件/数据库事务与同步补偿 |
| AC-14 | §3.3 片段生成成功且修订未变：相关分镜 normal、片段 fresh、新 take 落盘；无其他 active 视频任务时 ready，有 active 时按 C009 聚合；§3.2 完成判定反竞态：source_revisions 全一致时回写 fresh/normal；任一不一致时产物仍保存且不得覆盖 stale/changed；generation_state 始终按 C009 聚合 |
| AC-15 | C009 多任务 generation_state 聚合与重启恢复；§6.1 重启恢复 |
| AC-18 | C009 take 列表、current、删除与媒体生命周期 |
| AC-21 | C009 真实 MiniMax workflow/template 视频闭环；C009 复审真实 Comfy workflow interrupt 失败闭环 |
| AC-23 | C009 复审 generate-video 零 enabled 与保留 mode 的 409 原子前置条件 |
