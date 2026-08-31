# C007 M3 资产出图 Spec

## 目标与边界

### 目标

C007 交付 ROADMAP 中的 M3 资产出图纵向闭环：应用启动时加载并校验 Z-Image API 工作流绑定，公开真实 vLLM/Comfy/工作流诊断；`gen_asset_image` 按 R4 构建或复用中间提示词，严格执行 vLLM wake/sleep 与 Comfy `/free` 的同卡分时，保存生成图片版本，并在资产页完成意见输入、抽卡、版本画廊和调试提示词展示。

### 范围内

1. 仅 Z-Image 的 API 格式 workflow、`prompt_path`、`seed_path`、`output_node`、启动校验和 workflow hash；不提前加入 MiniMax 绑定。
2. `GET /api/system/health` 的真实 vLLM/Comfy 健康与 Z-Image 绑定诊断，以及设置页诊断面板。
3. `POST /api/assets/{asset_id}/generate-image`、`gen_asset_image` 三键 payload、R4 `input_hash`、可选 `request_id` 幂等和同资产多任务抽卡。
4. 唯一 `zimage` 模板按 `asset.type` 明确分为人物四视图与单张场景环境图两条语义分支，统一使用 1344×1024 workflow；模板渲染、封闭 `{prompt}` guided_json、缓存命中只复用 prompt、每个新任务使用独立 seed。
5. vLLM `wake_up`/`sleep?level=1`、Comfy `/prompt`/WS/`history`/`view`/`interrupt`/`free`，以及任务进度转发。
6. 生成 PNG 的临时文件、解码校验、sha256、原子改名、`AssetImage` 落库、首个可安全选用版本自动 current、同步文件补偿和 task 终态一致性。
7. R11：默认图片列表不返回中间提示词；`DEBUG_PROMPTS=true` 时在既有图片列表项中额外返回并展示 `built_prompt` 与 `input_snapshot`。

### 范围外

- C008 的 clip preview/创建、参考资产选择、槽位/override/R5-R9/R12。
- C009 的 `gen_clip_video`、MiniMax H3、duration/ref 注入、视频 take、`actual_duration`、R10。
- C010 导演台、C011 任务中心 UI 专题、C012 发布级全链路总验收。
- PRD §0 围栏中的候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格/模板版本化、独立 `generation_runs`、continuity、context loop、fl2v、音频。
- 自动重试、第二 worker/第二事件通道、工作流注册表、运行时工作流热重载、文件完整性巡检、后台补偿任务或 Comfy 输出目录清理。

### 现状与影响

- 前置 C006 已由当前 `HEAD 58f43ba` 归档；C007 复用现有 PostgreSQL task 队列、advisory lock、heartbeat、条件终态、WS、vLLM structured client、资产 CRUD/画廊、媒体 ID 路径和 trash。
- `assets.image_prompt_cache/image_prompt_hash`、`asset_images.seed/built_prompt/input_hash/input_snapshot/user_note` 和 task type `gen_asset_image` 已存在；本 change **零 migration、零表/列/索引/枚举变化**。
- 当前 `/api/system/health` 只返回 `not_checked`；vLLM client 只有 wake/chat；没有 Comfy client、workflow 目录、`gen_asset_image` handler/API 或图片调试字段。
- 当前资产页已有上传、current 切换、删除和版本画廊；C007 只在这条可工作路径上增量加入生成能力，不另建资产页或生成历史页。
- 浏览器继续只使用 `/api`、`/media`、`/ws` 同源相对地址；`COMFY_BASE_URL` 与 `VLLM_BASE_URL` 只在后端读取，不进入 payload 或前端。

### 风险

| 风险 | 约束 |
|---|---|
| 外部 workflow 不是 API 格式或绑定漂移 | 静态校验在 worker 启动前失败；不把 UI graph 转换成猜测的 API graph |
| 同卡 vLLM/Comfy 重叠 | 复用单 worker；每次 Comfy submit 前必须完成 sleep，Comfy 结束后必须 free |
| payload 与运行时文件/配置不一致 | 入队保存完整已校验 workflow object、hash、绑定和业务输入；worker 不重读当前 workflow/实体作为执行输入 |
| 取消与成功提交竞争 | 最后安全点在最终事务前；图片、缓存和 task done 同一数据库胜方 |
| 文件系统与数据库无共同事务 | 正式文件先落位而数据库失败时同步移入 trash；补偿失败与原错误一起暴露 |
| 外部 WS/history 为不可信输入 | 按 prompt id 过滤并严格校验终态、输出节点、元数据和 PNG；不选其他节点 fallback |
| 单一模板把场景误生成人物或与 guided_json/画幅冲突 | 正式 `zimage` 内容必须按 `asset.type` 二选一执行；不得让 scene 进入人物四视图分支，不得要求裸文本或 3:2；T13 写入并逐字读回，T14 分别真实验收人物与场景 |

## 外部依赖

