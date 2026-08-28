# C003 M1 手动资产与媒体文件 Spec

## 1. 规范边界

本 spec 只授权 ROADMAP `C003`。规范来源为 PRD §2.1(5,12)、§3.2 资产修订、§3.3 资产相关行、§4 assets/asset_images、§5 资产与媒体、§6.4、§9、§10、§11 M1 与 §12；PRD §0 范围围栏始终优先。

C003 复用 C001 已有 schema，不新增或修改迁移。PRD §11 规定级联规则在下游实体所在里程碑落地，因此 C003 只落实资产自身 revision、媒体文件“不删/入 trash”及已有外键的数据库效果；绑定分镜 `changed`、相关片段 `stale` 和完整 R12 行为不得提前实现。

用户已裁决：上传保留原始编码和字节并使用真实扩展名；首张手动上传自动成为当前图；资产类型创建后不可修改。上述裁决是本 spec 的强制语义。

## 2. 可观察交付物

C003 完成后必须同时满足：

1. FastAPI 使用真实 PostgreSQL async session 提供手动资产、资产图片和 ID 媒体 API；不增加 Alembic revision。
2. 资产创建只接受 `character` 或 `scene`，保存 `source=manual`、`revision=1`；PATCH 只允许名称和描述，实际变化时 revision 原子 `+1`，类型不可修改。
3. multipart 上传只接受不超过 `UPLOAD_MAX_MB` 的可完整解码 PNG/JPEG/WebP；保存字节与上传字节一致，文件扩展名与真实格式一致，sha256 对正式存储字节计算。
4. 资产没有当前图时，首张成功上传自动 `is_current=true` 且资产 revision `+1`；后续上传默认非当前。当前切换在单一事务内先清后设，同值 PUT 不增加 revision。
5. 资产图片可按 ID 流式读取；接口不接受路径、不使用用户文件名、不暴露数据库 `file_path`。
6. 当前图片直接删除返回 409；非当前图片删除、资产删除及当前已交付项目删除涉及的资产媒体进入 trash。trash 在应用启动时和此后每 24 小时清理超过保留期的文件。
7. 集工作区资产页展示当前项目的真实资产和版本画廊，可完成创建、编辑、上传、切当前、删非当前版本和删资产；三个后续业务页不因 C003 获得新能力。
8. 所有失败使用统一错误体；409/422 语义符合本 spec，前后端均不自动重试。

## 3. 数据与公开字段

### 3.1 Asset

API 公开字段：

`id, project_id, type, name, description, source, revision, created_at, updated_at`

写入约束：

- create body 仅为 `{type,name,description}`；`type` 只能是 `character` 或 `scene`，`source` 固定由后端写为 `manual`，`revision=1`。
- `name` 去除首尾空白后必须非空并保存去除后的值；`description` 保留原始换行和首尾空白，但必须至少含一个非空白字符。
- PATCH body 只允许 `name`、`description` 中至少一个；类型、source、revision、缓存字段、id 与时间戳均不可写。
- 名称或描述的持久值实际变化时，单次 PATCH 使 `revision +1` 并更新 `updated_at`；同值 PATCH 返回现有资源，不增加 revision、不伪造更新时间。
- C003 不返回 `image_prompt_cache`、`image_prompt_hash`，不创建或修改这些生成缓存字段。

数据库中为未来保留的 `prop` 不属于 v1 API/UI 的合法值；实现不得 seed、创建、编辑或展示道具资产，也不得建立兼容映射或别名。

### 3.2 AssetImage

JSON API 公开字段：

`id, asset_id, sha256, seed, source, is_current, created_at`

- C003 上传产生的行固定 `source=uploaded`、`seed=null`。
- 不返回 `file_path`、`built_prompt`、`input_hash`、`input_snapshot`、`user_note`。
- 前端媒体 URL 由 ID 构造为 `/media/asset-images/{id}`，不是数据库字段。
- 图片列表按 `id` 升序返回；任一资产在任何已提交状态下至多一行 `is_current=true`。

## 4. REST API

除媒体路径外，业务路径均以 `/api` 为前缀。POST 创建成功返回 201，GET/PATCH/PUT 返回 200，DELETE 成功返回 204 且无响应体。

### 4.1 资产

