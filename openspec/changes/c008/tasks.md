# C008 M4 clip 预检创建与槽位 Tasks

执行纪律：严格按依赖顺序一次完成一个 checkbox；每项验收通过并保留原始输出后才可勾选。除本文件明确列出的新 C008 测试外，不得修改、删除、跳过或弱化任何既有测试。实现阶段若发现 spec 与代码/PRD 出现会改变行为的新冲突，停止并报告，不继续后续 task。

- [x] **T0 — 固定 C008 基线与隔离 PostgreSQL 验收环境**
  - 依赖：无。
  - 交付：确认当前 HEAD 的 C007 归档、C008 零 migration 基线和 §12.4 PostgreSQL 门槛；使用全新唯一数据库，不停止/污染用户现有生产数据，不探测或要求 vLLM/Comfy/MiniMax。
  - R：无；PRD §4、§10、§11 M4、§12.4；ROADMAP C008 前序 C007/外部依赖“无新增”。
  - 验收方式与命令（PowerShell，数据库名每次换新；不得打印 DSN）：

    ```powershell
    git log -1 --oneline
    Test-Path openspec/archive/C007/spec.md
    Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -InformationLevel Quiet
    Set-Location D:\ai_drama_studio\backend
    $databaseLine = Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
    $sourceUrl = $databaseLine.Substring('DATABASE_URL='.Length)
    $c008Db = 'ai_drama_studio_c008_t0_20260831'
    $env:DATABASE_URL = $sourceUrl
    $env:C008_DB_NAME = $c008Db
    @'
    import asyncio, os
    from urllib.parse import urlsplit, urlunsplit
    import asyncpg
    async def main():
        parsed = urlsplit(os.environ["DATABASE_URL"].replace("+asyncpg", "", 1))
        admin = urlunsplit((parsed.scheme, parsed.netloc, "/postgres", parsed.query, parsed.fragment))
        connection = await asyncpg.connect(admin)
        try:
            if await connection.fetchval("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=$1)", os.environ["C008_DB_NAME"]):
                raise RuntimeError("C008 database name already exists; choose a fresh name")
            await connection.execute(f'CREATE DATABASE "{os.environ["C008_DB_NAME"]}"')
        finally:
            await connection.close()
    asyncio.run(main())
    '@ | python -
    $env:DATABASE_URL = $sourceUrl -replace '/[^/]+$', ('/' + $c008Db)
    python -m alembic upgrade head
    python -m alembic current
    python -m alembic check
    git diff --name-only bffb69b..HEAD -- backend/alembic/versions
    git diff --name-only -- backend/alembic/versions
    ```

    期望：HEAD/归档存在；5432 为 `True`；upgrade 成功；current 为唯一 `6b8e3f0a1d24 (head)`；check 为 `No new upgrade operations detected.`；两个 migration diff 命令均无输出。若数据库名已存在必须换名，不复用。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用；这是 AC-01/AC-02 的外部/范围门槛，替代验收已在 spec §11 固定。

- [x] **T1 — 交付可复用的 clip 纯规则裁决**
  - 依赖：T0。
  - 交付：在现有 service 边界内实现无 I/O 的选择规范化、R5 连续、R5a 场景、R6 时长/建议、R7 候选排序/默认选择、R8 warnings；补齐 `1 <= SLOT_HARD_LIMIT <= 9` 启动校验。只新增职责名文件，不建 registry/helper 层。
  - R：R5、R5a、R6、R7、R8；PRD §3.4、§10。
  - 验收方式与命令：新增 `backend/tests/unit/test_c008_clip_rules.py`，覆盖规范化顺序、全部 closed violation/warning code、人物首次出场/同镜 id/场景垫底、ceil+clamp、候选超限但合法子集可选、soft/hard 配置边界；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/unit/test_c008_clip_rules.py
    ```

    期望：全部通过；测试不访问数据库、文件、网络，不识别测试数据分支。
  - 计划测试层级：纯函数。
  - 追溯行：`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`；`R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH`；`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`。

- [x] **T2 — 交付只读 clip preview API**
  - 依赖：T1。
  - 交付：新增 clips request/response schema、service 查询和 router，注册 `POST /api/episodes/{id}/clips/preview`；使用生产 PostgreSQL 真相调用 T1 规则，返回 spec §3.4 精确字段、顺序与 message，不写 Clip/关系/槽位，不发 token。
  - R：R5、R5a、R6、R7、R8；PRD §3.4、§5 片段。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_clip_preview.py`，覆盖 200 violations、零写入、未知/跨集/重复/空/strict 类型 404/422、时长和候选精确响应；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_clip_preview.py
    ```

    期望：全部通过；每个错误体均为非空 `detail.code/message`，preview 违规不误用 422。
  - 计划测试层级：API 集成。
  - 追溯行：`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`；`R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH`；`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`。

- [x] **T3 — 原子创建 Clip/ClipShot/ClipRefSlot 并交付 list/detail**
  - 依赖：T2。
  - 交付：实现正式 POST 的事务内当前真相复检、服务端规范排序、默认 duration、固定快照和三类行原子写入；实现 episode clip list 与 clip detail 的精确公开表示和派生时间轴顺序。不得接受 preview token、客户端 slot_no、clip order 或预留 generation_mode。
  - R：R5、R5a、R6、R7、R8；PRD §3.4、§4 clips/clip_shots/clip_ref_slots、§5 片段。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_clip_create.py`，覆盖合法 201、默认值/明确值、候选超限后合法子集、非候选/规则/strict body 422、写入阶段失败全回滚、list/detail 字段与稳定排序；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_clip_create.py
    ```

    期望：全部通过；成功行的 position/slot_no 连续且快照精确；失败时 Clip/ClipShot/ClipRefSlot 均零新增；公开响应无 cache/hash/path。
  - 计划测试层级：API 集成。
  - 追溯行：`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`；`R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH`；`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`；`C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`。

- [x] **T4 — 封闭并发创建的 R5 独占竞态**
  - 依赖：T3。
  - 交付：按稳定顺序锁定所选 Shot/现有关系，并把数据库唯一冲突翻译为同一 R5 结构化 422；不得用进程内锁、全局 registry、retry 或 409 掩盖竞态。
  - R：R5；PRD §3.4 R5、§4 `clip_shots.shot_id UNIQUE`、§5 409/422 语义。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_clip_concurrency.py`，使用至少两个独立 AsyncSession/数据库连接和屏障，同时创建相同及部分重叠选择；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_clip_concurrency.py
    ```

    期望：每组精确一个完整成功、其他为 422；每个 Shot 至多一条关系，无孤儿 Clip/Slot、死锁、409 或自动重试。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`。

