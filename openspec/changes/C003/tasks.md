# C003 M1 手动资产与媒体文件 Tasks

以下 task 按依赖顺序执行。一次只执行一个被明确指定的 task；未完成该 task 的全部验收、完整 pytest 与证据记录前不得勾选。C003 不创建或修改任何数据库 migration。

## T1 图片依赖、公开 schema 与存储路径基础

- [x] 在后端依赖中加入 FastAPI multipart 解析与成熟图片解码库；建立 Asset/AssetImage 的公开输入输出 schema，以及受 `DATA_DIR` 约束的格式→扩展名、MIME、正式/临时/trash 路径和 sha256 基础函数。
  - **R：** 无；对应 PRD §4 assets/asset_images、§5 上传约束与媒体、§6.4 文件流程、§10 `DATA_DIR`/`UPLOAD_MAX_MB`/文件布局；采用用户裁决 1B、3A。
  - **范围：** 本 task 不注册路由、不写数据库用例、不创建文件上传端点、不启动清理协程；不得暴露 `file_path` 或生成缓存字段，不增加 migration、自研 multipart/图片解析器、内容寻址存储或锁文件。
  - **验收方式：**
    1. 在 `backend/` 运行 `python -m pip install -e ".[dev]"` 与 `python -m pip check`，确认 multipart 和图片解码依赖可导入且无依赖冲突。
    2. 运行一次性人工检查命令导入新增 schema/路径函数，核对 PNG→`.png`/`image/png`、JPEG→`.jpg`/`image/jpeg`、WebP→`.webp`/`image/webp`，所有解析后路径均位于指定临时 `DATA_DIR`，用户文件名不参与结果；该命令不写 pytest 文件。
    3. 在 `backend/` 运行 `python -m pytest -q tests`；在仓库根运行 `git diff --check`，并确认 `git diff -- backend/alembic` 为空。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T2 手动资产创建、列表、读取与编辑 API

- [x] 实现 Asset create/list/item/PATCH schema、service 与 route：创建固定 `source=manual, revision=1`，只接受 character/scene，类型不可 PATCH，名称/描述实际变化时原子 revision+1，同值不增。
  - **R：** 无；对应 PRD §2.1(5)、§3.2 资产修订、§4 assets、§5 资产 API、§11 M1；采用用户裁决 3A。
  - **范围：** 只实现 `GET/POST /api/projects/{id}/assets`、`GET/PATCH /api/assets/{id}`；DELETE、图片、媒体、trash、前端和下游 changed/stale 均留给后续 task。不得读写 prompt cache/hash 或 prop。
  - **验收方式：**
    1. 在专用 PostgreSQL 通过 `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/projects/$projectId/assets -ContentType 'application/json' -Body (@{type='character';name='角色甲';description='描述'} | ConvertTo-Json)` 创建资产，再运行列表、单项与 PATCH 命令，核对字段、id 排序、source、revision 与 updated_at。
    2. 人工请求 `type='prop'`、未知 type、空白 name/description、空 PATCH、PATCH type/source/revision、未知项目/资产；核对 422/404 与统一错误体。对同值 PATCH 和两次实际变化分别核对 revision 不变与逐次 +1。
    3. 运行 `python -m pytest -q tests` 与 `git diff --check`；确认没有新增自动测试、DELETE/图片/media/UI 或 migration。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T3 原子图片上传、图片列表与首图 current

- [x] 实现 `GET/POST /api/assets/{id}/images`：multipart `file` 流式写临时文件，执行大小/MIME/完整解码校验，保留原始字节、计算 sha256、取得 image id 后原子改名并落库；首图自动 current 且资产 revision+1，后续图非 current。
  - **R：** 无；对应 PRD §2.1(5,12)、§3.2 资产当前版本修订、§4 asset_images、§5 上传、§6.4、§10、§11 M1；采用用户裁决 1B、2A。
  - **范围：** 本 task 不实现 current PUT、图片/资产 DELETE、媒体 GET、trash 定时清理或前端；失败不重试，临时文件必须清理，rename 后数据库失败产生的无引用正式文件须在同一请求内移入 trash；不创建补偿队列或 generation_runs。
  - **验收方式：**
    1. 在隔离 `DATA_DIR` 准备各一张有效 PNG/JPEG/WebP，分别运行 `curl.exe -f -F "file=@$pngPath;type=image/png" http://127.0.0.1:8000/api/assets/$assetId/images`（另两种替换文件与 MIME）；用 `Get-FileHash -Algorithm SHA256` 对比响应 sha256，并核对正式扩展名与原字节一致、用户文件名未入路径。
    2. 核对首图 `is_current=true` 且资产 revision 从 1 到 2，第二/三图为 false 且 revision 保持 2；并发提交两个首图的隔离场景中只有一个 current、两请求成功时 revision 只增加一次。
    3. 用超限文件、声明/实际 MIME 不匹配、损坏图片、缺少 file 与未知 asset 执行 HTTP 命令，核对 422/404、没有 AssetImage 行、没有正式文件、临时文件已清理且无自动重试。
    4. 运行 `python -m pytest -q tests` 与 `git diff --check`；确认没有新增自动测试或 migration。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T4 AssetImage ID 媒体服务

