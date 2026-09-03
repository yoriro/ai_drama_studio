# C010 M4 导演台 UI Tasks

## 执行纪律与固定回归命令

- 严格按 T0→T1→…→T10→T10A→T11→T11A→T12→T13→三个收尾 task 执行；任一验收命令或人工门槛失败立即停止，不勾选、不回填“已通过”、不提交该 task，也不先做后续 task。
- 每个 task 只提交其列出的生产/新测试/文档文件和当次 checkbox/追溯回填；不得提交 `.work/`、下载目录工件或无关用户改动。现有任何测试文件均不得修改、删除、skip、改名或弱化；唯一例外是 T11A 按 `AGENTS.md` C010 窄授权精确替换四个文件各一个旧 hash 常量，除此之外仍零测试 diff。
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

  期望：frontend test、build、完整 pytest 与 `git diff --check` 均 exit 0；日志保留原生汇总。固定回归不能替代本 task 的定向断言或浏览器证据。

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

- [ ] **T12 — 真实 MiniMax 浏览器生成、take 与 stale 竞态验收**

  - **交付：** T11A 通过并提交后，保留首次 T12 的失败数据库、failed Task、DATA_DIR 与日志不动，另建全新 PostgreSQL、隔离 DATA_DIR、全新实体与新 Task；以生产浏览器→Vite→FastAPI→Task/WS→vLLM/Comfy→MP4 全通路完成两次视频生成、播放/current 切换，并在另一条实际 running 任务期间通过正式 Shot PATCH 制造 source revision 漂移；记录全部服务、queue/history、Task、DB、媒体与最终资源态。不得 mock、直接写 DB/文件、重试旧 failed Task、复用旧 request_id 或沿用 C009/首次 T12 日志冒充。
  - **R：** R4、R5、R5a、R6、R7、R8、R9、R10；PRD §3.1-§3.3、§6.1-§6.3、§7、§9、§11 M4、§12.1-§12.4。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 take 与生成交互：多任务提交、完整失败原因、take 画廊/current/delete/media/DEBUG 与两维状态刷新`；`C010 Director REST/WS 竞态：socket-first 缓冲、旧响应失效、replacement refresh、task detail 去重与成功通知后置`；`C010 M4 生产浏览器闭环：真实 API/WS/PostgreSQL/vLLM/Comfy 下创建、生成、take、stale 与 R5a/R10/R12 异常路径`；`C010 MiniMax workflow 外部枚举绑定：节点 310 LoRA 注册名与当前 Comfy object_info 一致、hash 更新且无路径猜测或 fallback`；`§3.2 完成判定反竞态：source_revisions 全一致时回写 fresh/normal；任一不一致时产物仍保存且不得覆盖 stale/changed；generation_state 始终按 C009 聚合`。
  - **验收方式与命令/人工检查：** 新库创建前证明名称不存在且不同于所有既有 T12 库，执行 `python -m alembic upgrade head/current/check`，使用新的绝对 DATA_DIR，再运行 T10A driver 建立已披露的确定性 Shot 前置；用正式设置 API从 `C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md` 安装模板并 GET 逐字核对。发起任何生成前重新保存当前 Comfy `/object_info` 并断言节点 310 的精确值仍在允许列表；读取 `.work/c010/T11A-workflow-hash.txt`，用重启后的生产后端检查 health 必须 vLLM/Comfy healthy、bindings valid、`hashes.minimaxh3` 与该记录值逐字相等，Comfy queue 初始为空。浏览器完成 AC-15 主路径：同场景连续三 Shot preview/create，槽位顺序可见，点击生成并记录 queued/generating/ready、WS、task_id、prompt_id、Comfy `POST /prompt` 200、history、take/media/seed/actual；再次点击得到第二 seed/take，切 current。另建/复用合法 Clip，待新 Task 与 Comfy prompt 确认 running 后经正式 Shots 页面/API修改所含 Shot，任务 done 后断言 take 保存而 Clip stale/Shot changed。首次失败 Task 只读核对仍为 failed，不调用重试或重复提交其 request。driver 完成后全部被验收操作不得直写 DB/文件。新证据使用不覆盖旧文件的 `.work/c010/T12-rerun-*` 名称；终态要求 temp 空、Comfy queue 空、vLLM sleeping、页面与 REST/DB一致。外部文件缺失、`object_info`/health/hash/queue 前置不满足、无法在 running 窗口完成编辑或任一真实任务失败时立即停止，不以 C009 成功、首次 T12 失败资料、静态 MP4 或 mock 替代。

- [ ] **T13 — 最终全量回归、追溯回填、范围审计与完成报告**

  - **交付：** 用全新最终 PostgreSQL 重跑 Alembic、完整 frontend test/build 与完整 pytest；逐条映射 AC-01..18 到代码、新测试、T11A 获授权的四个既有 hash 常量、T11/T11A/T12 原始证据，回填所有 C010 追溯行真实 node ID/证据路径；创建 `.work/c010/completion-report.md`，不新增实现。
  - **R：** R5、R5a、R6、R7、R8、R9、R10、R12；PRD §0、§3、§9、§11 M4、§12。
  - **计划测试层级：** 跨进程/资源生命周期。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`；`C010 MiniMax workflow 外部枚举绑定：节点 310 LoRA 注册名与当前 Comfy object_info 一致、hash 更新且无路径猜测或 fallback`，并审计全部 C010 行。
  - **验收方式与命令：** 创建名为 `ai_drama_studio_c010_final_<timestamp>` 且现场证明不存在的数据库，显式导出其 `DATABASE_URL` 和新的 `.work/c010/T13-data`，依次运行并保留原生 stdout/stderr：

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
        'backend/tests/api/test_c007_health.py',
        'backend/tests/api/test_c009_health.py',
        'backend/tests/api/test_system.py',
        'backend/tests/unit/test_c009_workflow_binding.py'
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
    print(f"C010_WORKFLOW_EXACT_DIFF=PASS HASH={digest}")
    print("C010_HASH_TEST_BASELINE_EXACT_DIFF=PASS")
    '@ | python - 2>&1 | Tee-Object -FilePath '.work\c010\T13-workflow-scope.log'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $pending = rg -n 'C010 .*\|.*待填' openspec/TRACEABILITY.md
    if ($LASTEXITCODE -eq 0) { $pending; exit 1 }
    if ($LASTEXITCODE -ne 1) { exit $LASTEXITCODE }
    git status --short
    ```

    期望：Alembic 唯一 current head且 `No new upgrade operations detected.`；所有测试/build exit 0；forbidden diff 为空；workflow scope 检查精确 PASS，raw hash 与 T11A 现场记录、生产 loader/health 逐字一致且不同于修正前值；四个既有测试文件各自只含旧→新 hash 单常量替换，其他既有测试零 diff；每个新增测试真实 node ID/人工证据已回填；scope 每项对应 task。完成报告至少含：baseline/commit 映射、checkbox/追溯、实际命令与原始结果、外部依赖/资源终态、逐条“操作 → 观测值”浏览器走查、未验证项与沉淀。缺一项不得勾选或提交。

- [ ] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）

  - **R：** 无；PRD §12 外部环境与运行事实。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`。
  - **验收方式与命令或人工检查：** `git diff -- NOTES.md`；只写 T0/T11/T12/T13 已现场验证且可复用的端口、启动命令、依赖状态、浏览器/WS/数据库坑和真实结果，所有漂移/未验证事实明确标注。确无长期价值内容时不改文件，并在完成报告精确写“NOTES.md：无”。

