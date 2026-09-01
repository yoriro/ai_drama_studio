# C008 M4 clip 预检创建与槽位 Spec

## 目标与边界

### 目标

C008 交付 ROADMAP 中 M4 的第一段后端纵向切片：为既有分镜提供 clip 预检、正式创建、读取、编辑和删除 API，落实 R5/R5a/R6/R7/R8 的服务端最终裁决；创建后持久化固定 `clip_shots` 与 `clip_ref_slots`，提供槽位启停、override 上传/清除、R9 取图结果和 R12 已删资产处置 API。C008 的结果必须能被 C009 的视频任务和 C010 的导演台直接消费，但本 change 不提前实现它们。

### 范围内

1. `POST /api/episodes/{episode_id}/clips/preview`：只读计算 R5/R5a/R6、候选参考资产、确定性排序、默认选择、violations 与 warnings。
2. `GET/POST /api/episodes/{episode_id}/clips`、`GET/PATCH/DELETE /api/clips/{clip_id}`：正式创建时重新裁决全部规则，原子写入 Clip/ClipShot/ClipRefSlot，并提供稳定读取、片段输入编辑和删除。
3. R7/R8：参考资产只能从候选并集中选择 1..`SLOT_HARD_LIMIT` 个；候选超过硬上限时通过选择子集解决，不要求删分镜绑定；启用槽位超过 `SLOT_SOFT_LIMIT` 只返回软提示。
4. `GET /api/clips/{clip_id}/slots` 与 `PATCH /api/clips/{clip_id}/slots/{slot_no}`：固定槽位读取、启停、override 上传/清除和 R9 取图解析。
5. `GET /media/slot-overrides/{slot_id}`：只按槽位 ID 查库并流式返回当前 override，不接受用户路径。
6. R12：删除资产后直接引用该资产的槽位 `asset_id` 置 null，名称/类型快照、槽位号、enabled 与 override 保留，相关片段 stale；不自动停用、压缩或重排。
7. PRD §3.3 的片段删除：释放其分镜关系，删除片段/槽位/既有视频行，并把 override/视频文件移入 trash；数据库失败时按 D-010 同步恢复本次文件移动。
8. 精确的 404/409/422/500 错误语义、PostgreSQL 并发裁决、文件与数据库补偿，以及 C008 所需自动测试和追溯回填。

### 范围外

- C009 的 `gen_clip_video` API/handler、MiniMax H3 workflow/binding、R4 视频 prompt 缓存、R5/R5a 生成前复检、R10、GPU 分时、视频上传/落盘、`actual_duration`、take 画廊/current-video 与完成反竞态。
- C010 的导演台“一带两轨一板”、预检选择面板、槽位面板、take 面板和浏览器交互；C008 不修改前端业务代码，现有导演台空态保留。
- C011 全局 UI/UX、C012 发布级 E2E，以及 ROADMAP 后续 change 的任何占位 endpoint、handler、绑定或页面。
- PRD §0 围栏中的候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格/模板版本化、独立 `generation_runs`、continuity、context loop、fl2v 读写和音频。`clips.generation_mode` 只写既有默认 `ref2v`，不读写预留值。
- 自动重试、preview token、客户端裁决、后台文件补偿、槽位历史/版本、自动增删槽位、自动替换参考资产或兼容旧 API。

### 现状/影响

- 当前 `HEAD a35344d` 已提交 C008 T0-T13；其祖先 `bffb69b` 已归档 C007。后端已有 PostgreSQL、显式 service 事务、统一结构化错误、资产/分镜/片段/槽位 API、trash 与媒体 ID 路由；浏览器继续只使用 D-002 的 `/api`、`/media`、`/ws` 同源相对地址。
- C001 已建 `clips`、`clip_shots`、`clip_ref_slots`、`clip_videos` 及所需唯一/外键约束；`CLIP_MIN_SECONDS`、`CLIP_MAX_SECONDS`、`SLOT_SOFT_LIMIT`、`SLOT_HARD_LIMIT` 已在配置中。已提交 C008 实现已补 `SLOT_HARD_LIMIT <= 9` 的启动校验，默认值仍为 9；复审只缺合法非默认组合的直接证据。C008 继续保持 **零 migration、零表/列/索引/枚举变化**。
- 已提交实现包含 clips/slots Pydantic schema、service 与 router，但没有前端客户端；`/director` 仍显示未交付空态。复审确认主体纵向切片与全量测试可运行，同时以生产 API、真实 PostgreSQL 和真实文件通路复现了四项待修缺口：C008 path id 超 PostgreSQL INTEGER 范围进入数据库后为 500、`user_note` 含 U+0000 为 500、Pillow 解压炸弹为 500、同格式 override 替换留下的合法同名 trash 阻止后续 Clip DELETE。
- 已提交资产删除路径同时收集分镜绑定和直接槽位引用的 Clip，使其 stale，再依赖 `clip_ref_slots.asset_id ON DELETE SET NULL` 完成 R12；已有 API 用例覆盖“资产已从 Shot 解绑但槽位仍引用”的直接槽位分支。
- 当前 episode/project/R3 清理代码已经认识 clip video 与 slot override 相对路径；C008 新增的正式路径必须继续使用同一 `DATA_DIR`、trash 和路径边界，不建立第二套文件系统抽象。

### 风险