- [x] **T5 — 交付 Clip PATCH 的输入修订状态机**
  - 依赖：T3。
  - 交付：实现 `PATCH /api/clips/{id}` 对 `user_note`/`requested_duration` 的严格部分更新、null/no-op、配置边界、并发串行裁决；实际变化一次 revision+1/stale，generation_state/Shot/Slot/文件不变。
  - R：R6；无其他直接 R 编号，PRD §3.2 修订与两维状态、§5 片段 PATCH。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_clip_patch.py`，覆盖字段组合、clear/no-op、MIN/MAX、null/bool/float/string/unknown/empty 422、未知 404、一次请求只增一次 revision；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_clip_patch.py
    ```

    期望：全部通过；响应精确复用 Clip 公开合同。
  - 计划测试层级：API 集成。
  - 追溯行：`R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH`；`C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`。

- [x] **T6 — 交付固定槽位读取与 R9 图片解析**
  - 依赖：T3。
  - 交付：实现 `GET /api/clips/{id}/slots` 的固定字段/顺序、asset_deleted、soft warning 和 `override > asset current > null` 解析；只返回同源媒体 URL，不返回 path/hash，不执行 R10。
  - R：R7、R8、R9、R12；PRD §3.4、§5 槽位、§9 交接。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_slots.py`，覆盖槽位顺序/快照、override/current/missing 组合、enabled 不改变解析、软 warning、未知/内部不一致错误；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_slots.py
    ```

    期望：全部通过；URL 只为 `/media/slot-overrides/{slot_id}` 或 `/media/asset-images/{image_id}`，无内部路径。
  - 计划测试层级：API 集成。
  - 追溯行：`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`；`R9 槽位取图优先级：override 图优先于资产当前图`；`R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`。

- [x] **T7 — 交付槽位 enabled mutation**
  - 依赖：T6。
  - 交付：实现 slot PATCH 的严格 JSON 模式；只改目标 enabled，no-op 不变，实际变化使 Clip revision+1/stale，返回目标 slot 与最新 warnings。不得在此模式接受 multipart/file/override 字段。
  - R：R8；无其他直接 R 编号，PRD §3.2 Clip revision、§3.4 槽位启停、§5 槽位 PATCH。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_slot_enabled.py`，覆盖 true/false、no-op、其他槽位不动、soft warning 出现/消失、绝对 slot path 1..9、404/422；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_slot_enabled.py
    ```

    期望：全部通过；任何实际请求只增加一次 Clip revision，generation_state/Shot/文件不变。
  - 计划测试层级：API 集成。
  - 追溯行：`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`。

