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
    git diff --name-status bffb69b..HEAD
    git log -1 --oneline --decorate
    Get-ChildItem -File openspec/changes/c008 | Select-Object Name
    ```

    期望：`openspec/changes/c008` 精确只有 `spec.md`、`tasks.md`；未勾选项不伪报完成；提交包含本 change 实际交付且不吸收用户已有 `.work/c007` 未跟踪文件或无关改动。
  - 计划测试层级：不新增自动测试。
  - 追溯行：不适用；commit/文档一致性采用上述人工与 git 验收。