| 风险 | C008 约束 |
|---|---|
| preview 后数据变化导致创建使用旧结论 | preview 不发 token、不预留资源；POST create 在同一事务内重新锁定并裁决当前 Shot/ShotAsset/Asset/ClipShot 真相 |
| 两个请求同时占用同一分镜 | 按固定顺序锁定所选 Shot，数据库 `UNIQUE(clip_shots.shot_id)` 兜底；只能一个完整创建成功，败者为 422，无孤儿 Clip/Slot |
| 客户端顺序改变槽位 | `shot_ids` 与 `reference_asset_ids` 的请求顺序都不定义业务顺序；后端按不可编辑的 `Shot.order_index` 和 R7 排序键规范化 |
| 候选超过 9 被误实现为永久死锁 | preview 默认预选前 9 并提示必须精简；正式创建只校验最终选择为候选子集且 1..9，候选总数本身不拒绝合法子集 |
| override 文件和数据库分裂 | 临时文件校验后原子落位；替换/清除先记录本次移动，数据库失败同步恢复旧文件并清理新文件；补偿失败与主错误一起暴露 |
| 同一 override 正式路径反复进入 trash | trash 仍使用 `trash/<正式相对路径>` 单一规范位置；合法同名 trash 已存在时，后一次实际替换/清除/删除以当前被移动文件原子替换该位置，不创建历史/版本后缀，也不得把该正常生命周期判成 500 |
| 敌意整数/字符串穿透到 PostgreSQL | 所有 C008 path id 在查询前限制到 PostgreSQL signed INTEGER；create/PATCH 的 `user_note` 在 schema 边界拒绝 U+0000，均以 422 结束且不进入数据库操作 |
| 图片头声明超大解码尺寸 | png/jpg/webp 除完整解码与 MIME 一致外，Pillow 解压炸弹异常也属于上传内容校验失败；返回 422并清理 temp，不写正式文件或数据库 |
| 资产删除丢失槽位语义 | R12 只把 `asset_id` 置 null并使相关 Clip stale；快照、编号、enabled、override 均保留，不自动选择替代资产 |
| C008 提前固化视频语义 | 只解析 R9 当前图片来源，不创建任务/payload/prompt/video；R10 与生成时复检明确留给 C009 |

## 外部依赖

| 来源 | C008 开工或验收门槛 | 当前证据 | 缺失项与结论 |
|---|---|---|---|
| PRD §12.1：Z-Image、MiniMax H3 ref2v API workflow 与绑定 | C008 不调用 Comfy、不加载 MiniMax binding；Z-Image 是已归档 C007 能力。MiniMax 文件只在 C009 开工前成为门槛 | 当前仓库只有 C007 已验收的 `comfy.zimage` binding；C007 spec 已明确禁止预建 MiniMax | **非 C008 门槛**；不得为消除“缺失”而伪造 MiniMax 文件、节点或路径 |
| PRD §12.2：4 个提示词模板 | C008 不渲染模板、不调用 LLM；`minimaxh3` 正式内容可后补 | 数据模型/migration 已有固定 key，当前 C008 路径不读取其正文 | **非 C008 门槛**；不得在 C008 写正式或占位视频模板 |
| PRD §12.3：vLLM sleep/wake | C008 无 GPU/LLM/Comfy 步骤，不以 sleep/wake 作为开工或验收条件 | C007 归档证据曾验证真实 sleep/wake；本规划未重新发起外部请求 | **非 C008 门槛**；历史证据不冒充本 change 的外部验收 |
| PRD §12.4：PostgreSQL DSN、Comfy/vLLM 地址端口 | PostgreSQL 是 C008 实现和验收门槛；所有数据库、唯一约束、锁与事务测试必须使用显式 `DATABASE_URL` 指向全新隔离 PostgreSQL。Comfy/vLLM 地址不是 C008 门槛 | `NOTES.md` 记录本机 PostgreSQL `127.0.0.1:5432`、隔离库/Alembic 操作和 advisory-lock/历史数据坑；C007 已在当前 HEAD 归档 | **实现时需刷新**：开工 task 必须新建隔离库并 `alembic upgrade head`，不能复用有 worker 锁或历史数据的库；无需用户提供新的外部文件或地址 |
| ROADMAP 前序 C007 | C007 必须归档；当前代码中的 clip schema/config/级联现状必须核对 | 当前 HEAD 为 `a35344d`；祖先提交 `bffb69b Archive completed C007 change` 可见，且 `openspec/archive/C007/spec.md` 存在 | **满足** |

C008 当前没有未满足的外部阻塞。PostgreSQL 可达性属于执行时必须现场证明的门槛；若实施时不可达，应停止该 task 并报告，不得改用 SQLite、mock 数据库或旧日志。

## 1. 可观察行为