| 来源 | 开工或验收门槛 | 当前证据 | 缺失项与结论 |
|---|---|---|---|
| PRD §12.1：Z-Image API workflow JSON + §8 节点绑定 | C007 开工前必须有可直接放入 `/prompt.prompt` 的 API JSON，并确认 prompt/seed/output 绑定 | 原文件 `F:\ComfyUI\user\default\workflows\Z_Image_Turbo_官方工作流.json` 为 10073-byte UI graph；已保留原文件并生成 `F:\ComfyUI\user\default\workflows\Z_Image_Turbo_官方工作流_api.json`（3411 bytes，SHA-256 `e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa`）。转换文件顶层仅含节点 `3,6,7,8,9,13,16,17,18`，绑定为 `6.inputs.text`、`3.inputs.seed`、`9`；node 11 的 UI bypass 已解析为 `16→3`。它与 Comfy 成功历史 prompt `104082aa-e8d1-4a42-8343-26d5ab8cbc4a` 除合法 seed 外逐字段一致，并通过当前 `/object_info` 的 class、必填输入、引用、sampler 和 seed 范围检查 | **满足**：Luna 在 T0 重跑文件结构与绑定检查后，使用转换后的 API 文件作为 T1 输入；不得改用原 UI graph，也不得把成功历史中的临时 prompt/seed 覆盖进交付文件 |
| PRD §12.2：`zimage` 模板内容可先占位 | 正式模板不是 C007 开工门槛；T13 配置门槛为单一模板精确包含三个变量、按 `asset.type` 二选一执行 §4.1 人物/场景分支、要求封闭 JSON 输出且只描述 1344×1024；T14 验收门槛为两类资产均走真实运行通路并逐项记录可判定语义检查 | 2026-08-30 T13 已通过设置 API 写入并逐字读回 2770 字正式模板，`READBACK_MATCH=True`，占位符顺序为 `asset,style,user_note`，同一正文包含 character/scene 二选一分支、1344×1024 与唯一 `prompt` JSON 输出合同。T14 的人物 task `235/248/249` 与场景 task `250` 均经生产 PostgreSQL、vLLM、Comfy、workflow、媒体与 task/WS 通路完成，人物图片 `31/32/33`、场景图片 `34` 均为 1344×1024 PNG，场景首版自动 current；人工视觉偏差及需求方裁决已如实记录在 TRACEABILITY，不伪写为满足 | **满足**：T13 配置门槛和 T14 真实通路门槛均有证据；正式内容继续只允许一个 `zimage` key，不得回退为仅人物模板、3:2、裸文本输出或代码侧隐藏业务 prompt |
| PRD §12.3：vLLM `--enable-sleep-mode` 且 sleep/wake 可用 | C007 开工前须有一次真实 sleep(level 1)→wake 成功证据；验证时不得有正在执行的生产任务 | WSL 当前进程命令含 `--enable-sleep-mode`；`http://127.0.0.1:8001/health` 为 200；2026-08-28 验证时 running task 为 0，初始 `/is_sleeping=false`，POST `/sleep?level=1` 为 200 且随后 `/is_sleeping=true`，POST `/wake_up` 为 200 且最终 `/is_sleeping=false` | **满足**：真实往返通过，验证后 vLLM 已恢复 awake |
| PRD §12.4：Postgres DSN、Comfy/vLLM 地址端口 | 实现与验收环境均须可达；地址不得写入业务 payload | PostgreSQL `127.0.0.1:5432` 已被 C001-C006 使用；vLLM `127.0.0.1:8001` 当前健康；用户确认 Comfy 端口 8188，`127.0.0.1:8188/system_stats` 当前 200，ComfyUI `0.33.0`、RTX 4090 | 地址门槛满足；实现仍从 `DATABASE_URL`、`VLLM_BASE_URL`、`COMFY_BASE_URL` 读取，不硬编码证据地址 |
| ROADMAP 前序 C006 | C006 归档且回归通过后才能进入 C007 | Git 当前提交为 `Archive completed C006 change`；TRACEABILITY 已回填 C006 用例 | 满足 |

当前 C007 的 PRD §12 开工门槛与 §12.2 正式双分支单模板配置门槛均已满足。T20 因完成报告引用的 HTTP 原始日志不存在而重新开放，仅表示最终复验的证据链需要重做，不把已经完成的外部依赖门槛倒写为未满足；不得补写旧日志或用 mock 代替新的真实请求/响应。

## 1. 可观察行为

1. 有效启动加载唯一 Z-Image API workflow，验证绑定并计算 hash；缺文件、UI 格式、非法 JSON、路径或输出节点错误使应用在启动阶段非零失败，worker 不启动、请求不被接受。
2. vLLM 或 Comfy 暂时不可达不把静态绑定伪装成错误，也不阻止诊断 API 启动；`/system/health` 明确显示对应 `unhealthy` 原因。
3. 用户在任一资产卡填写可选意见并点击生成，API 立即返回 task id，不等待 vLLM/Comfy；同资产允许多个新 task 排队。
4. 入队时冻结资产、风格、模板、模型、温度、workflow object/hash/绑定、seed、Comfy prompt id、缓存判定和完整 R4 hash 输入。
5. 缓存未命中时，`asset.type=character` 只生成一张 1344×1024 人物四视图设定图的中间提示词，`asset.type=scene` 只生成一张 1344×1024 连续场景环境图的中间提示词；两者不得进入对方分支，用户意见不得改变资产类型、画幅、构图硬约束或 JSON 输出合同。
6. 缓存命中时不调用 vLLM chat，只复用快照中的 cached prompt 并使用本 task seed；缓存未命中时 wake vLLM、用一条 user message 和封闭 schema 构建 prompt。
7. 每次 Comfy submit 前 vLLM sleep(level 1) 必须已成功；Comfy 结束、失败或中断后必须请求 `/free`，单 worker 中不允许 LLM 与 Comfy 推理重叠。
8. Comfy WS 只接受本 task prompt id 的进度/终态；成功后只从绑定输出节点的 history 取一张 PNG，经后端临时文件和原子改名保存。
9. 成功生成新增一个 `source=generated` 图片版本。最终提交前来源 revision 未变且资产尚无 current 时，该图自动 current；否则保存为非 current，不覆盖用户在任务期间作出的编辑或 current 选择。
10. 图片行、prompt cache 更新、必要的 current/revision/下游级联和 task `done/progress=1` 同一事务提交；失败无“已 done 但缺图”或“canceled 但有图”。
11. 资产页在对应 task 终态后重新读取真实画廊；后续抽卡保留旧版本并可继续使用既有“设为当前/删除非当前版本”操作。
12. 默认 API/页面不出现 `built_prompt`/`input_snapshot`；debug 开启时既有图片列表项和画廊调试区才出现它们。

## 2. Workflow、绑定与诊断合同

### 2.1 文件与绑定

实现阶段只允许新增 C007 当前所需：

```toml
[comfy.zimage]
workflow = "workflows/zimage.json"
prompt_path = "6.inputs.text"
seed_path = "3.inputs.seed"
output_node = "9"
```

- binding 文件固定为 `backend/workflows/bindings.toml`；其中 `workflow` 相对 `backend/` 解析，生产 workflow 固定为 `backend/workflows/zimage.json`。binding 只含 `comfy.zimage`，不得预建 `minimaxh3`。
- API workflow 顶层必须是非空 object；每个顶层成员必须是节点 id → `{class_type, inputs, ...}`，`class_type` 为非空字符串且 `inputs` 为 object。出现 UI graph 的 `nodes/links` 结构必须明确失败。
- `prompt_path` 和 `seed_path` 用点分 object key 逐段解析；不支持数组索引、通配符、fallback 路径或模糊节点名。prompt 叶值必须为 string；seed 叶值必须为非 bool integer。
- `output_node` 必须是 workflow 顶层真实节点 id；运行结果只接受此节点，不扫描其他输出节点。
- workflow hash 固定为仓库 API JSON **原始文件 bytes** 的 SHA-256 小写 64 位十六进制；不再建立 canonical serializer、签名、锁文件或热重载。应用重启后才加载新的文件/hash。
- 启动时保存一个只读的已校验 Z-Image binding snapshot，供 health 和入队复制；handler 执行使用 task payload 内的副本，不重读磁盘。

