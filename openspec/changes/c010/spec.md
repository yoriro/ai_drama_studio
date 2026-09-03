# C010 M4 导演台 UI Spec

## 目标与边界

### 目标

C010 交付 ROADMAP 中 M4 的浏览器导演台：把 C008/C009 已有的 clip、slot、video 与 task 合同接成“一带两轨一板”，完成分镜选择、预检、参考资产精简、创建片段、片段输入编辑、槽位处置、视频生成、take 画廊与 current 切换，并把 `generation_state` 与 `freshness` 作为互不覆盖的两维状态呈现。浏览器只做可用性提示，R5/R5a/R6/R7/R8/R9/R10/R12 仍以现有 API 返回为最终裁决。

### 范围内

1. 用现有 `/api/projects/{project_id}/assets`、`/api/episodes/{episode_id}/shots` 与 `/api/episodes/{episode_id}/clips` 构建场景带、分镜轨和片段轨；所有轨道共享同一分镜列定义，使宽度与 `duration_est` 成比例。
2. 在分镜轨提供唯一的“新片段分镜勾选”入口；按场景身份给出跨场景置灰，零场景分镜仍可加入任意单场景选择，绑定多个场景的分镜显示警示且不可勾选。连续性、占用与最终同场景裁决由 preview/create API 完成。
3. 完成 `preview → 选择参考资产 → create` 交互：逐字展示服务端 violations/warnings，保持候选顺序与默认选择，以服务端响应推导本次最大可选数，不复制可配置阈值。
4. 片段详情面板提供 `user_note`、`requested_duration` 保存和片段删除；选中 Clip 的槽位面板提供启停、override 上传/清除、R9 图片展示与 R12 已删资产处置引导。
5. 视频区提供生成按钮、任务状态/进度/完整失败原因、take 画廊、current 切换、非 current take 删除、视频播放，以及 `DEBUG_PROMPTS=true` 时服务端实际返回的可选调试字段展示。
6. 按 D-008 实现 Director 专用的 WS/REST 同步：先连 WS 并缓冲事件，再取 REST 快照；旧响应不得覆盖新事件或新的选中 Clip；mutation/terminal refresh 遇到更新事件时必须重发最新快照，成功提示只能在最新快照落地后出现。
7. 新增 C010 所需的前端纯逻辑与任务事件竞态自动测试、真实浏览器走查和生产通路证据；保持后端完整回归全绿。
8. 仅为解除 T12 现场发现的 MiniMax H3 外部枚举漂移，允许把 `backend/workflows/minimax_h3_ref2v.json` 节点 `310.inputs.lora_name` 从裸文件名精确改为当前 Comfy `/object_info` 注册的 `minimax_h3\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`；由该唯一字面值变化产生新的 workflow hash。
9. 为同步第 8 项必然改变的 raw workflow hash，仅按 `AGENTS.md` 的 C010 一次性窄例外，把四个既有测试文件中的单一固定 hash 常量从 `bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780` 精确更新为当前 Windows checkout 的 `4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772`；不改变测试结构、参数或断言强度。

### 范围外

- 不新增或修改后端 router、schema、service、task handler、模型、migration、工作流绑定配置或提示词模板；除范围内第 8 项对既有 workflow JSON 单一叶子的精确修正和第 9 项四个测试常量的窄同步外，C010 只消费 C008/C009 已有合同。不得借该修正加入动态 LoRA 查找、basename 归一化、兼容别名、fallback、retry，或修改 Comfy 错误体处理。
- 不实现 C011 的全局导航重做、全站响应式/视觉统一、任务中心取消/历史/过滤、全局 toast 框架或跨页面状态框架；C010 只做导演台可操作所需的局部布局、反馈、空态和错误态。
- 不实现 C012 的整集发布 E2E、自动化视觉质量判定或无人值守全链路验收。
- 不实现分镜增删/拆分/合并/排序、候选分镜版本、资产别名/合并、风格/模板版本化、独立 `generation_runs`、continuity 字段或逻辑、`fl2v`/`context_loop` 交互与生成、音频数据/API/控件/占位轨。PRD §9 的“为 v2 预留音频轨位置”在 v1 只表示当前两轨布局不得声称交付音频；不得据此预建音频组件或扩展点。
- 不把 preview 结果变成授权 token，不在前端复制 PostgreSQL 锁、R5-R10 规则引擎、配置阈值、重试、轮询或静默 fallback。
- 不重构 AssetPage、TasksPage 或通用应用壳；Director 的同步逻辑可以复用既有 API/WS 客户端，但不得为了 C010 顺手抽象全站状态层。

### 现状/影响