1. preview 接受一次分镜选择，返回当前数据库真相下的规范化分镜顺序、时长、候选参考资产、默认选择、硬违规和软提示；无任何数据库/文件副作用。
2. preview 的硬违规仍返回 HTTP 200 并列入 `violations`，让 C010 可展示全部裁决；请求 JSON 本身无效、episode/shot 归属无效则返回 404/422。
3. 正式创建不信任 preview 结果，在一个明确事务中重新计算规则。存在任一 violation、引用不属于候选的 asset、选择数不在 1..9 或 requested duration 不合法时返回 422，且不写 Clip/关系/槽位。
4. 创建成功返回一个 `generation_mode=ref2v`、`generation_state=empty`、`freshness=fresh`、`revision=1` 的 Clip；`clip_shots.position` 与固定槽位均按服务端规范顺序从 1 连续编号。
5. 片段列表按首个分镜的 `order_index`、再按 clip id 稳定排序；时间轴位置只从 `clip_shots` 推导，不持久化或接受 clip order。
6. PATCH `user_note` 或 `requested_duration` 的实际变化使 Clip `revision += 1`、`freshness=stale`，不改变 generation_state、分镜状态、槽位或文件；no-op 不增加 revision。
7. 槽位号、资产名称/类型快照和相对顺序创建后固定。启停或 override 的实际变化只修改目标槽位，并使所属 Clip revision+1/stale；其他槽位不移动。
8. 槽位图片解析固定为 override > 仍存在资产的 current AssetImage > 无可用图；C008 只公开解析结果，不执行 R10 失败或视频生成。
9. 删除被槽位引用的资产后，该槽位继续以原号返回，`asset_id=null`、`asset_deleted=true`，快照可展示；有 override 时仍解析为 override，无 override 时解析为缺图。
10. 删除片段后其分镜可被新的 clip 使用；该 clip 的关系、槽位、视频行消失，关联 override/video 文件进入 trash。任何文件/数据库失败均不返回 204 伪成功。
11. C008 不改变现有分镜 PATCH 的“0 场景/多场景可保存”语义；R5a 只在 preview/create 裁决是否可组片。
12. 所有 C008 episode/clip/slot 媒体 path id 必须在 PostgreSQL signed INTEGER 范围内；超范围输入固定为 422/`validation_error` 且不执行数据库查询，范围内但不存在仍为 404/`not_found`。
13. `user_note` 可为 null、空字符串或普通 string并保持原值，但包含 U+0000 的 create/PATCH 输入固定为 422且不写数据库；不得把 PostgreSQL 编码错误暴露为 500。

## 2. 数据与状态合同

### 2.1 复用模型与零迁移

C008 只复用既有模型：

- `Clip`：创建时 `episode_id`、`user_note`、`requested_duration`；`generation_mode=ref2v`、`generation_state=empty`、`freshness=fresh`、`revision=1`；`prompt_cache/prompt_input_hash=null`。
- `ClipShot`：每个所选 Shot 一行；`position=1..N`，顺序精确等于 `Shot.order_index ASC, Shot.id ASC`；不创建 shot_ids 数组或 clip order_index。
- `ClipRefSlot`：每个最终参考资产一行；`slot_no=1..M`、`asset_id`、创建时 name/type 快照、`enabled=true`、override 字段 null。
- `ClipVideo`：C008 不创建；删除 clip 时必须正确清理已经存在的行与文件，以保持前序兼容和后续可组合性。

服务层必须在写入前执行本 spec 的完整校验；既有数据库唯一/外键约束是并发兜底，不替代 R5/R5a/R6/R7/R8 的结构化 422。

`SLOT_HARD_LIMIT` 的合法配置范围为 `1..9`，`SLOT_SOFT_LIMIT <= SLOT_HARD_LIMIT` 继续沿用现有校验。正式创建使用当前配置 hard limit；数据库中已存在的槽位仍按绝对 `slot_no 1..9` 可读取和处置，运行时调低 hard limit不得使旧槽位路由变成 422。

### 2.2 状态转换

| 触发 | generation_state | freshness | revision | Shot.status |
|---|---|---|---|---|
| 创建 Clip | `empty` | `fresh` | `1` | 不变 |
| PATCH 相同 user_note/duration | 不变 | 不变 | 不变 | 不变 |
| PATCH 实际改变 user_note/duration | 不变 | `stale` | `+1` | 不变 |
| 槽位 enabled/override no-op | 不变 | 不变 | 不变 | 不变 |
| 槽位 enabled/override 实际变化 | 不变 | `stale` | `+1` | 不变 |
| 删除引用资产（R12） | 不变 | `stale` | 不变 | 沿用 C006：原绑定 Shot 各自 changed/revision+1 |
| 删除 Clip | 行删除 | 行删除 | 行删除 | 不变，仅释放 ClipShot |

`freshness` 是派生态；只把 fresh 改为 stale，不因重复触发增加 Clip revision。R12 的 `asset_id SET NULL` 是外部资产删除的引用处置，不属于 PRD 列出的用户编辑 Clip 输入，故不增加 Clip revision。

## 3. 预检与规则裁决

### 3.1 请求规范化

`shot_ids` 必须是非空、无重复的 strict positive integer array；bool、浮点、字符串、null、空数组或重复值均为 422。所有 body id 必须先落在 PostgreSQL signed INTEGER 范围内并属于 path episode；超范围、不存在或跨 episode均为请求内容校验失败 422。所有 C008 path episode/clip/slot id 同样必须在数据库查询前限制到该范围；超范围为 422，范围内未知资源才为 404。

请求数组顺序不承载业务语义。服务端固定按 `Shot.order_index ASC, Shot.id ASC` 得到规范化选择；这只读取 C006 已冻结的只读顺序，不实现分镜排序能力。

### 3.2 R5/R5a/R6

- R5 连续：规范化后的相邻 `order_index` 必须精确相差 1；任一 Shot 已存在 `ClipShot` 即违反独占。
- R5a 单 Shot：每个所选 Shot 当前绑定的 distinct `scene` 资产数不得大于 1；大于 1 产生 `shot_has_multiple_scenes`。
- R5a 整体：全部所选 Shot 的 distinct scene 并集不得大于 1；大于 1 产生 `multiple_scenes`。零场景和全体只绑人物均合法。
- R6 总时长：`duration_est_total` 是规范化选择的 `duration_est` 数值和，不舍入；大于 `CLIP_MAX_SECONDS` 产生 `duration_exceeds_max`。小于 `CLIP_MIN_SECONDS` 只产生 `duration_below_min` warning。
- 建议请求时长固定为 `min(MAX, max(MIN, ceil(duration_est_total)))`。
- 存储中出现非有限、非正或超出现有 Shot 合同的 duration 属内部数据不一致，返回结构化 500；不得忽略或替换默认值。