- [x] **T8 — 交付 override 上传/替换/清除、ID 媒体与同步补偿**
  - 依赖：T6、T7。
  - 交付：实现 spec §5.3 的严格 multipart 二选一、三种图片校验、临时/正式/相对路径、原 bytes sha256、原子落位、替换/清除与 D-010 同步补偿；实现 `/media/slot-overrides/{slot_id}`。不得转码、使用用户文件名、后台补偿或 override 历史表。
  - R：R9；无其他直接 R 编号，PRD §2.1(7,12)、§3.2、§5 上传/媒体、§6.4、§10；D-002、D-003、D-010。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_slot_overrides.py`，通过生产 API、真实 PostgreSQL 和隔离 DATA_DIR 覆盖 png/jpg/webp、所有 multipart/内容错误、首次/同 bytes/替换/清除、媒体 404/500、rename 后 DB 失败及恢复失败；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_slot_overrides.py
    ```

    期望：全部通过；temp 始终清理，正常失败恢复旧 DB/文件真相，补偿失败同时保留主/补偿原因，绝无 200/占位/重试。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`R9 槽位取图优先级：override 图优先于资产当前图`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`。

- [x] **T9 — 补齐资产删除的完整 R12 槽位处置**
  - 依赖：T6、T8。
  - 交付：在既有资产删除显式事务中加入直接 ClipRefSlot 引用集合，与 C006 Shot 绑定集合去重后 stale；保留 FK `SET NULL`、名称/类型快照、slot_no、enabled、override 和 Clip revision/state。不得自动停用、删槽位、删 override 或选替代资产。
  - R：R12；PRD §3.3 删除资产、§3.4 R12、§5 Asset DELETE。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_asset_slot_cascade.py`，覆盖同一资产经 Shot+多个 Slot 重复命中、已从 Shot 解绑但仍在 Slot、带/不带 override、其他 Clip/Slot 不动；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_asset_slot_cascade.py
    ```

    期望：全部通过；slot asset_id 精确 null，相关 Clip stale且 revision/state 不变，快照/override/编号/enabled 保留，图片仍按既有路径入 trash。
  - 计划测试层级：API 集成。
  - 追溯行：`R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10`；`§3.3 删除资产：解绑并 changed、相关片段 stale、槽位按 R12 处置、资产图片入 trash`。

- [x] **T10 — 封闭 create 与 Shot PATCH/Asset DELETE 的来源竞态**
  - 依赖：T4、T9。
  - 交付：统一 C008 涉及的稳定锁顺序与提交后复检，使 create 与现有 Shot PATCH/Asset DELETE 竞争时只出现 spec §6 的串行化结果；不得用 broad retry、进程锁或吞掉 PostgreSQL 错误。
  - R：R5、R5a、R7、R12；PRD §3.2、§3.3、§3.4。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_clip_source_races.py`，用独立连接和事件屏障分别固定两个提交先后，断言候选/槽位快照、Shot/Clip/Slot/FK 结果；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_clip_source_races.py
    ```

    期望：全部通过；无混合快照、死锁、悬空非 null FK、漏 stale 或自动重试。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`；`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10`。

- [x] **T11 — 交付 Clip DELETE 的释放、trash 与失败恢复**
  - 依赖：T8、T9。
  - 交付：实现 `DELETE /api/clips/{id}`，显式锁定/删除 ClipShot、Slot、既有 ClipVideo、Clip，释放 Shot 且不改其值；override/video 文件按生产相对路径进 trash，任何数据库失败恢复本次移动。不得依赖未验证的 CASCADE 丢失媒体引用。
  - R：无；PRD §3.3“删除片段”、§5 Clip DELETE、§6.4 文件纪律；D-003、D-010。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_clip_delete.py`，覆盖多个 Shot、override、注入 ClipVideo、204 空 body、可重新组片、缺/坏路径、部分移动失败、数据库失败和恢复失败；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_clip_delete.py
    ```

    期望：正常路径 DB 全删且文件在 trash、Shot 原值；任一失败不返回 204，成功补偿恢复旧真相，补偿失败完整可诊断。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`；`§3.3 删除片段：其分镜释放、片段删除、视频移入 trash`。

- [x] **T12 — 封闭 C008 OpenAPI、content-type 与错误语义**
  - 依赖：T5、T7、T8、T11。
  - 交付：核对所有 C008 路由只接受 spec 指定 JSON/multipart，未知资源/输入/内部错误稳定映射 404/422/500；确认正常业务无新增 409，且 OpenAPI/handler 不含 C009 endpoint、MiniMax 或 `gen_clip_video` 注册。
  - R：R5、R5a、R6、R7、R8、R9、R12；PRD §5 通用错误体、§9 前端直显。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_contract_errors.py`，只覆盖 TRACEABILITY 已列 C008 API/slot 行的协议边界，不重复测试纯规则；运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_contract_errors.py
    ```

    另人工检查：

    ```powershell
    @'
    from app.main import create_app
    app = create_app()
    paths = sorted(app.openapi()["paths"])
    print("\n".join(path for path in paths if "clip" in path or "slot" in path))
    print(sorted(app.state.task_handlers))
    '@ | python -
    ```

    期望：只出现 C008 spec 授权的 clip/slot/slot media 路由；handlers 精确仍为 `gen_assets/gen_asset_image/gen_shots`，无 `gen_clip_video`。
  - 计划测试层级：API 集成。
  - 追溯行：`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`；`R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH`；`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`；`R9 槽位取图优先级：override 图优先于资产当前图`；`R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10`；`C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`。

- [x] **T13 — 回填追溯并执行 C008 全量收口验收**
  - 依赖：T1-T12 全部完成且各自定向验收通过。
  - 交付：把所有新测试的真实 pytest node ID 回填到本 tasks 引用的 TRACEABILITY 行；核对每个新用例至少归属一行、无未授权测试、既有测试零修改；运行定向/全量/Alembic/build/diff/scope 命令并保留原始输出。失败时不勾选、不提交伪完成。
  - R：R5、R5a、R6、R7、R8、R9、R12；PRD §3.3、§3.4、§5、§11 M4。
  - 验收方式与命令（继续使用 T0 的隔离 `DATABASE_URL`）：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/unit/test_c008_clip_rules.py tests/api/test_c008_clip_preview.py tests/api/test_c008_clip_create.py tests/api/test_c008_clip_concurrency.py tests/api/test_c008_clip_patch.py tests/api/test_c008_slots.py tests/api/test_c008_slot_enabled.py tests/api/test_c008_slot_overrides.py tests/api/test_c008_asset_slot_cascade.py tests/api/test_c008_clip_source_races.py tests/api/test_c008_clip_delete.py tests/api/test_c008_contract_errors.py
    python -m pytest -q
    python -m alembic current
    python -m alembic check
    Set-Location D:\ai_drama_studio\frontend
    npm run build
    Set-Location D:\ai_drama_studio
    git diff --check
    git diff --name-only bffb69b..HEAD -- backend/alembic/versions frontend
    git diff --name-only -- backend/alembic/versions frontend
    git diff --name-only bffb69b -- backend/tests | Select-String -Pattern 'test_c00[1-7]|test_system.py|test_task_queue.py'
    git diff --unified=0 bffb69b -- backend frontend | Select-String -Pattern 'minimax|gen_clip_video|generate-video|current-video|clip-videos|context_loop|fl2v|audio|generation_runs|continuity|retry|fallback'
    rg -n "^\| (R5 |R5a |R6 |R7 |R8 |R9 |C008 |R12 |§3\.3 删除片段)" openspec/TRACEABILITY.md
    ```

    期望：定向与完整 pytest 全通过；current/check/build/diff-check 成功；migration/frontend diff 均无输出；既有测试扫描无输出；范围扫描不得出现新增 C009+/围栏/retry/fallback 实现（合法的既有代码/文档上下文必须逐项人工解释，不能静默忽略）；所有相关追溯行不再以 C008 部分 `待填` 结束。
  - 计划测试层级：不新增自动测试。
  - 层级说明：本 task 只运行并审计 T1-T12 已计划的全部层级，不再创建用例。
  - 追溯行：`R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`；`R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH`；`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`；`R9 槽位取图优先级：override 图优先于资产当前图`；`R12 删除资产后的槽位：asset_id 置 NULL、快照和槽位号保留、片段 stale，不停用或无 override 时再次生成触发 R10`；`C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`；`§3.3 删除片段：其分镜释放、片段删除、视频移入 trash`。

