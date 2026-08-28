# C005 M2 gen_assets Spec

## 1. 规范边界

本 spec 只授权 ROADMAP `C005`：`gen_assets` 的 vLLM guided_json 调用、R2 增量合并、剧本修订角标、生成按钮与结果呈现。规范来源为 PRD §0、§2.1(4,11)、§3.1-§3.3、§5 生成动作、§6.1-§6.4、§7、§9、§10、§11 M2、§12，以及用户已确认并写回 PRD 的 2026-08-26 实施裁决。

C005 复用 C001-C004 已有数据模型、任务表、队列和页面，不新增或修改 migration。不得实现范围围栏或后续 change；不得引入自动任务重试、解析 fallback、风格/模板版本化、内容 hash、第二套队列或隐藏业务 prompt。

## 2. 可观察行为

1. 用户在集工作区的剧本页点击“生成资产”，后端立即以该 episode 为 target 创建一条 `gen_assets` task，返回 task id；HTTP 请求不等待 vLLM 完成。
2. 同一 episode 已有 queued/running `gen_assets` 时，重复点击返回 409，不创建第二条 active task。
3. 入队时固定剧本、剧本修订号、项目风格、`script2assets` 模板、项目已有资产、模型和温度；任务执行期间对这些数据的编辑不改变本次输入。
4. worker 唤醒 vLLM，以完整模板渲染结果作为单条 user message，同时发送封闭 guided_json schema，默认温度为 `0.2`。
5. 成功输出中 `existing_id=null` 的项新增；真实属于当前项目的非 null id 只表示复用且不写既有行；不存在或跨项目 id 降级为新增并记录 warning。
6. 一次成功任务中的新增资产与 episode 的 `assets_generated_script_revision` 一起提交；任务运行中改剧本时，该标记仍写入队快照修订号。
7. vLLM、HTTP、超时、JSON、schema 或数据库任一步失败，任务进入 failed，`error_msg` 保留完整原因，不自动重试；不留下本次部分资产或成功修订标记。
8. 生成结果出现在项目资产页；若成功标记小于当前剧本修订，界面显示“资产提取基于旧剧本”。
9. C004 任务中心/WS 继续显示 queued、running、done、failed、canceled 和完整失败详情；C005 不新增另一套任务观察渠道。

## 3. API 合同

### 3.1 生成动作

`POST /api/episodes/{episode_id}/generate-assets`

- 请求 body：无。空请求可接受；`{}`、`null` 或任何非空 body 均不是该端点合同。
- 请求 header：不新增 `Idempotency-Key`、`If-Match` 或自定义版本 header。
- 成功：HTTP `202`，响应字段精确为 `{"task_id": <positive integer>}`，无额外字段。
- task：`type="gen_assets"`、`target_id=episode_id`、`request_id=null`、`status="queued"`、`progress=0`。
- 该端点不接受 `request_id`。PRD 只在资产出图和片段视频 body 中定义可选 `request_id`；C005 的重复提交由同 episode + `gen_assets` active 去重裁决。
- episode 存在但剧本为空字符串时仍可入队；C005 不创造 PRD 未定义的“空剧本”前置条件。模型可返回空 `assets` 数组，成功时仍写快照修订标记。
- API 只验证和快照当前数据库输入，不在请求线程同步探测或调用 vLLM。

### 3.2 既有读取接口

C005 不改变 episode、project、asset 或 task 的公开 schema。前端使用既有 episode 读取获得 `script_revision` 与 `assets_generated_script_revision`，使用既有项目资产列表呈现生成结果，使用既有任务详情/任务中心观察执行状态。

### 3.3 分页、排序与过滤

生成端点无分页、排序或过滤参数。项目资产列表继续沿用 C003 合同；本次快照中的已有资产按当前项目资产读取的稳定顺序（`id` 升序）序列化。C005 不增加分页、搜索或资产类型筛选 API。

## 4. 入队快照与数据合同

### 4.1 Payload 顶层

payload 必须继续符合 C004 的精确三成员合同，不得增减顶层键：

