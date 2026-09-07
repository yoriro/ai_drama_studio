# C010 M4 导演台 UI Tasks

## 执行纪律与固定回归命令

- T0–T21 是已完成的历史阶段，T22–T29 是已提交的二次复审阶段；最终补修严格按 T30→T31→三个收尾 task 执行。任一验收命令或人工门槛失败立即停止，不勾选、不回填“已通过”、不提交该 task，也不先做后续 task；命令包装、日志采集或临时端口等操作性故障可在同一 task 内自检、修正装置并重跑，但不得借此改变产品语义或放宽断言。
- 每个 task 只提交其列出的生产/测试/文档文件和当次 checkbox/追溯回填；不得提交 `.work/`、下载目录工件或无关用户改动。除 `AGENTS.md` 已记录的一次性窄例外外，现有任何测试文件均不得修改、删除、skip、改名或弱化；T30 只能按 `AGENTS.md` 对 `directorReviewMutationWiring.test.ts` 的窄授权追加一个验收分支及其直接必需装置，既有矩阵必须逐字保留。
- T0 创建并记录同一个 C010 隔离数据库名。T1 之后每个实现 task 完成前，除本 task 的定向命令外，均执行下面的固定回归命令；`$task` 替换为当前 task 编号：

  ```powershell
  Set-Location D:\ai_drama_studio
  $task = 'Tn'
  $work = 'D:\ai_drama_studio\.work\c010'
  $c010Db = (Get-Content -LiteralPath "$work\database-name.txt" -Raw).Trim()
  $databaseLine = Get-Content -LiteralPath 'backend\.env' | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
  if (-not $databaseLine) { throw 'backend/.env DATABASE_URL is missing' }
  $sourceUrl = $databaseLine.Substring('DATABASE_URL='.Length)
  $env:DATABASE_URL = $sourceUrl -replace '/[^/]+$', ('/' + $c010Db)
  $env:DATA_DIR = "$work\test-data"
  npm --prefix frontend run test 2>&1 | Tee-Object -FilePath "$work\$task-frontend-test.log"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  npm --prefix frontend run build 2>&1 | Tee-Object -FilePath "$work\$task-frontend-build.log"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Push-Location backend
  python -m pytest -q 2>&1 | Tee-Object -FilePath "$work\$task-full-pytest.log"
  $pytestExit = $LASTEXITCODE
  Pop-Location
  if ($pytestExit -ne 0) { exit $pytestExit }
  git diff --check
  ```

  期望：frontend test、build、完整 pytest 与 `git diff --check` 均 exit 0；日志保留原生汇总。固定回归不能替代本 task 的定向断言或浏览器证据。T22–T31 不复用 T0 或 T20 已写入正式模板/Task/ClipVideo 的验收库：凡 task 要求完整 backend pytest，均新建“仅 Alembic 迁移、无业务验收数据”的独立干净数据库与隔离 DATA_DIR，并用 durable wrapper 保存真实 exit code；生产浏览器验收库只允许迁移状态、正式 API/数据库/媒体终态的只读核对。

## Tasks

- [x] **T0 — 固定规划基线、C009 前序证据与隔离 PostgreSQL**

  - **交付：** 只创建 `.work/c010/` 证据并勾选本项；记录实施前 HEAD、C010 规划提交与 C009 完成/归档提交的祖先关系、C009 已归档事实、tracked 工作区状态、前端现状、外部端口现场状态，并创建一个全新 C010 PostgreSQL 数据库。不得再次移动或改写 C009 archive、修改生产代码或把 `.work` 加入 Git。
  - **R：** 无；PRD §0、§11 M4、§12.1-§12.4；ROADMAP C010 依赖 C009。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`。
  - **验收方式与命令：** 以下五段必须作为 **五次独立 shell/tool 调用** 按顺序执行，不得再包进同一个有总超时的外层命令。任一段非 0 或工具超时立即停止；后续段不得执行。每段分别保留完整 stdout/stderr。首次重跑前先复制而非覆盖已有超时日志、`baseline-sha.txt` 与 `database-name.txt`；既有数据库不删除、不复用。

    **第 1 段：基线、归档状态与端口现场。**

    ```powershell
    $ErrorActionPreference = 'Stop'
    Set-Location D:\ai_drama_studio
    New-Item -ItemType Directory -Path '.work\c010' -Force | Out-Null
    $evidenceStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    if (Test-Path -LiteralPath '.work\c010\T00-baseline.log') {
        Copy-Item -LiteralPath '.work\c010\T00-baseline.log' -Destination ".work\c010\T00-baseline-before-$evidenceStamp.log"
    }
    if (Test-Path -LiteralPath '.work\c010\baseline-sha.txt') {
        Copy-Item -LiteralPath '.work\c010\baseline-sha.txt' -Destination ".work\c010\baseline-sha-before-$evidenceStamp.txt"
    }
    if (Test-Path -LiteralPath '.work\c010\database-name.txt') {
        Copy-Item -LiteralPath '.work\c010\database-name.txt' -Destination ".work\c010\database-name-before-$evidenceStamp.txt"
    }
    Start-Transcript -LiteralPath '.work\c010\T00-baseline.log' -Force
    try {
        $headSha = git rev-parse HEAD
        if ($LASTEXITCODE -ne 0) { throw "git rev-parse failed: $LASTEXITCODE" }
        $headSha | Tee-Object -FilePath '.work\c010\baseline-sha.txt'
        git status --short
        if ($LASTEXITCODE -ne 0) { throw "git status failed: $LASTEXITCODE" }
        $trackedStatus = @(git status --short --untracked-files=no)
        if ($LASTEXITCODE -ne 0) { throw "tracked git status failed: $LASTEXITCODE" }
        if ($trackedStatus.Count -ne 0) { $trackedStatus; throw 'tracked worktree is not clean' }
        git merge-base --is-ancestor 74990fc86ad0540294bc09df6c6327a4c8e35089 HEAD
        if ($LASTEXITCODE -ne 0) { throw 'C010 planning commit is not an ancestor of HEAD' }
        git merge-base --is-ancestor af7f6fd9310ba7ac2dc577a7db7457b7c18f7d4e HEAD
        if ($LASTEXITCODE -ne 0) { throw 'C009 archive commit is not an ancestor of HEAD' }
        $activeSpec = Test-Path 'openspec\changes\c009\spec.md'
        $archiveSpec = Test-Path 'openspec\archive\C009\spec.md'
        Write-Output "c009_active_spec=$activeSpec"
        Write-Output "c009_archive_spec=$archiveSpec"
        if ($activeSpec -or -not $archiveSpec) { throw 'C009 archive state does not match the C010 baseline' }
        $unchecked = @(rg -n '^- \[ \]' openspec/archive/C009/tasks.md)
        $uncheckedExit = $LASTEXITCODE
        if ($uncheckedExit -eq 0) { $unchecked; throw 'C009 archive contains unchecked tasks' }
        if ($uncheckedExit -ne 1) { throw "C009 task scan failed: $uncheckedExit" }
        rg -n 'director.*暂未交付|导演台.*暂未交付|activeTab === "director"' frontend/src/pages/EpisodeWorkspacePage.tsx
        if ($LASTEXITCODE -ne 0) { throw 'Director placeholder baseline was not found' }
        $postgresReady = Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -InformationLevel Quiet
        $vllmReady = Test-NetConnection -ComputerName 127.0.0.1 -Port 8001 -InformationLevel Quiet
        $comfyReady = Test-NetConnection -ComputerName 127.0.0.1 -Port 8188 -InformationLevel Quiet
        Write-Output "PostgreSQL 127.0.0.1:5432=$postgresReady"
        Write-Output "vLLM 127.0.0.1:8001=$vllmReady"
        Write-Output "ComfyUI 127.0.0.1:8188=$comfyReady"
        if (-not $postgresReady) { throw 'PostgreSQL is not reachable' }
    }
    finally {
        Stop-Transcript
    }
    ```

    **第 2 段：创建新的隔离数据库。**

    ```powershell
    $ErrorActionPreference = 'Stop'
    Set-Location D:\ai_drama_studio
    Start-Transcript -LiteralPath '.work\c010\T00-database.log' -Force
    try {
        $c010Db = 'ai_drama_studio_c010_' + (Get-Date -Format 'yyyyMMdd_HHmmss')
        Set-Content -LiteralPath '.work\c010\database-name.txt' -Value $c010Db -NoNewline
        $databaseLine = Get-Content -LiteralPath 'backend\.env' | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
        if (-not $databaseLine) { throw 'backend/.env DATABASE_URL is missing' }
        $env:DATABASE_URL = $databaseLine.Substring('DATABASE_URL='.Length)
        $env:C010_DB = $c010Db
        @'
    import asyncio, os
    from urllib.parse import urlsplit, urlunsplit
    import asyncpg
    async def main():
        parsed = urlsplit(os.environ['DATABASE_URL'].replace('+asyncpg', '', 1))
        admin = urlunsplit((parsed.scheme, parsed.netloc, '/postgres', parsed.query, parsed.fragment))
        connection = await asyncpg.connect(admin)
        try:
            exists = await connection.fetchval(
                'SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=$1)',
                os.environ['C010_DB'],
            )
            if exists:
                raise RuntimeError('C010 database name was not fresh')
            await connection.execute(f'CREATE DATABASE "{os.environ["C010_DB"]}"')
        finally:
            await connection.close()
    asyncio.run(main())
    '@ | python -
        if ($LASTEXITCODE -ne 0) { throw "database creation failed: $LASTEXITCODE" }
        Write-Output "C010_DATABASE=$c010Db"
    }
    finally {
        Stop-Transcript
    }
    ```

    **第 3 段：Alembic upgrade/current/check。**

    ```powershell
    $ErrorActionPreference = 'Stop'
    Set-Location D:\ai_drama_studio
    Start-Transcript -LiteralPath '.work\c010\T00-alembic.log' -Force
    $locationPushed = $false
    try {
        $c010Db = (Get-Content -LiteralPath '.work\c010\database-name.txt' -Raw).Trim()
        $databaseLine = Get-Content -LiteralPath 'backend\.env' | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
        if (-not $databaseLine) { throw 'backend/.env DATABASE_URL is missing' }
        $sourceUrl = $databaseLine.Substring('DATABASE_URL='.Length)
        $env:DATABASE_URL = $sourceUrl -replace '/[^/]+$', ('/' + $c010Db)
        $env:DATA_DIR = 'D:\ai_drama_studio\.work\c010\test-data'
        Push-Location backend
        $locationPushed = $true
        python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed: $LASTEXITCODE" }
        python -m alembic current
        if ($LASTEXITCODE -ne 0) { throw "alembic current failed: $LASTEXITCODE" }
        python -m alembic check
        if ($LASTEXITCODE -ne 0) { throw "alembic check failed: $LASTEXITCODE" }
    }
    finally {
        if ($locationPushed) { Pop-Location }
        Stop-Transcript
    }
    ```

    **第 4 段：完整 pytest。** 该段单独使用工具允许的最大超时，不与其他命令共享时间预算。

    ```powershell
    $ErrorActionPreference = 'Stop'
    Set-Location D:\ai_drama_studio
    Start-Transcript -LiteralPath '.work\c010\T00-full-pytest.log' -Force
    $locationPushed = $false
    try {
        $c010Db = (Get-Content -LiteralPath '.work\c010\database-name.txt' -Raw).Trim()
        $databaseLine = Get-Content -LiteralPath 'backend\.env' | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
        if (-not $databaseLine) { throw 'backend/.env DATABASE_URL is missing' }
        $sourceUrl = $databaseLine.Substring('DATABASE_URL='.Length)
        $env:DATABASE_URL = $sourceUrl -replace '/[^/]+$', ('/' + $c010Db)
        $env:DATA_DIR = 'D:\ai_drama_studio\.work\c010\test-data'
        Push-Location backend
        $locationPushed = $true
        python -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw "full pytest failed: $LASTEXITCODE" }
    }
    finally {
        if ($locationPushed) { Pop-Location }
        Stop-Transcript
    }
    ```

    **第 5 段：前端 build。**

    ```powershell
    $ErrorActionPreference = 'Stop'
    Set-Location D:\ai_drama_studio
    Start-Transcript -LiteralPath '.work\c010\T00-frontend-build.log' -Force
    try {
        npm --prefix frontend run build
        if ($LASTEXITCODE -ne 0) { throw "frontend build failed: $LASTEXITCODE" }
    }
    finally {
        Stop-Transcript
    }
    ```

    期望：五段工具调用均在各自时限内 exit 0；当前 HEAD 同时包含 C010 规划提交 `74990fc` 与 C009 归档提交 `af7f6fd`；C009 archive tasks 无未勾选项，活动 spec 不存在且 archive spec 存在；PostgreSQL 端口为 True；新数据库创建成功，upgrade/current/check、完整 pytest 与 frontend build 全部通过。vLLM/Comfy 现场 True/False 只记录，不阻塞 T1；不可达时只把 T12 标记为待现场恢复，不伪造 ready。提交只能包含本文件 T0 checkbox。

- [x] **T1 — 交付 C010 前端纯逻辑测试 runner**

  - **交付：** 在 `frontend/package.json` 增加单一 `test` script，加入并锁定 `vitest@3.2.4` dev dependency；只修改 `frontend/package.json`、`frontend/package-lock.json` 与本 task checkbox。不得加 jsdom、Testing Library、Playwright/Cypress、空测试或自建 runner。
  - **R：** 无；PRD §11 M4；`openspec/project.md` 测试追溯纪律。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`。
  - **验收方式与命令：** `npm --prefix frontend install --save-dev --save-exact vitest@3.2.4`；将 script 精确设为 `"test": "vitest run"`；执行 `npm --prefix frontend run test -- --passWithNoTests`、`npm --prefix frontend run build` 与固定回归中的完整 pytest 部分。执行 `npm --prefix frontend ls vitest --depth=0`，期望只显示锁定版本且所有命令 exit 0；`git diff --name-status` 只含 package/lock/tasks，不含测试或生产页面。