## 复审修复（以已提交基线 `a35344d` 为起点）

以下 task 只修复 C008 复审已证实的行为/证据缺口。继续保持零 migration；不改槽位表、槽位创建排序和快照落库语义；不实现 C009 序列化器、MiniMax H3、`gen_clip_video`、prompt 或 input hash。四个经 `.work/c008/probe-*.py` 确认的 BLOCK 必须各有新增回归用例，不得修改任何已有测试文件。

- [x] **T14 — 在查库前封闭 C008 整数 ID 边界**
  - 依赖：T13 的已提交实现与复审 probe 证据。
  - 交付：所有 C008 `episode_id`/`clip_id`/slot media `slot_id` path 参数以及 create/preview 的 `shot_ids`/`reference_asset_ids` 在 FastAPI/Pydantic 边界限定为 PostgreSQL signed INTEGER（`-2147483648..2147483647`；原本要求 positive 的 body id 仍必须 positive）。越界固定返回 422/`validation_error`，不执行 SQL；范围内未知资源仍返回 404/`not_found`。不改 schema/migration。
  - R：body 的 Shot/Asset 约束对应 R5、R7；path 整数边界 R：无，依据 PRD §4 的 INTEGER 模型、§5 通用错误体与输入校验语义。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_integer_bounds.py`，通过生产 app、全新隔离 PostgreSQL 和 SQLAlchemy 查询计数器（只在测试中挂载，不增生产 test hook）遍历 C008 所有相关路由；对上下界外值断言精确错误体且 SQL 计数为 0，对范围内不存在值断言精确 404。不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_integer_bounds.py
    ```

  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C008 复审 API 敌意输入边界：所有 episode/clip/slot 路径 ID 在访问 PostgreSQL 前拒绝超出有符号 INTEGER 的值，create/PATCH user_note 拒绝 U+0000，且不产生数据库副作用`；body id 同时归属 `R5 连续与独占：分镜 order_index 严格连续且单分镜至多属于一个片段，违规 422`、`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`。

- [x] **T15 — 在 schema 边界拒绝 `user_note` 中的 U+0000**
  - 依赖：T14。
  - 交付：Clip create/PATCH 的 `user_note` 含 U+0000 时在任何 SQL 前返回 422/`validation_error`；null、空串和不含 U+0000 的字符串仍原样保存，不 trim、不吞 PostgreSQL 编码异常。不改 schema/migration。
  - R：无；依据 PRD §5 Clip create/PATCH 请求与通用 422 语义。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_user_note.py`，用生产 app、真实隔离 PostgreSQL 和查询计数器分别命中 create/PATCH，断言精确 422 错误体、SQL 计数为 0、三类 C008 表计数不变；另用独立正常请求证明空串不被改写。不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_user_note.py
    ```

  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C008 复审 API 敌意输入边界：所有 episode/clip/slot 路径 ID 在访问 PostgreSQL 前拒绝超出有符号 INTEGER 的值，create/PATCH user_note 拒绝 U+0000，且不产生数据库副作用`。

