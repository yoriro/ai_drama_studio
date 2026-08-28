# C006 M2 gen_shots Spec

## 1. 规范边界

本 spec 只授权 ROADMAP `C006`：`gen_shots` 的 R1/R3 全流程、动态 guided_json、分镜读取/编辑/绑定、changed/stale 级联、旧剧本角标与 C006 所需 UI。规范来源为 PRD §0、§2.1(4,6,11)、§3.1-§3.3、§4、§5、§6.1-§6.4、§7、§9-§12，以及需求方在本 change 冻结的正式 `script2shots` 模板和四项实施说明。

C006 复用 C001-C005 已有表、任务队列、WS、vLLM 客户端、模板设置和页面骨架，数据库必须零 migration。不得预建或实现候选分镜版本、分镜增删/拆分/合并/排序、clip 创建/编辑/视频生成、资产图生成、导演台、generation_runs、continuity、音频或其他后续 change 能力；不得自动重试、静默 fallback、隐藏第二份业务 prompt、内容 hash 或模板/风格版本化。

## 2. 可观察行为

1. 项目没有任何可用于 C006 的 `character/scene` 资产时，生成动作被 R1 阻止并返回 409，不创建 task；impact 仍只读返回当前删除影响，不能以预检成功替代 generate 的 R1 裁决。
2. 用户点击“生成分镜”时，前端先请求影响预检。影响不为空时必须展示将删除的片段数和视频数，用户确认后才携 10 分钟 token 发起生成；影响为空时可直接生成。
3. 生成 API 立即返回 queued `gen_shots` task，不等待 vLLM。相同 episode 同时最多一条 queued/running `gen_shots`，重复提交返回 409。
4. 入队时冻结剧本、剧本修订号、风格、正式模板、完整项目资产清单、渲染后的单条 user message、模型、温度、动态 schema，以及本次会被替换的结构快照。worker 不用执行时的新输入改写这份快照。
5. worker 唤醒 vLLM，以默认温度 `0.2` 和入队时动态 schema 生成分镜。非法 JSON、结构、枚举、时长、order 或资产 id 使整条 task failed，不自动修补或重试。
6. 单个分镜绑定 0 个场景或不少于 2 个场景都可成功落库。它们分别显示“未绑定场景”提示和“绑定多个场景，需修正”警示；不能把这两种质量问题升级为生成或 PATCH 的拒绝条件。
7. 只有新分镜完成全部生成与校验后，才进入 R3 最终替换阶段。任何此前的 LLM/HTTP/schema/资产归属错误都使旧分镜、旧片段、视频和 marker 分毫不动。
8. 成功替换本集全部旧分镜，删除本集全部片段及其关系/槽位/视频行，把相关 clip 视频和 override 文件移入 trash，写入入队快照的剧本修订号，新分镜均为 `normal`。
9. 用户可按叙事顺序查看分镜并编辑景别、运镜、描述、台词和资产绑定。实际变化使该分镜 `revision += 1`、`status=changed`，包含它的片段变为 `stale`；文件不删。
10. 编辑资产名称/描述、换当前图片或删除资产时，已绑定分镜和相关片段按 PRD §3.3 变化；删除资产必须解绑，不能因外键级联而漏掉 changed/stale 判定。
11. 若生成期间剧本从修订 N 改为 N+1，本任务仍使用 N 的快照；成功 marker 写 N，分镜页和剧本页显示“分镜基于旧剧本”。用户须显式再次生成，系统不自动重跑。
12. 所有失败直接 surfaced：同步 API 显示固定错误体，异步失败由 task 保存完整 `error_msg`；不得吞异常、伪成功或自动提交替代请求。

## 3. API 合同

### 3.1 影响预检

`POST /api/episodes/{episode_id}/generate-shots/impact`

- 请求 body：无。真正零字节 body 合法；`{}`、`null`、空白字符或其他任意非空 body 均返回 422。
- 请求 header：不新增认证、`Idempotency-Key`、`If-Match` 或版本 header。
- 计数范围：只统计该 episode 当前会被 R3 删除的 clip 行数，以及这些 clip 下当前全部 `clip_videos` 行数；不把 shot 数、媒体文件数或其他 episode 数据混入计数。
- 影响不为空时，HTTP 200 响应字段精确为：

```json
{"clips_count":2,"videos_count":3,"confirm_token":"opaque-token","expires_in":600}
```

- 影响为空时，HTTP 200 响应字段仍固定，值精确为：

```json
{"clips_count":0,"videos_count":0,"confirm_token":null,"expires_in":null}
```