### 2.2 启动顺序

静态 workflow/绑定校验必须在 task 恢复、worker 启动和 ASGI yield 前完成。校验失败记录具体文件与失败路径但不打印 workflow prompt、凭据或环境变量，并使启动失败。advisory lock 若已取得，失败退出时仍按现有 lifespan 顺序释放。

启动时对 vLLM `/health` 与 Comfy `/system_stats` 各执行一次单请求探测，不重试；外部不可达只形成明确诊断并记录日志，不绕过静态校验、不启动第二种降级模式。

### 2.3 `GET /api/system/health`

成功固定 HTTP 200；每次 GET 各执行一次当前健康探测，不自动重试，返回精确职责：

```json
{
  "vllm": {"status": "healthy", "message": null},
  "comfy": {"status": "healthy", "message": null},
  "workflow_bindings": {
    "status": "valid",
    "message": null,
    "hashes": {"zimage": "<64 lowercase hex>"}
  }
}
```

- `vllm.status` 封闭为 `healthy|unhealthy`；vLLM `/health` 任意 2xx 都返回 `healthy` 且 `message=null`，完全忽略响应体，包括空 body 与非 JSON body。vLLM 连接失败、超时、无法形成合法 HTTP 响应或非 2xx 时返回 `unhealthy` 与非空、可展示且不含凭据的说明；不存在 vLLM 畸形 JSON 分支。
- `comfy.status` 封闭为 `healthy|unhealthy`；Comfy `/system_stats` 必须为 2xx 且 body 为 JSON object 才返回 `healthy/null`，连接失败、超时、无法形成合法 HTTP 响应、非 2xx 或畸形/非 object JSON 时返回 `unhealthy` 与非空、可展示且不含凭据的说明。
- 服务能响应时 `workflow_bindings.status` 固定为 `valid`，hashes 精确只含 `zimage`；静态 invalid 通过启动失败暴露，不返回伪造的运行中 200。
- health 不执行推理、sleep/wake/free、workflow submit 或任务 mutation。

## 3. 生成 API、payload 与 R4

### 3.1 API

`POST /api/assets/{asset_id}/generate-image`

- `asset_id` 必须落在 PostgreSQL `INTEGER` 的 `-2147483648..2147483647` 范围内；超出范围在 API 边界返回结构化 422，不访问数据库或任务队列。
- 请求必须是 JSON object，允许字段仅为 `user_note`、`request_id`；`{}` 合法，缺 body、JSON `null`、数组、未知字段或错误类型为 422。
- `user_note` 为 string 或 null，省略等同 null；字符串不 trim，null 与空字符串是不同的 R4 输入。前端空白意见发送 null。
- `request_id` 为 string 或 null，沿用 D-007：去首尾空白后 1..128，保存规范化值；空白/超长为 422。
- 不接受 query、幂等 header、seed、workflow 路径、模型、温度或客户端文件路径。
- 新 task 成功为 HTTP 202，响应字段精确 `{"task_id": <positive integer>}`；task 为 `type=gen_asset_image`、`target_id=asset_id`、`status=queued`、`progress=0`。
- API 只读/锁定并快照当前数据库输入，不同步调用 health、vLLM 或 Comfy。外部服务当前 unhealthy 不改成同步 409；已返回 202 后由 task 真实失败。

### 3.2 `input_hash`

R4 输入顺序精确为：

```text
[asset.name, asset.description, asset.revision,
 style.prompt_fragment, zimage template content, user_note,
 VLLM_MODEL, workflow_hash]
```

按上述固定数组顺序序列化为 UTF-8 JSON：`ensure_ascii=false`、无缩进、分隔符 `,`/`:`、禁止 NaN；`input_hash` 为该 bytes 的 SHA-256 小写 64 位十六进制。不得加入 asset id/type、seed、温度、built prompt、当前时间、base URL、文件路径或版本前缀，也不得另建通用 canonical serialization 层。

### 3.3 task payload

顶层必须且只能为 D-006 三键：

```json
{
  "input_snapshot": {},
  "input_hash": "<64 lowercase hex>",
  "source_revisions": {"asset": {"id": 21, "revision": 3}}
}
```

`input_snapshot` 必须且只能包含：

| 字段 | 精确语义 |
|---|---|
| `asset` | `{id,project_id,type,name,description,revision}`；type 仅 `character|scene` |
| `style` | 入队时项目风格 `prompt_fragment` 原文 |
| `template_key` | 固定 `zimage` |
| `template_content` | 入队时模板正文原文 |
| `user_note` | 请求的 string 或 null |
| `rendered_prompt` | §4 由快照一次渲染的一条 user message |
| `model` | 入队时 `VLLM_MODEL` 非空字符串 |
| `temperature` | 入队时 `VLLM_TEMPERATURE` number |
| `guided_json_schema` | §4.2 完整封闭 schema object |
| `workflow` | `{name:"zimage",hash,prompt_path,seed_path,output_node,definition}`；definition 为已校验 API workflow object 的深拷贝 |
| `seed` | `[0, 2^63-1]` integer，最终写 `AssetImage.seed` |
| `comfy_prompt_id` | canonical lowercase UUID string；同一值同时作为 WS `clientId`、submit body `client_id`/`prompt_id`，并供 history/interrupt 关联 |
| `cached_prompt` | 入队时 hash 命中且 cache 非 null 时为原 cache string，否则 null |

不得放入 base URL、凭据、ORM 对象、当前时间、文件绝对路径、template/style 伪 revision、MiniMax/clip 数据或额外顶层键。

入队在一个明确事务中锁定目标 Asset、Project、Style、`zimage` PromptTemplate，并读取同一已校验 workflow snapshot 后计算 payload。资产不存在为 404；项目/风格/模板缺失、模板占位符合同不满足为 409。`image_prompt_hash` 等于本次 hash 但 `image_prompt_cache` 为 null 属于数据库内部不一致，返回结构化 500，不把它当 cache miss。

### 3.4 seed、prompt id、并发与 `request_id`