- [x] **T16 — 将 Pillow 解压炸弹纳入 override 422 内容校验**
  - 依赖：T15。
  - 交付：公共图片验证边界将 Pillow `DecompressionBombError`（以及该限制明确升格为异常的情形）映射为 422/`validation_error`；上传 temp 清理，正式路径、Slot/Clip、trash 均不变。不降级解码、不转码、不 fallback。
  - R：无；依据 PRD §5 override 上传输入、§6.4 文件纪律与通用 422 语义。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_override_image.py`，使用只依赖图片头尺寸的有限 fixture 触发生产 Pillow 限制，不分配巨幅像素数据，不在生产代码识别测试值；通过生产 multipart/API、真实隔离 PostgreSQL 和隔离 `DATA_DIR` 断言精确 422 及所有无副作用观测点。不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_override_image.py
    ```

  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C008 复审 override 敌意图片输入：Pillow 解压炸弹等非法图片返回 422，temp 被清理且正式文件、数据库与 trash 不变`。

- [x] **T17 — 使 canonical trash 同路径的合法生命周期可重复执行**
  - 依赖：T16。
  - 交付：同格式 override 实际替换后，后续清除或 Clip DELETE 将当前正式文件原子替换到同一 canonical trash 路径；该位置最终精确保留本次最新移入 bytes，不生成 hash/时间戳/版本后缀，不将合法同名当成 500。保留 D-010 的 DB 失败补偿与“主错误+恢复错误”可诊断性。
  - R：无；依据 PRD §3.3 删除片段、§5 override 清除/替换、§6.4 文件与 trash 纪律，以及 DECISIONS D-010。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_trash_lifecycle.py`，使用生产 API、真实隔离 PostgreSQL、隔离 `DATA_DIR` 和两份同格式不同 bytes，分别验收“上传 A → 替换 B → 清除”和“上传 A → 替换 B → 删 Clip”；断言响应、DB、formal/temp、canonical trash 的精确 bytes 及不存在其他版本文件。同时复跑已有补偿用例，不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_trash_lifecycle.py tests/api/test_c008_slot_overrides.py tests/api/test_c008_clip_delete.py
    ```

  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C008 复审同路径 trash 生命周期：同格式 replacement/clear/delete 在合法同名 canonical trash 已存在时继续成功，canonical trash 保留本次最新移入文件，不创建历史版本路径，失败补偿仍一致`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`；`§3.3 删除片段：其分镜释放、片段删除、视频移入 trash`。

- [x] **T18 — 补齐合法非默认 Settings 触发证据**
  - 依赖：T17。
  - 交付：不改 Settings 语义；新增独立回归证明 `1 <= SLOT_SOFT_LIMIT <= SLOT_HARD_LIMIT <= 9` 的非默认组合可构造成功并被 C008 规则使用，且已有 `10`/软上限大于硬上限的启动失败证据仍有效。
  - R：R8；依据 PRD §3.4 R8、§10 环境变量。
  - 验收方式与命令：新增 `backend/tests/unit/test_c008_review_settings.py`，直接构造生产 `Settings` 并调用生产规则函数，断言非默认 hard/soft 下的精确默认选择数、`selected_by_default` 和 warning 边界，候选全量列表不被截断；不改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/unit/test_c008_review_settings.py tests/unit/test_c008_clip_rules.py
    ```

  - 计划测试层级：纯函数。
  - 追溯行：`C008 复审精确触发条件：两个单分镜场景跨场、合法非默认 Settings、时长 MIN/MAX、建片后活资产变更与精确错误 code 均按 C008 公开合同可观测`；`R8 数量提示：候选超过 9 时要求精简至合法子集、最终选择超过 9 阻止创建，启用槽位超过 4 只给软提示`。

- [x] **T19 — 补齐“两个单场景分镜跨场”的 R5a 证据**
  - 依赖：T18。
  - 交付：不改 R5a 语义；新增独立 API 用例，精确触发“Shot A 只绑 Scene A，Shot B 只绑 Scene B”，补齐既有用例未证明的整体跨场分支。
  - R：R5a；依据 PRD §3.4 R5a、§5 preview/create。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_scene_boundary.py`，用生产 API 与真实隔离 PostgreSQL，断言 preview 为 200、violations 精确只含整体 `multiple_scenes` 对应 closed code、零写入；create 为精确 422/`validation_error` 且 Clip/ClipShot/Slot 计数不变。不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_scene_boundary.py
    ```

  - 计划测试层级：API 集成。
  - 追溯行：`C008 复审精确触发条件：两个单分镜场景跨场、合法非默认 Settings、时长 MIN/MAX、建片后活资产变更与精确错误 code 均按 C008 公开合同可观测`；`R5a 同场景：去重后至多一个场景，零场景合法，双场景分镜不可组入，生成前必须复检`。