### 3.3 R7/R8 候选与排序

候选集合是所选 Shot 当前绑定的全部 distinct `character/scene` 资产并集。排序键固定为：

```text
(asset.type == "scene" ? 1 : 0, 首次出现的规范化 Shot.position, asset.id)
```

因此所有人物在前、所有场景垫底；同类资产按所选分镜中的首次出场先后，同一分镜首次出现的并列资产按 id 升序。每个候选响应保存首次出现的 shot id/order_index；不使用资产创建时间、客户端数组顺序或名称排序。

- 无候选产生 `no_reference_candidates` violation，因为正式创建要求至少一个参考资产。
- 默认选择是候选排序的前 `min(candidate_count, SLOT_HARD_LIMIT)` 个。
- 候选数大于 `SLOT_HARD_LIMIT` 不作为永久 violation；返回 `reference_selection_required` warning，正式创建必须提交精简后的候选子集。
- 默认选择或当前启用槽位数大于 `SLOT_SOFT_LIMIT` 返回 `enabled_slots_exceed_recommendation` warning，message 直接说明“建议 4 张以内”（实际数字取配置）；它不阻止 preview/create/PATCH。

### 3.4 preview 响应

`POST /api/episodes/{episode_id}/clips/preview`

请求 body 字段精确只含 `shot_ids`。成功固定 HTTP 200，响应字段精确为：

```json
{
  "episode_id": 12,
  "shot_ids": [41, 42, 43],
  "duration_est_total": 7.2,
  "suggested_requested_duration": 8,
  "reference_candidates": [
    {
      "asset_id": 21,
      "asset_type": "character",
      "asset_name": "林晚",
      "first_shot_id": 41,
      "first_order_index": 1,
      "selected_by_default": true
    }
  ],
  "default_reference_asset_ids": [21],
  "violations": [],
  "warnings": []
}
```

`violations` 与 `warnings` 每项字段精确为 `{"code":"<closed code>","message":"<non-empty display text>"}`。顺序固定为 R5 连续、R5 占用、R5a 单镜（按 shot 顺序）、R5a 整体、R6 最大时长、R7 无候选；warnings 固定为 R6 最小时长、R8 候选精简、R8 软上限。preview 即使有 violation 也尽量返回可计算的时长与候选，且不写数据库、不锁定未来创建权。

## 4. Clip API 合同

### 4.1 正式创建

`POST /api/episodes/{episode_id}/clips`

body 必须是 JSON object，允许字段精确为：

```json
{
  "shot_ids": [41, 42, 43],
  "reference_asset_ids": [21, 31],
  "requested_duration": 8,
  "user_note": "节奏紧凑"
}
```

- `shot_ids` 按 §3.1；`reference_asset_ids` 必须为无重复 strict positive integer array，长度 `1..SLOT_HARD_LIMIT`。
- `reference_asset_ids` 必须是本次重新计算候选的子集；请求顺序被忽略，最终按 §3.3 排序并编号。
- `requested_duration` 省略时取本次重新计算的建议值；出现时必须是 strict integer 且位于 `[CLIP_MIN_SECONDS, CLIP_MAX_SECONDS]`。显式 null、bool、浮点或字符串为 422。
- `user_note` 省略或 null 保存为 null；不含 U+0000 的 string 按原值保存，不 trim，空字符串合法；包含 U+0000 为 422。未知字段为 422。
- 创建事务按 id 稳定锁定 episode、所选 Shot、相关 Asset 与现有 ClipShot 后重新计算 §3 全部结果；preview 不是授权 token。
- 任一 violation 使创建返回 422，`detail.message` 按 preview violation 顺序列出可展示原因；reference/duration 单独校验失败同为 422。
- 成功 HTTP 201，Clip、全部 ClipShot、全部 Slot 及响应同一事务提交；失败无部分行。

### 4.2 Clip 公开表示与读取

Clip response 字段精确为：

```json
{
  "id": 51,
  "episode_id": 12,
  "generation_mode": "ref2v",
  "user_note": "节奏紧凑",
  "requested_duration": 8,
  "generation_state": "empty",
  "freshness": "fresh",
  "revision": 1,
  "shot_ids": [41, 42, 43],
  "start_order_index": 1,
  "end_order_index": 3,
  "enabled_slot_count": 2,
  "warnings": [],
  "created_at": "UTC ISO 8601",
  "updated_at": "UTC ISO 8601"
}
```

不公开 prompt cache/hash、内部路径或后续视频字段。warnings 只含当前可判定的 `duration_below_min` 与 `enabled_slots_exceed_recommendation`。

- `GET /api/episodes/{episode_id}/clips`：未知 episode 404；空集 `[]`；按 `start_order_index ASC, id ASC`。
- `GET /api/clips/{clip_id}`：未知 clip 404。
- 任一可达 Clip 必须至少有一个 ClipShot；缺关系、position 不连续或 shot 跨 episode 属内部不一致，返回 500，不伪造起止位置。

### 4.3 PATCH

`PATCH /api/clips/{clip_id}` 只接受至少一个 `user_note`/`requested_duration`：