- `clips_count`、`videos_count` 是大于等于 0 的整数；`confirm_token` 为不透明、非空字符串或 null；`expires_in` 只在发 token 时为整数 `600`，否则为 null。
- token 的服务端状态只需存在于当前后端进程，TTL 固定 600 秒，不写数据库、不加配置项、不做 token 版本表。进程重启后旧 token 失效，用户重新预检。
- token 绑定 episode id 和预检时的**精确影响快照**：当前 clip id/revision 集、clip_video id 集、clip override 文件引用集，而不只绑定两个计数。TTL 内重复读取不延长有效期。
- 预检只读，不删除数据、不移动文件、不创建 task，也不预留“删除权”。

### 3.2 生成动作

`POST /api/episodes/{episode_id}/generate-shots`

- 请求 body 必须是 JSON object，允许字段仅为可选 `confirm_token`：

```json
{}
```

或：

```json
{"confirm_token":"opaque-token"}
```

- `confirm_token` 类型只能为非空 string 或 null。无 body、JSON `null`、数组、未知字段、空字符串或纯空白 token 均为 422。
- 当前影响为空时，字段省略或 null 合法；若携带非 null token，该 token 仍必须属于当前 episode、未过期且绑定当前空影响，否则 409。
- 当前影响不为空时，字段省略/null、过期、跨 episode、伪造或与当前影响快照不一致均为 409；不创建 task。
- R1、token 和模板/风格等前置条件通过后，成功为 HTTP 202，响应字段精确为 `{"task_id":<positive integer>}`。
- 新 task 精确为 `type="gen_shots"`、`target_id=episode_id`、`request_id=null`、`status="queued"`、`progress=0`。
- 此端点不接受 request_id。HTTP/前端不得自动重发；前一 task 为 done/failed/canceled 后，用户再次点击属于新的显式操作并可创建新 task。
- API 只验证、渲染和快照当前数据库输入，不在请求线程调用 vLLM。

### 3.3 分镜列表

`GET /api/episodes/{episode_id}/shots`

- 成功为 HTTP 200 JSON array；未知 episode 为 404。
- 不分页、不搜索、不筛选；固定按 `order_index ASC, id ASC` 返回。
- 每项字段精确为：

| 字段 | 类型/必填性 | 合同 |
|---|---|---|
| `id` | positive integer，必填 | Shot id |
| `episode_id` | positive integer，必填 | 所属 episode |
| `order_index` | integer `>=1`，必填 | 叙事顺序；只读 |
| `duration_est` | number `1..5`，必填 | 秒；只读；JSON number，不转字符串 |
| `shot_type` | string，必填 | `远景/全景/中景/近景/特写` 之一 |
| `camera` | string，必填 | `固定/推/拉/摇/移/跟/手持` 之一 |
| `description` | string，必填 | 当前描述原文 |
| `dialogue` | string，必填 | 当前台词原文，可为 `""` |
| `asset_ids` | integer array，必填 | 当前绑定 id，按 id 升序，无重复 |
| `status` | string，必填 | 封闭枚举 `normal/changed` |
| `revision` | integer `>=1`，必填 | 当前修订号；只读 |
| `created_at` | string，必填 | UTC ISO 8601，带时区 |
| `updated_at` | string，必填 | UTC ISO 8601，带时区 |

空集返回 `[]`。金额字段不存在。此端点不接受分页、排序、过滤或 include 参数。

### 3.4 编辑分镜

`PATCH /api/shots/{shot_id}`

- body 必须是 JSON object，允许字段只为 `shot_type`、`camera`、`description`、`dialogue`、`asset_ids`；至少出现一个字段，未知字段为 422。
- `shot_type`、`camera` 使用 §3.3 封闭枚举；`description`、`dialogue` 必须为 string，不自动 trim、截断或改写；`asset_ids` 必须为无重复 positive integer array，允许 `[]`。
- 所有 asset id 必须在请求提交时真实属于该 Shot 所在项目，且类型是 `character/scene`；不存在、跨项目、`prop` 或重复 id 都是请求内容校验失败，返回 422。
- 0 个场景或不少于 2 个场景合法，不返回 409/422；API 按请求保存，UI 负责提示。
- 只出现但值与当前数据库完全相同的字段属于 no-op：返回当前对象，不增加 revision、不改 status、不级联 stale。
- 存在实际变化时，在一个数据库事务中替换指定字段/全部绑定，`revision += 1`、`status=changed`；若该 Shot 已属于一个 clip，则把该唯一 clip 设为 `freshness=stale`，未属于 clip 时不产生 clip 状态变化。受 PRD R5 与 `clip_shots.shot_id UNIQUE` 约束，同一 Shot 不可能同时命中多个 clip；不改变 clip `generation_state`、revision 或文件。
- 成功 HTTP 200，响应使用 §3.3 单项字段。未知 Shot 为 404。
- C006 不支持 PATCH `order_index`、`duration_est`、`status`、`revision`、`episode_id` 或时间字段；这些字段出现即 422。
- 不支持 ETag/If-Match。并发 PATCH 在数据库当前值上逐个串行裁决；不同字段可合并，同一字段后提交者覆盖先提交值，每个实际变化的成功请求只递增一次 revision。