| 方法与路径 | 行为 |
|---|---|
| `GET /api/projects/{id}/assets` | 项目存在时按 asset id 升序返回全部 v1 资产；不存在项目为 404 |
| `POST /api/projects/{id}/assets` | body `{type,name,description}`；创建手动资产并返回 Asset |
| `GET /api/assets/{id}` | 返回 Asset；不存在为 404 |
| `PATCH /api/assets/{id}` | 只修改名称/描述并遵守 §6.1 revision 语义；不存在为 404 |
| `DELETE /api/assets/{id}` | 将该资产全部图片移入 trash，删除资产及图片行，返回 204；当前图禁删规则不阻止删除整个资产 |

C003 同时扩展既有 `DELETE /api/projects/{id}` 的当前可达级联：删除项目拥有的全部资产时，其资产图片必须进入 trash，再完成 C002 已有的剧集/项目删除；风格不删除。API 外部注入的后续实体若仍阻止项目删除，保持 C002 的 409 与整体数据库回滚，不在 C003 提前删除分镜、片段、任务或其媒体。

### 4.2 资产图片

| 方法与路径 | 行为 |
|---|---|
| `GET /api/assets/{id}/images` | 资产存在时按 id 升序返回图片版本；无图片返回 `[]` |
| `POST /api/assets/{id}/images` | multipart 字段 `file`；校验并原子落盘，创建 `source=uploaded` 图片并返回 201 |
| `PUT /api/assets/{id}/current-image` | JSON body `{image_id}`；图片必须属于该资产，返回被选中的 AssetImage |
| `DELETE /api/asset-images/{id}` | 非当前版本移入 trash 并删除，返回 204；当前版本返回 409，文件和数据库均不变 |

`image_id` 不存在或不属于路径资产属于 body 业务校验失败，返回 422；路径资产不存在仍为 404。

### 4.3 ID 媒体

`GET /media/asset-images/{id}` 按 ID 查询 `asset_images.file_path` 并流式返回原始存储字节：

- PNG 返回 `image/png`，JPEG 返回 `image/jpeg`，WebP 返回 `image/webp`。
- 图片行不存在为 404；行存在但文件缺失、不可读或路径越出 `DATA_DIR` 是未预期存储错误，返回 500 并记录 traceback，不伪装为 404 或空图片。
- 不接受 query/path 中的用户文件路径，不重定向到任意本地路径，不返回占位图或 fallback。

## 5. 上传与文件生命周期

### 5.1 格式、大小与路径

- 允许声明 MIME：`image/png`、`image/jpeg`、`image/webp`；必须完整解码并确认真实格式与声明 MIME 一致。
- `UPLOAD_MAX_MB` 按 `值 × 1024 × 1024` 字节计算硬上限；流式写入一旦超过上限即失败，不继续消费为成功文件。
- 保留上传的原始字节，不解码重编码。PNG 使用 `.png`，JPEG 统一使用 `.jpg`，WebP 使用 `.webp`。
- sha256 对最终存储的原始字节计算；响应值必须与这些字节一致。
- 正式相对路径为 `projects/{project_id}/assets/{asset_id}/{image_id}.{ext}`，数据库 `file_path` 保存受系统控制的 `DATA_DIR` 内相对路径。
- 临时目录与正式目录必须位于同一个 `DATA_DIR` 文件系统，以保证最终 rename 原子；用户文件名不得进入正式、临时或 trash 路径，也不得写入业务响应。

### 5.2 上传顺序与事务

一次上传按以下顺序执行：

1. 验证路径资产存在并锁定该资产的上传/当前版本判定；未知资产为 404。
2. 将 multipart 内容流式写入 `DATA_DIR` 内系统临时文件，同时执行大小硬限制。
3. 完整解码临时文件，确认仅为 PNG/JPEG/WebP 且实际格式与 MIME 匹配。
4. 对临时文件字节计算 sha256，取得将用于正式文件名的数据库 image id，但此时不得提交半成品 `asset_images` 行。
5. 原子 rename 到正式 `{image_id}.{ext}` 路径。
6. 在数据库事务中插入 AssetImage；若资产此前没有 current，则本行自动 current 并使 Asset revision 原子 `+1`、更新 `updated_at`，否则本行为非 current。
7. 数据库提交成功后返回 201；任何步骤失败都不重试、不返回成功，未落定临时文件必须在 `finally` 删除。

并发首图上传必须按资产串行判定：两个请求均可成功时，只有先完成的首图成为 current，另一张为非 current，资产 revision 只因首次 current 建立增加一次。已有部分唯一索引继续作为数据库兜底，不得捕获冲突后自动重试。