- `user_note` 为不含 U+0000 的 string 或 null；null 明确清空，U+0000 为 422。
- `requested_duration` 为 strict integer且在配置闭区间内，不接受 null。
- 未知字段、空 object 或错误类型为 422；未知 clip 404。
- 并发 PATCH 锁定 Clip，在当前已提交值上串行裁决；一个请求中多个字段发生变化也只 `revision += 1` 一次。
- no-op 返回当前 ClipResponse；实际变化按 §2.2，HTTP 200。

### 4.4 DELETE

`DELETE /api/clips/{clip_id}`：未知 clip 404；成功 204 且空 body。

删除事务锁定 Clip、ClipShot、Slot、Video，先解析并记录所有非空 override/video 相对路径；路径越界、文件缺失或扩展不合法为 500 且数据库不变。文件移动与数据库删除遵循 D-010：任一失败同步恢复本次已移动文件；恢复失败与原错误同时记录并返回 500。同一正式相对路径因既往合法替换已存在同名 trash 不是数据不一致；删除时当前正式文件必须原子替换该规范 trash 位置，并继续完成事务，不创建带时间戳/hash/版本后缀的历史文件。成功后关系/槽位/视频/clip 均不存在，原 Shot 内容、revision/status 不变并可再次组片。

## 5. 槽位、override 与 R9/R12

### 5.1 槽位读取与 R9

`GET /api/clips/{clip_id}/slots` 返回：

```json
{
  "clip_id": 51,
  "items": [
    {
      "id": 81,
      "clip_id": 51,
      "slot_no": 1,
      "asset_id": 21,
      "asset_name_snapshot": "林晚",
      "asset_type_snapshot": "character",
      "asset_deleted": false,
      "enabled": true,
      "image_source": "asset_current",
      "image_url": "/media/asset-images/31"
    }
  ],
  "warnings": []
}
```

- items 固定按 `slot_no ASC`；字段不返回 `override_image_path`、`override_sha256` 或资产文件路径。
- `asset_deleted` 精确等于 `asset_id is null`。
- R9：override 非空时 `image_source="override"`、URL 为 `/media/slot-overrides/{slot_id}`；否则仍存在资产且有 current image 时为 `asset_current` 与 `/media/asset-images/{image_id}`；否则两字段均为 null。
- `enabled=false` 不改变上述可观察解析，只表示 C009 不应把该槽位放入启用 references；C008 不执行 R10。
- warnings 只含启用数超过 soft limit 的提示。未知 clip 404；数据引用不一致为 500。

### 5.2 enabled mutation

同一 `PATCH /api/clips/{clip_id}/slots/{slot_no}` 的 JSON 模式只接受精确 `{"enabled": true|false}`。path slot_no 必须在数据库绝对范围 `1..9`；clip 或该 slot 不存在为 404，未知/空/错误字段为 422。

成功 HTTP 200，响应精确 `{"slot": <§5.1 item>, "warnings": [...]}`。值相同为 no-op；实际变化只改该槽位并按 §2.2 更新 Clip。

### 5.3 override multipart mutation

同一路由的 `multipart/form-data` 模式只允许以下二选一：

1. 上传：恰有一个非空 `file` part；
2. 清除：无 file，且 `clear_override=true`。

不得在 multipart 同时改 enabled；同时上传与清除、空 multipart、`clear_override=false`、未知 part 或多个 file 均为 422。

上传沿用 PRD 通用约束：大小不超过 `UPLOAD_MAX_MB`，声明 MIME 只允许 png/jpg/webp，真实完整解码格式必须与 MIME 一致；损坏、截断或触发 Pillow 解压炸弹限制均为内容校验失败 422。用户文件名不进入路径。临时文件位于 `DATA_DIR/tmp/slot-overrides`，正式相对路径固定为：

```text
projects/{project_id}/episodes/{episode_id}/clips/{clip_id}/slots/{slot_id}.{png|jpg|webp}
```

保存原始 bytes 的 sha256。与现有 override bytes/格式完全相同的上传和清除不存在的 override 均为 no-op；其他上传/替换/清除使 Clip revision+1/stale。旧正式文件进入对应 trash 相对路径；同名规范 trash 已存在时由本次旧正式文件原子替换，后续清除或 Clip DELETE 不得因此失败。新正式文件、DB path/hash、Clip 状态必须作为一个有同步补偿的业务单元。不得转码、生成占位图、保留旧 override 版本表或后台重试。

成功响应与 enabled mutation 相同。已删资产槽位允许上传/清除 override。

### 5.4 override 媒体

`GET /media/slot-overrides/{slot_id}`：slot 不存在或当前没有 override 为 404；存在时按数据库相对路径解析、校验在 `DATA_DIR` 内并以 png/jpg/webp MIME 返回。DB 指向越界、错误扩展或缺失/不可读文件为结构化 500。响应不接受 query 路径、下载文件名或绝对路径。

### 5.5 R12 资产删除

删除 Asset 的同一事务必须同时覆盖两类依赖：

1. 沿用 C006：当前 ShotAsset 绑定的 Shot changed/revision+1，包含这些 Shot 的 Clip stale；
2. 新增 C008：任何 `ClipRefSlot.asset_id` 直接引用该资产的 Clip stale，即使该资产已从对应 Shot 解绑。

随后删除图片/绑定/Asset，让数据库 FK 把槽位 asset_id 置 null。一个 Clip 被两条路径或多个槽位命中只处理一次；Clip revision/generation_state、slot_no、名称/类型快照、enabled、override 和其他槽位均不变。不自动删除槽位、移动 override、选择替代资产或触发生成。