## 4. 入队快照与数据合同

### 4.1 Payload 顶层

payload 必须继续符合 C004 的精确三成员合同：

```json
{
  "input_snapshot": {},
  "input_hash": null,
  "source_revisions": {}
}
```

`gen_shots` 不使用 R4 缓存，`input_hash` 固定为 null；不得新增内容 hash、签名、canonical serialization 或其他顶层键。

### 4.2 `input_snapshot`

`input_snapshot` 必须至少且仅包含以下 C006 执行输入：

| 字段 | 类型/必填性 | 精确语义 |
|---|---|---|
| `episode_id` | positive integer，必填 | 与 task target 相同 |
| `project_id` | positive integer，必填 | 入队时所属项目 |
| `script` | string，必填 | 入队时 `script_text` 原文，不 trim |
| `script_revision` | integer `>=1`，必填 | 入队时 episode 修订号 |
| `style` | string，必填 | 入队时所选风格 `prompt_fragment` 原文 |
| `template_key` | string，必填 | 固定为 `script2shots` |
| `template_content` | string，必填 | 入队时固定 key 的完整正文 |
| `assets` | array，必填 | §4.4 四字段项目资产快照 |
| `rendered_prompt` | string，必填 | §5 一次渲染的完整 user message |
| `model` | non-empty string，必填 | 入队时 `VLLM_MODEL` |
| `temperature` | number，必填 | 入队时配置；默认 `0.2` |
| `guided_json_schema` | object，必填 | §6.2 由本次资产 id 动态形成的完整 schema |
| `replacement_snapshot` | object，必填 | §4.5 当前待替换结构与媒体引用 |

不得把 vLLM base URL、当前时间、token、token TTL、模板/风格版本、别名、候选分镜、数据库对象引用、后续 clip 输入或未知字段放入快照。confirm token 只做同步入队授权，不进入 worker payload。

### 4.3 `source_revisions`

```json
{
  "episode":{"id":12,"script_revision":3},
  "assets":[{"id":21,"revision":2}],
  "shots":[{"id":41,"revision":1}],
  "clips":[{"id":51,"revision":4}]
}
```

- episode 与 `input_snapshot.episode_id/script_revision` 一致。
- assets、shots、clips 均按 id 升序，每项只含 `id/revision`；空集合精确为 `[]`。
- assets 记录 prompt 与动态 enum 的来源；shots/clips 记录最终替换前的竞态依据。
- style/template 不得制造 revision；其文本已在 `input_snapshot` 固化。
- 运行中改剧本、风格、模板或新增资产不改本次模型输入。删除/编辑入队资产或改变待替换结构的处理见 §7.4。

### 4.4 `assets` 注入源

数组只包含入队时当前项目的 `character/scene`，按 id 升序，每项字段精确为：

```json
{"id":21,"type":"character","name":"林夏","description":"二十多岁女性…"}
```

- `id` 为 positive integer；`type` 封闭为 `character/scene`；`name/description` 为数据库原文。
- 顶层无包装对象；注入为紧凑 JSON，不加 Markdown 或自然语言。
- R1 使空数组不能入队；数据库中的 `prop` 预留不进入快照、prompt 或 enum。

### 4.5 `replacement_snapshot`

该对象必须且仅包含：

| 字段 | 类型 | 精确语义 |
|---|---|---|
| `shots` | array of `{id,revision}` | 当前 episode 全部旧 Shot |
| `clips` | array of `{id,revision}` | 当前 episode 全部旧 Clip |
| `clip_video_ids` | positive integer array | 上述 clips 下全部视频行 id |
| `clip_media` | array | 下述精确三字段媒体引用；覆盖 clip video 与 slot override |

`clip_media` 每项必须且仅包含：

```json
{"kind":"clip_video","id":71,"path":"projects/4/episodes/12/clips/51/71.mp4"}
```

或：

```json
{"kind":"slot_override","id":81,"path":"projects/4/episodes/12/clips/51/slots/81.png"}
```