- [x] 实现 `GET /media/asset-images/{id}`，只按数据库 ID 解析受控相对路径并流式返回原始字节与正确图片 Content-Type；JSON API 不暴露 `file_path`。
  - **R：** 无；对应 PRD §2.1(12)、§5 媒体、§6.4、§10、§11 M1。
  - **范围：** 只交付资产图片媒体读取；不实现 clip video/slot override 媒体、不接受用户路径、不返回占位图、不做缓存/CDN/ETag 或 fallback。
  - **验收方式：**
    1. 对 T3 三种图片分别运行 `Invoke-WebRequest -Uri http://127.0.0.1:8000/media/asset-images/$imageId -OutFile $downloadPath`，核对状态 200、Content-Type、下载字节 sha256 与上传响应一致。
    2. 请求未知 ID，核对 404 统一错误体；在隔离验收数据中使数据库行指向缺失文件，核对 500、日志 traceback 且无空响应/占位图，随后清理隔离数据。
    3. 审查 OpenAPI 与 JSON 响应没有 file_path 或任意路径入参；运行 `python -m pytest -q tests` 与 `git diff --check`。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T5 当前版本切换、直接图片删除与编辑/换图追溯测试

- [x] 实现 current-image PUT 与 AssetImage DELETE：资产级串行化地先清后设，切换到新 current 时资产 revision+1、同值不增且文件不删；current 直接删除 409，非 current 删除后文件入 trash。新增且仅新增一条覆盖“编辑资产或换当前图”C003 部分语义的 API 集成用例并回填追溯行。
  - **R：** 无；对应 PRD §3.2 资产修订、§3.3“编辑资产 / 换当前图”、§4 current 约束、§5 current-image/asset-images、§6.4、§11 M1。
  - **范围：** 自动测试只覆盖名称/描述与 current 切换造成的 revision、同值不增和文件不删；current 删除 409、非 current 删除/trash 用 HTTP 命令人工验收，不把无独立追溯行的删除约束写入新测试。不得实现 Shot changed、Clip stale、生成或重试。
  - **验收方式：**
    1. 运行 `Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/assets/$assetId/current-image -ContentType 'application/json' -Body (@{image_id=$imageId} | ConvertTo-Json)`，核对目标归属校验、唯一 current、实际切换 revision+1、同值 PUT 不增、所有版本文件与 sha256 不变；未知/跨资产 image_id 为 422。
    2. 对 current 执行 DELETE，核对 409 且行/文件不动；切换后删除旧非 current，核对 204、行消失、文件在 trash。此项仅为人工 HTTP/文件检查。
    3. 运行新增授权 node ID，再运行 `python -m pytest -q tests`；将真实 node ID 回填 `openspec/TRACEABILITY.md` 的准确行并注明 changed/stale 待 C006/C008-C009。
    4. 运行 `git diff --check`，确认只新增该追溯行授权的测试，不修改、删除、跳过或弱化既有测试。
  - **计划测试层级：** API 集成
  - **追溯行：** §3.3 编辑资产或换当前图：绑定分镜 changed、相关片段 stale、文件不删

## T6 删除资产、媒体入 trash 与删除资产追溯测试