## 6. 并发与事务

1. 两个正式创建请求若选择集合有交集，锁定顺序固定；提交后最多一个 Clip 拥有任一 Shot。一个请求完整 201，其他请求重新裁决或命中唯一约束后为结构化 422；不得把 R5 业务违规改成 409。
2. 创建与 Shot PATCH 竞争时只能有两种可观察结果：PATCH 先提交则创建基于新绑定重新裁决；创建先提交则 PATCH 成功并把新 Clip stale。不得创建使用一半旧/一半新绑定的槽位。
3. 创建与 Asset DELETE 竞争时：创建先提交则删除按 R12 把新槽位置 null/片段 stale；删除先提交则创建的 reference 候选复检失败并 422。不得留下指向不存在资产的非 null FK 或缺快照槽位。
4. Clip/Slot mutation 使用 D-003 的请求会话和 service 显式事务；API 依赖不隐式提交。
5. 所有列表、锁和批量 mutation 使用稳定 id/position 顺序，避免同类 C008 请求因锁顺序随机产生可避免死锁；数据库仍是最后事实源。

## 7. UI 交接约束

C008 不交付 UI。为 C010 固定以下后端交接：

- preview 的 `violations[].message`、`warnings[].message` 可直接展示；C010 可做置灰/提示，但不得把客户端判断当最终裁决。
- `reference_candidates` 与 `default_reference_asset_ids` 已是确定性顺序；C010 不按名称、创建时间或点击顺序重排。
- 所有图片 URL 为 D-002 同源相对 `/media`；前端不得读取内部路径。
- `asset_deleted=true` 时 C010 显示 PRD 固定文案“原资产已删除”，并提供停用或 override 操作；不得自动压缩槽位。
- 软上限只依据 API warning 展示黄色提示，不能阻止提交；API 422 的 `detail.message` 直显。
- C008 完成后 `/director` 仍可保持既有空态；不得为了人工验收提前实现 C010 页面或假数据。
- C008 只交付 C009 序列化所需的数据库事实，不生成 `{{references}}`、不读取模板、不计算视频 input_hash。PRD §7 已补压实编号和 description 示例；本轮后续交接同时固定：启用槽位按 slot_no 排序后第 k 项为 `subject{k}`；活资产在入队同一事务读取 name/type/description 当前值，有 override 也不改用快照；已删且有 override 时使用 name/type 快照与 null description，已删且无 override 时先由 R10 拒绝；含 slot_no、编号后 reference_name、name/type/description、image_source、实际 image id 或 override hash 的完整序列化产物参与 input_hash。以上规则不得反向修改 C008 槽位表、创建排序或快照落库。

## 8. 错误码矩阵

所有非 2xx 体固定为 `{"detail":{"code":"<non-empty>","message":"<non-empty>"}}`。

| HTTP / code | C008 触发条件 | 不得替代为 |
|---|---|---|
| 404 / `not_found` | path episode/clip/slot 不存在；slot override 媒体不存在或当前无 override | 403、409、422 |
| 409 / `conflict` | C008 当前没有新增的正常业务 409；只保留项目既有、真正的前置/资源冲突语义 | 把 R5/R5a/R6/R7/R8 输入违规或并发独占失败写成 409 |
| 422 / `validation_error` | JSON/multipart/path 类型与形状、C008 path/body id 超 PostgreSQL INTEGER 范围、`user_note` 含 U+0000、空/重复/跨集 shot、R5/R5a/R6 violation、reference 非候选/数量、duration、PATCH、upload 内容校验（含 Pillow 解压炸弹），以及并发创建败者 | 409、500、200 包装正式创建错误 |
| 500 / `internal_error` | 数据库结构不一致、相对路径/文件状态不一致、数据库/文件 mutation 或同步补偿失败 | fallback、部分 2xx、409/422 |

preview 的规则 `violations` 是 HTTP 200 的预检结果，不是伪成功创建；正式 POST 对同一硬违规必须 422。C008 不创建异步 task，因此没有“先 202 后 task failed”的错误通道。

## 9. 验收装置与证明范围

C008 不新增生产 demo、验收 endpoint、长期脚本或第二存储通路，也不依赖项目自建的独立验收驱动。

- 纯函数测试直接调用生产规则函数，只证明排序、规则、时长与 warning 的确定性，不证明数据库锁。
- API 集成测试通过生产 FastAPI router/service、真实 PostgreSQL、隔离 `DATA_DIR` 和真实文件读写，证明 HTTP、约束、级联与单事务结果；只构造本地 png/jpg/webp，不 mock 数据库。
- 跨进程/资源生命周期测试使用至少两个独立 PostgreSQL 连接/会话并行调用生产 service/API，文件仍走生产相对路径、原子 rename、trash 和补偿函数。它能证明本机 PostgreSQL 锁/唯一约束与文件/DB 胜方，不能证明 C009 的 worker、GPU、Comfy 或视频质量。

因此没有需要在 tasks 中单列交付的自建验收装置。若实现者新增临时 probe，只能作为 `.work/c008` 一次性证据且不得代替计划 pytest；新增前须先在 tasks 中获得明确授权。

## 10. 验收标准

每条均写明触发、观测点和真假期望；风险标签为审查定向验证类别。