- 无 `request_id`：每个新请求独立生成一个 63-bit non-negative random seed 和 UUID4 prompt id；同资产 queued/running 数量不受 target 去重限制。
- 有 `request_id`：只使用 D-007/现有 `normalize_request_id` 得到的 `request_id.strip()` 结果；保留大小写、内部空白和其余 Unicode code points，不做 lowercase、空白折叠或 NFC/NFKC。确定性映射固定为：

  ```python
  GEN_ASSET_IMAGE_NAMESPACE = UUID("27e66eeb-4d70-597c-8f24-fb984fab13c3")
  prompt_uuid = uuid5(GEN_ASSET_IMAGE_NAMESPACE, normalized_request_id)
  comfy_prompt_id = str(prompt_uuid)
  seed = prompt_uuid.int & 0x7FFF_FFFF_FFFF_FFFF
  ```

  namespace 字面值的审计来源固定为 `uuid5(NAMESPACE_URL, "ai-drama-studio:gen_asset_image")`；运行时合同是上述 UUID 字面值，不从配置读取。`uuid5` 使用 Python 标准库语义，name 为规范化字符串的 UTF-8 bytes；`str(prompt_uuid)` 必须是 canonical lowercase hyphenated UUID。seed 取同一 UUID 整数的低 63 bits，范围含 `0` 与 `2^63-1`。不得加入 type、target、user_note、当前时间或第二次 hash，不做碰撞 registry、碰撞重试或 fallback。
- 固定测试向量：原始 `request_id=" abc "` 规范化为 `"abc"`，必须得到 `comfy_prompt_id="f0faf273-5fe9-5726-98be-3d449efdbe8d"` 与内部 `seed=1782929867419795085`。`input_hash` 仍按 §3.2 计算并排除 seed/prompt id；公开 AssetImage JSON 与 debug `input_snapshot.seed` 将该值投影为十进制字符串。
- 查到任意状态的同 request id 时，先比对 type、target 和该任务类型明确列出的客户端身份字段；`gen_asset_image` 只比较请求 `user_note` 原值，`null`、空字符串和空白字符串互不等价。一致则以既有冻结 payload 返回原 task，后续资产/风格/模板/缓存/workflow 变化不把幂等重放改成新抽卡；任一身份字段不一致为结构化 409。
- 两个不同新请求必须创建两个 task、保留各自 seed；重复同 request id 只返回一个 task 和同一 seed。

## 4. 模板、guided_json 与缓存

### 4.1 渲染与正式模板语义

`zimage` 模板必须包含三个必需变量 `{{asset}}`、`{{style}}`、`{{user_note}}`，且不得含其他未解析 `{{...}}`。缺任一必需变量或含未知变量使生成 API 返回 409。

- `{{asset}}` 注入紧凑 JSON object，字段精确 `{type,name,description}`，使用快照原文、`ensure_ascii=false`，不含 id/revision/image/path。
- `{{style}}` 注入快照 style 原文。
- `{{user_note}}` 为 string 时注入原文，为 null 时注入空字符串。
- 只替换原模板中的识别位置一次；注入文本中的 `{{...}}` 不二次解释。
- 完整结果保存为 `rendered_prompt`，并作为 vLLM 唯一 user message；共享传输层不得选择模板、添加业务 system prompt 或重写 schema。

正式内容只有一个 `zimage` 模板，不新增 `zimage_character`、`zimage_scene` 或模板版本。模板必须先读取 `{{asset}}` 注入 JSON 中的 `type`，并且只执行一个匹配分支：

- `character`：把 name/description、style 和 user_note 改写为一张 **1344×1024 横向人物四视图设定图**的 prompt。画面精确为同一角色的正面头肩近景、全身正面、全身背面、全身左侧面四栏；后三栏等高且完整显示头顶至鞋底，四栏互不重叠。角色身份、年龄、骨相、发际线、发长、体型、服装结构、污渍/湿润状态和鞋在四视图一致；不出现额外人物、重复肢体、道具、场景、文字、姓名、标志或水印。人物 prompt 正文保持需求方所给七段结构，未提供的服装/体型/脸型/妆容等只补普通中性默认值，不添加疤痕、饰品、图案、纹身等新辨识特征，正文不超过 650 个汉字。
- `scene`：把 name/description、style 和 user_note 改写为一张 **1344×1024 横向单幅场景环境设定图**的 prompt。画面必须是一个连续、统一的空间，明确观察位置与方向、镜头高度、前景/中景/背景、空间布局与通行关系、建筑或地貌、家具/设施/环境物件、时间、天气、光照、主要材质和项目风格；透视、比例、遮挡和纵深关系一致。画面不得出现可辨识人物，不得成为多格拼图、人物四视图、分镜板、平面图，不得出现文字、标志或水印。描述缺项只补不抢主体的普通中性默认值，不添加新地标、剧情事件或辨识性人物。
- `user_note` 只能细化已选分支的视觉内容；与资产类型、1344×1024 画幅、人物四视图/单幅场景构图或封闭 JSON 输出冲突的意见不改变这些硬约束。
- 正式模板不得再写“横向 3:2”，不得要求直接输出裸 prompt 正文。它必须明确要求 vLLM 只输出字段精确为 `prompt` 的 JSON object；`prompt` 值才是对应分支的最终正文，人物为七段、场景为四段。§4.2 guided_json 是机器硬约束，模板文字与其保持一致。

T13 写入的模板正文必须把上述分支落实为可直接执行的填写说明，并且在正文末尾各出现一次且仅一次以下输入位：

```text
资产：{{asset}}
风格：{{style}}
用户补充：{{user_note}}
```

模板本身不硬编码具体角色或场景，不内置临时测试输入。人物分支可保留需求方提供的林晚示例作为填写示例，但示例必须标明它只是 `prompt` 字段值，不能再次要求裸文本响应；场景分支无需伪造固定示例。正式内容经设置 API 即时生效，变更后因模板正文参与 R4 hash，下一新请求必须 cache miss，不追溯既有图片。

### 4.2 vLLM schema

请求使用快照 model/temperature，schema name 固定 `zimage`，schema 精确：

```json
{
  "type": "object",
  "properties": {"prompt": {"type": "string"}},
  "required": ["prompt"],
  "additionalProperties": false
}
```

