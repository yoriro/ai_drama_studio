# C003 M1 手动资产与媒体文件 Proposal

## 元数据

- Change：`C003`
- 里程碑：PRD §11 M1 的“手动资产闭环”纵向切片
- 前序 change：`C002`
- 当前状态：开发与走查完成；Luna 已完成 T12-T14，2026-08-25 Sol 增量复审通过；待用户确认后再决定 archive 或进入后续 change

## 背景与现状

C001 已按 PRD §4 建立 `assets`、`asset_images` 及相关外键、约束和当前版本部分唯一索引；配置中已有 `DATA_DIR`、`UPLOAD_MAX_MB` 与 `TRASH_RETENTION_HOURS`。C002 已交付项目、剧集和四选项卡工作区，并经最终复审通过；当前资产选项卡仍是未交付空态。

现有代码没有资产 schema、service、route、前端 API 客户端或画廊，也没有 multipart 解析、图片解码校验、ID 媒体服务、原子文件写入和 trash 清理实现。`openspec/archive/` 只有 `.gitkeep`，没有可假设存在的归档能力。C003 复用既有完整 schema，不新增或修改数据库表、列、索引和 Alembic revision。

## 目标

交付不依赖任务系统、vLLM 或 ComfyUI 的手动资产闭环：操作者可在集工作区查看当前项目的角色/场景资产，创建和编辑资产，上传 PNG/JPEG/WebP 图片，查看版本画廊、切换当前版本、按 ID 读取媒体，并删除非当前图片或整个资产；文件写入使用临时文件、可解码校验、sha256 与同文件系统原子改名，删除内容进入 trash，过期 trash 在启动时和每日清理。

## 已确认裁决

以下裁决由用户于 C003 规划前明确给出，是本 change 的规范输入：

1. 上传的 PNG/JPEG/WebP **保留原始编码与原始字节**，正式路径使用与实际格式匹配的 `{image_id}.png`、`{image_id}.jpg` 或 `{image_id}.webp`；PRD §10 的 `.png` 路径示例按 `{image_id}.{ext}` 落地。
2. 一个资产还没有当前图片时，首张成功上传的图片自动成为 `is_current=true`，并因当前版本发生变化使资产 `revision +1`。
3. 资产类型创建后不可修改；C003 API/UI 只允许 `character`、`scene`，`prop` 只保留为 C001 数据库约束中的未来枚举值，v1 不创建、不编辑、不展示道具资产。

## 范围内

1. 增加手动资产的创建、项目内列表、单项读取、名称/描述编辑和删除；创建时 `source=manual`，类型只允许角色或场景。
2. 增加图片列表、multipart 上传、当前版本切换和图片删除；首张成功上传自动设为当前，当前图片禁止直接删除并返回 409。
3. 按上传文件的真实格式保留字节与正确扩展名；执行大小、MIME 与完整解码校验，使用系统生成路径并记录存储字节的 sha256。
4. 提供 `GET /media/asset-images/{id}`；只按数据库 ID 查找真实路径并流式返回，不接受用户路径，不向业务 API 暴露 `file_path`。
5. 实现正常路径上的临时文件→校验→sha256→同文件系统原子改名→数据库记录；失败不重试、不返回伪成功，并清理尚未落定的临时文件。
6. 资产图片、资产和当前已交付项目删除路径涉及的资产媒体均移入 `{DATA_DIR}/trash/...`；启动时及每 24 小时清理超过 `TRASH_RETENTION_HOURS` 的 trash 文件。
7. 把集工作区资产选项卡升级为当前项目级资产管理页，交付真实 loading/error/empty/ready、CRUD、上传、画廊、当前版本与删除交互。
8. 只为追溯表中两条资产级联行增加 C003 部分覆盖的 API 集成测试，并准确标注下游 changed/stale/R12 部分仍由后续 change 完成。

## 范围外

- 不实现 `generate-assets`、`generate-image`、Qwen、Z-Image、ComfyUI、任务队列、worker、WS、seed 抽卡、user_note、prompt 构建、input_hash 或诊断面板；分别属于 C004-C007。
- 不实现剧本旧版本角标、自动生成资产、分镜生成、分镜编辑/绑定、片段、槽位、override、视频或导演台业务。
- 不提前实现“编辑资产/换当前图”对已绑定分镜的 `changed` 与相关片段的 `stale`；这些下游实体的可达行为按 PRD §11 在 C006/C008-C009 落地。
- 不完整实现 R12 的快照展示、片段 stale、槽位停用/override 处置或生成前 R10 阻断；C003 只保留 C001 已有外键的 `ON DELETE SET NULL` 数据库效果，完整行为属于 C008-C009。
- 不暴露或修改 `image_prompt_cache`、`image_prompt_hash`、`built_prompt`、`input_hash`、`input_snapshot`、`user_note`；不实现 `DEBUG_PROMPTS` 产物详情。
- 不新增数据库迁移、表、字段、索引、审计、repository、unit-of-work、缓存、锁文件、重试、fallback 或兼容层。
- 不实现道具资产、资产别名/合并、资产版本化、候选分镜版本、风格/模板版本化、`generation_runs`、continuity、context loop、fl2v 或音频。