- [x] **T20 — 补齐 requested_duration 精确 MIN/MAX PATCH 证据**
  - 依赖：T19。
  - 交付：不改 R6 语义；用真实 API 补齐 `CLIP_MIN_SECONDS` 与 `CLIP_MAX_SECONDS` 均可 PATCH，且每次实际变更只增一次 revision、按原值精确持久化的证据。
  - R：R6；依据 PRD §3.4 R6、§5 Clip PATCH。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_duration_boundaries.py`，用生产 API 与真实隔离 PostgreSQL，对同一 Clip 先后 PATCH MIN/MAX，每次同时断言响应值、DB 值、revision 增量、`stale`、Shot/Slot 与文件不变；不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_duration_boundaries.py
    ```

  - 计划测试层级：API 集成。
  - 追溯行：`C008 复审精确触发条件：两个单分镜场景跨场、合法非默认 Settings、时长 MIN/MAX、建片后活资产变更与精确错误 code 均按 C008 公开合同可观测`；`R6 时长：最大值硬校验、最小值软提醒、默认 requested_duration 计算及合法 PATCH`。

- [x] **T21 — 补齐建片后活资产变更的 C008 槽位证据**
  - 依赖：T20。
  - 交付：不改槽位表、创建逻辑或快照列。新增独立 API 回归：经正式 create 落槽后修改活资产 name/description 并切换 current image，槽位 name/type 快照与 slot_no 仍为建片时值，R9 的 `asset_current` URL 跟随当前图。本 task 不断言 C009 `{{references}}`、活描述或 input hash。
  - R：R7、R9；资产级联状态依据 PRD §3.3，槽位读取依据 §3.4 R7/R9 与 §5。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_slot_snapshots.py`，通过生产 Asset/Clip API、真实隔离 PostgreSQL 与隔离 `DATA_DIR` 完成上述序列；断言公开 slots JSON、DB 快照、R9 URL、Clip 精确为 stale 且 revision 不变，以及槽位数/顺序的精确值。不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_slot_snapshots.py
    ```

  - 计划测试层级：API 集成。
  - 追溯行：`C008 复审精确触发条件：两个单分镜场景跨场、合法非默认 Settings、时长 MIN/MAX、建片后活资产变更与精确错误 code 均按 C008 公开合同可观测`；`R7 参考资产与槽位：候选并集、首次出场确定性排序、选择子集 1..9、槽位创建后不重排`；`R9 槽位取图优先级：override 图优先于资产当前图`。

- [x] **T22 — 分别证明 Clip/ClipShot/ClipRefSlot 写入阶段的原子回滚**
  - 依赖：T21。
  - 交付：不为测试拆分或改写正式创建顺序；新增独立回归，在真实 PostgreSQL 事务的 Clip INSERT、ClipShot INSERT、ClipRefSlot INSERT 语句处分别注入一次确定失败，三种失败均返回 500/`internal_error` 并恢复调用前三表计数，无孤儿关系。
  - R：R5、R7；事务语义依据 PRD §5 Clip create、§3 强制一致性规则。
  - 验收方式与命令：新增 `backend/tests/api/test_c008_review_create_atomicity.py`，使用生产 service/API、真实隔离 PostgreSQL 和仅存在于测试的 SQLAlchemy statement listener；每个参数化分支必须先断言确实命中目标 INSERT，finally 移除 listener，不增生产 test hook。不得改已有测试。运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_create_atomicity.py
    ```

  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C008 复审创建原子性：Clip、ClipShot、ClipRefSlot 三个写入阶段分别失败时均回滚全部创建副作用`；`C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`。