响应必须是且只是一项 `prompt` 的 object，prompt 至少含一个非空白字符。非法 HTTP/JSON/schema、额外字段、空白 prompt 或解释/围栏均使 task failed，不退回自由文本或模板拼接结果。

### 4.3 R4 分支

- `cached_prompt` 非 null：不得 wake 或调用 chat；`built_prompt=cached_prompt`。
- `cached_prompt` 为 null：在外部调用前检查取消，调用 wake，再以 §4.1/§4.2 构建 `built_prompt`；chat 之后再次检查取消。
- 两个分支都必须把完整 `built_prompt` 与 `input_hash` 写结构化日志，最终图片行始终保存它们。
- cache miss 生成的 prompt 只在最终成功事务中写 `assets.image_prompt_cache/image_prompt_hash`；Comfy 或文件失败不得只留下新 cache。cache hit 不重写 cache。
- 风格、模板、资产 name/description/revision、user_note、model 或 workflow hash 任一变化导致下一新请求 hash 不同和 cache miss；seed 变化不影响 hash。

## 5. GPU、Comfy、取消和文件/事务

### 5.1 固定顺序

handler 只注册到现有 TaskQueue，固定执行：

1. 取消安全点；按 §4 命中或构建 built prompt。
2. 取消安全点；`POST {VLLM_BASE_URL}/sleep?level=1` 成功返回。
3. 深拷贝 payload workflow，仅把 `prompt_path` 叶值替换为 built prompt、`seed_path` 替换为 seed；payload 本身不变。
4. 先连接 `ws://.../ws?clientId=<input_snapshot.comfy_prompt_id>`，再 POST `/prompt`；body 的 `client_id`、`prompt_id` 都精确等于该值，`prompt` 为注入后的 workflow；记录返回 prompt id，必须与请求 id 一致。
5. 转发匹配 prompt id 的进度，等待明确 success/error/interrupted；success 后 GET `/history/{prompt_id}`，只取绑定输出节点的一张图，再 GET `/view` 流式写入 backend 临时文件，并解码校验 PNG、计算 sha256。
6. 包住第 4-5 项的 Comfy 资源作用域无论成功、错误或中断都在 `finally` POST `/free`，body 精确 `{"unload_models":true,"free_memory":true}`；不重试。只有 free 成功且无主错误才离开该作用域。
7. Comfy/free 结束后执行取消安全点，再执行 §5.4 最终提交。

sleep 未成功时不得 submit Comfy。cache miss 的 wake/chat 完成后才 sleep；cache hit 虽不调用 LLM，仍必须在 submit 前 sleep。Comfy free 必须在任何图片/cache/done 数据库提交之前完成；free 失败时任务仍为 running，由统一失败路径置 failed。若同时已有主错误，`error_msg`/日志必须同时含主错误和 free 错误。

### 5.2 WS、history 与进度

- 只处理 text JSON；binary preview 明确忽略。`status/executed/execution_cached` 可用于诊断但不决定成功。
- `progress` 必须匹配 prompt id，`value/max` 为合法 number 且 `max>0`；映射到 task 总进度区间 `[0.25,0.90]`，保持非递减并经现有 task WS 发布。
- 匹配的 `executing` 至少把进度推进到 `0.25`；不得把 node 消息直接当成功。
- `execution_error` 使用 node/type/exception message 形成完整失败；`execution_interrupted` 仅在数据库已有取消意图时走 canceled，否则是 task failure；`execution_success` 后仍须由 history/output 校验裁决。
- 不重连、不切换到轮询、不选择其他 prompt/output node。连接断开、畸形关联消息、history 缺项或状态不成功均明确失败。

### 5.3 输出约束

history 的绑定输出节点必须存在 `images` array 且长度精确为 1；该项的 `filename`、`type` 必须为非空字符串，`subfolder` 必须为字符串且允许合法空字符串，并将三者原值用于同一 Comfy `/view`。下载结果必须能由 Pillow 完整 decode 且真实格式为 PNG；0 张、多张、非 PNG、损坏或不可读均失败，不保存占位图、不转码 fallback。

后端临时文件位于 `DATA_DIR/tmp`；正式相对路径沿用 `projects/{project_id}/assets/{asset_id}/{image_id}.png`。sha256 针对最终保存的原始 PNG bytes。

### 5.4 最终事务与完成判定

进入最终事务前执行最后取消安全点；事务中不调用外部 HTTP/WS、不等待可取消步骤。事务内：

1. 锁定 task、目标 Asset 和该资产 current 图片；确认 asset id/project id 仍匹配。
2. 在任何业务写入前比较 `source_revisions.asset.revision` 与锁定 Asset 当前 revision。
3. 插入一个 `AssetImage`：`source=generated`、payload seed、built_prompt、input_hash、完整 `input_snapshot`、user_note、sha256 和系统路径。
4. 仅当第 2 项 revision 一致且提交前没有 current 图片时，新图 `is_current=true`，Asset revision `+1`，并沿用现有 current 变化级联把绑定 Shot changed、相关 Clip stale；否则新图固定非 current，不修改 Asset revision/下游状态。
5. cache miss 时写 Asset cache/hash；cache hit 保持 cache；图片、cache、current/revision/级联和 task 条件 `done/progress=1` 同一事务提交。

Asset 在运行中被删除使 task failed 且不留正式文件/图片行。Asset 仍存在但 revision 已变化时，产物仍保存为非 current，证明快照可追溯且不覆盖用户新选择。风格/模板/workflow 在任务运行中变化不改本 task；下一新请求由新 hash 失配重建。

正式 rename 后数据库事务失败，必须在本次操作中把无人引用正式文件移入现有 trash 路径；补偿失败与数据库错误一起上报。临时文件在所有出口删除。不得后台重试、保留 pending 行、写伪成功或删除其他 task/版本文件。

### 5.5 取消与 `/interrupt`

- queued 取消沿用 C004，直接 canceled，不调 Comfy。
- running `gen_asset_image` 第一次成功提交 `cancel_requested_at` 后，cancel API 才以 payload `comfy_prompt_id` 调一次 targeted `POST /interrupt`；重复 running/canceled 取消不重复 interrupt，其他 task type 在 C007 不调 Comfy。
- `/interrupt` 是 PRD 明示的尽力副作用：网络/HTTP 失败必须带 task id/prompt id 记录 warning，但已提交的取消意图和 200 TaskResponse 不回滚、不伪称 interrupt 成功。
- handler 在外部调用前后、文件正式落位前、最终事务前检查取消；cancel 先赢时清理 temp/free 后 canceled 且无图片/cache写入，最终提交先赢时图片与 done 同一胜方，之后 cancel 为既有 409。