- [x] **T2 — 新增 Director clip/slot/video 前端 API 合同**

  - **交付：** 新建 `frontend/src/api/clips.ts`，声明 spec §2.1 的公开类型与全部既有 endpoint 函数；新建 `frontend/src/api/clips.test.ts`，通过替换 `globalThis.fetch` 精确断言 URL、method、JSON body、204 helper、FormData part 和 multipart header 不被手写，并覆盖结构化 409/422、非 JSON 与 204 漂移。不得加入后端字段、内部路径、API base URL 或 runtime fallback。
  - **R：** R5、R5a、R6、R7、R8、R9、R10、R12；PRD §5 片段 API、§9、§11 M4。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功`。
  - **验收方式与命令：** `npm --prefix frontend run test -- src/api/clips.test.ts`，期望每个公开函数至少有一条精确 request 断言，seed 被断言为 string，DEBUG 字段可选，upload `Headers` 不含显式 multipart Content-Type；随后运行固定回归命令。通过后把真实 Vitest node 名回填本追溯行，再勾选并提交。

- [x] **T3 — 实现共享轨道投影与分镜选择纯逻辑**

  - **交付：** 新建 Director 专用纯模块（建议 `frontend/src/features/director/directorModel.ts`）和同名测试，产出 scene classification/bands、共享 Shot index/grid columns、Clip spans、连续 gaps、状态展示 token、占用/跨场景/零场景/多场景选择 eligibility 与 preview 最大候选数。非法 duration、未知/重叠/非连续 Clip 必须抛可见上层可处理的明确错误，不默认或修剪。
  - **R：** R5、R5a、R6、R7、R8；PRD §3.2、§9“一带两轨一板”、§11 M4。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C010 导演台轨道投影与选择：场景带、duration 比例分镜轨、片段轨、空洞、changed 与两维状态，零场景可加入任意单场景、双场景不可选`；`C010 预检与创建交互：服务端 violations/warnings、候选原序/default、响应推导硬上限、软提示与创建后权威刷新`。
  - **验收方式与命令：** `npm --prefix frontend run test -- src/features/director/directorModel.test.ts`；断言至少覆盖 spec AC-03/04/05 的精确段数、`1fr 2fr 5fr`、跨 scene/zero/multiple/occupied/noncontiguous、五生成态×两 freshness、gap 合并、候选 overflow/等量替换及每个非法投影错误；不得只判数组非空。随后运行固定回归，回填真实 node 名后提交。

- [x] **T4 — 用真实 Director 页面替换空态并交付三轨浏览**

  - **交付：** 新建 `frontend/src/pages/DirectorPage.tsx`，由 `EpisodeWorkspacePage` 在 director tab 传入已验证的 project/episode id；加载 assets/shots/clips，使用 T3 的单一投影渲染场景带、分镜轨、片段轨/空洞，支持 Shot checkbox 与 Clip bar selection，并在 `frontend/src/styles.css` 只增加 `director-*` 局部样式。交付 loading、空 shots、ready、错误和 no-selection 面板；不得加入后续 mutation 的假按钮或假数据。
  - **R：** R5、R5a；PRD §2.1(7)、§3.2、§9、§11 M4。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 导演台轨道投影与选择：场景带、duration 比例分镜轨、片段轨、空洞、changed 与两维状态，零场景可加入任意单场景、双场景不可选`；`C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功`。
  - **验收方式与命令：** 执行 `npm --prefix frontend run test -- src/features/director/directorModel.test.ts` 与固定回归；用 `rg -n '暂未交付' frontend/src/pages/EpisodeWorkspacePage.tsx frontend/src/pages/DirectorPage.tsx` 期望 Director 不再走旧空态，检查 route 仍只有既有 director path。T3 精确投影测试、TypeScript build 和 JSX/CSS diff 必须共同证明三轨使用同一 model 输出；真实 DOM/截图追溯保持待填，直到 T11 使用 T10A 装置完成，不能在本 task 冒充浏览器已验收。

- [x] **T5 — 接入 D-008 Director WS/REST 同步协调器**

  - **交付：** 新建 Director 专用同步模块及测试并接入页面；实现 socket-first 缓冲、页面/详情 request generation、未知 gen_clip_video task 单 in-flight detail GET、initial/reconnect、事件使 refresh 失效并补发、success/terminal notice 后置、同 Clip dirty 草稿合并和选中 Clip 切换隔离。不得改 AssetPage/TasksPage，不得加 interval polling、mutation retry、全局 store 或通用注册表。
  - **R：** 无；PRD §3.2、§6.1、§9、§11 M4；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 Director REST/WS 竞态：socket-first 缓冲、旧响应失效、replacement refresh、task detail 去重与成功通知后置`。
  - **验收方式与命令：** `npm --prefix frontend run test -- src/features/director/directorSync.test.ts`；使用可控 deferred Promise/EventTarget，逐项断言 spec AC-13/14：open 在 snapshot 前、旧 response 应用次数 0、replacement refresh 次数精确、同 task detail 最大并发 1、同 Clip refresh 保留 dirty 且更新 base、切 Clip 后旧详情零应用并废弃旧草稿、initial failure close/reconnect、最新错误可见、notice 在最新 apply 后，且 fake clock 中无 polling timer。随后运行固定回归并回填真实 node 名。

- [x] **T6 — 交付预检、候选精简与创建面板**

  - **交付：** 在 Director 页面完成 Shot 选择→preview→面板→create；逐项显示 API violations/warnings/时长映射，候选严格保序/default 勾选，最大选择数从响应推导；selection 变化清空旧 preview/draft。创建成功须经 T5 最新 refresh 才选中新 Clip/提示成功，失败保留输入并直显 message。扩充 T3 测试覆盖 preview state/cap，不新增 DOM runner。
  - **R：** R5、R5a、R6、R7、R8；PRD §3.1、§5 片段、§9、§11 M4。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C010 预检与创建交互：服务端 violations/warnings、候选原序/default、响应推导硬上限、软提示与创建后权威刷新`；`C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功`。
  - **验收方式与命令：** `npm --prefix frontend run test -- src/features/director/directorModel.test.ts src/api/clips.test.ts`；断言 request 精确、候选顺序/default、0/N/N+1、soft warning 原文、selection invalidation 与 422 保留状态，再运行固定回归。回填新增 node ID；真实“非连续 preview→violation”“合法 preview→201”的 HTTP/DOM 证据留到 T11，不得只凭 mock 声称完成浏览器追溯行。

- [x] **T7 — 交付片段设置保存与删除**

  - **交付：** 选中 Clip 后显示 note/requested duration 草稿；note 控件区分 null、空串与普通/空白 string，并以独立“清空为未填写”产生 null；同时扩充 Director 纯状态测试覆盖 dirty/no-op/changed field 计算。no-op 不请求，实际变化以一个只含 changed fields 的 PATCH 保存，非整数本地明确阻止、范围交给 API。只有 requested duration dirty 时生成按钮不可用并显示“请先保存请求时长”；note dirty 留给 T10 按 generate-video 的显式 user_note 语义提交。删除用 `window.confirm` + `requestNoContent`；204 及最新页面快照后才清空/提示，失败不乐观修改。
  - **R：** R4（保存后的生成输入）、R6；无直接 R 的删除，PRD §3.2、§3.3 删除片段、§5、§9、§11 M4。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C010 片段详情输入与删除：note/duration 草稿保存、requested-duration 生成门槛、note 随生成提交、204 后权威刷新与失败保真`；`§3.3 删除片段：其分镜释放、片段删除、视频移入 trash`。
  - **验收方式与命令：** 执行 `npm --prefix frontend run test -- src/features/director/directorModel.test.ts src/api/clips.test.ts`，精确断言 no-op/单字段/双字段 PATCH body、null/空串、duration 整数解析、duration dirty 与 note dirty 的不同生成门槛、DELETE 204；再运行固定回归。浏览器/refresh/error 的最终证据留到 T11并保持追溯待填，本 task 不以纯逻辑替代 DOM 验收。

- [x] **T8 — 交付槽位、override 与 R12 处置面板**

  - **交付：** 加载/显示 slots 与 warnings；实现并测试 Slot 视图模型的固定顺序、source/deleted/action 映射；实现 enabled JSON PATCH、override 单文件 FormData 上传、清除确认；只用 API `image_source/image_url`。已删资产固定显示快照名+“原资产已删除”，无图时同时提供停用/上传且不自动执行。每次 mutation 通过 T5 刷新 Clip+slots，不乐观改号/状态。
  - **R：** R8、R9、R10、R12；PRD §3.1、§3.3、§5、§9、§11 M4。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C010 槽位与 R12 处置：固定 slot、enabled、override、R9 media、soft warning、已删资产快照与用户显式处置`；`C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功`。
  - **验收方式与命令：** 执行 `npm --prefix frontend run test -- src/features/director/directorModel.test.ts src/api/clips.test.ts`，逐项断言 current/override/null/disabled/deleted 的文案、动作集合、URL原值和 JSON/FormData/clear request；再运行固定回归。真实合法/非法上传、R12、DOM 与 refresh 证据统一留到 T11，不能由视图模型测试替代。

- [x] **T9 — 交付 take 画廊、current、删除、媒体与 DEBUG 展示**

  - **交付：** 为所选 Clip 加载 videos；实现并测试 take 视图模型的 API 原序、string seed、duration/null、current action 与可选 DEBUG 映射；按该模型显示 `<video controls>`，实现设 current 与 non-current 删除确认，current delete 控件禁用且零请求。媒体错误可见且不修改 take。
  - **R：** 无；PRD §3.2、§5 take API、§9 DEBUG/详情面板、§11 M4。
  - **计划测试层级：** 纯函数。
  - **追溯行：** `C010 take 与生成交互：多任务提交、完整失败原因、take 画廊/current/delete/media/DEBUG 与两维状态刷新`；`C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功`。
  - **验收方式与命令：** 执行 `npm --prefix frontend run test -- src/features/director/directorModel.test.ts src/api/clips.test.ts`，精确断言 0/1/多 take 原序、seed不转 number、actual null/value、current/non-current action、DEBUG字段有/无、PUT/DELETE/422；再运行固定回归。真实播放器、current 切换、删除与 DEBUG DOM 证据由 T11/T12完成，不能伪造 take fixture或直接写 ClipVideo。

- [x] **T10 — 交付生成按钮、Task 反馈与多任务语义**

  - **交付：** 接入 generate-video：requested duration dirty/详情未就绪/HTTP 在途时禁用；note 未变 POST `{}`，note 草稿实际变化时精确提交 `{user_note}`（保留 string/null/空串，不 trim），且始终无 request_id。202 记录 task_id、显示“任务已提交”并刷新；failed 显示完整 error_msg，done 在最新 take 落地后提示，canceled 只刷新；首个 202 返回后允许再次有意生成。
  - **R：** R4、R5、R5a、R9、R10；PRD §3.1、§3.2、§5 生成动作、§6.1、§9、§11 M4；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 take 与生成交互：多任务提交、完整失败原因、take 画廊/current/delete/media/DEBUG 与两维状态刷新`；`C010 片段详情输入与删除：note/duration 草稿保存、requested-duration 生成门槛、note 随生成提交、204 后权威刷新与失败保真`；`C010 Director REST/WS 竞态：socket-first 缓冲、旧响应失效、replacement refresh、task detail 去重与成功通知后置`；`C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功`。
  - **验收方式与命令：** 扩充并执行 `npm --prefix frontend run test -- src/features/director/directorSync.test.ts src/api/clips.test.ts`；定向断言 note 未变/普通 string/空串/null 的 presence/value 与 body 精确、两次 sequential 202产生两 POST、同一次 in-flight 只有一 POST、无 request_id、202不触发完成 notice、immediate failed完整原因且 note 取服务端刷新值、409/transport无假 task/take、done notice 后于 replacement REST apply。随后固定回归并回填真实 node 名。