```json
{
  "input_snapshot": {},
  "input_hash": null,
  "source_revisions": {}
}
```

`gen_assets` 不使用 R4 的缓存，因此 `input_hash` 固定为 `null`；不得为它新增 hash、签名或 canonical serialization。

### 4.2 `input_snapshot`

`input_snapshot` 必须至少且仅包含以下 C005 执行输入：

| 字段 | 类型/必填性 | 精确语义 |
|---|---|---|
| `episode_id` | positive integer，必填 | 与 task target 相同 |
| `project_id` | positive integer，必填 | episode 入队时所属项目 |
| `script` | string，必填 | 入队时 `script_text` 原文，不 trim |
| `script_revision` | integer `>=1`，必填 | 入队时 episode 修订号 |
| `style` | string，必填 | 入队时项目所选风格的 `prompt_fragment` 原文 |
| `template_key` | string，必填 | 固定为 `script2assets` |
| `template_content` | string，必填 | 入队时设置中该 key 的完整正文 |
| `existing_assets` | array，必填 | 入队时当前项目 character/scene 的四字段快照，见 §4.4 |
| `rendered_prompt` | string，必填 | 按 §5 一次渲染后的完整 user message |
| `model` | non-empty string，必填 | 入队时 `VLLM_MODEL` |
| `temperature` | number，必填 | 入队时配置值；默认 `0.2` |

不得把 vLLM base URL、当前时间、模板版本号、风格版本号、推导出的实体别名、当前数据库对象引用或后续 change 输入放入该快照。base URL 是运行环境地址，不是可回放的业务输入。

### 4.3 `source_revisions`

`source_revisions` 记录用于完成判定和证据的已有修订，不引入新版本机制：

```json
{
  "episode": {"id": 12, "script_revision": 3},
  "assets": [
    {"id": 21, "revision": 2}
  ]
}
```

- episode 成员必须与 `input_snapshot.episode_id/script_revision` 相同。
- assets 只列入快照中的现有资产，按 id 升序；每项只含现有 `id`、`revision`。
- style/template 不得增加自研 revision 字段或版本表；其原文已在 `input_snapshot` 固化。
- worker 不以执行时的 `source_revisions` 当前值替换输入；剧本或资产变化不使已入队任务自动重排或重试。

### 4.4 `existing_assets` 注入源

数组只包含当前项目的 `character`、`scene`，按 id 升序，每项字段精确为：

```json
{"id":21,"type":"character","name":"林夏","description":"二十多岁女性…"}
```

- `id`：正整数。
- `type`：封闭枚举 `character|scene`；数据库中的 `prop` 预留不得进入 C005。
- `name`、`description`：入队时数据库字符串原文。
- 顶层无包装对象；注入值是紧凑 JSON 数组，不包含无意义空白、不转成 Markdown、不加说明文字。
- 无资产时精确注入 `[]`，不得注入“无”“暂无资产”或其他自然语言。

## 5. `script2assets` 模板与渲染

### 5.1 唯一业务模板

目标环境 `script2assets` 的 C005 正式正文冻结如下；设置页可以编辑该固定 key，但代码不得复制、拼接或隐藏其中的业务规则：