- `kind` 是封闭枚举 `clip_video/slot_override`。
- `kind="clip_video"` 时，`id` 精确取 `clip_videos.id`，`path` 精确取该行入队时的 `file_path`。
- `kind="slot_override"` 时，`id` 精确取保存该 override 的 `clip_ref_slots.id`，`path` 精确取该槽位行入队时非 null 的 `override_image_path`；没有 override 的槽位不进入数组。
- `id` 为 positive integer；`path` 为数据库中保存的非空存储相对路径原文，不转绝对路径、不规范化或改写。
- 数组固定先列全部 `clip_video`，再列全部 `slot_override`；每组内按 `id ASC`，同一 `(kind,id)` 不重复。空媒体精确为 `[]`。
- `clip_video_ids` 必须精确等于 `clip_media` 中全部 `kind="clip_video"` 项的 `id`，按升序排列。
- 最终提交前须按 `kind/id` 重读对应业务行，确认其仍属于 `clips` 快照中的 clip 且当前路径与 `path` 精确一致；任一行、归属或路径漂移均按 §7.4 失败。

它用于证明最终覆盖仍针对用户确认的同一批旧结构和媒体，不是生成历史或候选版本。不得保存绝对路径、token、文件 hash、文件内容或其他 episode 数据。

## 5. `script2shots` 模板与渲染

### 5.1 唯一业务模板

目标验收环境 `script2shots` 正文冻结如下；设置页可编辑此固定 key，但代码不得复制、拼接或隐藏其中的业务规则：

```text
你是短剧制作流水线中的「分镜拆解器」。你的输出会被程序直接解析:只允许输出一个 JSON 对象,不要输出任何解释、前言或 Markdown 代码围栏。

# 任务
把剧本拆解为可逐条生成视频的分镜序列。每个分镜的 description 之后会用于生成该镜头的视频画面,asset_ids 用于自动加载参考图,因此拆解粒度与绑定准确性直接决定成片质量。

# 项目资产清单(绑定的唯一合法依据)
{{assets}}

# 拆解规则(逐条遵守)
1. 粒度:每个分镜 2-3 秒(duration_est 取 1-5 之间的数,单位秒),一个镜头只承载一件事——一个动作、一句台词或一个反应。60 秒一集通常拆成 20-30 个分镜。全部分镜的 duration_est 合计应接近整集时长。
2. 顺序:order 从 1 开始连续递增,严格按叙事顺序,不重号不跳号。
3. 场景连续:同一地点的连续剧情拆出的分镜必须相邻成块,不要在地点之间来回跳切(除非剧本明确要求交叉剪辑)。相邻同场景的分镜后续才能合并生成视频。
4. 绑定(asset_ids,只能使用清单中的 id):
   - 绑定且仅绑定「画面中实际出现的人物」+「该镜头发生地的场景」。
   - 每个分镜至多绑定 1 个场景。特写等无法辨认地点的镜头可以不绑场景;严禁绑定 2 个场景——跨地点的转场一律拆成两个分镜,各绑各的场景。
   - 画外音的说话者不出镜则不绑;被提及但不出镜的人物不绑。
   - 若剧本中出现清单里没有对应资产的人物或地点,只在 description 中文字描述,不要试图绑定任何近似资产。
5. description(30-80 字,纯视觉):谁在哪做什么——动作、表情、关键构图或光线变化。用资产的规范名指代人物与场景。情绪只写外显表现("眼神黯淡、低头"可,"想起了往事"不可)。不写台词内容,不写画风词汇,不写心理活动。
6. dialogue:该镜头内说出的台词原文,格式「说话人:台词」,多句用 / 分隔;旁白写「旁白:内容」;无台词填空字符串 ""。
7. shot_type(景别)取:远景/全景/中景/近景/特写;camera(运镜)取:固定/推/拉/摇/移/跟/手持 之一。

# 项目风格(仅作时代与题材的背景参考,勿写入描述)
{{style}}

# 剧本
{{script}}

# 输出格式(只输出这一个 JSON,别无其他)
{"shots": [{"order": 1, "duration_est": 2.5, "shot_type": "近景", "camera": "固定", "description": "示例描述", "dialogue": "林夏:示例台词", "asset_ids": [21, 31]}]}
```

### 5.2 渲染规则

1. 模板必须含且只解析 `{{assets}}`、`{{style}}`、`{{script}}` 三个已知占位符；缺任一必需占位符或存在未知未解析占位符时不入队，返回 409。
2. 值全部来自 §4 同一入队快照。script/style 原样替换；assets 为 §4.4 紧凑 JSON。
3. 只替换原模板中识别出的占位符一次；注入内容中的 `{{...}}` 不二次解释。
4. 完整结果存入 payload，并作为一次 vLLM 请求中的单条 user message；业务模板是唯一事实来源。
5. 默认不发送 system message。兼容客户端若协议上强制要求，只允许精确一句：`你是结构化数据生成器,只输出 JSON`；不得把拆镜、绑定或字段规则藏入 system。

## 6. vLLM 请求、动态 schema 与输出校验

### 6.1 请求