- [x] **T10A — 交付确定性 Director 浏览器验收夹具装置**

  - **交付：** 在 `.work/c010/director-fixture.py` 创建且实际运行一次性 driver，并为它创建独立于 T0 回归库的全新浏览器数据库，数据库名写入 `.work/c010/browser-database-name.txt`。driver 通过正式 API 创建 project/style/episode/assets、上传图片、创建初始 Clip并执行 changed mutation；仅因项目没有 Shot create API，才可用生产 SQLAlchemy model/session 向同一浏览器数据库写入 Shot/ShotAsset。输出所有实体 ID、场景分类、候选顺序与预期场景到 `.work/c010/director-fixture.json`。不得写 Task/ClipVideo、前端状态、媒体正式输出或 production/test 文件，不得提交脚本。
  - **R：** 无；PRD §9、§11 M4 的确定性浏览器前置数据，不替代 R5-R12 正式 API 验收。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** 不适用。
  - **验收方式与命令：** 先运行固定回归。按 T0 的数据库创建方式另建名称含 `c010_browser_<timestamp>` 的全新库，记录名称，显式设置该 DSN 与绝对 DATA_DIR `D:\ai_drama_studio\.work\c010\T10A-data`；确认 8000 未被非本 task 进程占用后，从任意当前目录使用 `Start-Process -FilePath python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -PassThru -WindowStyle Hidden -WorkingDirectory 'D:\ai_drama_studio\backend'` 启动本 task Uvicorn并记录 PID。设置 `$env:PYTHONPATH='D:\ai_drama_studio\backend'`，执行 `python 'D:\ai_drama_studio\.work\c010\director-fixture.py' --base-url http://127.0.0.1:8000 --output 'D:\ai_drama_studio\.work\c010\director-fixture.json'`；再通过正式 `GET assets/shots/clips/slots` 逐项核对：至少两个 scene、一个 unbound、一个绑定两个 scene、一个 changed、一个非连续可选组合、11 个候选、一个已占用 Shot和一个可删除资产槽位；脚本 SQL 日志只能出现 `shots`/`shot_assets` INSERT。执行 `rg -n 'Task|ClipVideo|clip_videos|tasks|frontend' 'D:\ai_drama_studio\.work\c010\director-fixture.py'` 并人工确认无写入这些对象的代码。结束仅停止本 task PID并证明 8000 释放。报告必须明确：装置与生产共享 PostgreSQL/schema/ORM，唯一区别是绕过 `gen_shots` 建 Shot；它不能证明 M2 或直写夹具校验。通过后只提交 tasks checkbox，不提交 `.work`。

- [x] **T11 — 真实浏览器非 GPU 合同走查**

  - **交付：** 使用 T10A 独立浏览器 PostgreSQL/fixture、生产 FastAPI/Vite/Task WS 和正式 API；T10A 完成后不再直接写数据库，不创建第二个脚本、不调用 mock。覆盖一带两轨、选择/preview/create、>9、settings/delete、slots/R12、immediate R5a/R10 failed、错误体与刷新；保存逐项原始 HTTP/WS/DOM/截图。
  - **R：** R5、R5a、R6、R7、R8、R9、R10、R12；PRD §3.1-§3.5、§5、§9、§11 M4。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 导演台轨道投影与选择：场景带、duration 比例分镜轨、片段轨、空洞、changed 与两维状态，零场景可加入任意单场景、双场景不可选`；`C010 预检与创建交互：服务端 violations/warnings、候选原序/default、响应推导硬上限、软提示与创建后权威刷新`；`C010 片段详情输入与删除：note/duration 草稿保存、requested-duration 生成门槛、note 随生成提交、204 后权威刷新与失败保真`；`C010 槽位与 R12 处置：固定 slot、enabled、override、R9 media、soft warning、已删资产快照与用户显式处置`；`C010 Director API/媒体/错误边界：只用同源路径，404/409/422/500/协议/网络/媒体错误可见且无 retry/fallback/伪成功`；`C010 M4 生产浏览器闭环：真实 API/WS/PostgreSQL/vLLM/Comfy 下创建、生成、take、stale 与 R5a/R10/R12 异常路径`。
  - **验收方式与命令/人工检查：** 先运行固定回归。确认 8000/5173 若由非本 task 进程占用则停止报告，不终止；否则从 `.work/c010/browser-database-name.txt` 重建并显式导出浏览器 DSN，使用 `.work/c010/T10A-data` 启动生产 Uvicorn 和 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort`，PID/命令写 `.work/c010/T11-processes.log`。读取并冻结 T10A JSON，不再运行 driver或直写；逐项按 AC-02..12 操作并写成“操作 → 请求/WS → DOM/DB 观测值”到 `.work/c010/T11-browser.log`，截图至少 `T11-tracks.png`、`T11-preview-overflow.png`、`T11-deleted-slot.png`、`T11-task-error.png`。结束只停止本 task 启动的进程，并证明端口释放。若 driver 做了披露范围外 DB 写入、UI 与正式 API 不一致或证据缺项，均不得通过。