## 现状与预期影响

- `backend/pyproject.toml`：增加 FastAPI multipart 所需依赖与成熟图片解码库；不引入自研图片解析器。
- `backend/app/schemas/`、`services/`、`api/`：增加资产、资产图片、媒体和本地文件生命周期的最小模块；继续使用现有 async session 与统一错误边界。
- `backend/app/main.py`：注册资产/媒体路由，并在 lifespan 中管理 trash 启动清理与每日后台任务；健康骨架仍不探测外部服务。
- `frontend/src/api/`、`pages/`、`styles.css`：增加资产类型化客户端与资产页；不改变剧本、分镜、导演台和任务中心的业务边界。
- `backend/tests/api/`、`openspec/TRACEABILITY.md`：仅增加并回填本 proposal 明列的两条资产相关追溯场景。
- `backend/alembic/` 与 C001 schema：无变化。

## 依赖

### 前序 change

`C002` 是唯一前序 change。2026-08-25 最终复审确认其专用 PostgreSQL 验收库为 `6b8e3f0a1d24 (head)`、`alembic check` 无漂移、完整 pytest 为 `3 passed`、前端构建和 T15/T16 浏览器流程通过，因此 C003 可基于其项目、剧集和工作区能力开工。C001/C002 尚未 archive 不扩大 C003 的实现范围。

### 外部依赖

| 来源（PRD §12） | C003 开工/验收门槛 | 当前证据 | 缺失项与处理 |
|---|---|---|---|
| §12.1 Z-Image、MiniMax H3 工作流与绑定 | 非 C003 开工或验收门槛 | `docs/前置依赖清单.md` 状态为“待提供” | C003 不读取、不校验、不伪造工作流；留待 C007/C009 |
| §12.2 四个提示词模板初始内容 | 非 C003 门槛 | C002 已以明确占位内容交付四个固定 key；正式内容仍待提供 | C003 不读取或修改模板，不把占位内容当正式依赖 |
| §12.3 vLLM sleep/wake | 非 C003 门槛 | 状态为“待提供” | C003 不启动或调用 vLLM；C007 开工前补齐 |
| §12.4 PostgreSQL DSN | 沿用 C001/C002；C003 API 集成与验收必须使用可验证的真实 PostgreSQL | 本机 PostgreSQL `5432` 已提供；2026-08-25 Sol 在专用库 `ai_drama_studio_c003_audit_20260825` 验证 `6b8e3f0a1d24 (head)`、`alembic check` 无待生成操作、两条授权用例 `2 passed`、完整 pytest `5 passed` | C003 的 PostgreSQL 验收依赖证据已合格；当前复审未通过源于实现/spec 偏差，不是外部依赖缺失。默认示例、SQLite 或 mock 仍不得作为验收证据 |
| §12.4 Comfy/vLLM 地址端口 | 非 C003 门槛 | 尚待对应 change 提供 | C003 不发出任何外部请求，也不把 `.env.example` 示例地址视为可用服务 |

ROADMAP 对 C003 标注“无新增”外部依赖。multipart 与图片解码 Python 包属于仓库实现依赖，不是 PRD §12 外部服务；实施时应使用现有框架生态的成熟库，不手写解析器。

## 风险与控制

- **格式与扩展名不一致**：以完整解码得到的真实格式为准，声明 MIME 必须匹配；JPEG 统一使用 `.jpg`，不把 JPEG/WebP 原始字节伪装为 `.png`。
- **首图并发产生多个 current**：上传和当前切换必须在资产级串行化事务内执行，并继续依赖已有部分唯一索引兜底；不通过重试掩盖竞态。
- **DB 与文件系统不存在共同事务**：不得宣称跨系统原子。正常路径严格按 spec 顺序执行；任何文件或数据库失败都必须显式失败并记录真实原因，不返回 2xx，不吞错，临时文件在 `finally` 清理。
- **路径穿越或泄露**：用户文件名不入路径，业务响应不返回 `file_path`，媒体端点只接受数值 ID；所有正式、临时和 trash 路径必须解析在配置的 `DATA_DIR` 内。
- **级联被提前实现**：C003 只闭环资产本身和媒体文件。分镜 changed、片段 stale 及完整 R12 必须留待拥有下游实体行为的后续 change。
- **测试过量**：上传格式、媒体响应、CRUD/UI、项目删除与 trash 定时清理没有独立追溯行，只能通过命令和人工检查验收；新增自动测试仅限两条资产级联行。