- 使用已有环境配置的 `VLLM_BASE_URL`、`VLLM_MODEL` 和 `VLLM_TEMPERATURE`；不硬编码地址/模型。温度默认 `0.2`，沿用 C005 `[0,2]` 启动校验。
- LLM 前执行已有 wake；请求失败、超时、非成功 HTTP、缺内容均抛出真实错误并使 task failed，不自动重试。
- prompt 指令和 vLLM 结构硬约束必须同时存在；schema 请求失败不得退回自由文本或弱解析。

### 6.2 入队时动态 `response_format`

完整 response_format 存入 `input_snapshot.guided_json_schema`，其中 `asset_ids.items.enum` 在**入队时**精确等于 §4.4 全部资产 id（升序、无重复）：

```json
{
  "type":"json_schema",
  "json_schema":{
    "name":"script2shots",
    "strict":true,
    "schema":{
      "type":"object",
      "properties":{
        "shots":{
          "type":"array",
          "items":{
            "type":"object",
            "properties":{
              "order":{"type":"integer"},
              "duration_est":{"type":"number","minimum":1,"maximum":5},
              "shot_type":{"type":"string","enum":["远景","全景","中景","近景","特写"]},
              "camera":{"type":"string","enum":["固定","推","拉","摇","移","跟","手持"]},
              "description":{"type":"string"},
              "dialogue":{"type":"string"},
              "asset_ids":{"type":"array","items":{"type":"integer","enum":[21,31]}}
            },
            "required":["order","duration_est","shot_type","camera","description","dialogue","asset_ids"],
            "additionalProperties":false
          }
        }
      },
      "required":["shots"],
      "additionalProperties":false
    }
  }
}
```

示例 `[21,31]` 必须被每次入队真实资产 id 列表替换。不得加入 `prop`、null、范围外 id、执行时新增 id、额外属性、候选版本或宽松 union。`shots` 不设置 `minItems`；空剧本可由模型返回 `[]`，成功时仍完成 R3 覆盖并更新 marker。

当前正式验收 vLLM 的 grammar 引擎对含 `uniqueItems` 的请求返回 HTTP 400 `Grammar error: Unimplemented keys: ["uniqueItems"]`，因此发往 vLLM 及存入快照的 schema **不得包含**该关键字。资产 id 去重语义不变，必须由 §6.3 后端硬校验在任何业务写入前执行；这不是自由文本 fallback、自动修补或放宽非法重复绑定。

### 6.3 后端硬校验

响应必须是且只是一份符合 §6.2 的 JSON object。Markdown 围栏、解释文字、非法 JSON、缺/多字段、错误类型、非法枚举、`duration_est` 越界或重复 asset id 均使整任务 failed。

schema 之外还必须校验：

1. N 条分镜的 `order` 必须精确为整数序列 `1..N`，不重号、不跳号、不重排；数据库 `order_index` 取该值。
2. 每个 asset id 必须属于入队资产快照，且最终提交时仍真实属于该 episode 的项目并为 `character/scene`。任何不存在、跨项目、被删除或非法类型 id 都使整任务 failed；不得忽略、降级新增、近似绑定或部分落库。
3. 0 个场景或不少于 2 个场景不属于硬校验失败；照常保存并由 UI 角标提示。

模板中的 20-30 镜、2-3 秒偏好、总时长接近、30-80 字、纯视觉、台词格式、实际出镜绑定、场景连续与跨地点拆镜是模型质量规则。后端不得复制第二套 NLP/启发式裁决器，不截断、补写、合并、拆分、排序或替换输出；其质量由正式模板和 §14 真实验收决定。

## 7. R3 覆盖、状态转换与竞态

### 7.1 正常顺序

`queued → running → done`。handler 至少按下列顺序执行：wake 安全点 → 使用快照调用 vLLM → 解析与全部硬校验 → 最终安全点 → R3 替换事务 → done。progress/WS 可报告阶段，但不能以 progress 冒充业务完成。

最终替换必须作为一个不可部分提交的业务单元：

1. 锁定 episode 及 `replacement_snapshot` 中待替换结构，重新核对 §7.4 条件和所有媒体相对路径；在此之前不得移动文件或删除业务行。
2. 先让 C004 的条件终态裁决确认该 running task 仍可提交；取消先赢时立即停止，旧结构、文件和 marker 不动。
3. 将本集 clip video 与 slot override 媒体移入已有 trash 纪律；删除相关 clip_videos、clip 关系/槽位/clip 行、旧 shot_assets/shot 行；按模型顺序插入新 Shot 与绑定。
4. 新 Shot 的 `order_index=order`、`duration_est/shot_type/camera/description/dialogue` 取模型原值，`status=normal`、`revision=1`；写 `episodes.shots_generated_script_revision=input_snapshot.script_revision`。
5. 所有数据库变化和 task `done/progress=1` 同一事务提交。数据库提交失败时必须回滚全部数据库变化，并同步恢复本次已移入 trash 的原文件；恢复失败也必须完整报错，不能伪称旧数据无损或成功。