- [ ] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）

  - **R：** 无；PRD §0、§3、§9；DECISIONS D-002、D-004、D-008。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 Director REST/WS 竞态：socket-first 缓冲、旧响应失效、replacement refresh、task detail 去重与成功通知后置`。
  - **验收方式与人工检查：** 完成报告逐项判断“零场景在单场景选择中仍可选、preview 动态硬上限推导、requested duration 保存门槛与 note 随生成提交、Director D-008 实现形态”是否只是 PRD/spec 的局部落实或需要长期跨 change 决策。不得自行修改 DECISIONS；无新跨 change 约定时精确写“DECISIONS.md 候选项：无”。

- [ ] change 文档与 commit 状态一致

  - **R：** 无；PRD §11 M4；AGENTS Change纪律。
  - **计划测试层级：** 不新增自动测试。
  - **追溯行：** `C010 范围、零 migration、构建回归与完成证据`。
  - **验收方式与命令：** 执行 `git status --short`、`git diff --check`、`git diff --name-status (Get-Content .work/c010/baseline-sha.txt)..HEAD`、`git log --oneline (Get-Content .work/c010/baseline-sha.txt)..HEAD`，并逐项对照 spec AC、tasks checkbox、TRACEABILITY 与完成报告。期望所有勾选交付已提交，未完成项未宣称通过，`.work/`/下载文件未提交，`openspec/archive/C009/` 相对 C010 执行 baseline 未再次移动或改写且 `openspec/changes/c009/` 保持不存在；后端 Python、binding TOML 与 migration 零 diff，workflow 仅有 T11A/AC-18 节点 310 单叶修正，既有测试仅有 `AGENTS.md` 明列四个常量的精确旧→新替换。
