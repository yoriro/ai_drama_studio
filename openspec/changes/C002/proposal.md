# C002 M1 项目、设置与剧集 Proposal

## 元数据

- Change：`C002`
- 里程碑：PRD §11 M1 的“项目、风格、模板、剧集 CRUD 与页面”纵向切片
- 前序 change：`C001`
- 当前状态：实现与 2026-08-25 Sol 最终复审均已完成；C002 符合 spec，尚未执行 archive

## 背景与现状

`C001` 已建立 FastAPI、统一错误边界、SQLAlchemy 2 全量 metadata、Alembic 初始迁移、React/Vite/TS 路由壳和相对路径 API 客户端。C002 当前实现已增加运行时数据库 session、四类业务 API、模板数据迁移与对应页面；`openspec/archive/` 仍为空，C001/C002 均尚未 archive。

2026-08-25 的验收核对显示，C002 专用验收库 `ai_drama_studio_c002_acceptance_20260824` 位于 `6b8e3f0a1d24 (head)`，`alembic check` 无待生成操作，四条占位模板可读；默认库 `ai_drama_studio` 仍位于 C001 revision `3ad09fb566ed`，尚未部署 C002 migration。

## 目标

交付一个不依赖生成系统的可运行纵向切片：操作者可维护风格和固定四类提示词模板，可创建、查看、编辑、删除项目与剧集，可在真实集级工作区录入和修改剧本；后端落实剧本修订以及风格/模板“只影响后续生成”的语义，前端只呈现并调用 API，不承担最终业务裁决。

## 范围内

1. 建立 SQLAlchemy async engine/session 与 FastAPI 请求事务边界，继续只支持 PostgreSQL + asyncpg。
2. 以一条数据迁移写入四个固定 key 的明确占位模板；不改 C001 定稿 schema，不 seed 风格、项目或剧集。
3. 实现项目、风格、固定模板和剧集的 C002 REST API，包括项目删除对当前可创建剧集的事务级联，以及被项目引用的风格禁止删除。
4. 实现剧本创建/编辑的 `SCRIPT_CHAR_LIMIT` 校验；实际剧本内容变化时 `script_revision` 原子加一，其他下游行、状态和文件均不动。
5. 实现风格/模板编辑即时对读取结果生效，但不追溯修改任何既有分镜、片段、产物或状态，不创建版本历史，也不提前计算 input_hash。
6. 把项目首页和设置页从空态升级为真实管理页面，新增项目剧集页与带真实 project/episode ID 的四选项卡工作区；项目详情可用按钮返回项目首页并提供“进入集工作区”入口，工作区可用按钮返回当前项目；剧本页先展示最近一次持久化剧本，再由页内“编辑剧本”按钮进入编辑态，保存成功有可见反馈；本 change 仅让剧本选项卡具备业务功能。
7. 只增加追溯表已授权的 C002 API 集成用例：`§3.3 编辑剧本`、`§3.3 编辑风格或模板`，以及 R11 的“模板可见可编辑”部分；其他 CRUD 使用命令和人工验收。

## 范围外

- 不实现资产 CRUD、上传、画廊、`is_current`、`/media`、原子媒体写入或 trash；这些属于 C003。
- 不实现项目/剧集删除对资产、分镜、片段、任务或媒体文件的后续级联；PRD §11 明确级联在其下游实体所在里程碑落地，C003 及后续 change 负责扩展。
- 不实现任务队列、worker、WS、取消、去重、重启恢复或任何生成动作；这些始于 C004。
- 不实现剧本“基于旧剧本”角标、生成资产/分镜按钮、impact/token、分镜页或资产页业务；这些属于 C005/C006。
- 不实现设置页系统诊断、workflow binding、vLLM/ComfyUI 探测；这些属于 C007。
- 不实现 `asset_images`/`clip_videos` 详情或 `DEBUG_PROMPTS` 条件字段；R11 的该部分由 C007/C009 落地。
- 不实现提示词渲染、变量校验、input_hash、built_prompt/input_snapshot 写入或生成日志。
- 不新增鉴权、分页、搜索、排序编辑、批量操作、导入导出或未列 API。
- 不实现或预建范围围栏中的候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格/模板版本化、`generation_runs`、continuity、context loop、fl2v 或音频能力。

## 现状与预期影响