DB 与文件系统没有共同事务，不得描述为跨系统原子；若正式 rename 后数据库失败，必须显式报告失败，并在本次请求的同步清理中将没有已提交 AssetImage 行引用的正式文件移入 trash。若该清理本身也失败，日志必须同时保留数据库失败与实际文件落点，不能吞错、伪造行或返回 2xx。实施不得引入后台重试或隐藏补偿队列。

### 5.3 trash

- trash 相对根为 `trash/`；资产图片按系统正式相对路径移动到 `trash/projects/{project_id}/assets/{asset_id}/{image_id}.{ext}`，不得使用上传文件名。
- 直接删除非当前 AssetImage、删除 Asset 和 C003 扩展后的项目删除均将相关资产图片移入 trash；删除整个资产时允许其 current 图片一并进入 trash。
- 正常删除响应只有在数据库删除与要求的 trash 移动均完成后才返回 204；任一步骤异常不得返回伪成功。实现不得声称文件系统和数据库具备不存在的共同事务。
- 应用启动时先执行一次过期清理；运行期间每 24 小时再执行一次。以 trash 文件 mtime 判定，删除早于当前时间减 `TRASH_RETENTION_HOURS` 的文件，并清理因此产生的空目录。
- 清理失败必须记录 traceback 并显式暴露失败，不重试、不静默跳过；应用关闭时取消每日清理协程并等待其结束，不遗留后台任务。
- C003 不清理正式目录中的无主文件，不建立扫描注册表、锁文件、审计表或内容寻址存储。

## 6. 状态转换

### 6.1 Asset revision

| 成功操作 | Asset revision | AssetImage/current | 文件 |
|---|---|---|---|
| 创建资产 | 初始 `1` | 无图片、无 current | 不写文件 |
| 名称/描述实际变化 | `+1` | 不动 | 不删 |
| 名称/描述同值 PATCH | 不变 | 不动 | 不动 |
| 首张成功上传 | `+1` | 新图 current | 新文件正式落盘 |
| 后续上传 | 不变 | 新图非 current | 新文件正式落盘 |
| 切换到另一版本 | `+1` | 原 current=false、目标=true，同事务 | 两文件均保留 |
| PUT 已是 current 的版本 | 不变 | 不变 | 不动 |
| 删除非当前图片 | 不变 | 删除该行，current 不变 | 该文件入 trash |

失败的校验、文件写入、数据库冲突或删除请求均不得增加 revision 或返回成功。

### 6.2 下游级联边界

- C003 的名称/描述编辑或 current 切换保证资产 revision 正确且任何现有图片文件不删除。
- C001 外键在删除资产时可能使 `shot_assets` 解绑、`clip_ref_slots.asset_id` 置 NULL；C003 不新增这些表或约束。
- C003 不把 Shot 标记 `changed`，不把 Clip 标记 `stale`，不实现已删资产槽位 UI、停用/override 或 R10 生成阻断。对应追溯行只能标注 C003 文件侧部分覆盖，后续由 C006/C008-C009 回填其余语义。

## 7. 错误协议与 409/422

所有 API 错误体精确保持：

```json
{"detail":{"code":"<machine_code>","message":"<human_message>"}}
```

- 404 / `not_found`：路径资产、项目、AssetImage 媒体 ID 不存在。
- 409 / `conflict`：直接删除 current AssetImage；数据库级当前版本、外键或并发资源冲突。409 不用于上传内容校验。
- 422 / `validation_error`：未知/多余字段、空 PATCH、空白名称/描述、`prop` 或其他非法类型、无效 multipart、文件超过上限、MIME 不在白名单、声明 MIME 与真实格式不符、图片不可完整解码、current-image body 的 image_id 不存在或不属于该资产。
- 500 / `internal_error`：数据库不可达、正式文件缺失/不可读、DATA_DIR 权限/越界、原子 rename 或 trash/清理异常及其他未预期错误；日志保留 traceback。

不得用 200 包装错误，不得把 409/422 互换，不得返回路径或内部异常细节，不得自动重试。前端直接呈现后端 `detail.message`，并保留用户尚未成功提交的输入和选择。

## 8. 前端行为

### 8.1 路由与数据归属

`/projects/:projectId/episodes/:episodeId/assets` 从 C002 空态升级为资产页。页面先读取项目与剧集并验证 `episode.project_id === project.id`；不匹配时显示明确错误并禁止任何资产 mutation。资产是项目级资源，因此该项目任一合法集工作区看到的是同一份 `/api/projects/{projectId}/assets` 数据。

剧本、分镜、导演台、设置与任务中心保持各自现有边界；C003 不新增项目级另一套资产路由。

### 8.2 页面交互