- [x] 实现 `DELETE /api/assets/{id}`：允许删除含 current 的整个资产，将其全部图片移入 trash并删除数据库行；保留 C001 FK 的解绑/SET NULL 效果。新增且仅新增一条覆盖“删除资产”C003 文件侧语义的 API 集成用例并回填追溯行。
  - **R：** 无；对应 PRD §3.3“删除资产”、§4 外键与媒体约束、§5 资产 DELETE、§6.4、§11 M1；完整 R12 不属于本 task。
  - **范围：** 自动测试只覆盖资产/图片行删除和全部图片入 trash，不预置或断言尚未交付的 Shot/Clip 状态；已有 FK 效果仅用隔离数据库人工检查。不得实现 Shot changed、Clip stale、槽位 UI/停用/override、R10 阻断或自动重排。
  - **验收方式：**
    1. 为一个资产上传 current 与非 current 多种格式后执行 `Invoke-WebRequest -Method Delete -Uri http://127.0.0.1:8000/api/assets/$assetId`，核对 204、资产/图片 GET 为 404、所有正式文件均位于对应 trash 路径；删除无图片资产同样 204。
    2. 使用不写入 pytest 的一次性隔离数据库命令预置最小 `shot_assets`/`clip_ref_slots` 关系，核对删除产生 C001 FK 已定义的解绑/asset_id NULL；不把尚未交付的 changed/stale 行为固化为 C003 自动测试，检查后清理验收数据。
    3. 运行新增授权 node ID与完整 `python -m pytest -q tests`；回填准确追溯行并注明 changed/stale/完整 R12 待 C006/C008-C009。
    4. 运行 `git diff --check`，确认只新增该追溯行授权的测试，无后续业务或 migration。
  - **计划测试层级：** API 集成
  - **追溯行：** §3.3 删除资产：解绑并 changed、相关片段 stale、槽位按 R12 处置、资产图片入 trash

## T7 扩展项目删除的资产媒体生命周期

- [x] 扩展 C002 的项目 DELETE：在当前可达范围内删除项目资产/图片并将图片移入 trash，再完成剧集与项目删除；保留风格，外部注入的后续实体仍按 C002 返回 409 并回滚数据库变更。
  - **R：** 无；对应 PRD §2.1(1,5,12)、§5 项目/资产、§6.4、§11 M1“已有实体级联”。
  - **范围：** 只扩展项目→资产图片/资产的 C003 可达级联；不删除 shots、clips、tasks、clip media 或后续实体，不新增自动测试或 migration。
  - **验收方式：**
    1. 通过现有 API 创建项目、两集、两个资产和多张图片，执行 `Invoke-WebRequest -Method Delete -Uri http://127.0.0.1:8000/api/projects/$projectId`，核对 204、项目/剧集/资产/图片行消失、全部资产文件入 trash、引用 style 保留。
    2. 在专用验收状态注入会被后续外键阻止的数据，核对 409 统一错误体、数据库无部分删除且错误未伪装为 422/500；随后人工清理隔离数据。
    3. 运行 `python -m pytest -q tests` 与 `git diff --check`；确认没有新增测试、后续级联或迁移。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T8 启动与每日 trash 清理生命周期

- [x] 在 FastAPI lifespan 中加入启动清理和每 24 小时清理协程，按 `TRASH_RETENTION_HOURS` 与文件 mtime 删除过期 trash、清理空目录，并在关闭时取消且等待协程；清理异常显式记录，不重试、不吞错。
  - **R：** 无；对应 PRD §6.4 trash 生命周期、§10 `TRASH_RETENTION_HOURS`、§11 M1/M6。
  - **范围：** 只清理 `DATA_DIR/trash`；不扫描正式目录、不清理数据库、不建立任务表记录、重试、锁文件、registry 或审计机制。M6 自动回归仍属 C012。
  - **验收方式：**
    1. 使用已解析并核对的专用临时绝对目录作为 `DATA_DIR`，人工建立一个 mtime 早于阈值和一个未过期的 trash 文件；启动应用后核对旧文件/空目录被删、新文件保留。
    2. 在隔离进程中把周期缩短仅可通过直接调用清理入口的人工命令验证同一规则，不得增加测试专用生产配置；制造权限/不可读错误时核对 traceback、非伪成功且没有重试。
    3. 正常关闭服务，核对没有遗留清理协程；运行 `python -m pytest -q tests` 与 `git diff --check`，确认未新增自动测试。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T9 前端资产类型与 API 客户端