```text
你是短剧制作流水线中的「资产提取器」。你的输出会被程序直接解析:只允许输出一个 JSON 对象,不要输出任何解释、前言或 Markdown 代码围栏。

# 任务
通读剧本,提取本集出现的全部「人物」与「场景」资产,输出完整所需清单。这份清单随后用于:生成资产参考图(人物四视图/场景图)、绑定分镜、指导视频生成。因此 description 必须是"照着能画出来"的客观视觉事实。

# 项目已有资产(增量合并的依据)
{{existing_assets}}

# 判定规则(逐条遵守)
1. 完整性:剧本中每一个出镜的人物、每一个发生画面的地点,都必须出现在输出里;遗漏会导致后续分镜无法绑定。
2. 复用优先:每一项先判断它与已有资产是否指同一个人/同一地点。判定以指称对象为准,与名字写法无关——"林夏/小夏/女主"若指同一人,即同一资产。是 → existing_id 填该资产的 id,name 原样抄写已有名称;否 → existing_id 填 null,视为新增。
3. id 纪律:existing_id 只能取自上方清单中真实存在的 id,严禁编造。拿不准是否同一实体时,一律填 null 新建——重复资产可由人工发现并处理,错误复用会让新角色凭空消失。
4. 不建资产的情况:无名、无正脸、一闪而过且无需前后画面一致的路人/群演不建;纯听觉元素(画外音、电话里的声音)不建。
5. 场景拆分:同一地点在剧中呈现明显不同视觉状态(白天/夜晚、完好/损毁)时,拆为不同的场景资产,并在 name 中标注状态,如「办公室(夜)」。
6. 去重:输出数组内不得出现指向同一实体的两项。

# 字段要求
- type:人物填 "character",场景填 "scene",不允许其他取值。
- name:2-8 个字的规范名。人物用剧本中最正式的称呼;场景用「地点+状态」;同一项目内不与其他资产重名。
- description(新增项的核心,60-150 字):
  · 人物:性别、年龄段、体型、发型发色、面部特征、固定的整套着装(写死以保证跨镜一致)、随身物件、气质。只写贯穿全剧的稳定外观,不写情绪、剧情动作、人物关系。
  · 场景:地点类型、时段与光线、空间布局、标志性陈设与道具、整体氛围。不写发生在其中的事件。
  · 复用项(existing_id 非 null)的 description 原样抄写已有描述。
- 描述只写客观视觉事实,不写画风词汇(如"赛博朋克""水彩")——画风由系统在出图时按项目风格统一注入。

# 项目风格(仅作时代与题材的背景参考,勿写入描述)
{{style}}

# 剧本
{{script}}

# 输出格式(只输出这一个 JSON,别无其他)
{"assets": [{"existing_id": null, "type": "character", "name": "示例名", "description": "示例描述"}]}
```

### 5.2 渲染规则

1. 模板必须含且只解析三个已知占位符：`{{existing_assets}}`、`{{style}}`、`{{script}}`；缺少任一必需占位符或存在其他未解析占位符时，不入队并返回 409。
2. 三个值都取 §4 的入队快照。`script`、`style` 原样替换；`existing_assets` 按 §4.4 紧凑 JSON 序列化。
3. 渲染只针对原始模板中识别出的占位位置执行一次；注入文本中的 `{{...}}` 不再二次解释。
4. 完整渲染结果保存到 payload，并作为一次 vLLM 请求中的单条 user message；不得把模板拆成多条业务消息。
5. 默认不发送 system message。若所用兼容客户端在协议层强制要求 system message，只允许精确内容：`你是结构化数据生成器,只输出 JSON`。不得在 system 中加入实体规则、字段规则、示例或 fallback 指令。

## 6. vLLM 请求与输出合同

### 6.1 请求

- 目标：配置的 `VLLM_BASE_URL` 与 `VLLM_MODEL`；不得硬编码开发地址或模型名。
- 温度：`VLLM_TEMPERATURE`，默认 `0.2`；必须为闭区间 `[0,2]` 的数，配置非法时应用启动失败，不静默回落到默认值。
- 消息：§5.2 的一条 user message；仅在协议强制时增加已冻结的通用 system message。
- 结构约束：格式指令与 vLLM 侧硬约束必须同时存在；不得只靠 prompt，也不得在 schema 失败后退回自由文本解析。
- 请求失败、非成功 HTTP、超时或响应缺少内容均抛出真实错误并使 task failed；不自动重试。

### 6.2 `response_format` / guided_json schema