删除顺序须尊重现有外键，不得依赖意外 CASCADE 丢失需计数、trash 或 stale 的对象。C006 不新建候选表、generation run 或删除历史。

### 7.2 失败与取消

- wake/vLLM/HTTP/JSON/schema/order/资产归属/数据库/文件任一步异常：task 直接 failed，完整 `error_msg` 与 traceback 可诊断，不重试、不创建替代 task。
- LLM 和全部校验失败发生在替换前，旧 shots/clips/media/marker 必须完全不动。
- queued 取消和 running 安全点取消沿用 C004。至少在外部调用前、调用后、任何文件移动前检查取消；文件移动和最终事务期间不插入可被另一终态割裂的异步步骤。
- 条件终态只有一方获胜。canceled/failed 不得被 done 覆盖；done 后取消返回既有 C004 冲突语义，不反向删除结果。

### 7.3 重复提交与幂等

- 同 episode + `gen_shots` queued/running 时返回 409，不返回既有 task id、不消费/延长 token、不创建第二条 active task。
- 前一 task 终态后允许用户重新 impact 并显式发起下一 task；这不是自动重试。
- C006 无 request_id、HTTP 自动重发、ETag/If-Match、任务版本号、生成历史或结果缓存。
- impact token 只确认破坏性影响，不保证请求幂等；active 唯一约束是并发最终裁决。

### 7.4 运行中变化

- 剧本 revision 变化：不阻止当前 task；继续使用旧剧本，成功 marker 写旧 revision，显示旧剧本角标。
- 风格或模板变化：不阻止当前 task；继续使用快照文本，只影响后续任务。
- 新增资产：不扩充本次 prompt/schema，不阻止提交。
- 入队资产被编辑：模型仍使用快照 name/description；只要 id 仍属本项目且类型合法即可提交。资产 revision 的差异不自动改写模型输出。
- 入队资产被删除、移出项目或变成非法类型：若模型输出引用该 id，整任务 failed，旧结构不动；未引用则不因该资产变化拒绝。
- 待替换 shots/clips/video/override 行集合、媒体行所属 clip、媒体相对路径，或任一 shot/clip revision 与 `replacement_snapshot` 不一致：task failed，旧/新结构都不部分写入，要求用户重新 impact/generate。只比较计数不合格。

## 8. 分镜与资产级联

### 8.1 编辑分镜

§3.4 的任一实际文本或绑定变化都必须在同一事务中把该 Shot 标为 changed，并把所有包含它的 Clip 标为 stale。`generation_state` 保持当前值；现有视频和 override 文件不删；clip revision 不因 freshness 派生态单独增加。

### 8.2 编辑/换图/删除资产

- 资产 name/description 实际变化，或 current image 实际变化：所有绑定该资产的 Shot 各自 `revision += 1/status=changed`；包含这些 Shot 的 Clip 设 stale；不删任何文件。
- no-op 资产 PATCH/current 设置不触发级联。
- 删除资产：在删除前确定所有绑定 Shot/相关 Clip；解绑该 asset，受影响 Shot 各递增一次 revision 并 changed，相关 Clip stale；资产图片继续按 C003 移入 trash。
- 同一操作通过多个绑定命中同一 Shot/Clip 时只处理一次。
- C006 不实现 R12 槽位快照展示、启停/override 处置 API 或 R10；现有外键 `asset_id SET NULL` 只保留数据库完整性，完整槽位行为延后 C008-C009。

### 8.3 既有删除能力兼容

现有 episode/project DELETE 在 C006 数据可达后必须能按当前已有实体级联删除其 shots/shot_assets；若夹具中已有属于该 episode 的 clips/clip media，则按 R3 同一删除与 trash 纪律清理。不得新增新的删除端点或扩大到其他项目/episode。删除是否被当前 change 尚不可达的外部注入后续实体阻止，继续沿用 C002/C003 的 409 回滚语义。

## 9. UI 合同

### 9.1 剧本页生成入口与确认

- 集工作区剧本只读状态提供明确按钮“生成分镜”；正在编辑未保存剧本时不得以旧数据库内容发起，用户先保存。
- 点击先调用 impact。0/0 时直接提交 `{}`；非零时弹窗逐项显示“将删除片段 X 个、视频 Y 个”，只有明确确认才携 token 提交；取消弹窗不创建 task。
- 202 后显示 task id 和进入现有任务中心的入口，不自动离开剧本页。active 409 或其他错误直接显示 `detail.message`，不自动重发。

### 9.2 分镜页