## 6. API 公开字段与 UI

### 6.1 图片列表与 R11

不新增 PRD 未列出的单图详情 endpoint；既有 `GET /api/assets/{asset_id}/images` 的每个列表项就是图片详情表示。

- `DEBUG_PROMPTS=false`：字段精确保持 C003 的 `id,asset_id,sha256,seed,source,is_current,created_at`；不得出现 `file_path,built_prompt,input_hash,input_snapshot,user_note`。
- `DEBUG_PROMPTS=true`：在上述字段上**只额外**出现 `built_prompt` 与 `input_snapshot`；generated 行两者非 null，uploaded 行两者为 null。仍不返回 `file_path,input_hash,user_note` 独立字段。
- 上述两种公开响应中的 `seed` 都是原始数据库整数的十进制字符串或 `null`；数据库、task payload 和 worker 内部仍使用 `[0, 2^63-1]` integer。`DEBUG_PROMPTS=true` 时 generated 行 `input_snapshot.seed` 也投影为十进制字符串或 `null`，不改变冻结 payload。
- 其他资产、项目、episode、task、health 或媒体 API 不因 debug 返回中间提示词。

### 6.2 资产页

- 每张资产卡新增一个意见 textarea 和“生成图片”按钮；空白意见发送 null。请求中只禁用该卡的重复 HTTP 提交，202 返回后立即恢复，允许用户再次点击形成新 task。
- 202 后显示真实 task id 和现有任务中心入口；同步错误保留意见并直显 `detail.message`，不自动重发。
- 页面监听现有 task WS；收到 terminal `gen_asset_image` 后通过 task GET 确认 target 属于当前列表，再重新读取该资产/画廊。断线沿用 D-008 的既有 1/2/5/10 秒观察通道重连且不重发 mutation；重连成功后对当前资产列表执行一次 GET 刷新以补断线窗口。页面重新进入时同样以 GET 真相为准，不依赖 WS 历史或假图片。
- 首次连接与每次重连都先缓冲 WS 事件，再执行 REST 快照，快照成功后按接收顺序应用缓冲事件；快照失败必须保留可见错误、关闭当前 socket 并沿用既有重连调度，下一连接重新执行同一同步流程，不永久忽略事件或丢失 terminal 更新。
- WS connect/reconnect 使旧 REST 请求失效时，旧请求不得覆盖新状态或遗留 `refreshing=true`；当前不存在有效刷新请求时 `refreshing=false`，刷新/创建按钮恢复可用。不得增加 polling、fallback 或静默吞错。
- socket 保持连接时，任何 WS 事件都可以使在途画廊 REST 快照变旧；变旧响应不得写入 entries/load state/error，但只要该刷新仍对应一次待完成的创建、切换 current、删除或 terminal 同步，就必须在最新事件 revision 上合并或补发 REST 快照，直至最新快照成功应用或最新一次失败形成可见错误。terminal task id 去重不得抑制这次补刷新；在最新快照成功前不得显示“画廊已刷新”，所有有效刷新结束后 `refreshing=false` 且按钮可用。不得以轮询、自动 mutation 重发或应用旧响应代替补刷新。
- 画廊显示 generated/uploaded、seed、current 和既有切换/删除动作；首个安全 current 立即出现在当前图，后续生成保留为可选版本。
- API 返回 debug 字段时，每个版本提供可展开的 built prompt 与格式化 input snapshot；字段不存在时不渲染空调试面板。

### 6.3 设置页

设置页初次进入并行但相互独立地读取 styles、templates、health；任一 health 组件 unhealthy 或整个 health 请求失败都不得隐藏已成功读取的风格/模板。诊断区分别显示 vLLM、Comfy、Z-Image binding 和完整 workflow hash，提供一次性“刷新诊断”按钮但无定时轮询或自动重试；组件 unhealthy 显示其 `message`，请求级失败直显 API 错误，不伪装为组件 healthy。

## 7. 状态转换与错误语义

### 7.1 task 状态

正常 `queued → running → done`；done 固定 progress=1。任一 wake/chat/sleep/Comfy/WS/history/view/PNG/文件/数据库/free 异常使仍为 running 的 task 一次进入 failed，`error_msg` 完整非空、finished_at 有值，不重试、不新建替代 task。取消和终态条件更新沿用 C004。

### 7.2 HTTP 错误矩阵

所有非 2xx 仍为 `{"detail":{"code":"<non-empty>","message":"<non-empty>"}}`。

| HTTP / code | 触发条件 | 不得替代为 |
|---|---|---|
| 404 / `not_found` | generate-image 的 asset id 不存在；既有资源不存在 | 403、409、422 |
| 409 / `conflict` | request id 已绑定不同 type/target/user_note；项目风格或 zimage 模板缺失；模板缺必需变量或有未知变量；合法请求被当前前置状态阻止 | 422、200 |
| 422 / `validation_error` | path/body JSON 类型、缺 body、null/array body、未知字段、user_note/request_id 类型、空白/超长 request id | 409 |
| 500 / `internal_error` | cache hash/cache 内容内部不一致、数据库不可达或同步 API 未预期错误；日志保留 traceback | 409、422、200 |

静态 workflow/binding 错误是启动失败，不映射 409。health 组件 unhealthy 是 HTTP 200 中的显式诊断，不是伪成功生成。已返回 202 后的全部外部/文件/事务失败只通过 task failed/error_msg 暴露，不改写原 POST 状态码。

## 8. 验收标准

每条均给出触发、观测点和期望值；风险标签用于审查定向验证。