- [x] **T11A — 修正 MiniMax H3 LoRA 外部枚举绑定**

  - **交付：** 保留 T12 已有失败数据库、Task 与 `.work/c010/T12-*` 原始证据不动；从当前运行的正式 Comfy `/object_info` 重新取得 `LoraLoaderModelOnly.lora_name` 允许列表，只把 `backend/workflows/minimax_h3_ref2v.json` 节点 `310.inputs.lora_name` 从裸文件名改为 `minimax_h3\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`。随后仅按 `AGENTS.md` C010 窄授权，把 `test_c007_health.py`、`test_c009_health.py`、`test_system.py` 的 `MINIMAX_WORKFLOW_HASH` 和 `test_c009_workflow_binding.py` 的 `EXPECTED_HASH` 从旧 hash 精确替换为 `4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772`。不得修改其他 workflow 叶、测试字符、Python 生产代码、binding TOML、migration 或前端，不增加动态 expected、路径查找、别名、fallback、retry，也不修改 Comfy 错误体处理。回填本 task 真实证据并单独提交。
  - **R：** 无；PRD §7、§12.1、§12.4；spec §2.3、AC-18。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 MiniMax workflow 外部枚举绑定：节点 310 LoRA 注册名与当前 Comfy object_info 一致、hash 更新且无路径猜测或 fallback`。
  - **验收方式与命令：** 先确认 `127.0.0.1:8188` 是将用于 T12 的正式 Comfy；若不可达立即停止。按下列顺序执行，任一失败即保留证据并停止：

    ```powershell
    Set-Location D:\ai_drama_studio
    $work = 'D:\ai_drama_studio\.work\c010'
    $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8188/object_info'
    if ($response.StatusCode -ne 200) { throw "Comfy object_info HTTP $($response.StatusCode)" }
    [System.IO.File]::WriteAllText("$work\T11A-comfy-object-info.json", $response.Content, [System.Text.UTF8Encoding]::new($false))
    @'
    import json
    from pathlib import Path

    expected = "minimax_h3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    data = json.loads(Path(r"D:\ai_drama_studio\.work\c010\T11A-comfy-object-info.json").read_text(encoding="utf-8"))
    allowed = data["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0]
    assert isinstance(allowed, list), type(allowed)
    assert expected in allowed, expected
    print(f"EXPECTED_LORA_REGISTERED={expected}")
    '@ | python - 2>&1 | Tee-Object -FilePath "$work\T11A-object-info-check.log"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    ```

    完成唯一 JSON 叶修改后执行：

    ```powershell
    Set-Location D:\ai_drama_studio
    $work = 'D:\ai_drama_studio\.work\c010'
    @'
    import copy
    import hashlib
    import json
    import subprocess
    from pathlib import Path

    path = Path("backend/workflows/minimax_h3_ref2v.json")
    before = json.loads(subprocess.check_output(["git", "show", "HEAD:backend/workflows/minimax_h3_ref2v.json"]))
    after = json.loads(path.read_text(encoding="utf-8"))
    expected = copy.deepcopy(before)
    expected["310"]["inputs"]["lora_name"] = "minimax_h3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    assert after == expected, "workflow has a semantic change outside node 310 lora_name"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(digest) == 64 and digest == digest.lower()
    assert digest != "bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780", digest
    Path(r"D:\ai_drama_studio\.work\c010\T11A-workflow-hash.txt").write_text(digest + "\n", encoding="ascii")
    print(f"WORKFLOW_SHA256={digest}")
    '@ | python - 2>&1 | Tee-Object -FilePath "$work\T11A-workflow-diff-check.log"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $numstat = git diff --numstat HEAD -- backend/workflows/minimax_h3_ref2v.json
    $numstat | Tee-Object -FilePath "$work\T11A-workflow-numstat.log"
    if ($numstat -ne "1`t1`tbackend/workflows/minimax_h3_ref2v.json") { throw "unexpected workflow line diff: $numstat" }
    $backendChanges = @(git diff --name-only HEAD -- backend)
    if ($backendChanges.Count -ne 1 -or $backendChanges[0] -ne 'backend/workflows/minimax_h3_ref2v.json') { throw "unexpected backend diff: $($backendChanges -join ', ')" }
    if (@(git diff --name-only HEAD -- backend/tests).Count -ne 0) { throw 'test files changed' }
    Push-Location backend
    @'
    from app.integrations.workflow_binding import load_minimax_binding_snapshot
    from pathlib import Path

    snapshot = load_minimax_binding_snapshot()
    expected_name = "minimax_h3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    expected_hash = Path(r"D:\ai_drama_studio\.work\c010\T11A-workflow-hash.txt").read_text(encoding="ascii").strip()
    assert snapshot.definition["310"]["inputs"]["lora_name"] == expected_name
    assert snapshot.workflow_hash == expected_hash
    print(f"BINDING_STATUS=valid HASH={snapshot.workflow_hash}")
    '@ | python - 2>&1 | Tee-Object -FilePath "$work\T11A-binding-loader.log"
    $bindingExit = $LASTEXITCODE
    Pop-Location
    if ($bindingExit -ne 0) { exit $bindingExit }
    ```

    完成上述 workflow/binding 检查后，才允许逐项替换四个测试常量；然后执行以下精确 diff 与定向测试：

    ```powershell
    Set-Location D:\ai_drama_studio
    $work = 'D:\ai_drama_studio\.work\c010'
    @'
    import subprocess
    from pathlib import Path

    old = b"bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780"
    new = b"4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772"
    files = (
        "backend/tests/api/test_c007_health.py",
        "backend/tests/api/test_c009_health.py",
        "backend/tests/api/test_system.py",
        "backend/tests/unit/test_c009_workflow_binding.py",
    )
    for name in files:
        before = subprocess.check_output(["git", "show", f"HEAD:{name}"]).replace(b"\r\n", b"\n")
        after = Path(name).read_bytes().replace(b"\r\n", b"\n")
        assert before.count(old) == 1, (name, before.count(old))
        assert after == before.replace(old, new), f"unauthorized test diff: {name}"
    changed = set(subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "backend/tests"], text=True).splitlines())
    assert changed == set(files), changed
    print("T11A_TEST_BASELINE_DIFF=PASS")
    '@ | python - 2>&1 | Tee-Object -FilePath "$work\T11A-test-baseline-diff.log"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $testNumstat = @(git diff --numstat HEAD -- backend/tests)
    $testNumstat | Tee-Object -FilePath "$work\T11A-test-baseline-numstat.log"
    if ($testNumstat.Count -ne 4 -or @($testNumstat | Where-Object { $_ -notmatch '^1\s+1\s+backend/tests/' }).Count -ne 0) { throw "unexpected test numstat: $($testNumstat -join '; ')" }
    $c010Db = (Get-Content -LiteralPath "$work\database-name.txt" -Raw).Trim()
    if (-not $c010Db) { throw 'C010 database-name.txt is empty' }
    $databaseLine = Get-Content -LiteralPath 'backend\.env' | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
    if (-not $databaseLine) { throw 'backend/.env DATABASE_URL is missing' }
    $sourceUrl = $databaseLine.Substring('DATABASE_URL='.Length)
    $env:DATABASE_URL = $sourceUrl -replace '/[^/]+$', ('/' + $c010Db)
    $env:DATA_DIR = "$work\test-data"
    $env:C010_EXPECTED_DB = $c010Db
    Push-Location backend
    @'
    import asyncio
    import os

    import asyncpg

    async def main() -> None:
        dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
        connection = await asyncpg.connect(dsn)
        try:
            database = await connection.fetchval("select current_database()")
            holders = await connection.fetchval(
                """
                select count(*)
                from pg_locks locks
                join pg_stat_activity activity on activity.pid = locks.pid
                where locks.locktype = 'advisory'
                  and locks.granted
                  and activity.datname = current_database()
                """
            )
        finally:
            await connection.close()
        assert database == os.environ["C010_EXPECTED_DB"], (database, os.environ["C010_EXPECTED_DB"])
        assert holders == 0, f"C010 database advisory lock holders={holders}"
        print(f"DATABASE={database}")
        print("ADVISORY_HOLDERS=0")

    asyncio.run(main())
    '@ | python - 2>&1 | Tee-Object -FilePath "$work\T11A-database-preflight-rerun.log"
    $preflightExit = $LASTEXITCODE
    if ($preflightExit -ne 0) { Pop-Location; exit $preflightExit }
    python -m pytest -q tests/api/test_c007_health.py tests/api/test_c009_health.py tests/api/test_system.py tests/unit/test_c009_workflow_binding.py 2>&1 | Tee-Object -FilePath "$work\T11A-hash-baseline-targeted-rerun.log"
    $targetedExit = $LASTEXITCODE
    Pop-Location
    if ($targetedExit -ne 0) { exit $targetedExit }
    ```

    首次 `T11A-hash-baseline-targeted.log` 因命令未显式导出 DSN而回退到 `backend/.env` 的非 C010 数据库，并被既有进程的 advisory lock 拒绝；该日志必须保留，不能宣称为代码/测试失败或覆盖。此前同一次 T11A 运行中已经 exit 0 且对应 frontend 文件此后零 diff 的 `T11A-frontend-test.log`、`T11A-frontend-build.log` 可以保留，不要求重复运行。定向通过后，必须在同一 shell 继续使用上面已显式设置的 C010 `DATABASE_URL`/`DATA_DIR`，或在新的 shell 中重新执行同一 DSN 构造与零 lock preflight，再运行完整 `python -m pytest -q` 写入 `T11A-full-pytest-rerun.log`，随后执行 `git diff --check`。全部 exit 0 后才将本追溯行回填为 `/object_info`、workflow/hash/binding、四常量精确 diff、数据库零锁、定向与完整 pytest、frontend test/build 原始证据，勾选 T11A并提交。最终 commit 只允许 workflow、上述四个测试文件、tasks checkbox 与追溯回填；不得为命中 hash 改变 workflow 换行。该 task 不新增测试；`/object_info` 不能代替 T12 的真实 `/prompt`/history/MP4。

- [x] **T11B — 修复自给自足的 Director 参考图片夹具**

  - **交付：** 保留全部既有 T12 失败数据库、DATA_DIR、Task 与日志不动；只修改未跟踪的 `.work/c010/director-fixture.py`，删除固定 68-byte `1×1` `PNG_BYTES`，使用项目既有 Pillow 在内存中按资产序号生成 13 张互不相同的 `512×512` RGB PNG。每张至少有背景与对比图形两种像素颜色，文件名精确为 `reference-01.png` 至 `reference-13.png`；driver 仍逐张调用正式 `POST /api/assets/{id}/images`。不得读取用户图片、旧数据库、旧 DATA_DIR或其他外部素材文件，不得直接写资产图片正式路径、Task、ClipVideo或视频，不得要求用户手工干预。用一套全新 fixture 验证库/隔离 DATA_DIR 实际运行并回读验证；`.work` 脚本与图片不提交，本 task 提交只含 checkbox 与追溯证据回填。
  - **R：** R7、R9、R10；PRD §3.4、§8、§9、§11 M4、§12.1。R7/R9/R10 的业务实现不变，本 task 只保证验收装置提供可走生产图片通路的前置输入。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 自洽 Director 夹具参考图：无需用户素材或旧库，driver 经正式 API 生成/上传/回读 13 张生产可加载图片`。
  - **验收方式与命令/人工检查：** 创建名称含 `ai_drama_studio_c010_t11b_<timestamp>` 且现场证明不存在的全新 PostgreSQL，显式导出该 DSN和绝对 `DATA_DIR=D:\ai_drama_studio\.work\c010\T11B-data`，执行 `python -m alembic upgrade head/current/check`。确认 8002 空闲后，从 `D:\ai_drama_studio\backend` 启动本 task 独占的 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8002` 并记录 PID；执行 `python 'D:\ai_drama_studio\.work\c010\director-fixture.py' --base-url http://127.0.0.1:8002 --output 'D:\ai_drama_studio\.work\c010\T11B-fixture.json'`。随后用 `httpx` 逐个读取 JSON 中 13 个 asset id 的 `GET /api/assets/{id}/images` 与唯一 current image 的 `GET /media/asset-images/{image_id}`，用 Pillow 精确断言 HTTP 200、每资产一张 current、format=`PNG`、size=`(512,512)`、mode=`RGB`、`len(getcolors(maxcolors=262144)) >= 2`，并断言 13 个响应 bytes 两两不同；再对 driver 创建的所有 Clip 执行 videos GET 并断言均为空、tasks GET 为空。静态检查 driver 不再含 `base64`/`PNG_BYTES`/`1×1`，图片生成不接收路径参数。停止且只停止本 task Uvicorn，证明 8002 释放。另建一个无 lock 的全新回归库，显式导出 DSN后执行 `python -m pytest -q`。所有命令和原始输出写入不覆盖旧证据的 `.work/c010/T11B-*`；任一失败立即停止，不勾选、不手工换图、不切旧库、不进入 T11C/T12。

- [x] **T11C — 对齐真实 Comfy `execution_error.node_id` 并保留完整失败原因**

  - **交付：** 仅在 `backend/app/tasks/gen_clip_video.py` 将匹配当前 prompt 的 `execution_error` 节点读取从 `data.get("node")` 改为 `data.get("node_id")`，字段校验标签与最终 RuntimeError 标签同步为 `node_id`；`node_type`、`exception_message`、跨 prompt 先忽略、failed/no-take/no-retry与单一 `/free` owner 均保持。仅按 `AGENTS.md` C010 窄授权同步 `backend/tests/task_system/test_c009_review_worker_failures.py` 的四个事件/body键和一个末行标签；不得兼容旧 `node`、查询 history fallback、修改 `gen_asset_image`、其他生产/测试文件、API/schema/migration/workflow/binding/前端或错误状态机。
  - **R：** 无；PRD §6.4、§8、§11 M4（任何异常 failed + 完整 `error_msg`、不重试，Comfy WS 进度/错误通路）。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 Comfy execution_error 真实协议：node_id 完整原因、跨 prompt 隔离、failed/no-take/no-retry 与 free-once`。
  - **验收方式与命令：** 先以只读命令保存当前 `F:\ComfyUI\execution.py` 中 `execution_error` 的 `node_id/node_type/exception_message` 发送片段和 T12 prompt `33bc1ebd-1af5-47db-bff5-2e68a8b5203f` history（若当前 Comfy history 仍存在；不存在只记录漂移，不以伪造响应替代）到 `.work/c010/T11C-*`。修改后执行 `git diff --check` 与精确 diff 审计：生产文件只允许 `node`→`node_id` 的读取/标签变化；获授权测试只允许 `_worker_failure_websocket` 及精确 body 断言的四处 key、`_assert_failure_error` 的一处标签变化，且 `rg -n 'data.get\("node"\)' backend/app/tasks/gen_clip_video.py` 无匹配；其他既有测试零 diff。用名称含 `ai_drama_studio_c010_t11c_<timestamp>` 的全新已迁移 PostgreSQL和隔离 DATA_DIR，执行 `python -m pytest -q tests/task_system/test_c009_review_worker_failures.py`，必须保留 `[wake]`/`[sleep]`/`[ws]` 全部通过并由 `[ws]` 精确证明：无关 prompt 的畸形 node 字段被忽略、当前事件只含 `node_id`、错误末行为 `RuntimeError: Comfy execution_error node_id=168 type=T25StubNode exception=T25 WS stage failure`、Task/Clip failed、ClipVideo=0、调用顺序/次数不变、无 retry且 `/free` 一次。随后同一无 lock DSN运行 `python -m pytest -q`。全部 exit 0 后回填真实用例/日志、勾选并单独提交；任一失败立即停止，不进入 T12。

- [x] **T12 — 真实 MiniMax 浏览器生成、take 与 stale 竞态验收**

  - **交付：** T11A/T11B/T11C 均通过并提交后，保留两轮既有 T12 失败数据库、failed Task、DATA_DIR 与日志不动，另建全新 PostgreSQL、隔离 DATA_DIR、全新实体与新 Task；由修正后的同一个 driver 自动生成/正式上传图片，不接受用户素材或旧库输入。以生产浏览器→Vite→FastAPI→Task/WS→vLLM/Comfy→MP4 全通路完成两次视频生成、播放/current 切换，并在另一条实际 running 任务期间通过正式 Shot PATCH 制造 source revision 漂移；记录全部服务、queue/history、Task、DB、媒体与最终资源态。不得 mock、直接写 DB/文件、手工换图、切旧库、重试旧 failed Task、复用旧 request_id 或沿用 C009/既有 T12 日志冒充。
  - **R：** R4、R5、R5a、R6、R7、R8、R9、R10；PRD §3.1-§3.3、§6.1-§6.3、§7、§9、§11 M4、§12.1-§12.4。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 take 与生成交互：多任务提交、完整失败原因、take 画廊/current/delete/media/DEBUG 与两维状态刷新`；`C010 Director REST/WS 竞态：socket-first 缓冲、旧响应失效、replacement refresh、task detail 去重与成功通知后置`；`C010 M4 生产浏览器闭环：真实 API/WS/PostgreSQL/vLLM/Comfy 下创建、生成、take、stale 与 R5a/R10/R12 异常路径`；`C010 MiniMax workflow 外部枚举绑定：节点 310 LoRA 注册名与当前 Comfy object_info 一致、hash 更新且无路径猜测或 fallback`；`C010 自洽 Director 夹具参考图：无需用户素材或旧库，driver 经正式 API 生成/上传/回读 13 张生产可加载图片`；`C010 Comfy execution_error 真实协议：node_id 完整原因、跨 prompt 隔离、failed/no-take/no-retry 与 free-once`；`§3.2 完成判定反竞态：source_revisions 全一致时回写 fresh/normal；任一不一致时产物仍保存且不得覆盖 stale/changed；generation_state 始终按 C009 聚合`。
  - **验收方式与命令/人工检查：** 新库创建前证明名称不存在且不同于所有既有 T12 库，执行 `python -m alembic upgrade head/current/check`，使用新的绝对 DATA_DIR，再运行 T11B 已验收的同一个 T10A driver 建立已披露的确定性 Shot与 13 张自动图片前置；生成前按 T11B 的正式 API/媒体回读检查再次精确证明 13 张图片均为 `512×512` RGB、非单色且 bytes 两两不同，全程不接受人工文件。用正式设置 API从 `C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md` 安装模板并 GET 逐字核对。发起任何生成前重新保存当前 Comfy `/object_info` 并断言节点 310 的精确值仍在允许列表；读取 `.work/c010/T11A-workflow-hash.txt`，用重启后的生产后端检查 health 必须 vLLM/Comfy healthy、bindings valid、`hashes.minimaxh3` 与该记录值逐字相等，Comfy queue 初始为空。浏览器完成 AC-15 主路径：同场景连续三 Shot preview/create，槽位顺序可见，点击生成并记录 queued/generating/ready、WS、task_id、prompt_id、Comfy `POST /prompt` 200、完整 history、take/media/seed/actual；再次点击得到第二 seed/take，切 current。另建/复用合法 Clip，待新 Task 与 Comfy prompt 确认 running 后经正式 Shots 页面/API修改所含 Shot，任务 done 后断言 take 保存而 Clip stale/Shot changed。两轮旧 failed Task 只读核对仍为 failed，不调用重试或重复提交其 request。driver 完成后全部被验收操作不得直写 DB/文件。新证据使用不覆盖旧文件的 `.work/c010/T12-rerun-*` 名称；终态要求 temp 空、Comfy queue 空、vLLM sleeping、页面与 REST/DB一致。若任一新 Task failed，停止前必须按 payload prompt_id 保存该次原始 `/history/{prompt_id}`，不得只记录后端二次错误。外部文件缺失、`object_info`/health/hash/queue 前置不满足、无法在 running 窗口完成编辑或任一真实任务失败时立即停止，不以 C009 成功、既有 T12 失败资料、静态 MP4、mock、手工素材或旧库替代。

- [x] **T13 — 最终全量回归、追溯回填、范围审计与完成报告**

  - **交付：** 用全新最终 PostgreSQL 重跑 Alembic、完整 frontend test/build 与完整 pytest；逐条映射 AC-01..20 到代码、新/窄修正测试、T11A 获授权的四个 hash 常量、T11B fixture、T11C node_id 与 T11/T12 原始证据，回填所有 C010 追溯行真实 node ID/证据路径；创建 `.work/c010/completion-report.md`，不新增实现。
  - **R：** R5、R5a、R6、R7、R8、R9、R10、R12；PRD §0、§3、§9、§11 M4、§12。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`；`C010 MiniMax workflow 外部枚举绑定：节点 310 LoRA 注册名与当前 Comfy object_info 一致、hash 更新且无路径猜测或 fallback`；`C010 自洽 Director 夹具参考图：无需用户素材或旧库，driver 经正式 API 生成/上传/回读 13 张生产可加载图片`；`C010 Comfy execution_error 真实协议：node_id 完整原因、跨 prompt 隔离、failed/no-take/no-retry 与 free-once`，并审计全部 C010 行。
  - **验收方式与命令：** 创建名为 `ai_drama_studio_c010_final_<timestamp>` 且现场证明不存在的数据库，显式导出其 `DATABASE_URL` 和新的 `.work/c010/T13-data`，依次运行并保留原生 stdout/stderr。若此前已在同一实现/测试 commit 上完成 Alembic、完整后端、完整前端测试与 build，仅因下述源码文本检查误把 Python 相邻字符串拼接判为失败，则保留首次失败的 `T13-workflow-scope.log`，允许从修正后的 scope 检查继续，输出另存为 `T13-workflow-scope-rerun.log`；复跑前若实现、迁移、前端或测试发生 tracked 改动，必须从头重跑全部门槛：

    ```powershell
    Set-Location D:\ai_drama_studio\backend
    python -m alembic upgrade head 2>&1 | Tee-Object -FilePath '..\.work\c010\T13-alembic-upgrade.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python -m alembic current 2>&1 | Tee-Object -FilePath '..\.work\c010\T13-alembic-current.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python -m alembic check 2>&1 | Tee-Object -FilePath '..\.work\c010\T13-alembic-check.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python -m pytest -q 2>&1 | Tee-Object -FilePath '..\.work\c010\T13-full-pytest.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Set-Location ..
    npm --prefix frontend run test 2>&1 | Tee-Object -FilePath '.work\c010\T13-frontend-test.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    npm --prefix frontend run build 2>&1 | Tee-Object -FilePath '.work\c010\T13-frontend-build.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $baseline = (Get-Content -LiteralPath '.work\c010\baseline-sha.txt' -Raw).Trim()
    git diff --check
    git diff --name-status "$baseline..HEAD" | Tee-Object -FilePath '.work\c010\T13-scope.log'
    $backendAndOldActive = @(git diff --name-only "$baseline..HEAD" -- backend openspec/changes/c009)
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $allowedBackend = @(
        'backend/workflows/minimax_h3_ref2v.json',
        'backend/app/tasks/gen_clip_video.py',
        'backend/tests/api/test_c007_health.py',
        'backend/tests/api/test_c009_health.py',
        'backend/tests/api/test_system.py',
        'backend/tests/unit/test_c009_workflow_binding.py',
        'backend/tests/task_system/test_c009_review_worker_failures.py'
    )
    $forbidden = @($backendAndOldActive | Where-Object { $_ -notin $allowedBackend })
    $forbidden | Set-Content -LiteralPath '.work\c010\T13-forbidden-diff.log'
    if ($forbidden.Count -ne 0) { $forbidden; exit 1 }
    @'
    import copy
    import hashlib
    import json
    import re
    import subprocess
    from pathlib import Path

    baseline = Path(".work/c010/baseline-sha.txt").read_text(encoding="utf-8").strip()
    workflow_path = Path("backend/workflows/minimax_h3_ref2v.json")
    before = json.loads(subprocess.check_output(["git", "show", f"{baseline}:backend/workflows/minimax_h3_ref2v.json"]))
    after = json.loads(workflow_path.read_text(encoding="utf-8"))
    expected = copy.deepcopy(before)
    expected["310"]["inputs"]["lora_name"] = "minimax_h3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
    assert after == expected, "workflow differs outside node 310 lora_name"
    digest = hashlib.sha256(workflow_path.read_bytes()).hexdigest()
    recorded = Path(".work/c010/T11A-workflow-hash.txt").read_text(encoding="ascii").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", recorded), recorded
    assert digest == recorded, (digest, recorded)
    assert digest != "bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780", digest
    old_hash = b"bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780"
    new_hash = b"4f078c121b8ec0d9023e775e0b052036407a5f75bf626d13ea223ebf3d5b4772"
    test_files = (
        "backend/tests/api/test_c007_health.py",
        "backend/tests/api/test_c009_health.py",
        "backend/tests/api/test_system.py",
        "backend/tests/unit/test_c009_workflow_binding.py",
    )
    for name in test_files:
        prior = subprocess.check_output(["git", "show", f"{baseline}:{name}"]).replace(b"\r\n", b"\n")
        current = Path(name).read_bytes().replace(b"\r\n", b"\n")
        assert prior.count(old_hash) == 1, (name, prior.count(old_hash))
        assert current == prior.replace(old_hash, new_hash), f"unauthorized test diff: {name}"
    error_test = "backend/tests/task_system/test_c009_review_worker_failures.py"
    prior = subprocess.check_output(["git", "show", f"{baseline}:{error_test}"]).replace(b"\r\n", b"\n")
    current = Path(error_test).read_bytes().replace(b"\r\n", b"\n")
    assert prior.count(b'"node": None') == 2, prior.count(b'"node": None')
    assert prior.count(b'"node": "168"') == 2, prior.count(b'"node": "168"')
    assert prior.count(b'"node=168 type=T25StubNode exception=T25 WS stage failure"') == 1
    expected_error_test = prior.replace(b'"node": None', b'"node_id": None')
    expected_error_test = expected_error_test.replace(b'"node": "168"', b'"node_id": "168"')
    expected_error_test = expected_error_test.replace(
        b'"node=168 type=T25StubNode exception=T25 WS stage failure"',
        b'"node_id=168 type=T25StubNode exception=T25 WS stage failure"',
    )
    assert current == expected_error_test, f"unauthorized test diff: {error_test}"
    handler = Path("backend/app/tasks/gen_clip_video.py").read_text(encoding="utf-8")
    assert 'data.get("node_id")' in handler
    assert 'data.get("node")' not in handler
    assert '"Comfy execution_error "' in handler
    assert 'f"node_id={node} type={node_type} exception={exception_message}"' in handler
    print(f"C010_WORKFLOW_EXACT_DIFF=PASS HASH={digest}")
    print("C010_HASH_TEST_BASELINE_EXACT_DIFF=PASS")
    print("C010_COMFY_NODE_ID_EXACT_DIFF=PASS")
    '@ | python - 2>&1 | Tee-Object -FilePath '.work\c010\T13-workflow-scope-rerun.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $pending = rg -n 'C010 .*\|.*待填' openspec/TRACEABILITY.md
    if ($LASTEXITCODE -eq 0) { $pending; exit 1 }
    if ($LASTEXITCODE -ne 1) { exit $LASTEXITCODE }
    git status --short
    ```

    期望：Alembic 唯一 current head且 `No new upgrade operations detected.`；所有测试/build exit 0；forbidden diff 为空；workflow scope 检查精确 PASS，raw hash 与 T11A 现场记录、生产 loader/health 逐字一致且不同于修正前值；四个既有测试文件各自只含旧→新 hash 单常量替换，worker failure 测试只含四个 `node_id` key与一个错误标签替换，其他既有测试零 diff；视频 handler 不再读取 `node`；T11B driver/图片保持未跟踪且不入 commit；每个新增/修正测试真实 node ID/人工证据已回填；scope 每项对应 task。完成报告至少含：baseline/commit 映射、checkbox/追溯、实际命令与原始结果、外部依赖/资源终态、逐条“操作 → 观测值”浏览器走查、未验证项与沉淀。缺一项不得勾选或提交。该 task 的原结论已被 Sol 复审重新打开；其历史日志保留，但不能替代 T14-T21 修复后的最终一致性。

- [x] **T14 — 封闭 Director REST 成功体的 ID、seed 与媒体 URL 边界**

  - **交付：** 在 C010 Director 消费成功响应、投影和媒体值的边界增加运行时校验，不以 TypeScript `as` 代替。所有会进入后续 API 路径的 Project/Episode/Asset/Shot/Clip/Slot/Video id 与 `slot_no` 必须是正的 JavaScript safe integer且不强转；ClipVideo seed 必须是 `0..2^63-1` 的十进制 string并保持逐字值；Slot 图片只接受 null、`image_source=asset_current` 对应的 `/media/asset-images/{正整数}`，或 `image_source=override` 对应的 `/media/slot-overrides/{当前 slot.id}`；take 只接受 `/media/clip-videos/{当前 video.id}`。拒绝 ID/source 不匹配、绝对/协议相对/`file:`、反斜杠、`.`/`..`、query、fragment与错类型；ClipVideo 可选 DEBUG 键只允许 `built_prompt/input_snapshot`，出现 `input_hash` 必须报 protocol error。畸形值必须在任何基于该值的 fetch、站外/媒体 DOM 请求或业务 state mutation 前产生可见 `ApiProtocolError`。只修改 C010 实际消费边界所需的前端 API/model/page文件；不得修改后端、schema、已有测试、引入兼容强转、默认值、fallback 或新依赖。新增且只新增独立回归文件 `frontend/src/features/director/directorReviewRestBoundary.test.ts`。
  - **R：** R9、R11；PRD §3.4、§3.5、§9；D-012 公共 seed string 约定。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 复审 REST 成功体边界：Director ID、seed 与媒体 URL 运行时校验，敌意值在查询/DOM 前失败`。
  - **验收方式与命令：** 新用例必须逐项注入 review 探针中的 `https://attacker.invalid/reference.png`、`file:///C:/Windows/win.ini`、`9223372036854775807` number，以及 unsafe/string/bool/float ID、协议相对、穿越、query/fragment URL；精确断言错误类型/message、零后续 fetch 与零媒体节点消费，并保留合法最大 seed string与合法媒体 URL。执行 `npm --prefix frontend run test -- src/features/director/directorReviewRestBoundary.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`；另建 `ai_drama_studio_c010_t14_<timestamp>` 全新库，显式 `DATABASE_URL` 后在 `backend` 执行 `python -m alembic upgrade head`、`python -m pytest -q`。全部 exit 0 后回填真实用例 ID、勾选并单独提交；既有测试文件必须零 diff。

- [x] **T15 — 校验 Task REST/WS 成功体并阻止非法 task_id 改写请求路径**

  - **交付：** 为复用的 Task REST 与 `/ws/tasks` JSON 增加运行时合同：顶层必须是对象，task/target id 为正 safe integer，type/status 属于既有枚举，progress 为有限 0..1 number，message/error/timestamp 字段符合公开 nullable/string 类型；null、array、未知枚举、错类型、unsafe integer及路径型 string 均为 protocol error。非法 WS 事件必须在 `getTask` 前失败并形成 Director 可观察错误，不得产生 `/api/tasks/../../...`、URL 归一后的其他请求或未处理异常；合法未知 task 仍保持每个 id 至多一个 detail GET。只修改 `frontend/src/api/tasks.ts`、`frontend/src/api/ws.ts` 与必要的 Director 协调器错误接线；不得创建 Director 私有 Task 格式、修改后端/既有测试或吞异常。新增独立回归文件 `frontend/src/features/director/directorReviewTaskBoundary.test.ts`。
  - **R：** 无；PRD §6.4、§9；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 复审 Task REST/WS 边界：事件与详情字段运行时校验，非法 task_id 不发请求`。
  - **验收方式与命令：** 用生产 parser/controller 注入 `task_id="../../system/health"`、`Number.MAX_SAFE_INTEGER+1`、null/array、错 type/status/progress/message 和畸形 Task detail；断言零详情请求或请求路径严格未发生、原始 protocol error 可观察、socket按现有协议错误路径关闭且无 polling/retry。合法事件仍断言唯一 detail GET。执行 `npm --prefix frontend run test -- src/features/director/directorReviewTaskBoundary.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`，并按 T14 方式在 `ai_drama_studio_c010_t15_<timestamp>` 新库运行 `python -m alembic upgrade head` 与 `python -m pytest -q`；通过后回填、勾选、单独提交，既有测试零 diff。

- [x] **T16 — 修复 terminal detail 与页面 refresh 交错时的事件丢失**

  - **交付：** 修正 DirectorSync：terminal event 已记录、其唯一 Task detail 尚在途，而另一次页面 refresh 随后开始或已经在途时，不得因 `pageRequest !== null` 直接遗弃记录。事件必须精确消费一次；若当前 refresh 开始于事件提交之后，可绑定该提交后快照，否则使旧响应失效并补发 replacement。最终必须应用事件提交后的页面事实或显示最新错误，相关 selected Clip 详情按需刷新，done/failed语义不变；不得 polling、重复 detail GET、自动重放 mutation或重复通知。新增独立回归文件 `frontend/src/features/director/directorReviewTerminalRace.test.ts`，不得修改既有测试。
  - **R：** 无；PRD §6.4、§9；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 复审 terminal 竞态：detail 与页面 refresh 交错时事件不丢失且通知后置`。
  - **验收方式与命令：** 用 deferred Promise 精确复现 `.work/c010/probe-director-sync-races.log` 的顺序：ready 后 terminal event 到达、detail pending、手工/ mutation page refresh 开始、detail 再完成。断言 record 精确一次 consumed、detail GET=1、页面请求使用提交后快照或精确一条 replacement、旧响应零应用、terminal notice 晚于所需页面/详情且精确一次、最终无永久 loading。再覆盖事件在 refresh 开始后到达的既有 D-008 顺序。执行 `npm --prefix frontend run test -- src/features/director/directorReviewTerminalRace.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`，并在 `ai_drama_studio_c010_t16_<timestamp>` 新库运行 `python -m alembic upgrade head`、`python -m pytest -q`；通过后回填、勾选、单独提交。

- [x] **T17 — 让 ready 页面中的 Task detail/socket 错误实际可见**

  - **交付：** Director 页面必须渲染协调器在 ready 快照期间产生的 Task detail failure 与 socket error；可以保留最后一份已知页面数据，但必须同时显示原始 client/protocol message，不能只写入内部 `state.error`，不能要求 event 已经是 failed 才显示，也不能把错误替换为成功通知。socket协议错误的既有关闭/重连节奏、Task failed完整 `error_msg` 和普通 action error保持。新增独立回归文件 `frontend/src/features/director/directorReviewErrorVisibility.test.ts`，不得修改既有测试或为测试增加生产特判。
  - **R：** 无；PRD §6.4、§9；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 复审同步错误可见性：ready 页面仍展示 Task detail/socket 错误`。
  - **验收方式与命令：** 以 production sync/view projection 或实际组件可观察输出分别注入：ready+done event+Task detail transport failure、ready+socket error、合法 failed Task detail。精确断言前两者原始错误可见且无伪成功，第三者仍完整显示服务端 `error_msg`；恢复后的最新成功快照才可清除对应旧连接错误。执行 `npm --prefix frontend run test -- src/features/director/directorReviewErrorVisibility.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`，并在 `ai_drama_studio_c010_t17_<timestamp>` 新库运行 `python -m alembic upgrade head`、`python -m pytest -q`；通过后回填、勾选、单独提交。

- [x] **T18 — 让 mutation 的 404/409 进入权威刷新且绝不重放 mutation**

  - **交付：** save/delete/slot/take/generate 任一 mutation 返回结构化 404 或409时，先逐字保留 `detail.message`，再触发与该动作影响面相符的最新页面/详情刷新；原 mutation 始终精确一次。若刷新确认选中 Clip/Slot/take 已消失，清除幽灵选择/详情；刷新失败则显示最新刷新错误且不显示成功。422/500/transport继续可见且不得产生假 Task/take、乐观业务值或自动 mutation 重放。新增独立回归文件 `frontend/src/features/director/directorReviewMutationRefresh.test.ts`，不得修改既有测试。
  - **R：** R9、R10、R12（槽位/生成分支）；其余无直接 R；PRD §3.3、§3.4、§9。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 复审 mutation 重建：404/409 后刷新权威状态且无自动重放`。
  - **验收方式与命令：** 对五类 action 分别跑 404/409 矩阵；每格精确断言 mutation count=1、错误 message、权威 GET 数与路径、无成功 notice；至少一格让最新列表确认 Clip 消失并断言 selection/detail 清空。另覆盖422与transport确保无假 mutation结果。执行 `npm --prefix frontend run test -- src/features/director/directorReviewMutationRefresh.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`，并在 `ai_drama_studio_c010_t18_<timestamp>` 新库运行 `python -m alembic upgrade head`、`python -m pytest -q`；通过后回填、勾选、单独提交。

- [x] **T19 — 将 save/slot 成功提示绑定到页面与详情的共同最新快照**

  - **交付：** save 和 slot 成功后，局部详情及页面 clips/shots/assets 快照都属于该 action 当前最新 generation且均已应用，才显示精确一次成功提示；详情先完成、页面仍 pending/error或被 WS 更新失效时不得提前提示。replacement 完成后才提示，旧 action/旧 Clip 的响应不得触发提示。take只依赖其正式详情/videos刷新，create/delete/terminal沿用各自已有正确绑定。新增独立回归文件 `frontend/src/features/director/directorReviewNoticeOrdering.test.ts`，不得修改既有测试。
  - **R：** 无；PRD §9；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 复审 mutation 通知：save/slot 成功提示等待页面与详情最新快照`。
  - **验收方式与命令：** deferred Promise 覆盖 save/slot 各两种顺序：detail先完成但page pending；期间 WS event 使page generation失效并产生replacement。断言旧/单边快照阶段 notice=0，最新页面+详情落地后notice=1且内容准确；刷新 error 时notice=0且错误可见。执行 `npm --prefix frontend run test -- src/features/director/directorReviewNoticeOrdering.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`，并在 `ai_drama_studio_c010_t19_<timestamp>` 新库运行 `python -m alembic upgrade head`、`python -m pytest -q`；通过后回填、勾选、单独提交。

- [x] **T20A — 交付浏览器错误路径的一次性故障装置**

  - **交付：** 在 `.work/c010/director-review-fault-server.py` 创建不提交的一次性本机 HTTP 装置，使用标准库或项目已有依赖，提供加载 Director 所需的最小公开 Project/Episode/assets/shots/clips/clip-detail/slots/videos/Task JSON，并按命令行 mode 只让一个指定请求返回结构化404/409/422/500、非JSON或连接中断；所有 mutation请求写入只追加 ledger且不得伪造已成功的数据库/Task/take。不得导入/修改 frontend production模块、写PostgreSQL/媒体、监听非127.0.0.1、创建隐藏fallback或长期endpoint。输出 mode、监听PID/端口、请求方法/path/body/次数及终止证据。
  - **R：** 无；PRD §9；spec §9 验收装置差异。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 复审浏览器补证：Director AC-02..12 缺失路径、修复行为与真实 WS terminal`。
  - **验收方式与命令：** 先执行 `rg -n 'sqlalchemy|DATABASE_URL|asyncpg|clip_videos|INSERT|UPDATE|DELETE FROM|frontend/src' .work/c010/director-review-fault-server.py`，人工确认无 DB/file/media/Task 写入和 production import；执行 `python .work/c010/director-review-fault-server.py --self-check --output .work/c010/T20A-self-check.json`，要求逐项输出 `initial-404/initial-500/initial-non-json/initial-disconnect/mutation-404/mutation-409=PASS`。再以 `python .work/c010/director-review-fault-server.py --mode initial-500 --host 127.0.0.1 --port <已确认空闲端口> --ledger .work/c010/T20A-ledger.jsonl` 启动一轮真实进程，用 `Invoke-WebRequest` 核对HTTP 500和结构化错误体，只停止记录PID并以 `Get-NetTCPConnection` 证明端口释放。原始输出写 `.work/c010/T20A-*`。运行 `npm --prefix frontend run test`、`npm --prefix frontend run build`，并在 `ai_drama_studio_c010_t20a_<timestamp>` 新库运行 `python -m alembic upgrade head`、`python -m pytest -q`；通过后只提交 tasks checkbox与追溯中的装置说明，脚本/ledger不提交。报告必须逐字说明：该装置与生产共用真实 Vite/React/Director客户端及浏览器DOM，但替代FastAPI/PostgreSQL，只证明前端输入后的行为，不能证明后端响应语义或生产数据。

- [x] **T20 — 补齐复审缺失的真实浏览器路径与 WS terminal 证据**

  - **交付：** 先用 T20A 对不可稳定由生产服务制造的初始500/非JSON/network与指定404/409时序验证真实浏览器DOM；再以全新隔离PostgreSQL/DATA_DIR、T11B已验收的自给 fixture driver、生产FastAPI/Vite、正式模板API、真实vLLM/Comfy和生产Task WS完成其余补证。不得复用旧验收库冒充新现场、直接写Task/ClipVideo/媒体、重跑失败Task、伪造WS事件或让故障装置代替正常生产链路。
  - **R：** R5、R5a、R6、R7、R8、R9、R10、R11、R12；PRD §3、§6.4、§9、§11 M4。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 复审浏览器补证：Director AC-02..12 缺失路径、修复行为与真实 WS terminal`；并回填 T14-T19 对应复审行的浏览器补充证据。
  - **验收方式与命令/人工检查：** 先按 T11B/T12 的绝对路径方式创建 `ai_drama_studio_c010_t20_<timestamp>`、显式导出 `DATABASE_URL`/隔离 `DATA_DIR`，从 `backend` 执行 `python -m alembic upgrade head`，启动 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，从仓库根执行 `python .work/c010/director-fixture.py --base-url http://127.0.0.1:8000 --output .work/c010/T20-fixture.json`，再启动 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort`；正式模板只通过设置API安装，DEBUG切换时仅停止并以同一DSN重启本task后端。保存“操作 → HTTP/WS → DOM/数据库观测值”、截图和原始 transcript，至少逐项覆盖：初始404/500/非JSON/network；零场景可选、跨场景/双场景/已占用置灰原因；duration非整数与API越界；合法/非法slot上传、清除与取消；save/delete/slot/take/generate的404/409错误、权威刷新和零重放；0/1/多take、current禁删零请求、non-current确认删除、跨Clip current 422；同一已生成take在 `DEBUG_PROMPTS=false/true` 两次正式后端启动下分别无调试区/只显示built_prompt+input_snapshot且无input_hash；note普通/空串/null/空白与双击在途；真实WS在任务提交前已连接并捕获属于唯一task_id的至少一条raw terminal event，随后Task detail和最新REST落地。正常视频路径至少生成两条可播放take并保持不同seed string/唯一current；资源终态queue空、vLLM sleeping、temp空。任一项缺失或GPU服务不健康即停止，不得勾选。完成后执行 `npm --prefix frontend run test`、`npm --prefix frontend run build`；在生产浏览器验收库只执行 `python -m alembic current`、`python -m alembic check` 及 Task/ClipVideo/MP4/queue 的只读终态核对。另建 `ai_drama_studio_c010_t20_pytest_<timestamp>` 与独立 DATA_DIR，仅执行 Alembic migration 后运行完整 `python -m pytest -q`，并保存真实 exit code；两类数据库均通过后才可回填证据并单独提交（`.work`不提交）。

- [x] **T21 — C010 复审修复最终一致性审计**

  - **交付：** 汇总 T14-T20 的代码、六个新增回归文件、追溯与浏览器证据，更新 `.work/c010/completion-report.md`，明确原复审 BLOCK 的修复前探针、修复提交、回归ID与修复后观测。不得覆盖原失败日志，不得把 T20A 当生产后端证据，不得修改任何既有测试；若复跑仍失败或追溯含待填立即停止。
  - **R：** 无；PRD §0、§3、§9、§11 M4；DECISIONS D-008、D-012。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`；全部 C010 复审追溯行。
  - **验收方式与命令：** 新建 `ai_drama_studio_c010_review_final_<timestamp>` 且证明不存在，显式导出 DSN与隔离DATA_DIR；从 `backend` 执行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`；执行 `npm --prefix frontend run test -- src/features/director/directorReviewRestBoundary.test.ts src/features/director/directorReviewTaskBoundary.test.ts src/features/director/directorReviewTerminalRace.test.ts src/features/director/directorReviewErrorVisibility.test.ts src/features/director/directorReviewMutationRefresh.test.ts src/features/director/directorReviewNoticeOrdering.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`。执行 `git diff --check`、baseline..HEAD name/status/full scope、migration/binding/C009 archive零diff检查、禁止围栏/retry/fallback/continuity/versioning扫描、`rg -n 'C010 .*[|].*待填' openspec/TRACEABILITY.md`（期望无匹配）及既有测试差异精确审计。期望 T14-T20 checkbox/commit/证据相符，新增测试均回填准确ID，原39个前端测试未改弱，完成报告逐AC说明通过或未验证项；全部通过后才勾选并提交。

- [x] **T22 — 封闭 generate-video 成功体的 safe integer 边界**

  - **交付：** 仅在 `frontend/src/api/clips.ts` 的 `generate-video` 成功体 parser 把 `task_id` 从“正整数”提升为“正的 JavaScript safe integer”，复用项目现有 boundary helper；非法成功体必须抛出可见 `ApiProtocolError`，且在 `DirectorPage` 的 `sync.trackTask`、`generationTaskIds`、Task detail GET 或任何刷新前失败。新增独立回归文件 `frontend/src/features/director/directorReviewGenerateTaskIdBoundary.test.ts`；不得修改 `directorReviewRestBoundary.test.ts`、其他既有测试或后端合同，不得强转、截断、hash 或生成替代 ID。
  - **R：** 无；PRD §6.4、§9；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 二次复审 generate-video 成功体：task_id safe integer 与零非法状态污染`。
  - **验收方式与命令：** 新测试通过 production `generateClipVideo` 与 Director 生成提交 seam，依次注入 `Number.MAX_SAFE_INTEGER`、`Number.MAX_SAFE_INTEGER + 1`、string、boolean、float、null、array；精确断言合法最大值只进入一次 `trackTask`，其余均为 `ApiProtocolError` 且 track/state/detail GET/refresh 次数均为 0。执行 `npm --prefix frontend run test -- src/features/director/directorReviewGenerateTaskIdBoundary.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`；另建仅迁移的 `ai_drama_studio_c010_t22_<timestamp>` 与隔离 DATA_DIR，从 `backend` 执行 `python -m alembic upgrade head`，再用 durable wrapper 执行 `python -m pytest -q` 并保存 stdout、stderr、PID 和真实 exit-code 文件。全部 exit 0 后回填真实用例 ID、勾选并单独提交。

- [x] **T23 — 隔离保存 Clip A 与切换到 Clip B 的迟到响应**

  - **交付：** 保存动作必须捕获发起时的 Clip ID/动作 generation。保存 Clip A 在途时允许切换到 Clip B；A 成功后至多发起一次页面列表权威刷新，不得以 A 的动作刷新 B 详情、重置 B 草稿或在 B 上显示 `Clip #A 设置已保存`。若响应返回时仍选中 A，则保持既有“页面+详情均为该动作最新快照后提示一次”的语义；重新选择 A 后通过正式详情 reader 取得保存结果。仅修改 `frontend/src/pages/DirectorPage.tsx` 和确有必要的 `frontend/src/features/director/directorSync.ts`，新增 `frontend/src/features/director/directorReviewOldClipIsolation.test.ts`；不得修改既有测试、禁止选择切换、取消请求或吞掉 A 的成功结果。
  - **R：** 无；PRD §9；DECISIONS D-008。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 二次复审保存切换竞态：旧 Clip 响应不污染当前 Clip 详情与通知`。
  - **验收方式与命令：** 用 deferred Promise 构造 A PATCH pending→选择 B→A resolve→页面 refresh resolve→任一详情 resolve 的确定顺序；观察 production reader ledger、selectedClipId、A/B draft 和 notices，精确断言 selection=B、A PATCH=1、page GET≤1、A 动作导致的 B detail GET=0、B draft 不变、A success notice=0；重新选 A 后 A detail GET=1 且读到保存值。另覆盖响应时仍选 A 的成功提示精确一次。执行 `npm --prefix frontend run test -- src/features/director/directorReviewOldClipIsolation.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`；在仅迁移的新库 `ai_drama_studio_c010_t23_<timestamp>` 上用 durable wrapper 运行完整 `python -m pytest -q` 并保存真实 exit code。全部通过后回填、勾选、单独提交。

- [x] **T24 — 用真实生产消费链替换媒体 URL 的恒真断言**

  - **交付：** 新增独立回归 `frontend/src/features/director/directorReviewMediaConsumption.test.ts`，让 Slot/Video 成功体实际通过 production REST parser、Director model 投影与页面实际使用的媒体 element/sink；若当前 JSX 无可直接调用 seam，只允许把既有 `<img>/<video>` 的最小 presentational consumer 原样抽出并由 `DirectorPage` 实际调用，不得创建第二套 parser、测试专用分支、URL fallback 或新增依赖。不得修改旧 `directorReviewRestBoundary.test.ts`；旧文件中未变动的局部计数器不再作为 AC-23 的通过证据。
  - **R：** R9、R11；PRD §3.4、§3.5、§9。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 二次复审媒体消费证据：生产 parser 到媒体 sink 的敌意 URL 零消费`。
  - **验收方式与命令：** 新测试对合法 asset-current、override 与 clip-video URL 各验证 production consumer 精确设置/读取一次；再逐个注入站外 URL、`file:`、protocol-relative、UNC、`.`/`..`、query、fragment、资源 ID 不匹配和错类型，精确断言 parser 抛 `ApiProtocolError`，production media sink/element `src` 设置及站外 fetch 均为 0。计数只能由被测 consumer 调用改变，禁止测试在调用外手工递增。执行 `npm --prefix frontend run test -- src/features/director/directorReviewMediaConsumption.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`；在仅迁移的新库 `ai_drama_studio_c010_t24_<timestamp>` 上用 durable wrapper 运行完整 `python -m pytest -q` 并保存真实 exit code。全部通过后回填、勾选、单独提交。

- [x] **T25 — 用 Director 实际 action 接线替换 mutation 的自填账本断言**

  - **交付：** 新增 `frontend/src/features/director/directorReviewMutationWiring.test.ts`，测试必须从 `DirectorPage` 实际使用的 save/delete/slot/take/generate action seam 发起；若现有页面闭包不可调用，只允许提取一个由 `DirectorPage` 生产路径实际调用的最小 Director mutation adapter，不得复制 handler、加入测试 hook、改变 UI/HTTP 合同或引入全页状态框架。结构化 404/409 仍逐字显示 `detail.message`，按动作影响面调用正式 page/detail readers，原 mutation 精确一次且无成功 notice。不得修改旧 `directorReviewMutationRefresh.test.ts`；其测试自行填写的 `authorityGets`/`successNotices` 不作为 AC-24 的通过证据。
  - **R：** R9、R10、R12（slot/generate 分支）；其余 R：无；PRD §3.3、§3.4、§9。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 二次复审 mutation 页面接线：五类 404/409 权威 GET、零重放与零伪成功`。
  - **验收方式与命令：** 对实际 save/delete/slot/take/generate action 分别注入结构化 404、409 共 10 格；mutation、GET ledger 和 notices 只能由 production adapter/readers/notice publisher 产生。逐格断言 mutation=1、`detail.message` 精确可见、正式 page/detail GET 方法与路径/次数符合动作影响面、无 mutation 重放且 success notice=0；至少一格由 page reader 返回 Clip 消失并断言 selection/detail 清空。执行 `npm --prefix frontend run test -- src/features/director/directorReviewMutationWiring.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`；在仅迁移的新库 `ai_drama_studio_c010_t25_<timestamp>` 上用 durable wrapper 运行完整 `python -m pytest -q` 并保存真实 exit code。全部通过后回填、勾选、单独提交。

- [x] **T26 — 收回未消费导出与非 Director 顺手硬化**

  - **交付：** 以二次复审基线 `e158338dc89bebad5cd40781b50e6c11de3f989a` 为逐函数对照，删除 C010 新增但 Director 未消费的 `parseProjectListResponse`、`parseEpisodeListResponse` 导出；把 `deleteProject`、`generateAssets`、`readGenerateShotsImpact`、`generateShots`、`deleteEpisode`、`getAssetImageMediaUrl` 中仅由 C010 顺手加入且不服务 Director 的 safe-ID 行为恢复为该基线。必须保留 Director 实际使用的 Project/Episode 单体 parser、list 读取边界、T22 generate task_id 校验及 T23–T25 修复；不得使用 `git checkout/reset` 覆盖用户改动，不得删除调用中的代码或修改任何测试。
  - **R：** 无；PRD §0 范围围栏、§9；AGENTS Change 纪律。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 二次复审范围收口：移除未使用导出与非 Director 顺手硬化`。
  - **验收方式与命令：** 执行 `rg -n 'parseProjectListResponse|parseEpisodeListResponse' frontend/src`，期望零匹配；以 `git diff e158338dc89bebad5cd40781b50e6c11de3f989a -- frontend/src/api/projects.ts frontend/src/api/episodes.ts frontend/src/api/assets.ts` 逐函数核对上述六个非 Director helper 无 C010 行为差异，同时证明 Director 所需 parser/reader 与 T22–T25 diff仍在。执行 `npm --prefix frontend run test`、`npm --prefix frontend run build`、`git diff --check`，并用 `git diff --name-status e158338dc89bebad5cd40781b50e6c11de3f989a..HEAD -- 'frontend/src/**/*.test.ts'` 确认测试 diff 精确为 T14–T19 历史六个新增文件和 T22–T25 四个新增文件，均为 `A`，不存在 `M/D/R`；另在仅迁移的新库 `ai_drama_studio_c010_t26_<timestamp>` 上用 durable wrapper 运行完整 `python -m pytest -q`。全部通过后回填 diff/符号证据、勾选并单独提交。

- [x] **T27 — 审计隔离 headless Edge/CDP 浏览器验收装置**

  - **交付：** 在 `.work/c010/` 审计并按需复用既有 `T20-edge-launch*.py`、`T20-cdp.py`，交付单一不提交的 `.work/c010/director-review-browser-driver.py` 与 `T27-apparatus-audit.log`。驱动必须只连 `127.0.0.1`、使用独立临时 profile、记录启动 PID/完整参数/CDP 目标/结束与端口释放，不得附着或控制用户浏览器；必须提供 `--self-check` 并逐项记录 headless、程序化 click/file selection、`--disable-gpu`、DOM/media 观测与人工浏览器之间的差异。它可以驱动真实 Vite/React/Director、同源 API/WS/media，也可以明确连接 T20A 故障装置，但不得导入生产源码、写数据库/Task/媒体、伪造 WS terminal 或成为仓库长期 E2E runner。
  - **R：** 无；PRD §9；spec §9 验收装置。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 二次复审浏览器装置：隔离 headless CDP 差异、生产终态与修复路径`。
  - **验收方式与命令：** 执行 `rg -n '0\.0\.0\.0|--user-data-dir|--headless|--disable-gpu|127\.0\.0\.1|CDP|websocket|frontend/src|DATABASE_URL|sqlalchemy|asyncpg' .work/c010/director-review-browser-driver.py` 并人工逐项解释匹配；选择已确认空闲的 remote-debugging port，执行 `python .work/c010/director-review-browser-driver.py --self-check --debug-port <端口> --profile .work/c010/T27-edge-profile --output .work/c010/T27-self-check.json`，要求保存 Edge PID、profile 绝对路径、只连 loopback 的网络 ledger、DOM 读取结果和正常终止证据。随后用 `Get-Process -Id <记录PID> -ErrorAction SilentlyContinue` 与 `Get-NetTCPConnection -LocalPort <记录端口> -ErrorAction SilentlyContinue` 证明仅自建进程/监听已释放。原失败输出保留；装置、profile、截图和 ledger 均留在 `.work/`，本 task 只提交 checkbox 与追溯装置说明。

- [x] **T28 — 用审计后的浏览器装置重放修复路径并分离两类数据库**

  - **交付：** 使用 T27 的独立 profile 驱动、真实 Vite/React production modules 与本机 loopback 服务，重放 AC-21 的不安全 `task_id` 和 AC-22 的 A 保存/B 切换；保存“操作 → HTTP/WS → DOM/state 观测值”。同时只读复核 T20 生产浏览器验收库中 Task #1/#2、不同 seed、唯一 current video、MP4 可解码、最终空 queue 与已记录的 service 终态；不得在该库运行完整 pytest、清洗模板/Task、重跑失败 Task或把当前外部服务状态与 T20 终端时证据混写。完整 backend pytest 必须改在另一个全新、仅迁移的干净库与隔离 DATA_DIR。
  - **R：** 无；PRD §6.4、§9、§11 M4；DECISIONS D-008。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 二次复审浏览器装置：隔离 headless CDP 差异、生产终态与修复路径`；`C010 二次复审 generate-video 成功体：task_id safe integer 与零非法状态污染`；`C010 二次复审保存切换竞态：旧 Clip 响应不污染当前 Clip 详情与通知`。
  - **验收方式与命令/人工检查：** 先读取生产 `/openapi.json` 核对本轮使用的 method/path；由 T20A 或同约束的 loopback fault mode 对一次 `generate-video` 返回 `task_id=9007199254740992`，浏览器必须显示 protocol error，ledger 精确记录零 Task detail GET/WS tracking/成功 notice。再以 deferred save mode 让 A PATCH pending，浏览器点击选择 B 后释放 A 响应；精确记录 selected=B、A PATCH=1、A 导致的 B detail GET=0、B draft不变、A success notice=0，重新选择 A 后正式详情 GET 读到保存值。以 `python`/`ffprobe` 或项目既有 PyAV 只读检查 T20 保存 MP4，使用正式 API/DB read-only 查询核对 Task/ClipVideo/current/seed；若当前 Comfy/vLLM 状态与 T20 记录不同只标记漂移，不重写历史通过。运行 `npm --prefix frontend run test`、`npm --prefix frontend run build`；另建 `ai_drama_studio_c010_t28_pytest_<timestamp>`、隔离 DATA_DIR，执行 `python -m alembic upgrade head` 后用 durable wrapper 运行 `python -m pytest -q` 并取得真实 exit-code=0。生产验收库执行 `python -m alembic current`、`python -m alembic check` 和只读终态核对；两侧均满足后回填、勾选并提交，`.work/` 不提交。

- [x] **T29 — C010 二次复审修复最终一致性审计**

  - **交付：** 更新 `.work/c010/completion-report.md`，把六个复审问题逐项映射到 T22–T28 的修复提交、独立测试 ID、浏览器/数据库证据与保留的修复前失败输出；明确 T20 历史正式库 pytest 的 `2 failed, 344 passed` 是数据库职责错误，另列干净库全绿结果，不把二者合并或删去失败。核对 spec AC-21..27、tasks、TRACEABILITY、代码和 commits 一致；不得修改生产代码或任何既有测试。
  - **R：** 无；PRD §0、§3、§9、§11 M4；DECISIONS D-008、D-012。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 二次复审最终一致性：分离验收库与干净回归库并关闭全部 BLOCK`；全部 C010 二次复审追溯行。
  - **验收方式与命令：** 新建 `ai_drama_studio_c010_review_final_<timestamp>` 与隔离 DATA_DIR，先执行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`，再用 durable wrapper 执行 `python -m pytest -q` 并要求真实 exit-code=0。执行 `npm --prefix frontend run test -- src/features/director/directorReviewGenerateTaskIdBoundary.test.ts src/features/director/directorReviewOldClipIsolation.test.ts src/features/director/directorReviewMediaConsumption.test.ts src/features/director/directorReviewMutationWiring.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`。执行 `git diff --check`、`git diff --name-status e158338dc89bebad5cd40781b50e6c11de3f989a..HEAD`、`git log --oneline e158338dc89bebad5cd40781b50e6c11de3f989a..HEAD`、`rg -n 'C010 .*[|].*待填' openspec/TRACEABILITY.md`（期望无匹配）、围栏/versioning/retry/fallback/continuity 扫描及所有既有测试零 diff审计；逐项确认 T22–T28 checkbox/commit/证据一致，四个新测试均有真实用例 ID，完成报告第 5 段按“操作 → 观测值”覆盖正常路径和至少一条异常分支。全部通过后才勾选、回填并单独提交。

- [x] **T30 — 补齐 mutation 资源消失后的 selection/detail 清空回归**

  - **交付：** 严格依 `AGENTS.md` 的 C010 T30 一次性窄授权，只修改 `frontend/src/features/director/directorReviewMutationWiring.test.ts`：保留 T25 五类 action×404/409 既有矩阵逐字不变，追加一个独立测试及其直接必需的 import 与局部装置。测试须从生产 `createDirectorMutationAdapter` action seam 发起一条结构化 404 或 409，让生产 `createDirectorSync` 的 page reader 返回不含当前 Clip 的最新列表；不得修改生产代码、其他测试、spec 或旧追溯证据，不得自填 GET/notice 账本。
  - **R：** 无；PRD §9；DECISIONS D-008；spec AC-24。
  - **计划测试层级：** 任务系统 mock。
  - **追溯行：** `C010 最终复审 mutation 资源消失：生产 adapter 与 page reader 清空 selection/detail`；并补充 `C010 二次复审 mutation 页面接线：五类 404/409 权威 GET、零重放与零伪成功`。
  - **验收方式与命令：** 先保存 `git diff 02f5eeab5a9cc910011ffcf6c53c81733c5a7603^..02f5eeab5a9cc910011ffcf6c53c81733c5a7603 -- frontend/src/features/director/directorReviewMutationWiring.test.ts` 作为 T25 文件基线；修改后逐段证明既有矩阵测试名、五个 case、404/409 循环、mutation/GET/error/no-success 全部断言未变。新用例必须精确断言：原 mutation=1，结构化 `detail.message` 原文可见，权威页面 reader 只发正式 GET 且不重放 mutation，success callback/notice=0，最新 clips 不含目标后 `selectedClipId === null`、`clipDetail === null`，旧详情响应不得重新挂回。执行 `npm --prefix frontend run test -- src/features/director/directorReviewMutationWiring.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`；另建仅迁移的 `ai_drama_studio_c010_t30_<timestamp>` 与隔离 DATA_DIR，从 `backend` 执行 `python -m alembic upgrade head`，再用 durable wrapper 执行完整 `python -m pytest -q` 并保存 stdout、stderr、PID 与真实 exit-code。执行 `git diff --check` 及精确 scope diff；全部 exit 0 后回填真实测试 ID/日志、勾选并单独提交，任一失败立即停止且不得进入 T31。

- [x] **T31 — 修正完成报告证据归属并完成最终一致性复审**

  - **交付：** 不修改生产代码或测试。更新 `.work/c010/completion-report.md`：把 T23 新回归的证据边界准确写成“自动测试覆盖 production `resolveDirectorClipSave` + `createDirectorSync` seam，T28 浏览器重放覆盖实际 `DirectorPage` 调用链”，不得再声称 T23 测试本身穿过 adapter/page；新增 T30 修复前 Sol 探针、修复 commit、真实测试 ID、追溯与复跑结果。核对 AC-24、T30、两条 mutation 追溯行、checkbox 和 commits 一致。
  - **R：** 无；PRD §0、§9、§11 M4；DECISIONS D-008。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 二次复审最终一致性：分离验收库与干净回归库并关闭全部 BLOCK`；`C010 最终复审 mutation 资源消失：生产 adapter 与 page reader 清空 selection/detail`。
  - **验收方式与命令：** 新建 `ai_drama_studio_c010_review_t31_<timestamp>` 与隔离 DATA_DIR，执行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`，再用 durable wrapper 运行完整 `python -m pytest -q` 并要求真实 exit-code=0。执行 `npm --prefix frontend run test -- src/features/director/directorReviewGenerateTaskIdBoundary.test.ts src/features/director/directorReviewOldClipIsolation.test.ts src/features/director/directorReviewMediaConsumption.test.ts src/features/director/directorReviewMutationWiring.test.ts`、`npm --prefix frontend run test`、`npm --prefix frontend run build`；执行 `git diff --check`、规划 commit..HEAD name-status/log、migration/workflow/binding/backend production 零新增 diff、既有测试精确差异审计、围栏/versioning/retry/fallback/continuity 扫描和 `rg -n 'C010 .*[|].*待填' openspec/TRACEABILITY.md`（期望无匹配）。确认 T30 只窄改获授权文件，T25 既有矩阵逐字保留，完成报告不再夸大 T23 测试通路且明确 T28 浏览器证据；全部通过后回填、勾选并单独提交。

- [x] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）

  - **R：** 无；PRD §12 外部环境与运行事实。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`。
  - **验收方式与命令或人工检查：** `git diff -- NOTES.md`；复核 T22–T31 是否产生可跨 change 复用的 safe-integer、旧 Clip 竞态、浏览器装置、资源消失回归或验收库/回归库分工事实，只写已现场验证的端口、命令、依赖状态、坑和真实结果，所有漂移/未验证事实明确标注。确无长期价值内容时不改文件，并在完成报告精确写“NOTES.md：无”。

- [x] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）

  - **R：** 无；PRD §0、§3、§9；DECISIONS D-002、D-004、D-008。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 Director REST/WS 竞态：socket-first 缓冲、旧响应失效、replacement refresh、task detail 去重与成功通知后置`。
  - **验收方式与人工检查：** 完成报告在原候选审计基础上，判断“异步 action 是否必须绑定发起资源 identity”“生产浏览器验收库与干净回归库分工”“一次性 headless 装置的证据边界”是否只是本 spec 的局部落实或需要长期跨 change 决策。不得自行修改 DECISIONS；无新跨 change 约定时精确写“DECISIONS.md 候选项：无”。
  - **归档裁决：** 需求方于 2026-09-07 要求完成决策回填；“异步 action 绑定发起资源 identity、迟到响应不得污染当前资源、404/409 只刷新 REST 权威状态且不得重放 mutation”已补入 D-008。生产验收库/干净回归库分工与一次性 headless 装置证据边界仍属于验收流程，不提升为实现决策。

- [x] change 文档与 commit 状态一致

  - **R：** 无；PRD §11 M4；AGENTS Change纪律。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`。
  - **验收方式与命令：** 执行 `git status --short`、`git diff --check`、`git diff --name-status (Get-Content .work/c010/baseline-sha.txt)..HEAD`、`git log --oneline (Get-Content .work/c010/baseline-sha.txt)..HEAD`，并逐项对照 spec AC、tasks checkbox、TRACEABILITY 与完成报告。期望所有勾选交付已提交，未完成项未宣称通过，`.work/`/下载文件未提交，`openspec/archive/C009/` 相对 C010 执行 baseline 未再次移动或改写且 `openspec/changes/c009/` 保持不存在；binding TOML 与 migration 零 diff，workflow 仅有 T11A/AC-18 节点 310 单叶，后端 Python 仅有 T11C/AC-20 的 `gen_clip_video.py` node_id 修正；既有后端测试仅有 `AGENTS.md` 明列的四个 hash 常量与一个 worker failure 测试的精确替换；T14–T19 的历史生产 diff和六个历史新增测试保持不被改写；T22–T25 新增测试仍精确为四个声明文件，除 T30 获授权在 `directorReviewMutationWiring.test.ts` 追加一个独立分支及直接必需装置外，其余三个文件不变，且 T25 五类 action×404/409 矩阵逐字保留；T26 明列的非 Director 顺手改动已收回；T27/T28 装置和全部证据保持未跟踪；T29、T30、T31、三个收尾 checkbox、追溯回填、提交和报告一致；C012 独立获授权文档 commit 不得冒充 C010 实现证据。