发送给 vLLM 的 schema 语义精确如下；顶层和 item 都封闭，四个 item 字段全部 required：

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "script2assets",
    "strict": true,
    "schema": {
      "type": "object",
      "properties": {
        "assets": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "existing_id": {"type": ["integer", "null"]},
              "type": {"type": "string", "enum": ["character", "scene"]},
              "name": {"type": "string"},
              "description": {"type": "string"}
            },
            "required": ["existing_id", "type", "name", "description"],
            "additionalProperties": false
          }
        }
      },
      "required": ["assets"],
      "additionalProperties": false
    }
  }
}
```

不得加入 `prop`、自动补字段、允许额外属性、候选列表、版本字段或宽松 union。响应必须解析为且只为这个 JSON object；Markdown 围栏、前后解释文字、非法 JSON、额外键或类型不符均使 task failed。

### 6.3 语义校验边界

模板中的完整性、实体同一性、2-8 字名称、60-150 字描述、固定着装、场景拆分与输出去重属于模型质量规则。C005 后端不实现第二份实体识别器，也不自行截断、改写、去重或以 fallback 补全模型内容。硬校验仅为 §6.2 的结构、§7 的项目归属和数据库既有约束；数据库拒绝某项时整次任务失败并回滚。

## 7. R2 增量合并与事务

对输出 `assets` 按模型返回顺序逐项处理：

1. `existing_id=null`：在快照项目中新建一条资产，使用返回的 `type/name/description`，`source="generated"`，现有初始 revision 规则保持不变；不创建图片。
2. `existing_id` 非 null 且执行时真实属于当前项目：视为复用；不插入、不 PATCH、不更新 name/description/type/revision，不删除任何内容。模型返回文字即使与数据库不同也不覆盖既有资产。
3. `existing_id` 非 null 但不存在，或存在却属于其他项目：忽略该 id，按第 1 项新建，并记录 warning。warning 至少带 task id、episode id、project id、模型给出的 existing_id，且不得泄露凭据或完整剧本。

项目归属校验针对执行时数据库真相，不能只相信入队快照或模型输出。若快照后资产被删除，模型返回的旧 id 在执行时已不存在，按第 3 项降级新增；这不会触发自动重试。

所有本次新增行与 episode 的 `assets_generated_script_revision = input_snapshot.script_revision` 在一个数据库事务中完成。空数组允许只更新修订标记。事务提交前须检查取消安全点；事务一旦开始，不在其中插入可取消的外部步骤。任何验证/写入/标记错误回滚本次全部写入并向 worker 抛出，不能逐项吞错或保留“成功的部分”。

生成资产不得修改或删除既有 assets、asset_images、shots、shot_assets、clips、clip_shots、clip_asset_slots、clip_videos 或媒体文件；不得触发 trash。

## 8. 状态转换、并发与幂等

### 8.1 正常状态

`queued → running → done`。wake、vLLM、解析、校验与数据库提交都属于 running。worker 可在步骤边界提交非递减 progress 与中文 WS message，但不得用 progress 伪装业务成功；done 时沿用 C004 设为 `1.0`。

### 8.2 失败与取消

- 任一步骤异常：仍为 running 时进入 failed，写完整 `error_msg`/`finished_at`，保留 traceback 日志，不新建替代 task、不重排、不重试。
- queued 取消和 running 安全点取消沿用 C004。handler 至少在外部调用前、外部调用后、最终事务前检查安全点；取消后不得继续新增资产或写成功标记。
- 终态竞态沿用 C004 条件更新，败者不得覆盖先提交的 done/failed/canceled。

### 8.3 快照竞态

- 任务运行中编辑剧本：worker 仍用旧 script；成功标记写旧 `script_revision`。因为当前 `script_revision` 更大，页面显示旧剧本角标。
- 运行中编辑风格或模板：本 task 继续用 payload 中旧文本；只影响后续新任务。不得建立版本表或版本选择 UI。
- 运行中编辑/新增资产：本 task 的 prompt 仍用入队资产清单；落库阶段仅对非 null id 做实时项目归属防御，不重新生成 prompt。

### 8.4 重复提交

- 同 episode + `gen_assets` 已有 queued/running：409 `conflict`，不返回既有 task id、不创建新行。
- 前一 task 为 done/failed/canceled：允许再次发起并产生新 task；失败不自动重试，但用户显式再次点击属于新操作。
- C005 无 request_id、HTTP 自动重试、前端 mutation 重发、任务版本号、ETag 或 If-Match。

## 9. UI 合同

### 9.1 剧本页生成入口

- 集工作区剧本页的只读状态提供明确按钮“生成资产”；正在编辑未保存剧本时不发起生成，用户须先保存，以避免按钮视觉内容与数据库快照不一致。
- 点击成功后显示返回的 task id，并提供进入现有任务中心的入口；不自动跳转离开剧本页。
- 点击失败直接展示 `detail.message`。409 明确提示已有该集资产提取任务在进行；不得吞错、伪成功或自动重发。
- 前端可在请求进行期间临时禁用按钮防连点，但后端 409 仍是唯一最终并发裁决。

### 9.2 结果呈现

- 集工作区资产页继续读取项目级资产列表，显示生成后新增的 character/scene 名称、类型、描述及既有可见元数据。
- 用户从任务完成后切换/重新进入资产页时必须重新读取资产列表，不依赖生成请求的本地临时对象，不写假结果。
- C005 不新增自动轮询、推送资产 payload 或结果专用页面；任务状态由 C004 任务中心/WS 呈现。

### 9.3 旧剧本角标

- 判定精确为：`assets_generated_script_revision != null && assets_generated_script_revision < script_revision`。
- 成立时，在集工作区剧本页和资产页可见位置显示固定文案“资产提取基于旧剧本”。
- marker 为 null 表示尚无成功生成，不显示“旧剧本”；两者相等时不显示；禁止用前端本地时间或 task 状态推导。
- 页面进入或剧本保存/标签切换后重新读取 episode 真相；C005 不增加周期轮询。

## 10. 错误码矩阵

所有 HTTP 错误体必须为：

```json
{"detail":{"code":"non_empty_code","message":"可直接展示的中文说明"}}
```

| HTTP | `detail.code` | 触发条件 | 不得替代为 |
|---|---|---|---|
| 404 | `not_found` | episode id 在当前数据库不存在 | 403、409、422 |
| 403 | 不使用 | v1 无用户/权限系统；不存在“资源存在但无权生成”的场景 | 用 403 隐藏 404 |
| 405 | `method_not_allowed` | 已知路径使用未授权方法 | 404、422 |
| 409 | `conflict` | 同 episode 已有 active `gen_assets`；项目风格/`script2assets` 不存在；模板缺必需占位符或含未知未解析占位符等当前配置前置条件不满足 | 422、200 伪成功 |
| 422 | `validation_error` | path 不是整数、请求携带任何非空 body，或请求内容未通过边界输入校验 | 409 |
| 500 | `internal_error` | API 入队边界未预期的服务端错误；服务端必须记录 traceback | 200、409、422 |

404 与 403 只按鉴权判定：本地单操作者无鉴权，资源不存在一律 404，403 不使用。409 与 422 只按“合法请求是否被当前状态阻止”判定：格式合法但被 active task 或缺失运行配置阻止为 409；请求本身的类型/body 非法为 422。

vLLM 不可达、wake 失败、超时、非成功响应、非法 JSON/schema、数据库合并失败都发生在已返回 202 之后，因此不是该 POST 的 4xx/5xx 响应；对应 task 必须 failed，并通过任务详情保留完整 `error_msg`。不得把异步失败改成 200，也不得 fallback 为 `assets=[]`。

## 11. Non-Goals 与后续归属

| Non-Goal | 后续归属 |
|---|---|
| gen_shots、impact/confirm、分镜覆盖与编辑绑定 | C006 |
| Z-Image/Comfy、资产出图、input_hash、GPU sleep/free 调度 | C007 |
| clip 预检/创建/槽位与引用处置 | C008 |
| gen_clip_video、MiniMax H3、take/actual_duration/反竞态 | C009 |
| 导演台 UI | C010 |
| 任务中心取消/历史/过滤与全局 UI/UX 专题 | C011 |
| 全链路 E2E、发布级重启/级联/竞态总验收 | C012 |
| 候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格/模板版本化、generation_runs、continuity、context loop、fl2v、音频 | v1 明确排除，不延后到任何 change |

## 12. 向后兼容与迁移影响

- 数据库：零 migration，零表/列/索引变化；复用现有 episode marker、asset、task 字段。
- API：新增一个 endpoint，不改变现有响应字段、状态码或路径。不存在旧版 generate-assets 合同需兼容。
- 配置：新增 `VLLM_TEMPERATURE`，未显式配置时可观察默认值为 `0.2`；非法值启动失败，无旧别名或双读。
- 提示词：目标环境的 `script2assets` 从占位内容更新为 §5.1 正式正文时，只影响更新后入队的任务；已入队 payload 不变。不创建模板版本或迁移脚本。
- UI：在现有集工作区增量加入按钮、反馈和角标；保留既有剧本编辑、资产 CRUD、返回导航与任务中心行为。

## 13. 验收标准

- **AC-01 范围与迁移**：C005 没有 migration/schema 变化，没有围栏机制、gen_shots/图像/clip/video 后续能力、自动重试或隐藏 fallback。
- **AC-02 外部 gate**：真实 vLLM 地址/端口和 wake 证据到位；目标环境 `script2assets` 与 §5.1 逐字一致并可读回；示例配置不冒充证据。
- **AC-03 生成 API**：已存在 episode 的无 body 请求返回 202 + 精确 `task_id`，task type/target/request_id/status 正确；未知为 404、非空 body 为 422。
- **AC-04 Active 去重**：同 episode 并发或双击只有一条 queued/running `gen_assets`，败者为结构化 409；终态后可由用户显式新建下一 task。
- **AC-05 快照完整性**：payload 顶层精确三键；剧本/修订/风格/模板/资产/渲染 prompt/模型/温度与 source revisions 都来自同一次入队真相，`input_hash=null`。
- **AC-06 模板注入**：有资产时注入仅四字段的紧凑 JSON 数组，无资产时精确 `[]`；完整模板只作为一条 user message，业务规则不藏在 system 或代码。
- **AC-07 guided_json**：真实请求同时含温度 `0.2` 与 §6.2 封闭 schema；`prop`、缺字段、额外字段、围栏/解释文字或非法 JSON 均明确失败，无自由文本 fallback。
- **AC-08 R2 合并**：null id 新增；当前项目合法 id 不增不改不删；不存在/跨项目 id 新增并产生含上下文 warning；新增 source 为 generated，且不创建图片。
- **AC-09 事务与失败**：一次输出多项时全部新增与 marker 同事务；vLLM/schema/数据库任一步失败均无本次部分资产或 marker，task failed、完整错误、不重试。
- **AC-10 快照竞态角标**：运行中把剧本从修订 N 改为 N+1，模型收到 N 的剧本，成功 marker 为 N，页面显示“资产提取基于旧剧本”；重新成功生成 N+1 后角标消失。
- **AC-11 下游无损**：重新生成资产只新增 R2 项，不改变/删除既有资产、图片、shots、clips 或任何媒体文件，不触发 trash。
- **AC-12 UI 生成与结果**：剧本只读页可发起生成并看到 task id/任务中心入口；失败展示 `detail.message`；任务完成后切换/进入资产页可见真实新增结果，不依赖假数据或轮询。
- **AC-13 状态与取消**：C004 queued/running/done/failed/canceled、heartbeat、WS 和取消语义不漂移；C005 handler 在规定安全点响应取消，取消后不继续写资产/marker。
- **AC-14 错误一致性**：所有 API 错误符合固定结构，404/403 与 409/422 按 §10 一致；异步 vLLM 错误只落 failed，不伪装同步成功结果。
- **AC-15 追溯与回归**：新增测试全部属于 C005 tasks 指定的既有 TRACEABILITY 行并回填真实 node ID；既有测试未修改/弱化；完整 pytest、前端 build、Alembic check 与 diff/range scan 通过。