| ID | 风险 | 触发条件 | 观测点 | 期望值 |
|---|---|---|---|---|
| AC-01 | [常规] | 对 C007 diff、Alembic current/check 与围栏关键字扫描 | git diff、migration head、表结构 | 零 migration/schema 漂移；无 C008+、围栏机制、retry/fallback/第二队列/registry |
| AC-02 | [外部输入] | 分别使用原 UI 文件、转换后的 API 文件与 vLLM/Comfy 地址执行 T0 | JSON 顶层、绑定节点、真实 HTTP 结果 | 原 UI JSON 因 `nodes/links` 被拒；转换文件只含数值节点且 `6.inputs.text`、`3.inputs.seed`、输出节点 `9` 均存在；sleep→wake 均为 200、状态为 false→true→false；Comfy 地址探测为 200，T0 解除 |
| AC-03 | [外部输入] | 分别启动有效 API workflow、缺文件、UI graph、非法 JSON、坏 prompt/seed/output path | 进程退出、日志、worker/task 状态 | 有效者启动且给出 64 hex hash；四类坏输入均在 worker 前非零失败，不 claim task、不 fallback |
| AC-04 | [外部输入] | health 分别面对 vLLM 2xx 空/非 JSON、vLLM 超时/连接失败/非 2xx，以及 Comfy 2xx 畸形 JSON/连接失败/非 2xx | `/api/system/health`、本地慢服务命中计数与设置页 | vLLM 任意 2xx 均 healthy/null 且忽略 body；连接本地随机端口慢服务时该服务至少收到一次请求且 vLLM 为 unhealthy/超时 message；其他 vLLM 传输失败或非 2xx、Comfy 畸形 JSON/传输失败均 unhealthy/非空安全 message；binding 仍 valid 且 hash 精确，无 sleep/free/submit，测试不连接生产 8001 |
| AC-05 | [常规] | 向存在/不存在资产发送 `{}`、合法意见及非法 body、越过 PostgreSQL INTEGER 上下界的 `asset_id` | API、task 行 | 合法为 202 + 精确 task_id/queued gen_asset_image；未知 404；path/body 422；上下界外在访问数据库/队列前返回结构化 422；请求线程无外部调用 |
| AC-06 | [并发] | 同资产并发两个无 request id 请求；以 `" abc "`/`"abc"` 并发及终态重放；复用 key 改 target 或 user_note | task 数、id、payload seed/prompt id、HTTP | 无 id 创建两 task且 seed/prompt id 独立；两个有 id 请求只一行并返回同 task，精确得到 prompt id `f0faf273-5fe9-5726-98be-3d449efdbe8d`、seed `1782929867419795085`，终态重放仍返回冻结 payload；改 target/note 为 409；无 target active 409 |
| AC-07 | [事务一致性] | 入队时由独立数据库连接并发编辑 Asset、Style、Template，并在入队后替换磁盘 workflow | 锁等待/提交屏障、payload、hash 复算、worker 入参 | 三个 writer 在入队事务提交前分别被对应行锁阻塞、提交后全部完成；payload 顶层/内部字段精确且来自锁定快照；hash 按固定数组一致；worker 用同一冻结副本，不重读新值 |
| AC-08 | [外部输入] | cache miss 时让 vLLM 返回合法、额外字段、空 prompt、非法 JSON/HTTP | vLLM 请求、task、Comfy调用 | 合法恰一 wake/chat、一 user message、精确 schema；非法均 failed、Comfy 0 调用、无 cache/图片，且无隐藏业务 system prompt |
| AC-09 | [常规] | 先制造稳定 cache hit，再改变 seed、意见、资产描述、风格、模板、model、workflow hash | chat 次数、input_hash、cache、日志 | hit 时 chat=0且只换 seed；仅 seed 变化 hash 不变；其余任一变化 hash 改变并 chat=1；完整 prompt/hash 入库日志 |
| AC-10 | [跨进程] | 分别执行 cache miss/hit 的成功任务及 sleep 失败 | 按时序记录的真实客户端调用、Comfy队列、task | miss 为 wake→chat→sleep→Comfy→free；hit 无 wake/chat但有 sleep→Comfy→free；sleep 失败时 Comfy 0 调用；任一时刻无两种推理重叠 |
| AC-11 | [外部输入] | WS 注入其他 prompt、合法 progress、error、断线；history 注入 0/1/2 图、错节点、非 PNG | task progress/status、文件/DB | 只匹配本 prompt；progress 非递减落 `[0.25,0.90]`；仅绑定节点恰一 PNG成功，其余明确 failed、无正式引用/占位图/其他节点 fallback |
| AC-12 | [跨进程] | queued cancel、running 首次/重复 cancel、interrupt 失败、取消与最终提交竞态 | cancel 响应、interrupt 次数、task/图片/cache/file | queued 0 interrupt；running 首次 1 次 targeted interrupt，重复 0 次；interrupt 失败有 warning但取消意图保留；竞态只有 canceled+无业务写入或 done+完整产物一种胜方 |
| AC-13 | [事务一致性] | source revision 未变/已变且分别有/无 current 完成任务 | Asset/AssetImage/Shot/Clip/task 同事务结果 | 未变且无 current 才自动 current并 revision+1/级联；其余图为非 current；所有成功均保存快照产物；图片/cache/current/done 不可部分提交 |
| AC-14 | [事务一致性] | rename 后强制数据库失败、trash 补偿失败、主错误叠加 free 失败 | DATA_DIR、trash、DB、error_msg/log | DB 无图/cache/done；正常补偿把正式文件移入 trash；补偿/free 失败与主错误同时可诊断；temp 始终删除、无后台重试 |
| AC-15 | [并发] | 浏览器连续提交两次并等 terminal，再切 current/删除非 current/刷新；延迟 REST 时触发 WS 重连；首次 REST 快照失败后恢复服务；socket 保持连接时延迟一次画廊 REST，并在等待期间经生产任务 API/EventBus 发布一条无关非终态 WS 事件 | 资产页、任务中心、媒体 URL、REST 请求序列、WS 事件、按钮/提示、API真相 | 两 task id、两个 seed/版本；画廊从 API 刷新，首个安全版本 current，后续可切换/删除；断线使旧 REST 失效后 `refreshing=false` 且按钮可用；快照失败错误可见并关闭 socket，下一连接按序同步 terminal/REST 状态；保持连接的旧响应不写 UI，事件后至少一个绑定最新 revision 的 REST 快照成功应用，DOM 与 API 真相一致，成功前不显示“画廊已刷新”，结束后按钮可用；无假数据/轮询/自动 mutation 重发 |
| AC-16 | [常规] | 分别以 DEBUG_PROMPTS=false/true 读取 generated 与 uploaded 图片并打开资产页 | JSON keys、页面 DOM、其他 API | false 无中间字段；true 仅图片项额外含 built_prompt/input_snapshot（uploaded 为 null）并可展开；其他 API不泄露 file_path/prompt |
| AC-17 | [常规] | 覆盖同步 404/409/422/500 与异步外部/文件失败 | HTTP body、task详情、日志 | HTTP 固定 code/message 且语义不互换；异步 task failed/error_msg 完整、不重试、不把错误包装成 done/图片 |
| AC-18 | [常规] | 运行完整后端、前端构建、Alembic 与范围检查 | 命令退出码、TRACEABILITY、git diff | 计划测试全通过并回填准确 node ID；既有测试未改；build/check/diff 通过；未验收的真实外部门槛明确报告且 task 不勾选 |
| AC-19 | [外部输入] | 通过设置 API 写入并逐字读回 §4.1 正式单模板；使用包含明确人物外观/服装的 `character` 资产和包含明确前中后景、时间、天气、光照的 `scene` 资产各执行一次真实 cache miss | 模板 API、两次 input snapshot/rendered prompt/built prompt、task 终态、Comfy PNG 尺寸与人工视觉检查表 | 模板只有三个必需变量且明确 JSON 输出/1344×1024/二选一分支；两次 snapshot 均携带只允许非空 `prompt` 的封闭 schema且真实 task 为 done，证明响应已通过生产 JSON 解析；人物 built prompt 无场景分支指令且 PNG 为 1344×1024 单张四栏同一人物、无额外人物/文字/标志/水印，场景 built prompt 无人物四视图指令且 PNG 为 1344×1024 单幅连续环境、无可辨识人物/多格/分镜/文字/标志/水印；任一条件不满足则 T14 不通过 |