| ID | 风险 | 触发条件 | 观测点 | 期望值 |
|---|---|---|---|---|
| AC-01 | [常规] | 检查 C008 diff、Alembic current/check、router/handler/workflow 和围栏关键字 | git diff、migration head、OpenAPI、task handlers、前端 diff | 零 migration/schema 漂移；只新增 C008 clip/slot/media 后端能力；无 gen_clip_video/MiniMax/C010 UI/围栏能力/retry/fallback；`gen_clip_video` 仍未注册 |
| AC-02 | [常规] | 在当前 HEAD 与全新隔离 PostgreSQL 开始 C008 | git log、archive、`alembic upgrade/current/check` | C007 archive 提交可见；隔离库升级到唯一 head且 check 无新迁移；不要求 vLLM/Comfy/MiniMax 文件即可运行 C008 API |
| AC-03 | [外部输入] | preview 分别提交连续、跳号、已占用、零场景、两个分镜各绑一个不同单场景、含单镜双场景和无候选选择 | HTTP、violations、数据库行数 | 合法/违规 preview 均 200且零写入；连续零/一场景无 R5a violation；两个不同单场景精确只出现整体 `multiple_scenes`，单镜双场景同时出现对应 closed code；未知/跨集/重复/空 shot_ids 为 422，未知 episode 404 |
| AC-04 | [外部输入] | 用总时长 `<MIN`、`=MIN`、小数和 `>MAX` 的连续选择 preview/create，并分别 PATCH `MIN`、`MAX`、边界外及错误类型 | total、suggestion、warnings、HTTP、Clip | total 不舍入；建议值精确为 clamp(ceil(total))；低于 MIN 只 warning且可创建；超过 MAX create 422；MIN/MAX 均精确保存并各只增加一次 revision，null/bool/浮点/字符串/越界均 422 |
| AC-05 | [外部输入] | 分别以合法非默认 hard/soft limit 与 `SLOT_HARD_LIMIT=10` 启动 Settings，并构造人物跨镜首次出现、同镜并列、多场景垫底及候选数 `hard limit+1` | 配置启动、candidate/default/slot 顺序、warnings | 合法非默认组合启动成功；hard limit 只允许 1..9且 soft<=hard，10 在启动校验失败；排序键精确为人物优先→首次 Shot position→asset id，场景全部垫底；默认前 hard limit；候选超限出现精简 warning，但提交任意合法候选子集 1..hard limit 可 201；最终选择超限才 422；超过 soft limit 只有 warning |
| AC-06 | [事务一致性] | 正式创建合法输入、任一 rule violation、非候选 reference，并分别在写 Clip、ClipShot 关系、ClipRefSlot 槽位时注入数据库失败 | Clip/ClipShot/Slot/HTTP | 成功只产生一个完整 Clip、连续 position/slot_no、冻结快照与默认状态；三个独立写阶段任一失败均为 500且三类表回到调用前计数，业务输入失败为 422且同样无部分行 |
| AC-07 | [并发] | 两个独立连接同时创建相同或部分重叠 shot 集合 | 两个响应、Clip/ClipShot/Slot 总数、错误体 | 精确一个请求完整 201；其他请求结构化 422；每个 Shot 最多一条 ClipShot，无孤儿 Clip/Slot、无 409 |
| AC-08 | [并发] | create 分别与 Shot PATCH、Asset DELETE 在锁屏障处竞争 | 提交顺序、候选/槽位快照、Shot/Clip/Slot 状态 | 只出现 §6 列出的两种串行化结果；无混合绑定快照、悬空非 null asset_id 或漏掉 stale/R12 |
| AC-09 | [常规] | 创建两个不相交 Clip，GET list/detail，PATCH no-op、实际 user_note 清空/修改和 duration 修改 | JSON keys/order/revision/freshness/state | list 按首 Shot order/id；公开字段精确且不泄露 cache/path；no-op 不变；每个实际 PATCH 请求 revision 只 +1、stale、generation_state/Shot/Slot/文件不变 |
| AC-10 | [常规] | 通过正式创建得到槽位后，改变活资产 name/description/current image、改变客户端数组顺序、重复读取并切换 enabled | slot_no/快照/items/warnings/Clip | 槽位顺序与 name/type 快照不变，R9 current image 可随当前图变化，其他槽位不移动；enabled no-op 不增 revision，实际切换只改目标并 revision+1/stale；启用数超过 soft limit 仍 200且 warning |
| AC-11 | [外部输入] | 对 slot 上传合法 png/jpg/webp，以及超限、MIME/内容不符、损坏、Pillow 解压炸弹、空、多 file、上传+清除和未知 part | HTTP、temp/formal/trash、DB path/hash | 三种合法格式原 bytes 落系统路径且 URL 可读；包括解压炸弹在内的所有非法输入均为 422、无正式文件/DB变化且 temp 清理；无用户文件名路径、转码或 fallback |
| AC-12 | [事务一致性] | 首次上传、同 bytes 重传、同格式不同 bytes 替换、跨格式替换、清除/no-op，并在 rename 后强制 DB 失败、再强制恢复失败 | Slot/Clip、formal/trash/temp、HTTP/log | 首次/实际替换/清除各 revision+1/stale；同 bytes/空清除 no-op；同格式反复替换/清除时规范 trash 由最新被移动文件原子替换且不报冲突；正常失败恢复旧真相且无 temp/orphan；恢复失败与主错误同时可诊断，均不返回 200 |
| AC-13 | [常规] | 同一槽位组合 override 有/无、asset current 有/无、asset 已删、enabled true/false | slots API 的 image_source/image_url/asset_deleted | override 永远优先；否则 current；否则两字段 null；enabled 不改解析；已删资产保留快照/编号并明确 asset_deleted，API 不执行 R10 |
| AC-14 | [事务一致性] | 删除同时被 Shot 和一个/多个 Slot 引用的资产，其中一个 Slot 有 override，另一个已不再由 Shot 绑定 | Asset/Shot/Clip/Slot/文件 | 资产/图片按既有删除；所有直接/间接相关 Clip stale且去重；slot asset_id null，快照/编号/enabled/override/Clip revision/state不变；override 文件不动、不自动停用/重排 |
| AC-15 | [事务一致性] | 删除含多个 Shot、override 和注入 ClipVideo 的 Clip；先执行一次同格式 override 替换制造合法同名 trash，并分别制造缺文件、数据库失败和恢复失败 | DB、formal/trash、原 Shot、HTTP/log | 合法同名 trash 不阻止删除；正常 204后 Clip/关系/Slot/Video 删除、当前正式文件位于规范 trash、Shot 原值且可重组；真正失败无 204，正常补偿恢复 DB/文件一致真相，补偿失败完整可诊断 |
| AC-16 | [外部输入] | 读取存在/不存在/无 override/坏路径的 slot media；向全部 C008 API 发送未知字段、错误 content type、PostgreSQL INTEGER 上下界外 path id，并向 create/PATCH 发送含 U+0000 的 user_note | HTTP status/body、数据库是否被调用、返回 MIME、日志 | 正常媒体按真实格式返回；缺资源 404；所有输入错误在数据库操作前为 422/`validation_error`；范围内未知资源为 404/`not_found`；内部路径/文件错误为 500/`internal_error`；每个错误体字段集合与 code 精确，不只判非空，C008 无正常 409 |
| AC-17 | [常规] | 运行 C008 定向、完整 backend、前端 build、Alembic、范围/追溯/完成报告检查 | 原始命令输出、TRACEABILITY、`.work/c008/completion-report.md`、git diff | 计划用例全通过并回填真实 node ID与准确层级；既有测试文件零修改；完整 pytest/build/current/check/diff-check 通过；`openspec/changes/c008` 只含 spec/tasks，生产实现无越界；完成报告含五节且第 5 节按“操作 → 观测值”覆盖主路径和至少一条异常分支，NOTES/DECISIONS 候选与 checkbox 可核对 |