- 页面具备 loading、error、empty、ready 四种真实状态；错误不伪装为空列表，不自动重试。
- 空态提供“创建资产”入口。创建表单只含角色/场景类型、名称、描述；没有 prop、source、revision 或生成字段。
- 资产卡显示类型、名称、描述、revision、当前图片或明确“暂无当前图片”；图片 `src` 只使用 `/media/asset-images/{id}`。
- 编辑表单只允许名称和描述，类型以只读信息显示；同值保存使用 API 返回结果，不在前端自增 revision。
- 画廊展示全部图片版本及 current 标记。上传只接受 PNG/JPEG/WebP，并提示动态 `UPLOAD_MAX_MB` 由后端最终裁决；前端 MIME/accept 仅作交互提示，不能替代后端校验。
- 资产无 current 时首张上传成功后直接显示为 current；后续上传显示为非 current。非当前版本提供“设为当前”和“删除版本”；current 版本不得提供可执行的直接删除动作，并明确提示须先切换。
- 删除版本和删除资产前均需确认。删除资产文案明确其全部图片将进入 trash；成功后以 API 结果/重新读取更新页面，失败保留现有数据。
- 保存、上传、切换或删除进行中禁用对应重复提交入口；成功后不得自动发起同一 mutation，失败保留输入并直显 `detail.message`。
- 页面不得出现生成图片、抽卡、意见、旧剧本角标、分镜/片段级联状态、槽位、任务进度或诊断能力。

## 9. 测试与追溯

C003 只允许新增以下两个 API 集成测试场景：

1. `§3.3 编辑资产或换当前图：绑定分镜 changed、相关片段 stale、文件不删`
   - C003 覆盖：名称/描述实际变化与 current 切换的 revision 语义、同值不增、切换前后图片文件均保留。
   - 分镜 changed、片段 stale 待 C006/C008-C009；C003 回填必须注明部分覆盖，不得声称整行完成。
2. `§3.3 删除资产：解绑并 changed、相关片段 stale、槽位按 R12 处置、资产图片入 trash`
   - C003 覆盖：删除资产时全部资产图片进入 trash，资产与图片行删除，并保留 C001 已有 FK 效果。
   - changed/stale、槽位快照展示与完整 R12 待 C006/C008-C009；回填必须注明部分覆盖。

上传格式/大小、首图 current、直接图片删除、ID 媒体、项目删除扩展、trash 定时清理、CRUD/UI 没有独立追溯行，不得为这些场景新增自动测试；使用专用 PostgreSQL、隔离 DATA_DIR、HTTP 命令、文件 hash/路径检查和浏览器人工验收。实施后只回填上述两行的真实 pytest node ID。

## 10. 验收标准

1. 在真实 PostgreSQL C002 head 上运行 `alembic current` 仍为 `6b8e3f0a1d24 (head)`，`alembic check` 无操作；C003 没有新 migration 或 schema 漂移。
2. 资产 API 的字段、排序、201/200/204、404/409/422 与本 spec 一致；创建只允许 character/scene，type/source 不可 PATCH，实际名称/描述变化 revision 恰好 `+1`。
3. 分别上传有效 PNG/JPEG/WebP 后，正式文件扩展名与真实格式一致、字节 hash 与响应 sha256 一致、用户文件名不在路径；超限、伪 MIME、损坏图片均 422 且无正式文件/数据库行。
4. 首图自动 current 并使 revision `+1`；后续上传非 current；切换 current 原子且 revision `+1`，同值切换不增，任何时刻至多一个 current。
5. `/media/asset-images/{id}` 返回原始字节与正确 Content-Type；未知 ID 404，接口和 JSON 均不暴露 `file_path`。
6. current 直接删除为 409 且不动；非 current 删除、资产删除和项目删除涉及的资产文件进入 trash，成功响应后对应数据库行不可读。
7. 启动清理和每日清理在隔离 DATA_DIR 有真实证据：过期 trash 被删、未到期文件保留、空目录清理；异常不被吞掉，无重试。
8. 授权的两条 API 集成用例及完整 `python -m pytest -q tests` 成功；TRACEABILITY 只回填这两行并注明部分覆盖边界。
9. `npm run build` 成功；浏览器可完成创建资产、编辑、三格式上传、首图 current、切版本、媒体显示、删非 current、删资产和层级返回，刷新后数据库状态一致。
10. `git diff --check` 成功；diff 无迁移、任务/WS、vLLM/Comfy、生成动作、分镜/片段业务、R12 完整行为、道具资产或其他范围围栏能力。