- `backend/app/db/`：增加运行时 async session 与 FastAPI dependency，不增加连接重试或替代数据库。
- `backend/app/api/`、`schemas/`、`services/`：增加四类资源的最小路由、输入输出模型和事务用例；不增加 repository/projection/registry 等额外层。
- `backend/alembic/versions/`：在 C001 head 之后增加一条只写四个占位模板的数据迁移，不改表结构。
- `frontend/src/api/`、`features/`、`pages/`、`routes/`：增加类型化 CRUD 调用、项目/剧集工作区和设置管理界面；保留任务中心空实现。
- `backend/tests/api/` 与 `openspec/TRACEABILITY.md`：实施时只添加并回填本 proposal 列出的三行场景；R11 与风格/模板行只回填 C002 已覆盖部分，不得宣称后续提示词详情/hash 行为已测完。

## 依赖

### 前序 change

`C001` 是唯一前序 change。其代码、迁移、pytest、前端构建及 PostgreSQL head 已复审通过，具备 C002 开发基线。C001 尚未 archive 不改变当前“仅规划 C002”的授权边界，也不得被解释为允许直接开始实现。

### 外部依赖

| 来源（PRD §12） | C002 开工/验收门槛 | 当前证据 | 缺失项与处理 |
|---|---|---|---|
| §12.1 Z-Image、MiniMax H3 工作流与绑定 | 非 C002 开工或验收门槛 | `docs/前置依赖清单.md` 为“待提供” | C002 不读取、不校验、不伪造工作流；留待 C007/C009 |
| §12.2 四个提示词模板初始内容 | 正式内容不是 C002 门槛；PRD 明确允许先用占位示例 | C002 专用验收库已有四个固定 key 的明确占位内容；正式内容仍为“待提供” | 现有 GET/PATCH 和设置页可用占位内容验收；正式内容仍须在 C012 验收前提供，不得把占位内容标成正式内容 |
| §12.3 vLLM `--enable-sleep-mode` 与 sleep/wake | 非 C002 开工或验收门槛 | 依赖清单为“待提供” | C002 不启动或调用 vLLM；C007 开工前补齐 |
| §12.4 PostgreSQL DSN | 沿用 C001，C002 开工及 API 集成验收均须使用真实 PostgreSQL | 本机 PostgreSQL `5432` 已提供；2026-08-25 使用专用验收库 `ai_drama_studio_c002_acceptance_20260824` 验证 `6b8e3f0a1d24 (head)`、`alembic check` 无待生成操作、完整 `pytest` 为 `3 passed` | C002 专用验收门槛已有合格证据；默认库 `ai_drama_studio` 仍停留在 C001 revision，部署 C002 前不得将其描述为已就绪；不得用 `.env.example`、SQLite 或 mock 替代 |
| §12.4 Comfy/vLLM 地址端口 | 非 C002 开工或验收门槛 | 尚待对应 change 提供 | C002 不发送任何外部请求，也不把示例地址当作 healthy 证据 |

## 风险与控制

- **M1 被拆成两个 change**：C002 只交付项目/设置/剧集；C003 才让资产和文件成为可达下游。项目删除在 C002 仅级联当前可创建的剧集，不提前编写资产/media/trash 逻辑。
- **“模板 CRUD”被误扩张**：PRD §5 的精确接口只有固定四 key 的 GET/PATCH；不提供模板 POST/DELETE，也不允许改 key。
- **占位模板被误当正式输入**：四条内容带 `[占位]` 标识；无运行时 fallback 或自动替换。正式内容由需求方后补并经现有 PATCH 明确保存。
- **剧本修订丢失或误增**：只有 `script_text` 实际变化时增加一次 revision；标题/集序变化不增加，同值 PATCH 不伪造新修订；单次数据库更新保证内容和 revision 同事务提交。
- **更新语义越界**：编辑剧本、风格、模板不得触碰后续实体；相关 API 集成用例只验证“不动”，不提前实现 stale/changed/hash/task 行为。
- **前端成为业务裁决源**：前端可做输入提示和确认交互，但后端始终复核；所有 API 错误直显 `detail.message`，不吞错、不重试、不伪造成功。

## 完成定义

只有 `spec.md` 的全部可观察行为满足、四条占位模板经真实 PostgreSQL migration 可重建、授权 API 集成用例与完整 pytest 通过、前端生产构建成功、项目→剧集→剧本及设置页真实操作可完成、追溯行按实际 node ID 回填且范围审查无后续能力时，C002 才可提交 Sol 审查。

## Sol 首轮审计记录（2026-08-25）