- 集工作区现有“分镜”标签展示真实 GET 结果，按 order 呈现镜号、时长、景别、运镜、描述、台词、绑定资产规范名和状态。
- 提供对 §3.4 五类字段的编辑及项目 `character/scene` 资产绑定选择；不提供新增、删除、复制、拆分、合并、拖拽排序或 duration 编辑。
- `status=changed` 显示 changed 角标。
- 以当前绑定资产类型计数：场景数为 0 显示普通提示“未绑定场景”；场景数不少于 2 显示警示“绑定多个场景，需修正”；场景数等于 1 不显示场景角标。角标不禁用保存。
- API 保存失败时保留用户编辑态并直显 `detail.message`；成功后以 API 返回真相刷新该项。

### 9.3 旧剧本角标

- 判定精确为：`shots_generated_script_revision != null && shots_generated_script_revision < script_revision`。
- 成立时，在剧本页和分镜页可见位置显示“分镜基于旧剧本”。marker 为 null 或等于当前 revision 时不显示。
- 页面进入、剧本保存、标签切换或任务完成事件后重新读取数据库真相；C006 不新增周期轮询。

## 10. 错误码矩阵

所有 HTTP 错误体固定为：

```json
{"detail":{"code":"non_empty_code","message":"可直接展示的中文说明"}}
```

| HTTP | `detail.code` | 触发条件 | 不得替代为 |
|---|---|---|---|
| 404 | `not_found` | episode/shot id 在当前数据库不存在 | 403、409、422 |
| 403 | 不使用 | v1 无用户/权限系统，不存在“资源存在但无权访问” | 用 403 隐藏 404 |
| 405 | `method_not_allowed` | 已知路径使用未授权方法 | 404、422 |
| 409 | `conflict` | R1 无资产；impact token 缺失/过期/伪造/跨集/影响不匹配；同集已有 active gen_shots；风格/模板缺失或模板占位符不合法；当前合法请求被状态/前置条件阻止 | 422、200 伪成功 |
| 422 | `validation_error` | path/body 类型或 JSON 形状错误、impact 有非空 body、generate body/token 类型/未知字段错误、Shot PATCH 空对象/未知字段/枚举/资产 id/类型/项目归属/重复绑定校验失败 | 409 |
| 500 | `internal_error` | 同步 API 边界未预期服务端错误；服务端记录 traceback | 200、409、422 |

404 与 403 只按资源存在/鉴权判定；本地单操作者无鉴权，未知资源为 404。409 与 422 只按“格式合法的请求是否被当前状态阻止”判定：无资产、token、active 或缺运行配置是 409；请求本身字段/类型/业务输入不合法是 422。单 Shot 0/多场景明确不是错误。

已返回 202 后的 wake/vLLM/超时/JSON/schema/order/非法模型 asset id/替换快照竞态/数据库/文件失败都写 task failed 和完整 `error_msg`，不转换为原 POST 的同步 4xx/5xx，也不 fallback 为 `shots=[]` 或部分分镜。

## 11. Non-Goals 与后续归属

| Non-Goal | 归属 |
|---|---|
| Z-Image/Comfy、资产出图、input_hash、GPU sleep/free 调度 | C007 |
| clip preview/创建、R5/R5a-R8 最终裁决、参考选择、槽位编排与 R12 UI/API | C008 |
| gen_clip_video、MiniMax H3、R5/R5a/R10 入队复检、take/actual_duration/完成反竞态 | C009 |
| 导演台“一带两轨一板” | C010 |
| 任务中心历史/过滤完善与全局 UI/UX 专题 | C011 |
| 发布级全链路、重启/trash/级联矩阵/竞态总验收 | C012 |
| 候选分镜版本、分镜增删/拆分/合并/排序、资产别名/合并、风格/模板版本化、generation_runs、continuity、context loop、fl2v 读写、音频 | v1 明确排除，不延后到任何 change |

## 12. 向后兼容与迁移影响

- 数据库：零 migration，零表/列/索引/枚举变化；复用 C001 已有 Shot/Clip/Task/marker 结构。
- API：新增 impact、generate-shots、shots GET/PATCH；不改变 C005 generate-assets 合同。现无旧版 C006 API 需要兼容，不加别名或双路径。
- 数据：C006 首次让已有空 shots 表成为正常可达数据；成功重生成是 R3 明示覆盖，不保留旧格式/候选版本。
- 模板：正式验收库把 `script2shots` 从占位更新为 §5.1，只影响此后入队任务；干净 pytest 库仍使用 migration 占位。无模板 migration 或版本记录。
- UI：在既有集工作区增量提供生成/分镜能力，保留 C002-C005 剧本、资产、导航和任务中心行为。

## 13. 数据格式总约定