- [x] **T23 — 回填复审追溯、全量验收并重写完成证据**
  - 依赖：T14-T22 全部完成且各自定向验收通过。
  - 交付：将 T14-T22 新增用例的真实 pytest node ID 回填到本文引用的每条 TRACEABILITY 行；确认从已审查基线 `a35344d` 起没有任何既有测试被修改/删除/弱化。用实际输出重写 `.work/c008/completion-report.md`，且五节名称与顺序固定为：1. 基线与范围；2. 交付与 AC/追溯映射；3. 命令、退出码与原始输出路径；4. NOTES/DECISIONS/commit 状态；5. 操作 → 观测值。第 5 节记录生产 app+真实 PostgreSQL 的主路径和至少一条异常路径；明确 C008 无前端交付，不得伪报 Director UI。
  - R：R5、R5a、R6、R7、R8、R9、R12；依据 PRD §3.3、§3.4、§5、§11 M4。
  - 验收方式与命令：显式设置指向全新隔离库的 `DATABASE_URL`，先跑全部 C008 定向用例，再跑完整 pytest、Alembic、前端 build 和范围审计；下列每条的 stdout/stderr 和退出码均保存为 `.work/c008/` 下独立原始日志，报告第 3 节逐项链接路径并写实际结果，不截断或伪造输出：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/unit/test_c008_clip_rules.py tests/unit/test_c008_review_settings.py tests/api/test_c008_clip_preview.py tests/api/test_c008_clip_create.py tests/api/test_c008_clip_concurrency.py tests/api/test_c008_clip_patch.py tests/api/test_c008_slots.py tests/api/test_c008_slot_enabled.py tests/api/test_c008_slot_overrides.py tests/api/test_c008_asset_slot_cascade.py tests/api/test_c008_clip_source_races.py tests/api/test_c008_clip_delete.py tests/api/test_c008_contract_errors.py tests/api/test_c008_review_integer_bounds.py tests/api/test_c008_review_user_note.py tests/api/test_c008_review_override_image.py tests/api/test_c008_review_trash_lifecycle.py tests/api/test_c008_review_scene_boundary.py tests/api/test_c008_review_duration_boundaries.py tests/api/test_c008_review_slot_snapshots.py tests/api/test_c008_review_create_atomicity.py
    python -m pytest -q
    python -m alembic current
    python -m alembic check
    Set-Location D:\ai_drama_studio\frontend
    npm run build
    Set-Location D:\ai_drama_studio
    git diff --check
    git diff --name-status a35344d -- backend/tests
    git diff --name-only aac7f17 -- backend/alembic/versions frontend
    git diff --name-only -- backend/alembic/versions frontend
    git diff --unified=0 aac7f17 -- backend frontend | Select-String -Pattern 'minimax|gen_clip_video|generate-video|current-video|clip-videos|context_loop|fl2v|audio|generation_runs|continuity|retry|fallback'
    rg -n "^\| (R5 |R5a |R6 |R7 |R8 |R9 |C008 |R12 |§3\.3 删除片段)" openspec/TRACEABILITY.md
    ```

    人工核对 `git diff --name-status a35344d -- backend/tests` 只有 T14-T22 计划的新文件为 `A`，不得出现 `M`/`D`；围栏关键字扫描的每个命中必须逐项解释，不得静默忽略。
  - 计划测试层级：不新增自动测试。
  - 层级说明：本 task 只运行并审计 T14-T22 已计划的纯函数、API 集成和跨进程/资源生命周期用例，不再创建用例。
  - 追溯行：本 change 在 `openspec/TRACEABILITY.md` 中引用的全部 R5/R5a/R6/R7/R8/R9/R12、C008 与 `§3.3 删除片段` 行，包括五条 `C008 复审…` 新行。

## 二次复审修复（以已提交基线 `1e21f55` 为起点）

以下 task 只修复 Sol 二次复审确认的 AC-16 自动验收证据缺口。当前生产行为已由 `.work/c008/probe-error-contract-current.py` 在生产 router/service、真实 PostgreSQL 与真实媒体路径上证实符合 spec；本轮只授权新增独立回归测试及其追溯/完成证据，不授权修改任何既有测试或生产实现。若新增测试在相同通路上复现行为漂移，必须停止并报告探针与测试的环境/请求差异，不得直接改生产代码掩盖证据冲突。

- [x] **T24 — 精确锁定 AC-16 的结构化错误 code**
  - 依赖：已提交基线 `1e21f55`、二次复审 BLOCK，以及 `.work/c008/sol-rereview-probe-errors.log` 的当前行为证据。
  - 交付：新增且只新增 `backend/tests/api/test_c008_review_error_codes.py`，不得修改、删除或弱化任何既有测试。测试必须通过生产 FastAPI app、真实全新隔离 PostgreSQL、SQLAlchemy 查询计数器和隔离 `DATA_DIR` 覆盖：preview/create/PATCH 的未知字段；slot JSON 未知字段；slot 错误 content type；slot media 当前无 override；slot media 的数据库路径对应文件缺失。每个响应都精确断言外层字段集合仅为 `detail`、内层字段集合仅为 `code/message`，并分别锁定 422/`validation_error`、404/`not_found`、500/`internal_error`；message 必须为可直接展示的非空字符串，已有端点明确固定文案时断言该精确文案。五个请求边界输入在 SQL 前失败且查询计数精确为 0；媒体 404/500 允许按生产读取通路查库。不得新增 test hook、兼容层、fallback、重试或第二套错误映射。
  - R：无；依据 PRD §5 的统一错误体与 409/422 语义、C008 spec §8 错误码矩阵及 AC-16。
  - 验收方式与命令：先确认测试文件是相对 `1e21f55` 唯一新增测试文件，再在显式 `DATABASE_URL` 指向全新隔离 PostgreSQL、Alembic 已升级到 head 的环境运行：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_error_codes.py
    Set-Location D:\ai_drama_studio
    git diff --name-status 1e21f55 -- backend/tests
    ```

    期望：定向用例全部通过；test diff 精确只有 `backend/tests/api/test_c008_review_error_codes.py` 为 `A`，没有任何 `M`/`D`。保存完整 stdout/stderr 与退出码到 `.work/c008/T24-test.log`。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C008 片段 CRUD 与公开合同：稳定读取、输入 PATCH/no-op 状态、结构化错误及删除释放分镜`；`C008 槽位管理与 override 生命周期：固定编号、启停、R9 解析、上传/清除、ID 媒体、文件与数据库补偿`；`C008 复审 API 敌意输入边界：所有 episode/clip/slot 路径 ID 在访问 PostgreSQL 前拒绝超出有符号 INTEGER 的值，create/PATCH user_note 拒绝 U+0000，且不产生数据库副作用`；`C008 复审精确触发条件：两个单分镜场景跨场、合法非默认 Settings、时长 MIN/MAX、建片后活资产变更与精确错误 code 均按 C008 公开合同可观测`。

- [x] **T25 — 回填 T24 追溯并重做最终验收证据**
  - 依赖：T24 定向用例通过且 test diff 满足其边界。
  - 交付：把 T24 的真实 pytest node ID 回填至其列出的每条 `openspec/TRACEABILITY.md` 行；不得新增没有行为缺口的新追溯行。使用全新隔离 PostgreSQL 重跑 T24 与既有 C008 错误合同定向集、完整 backend pytest、Alembic current/check、前端 build、范围与测试 diff 检查；以实际输出更新 `.work/c008/completion-report.md` 的既有五节，追加二次复审基线、T24/T25、真实 node ID、命令结果、NOTES/DECISIONS/commit 状态和一条“错误输入 → 精确 status/code/零 SQL”走查。不得把 Sol 的 probe PASS 代替 pytest，也不得宣称 C008 有前端 UI。
  - R：无；依据 PRD §11、C008 spec AC-16/AC-17 与 `openspec/project.md` Change 工作流。
  - 验收方式与命令：所有命令的完整 stdout/stderr 与退出码分别保存到 `.work/c008/`，报告链接真实路径：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m pytest -q tests/api/test_c008_review_error_codes.py tests/api/test_c008_contract_errors.py tests/api/test_c008_review_integer_bounds.py tests/api/test_c008_review_user_note.py tests/api/test_c008_slot_overrides.py
    python -m pytest -q
    python -m alembic current
    python -m alembic check
    Set-Location D:\ai_drama_studio\frontend
    npm run build
    Set-Location D:\ai_drama_studio
    git diff --check
    git diff --name-status 1e21f55 -- backend/tests
    git diff --name-only 1e21f55 -- backend/app backend/alembic/versions frontend
    rg -n "^\| (C008 片段 CRUD|C008 槽位管理|C008 复审 API 敌意输入边界|C008 复审精确触发条件)" openspec/TRACEABILITY.md
    ```

    期望：定向与完整 pytest、Alembic、build 均退出 0；从 `1e21f55` 起测试 diff 只有 T24 新文件为 `A`，生产实现/migration/frontend diff 无输出；每条指定追溯行含 T24 的精确 node ID。任何失败必须保留原始输出并保持 T25 未勾选。
  - 计划测试层级：不新增自动测试。
  - 层级说明：本 task 只运行、审计并记录 T24 已计划的跨进程/资源生命周期用例及既有套件，不再创建测试。
  - 追溯行：T24 列出的四条准确行。