- C009 完成提交 `ba8730175ce4f5647152c7c682270058ebe8d196` 与归档提交 `af7f6fd9310ba7ac2dc577a7db7457b7c18f7d4e` 均已提交并作为当前 C010 执行基线的祖先。C009 全部 checkbox 已完成，`.work/c009/T29-full-pytest.log` 为 `346 passed`，T29 前端 build 为 `55 modules transformed` 且成功；C009 完成报告同时明确 Director UI 尚未交付。
- `frontend/src/routes/AppRoutes.tsx` 已有 `/projects/:projectId/episodes/:episodeId/director` 路由；`EpisodeWorkspacePage` 的导演台 tab 目前只显示“暂未交付”空态。当前没有 clips 前端 API 模块、Director 页面或前端自动测试 runner。
- 后端已经提供本 change 所需的 preview/create/list/detail/PATCH/DELETE、slots、generate-video、videos/current/delete、Task REST/WS 与 `/media` 路由；公开 seed 已是十进制 string，Clip 响应已含两维状态和 warnings。本 change 预期 **零 migration、零后端 Python/测试变化**；唯一 backend 工件变化是范围内第 8 项的 workflow JSON 单叶修正。
- C010 T12 首次真实生成已证明 vLLM chat 返回 200、9 次参考图片上传均返回 200，但 Comfy `POST /prompt` 在入队前返回 400，queue/history 为空。`.work/c010/T12-comfy-object-info.json` 显示当前 `LoraLoaderModelOnly.lora_name` 允许带 `minimax_h3\` 前缀的注册名，不允许仓库 workflow 节点 310 使用的裸文件名；当前旧 workflow SHA256 为 `bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780`。这说明 C009 的历史成功只证明当时运行环境可接受该值，不能证明当前外部枚举未漂移。
- T11A 首轮已证明外部注册名、workflow 单叶语义 diff、`1 insertion/1 deletion`、raw hash `4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772`、生产 binding loader、frontend test/build 均通过；完整 pytest 的 `339 passed, 7 failed` 全部只因四个既有常量仍固定旧 hash。该结果不是 workflow 功能失败，但在四个常量按授权同步并完整 pytest 全绿前，T11A 仍未完成。
- C009 文档已由提交 `af7f6fd9310ba7ac2dc577a7db7457b7c18f7d4e` 以内容不变的 rename 归档至 `openspec/archive/C009/`，活动目录 `openspec/changes/c009/` 已不存在。C010 将归档文档视为只读，不再次移动或改写。
- `.work/` 是既有未跟踪证据目录；C010 只在 `.work/c010/` 保存原始日志、截图和临时验收资料，不纳入提交。

### 风险

| 风险 | C010 约束 |
|---|---|
| 前端把置灰或按钮状态当成业务真相 | 置灰只限制已知跨场景/多场景 UX；preview/create/generate/slot/video 的 HTTP 结果始终最终有效，失败 `detail.message` 可见 |
| “跨段置灰”误伤 R5a 的零场景合法选择 | 零场景显示灰段但没有场景身份；在选择任一单场景后仍可勾选零场景。仅不同的单场景与多场景分镜不可勾选 |
| 三条轨道因各自计算宽度而错位 | 一个纯投影结果生成共享 CSS grid columns；场景段、Shot 块、Clip 跨度与空洞只引用同一 Shot index map |
| 前端硬编码默认 5/15 秒、4/9 个导致非默认配置漂移 | requested duration 交给 API 校验；候选最大可选数从 `reference_candidates` 与 `default_reference_asset_ids` 推导；黄色提示只展示 API warnings，不解析 message 反推配置 |
| preview 后数据变化 | 任一分镜选择变化立即废弃 preview；create 仍提交正式 API 并展示重新裁决的 422，不使用本地 token 或旧结论伪成功 |
| 旧 REST 覆盖新 WS 或新选中 Clip | 为页面快照和 Clip 详情分别维护请求代次；事件到达会使相关在途响应失效并要求最新 refresh，旧响应只丢弃、不应用 |
| mutation 已成功但随后刷新失败，页面显示伪成功 | 不做业务数据乐观写入；保留可见错误与待同步状态，重新建立 WS/REST 快照后才显示成功通知，不自动重放 mutation |
| WS/REST refresh 覆盖用户尚未提交的详情草稿 | 同一选中 Clip 的 refresh 只更新字段 base；dirty 字段保留用户原值并相对新 base 重算，未 dirty 字段才跟随服务端；切换/删除 Clip 才丢弃整份草稿 |
| immediate-failed Task 被当成“已成功开始生成” | `202/task_id` 只表示任务记录已创建；获取 Task/Clip 最新真相，failed 时显示完整 `error_msg`，不显示生成成功 |
| 多个视频任务被 UI 错误去重 | 只在一次 HTTP 请求在途时禁用生成按钮；收到 202 后可再次有意点击创建新任务，不生成或复用 request_id |
| 已删资产槽位被自动修复或重排 | 显示快照名、固定文案“原资产已删除”和当前图片来源；只提供停用或上传 override，不自动停用、替换、压缩或改号 |
| 媒体/调试字段泄露内部路径或大整数失真 | 图片/视频仅使用 API 给出的 `/media/...`；seed 保持 string；只在响应实际包含 DEBUG 字段时展示，不构造内部路径 |
| 静态 binding 合法但 Comfy 外部枚举已漂移 | 在 T11A/T12 启动新任务前读取当前生产 Comfy `/object_info`；节点 310 必须精确使用注册值，禁止根据目录或 basename 猜测、运行时改写、别名兼容或失败后 fallback |
| workflow 已授权变化但固定 hash 测试仍停在旧基线 | 只更新 `AGENTS.md` 明列的四个常量到同一个新 raw hash；保留所有既有断言，不改成动态 expected、不修改其他测试或生产 hash 算法 |
| C010 借局部页面提前完成 C011/C012 | 样式限定 Director class，测试只覆盖当前业务交互；不加全局设计系统、移动端重构、完整 E2E 平台或后续业务入口 |

## 外部依赖

| 来源 | C010 开工或验收门槛 | 当前证据 | 缺失项与结论 |
|---|---|---|---|
| PRD §12.1：MiniMax H3 ref2v API workflow 与 binding | 编写前端与纯逻辑测试不依赖 workflow 现场运行；真实“点击生成→take 可播放”验收前，当前 Comfy `/object_info` 必须包含 workflow 节点 310 的精确 LoRA 注册名，生产 binding loader 必须通过，后端 health 必须报告 `workflow_bindings.status=valid` 且 `hashes.minimaxh3` 等于本次修正后的现场值 | C009 T17 曾用旧裸文件名完成 1-reference/2-reference 视频，但 C010 T12 的 `.work/c010/T12-failure-final.log`、`T12-comfy-input-diagnosis.log` 与 `T12-comfy-object-info.json` 已证明当前运行时在 9 次 upload 200 后拒绝裸文件名并令 `/prompt` 返回 400；仓库旧 hash 为 `bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780` | **当前阻塞 T12，不阻塞已完成的前端任务**；先完成 T11A 的精确单叶修正并取得当前 `/object_info`、生产 loader 与新 hash 证据，再以全新数据库、DATA_DIR、Task 和 request 重新执行 T12；不得重试旧 failed Task、伪造注册名或用 C009 历史成功替代 |
| PRD §12.2：正式 `minimaxh3` 提示词模板 | UI 不读模板正文；真实视频验收要求隔离库中的 `minimaxh3` 已通过正式设置 API 安装并能被 C009 生成链路读取 | C009 完成报告记录模板 PATCH/GET 逐字相等及真实生成证据 | **实现门槛已满足、现场验收需重证**；不得由 C010 写默认/占位模板，也不得把下载文件复制进仓库 |
| PRD §12.3：vLLM `/sleep`、`/wake_up` | 普通 Director UI、preview/create/slot/take CRUD 不依赖 GPU；真实视频验收要求 vLLM health 可达，且任务结束后资源终态可观测 | C009 T17/T26 已有真实资源生命周期证据 | **非普通 UI 开工门槛**；真实视频 task 前后重新记录 health/sleep 状态，失败直接报告，不重试或 fallback |
| PRD §12.4：PostgreSQL DSN、vLLM/Comfy 地址端口 | C010 API/WS 浏览器验收和完整 pytest 必须使用显式 `DATABASE_URL` 指向全新隔离 PostgreSQL；真实视频还要求正式配置的 vLLM/Comfy 可达。浏览器仍只访问同源 `/api`、`/media`、`/ws` | `NOTES.md` 记录 PostgreSQL `127.0.0.1:5432`、显式导出 DSN、全新库/Alembic 与 advisory-lock 坑；C009 T29 在全新库通过。C009 完成报告明确终态后 Comfy 存活曾漂移，不能沿用为当前在线声明 | **开工时需现场刷新**；PostgreSQL 不可达则停止 T0；GPU 服务不可达只阻塞真实视频验收 task，不得改用 mock 冒充该证据 |
| ROADMAP 前序 C009（非新增 PRD §12 输入） | C009 的后端/API/WS/媒体能力和回归必须已提交，且当前代码不得仍是 Director 假实现 | C009 完成及归档提交均为当前基线祖先；`openspec/archive/C009/tasks.md` 无未勾选项，active spec 不存在，archive spec 存在；路由仍是明确空态 | **满足功能与归档前序**；C010 不改写或再次移动 C009 archive |
| 前端自动测试 runner（非运行时、非 PRD §12） | 在任何 C010 前端自动测试落盘前，先以单独 task 加入一个与现有 Node/Vite 兼容的成熟 runner、固定 lockfile 与 `npm run test`；不得手写测试执行器 | 当前 `package.json` 只有 dev/build/preview，仓库无 Vitest/Jest/Playwright/Testing Library | **T1 前置交付**；只加纯逻辑/任务事件测试所需的 dev dependency，不引入 C012 浏览器 E2E 平台 |

C010 不需要用户再提供 MiniMax JSON 或 prompt 模板。唯一可能阻塞的是实施期现场服务状态；该状态必须在对应 task 当场验证，历史日志与用户口头“ready”均不冒充本次验收结果。

## 1. 可观察行为

1. 进入 Director tab 后，页面先建立 Task WS，再并行读取本项目资产、本集分镜与片段；加载中显示明确状态，空分镜显示可操作指引，任一失败显示可读错误且不伪造空列表。
2. 页面 ready 后固定呈现：场景带、分镜轨、片段轨与右侧/下方详情面板。轨道只用于查看、勾选新片段分镜或选择既有 Clip；所有 mutation 控件只在详情/预检面板。
3. 选中分镜后可发起 preview。响应中的 `violations`、`warnings`、估算总时长、建议请求时长、候选资产和默认选择逐项可见；有 violation 时创建按钮不可用，但响应仍作为一次成功预检呈现。
4. 创建成功后清空旧 preview/分镜选择、刷新权威快照、选中新 Clip，并加载其 slots 与 videos。创建 422 时保留面板供用户调整并逐字显示服务端 message。
5. 选中 Clip 后可查看并编辑意见/请求时长。设置保存是一条只含实际变化字段的 `PATCH /clips/{id}`；无变化不发请求。未保存的 requested duration 会禁用生成并显示“请先保存请求时长”；未保存的意见则可由生成请求按 C009 的 `user_note` 语义原值提交并与 Task 同事务保存。
6. Clip 删除使用现有确认交互；204 后等最新 REST 快照落地再清空选中项和提示成功。失败保留选中项及服务端真相。
7. Slot 按 `slot_no` 显示快照名/类型、enabled、`image_source` 与 API 媒体。启停、上传 override、清除 override 每次只发一个对应 mutation；完成后重取 Clip 与 slots，不本地猜测 revision/freshness/warnings。
8. `asset_deleted=true` 时固定显示快照名和“原资产已删除”。有 override 时仍显示 override；无图时显示缺图状态，并同时提供“停用槽位”和“上传 override”两个明确处置入口。
9. 生成按钮调用现有 `POST /clips/{id}/generate-video`，不带自动生成的 request_id。一次请求在途时禁用；202 后可再次点击创建另一条视频任务。202 只提示任务已提交，不能提示视频已生成。
10. 与所选 Clip 相关的 Task 进度/状态可见；failed 取 Task detail 的完整 `error_msg` 展示。Clip 轨和详情的 generation/freshness 永远来自刷新后的 Clip response，不由 WS message 在前端推导最终状态。
11. take 按 API 顺序显示 current、requested/actual duration、string seed 和可播放视频；设 current 后刷新且至多一项标记 current。current take 的删除控件置为不可用并说明原因；non-current 删除需确认且 204 后消失。
12. `DEBUG_PROMPTS=false` 时页面没有空的调试占位；响应实际带 `built_prompt`、`input_hash` 或 `input_snapshot` 时，所选 take 出现可展开调试区并逐字/结构化展示公开值，seed 仍按 string 处理。
13. 所有 API `ApiError` 的 `detail.message` 在 Director 页面可见；网络、非 JSON 或响应协议错误同样可见，但不得替换成旧数据成功态、自动重试 mutation 或吞异常。

## 2. 数据与 API 约束

### 2.1 只消费既有公开表示

C010 新增前端 TypeScript 表示与调用，但不改变后端 OpenAPI：

- `ClipPreviewResponse`：精确消费 C008 的 `shot_ids`、时长、`reference_candidates`、`default_reference_asset_ids`、`violations`、`warnings`。
- `Clip`：消费 `id/episode_id/generation_mode/user_note/requested_duration/generation_state/freshness/revision/shot_ids/start_order_index/end_order_index/enabled_slot_count/warnings/timestamps`。
- `ClipSlot`：消费公开快照字段、`asset_deleted/enabled/image_source/image_url`；不添加或读取 override 内部路径/hash。
- `ClipVideo`：seed 类型固定为 string；基础字段按 C009 §9。DEBUG 字段只建为可选公开字段，不假定存在。
- `Task`/`TaskEvent`：复用 `frontend/src/api/tasks.ts` 与 `frontend/src/api/ws.ts`；不得创建 Director 私有任务格式。

所有调用使用 `requestJson` 或 `requestNoContent`：

| 用户动作 | 既有 API | C010 请求约束 |
|---|---|---|
| 初始/刷新 | `GET assets`、`GET shots`、`GET clips` | 同一次页面快照代次；旧代次结果不得部分应用 |
| 预检 | `POST /episodes/{id}/clips/preview` | JSON 精确 `{shot_ids}`；使用当前勾选，不发送本地 scene/duration 结论 |
| 创建 | `POST /episodes/{id}/clips` | JSON 精确 `{shot_ids, reference_asset_ids, requested_duration, user_note}`；候选按服务端顺序过滤，不重排 |
| 保存设置 | `PATCH /clips/{id}` | 至少一个且只含实际变化的 `user_note`/`requested_duration`；前端只做可提交形状检查，范围以 API 为准 |
| 删除 Clip | `DELETE /clips/{id}` | `requestNoContent`，必须验证 204 空体 |
| 读取/启停 Slot | `GET /clips/{id}/slots`、`PATCH /clips/{id}/slots/{slot_no}` | JSON mutation 精确 `{enabled:boolean}` |
| override 上传/清除 | 同一 Slot PATCH | 上传使用 `FormData` 的单一 `file`；清除只含 `clear_override=true`；不得手写 multipart Content-Type |
| 生成 | `POST /clips/{id}/generate-video` | note 未变时 body `{}`；note 草稿实际变化时精确提交 string 或 null 的 `user_note`；不自动生成 request_id，不把 requested duration 重复塞进不存在的字段 |
| take | `GET /clips/{id}/videos`、`PUT /clips/{id}/current-video`、`DELETE /clip-videos/{id}` | current body 精确 `{video_id}`；DELETE 用 204 helper |

### 2.2 同源、媒体与外部值

- 浏览器 API 只用 `/api`，Task socket 只用既有 `/ws/tasks`，图片/视频只用响应中的同源 `/media/...`；不得硬编码 `127.0.0.1`、8000/8001/8188、磁盘路径或用户文件名。
- Shot/Asset/Clip 数组不得用前端点击顺序改写后端业务顺序。轨道按 Shot 响应的 canonical order 建 index；候选按 preview 数组顺序显示和提交；Slot/Video 按 API 顺序显示。
- `requested_duration` 输入在本地保留为 string 草稿；只有可无损转为十进制整数时才能提交。前端不硬编码 MIN/MAX，API 的 422 是最终范围裁决。
- `user_note` 草稿保留 `null` 与 string 的差异：未填写状态明确显示为 null；textarea 一经编辑即为 string（删除全部文字得到合法空串）；独立“清空为未填写”动作才把草稿设为 null。不得 trim 或把 null/空串/空白合并。
- 本次最大参考数固定从 preview 得到：若候选多于默认 ID 数，则最大可选数等于 `default_reference_asset_ids.length`；否则等于候选数。不得把 9 写成可配置事实。选中数为 0 或超过该值时，创建按钮不可用且分别显示“至少选择 1 个参考资产”或“参考资产最多选择 N 个”。
- API warnings 始终按返回顺序、黄色语义显示，message 原文不解析、不改写；用户减少候选后也不在前端伪造“warning 已消失”，正式创建后的 warning 以新 Clip response 为准。
- 所有未知/畸形本地投影事实（例如 Shot duration 非有限、Clip 引用当前快照不存在的 Shot）必须进入可见 client/protocol error；不得用默认宽度、忽略 Clip 或假媒体兜底。

### 2.3 MiniMax workflow 外部枚举修正

- 仓库 JSON 中节点 `310.inputs.lora_name` 的 JSON 字面值必须精确为 `"minimax_h3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"`，解析后的值必须精确等于当前 Comfy `/object_info` 的允许项 `minimax_h3\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`。
- 相对 T11A 开始前的 workflow，唯一允许的 JSON 语义差异是上述一个叶值；节点、连接、prompt/seed/duration/reference 路径、模型、采样参数和输出均不得变化。后端 Python、binding TOML 与迁移不得变化；既有测试只允许 `AGENTS.md` 明列四个常量的精确旧→新替换。
- 修正后必须现场计算并保存原始文件 SHA256：值须为 64 位小写十六进制且不同于修正前当前 Windows 工作区记录的 `bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780`；生产 `load_minimax_binding_snapshot()` 与重启后的 `/api/system/health` 必须逐字返回该次记录的新值。原始 bytes hash 会受 Git checkout 的 LF/CRLF 表示影响，因此不得把跨 checkout 的预计算常量当成验收真相，也不得为命中某个 hash 改写换行；hash 变化只来自完整 workflow 文件的既有计算，不新增 hash 机制。
- 当前 Windows checkout 已现场得到新 raw hash `4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772`。现有 health/binding 测试本来就以精确常量固定该 checkout 的生产工件，因此四个获授权常量必须同步为该值；不得改成运行时读取 workflow 后自证相等。该测试基线不是 T12 外部验收的替代，loader/health 仍须与 `T11A-workflow-hash.txt` 交叉核对。
- `/object_info` 是外部注册值的现场真相，但单独只能证明输入枚举匹配，不能证明 workflow 可执行或视频有效；T12 必须继续用生产浏览器、任务、Comfy `/prompt`/queue/history 与 MP4 闭环证明执行成功。

## 3. 一带两轨一板

### 3.1 共享轨道投影

1. Shot canonical 顺序生成一个共享 grid column 列表，每列权重精确等于该 Shot 的 `duration_est`；场景带、分镜轨、Clip 轨不得各算一份像素宽度。
2. 每个 Shot 的场景分类由当前 Asset 列表过滤其 `asset_ids` 得到：0 个 scene=`unbound`；1 个=`scene(scene_id)`；大于等于 2=`multiple(scene_ids)`。相邻且分类 key 相同的 Shot 合为场景段；scene 段以稳定 palette 着色并显示场景名，unbound 为灰段并显示“未绑定场景”，multiple 为警示段并显示“多个场景”。颜色不能是唯一信息。
3. Shot 块显示 `order_index`、`shot_type`、`duration_est` 秒；`status=changed` 另有文字角标。只有 Shot 块提供新 Clip checkbox。
4. Clip 色条从其首个到末个 `shot_id` 横跨共享列；显示 Clip id、generation state 文字和状态色。`freshness=stale` 以独立文字/角标叠加，不能替换 generation state。
5. 未被任何 Clip 覆盖的相邻 Shot 合为虚线空洞，空洞不阻止其他选择或生成。Clip 数据出现重叠、未知 shot 或非连续跨度时显示协议错误，不在前端修剪。

### 3.2 选择语义

- 已属于 Clip 的 Shot checkbox 不可用于创建，且指出已占用；用户通过 Clip 色条选择已有 Clip。
- `multiple` Shot 始终不可勾选，并提示先到分镜页修正。
- 当前选择尚无单场景身份时，任一未占用的 `unbound` 或单场景 Shot 可勾选；一旦选择包含唯一 scene S，不同 scene 的 Shot 置灰不可选，`unbound` 仍可选。已选 Shot 永远可取消。
- 前端不自动补齐中间 Shot、不自动排序用户选择、不因时长或不连续而静默改选。用户可形成非连续选择并由 preview 显示 R5 violation。
- 任一 Shot 勾选变化立即清除 preview 响应、候选选择、创建草稿和旧错误；不能把旧 preview 用于新选择。

## 4. 预检与创建交互

1. 未选择 Shot 时预检按钮不可用并显示“请先选择分镜”。发起后只锁定该按钮的在途状态，不乐观创建。
2. preview HTTP 200 无论是否含 violations 都进入预检面板。面板逐项显示服务端 message、`duration_est_total` 与 `suggested_requested_duration` 的映射、候选的名称/类型/首次出现位置和默认勾选。
3. violations 非空、引用选择为空/超本次上限、requested duration 不是十进制整数或创建请求在途时，创建按钮不可用；warnings 只提示，不阻止。
4. 用户只能勾选 preview 返回的候选；勾选/取消不改变候选行顺序。候选 overflow 时所有候选仍可见，默认 ID 已是合法子集，用户可用等量替换但不能选超上限。
5. create 必须提交当前 preview 的 canonical `shot_ids` 与候选顺序过滤出的 IDs。成功 201 后以返回 Clip id 作为待选目标，但仍须等最新 clips REST 落地后才呈现创建成功。
6. create 返回 422 表示 preview 后规则/输入重新裁决失败；保持当前预检面板并显示 `detail.message`。404/409/500/transport/protocol error 同样不清空用户输入，不自动重发。

## 5. 片段详情、槽位、生成与 take

### 5.1 详情设置与删除

- 选中 Clip 时 `user_note` 与 `requested_duration` 草稿从该次 Clip REST 初始化；切换 Clip 会废弃旧详情请求与草稿。
- note 控件必须让“未填写(null)”与“空字符串”可区分：显示当前语义，编辑 textarea 产生 string，显式“清空为未填写”产生 null；该动作只改草稿，直至保存或生成成功刷新。
- 同一 Clip 的 Task event 或其他 refresh 不得覆盖 dirty 草稿：REST 更新 base Clip 后，未 dirty 字段取新服务端值，dirty 字段保留精确本地值并相对新 base 重算；只有切换 Clip、确认其已删除，或本次 save/generate 成功且最新 refresh 落地时才整体重置对应草稿。
- “保存设置”只 PATCH 实际变化字段；两个字段同时变化时在同一个 PATCH 中提交。成功后必须刷新 Clip，再以服务端值重置草稿。requested duration 未保存时生成按钮不可用；note 草稿可在生成时作为显式 `user_note` 提交，202 后再以服务端 Clip 值重置。
- 删除 Clip 前调用 `window.confirm`。204 后刷新 shots/clips；选中项只在最新快照确认 Clip 不存在后清空。用户取消确认时零 HTTP 请求。

### 5.2 槽位与 R9/R12

- Slot 行固定按 `slot_no`，显示 `asset_name_snapshot`、`asset_type_snapshot`、enabled、来源文字与 `image_url` 媒体；前端不压实号、不跟随当前资产改名重命名快照。
- enabled checkbox 每次只提交一个 Slot。上传 input 的 accept 只提示 png/jpg/webp，真实大小/MIME/内容仍由后端 422 裁决。清除 override 需确认，且只提交正式 `clear_override=true`。
- 每次 Slot mutation 成功后刷新 Clip 与 slots，以服务端 revision/freshness/enabled count/warnings/image source 为准；失败不更改本地业务值。
- R12 已删资产无 override 时同时显示快照名、“原资产已删除”、缺图、停用和上传 override；不得自动执行任何处置。用户仍点击生成时，由 C009 以 202 immediate-failed Task 表达 R10，不在前端改写为同步 422/409。

### 5.3 生成与任务反馈

- 生成只在 Clip 已选、详情已加载、requested duration 无未保存草稿且该次 POST 不在途时可点击。note 未变时省略字段，note 草稿实际变化时原值显式提交；不得 trim、把空串/null混同或先乐观保存。不得因 `generation_state=queued|generating` 永久禁用；C009 允许多次抽取视频。
- 202 后记录 task_id 并触发最新快照；显示“任务已提交”而非“视频已生成”。相关 Task status/progress/message 通过 WS 与 Task detail 显示。
- 任何 terminal event 都先取 Task detail，再刷新 Clip/slots/videos；failed 显示完整 `error_msg`。done 只有在最新 REST 已含相应状态/take 后才能显示完成提示。
- C010 不增加 cancel 控件；任务取消与历史/过滤属于 C011 任务中心。若其他页面/客户端取消，Director 只消费 canceled event并刷新，不把 canceled 当 ready/failed。

### 5.4 take 画廊

- take 列表按 API `id ASC` 原顺序。每项显示 current 文字、requested duration、`actual_duration`（null 明示“未探测”）、seed string、created_at 和视频 controls。
- 设 current 只对非 current 项可用；成功后等最新 videos REST 落地再显示成功。current 删除按钮禁用并说明“当前 take 不能删除”；non-current 删除确认后调用 204 API。
- 媒体加载失败是可见播放错误，不删除 take、不切 current、不改 URL。可选 DEBUG 字段只读展示，不提供编辑/复制回任务的 mutation。

## 6. WS/REST 同步与并发状态

C010 遵守 D-008，不新增 polling：

1. 初始或重连时创建 `/ws/tasks`，在 `open` 后记录当前页面事件代次并缓冲消息，再启动页面 REST 快照。快照应用后按到达顺序处理缓冲事件。
2. 初始快照失败时关闭该 socket、显示错误；既有重连节奏到下一连接后重新执行“socket-first → snapshot → buffered events”。不得在失败 socket 上继续应用事件。
3. 对每个未识别的 `gen_clip_video` task_id 至多存在一个 Task detail GET；detail 表明 target Clip 属于当前 episode 时，事件使页面 Clip 快照及当前选中 Clip 详情失效。其他 task type/episode 不触发 Director 数据 mutation。
4. 每个页面快照和 Clip 详情快照都有单调 request generation；响应只有在 generation 仍是最新且 route/selected clip 未变化时可应用。丢弃旧响应后不得遗留永久 loading/refreshing。
5. 若 WS 在 initial、mutation、terminal refresh 在途期间到达相关事件，当前 response generation 失效；在途结束后必须发起并绑定到最新 generation 的 REST，直到最新结果应用或最新错误可见。同一 Clip 的 refresh 按 §5.1 合并 dirty 草稿，不能借“权威刷新”静默丢用户未提交输入。
6. mutation 成功通知与 terminal done 通知绑定到所触发的 refresh generation；更新事件导致 replacement refresh 时，旧 generation 的通知不能提前出现，且 terminal task 去重不能阻止 replacement refresh。
7. socket message 解析失败、Task detail 失败或 refresh 失败均可见；不得吞掉、降级成旧状态、自动重放 mutation或启动定时轮询。

## 7. UI 状态转换

| 触发 | 页面/面板状态 | 可观察要求 |
|---|---|---|
| Director 初次进入或 WS 重连 | `connecting → snapshot-loading → ready/error` | socket-first；ready 前不显示旧业务真相，error 可见 |
| Shot 选择变化 | `selection-changed` | 旧 preview/candidates/create draft 立即清空 |
| 点击预检 | `previewing → preview-ready/error` | 200 violations 属 ready；非 2xx/transport 属 error且选择保留 |
| 点击创建 | `creating → refreshing → ready/error` | 无乐观 Clip；最新 refresh 落地后才选中新 Clip/提示成功 |
| 切换 Clip | `detail-loading → detail-ready/error` | 旧 Clip 的 slots/videos/draft 不得闪回覆盖 |
| 保存/slot/take/delete mutation | `mutating → refreshing → ready/error` | 控件局部禁用；API/refresh 任一步失败可见且不伪成功 |
| generate 返回 202 | `submitting → task-observed` | 只显示已提交；Clip 两维状态来自 REST |
| Task event queued/running | `event-invalidated → refreshing` | 可显示 Task progress；Clip generation state 仍以 REST 为准 |
| Task event done/failed/canceled | `terminal-detail → refreshing → ready/error` | failed 完整原因；done take 可见后才提示完成；canceled 不伪装结果 |
| 选中 Clip 被删除/不再属于本 episode | `refreshing → no-selection` | 清空详情，轨道显示最新空洞，不保留幽灵 Clip |

前端不直接写 `generation_state`、`freshness`、revision、Shot.status 或 take current；这些均为 API 权威投影。

## 8. 错误体与 409/422 语义

C010 不改变错误状态码，只完整消费：

| HTTP / 通路 | Director 行为 | 不得做 |
|---|---|---|
| preview 200 + `violations` | 在预检面板逐项显示，阻止当前 create | 当成请求失败 toast、隐藏违规或仍提交旧 preview |
| 404 / `not_found` | 逐字显示 `detail.message`；刷新权威列表，资源确已消失时清空选中项 | 改写成 409/422、保留幽灵资源或自动创建替代项 |
| 409 / `conflict` | 逐字显示：包括零 enabled、保留 generation_mode、current take 禁删及其他前置/冲突；随后刷新 | 将生成 409 伪装为 failed Task、自动启用槽位/切 mode/切 current |
| 422 / `validation_error` | 逐字显示输入/业务校验失败：create 重裁决、duration、reference、slot upload、跨 Clip video 等 | 当成冲突 409、静默修剪数组/文件或用 200 包装 |
| 202 immediate-failed Task | 先显示已提交，再通过 Task detail 显示完整 `error_msg` 并刷新 Clip | 当成同步 422/409，或只显示“生成失败”丢失原因 |
| 500 / `internal_error` | 逐字显示服务端 message，保留待同步/错误态 | fallback 到旧数据、假成功、自动重试 |
| network / protocol / media error | 显示实际 client error 或媒体错误，允许用户显式重试读取/操作 | 吞异常、无限重连 mutation、构造假 JSON/媒体 |

所有 action error 使用现有 `ApiError`/`ApiErrorMessage` 语义；可以附带 code，但 `detail.message` 必须原文可见。成功通知不能覆盖尚未解决的最新错误。

## 9. 验收装置与证明范围

1. T1 先安装并锁定成熟的前端单元测试 runner，只用于 C010 的 TypeScript 纯投影与 Director 专用同步协调器测试。测试直接导入生产模块，以 deferred Promise/fake TaskEvent 控制顺序；网络、WS 与 storage 为注入替身。它能证明同一生产状态算法在指定事件顺序下丢弃旧响应、补发 refresh、保留错误和控制通知，不能证明真实 Vite proxy、浏览器 WebSocket、PostgreSQL、布局或媒体播放。
2. 当前没有手工创建 Shot 的正式 API，而 C010 必须稳定构造零场景、双场景、非连续、changed 与 >9 候选。T10A 因此先在 `.work/c010/` 交付一次性确定性 fixture driver：project/style/episode/assets、图片、初始 Clip 与 changed mutation 仍用正式 API；只对没有公开创建入口的 Shot/ShotAsset 使用生产 SQLAlchemy model/session 写入同一全新 PostgreSQL。脚本不得写前端状态、伪造 Task/take、修改 production module 或被提交。它与生产共享数据库 schema/storage，但绕过上游 `gen_shots`；只能证明 Director 对这些既有 Shot 事实的读取与后续正式 API mutation，不能证明 M2 生成分镜或直写夹具本身的输入校验。
3. 真实视频验收继续使用 C009 的生产 worker、正式 vLLM/Comfy、经 T11A 单叶修正的正式 workflow、正式 template、PostgreSQL、Task REST/WS 和正式 MP4 媒体通路，没有 C010 专用代理或 fake。它能证明浏览器按钮到可播放 take 和 stale 竞态的完整链路；画面审美、长期一致性和模型确定性不适合自动断言，只人工记录“可播放、有视频流、actual_duration>0、画面非空”及现场截图/日志。
4. CSS 视觉像素与响应式不新增稳定自动测试：当前仓库没有浏览器 E2E runner，且 C011/C012 分别负责全局响应式视觉与完整 E2E。替代验收为固定数据下的真实浏览器 DOM/截图、三个轨道共享列的 computed style/边界对齐、文本/按钮状态和生产 API transcript；纯投影仍由自动测试覆盖，不以“无追溯行”跳过。
5. 除 T10A 的单一一次性 fixture driver 外，本 change 不自建 demo、长期验收 endpoint、第二数据存储或仓库脚本。T11/T12 的页面读取、preview/create、PATCH/DELETE、Task/WS、vLLM/Comfy 与媒体仍走生产通路；T11A 的 `/object_info` 也读取 T12 使用的同一 Comfy 进程，生产 loader 读取生产 workflow 文件，二者没有替代存储或代理。该预检能证明当前枚举与静态 binding/hash 匹配，不能证明 `/prompt` 接受、执行完成或 MP4 有效，后者必须由 T12 证明。依赖 fixture 的证据不得扩张为“上游生成也已验收”。审查阶段若按授权另建 `.work/c010/probe-*.py`，必须说明代理/延迟差异，且不能替代生产浏览器和真实视频证据。

## 10. 验收标准

每条均包含触发条件、观测点和唯一可判定期望；风险标签用于定向复审。

| ID | 风险 | 触发条件 | 观测点 | 期望值 |
|---|---|---|---|---|
| AC-01 | [常规] | 对 baseline..C010 HEAD 做文件、OpenAPI、migration、围栏与依赖审计 | git diff、`backend/`、Alembic、package lock、路由 | 业务 diff 只含 Director 前端、C010 新前端测试/runner、节点 310 的单叶 workflow 修正、四个既有测试的单一 hash 常量同步、change/追溯/NOTES；后端 Python、binding TOML、migration、其余既有测试以及 `openspec/archive/C009/` 相对 C010 执行 baseline 均无改动；无范围外围栏能力、retry/fallback/polling/版本化；Director 空态被真实页面替换 |
| AC-02 | [外部输入] | 分别让 assets/shots/clips 初始 REST 成功、结构化 404/422/500、非 JSON 和连接失败 | Director loading/ready/error DOM、请求 URL、控制台 | 只访问同源 `/api`；三源都成功才 ready；空 shots 显示明确空态；任一失败显示实际 message且不伪造空数据、不自动重试 mutation、不硬编码端口 |
| AC-03 | [常规] | 用相邻同场景、零场景、不同场景、双场景与 duration 1/2/5 的 Shot fixture 加载页面 | 场景带段数/标签、三轨 grid columns、Shot 文本/changed 角标 | 相邻同 classification 合段；scene/灰/警示均有文字；三轨共享精确 `1fr 2fr 5fr...` 权重并对齐；Shot 显示 order/type/duration，changed 独立可见，颜色不是唯一信息 |
| AC-04 | [外部输入] | 依次勾选未占用的单场景 S、零场景、不同场景 T、双场景、已占用与非连续 Shot，并再取消 | checkbox disabled/reason、selection IDs、preview 请求 | S 与零场景可同时选；T/双场景/已占用不可新选且原因可见；已选可取消；非连续选择不被自动补齐并原样发 preview；任一选择变化使旧 preview/candidates/draft 消失 |
| AC-05 | [常规] | 加载含 empty/queued/generating/ready/failed、fresh/stale 的多个 Clip 和两段未覆盖 Shot | Clip 色条 DOM/跨度/文字、空洞 | 每个 Clip 精确横跨其 shot_ids；五种 generation state 有独立文字/状态 class，stale 同时以另一角标呈现；连续未覆盖区为虚线空洞且不阻断选择；无音频轨控件/占位 |
| AC-06 | [外部输入] | 对合法、跳号、已占用、跨场景、双场景、超时长和无候选选择调用 preview | 请求 body、预检面板、API transcript、数据库计数 | body 精确只有当前 shot_ids；所有正常规则结果为 200面板且逐项原文显示 violations/warnings/时长/候选；有 violation 时 create disabled；预检零写入；非 2xx 保留选择且显示 message |
| AC-07 | [外部输入] | preview 返回按出场排序的候选、overflow 默认子集和 soft warning；用户取消/等量替换/尝试多选后 create | 候选 DOM 顺序、checkbox、create body、创建后轨道/详情 | 顺序与响应逐项一致；默认 IDs 精确勾选；最多只能保持响应推导的 N 项，全部候选仍可见；API warning 黄色原文且不阻止；create body 保持候选顺序；201 后最新快照含新 Clip、选择清空并自动选中新 Clip；重裁决 422 不伪成功 |
| AC-08 | [外部输入] | 对选中 Clip 修改 note、请求时长（合法整数/非整数/API 越界）、no-op 保存、只改 note 后生成、取消/确认删除，并让 WS/失败 refresh 发生在 dirty 期间 | PATCH/generate/DELETE 次数与 body、base/草稿、Clip revision/state、错误/成功提示 | no-op 零 PATCH；多个变化一个 PATCH且仅含变化字段；非整数不提交、API 越界 422 message 可见；仅 duration dirty 时 generate disabled；只改 note 可生成并原值进入 `user_note`；同 Clip refresh 更新 base但不丢 dirty值，失败不清草稿；取消删除零请求，204+最新列表确认后 Clip 消失/详情清空 |
| AC-09 | [外部输入] | 对正常、无 current、override、disabled 的 Slot 切换 enabled，上传合法/非法图片，清除/取消清除 | Slot 顺序/媒体/source、multipart/JSON、Clip 两维/warnings、错误 | slot_no 不变；override > current > null 的 API结果原样显示；JSON/FormData 精确且不手写 multipart header；成功后以 REST 更新 enabled/revision/stale/warning，失败无乐观变化且 message 可见；不读取内部 path/hash |
| AC-10 | [外部输入] | 创建后删除一个被 Slot 引用的资产，分别保留/不保留 override，再回到/刷新 Director并尝试生成 | Slot DOM、可用动作、Task detail、Clip | 快照名和“原资产已删除”精确可见；有 override 仍显示图；无图同时提供停用/上传且不自动处置；若仍 enabled 后生成，HTTP 202 对应 Task failed并显示含 R10/slot 的完整原因，不改写成同步 409/422 |
| AC-11 | [外部输入] | 列出 0/1/多 take，播放媒体，切换 current/no-op/跨 Clip 失败，删除 non-current/current，分别在 DEBUG 开/关响应下查看 | video DOM、seed 类型、PUT/DELETE、current 数、调试区、错误 | 顺序 id ASC；seed 按 string 原文、duration/null 文案准确；媒体 URL 只取 `/media`; 切换后精确一 current；current 删除控件禁用且不请求，non-current 确认后 204消失；跨 Clip 422直显；DEBUG 字段有才展示、无则无空占位 |
| AC-12 | [外部输入] | 分别在 note 未变/改为普通 string/空串/null 时生成并连续两次有意点击，再得到 queued→running→done、202 immediate failed、同步 409 和 transport error | POST 次数/body/task_id、Task/Clip/note/take/提示 | note 未变 body `{}`，实际草稿精确显式提交且不 trim/混同，均无 request_id；每次在途只一 POST，首个 202 后可再次创建独立 Task；只提示已提交，done 且最新 take 可见后才提示完成；immediate failed保留 note mutation并显示完整 error_msg；409/transport直显且无假 Task/take；Clip 两维只取 REST |
| AC-13 | [并发] | 用 deferred REST 在 initial snapshot 期间送入相关 WS 事件；再制造 initial 失败、socket 关闭和重连 | 事件 buffer、request generations、应用次数、loading/error、REST calls | socket open 先于 snapshot；旧 snapshot 零应用；事件顺序保留并触发最新 snapshot；失败 socket 关闭且错误可见；重连重复 socket-first 流程；最终只应用最新数据且不遗留 refreshing、不启动 polling |
| AC-14 | [并发] | 在 create/save/slot/current/delete/generate 或 terminal refresh 在途时送入更新事件，在 dirty 期间刷新，并在途中切换 selected Clip | 页面/详情 generation、base/草稿、replacement REST、成功通知、task detail GET | 每个未知 task 同时至多一条 detail GET；旧页面/旧 Clip 响应零应用；事件使在途 refresh 失效并精确补发最新 refresh；同 Clip dirty 精确保留且重算，切 Clip 才废弃；成功/terminal通知晚于最新快照；task去重不吞 replacement；最新失败可见 |
| AC-15 | [跨进程] | 在 T10A 已披露的确定性 Shot 前置数据上，以全新 PostgreSQL、生产 FastAPI/Vite/WS 与正式 vLLM/Comfy，从浏览器勾 3 个连续同场景 Shot→preview→create→生成两次→播放/切 current | fixture 边界、浏览器 DOM、HTTP/WS、Task、DB、Comfy queue/history、MP4/media、截图/log | fixture 只建立无公开创建入口的前置事实且不伪造 Task/take；其后槽位按正式候选出场顺序；状态可观察 queued/generating/ready且 freshness 独立；两次生成形成两个不同 seed string 的 take，首个 current、切换后精确一 current；媒体可播放、有 video stream、actual_duration>0；被验收操作期间无直接 DB/文件写入 |
| AC-16 | [跨进程] | 在生产浏览器/API通路验证跨场景置灰、双场景不可选、>9 精简、建片后改绑定破坏同场景并生成、运行中编辑 Shot、删除引用资产 | UI/API/Task error、Clip/Shot/Slot终态、WS/REST顺序 | 跨场景/双场景在 UI 有确定原因且 API正式违规仍按既有合同；>9 所有候选可见但最多合法 N项；破坏绑定后任务202→failed并显示 R5a原因；运行中编辑后 take仍保存但 Clip保持 stale/Shot changed；删除资产显示快照并要求处置 |
| AC-17 | [常规] | 执行 C010 定向测试、完整前端测试/build、完整 pytest、Alembic current/check、范围/追溯/完成报告审计 | 原始命令输出、TRACEABILITY、`.work/c010/completion-report.md`、git | 所有新增测试先有追溯行并回填真实 ID；完整 frontend/backend 通过，Alembic唯一 head且 no new operations；后端 Python 与 migration 零修改，workflow 只含 AC-18 单叶修正，既有测试只含 `AGENTS.md` 明列四个常量的精确旧→新替换；完成报告逐项“操作 → 观测值”覆盖 AC-01..16、AC-18 与异常分支，未验证项不宣称完成；NOTES/DECISIONS/checkbox/commit一致 |
| AC-18 | [外部输入] | 当前 Comfy `/object_info` 将带目录前缀的 LoRA 名列为允许项后，完成 T11A 并以新数据库、新 DATA_DIR、新 Task 重跑 T12 | T11A 原始 `/object_info`、workflow 与四个测试常量的精确 diff/raw SHA256、生产 binding loader、定向/完整 pytest、重启后 health、T12 `/prompt`/queue/history/Task | 节点 `310.inputs.lora_name` 解析值精确为 `minimax_h3\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` 且存在于现场允许列表；相对 T11A 前 workflow 仅该叶变化；现场 raw hash 与四个获授权常量均精确为 `4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772`，loader/health 均逐字等于该次记录值，七个原失败用例及完整 pytest 通过；旧 failed Task 保持原终态且未重试，新 Task 的 Comfy `/prompt` 返回 200并在 history 以其 prompt_id 可定位；无运行时猜测、别名、fallback、retry、为命中 hash 改换行、动态 expected 或其他测试修改 |

## 11. 追溯覆盖

| 验收标准 | `openspec/TRACEABILITY.md` 准确行或替代验收 |
|---|---|
| AC-03、AC-04、AC-05 | `C010 导演台轨道投影与选择：场景带、duration 比例分镜轨、片段轨、空洞、changed 与两维状态，零场景可加入任意单场景、双场景不可选` |
| AC-06、AC-07 | `C010 预检与创建交互：服务端 violations/warnings、候选原序/default、响应推导硬上限、软提示与创建后权威刷新`；后端最终裁决继续由 R5、R5a、R6、R7、R8 既有行覆盖 |
| AC-08 | `C010 片段详情输入与删除：note/duration 草稿保存、requested-duration 生成门槛、note 随生成提交、204 后权威刷新与失败保真`；删除持久化合同沿用 `§3.3 删除片段：其分镜释放、片段删除、视频移入 trash` |
| AC-09、AC-10 | `C010 槽位与 R12 处置：固定 slot、enabled、override、R9 media、soft warning、已删资产快照与用户显式处置`；后端继续由 R8、R9、R10、R12 与 C008 槽位行覆盖 |
| AC-11、AC-12 | `C010 take 与生成交互：多任务提交、完整失败原因、take 画廊/current/delete/media/DEBUG 与两维状态刷新`；后端继续由 C009 generation/take 行覆盖 |
| AC-13、AC-14 | `C010 Director REST/WS 竞态：socket-first 缓冲、旧响应失效、replacement refresh、task detail 去重与成功通知后置` |
| AC-02、AC-06 至 AC-12 的错误与同源部分 | `C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功` |
| AC-15、AC-16 | `C010 M4 生产浏览器闭环：真实 API/WS/PostgreSQL/vLLM/Comfy 下创建、生成、take、stale 与 R5a/R10/R12 异常路径` |
| AC-01、AC-17 | `C010 范围、零 migration、构建回归与完成证据` |
| AC-18 | `C010 MiniMax workflow 外部枚举绑定：节点 310 LoRA 注册名与当前 Comfy object_info 一致、hash 更新且无路径猜测或 fallback` |

AC-01/AC-17 的范围、文档、Alembic 与完成报告不适合新增单一运行时自动测试；替代验收固定为 git diff/range、OpenAPI 与围栏扫描、`alembic current/check`、完整 pytest、前端 test/build 和人工逐项核对。AC-18 的关键允许列表来自当前外部 Comfy 进程，固定 mock 会把会漂移的外部状态伪装成仓库事实；因此不新增测试，只按 `AGENTS.md` 窄例外同步四个既有精确 hash 常量，并以这些既有用例、同一生产 Comfy 的原始 `/object_info`、生产 binding loader/raw hash、重启后 health 以及 T12 新 Task 的真实 `/prompt`/history/MP4 联合验收。AC-03/04/13/14 的可确定投影与竞态必须有前端自动测试；AC-02/05-12 的实际控件/DOM、AC-15/16 的生产链路按 §9 的理由采用真实浏览器证据，不以“追溯表无行”跳过。