- id/revision/order/count 为 JSON integer；duration/progress/temperature 为 JSON number；不得以字符串传输。
- 时间只在已有实体响应中使用带时区 UTC ISO 8601；token TTL 使用整数秒，不返回金额或本地化日期。
- 枚举均为本文列出的封闭值，大小写和中文精确匹配；未知值不宽容接受。
- 新增列表只有 shots GET，固定全量排序，无分页/过滤；impact 和生成动作无查询参数。
- PATCH 为部分更新且不接受 null；未出现字段保持不变，出现字段按原值处理，不隐式 trim。

## 14. 验收标准

- **AC-01 范围与迁移**：C006 零 migration/schema 变化；无围栏机制、后续 clip/image/video/导演台实现、自动重试、隐藏 fallback 或第二业务 prompt。
- **AC-02 外部 gate**：正式验收库 `script2shots` 与 §5.1 逐字一致且可读回；真实 vLLM/model/wake 可达，并用 C006 动态 schema 成功返回封闭 JSON；不得用占位库或 mock 冒充。
- **AC-03 R1 与 impact**：0 资产时 impact 仍准确、只读返回影响，但 generate 为结构化 409 且不创建 task；非空影响发 600 秒 token，空影响返回 null token/TTL。
- **AC-04 token 绑定**：缺失、过期、跨集、伪造或结构影响变化 token 均 409；仅计数相同但 clip/video/revision 集变化也不能通过；重启后旧 token 失效。
- **AC-05 生成 API 与 active 去重**：合法请求返回精确 task_id、正确 queued task；同 episode 并发只产生一条 active gen_shots，败者 409；终态后显式重跑可新建。
- **AC-06 快照与渲染**：payload 顶层精确三键；剧本/修订/风格/模板/四字段资产/单 user prompt/模型/0.2/动态 schema/替换结构/source revisions 来自同一入队真相，`input_hash=null`，token 不入 payload。
- **AC-07 动态 guided_json**：asset enum 精确等于快照 id；字段全 required、顶层/item 封闭、duration 1..5、景别/运镜封闭；发往 vLLM 的 schema 不含其 grammar 未实现的 `uniqueItems`，重复 asset id 由后端硬校验拒绝；真实请求不退回自由文本。
- **AC-08 输出硬校验**：order 必须精确 1..N；非法结构、枚举、时长或不存在/跨项目/已删除 asset id 使 task failed，旧结构无损且无部分新 Shot；0/多场景不失败。
- **AC-09 R3 成功覆盖**：新输出先完整生成/校验，随后一次成功替换本集旧 shots，删除全部 clips/关系/槽位/videos，媒体入 trash，marker 写快照修订，新 Shot `normal/revision=1`，task done。
- **AC-10 R3 失败与取消**：vLLM/schema/数据库/文件失败不改变旧 shots/clips/media/marker；取消先赢无业务写入，提交先赢则结果与 done 同一胜方；失败不重试且保留完整原因。
- **AC-11 分镜读取编辑**：GET 稳定排序且字段/时间/枚举精确；PATCH 只接受五类字段，no-op 不增 revision，实际变化 changed/revision+1 并将相关 clip stale，文件和 generation_state 不变。
- **AC-12 资产级联**：资产文本/current 实际变化使绑定 Shot changed、相关 Clip stale；删除资产先解绑再 changed/stale，图片入 trash；同一对象一次操作只递增一次。
- **AC-13 场景质量角标**：生成和 PATCH 都接受零场景/多场景；UI 分别显示提示/警示且不禁用保存，单场景无角标。
- **AC-14 旧剧本竞态**：运行中剧本由 N 改 N+1 时模型仍收到 N，成功 marker=N，新 shots 正常但页面显示“分镜基于旧剧本”；显式重生成 N+1 后角标消失。
- **AC-15 UI 闭环**：剧本页先 impact、非空影响明确确认后携 token，能看到 task id/任务中心；分镜页呈现真实数据、编辑/绑定/changed/角标，错误直显 `detail.message`，无假数据或自动重发。
- **AC-16 真实模型质量**：用 C005 已生成资产的同一段剧本跑真实 gen_shots 并逐镜核对合法/准确绑定；另用含跨地点转场和纯特写的剧本，确认转场拆成两镜各绑各场景、纯特写允许零场景。不得用后端拆镜/重绑或 mock 代替。
- **AC-17 错误一致性**：所有同步错误保持固定结构，404/403 与 409/422 按 §10；异步错误只落 task failed，不伪装同步成功。
- **AC-18 删除兼容**：生成分镜后 episode/project 既有删除仍能处理 C006 可达 Shot 和 R3 媒体；外部注入的未授权后续实体仍按既有 409/回滚语义。
- **AC-19 追溯与回归**：新增自动测试全部归属 tasks 指定 TRACEABILITY 行并由 Sol 回填真实 node ID；既有测试未修改/弱化；完整 pytest、前端 build、Alembic current/check 与范围扫描通过。