## 9. 追溯覆盖与验收通路

| 验收标准 | TRACEABILITY 准确行或替代验收 |
|---|---|
| AC-03、AC-04 | `C007 Comfy 工作流绑定与诊断：API 格式、注入/输出路径、启动失败、workflow hash 与 /system/health` |
| AC-05、AC-06 | `§6.1 去重与幂等：gen_assets/gen_shots 同目标 active 冲突 409；图像/视频允许多任务；重复 request_id 返回既有任务，并按冻结的 UUIDv5 映射复用 seed/prompt id`；API 形状由同用例覆盖 |
| AC-07、AC-08、AC-09 | `R4 input_hash 缓存：输入一致复用 prompt 只换 seed，输入变化重建并更新缓存`；风格/模板分支同时归属 `§3.3 编辑风格或模板：分镜与片段不动、文件不删，下次生成因 hash 失配重建 prompt` |
| AC-10、AC-11、AC-12 | `C007 GPU/Comfy 资源生命周期：cache miss wake/chat、提交前 sleep、WS progress/history 输出、取消 interrupt、finally free，且 vLLM/Comfy 不并发`；取消状态同时归属 `§6.1 取消：queued 直接 canceled；running 记录 cancel_requested_at，并在安全点中断` |
| AC-13、AC-14 | `C007 资产出图事务与文件一致性：生成 PNG 校验/sha256/原子落盘、首版 current、修订竞态保存非 current、缓存/图片/done 同事务、失败补偿入 trash` |
| AC-15 | `C007 AssetPage REST/WS 刷新竞态：失效旧请求不覆盖状态且不遗留 refreshing`；`C007 AssetPage 初始快照失败恢复：socket 关闭、可见错误、既有重连后重新按序同步`；`C007 AssetPage 保持连接的事件/REST 竞态：旧响应失效后补发最新快照且成功提示不早于应用` |
| AC-16 | `R11 提示词可见性：默认 API 不返回中间提示词，DEBUG_PROMPTS=true 时详情返回 built_prompt 与 input_snapshot` |
| AC-19 | `C007 Z-Image 类型语义：单一 zimage 模板按 asset.type 生成 1344×1024 人物四视图或单幅连续场景，并使用封闭 prompt JSON` |
| AC-01、AC-02、AC-17、AC-18 中纯文档/真实外部/UI/范围部分 | 不适合新增独立自动测试：UI 无现有前端测试框架，外部 gate/mock 不能证明真实 GPU/workflow，文档与范围不是运行时行为。替代方式为 T0 真实 HTTP/文件检查、真实浏览器、现有 pytest、`npm run build`、Alembic、git/range scan；运行时错误分支仍由上述归属用例覆盖 |

AC-19 不新增自动测试：正式模板是经设置 API 维护的外部运行数据，人物一致性、单幅场景构图和可辨识人物等图像语义也不能由 mock 或仓库内固定像素夹具证明。替代验收固定为 T14 走生产 app lifespan、真实 PostgreSQL、真实 vLLM、真实 Comfy workflow、正式媒体存储和 task/WS 通路，保存模板读回、两类 input snapshot/rendered prompt/built prompt、task 终态、PNG 尺寸、页面/图片截图与逐项人工真假判定；真实响应体不经生产 API 暴露，封闭 JSON 合同以 snapshot schema、task done 和已落库非空 built prompt 联合证明。该通路能证明本环境中的真实结果，不能证明未来任意 seed 都满足审美质量。

自动的任务系统 mock 必须走生产 `TaskQueue`、三键 payload、PostgreSQL mutation、worker handler、文件服务和事件通路，只替换 vLLM/Comfy transport 与随机源；它能证明调用顺序、竞态、事务和文件补偿，不能证明真实 GPU 显存释放、真实 Z-Image 节点或图片质量。跨进程/资源生命周期验收使用生产 app lifespan、真实 PostgreSQL、隔离 `DATA_DIR` 和真实或协议等价的独立 HTTP/WS 进程；最终 T0/T14 的真实 vLLM/Comfy 回合才证明外部版本与 RTX 4090 分时。

C007 不增加生产 demo、验收 endpoint 或长期 acceptance driver。最终审查后的 T21 仅授权在 `.work/c007/probe-assetpage-ws-refresh.py` 交付一次性验收装置，并且必须先于生产修复 task 完成：它运行生产前端构建、生产 app lifespan、真实 PostgreSQL、资产 REST、任务入队 API/EventBus 与 `/ws/tasks` 通路；本地代理只延迟一次画廊 REST 响应，隔离 app 在 queued 事件发布后停止 worker，避免进入 vLLM/Comfy。该装置能证明保持连接时真实 WS 事件使旧 REST 失效后，前端是否补发最新快照、提示与 `refreshing` 是否满足 AC-15；不能证明生产网络延迟分布、worker/GPU 或外部生成质量，后几项仍分别由任务系统、T20 与 T14 证据覆盖。装置及原始输出只保存在 `.work/c007`，不得进入生产包或新增 endpoint。