## 11. 追溯覆盖

| 验收标准 | `openspec/TRACEABILITY.md` 准确行或替代验收 |
|---|---|
| AC-03、AC-07、AC-08 的 R5/R5a 部分 | `R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检` |
| AC-08 的来源/删除竞态部分 | `R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10` |
| AC-04 | `R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH` |
| AC-05、AC-06 | `R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示` |
| AC-09、AC-16 的 clip/API 部分 | `C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`；删除文件部分同时归属 `§3.3 删除片段：其分镜释放、片段删除、视频移入 trash` |
| AC-10、AC-11、AC-12、AC-13、AC-16 的 slot/media 部分 | `C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`；AC-10 的 soft warning 同时归属 R8，R9 解析归属 `R9 槽位取图优先级：override 图优先于资产当前图`，AC-13 的已删资产表示同时归属 R12 |
| AC-14 | `R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10`；`§3.3 删除资产：解绑并 changed、相关片段 stale、槽位按 R12 处置、资产图片入 trash` |
| AC-15 | `§3.3 删除片段：其分镜释放、片段删除、视频移入 trash`；override 补偿同时归属 C008 槽位生命周期行 |
| AC-03、AC-04、AC-05、AC-10 的复审精确触发部分 | `C008 复审精确触发条件：两个单分镜场景跨场、合法非默认 Settings、时长 MIN/MAX、建片后活资产变更与精确错误 code 均按 C008 公开合同可观测` |
| AC-06 的三阶段回滚部分 | `C008 复审创建原子性：Clip、ClipShot、ClipRefSlot 三个写入阶段分别失败时均回滚全部创建副作用` |
| AC-11 的解压炸弹部分 | `C008 复审 override 敌意图片输入：Pillow 解压炸弹等非法图片返回 422，temp 被清理且正式文件、数据库与 trash 不变` |
| AC-12、AC-15 的合法同名 trash 部分 | `C008 复审同路径 trash 生命周期：同格式 replacement/clear/delete 在合法同名 canonical trash 已存在时继续成功，canonical trash 保留本次最新移入文件，不创建历史版本路径，失败补偿仍一致` |
| AC-16 的 path id 与 U+0000 部分 | `C008 复审 API 敌意输入边界：所有 episode/clip/slot 路径 ID 在访问 PostgreSQL 前拒绝超出有符号 INTEGER 的值，create/PATCH user_note 拒绝 U+0000，且不产生数据库副作用` |
| AC-01、AC-02、AC-17 的纯范围/文档/构建部分 | 不适合新增独立自动测试：migration/越界/文档/追溯/前端无变化不是单一运行时行为。替代验收固定为 git range/diff、OpenAPI/handler 扫描、`alembic current/check`、完整 pytest、`npm run build` 与人工核对本表；其中可运行的 API/数据库行为仍由上述追溯行覆盖 |

AC-01/AC-02/AC-17 不以“追溯表无行”为由跳过；其替代命令已固定且必须在最终 task 留原始输出。其余 AC 均有运行时追溯行；tasks 动笔前已先新增上述五条 C008 复审追溯行，并校正 R5a/R7/R9/C008/R12 的实际测试层级。