- [x] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）
  - R：无；PRD §11 的可运行可验收原则。
  - 验收方式与命令：只写本轮实际验证的 PostgreSQL/命令/坑，不复制计划值；运行 `git diff -- NOTES.md` 并人工核对每条有本轮原始证据。无新事实则不改文件，并在完成报告逐字写“无”。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用；操作事实不是运行时需求。

- [x] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）
  - R：无；PRD §3.4、§5；跨 change 记录纪律见 `DECISIONS.md` 文件说明。
  - 验收方式与人工检查：逐项判断是否产生“已验收、约束多个后续 change、且非 PRD/AGENTS 已规定”的实现决定；完成报告只列候选，不在本 task 擅自写入 `DECISIONS.md`。无候选则逐字写“无”。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用；这是跨 change 治理检查。

- [x] change 文档与 commit 状态一致
  - R：无；PRD §11、`openspec/project.md` Change 工作流。
  - 验收方式与命令：核对 spec AC、tasks checkbox、TRACEABILITY node ID、实际 diff、测试证据与提交边界一致；运行：

    ```powershell
    Set-Location D:\ai_drama_studio
    git status --short
    git diff --check
    git diff --name-status aac7f17
    git diff --name-status a35344d -- backend/tests
    git log -1 --oneline --decorate
    Get-ChildItem -File openspec/changes/c008 | Select-Object Name
    ```

    期望：`openspec/changes/c008` 精确只有 `spec.md`、`tasks.md`；未勾选项不伪报完成；从 `a35344d` 起 T14-T24 计划新增测试均只为 `A`、既有测试无 `M`/`D`；提交包含本 change 实际交付且不吸收用户已有 `.work/` 审查证据或无关改动。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用；commit/文档一致性采用上述人工与 git 验收。