## 完成定义

只有 `spec.md` 的 API、状态、文件和 UI 行为全部满足，专用 PostgreSQL 验收环境可用，授权的两条 API 集成用例和完整 pytest 通过，前端生产构建成功，真实浏览器可完成“进入资产页→建资产→传三种格式→首图自动当前→切版本→读媒体→删非当前图→删资产并见文件进入 trash”，启动/每日 trash 清理有真实人工证据，追溯表仅回填授权行，且 diff 无后续生成/任务/分镜/片段或范围围栏能力时，C003 才可提交 Sol 审查。

## Sol 复审记录（2026-08-25）

结论：**未通过**。C003 的外部依赖、迁移一致性、授权测试、完整回归、生产构建、后端媒体/文件行为、并发首图、trash 与大部分浏览器 CRUD 均取得合格证据，但以下行为仍不符合 `spec.md`，在修复并复审前不得将 C003 视为完成：

1. **资产页媒体不可见**：`frontend/src/api/assets.ts` 按 spec 生成 `/media/asset-images/{id}`，但 `frontend/vite.config.ts` 只代理 `/api`。真实浏览器因此请求 `http://127.0.0.1:5173/media/asset-images/{id}`，得到 Vite 的 `text/html`（200），全部图片 `naturalWidth=0`；同一 ID 直连后端 `:8000` 为正确图片 Content-Type 与原字节。Luna 须补齐开发/验收环境的 `/media` 转发，使当前图和画廊真实可见，不得改成占位图或 fallback。
2. **上传错误优先级及执行顺序错误**：`backend/app/services/assets.py` 在确认并锁定路径资产前先校验 MIME、写临时文件和解码。实测未知资产配 `text/plain` 返回 422；`spec.md` §5.2 明确要求先验证路径资产，未知资产为 404。Luna 须按 spec 调整顺序，未知路径资产不得先消费上传内容或被 body 校验覆盖为 422，且不得引入重试。

已通过证据：专用 PostgreSQL 为 `6b8e3f0a1d24 (head)`，`alembic check` 为 `No new upgrade operations detected.`；授权 node ID 为 `2 passed`，完整 pytest 为 `5 passed`；`npm run build` 成功；PNG/JPEG/WebP 原字节、扩展名、sha256 与后端媒体 Content-Type 一致；并发首图两请求均 201、唯一 current、revision=2；current 直接删除为结构化 409，上传内容错误为结构化 422；资产/项目删除、冲突回滚与 trash、启动过期清理均通过；范围扫描无 migration 或后续 change 能力。

## Sol 增量复审记录（2026-08-25）

结论：**通过**。提交 `50c8148` 只修改 `backend/app/services/assets.py`、`frontend/vite.config.ts` 与本 change 的 `tasks.md`，首次复审的两项问题均已关闭：

1. Vite 已将 `/media` 转发至后端。PNG/JPEG/WebP 经 `http://127.0.0.1:5173/media/asset-images/{id}` 分别返回 200 与正确 Content-Type，响应字节 sha256 与上传文件一致且不再返回 `text/html`；真实浏览器中既有及新上传图片均为 `complete=true`、`naturalWidth=11`。
2. 上传现已先锁定并确认路径资产。对同一未知 asset ID 上传有效图片、非法 MIME、损坏图片和超限内容均为 404 / `not_found`，`DATA_DIR` 无临时文件；对存在资产的非法 MIME、损坏和超限内容仍为 422 / `validation_error`。有效三格式上传保持 201、原字节/hash/扩展名不变，并发首图两请求均 201、唯一 current、revision=2。

回归证据：`alembic current` 为 `6b8e3f0a1d24 (head)`，`alembic check` 为 `No new upgrade operations detected.`；两条授权用例 `2 passed`、完整 pytest `5 passed`；`npm run build` 成功（51 modules transformed）；真实浏览器完成创建、编辑、上传两版本、切换 current、删除非 current 与删除资产，图片行/资产行删除且文件进入 trash。增量 diff 没有测试或 migration 变化，范围扫描未发现后续 change 或范围围栏能力。