- [x] 增加 Asset/AssetImage 类型和 create/list/get/patch/delete、图片 list/upload/current/delete 的客户端，以及 ID 媒体 URL 构造；复用统一 ApiError 与 204 处理。
  - **R：** 无；对应 PRD §2.1(5,12)、§5 资产/媒体、§9、§11 M1。
  - **范围：** 只做类型化传输层；不实现页面、前端业务裁决、上传重试/进度任务、生成、WS、prop 或任意路径媒体客户端。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`；人工审查 JSON 与 multipart 请求路径、字段和方法精确符合 spec，multipart 不手写错误的 Content-Type boundary。
    2. 核对 DELETE 204 不解析 JSON，错误保留 status/code/message，所有 mutation 无 retry；媒体 URL 只接受数值 image ID 并生成 `/media/asset-images/{id}`。
    3. 在 `backend/` 运行 `python -m pytest -q tests`；在根目录运行 `git diff --check`，确认没有页面业务或自动测试。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T10 集工作区资产 CRUD、上传与画廊 UI

- [ ] 将资产选项卡空态升级为项目级资产页，交付 loading/error/empty/ready、角色/场景创建、名称/描述编辑、上传、当前图/版本画廊、切换、删非当前版本和删资产交互，并保持层级返回按钮。
  - **R：** 无；对应 PRD §2.1(5,12)、§5、§9、§11 M1；采用用户裁决 1B、2A、3A。
  - **范围：** 资产页只消费 C003 API；不显示 prop、生成图片/意见/seed 抽卡、旧剧本角标、分镜 changed、片段 stale、槽位、任务或诊断，不新增前端自动测试。
  - **验收方式：**
    1. 在 `frontend/` 运行 `npm run build`；在 `backend/` 运行 `python -m pytest -q tests`。
    2. 浏览器从项目详情进入某集资产页，完成“空态→建角色/场景→编辑名称描述→上传 PNG/JPEG/WebP→确认首图 current→切换版本→删除非 current→删除资产”，刷新与跨同项目另一集进入后数据一致。
    3. 人工核对 current 版本没有可执行删除动作、类型不可编辑、无 prop；制造 404/409/422/500 与后端不可达，确认输入保留、`detail.message` 可见、错误不伪装空态、无自动重试。
    4. 直接打开不匹配 project/episode 的资产 URL，确认禁止 mutation；运行 `git diff --check`，确认其他选项卡无新增业务。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** 不适用

## T11 C003 全链路、追溯与范围收口

- [ ] 完成 C003 全链路验收，核对迁移零变化、原子写入、媒体、trash、错误协议、前端与范围围栏，并只保留 T5/T6 授权测试和对应追溯回填。
  - **R：** 无；对应 PRD §0、§2.1(5,12)、§3.2、§3.3 资产相关行、§4、§5、§6.4、§9-§12；R12 完整行为明确留待 C008-C009。
  - **范围：** 本 task 不新增自动测试或业务能力，只运行 T5/T6 用例、完整回归和人工验收；不得借收口实现后续 change。
  - **验收方式：**
    1. 在 C003 专用 PostgreSQL 环境运行 `python -m alembic current`、`python -m alembic check`、T5/T6 两个真实 node ID 与 `python -m pytest -q tests`；确认 head 仍为 C002 revision且无 schema 漂移。
    2. 在 `frontend/` 运行 `npm run build`；使用隔离 `DATA_DIR` 完成 spec §10 的真实浏览器和 HTTP/文件全链路，记录三种格式 hash、Content-Type、revision、current 唯一性、409/422、trash 路径与启动清理证据。
    3. 审查 `openspec/TRACEABILITY.md` 只新增两条真实 node ID：编辑/换当前图行注明 changed/stale 待后续；删除资产行注明 changed/stale/完整 R12 待后续。不得回填 R12 或其他未实现行。
    4. 运行 `git diff --check` 与范围扫描；确认无 migration、prop UI/API、任务/WS、vLLM/Comfy、生成、分镜/片段业务、重试/fallback、versioning、generation_runs、continuity、context loop、fl2v 或音频。
  - **计划测试层级：** 不新增自动测试
  - **追溯行：** §3.3 编辑资产或换当前图：绑定分镜 changed、相关片段 stale、文件不删；§3.3 删除资产：解绑并 changed、相关片段 stale、槽位按 R12 处置、资产图片入 trash
  - **覆盖说明：** 本 task 只运行 T5/T6 已授权用例，不增加新用例；两行的下游部分继续保留待后续 change 回填。