- 已验证通过：专用验收库 migration head/check、完整 `pytest`（`3 passed`）、前端生产构建、主要 CRUD/错误体/409/422 语义、项目→剧集→剧本与设置页真实操作、项目/集路由关系保护、追溯表回填及范围围栏扫描。
- 阻塞项 1：并发剧本 PATCH 使用 ORM 读改写，20 个成功请求后最终 `script_revision` 仅为 `8`，而按初始 revision `1` 应为 `21`；不满足原子递增。
- 阻塞项 2：项目创建在风格存在性检查后遇并发删除，数据库 FK 冲突返回 `500 internal_error`，未按 spec 转换为 `409 conflict`。
- 阻塞项 3：前端使用 JavaScript UTF-16 `string.length` 统计字符；`审计剧本🎬` 后端字符数为 `5`，页面显示 `6`，与后端 `SCRIPT_CHAR_LIMIT` 的 Unicode 字符口径不一致。
- 阻塞项 4（原 spec 缺口）：集工作区没有直接返回当前项目详情的入口，用户只能先回项目首页再重新进入项目。
- 阻塞项 5（原 spec 缺口）：项目剧集卡片没有明确的“编辑剧本”入口；剧本保存成功后虽留在原页并更新 API 返回状态，但页面没有持续可见的成功反馈，用户无法判断操作是否完成。保存后不自动跳转本身不构成失败。
- 审计结论：C002 暂不符合 spec，修复上述阻塞项并完成复审前不得 archive；默认库部署缺口与实现缺陷分开跟踪。

## Sol 增量复审记录（2026-08-25）

- T10 已通过：20 个并发剧本 PATCH 全部返回 200，初始 revision `1`，最终 revision 精确为 `21`，临时数据清理返回 204。
- T11 已通过：项目 POST/PATCH 的风格 FK 确定性竞态均返回 `409 conflict`，PATCH 后原 style_id 保持不变，临时数据清理返回 204。
- T12 已通过：浏览器输入 `审计剧本🎬` 显示字符数 `5`。
- T13 已按上一版 spec 通过：项目详情存在“编辑剧本”入口，工作区四个选项卡共用返回当前项目的链接；该交互随后被本轮 T15-T16 新要求取代。
- T14 已通过：保存成功显示 API 返回 revision；再次修改后旧成功消息消失。
- 基线证据：专用验收库为 `6b8e3f0a1d24 (head)`，`alembic check` 无操作，完整 `pytest` 为 `3 passed`，前端生产构建成功，增量 diff check 成功。
- 本轮新增调整：工作区“返回项目”改为按钮呈现；项目详情增加“返回项目首页”按钮；项目详情不再承载“编辑剧本”动作，改为“进入集工作区”；剧本页默认展示最近一次持久化内容，并在页内提供“编辑剧本”按钮和明确的查看/编辑状态转换。
- 当前结论：上一轮实现缺陷已修复，但 T15-T16 未实施，C002 仍不得 archive；完成后须再次由 Sol 浏览器复审。

## Sol 最终复审记录（2026-08-25）

- T15 已通过：项目详情的“返回项目首页”和集工作区的“返回项目”均为文字明确的按钮外观链接，目标分别精确为 `/` 与 `/projects/{projectId}`；剧本、资产、分镜、导演台四个工作区 URL 均提供相同的返回项目入口，不依赖浏览器历史。
- T16 已通过：项目详情仅显示“进入集工作区”；剧本页默认逐字展示最近一次持久化剧本、保留换行并显示 revision，查看态没有 textarea/保存按钮；页内“编辑剧本”进入预填编辑态，取消后没有 PATCH、内容与 revision 不变。
- 保存与失败行为已通过：浏览器保存后仍在 `/script`，退出编辑态，API revision 从 `1` 增至 `2`，显示 `role=status` 成功消息；随后提交 2001 字符触发 422，编辑态和 2001 字符原输入保留、旧成功消息清除，数据库仍保持 revision `2` 与上一次成功内容。
- 层级与持久化已通过：从工作区点击“返回项目”进入精确项目详情，再点击“返回项目首页”进入 `/`；切换三个后续空态选项卡并返回剧本页后，仍显示数据库中的最近保存内容与 revision。
- 命令证据：在 C002 专用验收库运行 `alembic current` 得 `6b8e3f0a1d24 (head)`，`alembic check` 得 `No new upgrade operations detected.`，完整 `python -m pytest -q tests` 得 `3 passed in 1.13s`；`npm run build` 成功，`git diff --check` 成功。
- 环境说明：未注入 `DATABASE_URL` 的裸 pytest 会连接仍停在 C001 revision 的默认库并失败；改用 `docs/前置依赖清单.md` 已登记的 C002 专用验收 DSN 后，上述迁移与测试全部通过。默认库未部署 C002 migration 继续作为部署状态记录，不冒充验收库缺陷或完成证据。
- 最终结论：未发现剩余 spec 偏差或范围围栏违规；C002 通过 Sol 复审，可作为 C003 前序 change，尚未获得 archive 指令。
