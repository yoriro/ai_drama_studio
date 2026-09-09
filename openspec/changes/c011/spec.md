# C011 M5 全局 UI/UX 收尾

## 目标与边界

### 目标

在 C010 已交付功能上完成 PRD §11 M5：统一导航、响应式视觉、任务中心取消/历史/过滤及异常、空态和 changed/stale 呈现。落实来源返回、剧集唯一入口与FrameStudio视觉参考；2026-09-08走查追加白紫亮色/暗色切换、统一后退图标、绑定资产勾选行对齐及导演台镜头增宽。四项追加是需求方明确授权的前端范围，保留既有业务功能，并在T25前完成实现和全站重新验收。

### 范围内

1. 全站壳及项目、项目详情、集工作区四个选项卡、设置、任务中心的视觉与响应式统一。
2. 设置/任务中心的来源返回，保留项目、集和选项卡身份；项目详情以集标题作为唯一进入集的入口，编辑/删除集仍独立存在。
3. 用既有 Task REST/WS 接入状态、类型、数量过滤、有限历史分组、任务详情和单项取消；修复此接线必需的 REST/WS 竞态与可见错误。
4. 统一既有加载、空态、错误、业务警示与两维状态的展示；不改变业务条件、生成方式、请求身份和数据生命周期。
5. 为这些可观察行为补独立测试、定向受控验收与真实浏览器人工视觉验收。既有测试除AGENTS.md明确授权的C011 T05窄例外外逐字保留；所有新增用例先有追溯行。
6. 增加仅本浏览器保存的明暗主题选择；统一已有返回入口外观但保留目标语义；修复原生checkbox的文字布局；提高三轨共同时间轴的像素尺度但保持duration_est比例、顺序及选择约束。

### 范围外

- 后端生产 Python、API/schema、数据库/索引/迁移、工作流/binding、模板正文、GPU 调度和队列状态机变更。当前源码已提供任务中心所需接口；若实施中发现后端缺陷阻塞本 spec，停止并报告，不把修复夹带入 UI task。
- C012 的四模板自动部署、生产等价全链路生成、全级联矩阵、恢复/trash 发布验收。本 change 的局部回归不能声明 M6 完成。
- 全量无限任务历史、offset/cursor 分页、搜索/日期/项目过滤、任务删除/清空/批量取消/重试、独立 generation_runs 或任务结果归档。历史仅使用既有 tasks 读取窗口。
- 登录、用户系统、社区/作品流、首页一句话生成、示例 prompt 点击生成、风格市场、密度切换器、项目封面生成。主题切换仅按需求方2026-09-08明确授权的§3.3实现，不扩展为主题编辑器、跟随系统第三模式或账户偏好同步。
- §0 围栏全部机制，包括音频轨占位。沿用 C010 对 §9 音频预留的解释，不创建音频控件、数据或扩展点。
- 自动保存、跨页面草稿仓库、编辑恢复/导航拦截业务、全站状态框架、事件表、持久事件回放、额外锁/hash/签名/版本机制。返回恢复路由位置；现有显式保存与卸载草稿语义保持不变。

### 现状/影响

2026-09-07 只读核对，规划基线为 `1ef70e5d5fad245d6e38e1472eaa16ffb523aa59`：

| 当前证据 | 结论与影响 |
|---|---|
| `openspec/ROADMAP.md` C011；`git log -3 --oneline` 有 `1ef70e5 Archive completed C010 change` | 前序 C010 已归档；本轮未读归档 tasks，以 DECISIONS 和当前代码判断能力 |
| `frontend/src/components/AppShell.tsx` 只有项目/设置/任务中心 NavLink；各页面还有普通 `/tasks` Link | 没有来源返回。必须覆盖主导航和页面内任务中心/设置链接，不能只改 header |
| `routes/AppRoutes.tsx` 的四条集 tab URL；`EpisodeWorkspacePage.tsx` 以 activeTab 渲染 | 可用现有 URL 定位到原集原 tab，无需新业务路由；返回后重新读正式 API |
| `ProjectPage.tsx` 集标题与“进入集工作区”都指向同一 `.../script` | 移除重复 Link 即可；不得删除集标题或编辑/删除按钮 |
| `TasksPage.tsx` 已有列表、时间、进度和 WS 初次/重连同步；没有 cancel、过滤、历史控件 | 扩展真实页面，不能再建第二个任务中心；现有同步内部有请求合并和终态详情逻辑，但不能据此声称已满足 D-008 的全部竞态 |
| `api/tasks.ts` 已有严格 Task/事件 parser，listTasks 尚无过滤参数、无 cancel helper | 复用 parser/requestJson；增加查询和无 body cancel 客户端接线，不改变公开字段 |
| `backend/app/api/tasks.py` | GET 先 status/type AND 过滤，再 id DESC、limit（默认 50，1..100）；cancel 为无 body POST、200 Task；上述能力确已存在 |
| `backend/app/main.py::create_app` | 已有 task_handlers、startup_prepare、外部 client factory 注入 seam，可供隔离验收使用，不需生产验收 endpoint |
| `styles.css` 当前为米白背景、深绿导航、棕色强调色；Director 专用 grid 已存在 | 全局 token 与各页残留硬编码色需收口；不改三轨共同列投影和选择规则 |
| `ApiErrorMessage.tsx` 当前拼接 code 与 message | C011 的主错误正文直显 message；code 可单独作为诊断信息，不替换/改写正文 |
| package.json 已有 React 18、React Router 6、Vitest 3.2.4；没有已安装条目的 jsdom/Testing Library | 不换框架或 runner；新增 DOM 行为测试所需的开发依赖须先单列 task，版本以实施时本机 Node 兼容性锁定 |
| `NOTES.md` 同时含早期目录/端口记录与后续修复 | 只作历史线索；当前 services 在线性、可用空库、浏览器验收数据未在本轮验证。现有 `.work/` 未跟踪，保留 |

必须遵守 DECISIONS D-001（单依赖清单）、D-002（同源）、D-004（204 入口）、D-005/D-006/D-007（唯一队列、既有 payload/请求身份）、D-008（REST 权威、提交后事件与 identity）、D-012（seed string）、D-013（真实 health 合同）、D-014（模板部署归 C012）。D-003/D-009/D-010/D-011 的事务/资源/LLM 边界也不得因 UI 收尾改变。

2026-09-08追加现状核查：styles.css已有全站暗色语义变量及color-scheme:dark，没有主题状态/控件/持久化；index.html的theme-color仍为旧米白。返回文本位于AuxiliaryPageReturn、ProjectPage、EpisodeWorkspacePage正常/错误分支。ShotsPage中`.shot-asset-option`的flex声明被更高specificity的`.form-grid label`的grid覆盖，checkbox还继承文本输入的min-height/padding。DirectorPage三轨沿用directorModel的duration_est fr列，CSS每组仅min-width:760px；无逐镜头可读宽度门槛。以上是本次修复对象，不把2026-09-07规划基线描述冒充当前未实现状态。

### 风险

| 风险 | 约束 |
|---|---|
| 返回只回项目页、或在设置与任务中心间循环 | 记录最近一次进入辅助页前的工作 URL；辅助页之间继承来源 |
| 设计参考带入新业务或隐藏原功能 | 附件只作视觉输入，§4 功能清单逐项保留；不得伪造项目/媒体/任务卡片填满页面 |
| 低透明描边和浅灰文字不可读 | 装饰描边与交互焦点分开；正文/标签按 §3 对比度验收 |
| 全局 CSS 改坏 Director 比例/状态色 | 共享轨道列不变；生成态颜色与独立 stale、R8 黄色警示继续保留 |
| 历史筛选仅过滤最新 50 条造成漏报 | status/type 先经服务端过滤再 limit，不能从未过滤缓存推断数据库无匹配任务 |
| running 取消被显示成已取消 | 等待数据库状态；cancel_requested_at 只是请求已记录，200 running 不是 canceled |
| 旧 cancel/GET/WS 污染当前筛选或页面 | task identity、筛选代次与 socket 生命周期隔离；不得乐观伪造终态或重放 POST |
| 受控装置冒充生产生成验收 | §7 明确每条事件、存储、进程与替代边界；报告分开 DOM mock、受控后端和普通生产页面证据 |
| 亮色遗漏状态/弹层或切换卸载工作页 | 两套完整语义色覆盖全页；主题只改根属性与外观状态，禁止用theme作路由/页面key，未保存草稿和在途任务保持 |
| 图标统一后返回含义丢失 | 统一左箭头外观，aria-label/title保留各自目的地；禁止改为统一navigate(-1) |
| 固定镜头最小宽度破坏时长比例 | 三轨共享由最短时长计算的整体最小宽度，保持原fr列比例，不对每列单独钳制或改等宽 |

## 外部依赖

ROADMAP 标注 C011“无新增”；下表区分规划、非 GPU UI 验收和生产服务证据。未现场验证不等于可用，也不要求为普通视觉工作启动 GPU。

| 来源 | 开工或验收门槛 | 当前证据 | 缺失项/阻塞 |
|---|---|---|---|
| PRD §12.1 两个 API workflow 与 binding | 规划/纯前端不依赖 GPU；启动普通后端前需现有绑定 loader 通过；不改文件 | 当前 `backend/workflows/` 有 zimage.json、minimax_h3_ref2v.json、bindings.toml、minimaxh3.toml；C010 已归档 | 文件存在不证明当前 Comfy 可执行。现场 loader/health 未验证，**阻塞普通后端验收启动门槛确认**；不影响本文规划 |
| PRD §12.2 四模板 | 设置 UI 展示/编辑可用明确占位的干净测试库；受控生成按钮入队前须完成 §7.4 的合法人工模板前置，不要求真实生成和正式模板部署 | PRD §7、D-014 已给前序批准来源；2026-09-08 受控 generate-assets 因迁移占位模板变量不全返回409，未到handler barrier | **当前阻塞 T24 四类受控生成按钮验收，T24A完成后解除**。不阻塞普通视觉检查；四模板正式部署/重启逐字回读与消费仍留 C012，人工模板不能冒充正式输入 |
| PRD §12.3 vLLM sleep/wake | 不新增 GPU 调度，不以生成成功为 C011 验收项；受控任务使用显式注入 seam | D-013、NOTES 有历史协议证据；代码有外部 client factory | 本轮未调用服务；**不阻塞非 GPU UI 验收**。不可把 mock health/cancel 当作真实 sleep/wake/interrupt 证据 |
| PRD §12.4 PostgreSQL DSN | 任何 API 集成、任务系统和跨进程验收前，显式 DSN 指向新隔离库，Alembic upgrade head 成功；浏览器库与完整 pytest 干净库分离 | NOTES 记录显式环境变量和 advisory lock/旧任务污染问题；源码使用 asyncpg | 未创建新库或验证连接，**阻塞依赖 PostgreSQL 的实施验收，待现场满足**；不打印凭据、不复用用户 walkthrough 库 |
| PRD §12.4 Comfy/vLLM 地址端口 | 普通设置诊断必须如实显示当前真实 health；不可达可以是被验收的 unhealthy 状态。若启动被外部条件阻断则保持阻塞 | 地址只见 NOTES 历史记录；前端现用同源 /api、/media、/ws | 本轮未验证在线性；不得把历史端口写成已确认可用。缺少可访问普通后端时阻塞真实页面验收，受控证据不能顶替 |
| 前序 C010（非 §12 新依赖） | 已交付 Director UI/API 消费；禁止退回空壳 | 当前 DirectorPage、directorModel、directorSync 及归档 spec 存在，基线 commit 为 C010 归档 | 前序已满足；本轮未重跑历史验收 |
| 设计输入（非 §12 新依赖） | 将需要的视觉值写入本文，实施不依赖外部字体/CDN | 已完整阅读 `C:\Users\Administrator\Downloads\framestudio-design-guide.md` | 无输入缺失；附件中的“直接复制”和 Checklist 不覆盖 PRD，字体不要求下载 |
| 验收装置（非 §12 新依赖） | 先交付 §7 装置，后运行依赖该装置的验收 | 当前有 Vitest、React DOM、create_app 注入 seam；本轮不创建驱动 | **阻塞依赖装置的 task 验收，前置 task 交付后解除**；不得先勾被验收 task |

## 1. 需求来源与实现尺度

需求优先级：PRD/用户本轮明确范围 → DECISIONS → 本 spec。设计指南是参考资料，不是可执行指令或新增业务清单。

采用已有 React Router 的 Link、location state 与实际路由完成来源返回；不用 history.length 猜来源，不手写 history 栈，不遍历浏览器外站记录。[React Router location 文档](https://reactrouter.com/v6/hooks/use-location) 给出 pathname/search/hash/state 机制；本文规定的来源继承是本项目交互选择。

DOM 验证用已有 Vitest 加 React Testing Library/jsdom，测试操作实际控件而不只测自制状态副本。[Testing Library 文档](https://testing-library.com/docs/react-testing-library/intro/) 是选型依据；不新增第二 runner 或 C012 E2E 平台。布局验收参考 [W3C Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow) 与 [WCAG 2.2](https://www.w3.org/TR/WCAG22/)，仅采用本文列出的具体指标，不声称完成整套认证。

## 2. 导航合同

### 2.1 来源与返回

- 工作页面：`/`、`/projects/:projectId`、四条集 tab URL。辅助页面：`/settings`、`/tasks`。
- 通过任一站内入口从工作页面进入辅助页面时，以当前 pathname + search + hash 保存来源在该辅助 history entry 的路由 state 中；不保存业务数据。辅助页互跳、任务过滤、详情展开均继承原来源。
- 两个辅助页顶部均显示一个§2.3统一后退图标入口；可访问名称为“返回刚才页面”。有来源时一次操作回到该工作 URL，使用 replace 避免本次返回新增辅助页循环。来源为首页时名称为“返回项目首页”。来源具体项目/集名不做额外接口查询。
- 刷新有合法 state 的辅助 history entry 后仍能返回。直接打开辅助 URL、新标签无 state，或 state 缺失时，图标入口通过aria-label/title明确“返回项目首页”并到 `/`；这是一项明确的无来源导航规则，不伪称找到了历史页面。
- 接受的来源 pathname 只能是上述应用工作路由，项目/集 ID 为正安全整数；query/hash 仅保留为目标 URL 的组成部分，不从 query 的 returnTo 等字段读跳转授权。外部/协议相对 URL、脚本协议、反斜杠、未知路径、辅助页路径不作为来源。非法非空 state 显示“返回来源无效”，保留明确的“返回项目首页”入口，不导航到该值。
- 返回目标已删除/集不属于项目：由目标页面正式 GET 显示原始 404/归属错误与“返回项目首页”链接；不显示已缓存的旧实体、不自动重建/重定向到另一集。
- 来源按当前标签页 history entry 隔离，不用 localStorage/sessionStorage 全局最近页，不受另一标签页影响。
- 浏览器自身前进/后退继续工作；不劫持原生 back。恢复范围是项目/集/tab URL，不承诺草稿、列表滚动或当前 Clip 选择恢复。原页卸载不提交任何未保存内容，返回以正式 GET 重建既有页面。

### 2.2 唯一集入口

删除 ProjectPage 中“进入集工作区”重复 Link；集标题是原生可聚焦 Link，鼠标点击或 Enter 到同一集 `/script`。编辑/删除及其表单保持独立，点击它们不触发进入集；不把含按钮的整个 article 嵌进 Link。

### 2.3 统一后退图标（2026-09-08追加）

所有现有“返回项目首页”“返回项目”“返回刚才页面”导航入口，包含正常、无来源、非法来源与资源错误分支，采用同一个左箭头SVG图标和40×40 CSS px圆角轮廓控件；图标20×20、currentColor、aria-hidden=true，无外部图标依赖。可见区域只显示箭头，aria-label与title保留原中文目的地名称，键盘焦点满足§3.2；不把所有可访问名称泛化为“返回”。Link仍是Link，原button仍为type=button并响应Enter/Space，不得把Link的Space改为新导航行为。

这只统一外观：项目详情仍回`/`；集工作区仍回当前项目；辅助页仍按§2.1恢复精确来源并replace；非法来源提示文字保留，图标指向首页；资源错误分支仍按原目标处理。不使用history.back/navigate(-1)，不合并或新增返回入口，不将表单取消、对话框关闭、浏览器原生后退按钮改成这类导航。原规范中“显示返回项目首页”等要求自本次追加起指图标的可访问名称/title，目的地规则不变。

## 3. 视觉与响应式合同

### 3.1 采用的视觉值（暗色基线；亮色按§3.3覆盖）

| 角色 | 本 change 值/约束 |
|---|---|
| 全站背景 | `#0a0a0c` |
| 卡片/面板 | `oklch(0.19 0.012 285 / 0.7)`；select 可用 `oklch(0.20 0.012 285)` 实底 |
| 导航 | `oklch(0.18 0.012 285 / 0.72)`，圆角胶囊，玻璃模糊 14–18px；窄屏允许换行，不遮挡页面内容 |
| 装饰描边 | 白色 8%–16% 透明度；选中/焦点/业务状态可使用语义色 |
| 主 CTA | `oklch(0.86 0.19 128)` 青柠，字色 `#0a0a0c`；同一操作组仅一个视觉主按钮，其他操作仍可见可用 |
| 辅色 | `oklch(0.65 0.22 305)` 紫色只作装饰；不得替代 warning/error/生成态编码 |
| 文字 | 主文 `oklch(0.97 0.004 285)`；次文初值 `oklch(0.72 0.01 285)`；更淡颜色仅用于可读性达标的元信息 |
| 圆角 | 导航/chip 胶囊，输入/普通按钮 12px，卡片/面板 18–20px |
| 字体 | 优先系统已可用 Noto Sans SC/Space Grotesk，然后 system-ui；不请求外部字体。保留中文业务文案和 AI Drama Studio 品牌，不改名为 FrameStudio |
| 排版 | 首页 H1 48–80px 自适应、粗字重与负字距；工作页标题 28–40px、面板标题 20px、正文/输入 15–18px；不用 104px 宣传标题挤占工作区 |
| 密度 | 普通页 max-width 1240px，宽屏 gutter 28px、窄屏 16px；卡片 gap 16px；工作区垂直间距 16–32px，表单优先可操作 |
| 动效 | 150–350ms 的色彩/描边反馈；卡片上浮最多 6px且不遮挡；prefers-reduced-motion 时关闭位移/装饰动画；不强制循环光斑 |

这些值在现有 styles.css 集中定义并消费，清除对应旧色值；主题切换按§3.3，不增加CSS框架、远程图标/字体或全局组件注册机制。装饰 eyebrow 可用于页面区块，但不替换中文标题/label。背景装饰不可拦截指针。

### 3.2 布局与可访问性

明暗两主题均须在320×800、390×844、768×1024、1440×900 CSS px验收；2026-09-08追加实现影响的旧暗色截图不能代替最终双主题验收。按2026-09-09 §7.4裁决，T24全页原生200%与动态reduced-motion不再作为完成门槛，仍明确记录未验证范围；四视口不冒称原生缩放证据，现有reduced-motion样式保留并进行源码审计。

- 项目/剧集卡片按宽度重排；表单、设置编辑器、任务卡片在窄屏单列，按钮换行，长错误/ID/模板正文可读。
- 导演台继续“一带两轨一板”，场景带/分镜轨/片段轨共享同一水平滚动容器与列比例，详情窄屏移到轨道下方。允许轨道自身水平滚动；其他页面及页面根不出现水平溢出。
- 集 tab 四项和三个全局导航始终可到达；不能通过 display:none 删除移动端操作。sticky 元素不能盖住焦点或错误正文。
- 所有交互有可见焦点；label 与输入关联、icon-only 控件须有可访问名称。警示由文字加视觉样式表达，不只靠颜色；危险操作仍保留现有确认。
- 正文、表单标签和按钮文本对比度至少 4.5:1，大字至少 3:1；必要交互边界/焦点至少 3:1。在实际合成背景上测量，不能只拿 token 对白底测；非交互装饰描边可维持指南低透明度。
- 主导航/按钮交互目标至少 24×24 CSS px。不得把附件 `outline:none` 原样用于无替代焦点的输入框。
- 真正无图显示“暂无图片/暂无视频”，装饰渐变仅可作为明确占位背景；图片/视频加载失败显示错误，不能换一张装饰图冒充成功。

### 3.3 两套主题与切换状态

默认沿用暗色；亮色以白底、白色面板、紫色主按钮/选中/焦点为主，不能仅对页面背景做反色。复用现有语义变量，在根`data-theme="dark|light"`选择整套值；没有属性时使用暗色基线。亮色token固定如下，未列的字体、圆角、尺寸/布局复用§3.1；对应角色不得残留暗色硬编码。

| 亮色token（统一--color-前缀，shadow-panel例外） | 值 |
|---|---|
| background / surface / surface-soft / surface-strong / surface-input / nav | `#ffffff` / `#ffffff` / `#f7f4ff` / `#ede9fe` / `#ffffff` / `#faf8ff` |
| border / border-strong | `#ddd6e9` / `#80738f` |
| text / text-muted | `#21182f` / `#655b73` |
| primary / primary-foreground / primary-ring / accent-purple | `#7c3aed` / `#ffffff` / `#6d28d9` / `#6d28d9` |
| neutral-surface / neutral-text | `#f3f0f7` / `#51455f` |
| info-surface / info | `#e0f2fe` / `#075985` |
| success-surface / success / success-border | `#dcfce7` / `#166534` / `#15803d` |
| warning-surface / warning | `#fef3c7` / `#854d0e` |
| danger-surface / danger / danger-border | `#fee2e2` / `#991b1b` / `#b91c1c` |
| scene-purple / scene-green / scene-pink / scene-teal | `#ede9fe` / `#dcfce7` / `#fce7f3` / `#ccfbf1` |
| --shadow-panel | `0 12px 32px rgb(46 16 101 / 8%)` |

亮色`color-scheme:light`，暗色`color-scheme:dark`；theme-color随模式分别为`#ffffff`/`#0a0a0c`。按钮hover/选中/disabled、输入/select/checkbox、错误/notice、DEBUG、媒体空态、三轨/scene/status/stale和预检面板均消费当前模式，原始图片/视频像素不加反色滤镜。每种模式均在实际合成背景检查§3.2对比度；信息/成功/警示/错误继续各有独立文字和语义色，亮色紫色不替代黄色R8警示或生成态编码。

AppShell主导航旁提供一个`aria-label="外观主题"`的控件组，包含原生type=button的“暗色”“亮色”两项，当前模式对应aria-pressed=true且仅一项为true。控件高度至少40px、窄屏允许换行，320px下两个选项及全部导航都可到达；不把切换藏在设置页或悬浮层。选择当前模式无操作；选择另一模式只更新外观，不发API、改变URL/history、卸载路由页面、重置草稿/已选镜头/当前Clip/任务筛选，或重新订阅WS。不得给App/Outlet/页面增加theme作为key。

只用一个localStorage key `ai-drama-studio.theme` 保存精确字符串`dark|light`，不保存来源或业务数据；此处是§2.1禁止持久化返回来源之外的纯外观偏好。应用在React首次挂载前读取并设置根属性及theme-color，AppShell接续同一状态；不重复建立两套初始化逻辑。无记录时默认dark；显式选择后同origin刷新/新开页面读取最后一次保存值，不新增账户配置API或跨标签实时同步机制。

外部存储中的其他非空值不用于CSS/HTML拼接：本次使用dark并显示“主题设置无效，请重新选择”；用户选择合法值才覆盖旧值。读取遇到明确的DOMException时显示“无法读取主题设置，本次使用暗色”；写入遇到明确DOMException时当前页面仍应用所选模式并显示“主题已切换，但无法保存到此浏览器”。提示可见且role=status，不自动重试、吞异常或宣称保存成功；其他未知异常原样抛出。存储异常不改变业务请求或把已有输入清空。以上是公开的外观恢复规则，不是静默fallback。

### 3.4 勾选框与资产文字对齐

修复ShotsPage“绑定资产”的`.shot-asset-option`及通用表单规则的实际specificity冲突：普通文字输入的min-height/padding/layout不得作用到checkbox/radio/file等非文字控件。使用原生checkbox和关联label，checkbox可见框18×18px、不伸缩、无文本输入padding；label最小高度40px、勾选框与文字水平间隔8px，文字可换行。单行时文字行盒与勾选框垂直中心差不超过1px；多行时勾选框与第一行的行盒中心差不超过1px，后续行从文字起点继续，不落到勾选框下面。长中英文资产名、类型后缀、选中/未选中及禁用态在两主题和320px均无重叠或根溢出。

点击名称或checkbox均仅切换一次该资产，键盘Space切换一次；保留draft.asset_ids、保存PATCH、PRD §3.2/§3.3编辑修订与级联、后端错误与禁用条件。统一检查导演台参考资产候选和镜头勾选行是否被同一通用输入样式误伤；只修相同原生控件布局边界，不改候选上限/R8警示/可选规则。

### 3.5 导演台镜头可读宽度

保留生产directorModel的排序、duration_est权重和同一gridTemplateColumns，场景带/分镜轨/片段轨仍共享滚动容器。最短时长镜头的列宽至少192 CSS px，间隔保持8px。N>0时用当前已验证的正duration_est计算共同最小轨道内容宽度：`192 * sum(duration_est) / min(duration_est) + 8 * (N - 1)`；实际共同内容宽度为此值与容器可用宽度的较大者，各轨使用相同值。N=0时不计算min/除法，沿用空态，不产生Infinity/NaN宽度。

宽度只是一项前端布局计算，不修改duration_est、fr列输出、镜头顺序、分镜/片段关系或数据库。禁止给每个镜头单独min-width钳制、等宽化、压缩时长比例、增加缩放滑块/密度模式或分页/虚拟化。所有内容仍在一个横向滚动区域内；三轨对应列左右边界误差≤1 CSS px，Clip跨列宽度包含原8px间隙；扣除间隔后各列宽度/时长的比值在浏览器1px舍入误差内一致。

镜号、景别、时长、changed、不可选原因全部可读；较长原因换行增加高度，不通过全局缩小字体或隐藏文字塞入窄列。192px的最短列在320px视口及桌面200%保持可读尺度，页面根无水平滚动；键盘聚焦远端镜头/Clip时可在局部轨道滚动到目标，不被详情板遮住。主题切换不重建轨道选择/当前Clip，不重置滚动位置。

## 4. 功能保留与状态展示

### 4.1 全页保留清单

| 页面 | 必须保留的控件和可观察能力 |
|---|---|
| 项目首页 | 项目创建选风格、进入项目、改名/换风格、删除确认；无风格时链接到设置 |
| 项目详情 | 建集、编辑集序/标题、删除确认、集标题进入；唯一删除项是重复“进入集工作区”Link |
| 剧本 | 查看/编辑/保存/取消编辑、原字数与错误约束；生成资产、生成分镜 impact 数量/确认/token；两类旧剧本角标；任务入口 |
| 资产 | 项目级资产 CRUD、意见、生成、上传、current 图片、画廊/current 切换/非 current 删除、原完整 seed、DEBUG 字段按响应展示 |
| 分镜 | 原序展示、各文本字段/时长/绑定编辑；changed、零/多场景角标；没有结构增删排序 |
| 导演台 | 场景带与两轨、空洞与唯一分镜勾选轨；preview/候选精简/create；note/duration/save/delete；槽位固定号、启停、override；视频生成、take/current/delete/playback、两维状态和完整失败原因；原所有置灰/软警示规则 |
| 设置 | 风格 CRUD、四模板编辑/保存、诊断刷新、vLLM/Comfy status/message、两工作流 hash；保留诊断失败可见性与编辑内容 |
| 任务中心 | ID/type/target/progress/时间/error；新增本文限定的过滤、有限历史、详情、单项取消；保留 WS 重连 |

布局变化不改 mutation method/path/body、null/省略/空白语义、请求在途防重复、成功反馈时机、media URL、seed string、DEBUG 开关与后端裁决。所有现有危险操作确认继续存在。除本 spec 明确新增交互外不得改变“何时发请求、何时保存、何时允许生成”。

### 4.2 状态词义

- Shot `normal` 不显示 changed 角标；`changed` 统一显示“已变更（changed）”。
- Clip 生成态分别为“未生成（empty）/排队中（queued）/生成中（generating）/可用（ready）/失败（failed）”，保留五种可区分状态样式。
- Clip `stale` 独立显示“待更新（stale）”；`fresh` 不显示 stale。generating+stale、ready+stale 都必须同时可见。不把任务 done 等同为 Clip fresh。
- 保留“资产提取基于旧剧本”“分镜基于旧剧本”“原资产已删除”原文。旧剧本角标沿用当前 generated revision 与 script_revision 判定，不把 null 显示为已经生成过的旧结果。
- R8 黄色软警示继续黄色；changed/stale/零场景/轨道空洞均不新增禁用条件。所有生成和级联真相继续来自现有 API，不在通用 Badge 中计算业务规则。

## 5. 任务中心数据与交互合同

### 5.1 接口与有限历史

只调用 `GET /api/tasks?status=&type=&limit=`、`GET /api/tasks/{id}`、无 body `POST /api/tasks/{id}/cancel` 及 `/ws/tasks`。

过滤控件：状态=全部或五个既有值；类型=全部或四个既有值；数量=20/50/100，默认 50。全部选项省略该 query 参数，status/type 同时选中时传 AND 条件；页面值不放宽 API 1..100 范围。数量选择不表示分页。

每次过滤变化发一个当前条件的 GET；渲染该查询最新成功结果，按 id DESC。划分“进行中”（queued/running）和“历史”（done/failed/canceled），每组保持降序；空组不误报整个任务库为空。显示“最多显示匹配条件的最近 N 条，本次已加载 M 条”，M 是本次结果条数，不展示总数、不暗示可以访问 N 条之外的全部历史。当前条件结果为空时显示“当前条件下暂无任务”，仍保留过滤控件。

详情通过展开指定 task 获取正式 detail GET，显示 type/target/request_id、状态、完整 progress 与 created/started/finished/heartbeat/cancel_requested_at；null 时间显示“—”，有效时间按浏览器本地时区格式化并标明时区。完整 error_msg 可展开/换行/选择复制，不用省略号永久截断；不得返回或显示 payload。任务身份一直是 task.id，不把 target_id 当 task.id。

### 5.2 取消与状态转换

| 用户动作/服务端结果 | UI 期望 |
|---|---|
| queued 点击“取消任务” | 发送一次无 body POST；请求期间该 task 的取消入口 disabled；200 canceled 后显示已取消 |
| running 且 cancel_requested_at=null 点击 | POST 一次；200 running 且 cancel_requested_at 非 null 显示“已请求取消，等待任务停止”，仍显示 running 与真实进度 |
| running 已请求取消 | disabled 且保留等待文案；WS 未含该字段时由 detail GET 读回，不伪造时间 |
| done/failed/canceled | 没有可执行取消按钮；canceled 的 API 重复取消仍是既有 200，不改变接口 |
| 取消与完成竞争，POST 409 | 原样展示 detail.message，刷新该 task 与当前查询；以 done/failed 真实终态呈现，不提示取消成功 |
| POST 超时/网络/协议错误 | 错误可见，不自动重发 POST；一次权威读取用来澄清未知结果，未成功读回前提示“取消结果未确认”，不解锁同 task 的再次提交 |
| POST 404 | 错误可见；刷新当前过滤列表、清理已不存在的 task 详情；不去目标实体制造替代任务 |

操作状态属于 task id：筛选移走 A 或切到 B 时，A 的迟到响应只能更新 A 的请求记录/触发当前查询权威刷新，不能给 B 显示等待、错误或成功。离开 TasksPage 后的响应不得修改下一页面；返回后走正常 REST/WS 重建，不重放取消。

终态/首次取消意图变化必须读取该 task 的最新详情以补齐 cancel_requested_at、finished_at 与完整 error_msg；“已请求取消”不等于最终 canceled，绝不能只凭该 message 改终态。本 change 不改后端 running→安全点→canceled、取消/完成的胜方或 Comfy interrupt 行为。

### 5.3 REST/WS 观察一致性

复用 D-008，并限定到 TasksPage 所需职责；可以把该页面已有同步抽到 `features/tasks/`，不抽全站状态框架、不重写 Director/Asset 同步器。

1. 首次与重连：先建 socket/缓冲事件，再读取当前条件 REST；先应用快照、后按接收顺序应用事件。重连等待沿用 1/2/5/10 秒，成功同步才重置。
2. 过滤变化增加页面内请求代次；旧筛选/旧 socket/卸载后的成功或失败均不写当前 data/loading/error。已有旧列表若保留，必须明确标记“正在更新，以下为上次结果”，不能标成新条件 ready。
3. 事件引起当前行不再匹配、未知任务可能进入窗口、或终态/取消后需要恢复筛选窗口时，合并为一次当前查询权威刷新以补足最多 N 条。单 task detail 至多一个在途，多个相同 task event 不并发重复 GET；窗口列表也至多一个有效在途。
4. 保持连接时，新事件令在途刷新过期：过期响应不应用；为待完成的操作/terminal/filter 刷新在最新 revision 补一个查询，直到最新成功或最新失败可见。不得只丢旧响应而永久 loading；不靠轮询补足。
5. 允许 WS 在已有行推进 status/progress，但不能补造 target/time/payload；未知 task 必须经合法 ID 的 detail GET 后展示完整卡片。终态详情晚于更新事件到达时也须补一次最新读取，不能让首次 detail 永久吞掉 terminal。
6. loading、连接中、ready、更新中、REST error、重连中、取消结果未确认有独立文字；REST 失败不得呈现“暂无任务”。ready 阶段的详情/WS 解析错误仍须可见。
7. 初次同步失败或非法 WS 消息：保留具体错误，关闭对应 socket并沿用观察通道重连；只有最新 REST/WS 同步成功才清除同步错误。socket 重连不重发任何 mutation。
8. 404/409 的取消错误必须保留到用户关闭对应反馈或对同一 task 发起新的显式操作，不能被后台 GET 成功抹去；同步错误和操作错误分开显示。详情已消失则可在列表级提示“任务 #ID：原始 message”。
9. 卸载关闭 socket、清计时器、失效 pending 请求；idle ready 不轮询，不额外引入持久缓存、事件表或服务器字段。

## 6. 错误、空态与公开边界

错误体为 `{"detail":{"code":"非空","message":"非空"}}`。既有 API 全部遵循 409=前置/资源/任务冲突，422=输入/业务校验；不相互替代，不以 200 包装错误。取消成功 200，生成 accepted 202/task_id，两者不可混用。

| 情形 | 展示/请求结果 |
|---|---|
| API 404 | 显示 detail.message；目标不存在保持错误页面和可用导航 |
| cancel done/failed 409 | detail.message 原文 + §5 权威刷新，无 POST 重放 |
| status/type/limit 非法、cancel 非空 body 422 | 后端 validation_error 原文；客户端不能把错误当成空列表；正常控件不会主动构造这些非法请求 |
| API 500/网络失败 | 可见错误，保留尚未提交草稿；不自动重发 mutation |
| 合法 2xx 的 Task/WS 格式非法 | 使用已有严格 parser，产生可见协议错误；不强转 ID、不接受超出 safe integer 的 ID、不把 extra payload 当 DEBUG |
| 请求成功后的最新刷新失败 | 保留错误与待同步说明，无成功通知；允许显式“刷新任务”仅重读，不重发原动作 |
| 没有项目/集/资产/分镜/Clip/take/任务 | 使用现有能力的下一步文案，保留相应创建或导航入口；不能显示成功通知或虚构示例记录 |
| 媒体失败 | 明确“图片加载失败/视频加载失败”；保留真实媒体身份与其他动作，不换默认成功媒体 |

主错误正文必须逐字显示 ApiError.message（即服务端 detail.message）；code 可另列。Task error_msg 保留全部换行并可复制。其余本地网络/协议错误用实际错误文本，不用空态、正常默认数据或吞错替代。

## 7. 验收装置与证据边界

### 7.0 回归命令装置

前置 task 交付 `.work/c011/run_checks.ps1`，只包装现有 npm/Alembic/pytest/git 命令：每轮完整 pytest 使用新建、仅迁移的隔离 PostgreSQL 和独立 DATA_DIR；记录 stdout/stderr、PID、原生退出码与数据库名，不记录凭据。它不替换测试，不改生产数据，不建立锁/hash/第二依赖清单；失败即停止，旧日志不覆盖。该装置能证明实际执行和进程退出，不能仅凭输出中出现 passed 认定成功。

2026-09-07 T03 装置裁决：原生命令的 stderr 是输出通道，不等于命令失败。当前 `backend/alembic.ini` 明确把 INFO 日志写到 `sys.stderr`；验收启动器必须分别完整采集 stdout/stderr，等待子进程结束并记录原生退出码，再核对该命令的预期结果。非零退出码、无法启动/等待进程、日志保存失败或预期结果不符均须停止；有 stderr 但退出码为 0 不得仅因通道名判失败，也不得过滤 stderr 或修改 Alembic 日志配置来使验收变绿。Windows PowerShell 的重定向行为存在版本差异，不能依赖 `2>&1` 与 `$ErrorActionPreference='Stop'` 的组合来判定原生命令成功；参见 [Microsoft PowerShell preference 文档](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_preference_variables?view=powershell-7.5)。本次修复与重新验收的窄授权、证据保留及停止门槛见 tasks.md 的 T03 裁决；不放宽生产 Task 不重试规则。

### 7.1 DOM 行为装置

已有 Vitest 继续执行旧 Node 用例。新 DOM 文件按文件选择 jsdom，使用 React Testing Library 挂载真实 AppRoutes/AppShell/TasksPage/相关页面，替代 fetch/WebSocket 外部传输并用 deferred Promise 精确控制顺序。不替换被测 parser、cancel helper 或页面 action，不在测试中手填预期请求/通知账本。

同生产：React 组件、路由、parser、API helper、页面协调器与事件消费者。不同：无真实网络/DB/GPU，也无浏览器排版。能证明请求参数/次数、DOM 文案与选择、异步隔离；不能证明 PostgreSQL 取消已提交、跨进程 WS 发布或视觉布局。含取消、超时、重复请求、快照/竞态的用例归“任务系统 mock”。

### 7.2 一次性受控任务运行时

T04 的 OpenAPI 预检只验证 HTTP method/path。`/ws/tasks` 是 WebSocket 路由，不要求以 `GET /ws/tasks` 出现在 OpenAPI paths，也不得伪造 HTTP endpoint 或改生产 schema 使自检通过。WS 必须由独立客户端实际连接本轮服务、完成握手并观察后续生产事件；缺失路由、握手失败、事件缺失/不符仍须失败。HTTP 预检成功和 WS 验收成功分别记录，前者不能代替后者。自检只有主流程及规定资源清理全部正常结束才记录 RESULT PASS；任意异常或非零退出码不得伴随 PASS，未知异常原样传播并保留 traceback，不以捕获某一种异常是否发生推断成功。

前置 task 交付 `.work/c011/task_runtime.py`，独立进程调用现有 create_app 注入受控 task_handlers/外部 client factory。使用独立 PostgreSQL/DATA_DIR；主进程仍运行生产 lifespan、advisory lock、TaskQueue、worker、事务、EventBus、Task REST/WS。本机控制由驱动 stdin 指令/进程管道放行 barrier，不增生产 HTTP endpoint，不用 sleep 猜中竞态窗口。

任务数据经生产队列 enqueue/record_failed 等原语及提交后 publish 产生；测试 handler 只负责受控等待、报告进度、检查安全点、返回或抛出指定失败。不得向表直接 UPDATE status、向 browser 合成伪生产 WS，或定义第五种 task type。四类 type 的展示可由该运行时造合同数据，但必须有有效 target；gen_clip_video 需真实存在 Clip，以满足生产聚合。

差异是 handler/外部服务被显式替代，**不验证真实业务生成、媒体产物、GPU interrupt/free 或上游协议**；生产取消 API/队列/存储/事件仍为同一条。跨进程验收必须让浏览器/独立 HTTP+WS 客户端连接此后端，通过第三方独立 DB 只读连接核对状态；仅同进程调用 EventBus 不是跨进程证据。

稳定的跨进程 pytest 在新增测试文件内通过同一 create_app/TaskQueue seam 建立其独立进程 fixture，不导入 `.work`、不要求一次性驱动存在。它和浏览器运行时都验证生产原语；共用的是生产接口，不是未提交脚本或手写状态机。测试 fixture 仅提供受控外部边界与进程屏障。

驱动准备任务必须有足够多条历史以验证 N 上限和过滤先于 limit，并有 queued、可控 running、done、failed、canceled。每个 barrier 有实际“到达/放行”证据；记录原始 method/path/body、响应、WS、DB查询、PID、退出码。驱动只操作本轮进程与隔离资源，失败日志不覆盖，运行产物不提交。

### 7.3 普通页面 fixture 与浏览器

T03 的离线 ORM 准备须由一个顶层异步入口拥有事件循环；Shot、ClipVideo 与数据库身份读取在该循环内按原业务顺序执行，不能用多个 `asyncio.run()` 复用模块级 asyncpg 连接池。该入口在 `finally` 中等待 session/事务退出及既有 `dispose_engine()` 完成，再允许循环关闭；异常原样传播，清理异常也须保留。生产连接池配置不变。参照根目录 NOTES.md 的 C007 T6 已知坑；这不是新增产品行为。准备过程跨 API 已提交的数据和离线事务，不宣称整体原子：失败后保存部分数据与文件证据，不清库、不重放已执行的创建请求。每次新尝试使用独立证据目录，manifest、OpenAPI 快照及 fixture 图片均归属该批次，prepare/verify 必须选择同一批次；不得覆盖或搬走旧批次产物以绕过存在性检查。

本前置装置自身的资源生命周期归“跨进程/资源生命周期”：实际 prepare 子进程记录两段 ORM 操作所在循环、事务退出、引擎释放完成及进程退出的顺序；独立 verify 进程通过正式 API/media 回读。它能证明人工 fixture 的准备、连接释放和读取通路，不能证明生产生成 Task 的事务、失败清理或 GPU 生命周期。自检只证明其实际覆盖的启动前条件，不代替 prepare/verify；失败路径的 finally 另作逐段代码审计，不以成功运行宣称已动态验证全部异常分支。

启动器运行依赖必须在建库/迁移/启动进程之前检查。2026-09-07 T03补充裁决已验证 Windows PowerShell 5.1 需要显式 `Add-Type -AssemblyName System.Net.Http -ErrorAction Stop` 后再构造就绪探测的HttpClientHandler/HttpClient；这是本进程标准程序集初始化，不新增生产依赖或fallback。自检必须使用正式执行的 `powershell.exe -NoProfile`，并记录版本、类型可构造与释放、原生退出码及无业务副作用。程序集加载方式参见 [Microsoft Add-Type 文档](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/add-type?view=powershell-7.5)。就绪等待的连接失败/超时须保留具体观测，超出期限仍失败；详细续验授权见tasks.md的T03补充裁决。

另一个前置 task 交付 `.work/c011/ui_fixture.py`：在隔离普通后端的正式 OpenAPI 一次预检后，通过 API 创建风格/项目/集/资产、上传程序生成的可解码本地图片、创建 Clip/槽位；无创建 API 的 Shot 与用于静态 take/状态展示的 fixture 只能通过显式离线 ORM/文件准备步骤初始化到本轮隔离 DATA_DIR，并标记“人工 fixture”，不能写用户库或伪称来自生成。不得为 fixture 增生产 API；不运行四模板部署或上游生成。产物状态覆盖清单由回读实际 API 确认。该前置 task 同时交付 `.work/c011/vite.config.ts` 验收配置：只选择本轮隔离监听端口和同源代理目标，仍加载原 frontend 源码与原 React 插件；不修改生产 vite.config.ts。代理转发不替换响应，网络通路差异仅为现场明确记录的端口。

普通模式运行 `app.main:app` 的生产配置、真实 API/PostgreSQL/media；WS 如无新任务不能声称测到取消事件。受控任务模式单独记录，两个模式不可混报。真实浏览器人工操作完成视觉/键盘/响应式验收，记录 viewport、截图、操作、网络响应及 DOM；不依赖新建自有浏览器自动化驱动。若改用自建驱动，必须先增独立前置 task 和通路说明再用，不能夹在验收 task 内。

### 7.4 T24 补验的运行配置与浏览器控制（2026-09-08 裁决）

T24A 是受控生成按钮检查的前置任务，只准备独立受控库的运行配置，不增加生产能力或自建浏览器驱动。生产 REST 入队校验发生在注入 handler 之前；T04 self-check 经 TaskQueue 原语入队的证据不能证明四个页面按钮通过了 REST 校验。新受控库迁移和普通媒体 fixture 完成后，先确认 DEBUG_PROMPTS=true 在进程启动前生效并经现有 verify 回读，再通过正式设置 API 安装以下**人工验收模板**。它们只提供 PRD §7 的合法变量，正文固定为表内单行，不是既有正式模板，不用于任何真实外部生成。

| key | 人工验收正文（精确单行） |
|---|---|
| script2assets | `[C011人工验收，非正式模板] {{script}} {{style}} {{existing_assets}}` |
| script2shots | `[C011人工验收，非正式模板] {{script}} {{style}} {{assets}}` |
| zimage | `[C011人工验收，非正式模板] {{asset}} {{style}} {{user_note}}` |
| minimaxh3 | `[C011人工验收，非正式模板] {{shots}} {{references}} {{style}} {{requested_duration}} {{user_note}}` |

写前保存本轮 OpenAPI，核对 GET `/api/prompt-templates` 与 PATCH `/api/prompt-templates/{key}`；每项PATCH请求体仅为content，预期200，再GET逐字回读四个key/正文。缺项、不一致或非200阻塞，不从旧库复制、不直写表、不修改 migration/生产常量/正式模板，不执行 C012 bootstrap。该通路与生产设置API、存储和入队校验相同；handler、外部health clients仍是T04显式替代，证明页面→REST→队列→受控handler，不证明模板生成质量、生产业务产物或M6。

T24补验四类生成动作须各有合法且互不干扰的target，按原UI完成输入/确认；记录一次真实生成请求的method/path/body/202与task_id、同task_id的BARRIER_REACHED、REST/独立DB状态。确认受控handler注册和外部替代后才可点击；不得在普通后端触发真实GPU。每类完成观察后经既有受控管道结束/清理其任务，保持原隔离纪律，不把mock done当作资产/分镜/图片/视频生成成功。409日志只证明前置条件失败与错误展示，不计入成功入队。

**2026-09-09 T24验收范围裁决：** 需求方就全页原生200%、动态reduced-motion持续未验证询问是否舍弃。经核对PRD §9/§11 M5及ROADMAP C011，两项均为本change规划追加的检查，非PRD指定的硬门槛。取消两项作为T24完成及进入T25的阻断条件，不删除已有样式，不改变四视口、键盘、对比度、业务/受控生成验收或测试要求。T24须记录“全页原生200%、动态reduced-motion未验证，本次不阻塞”；这表示验收范围收窄，不是测试通过，也不是工具问题已解决。此前要求因这两项持续阻塞T24的裁决由本条替代；不自动转为C012任务，不新增装置、依赖或测试。

保留§3.1的reduced-motion实现要求，T24通过源码审计确认`@media (prefers-reduced-motion: reduce)`保留、覆盖现有悬浮位移选择器并设置`transform: none`、禁用循环装饰动画且缩短动画/过渡，记录规则位置及覆盖清单。该检查证明CSS规则与覆盖关系，不证明浏览器媒体偏好动态触发或实际动画结果。全页放大后的布局/可达性与动态减少动画响应仍是已知未验证范围，完成报告必须明列。T24F既有原生200%人工确认只覆盖其原有范围，不扩展到T24全页。viewport、devicePixelRatio=2、CSS zoom和静态样式均不得冒称这两项的动态证据。

现有computer-use技能的node_repl + @oai/sky在2026-09-08可加载且能列出Chrome/Edge窗口，这只证明工具入口可用，不是上述项目验收已经通过。后续T24B记录在读取Chrome窗口状态时因安全层无法确认当前URL而停止（`.work/c011/T24B-browser-control-failure-20260908_1218.log`），未执行临时主题切换；不能把窗口可枚举当作可安全控制。安全层停止后不得继续输入、换通路绕过或伪造当前URL；后续浏览器操作须先由工具安全层确认专用验收页面的实际URL与授权目标一致。未恢复该条件时，对应浏览器验收保持未完成。内置浏览器功能不构成自建验收驱动；若确需新增驱动，必须先另列前置任务。

**T24B/C验收归属调整（2026-09-08）：** T24B只验收CSS交付：两套token逐项符合§3.1/§3.3、消费规则覆盖指定组件、无对应暗色硬编码/媒体反色、保留响应式与焦点规则，以及build/G通过。不再要求在正式主题控件交付前通过DevTools临时改根属性；静态证据不能证明渲染对比度、320px布局或AC-26通过。以上双主题真实渲染检查全部移交T24C，须通过正式“亮色/暗色”按钮经生产主题逻辑→根属性→同一styles.css通路完成，覆盖§4各页组件、实际合成背景对比度及320px根溢出与键盘操作；不注入替代主题状态，不用jsdom代替布局。T24C显式承担该检查发现的§3.1/§3.3主题CSS修正，全部通过后才可进入T24D；最终T24仍执行双主题完整矩阵；原生200%和动态reduced-motion按2026-09-09本节裁决记录为未验证且不阻塞。此次只移动阶段验收归属，不删除或降低AC-05/07/26要求，不把原失败记录改写成通过，也不解除浏览器安全限制。

## 8. 验收标准

每条均按“触发 → 观测点 → 期望”判定；风险标签表示首要定向审查类别，不排除复用其他层回归。

| ID | 风险 | 触发条件 | 观测点与期望 |
|---|---|---|---|
| AC-01 | [常规] | 审核基线至交付 diff | 后端生产/模型/迁移/workflow/template 无 diff；既有测试除需求方2026-09-07授权的 C009 `_LifecycleHTTPHandler.do_POST` 提交屏障窄修正外无 M/D，该例外精确范围按 AGENTS.md；只有本 spec 授权 UI/新增测试/开发依赖/文档及该例外，零后续业务能力 |
| AC-02 | [常规] | 从首页/项目页/四个集 tab 分别经 header 和页内链接进入设置或任务；辅助页互跳并刷新后返回 | 一次返回精确回原 pathname/search/hash；不同标签页来源互不覆盖；原生 back/forward 可用；不新增保存请求 |
| AC-03 | [外部输入] | 无 state 直达/新标签、注入非法非空来源、或删除来源实体后返回 | 无state的图标名称/title为“返回项目首页”；非法来源显示错误且不导航外站/辅助循环；删除目标显示真实404和首页图标入口，无旧实体假页面 |
| AC-04 | [常规] | 点击/Enter 集标题，另点击编辑或删除集 | 同一集仅标题导航至 script；DOM 无“进入集工作区”；编辑/删除保留且不触发集导航 |
| AC-05 | [常规] | 在暗色和亮色分别查看§4全部页面计算样式与截图 | 背景/CTA/材质/圆角采用§3两套对应值，品牌/中文文案保留；无远程字体/装饰请求；无假项目/媒体/社区或登录入口 |
| AC-06 | [常规] | 两主题分别在四个指定视口逐页操作 | 页面根无水平溢出；导航、主题/后退控件、表单、按钮可到达；Director三轨同容器同列比例、镜头宽度达§3.5、局部可滚动，详情窄屏在下方，所有原操作保留；全页原生200%的未验证范围按§7.4明列 |
| AC-07 | [常规] | 两主题分别键盘Tab/Enter/Space、测实际背景文本对比度，并按§7.4审计reduced-motion源码规则 | 焦点可见不被盖；控件名称/label完整；一般目标至少24×24，新增主题/后退控件按40px合同；文本/焦点达§3比值；reduce规则存在且覆盖现有悬浮位移选择器，循环装饰动画关闭规则保留；警示不只靠颜色；动态媒体响应的未验证范围明列 |
| AC-08 | [常规] | 按 §4.1 逐项操作并对照修改前请求合同 | 每一功能仍有可到达入口，method/path/body/确认/DEBUG/media/seed 合同不变；唯一移除重复集 Link；清单不缺项 |
| AC-09 | [常规] | 输入 normal/changed、五种生成态分别配 fresh/stale、null/旧/当前剧本生成修订 | DOM 逐项等于 §4.2 文案和角标；stale 与生成态同时呈现，null 无旧结果角标；不增加禁用，R8 软警示保留黄色 |
| AC-10 | [外部输入] | 受控库有超过 100 条混合任务；选状态/类型/20、50、100及全部 | 实际 GET 参数准确且先服务端 AND 再 limit；列表数=min(N,匹配数)、组内 id DESC；组别和窗口说明准确；空结果不等同全库无任务 |
| AC-11 | [外部输入] | 展开有 null 时间、已请求取消时间、长多行错误的任务详情 | 正式 detail GET 返回字段逐项展示；null 为“—”、时区明确、错误可完整选择复制；没有 payload/内部快照 |
| AC-12 | [并发] | queued、running 首次与已请求取消状态分别操作；在途双击 | 每 task POST 至多一次、无 body；queued 最终 canceled，running 200 仍 running+等待；已请求/终态不可再触发 UI cancel；不影响其他 task |
| AC-13 | [并发] | cancel 先提交意图/完成先提交两种顺序，并让旧 200 running 晚于新 terminal WS 到达 | UI 终态与最新权威 GET 相同；409 原 message 可见，零取消伪成功；旧 running 响应不覆盖新终态；GET完成前不发布成功通知 |
| AC-14 | [并发] | A cancel 在途切筛选/展开 B/离开页面；POST 返回 404、409、网络超时或协议错误 | 错误按 A 归属；404/409 权威刷新且消失后清 A 详情；网络未知结果显示待确认并 GET，一次 POST 无重放；B/下一页面不被污染 |
| AC-15 | [并发] | socket 初连/重连期间事件先于 REST 回来，断线期间任务终结 | socket-first 缓冲→REST→事件；不回退终态；断线提示保留旧数据；重连沿 1/2/5/10 秒、最新成功后清提示；零 mutation 重放 |
| AC-16 | [并发] | 快速把过滤 A 改 B、旧 A 成功/失败迟到；当前事件使列表失效或任务移出过滤窗口 | 旧 A 不写 B data/loading/error；最多 N 且均匹配当前条件；一次最新查询补足移走任务后的窗口；旧响应失效后刷新必结束成功或可见失败 |
| AC-17 | [并发] | 未知 task 多事件、detail 在途又到 terminal/取消意图，最新详情成功或失败 | 每 task 最多一个在途 GET，必要时完成后补一次；时间/error/取消标记由最新详情补齐；ready 下失败可见，terminal 不被去重吞掉 |
| AC-18 | [外部输入] | Task REST/WS/cancel 返回未知枚举、越界进度、非 safe ID、额外 payload、畸形 JSON；或 API 422/500 | 实际生产 parser/action 报可见原错误；非法 ID 在详情 GET 前拒绝；不强转/空列表替代/伪成功；正常 API 错误 message 逐字显示 |
| AC-19 | [外部输入] | 每页加载中/真实空数据/读取失败/动作失败/媒体失败 | 对应加载、空态、错误彼此不同；失败不伪装“暂无”；导航仍可用、草稿不因错误清空；图片/视频失败不换占位成功媒体 |
| AC-20 | [跨进程] | 启动 §7.2 装置，让独立客户端 cancel，并用独立 DB 连接读结果 | task 状态与 API/生产 WS 一致；进程事件屏障证据齐全；handler 为受控替代的事实明确，零测试 endpoint/第五 type/直接状态 UPDATE |
| AC-21 | [跨进程] | queued 取消、running 意图到安全点、先 done 后 cancel，分别在独立客户端与后端进程执行 | DB/API/WS 记录匹配同一 task：queued canceled；running 请求后未放行仍 running，放行后 canceled；done 胜方 409 且 DB 保持 done；无重复 claim/POST，由既有队列原语裁决 |
| AC-22 | [常规] | 使用普通生产后端+§7.3 fixture，真实浏览器完成导航和 §3/§4 全页检查 | screenshot/DOM/HTTP 可对应各 AC；表单/媒体/选项卡可实际操作；fixture 与真实生成区分；人工与 DOM mock 结果分开，不声称 M6 |
| AC-23 | [常规] | 收尾审计并核对规定回归 | 按 §10.6 完成全部必需计划检查；覆盖最终受测实现的前端全量 test/build、全新仅迁移库完整 pytest 真实 exit 0，可精确引用同输入阶段结果；追溯回填实际用例/人工证据，NOTES/DECISIONS候选/commit与checkbox一致；本 task 必需门槛未做或失败不勾该项，最终缺完整回归不勾收尾 |
| AC-24 | [跨进程] | 在新普通隔离库/DATA_DIR/证据批次执行 T03 prepare，再在独立进程执行 verify | 两段 ORM 操作记录的事件循环相同；session/事务退出后引擎释放完成，prepare 进程再以 0 退出；verify 对本批次正式 API/media 的 §7.3 数据及解码检查全部通过且 exit=0；旧批次产物无覆盖，日志不宣称真实生成成功 |
| AC-25 | [外部输入] | 在T04受控模式的新隔离库执行T24A运行配置准备 | 写前OpenAPI包含正式模板GET/PATCH；四次PATCH均200且后续GET的key/正文逐字等于§7.4；DEBUG媒体字段经verify可见且exit=0；无生产配置/迁移/正式模板改动，证据标明人工模板与受控handler |
| AC-26 | [常规] | 在任一工作/辅助页操作“亮色”再“暗色”，逐页展开表单/DEBUG/预检/状态/空态，并在320px操作 | 一次点击切换根data-theme、color-scheme和theme-color，且仅对应按钮aria-pressed=true；各组件token符合§3.3/§3.1，亮色白底紫色主色；原媒体无反色；控件/导航无隐藏、无根溢出 |
| AC-27 | [外部输入] | 无记录首次启动、已有dark/light后刷新/新开同origin页、非法存储值、读取/写入DOMException | 无记录dark，合法值在React首次挂载前应用；非法值dark并显示规定错误，读取错误显示规定提示；写入失败当前选择生效但显示未保存；无静默成功/自动重试，无用户业务数据写入localStorage |
| AC-28 | [并发] | 在各自页面分别保留未保存剧本/意见、镜头/Clip选择或任务筛选并切换主题；另在可生成的页面令一条生成mutation在途，切换后再完成原响应 | 各页面原草稿/选择/轨道scrollLeft/筛选保持；URL/history不变；在途用例原mutation精确一次且body不变，零主题API请求/额外WS连接；原响应仍按原页面/任务身份处理，无卸载造成的丢失或重放 |
| AC-29 | [常规] | 对项目页、集页、辅助页正常/无来源/非法来源/资源错误分支逐一操作返回入口 | 可见入口均为同一40×40左箭头控件，SVG20×20且aria-hidden；aria-label/title为原目的地名称；一次激活到原目标，辅助返回仍replace并保留search/hash；非法来源提示保留，无navigate(-1)或新增入口 |
| AC-30 | [常规] | 两主题四视口下编辑绑定资产，输入单行/多行长名称，点击label与checkbox并按Space；检查导演台两类勾选行 | checkbox18×18、label至少40px、横向gap8px；框与第一行行盒中心差≤1px，文字续行不落在框下且无重叠；每次动作只切换目标一次，保存asset_ids及禁用/上限规则不变 |
| AC-31 | [常规] | Director显示空、单镜头及包含不等duration_est的多镜头列表，切换主题/视口并横向滚动及键盘聚焦 | 空态无NaN/Infinity；非空最短列≥192px，三轨同一§3.5宽度/8pxgap及比例，对应边界误差≤1px；镜号/景别/时长/changed/原因可读，Clip跨度/空洞/选择规则不变；远端控件可滚到，根不横向溢出 |

## 9. 追溯覆盖检查（先于 tasks）

已逐条检查现有追溯表：通用取消后端行、C010 Director 行不能冒充 TasksPage 或全站新 DOM 行为。新增下列准确行名；旧行/旧证据保持原文，不把计划用例写成已执行。下表覆盖全部 AC，无“因无追溯行而跳过”。

| AC | openspec/TRACEABILITY.md 准确行名 | 新增/沿用与方式 |
|---|---|---|
| AC-01、AC-23 | C011 范围回归与文档提交一致性 | 新增；git/命令/文档核验 |
| AC-02、AC-03、AC-04 | C011 导航来源返回与剧集唯一入口 | 新增；纯路由决策自动测试+真实浏览器 |
| AC-05、AC-06、AC-07 | C011 全站视觉与响应式可访问性 | 新增；人工计算样式/截图/键盘检查及reduced-motion源码审计；全页原生200%与动态媒体响应按§7.4明列未验证，不阻塞T24 |
| AC-08、AC-09 | C011 既有功能入口与状态呈现不变 | 新增；状态纯函数+全页人工清单；复用 C010 已有回归不修改 |
| AC-10 | C011 任务列表过滤与有限历史 | 新增；API 集成+纯查询/分组测试 |
| AC-11、AC-18 | C011 任务公开边界与可见协议错误 | 新增；生产 parser/TasksPage 的任务系统 mock |
| AC-12、AC-13 | C011 任务取消交互与终态竞争 | 新增；任务系统 mock |
| AC-14 | C011 任务取消错误与资源消失重建 | 新增；任务系统 mock |
| AC-15、AC-16、AC-17 | C011 任务中心 REST/WS 同步与过滤竞态 | 新增；任务系统 mock |
| AC-19 | C011 全局异常空态与媒体错误呈现 | 新增；真实浏览器人工检查 |
| AC-20 | C011 验收装置与生产通路归属 | 新增；跨进程生产队列/REST/WS/DB观察 |
| AC-24 | C011 验收装置与生产通路归属 | 沿用；T03 人工 fixture 子进程、连接池释放与独立 API/media 回读，区别于 AC-20 生产队列 |
| AC-25 | C011 验收装置与生产通路归属 | 沿用；T24A 正式设置API配置与人工模板逐字回读，不能替代四类页面按钮或M6 |
| AC-26、AC-27、AC-28 | C011 明暗主题与偏好存储 | 新增；纯函数存储值解析、挂载页面的任务系统mock与双主题真实浏览器矩阵 |
| AC-29 | C011 统一后退图标与目标保持 | 新增；沿用路由决策测试，真实浏览器核对可经正式入口到达的返回分支与可访问名称；非空非法Router state分支按本节2026-09-08 T24D裁决采用组合证据，不宣称动态注入已通过 |
| AC-30 | C011 资产勾选行对齐 | 新增；真实浏览器计算行盒/checkbox位置并验证label/键盘/保存，不用jsdom推断布局 |
| AC-31 | C011 导演台轨道可读宽度与比例 | 新增；最小轨道宽度纯函数与真实三轨边界/滚动/选择验收，既有projection测试保留 |
| AC-21 | C011 跨进程任务取消与观察一致性 | 新增；跨进程/资源生命周期 |
| AC-22 | C011 全局浏览器功能与视觉验收 | 新增；真实浏览器人工检查 |

不新增自动测试的理由与替代方式：

- AC-05/06/07 的玻璃合成、排版/焦点遮挡、人工输入体验无法由 jsdom 或截图字节固定相等证明；人工在指定真实视口查看计算样式、对比度、键盘和截图逐项留证。不是免检视觉项。
- AC-08 的全功能入口外观变化以 §4.1 全清单逐项记录、既有回归和正式请求对照验收；状态枚举映射 AC-09 仍新增纯函数测试。
- AC-19 的全页状态/媒体呈现用普通浏览器+受控响应的人工证据；任务页协议与异步错误另由 AC-14..18 自动覆盖，不以人工替代竞态验证。
- AC-01/23 是 diff、命令及交付事实，不新增“测试其他测试”用例；用 git、原始 stdout/stderr/退出码和逐项清单核验。
- AC-22 的视觉与人机操作不做模型像素断言；AC-20/21 的真实队列/DB一致性仍必须自动跨进程验证，不能改成人工点击就宣称通过。
- AC-26的颜色/布局、AC-29的图标尺寸/焦点和AC-30的真实文字行盒不适合jsdom布局断言，采用双主题真实浏览器计算样式/几何及键盘/label操作；返回路由决策仍运行既有测试，低影响图标与CSS更改不新增镜像测试。AC-27存储分支、AC-28在途交互必须自动验证，不以人工替代。AC-31的宽度计算新增纯函数测试，实际三轨对齐和局部滚动由浏览器补足。

**2026-09-08 T24D非空非法Router state验收裁决：** AC-03的非法来源拒绝与AC-29的该分支图标要求均保留；T24D及最终T24对这项外观替换采用三部分组合证据：①运行既有returnLocation.test.ts，非空非法state判定用例通过，并核对resolveReturnLocation及其调用的行为与T24D实施前一致；②审计AuxiliaryPageReturn非法分支仍渲染原“返回来源无效”status，以及label为“返回项目首页”、to为“/”、replace为true的BackNavigation；审计BackNavigation将这些props原样传给正式Link，非法分支无专属图标、CSS覆盖或额外导航逻辑；③在实际可达的页面验证同一个BackNavigation Link的双主题40×40/20×20、名称/title、焦点、Enter导航和Space不导航，并保留辅助页真实replace返回的证据。若有非法分支专属布局样式，或来源判定/导航语义发生变化，本组合证据不足，须停止重新确定对应验证范围。

上述方法证明非法输入判定、生产分支接线和共享渲染/交互分别成立；不证明IAB已动态注入非法state，不把query returnTo或无state页面冒充非法分支。`.work/c011/T24D-browser-acceptance-20260908_142513.log`中history不可用的原记录保留。该单一分支不再要求新增state注入驱动、生产调试入口或镜像测试；既有T05的AC-03证据保留，最终T24其他浏览器要求不变。此裁决仅适用于本次共享图标替换，不授权实现者自行豁免其他外部输入或并发验收。

## 10. 2026-09-09 审查退回与修复验收

需求方已授权修复 Astra 对 `1ef70e5d5fad245d6e38e1472eaa16ffb523aa59..b4750e4ad7a8785e8ff3e965848526436aae94c3` 的审查问题 B01–B10。原始报告为 `.work/c011/review-20260909.md`，最终前端探针为 `.work/c011/probe-task-observation-20260909-105843.stdout.log`。本节只明确既有 AC 的修复验证切片，不增加产品行为、AC 编号、后端合同或后续 change 范围。原报告和失败日志保留；下面均为待完成工作，不能当作新验证结果。

### 10.1 既有行为的定向回归切片

| 问题 | 既有 AC | 必须观察的触发与期望 |
|---|---|---|
| B01 | AC-12/14/16 | 取消 POST 未结束时改变状态/类型/limit，同一 task 仍在新窗口；取消提交总数=1，等待及错误仍归发起 task，其他 task 可独立操作；离开页面后不污染新页面 |
| B02 | AC-12/13 | 取消前的详情 GET 延迟返回 queued；该响应不得解除取消确认保护；取消后最新详情应用前 POST 总数=1，之后显示权威 canceled 或 running+cancel_requested_at |
| B03 | AC-13/17 | running 事件先到、随后开始的详情 GET 返回 done；保留 done/progress=1/finished_at；反向时序仍满足旧 REST 不覆盖新 WS，不能用一种固定覆盖顺序替代先后判断 |
| B04 | AC-11/15 | 展开详情后断线、任务在断线期间终结；同一已挂载页面重连成功后列表与展开详情的 status/finished_at/error_msg 均等于最新 GET，不能用整页 reload 替代 |
| B05 | AC-12/17 | 已知 running task 收到生产“已请求取消”事件；一次最新详情补齐取消时间，未终结前仍 running，UI 等待且不可再取消；若旧详情在途，最多一个并发 GET，结束后补一次所需新读取 |
| B06 | AC-03/29 | 返回已删项目，正式 project GET 为结构化404；原 message 与名称/title“返回项目首页”的共享左箭头同时可见；一次激活到“/”，不得生成旧实体或修改辅助返回 replace/search/hash |
| B07 | AC-05 | 两主题四视口读取实际标题计算样式：首页 H1 为48–80px，工作页标题为28–40px，根不新增水平溢出；仍按§3.1执行 |
| B08 | AC-08/19/22/28 | 补齐既定每主题四按钮真实入队与逐页异常证据；补各自页面意见草稿、镜头/Clip选择和scrollLeft的独立主题自动验证；未保存值、选择、URL与请求账本保持原合同 |
| B09/B10 | AC-23 | 全部新增测试逐个回填实际身份；spec/tasks/追溯进入提交且可从HEAD读取；未完成修复或缺证据的原任务不勾选 |

风险类别仍取§8对应 AC，不以本表取代风险标记。B01–B06每个问题必须新增至少一条“任务系统 mock”独立回归，实际调用生产页面/控制器和HTTP/WS seam，不能只运行审查脚本。既有测试及审查探针保留，不改名/弱化/删除；新增测试先使用§9现有追溯行。B08补充测试也使用“任务系统 mock”。B07仍以人工计算样式与浏览器交互验收，不新增CSS镜像测试。

### 10.2 验收装置补充与证据边界

T37单独交付T04受控后端的被动请求观测：只在 `.work/c011/task_runtime.py` 的既有受控服务入口包装生产ASGI应用，记录四类生成与impact的method、path、实际body字节、响应status和task_id关联。请求正文必须原样交给原生产应用一次；不替换响应、不伪造confirm_token、不增加生产路由、不直接写Task、不新增包或第二事件通道。没有body、空JSON及含confirm_token的JSON必须在证据中可区分；不记录环境DSN/凭据，不对业务body做会丢失合同信息的过滤。

此包装增加的是受控入口旁的被动日志；业务请求仍走原生产路由/校验/事务/TaskQueue/EventBus/WS/数据库，handler/client仍按§7.2明确替换。它证明实际入队请求及生产观察通路，不证明真实GPU计算/生成文件，也不能把按源码推测的body写成运行观测。装置需先以真实独立HTTP请求自检，证明观测前后生产响应一致、每请求仅一次、正常shutdown与端口关闭；T38才可依赖其证据。使用既有 `task_runtime.py self-check` 承载自检，不新造浏览器驱动或测试endpoint。

逐页外部失败继续用既有隔离服务停止/恢复、合法失败请求和隔离媒体文件临时改名/恢复等已授权手段。只操作本批次自有资源，不能停止用户服务；每次清楚记录人工制造条件与恢复结果。这只能证明页面面对实际错误响应的呈现，不能证明上游业务失败的全部原因。不可达的页面×状态组合须写明该页没有对应动作/媒体等事实与替代观测，不能制造产品不存在的状态或用“不适用”跳过可达分支。

### 10.3 覆盖与收口

本轮仍为31条AC、17条既有追溯行。逐条覆盖检查已定位到§9原行，无需新造同义行；待补的是用例ID、上述分支证据及文档提交。tasks以T29–T39明确修复顺序，随后重验已退回任务和T23/T24/T25，最后再完成T26–T28。历史成功输出只保留其对应基线/切片效力；受修复影响的证据重新取得。全页原生200%与动态reduced-motion仍按§7.4明列未验证且不阻塞，不重新打开已裁决的工具门槛。

### 10.4 T35 首页表单溢出补充裁决（2026-09-09）

T35原始日志 `.work/c011/T35-browser-acceptance-20260909.log` 记录：IAB在 `http://127.0.0.1:5173/`、320×800亮色观察到首页H1为48px，但根clientWidth=305、scrollWidth=552；创建项目表单label/input/select右界为552.5px。此记录是实际页面失败，不是完整隔离验收；没有证明所有工作页字号通过，也不能由“T35未改表单规则”推断布局缺陷无需修复。现有form-grid/label/grid项与原生select缺少收缩约束是应诊断的通路，具体导致宽度的输入与计算轨道仍须隔离复现确认。

需求方此前已授权C011前端优化与本轮问题修复。原T35只授权标题选择器但要求整页无溢出，范围不足；现明确把同一验收发现的表单宽度根因修复纳入T35，沿用AC-05/06/07和“C011 全站视觉与响应式可访问性”，不是新增产品功能或AC。生产文件仍限PageTitle.tsx、HomePage.tsx、styles.css；后两者只允许既有首页表单标记及form-grid、其label、文本/数字input、select、textarea的必要宽度/网格收缩约束。共享规则如需调整必须验证已有消费者，不得更改值、选项全文、请求body、字段校验或保存行为，不改变checkbox/file控件的既有T24E合同。

实施时先在自有普通隔离库、DATA_DIR、前端代理下，使用正式风格API建立符合既有输入限制的长中文/连续英文风格名，记录选择前后实际option文本、选中值、grid轨道与控件几何，确认根因。原5173/8000只读失败记录保留，不向用户库写fixture，不停止/改配置/清理用户服务。不能因短fixture不溢出就忽略已见失败。

修复后两主题四视口重复相同合法长内容场景：根scrollWidth不大于clientWidth，表单控件边界位于其容器内，标题仍满足首页48–80px/工作页28–40px；键盘可选择真实风格且值不被截断改写，项目创建/编辑的字段合同不变。另检查共享form-grid消费者与checkbox18px/label40px、file控件及Director局部轨道滚动，不能通过根overflow-x:hidden/clip、裁掉控件、删除长内容、缩小标题或改变viewport规避。纯CSS布局使用真实浏览器验收，不新增镜像自动测试；完整build/G仍须运行。

T35保持未完成直到上述与原验收全部通过，再按既有派发进入T36及后续任务。这是当前任务内已授权的明确布局修复，不必再次请示是否可以修CSS；产品语义冲突、安全阻断或需要超出这些文件/职责时仍须报告。本次不改全页原生200%/动态reduced-motion既定未验证但不阻塞的裁决，也不新增DECISIONS候选。

### 10.5 T39 探针与 T37/T38 证据补全裁决（2026-09-09）

在实施HEAD `739ecd4` 上，旧 `probe-task-observation-20260909-132904.stdout.log` 唯一失败为重连后列表done/详情running。Astra核对T32当前生产代码确认：真实TasksPage展开动作先setExpandedTask(taskId)，再loadTaskDetail；旧探针只做后者，没有登记当前展开身份，因此不再代表原定“已展开页面重连”的触发。Astra仅修改一次性诊断脚本的该场景，改为挂载真实TasksPage、点击查看详情、同页断线/重连；detail=done期望保留，并新增列表/详情状态、进度、完成时间、展开标志、GET次数、连接数与零POST断言，其他13场景不改。新日志 `probe-task-observation-20260909-141633.stdout.log` 实际14场景通过，重连list=done/detail=done、detailGET=2/listGET=2/sockets=2/posts=0；实际仓库taskDetailReconnect.test.tsx四用例复跑通过。此为Astra的独立诊断修正，未改生产或既有测试，旧报告/日志保留，不把旧失败涂改为通过。

该结果只排除此发探针对B04的误报，不代表整个T39或C011通过，也不增加“所有未展开缓存必须自动刷新”的产品语义。Luna继续只读审查探针，不自行变更断言；需要适配的装置问题按证据报告，不通过兼容旧探针调用方式修改生产行为。

T38仍缺完整异常矩阵、八个按钮任务各自的独立只读数据库结果，以及部分同task请求/body/barrier原始记录。T37另存在直接相关装置缺陷：PassiveRequestObserver未限制目标请求，捕获并base64输出媒体响应，且缓存receive耗尽后合成http.disconnect；这不满足§10.2限定观测范围和原ASGI透传要求。先重新打开T37，在原.work装置内恢复限定范围、真实receive/send透传和原始stdout/stderr运行时落盘，再恢复T38。非目标请求包括media直接走原应用，不拷贝其响应正文作为观测日志；目标请求的完整body/status/task_id仍不得截断、推测或替代。此项只修正验收装置，不改生产事件/存储/进程通路，handler/client的受控替代边界仍按§10.2；不用T37的其他task记录证明T38实际按钮已产生相同body。

当前T38未完成时运行T39属于依赖顺序偏离，保留为预诊断，不作为正式任务验收。先T37→T38完整通过，再T39→原退回任务/T23/T24/T25→T26–T28。可以只读恢复旧原始文件和旧库当前状态；晚取的DB结果必须标真实时间，不能冒称当时读取。无法恢复的观测和装置变化影响的链路使用新隔离批次重新验收，不重放旧failed Task、不修改旧日志。当前裁决沿用AC-11/15/20/22/23/25与现有追溯行，无新AC或仓库测试，没有待决产品语义，也不新增DECISIONS条目。

### 10.6 验收频率与阶段证据复用裁决（2026-09-09，需求方授权）

需求方明确批准取消每个小 task 必跑完整 pytest 的规则。本节与 tasks 开头的同日验收频率表共同替代 §10.4/§10.5 及此前任务裁决中的逐 task G 频率，不修改 AC 的产品行为、风险分类、专项证据或既有日志。仍为31条AC、17条追溯行；AC-23继续对应 §9「C011 范围回归与文档提交一致性」，只是把完整回归安排在集成收口并允许核验同输入结果，无新增追溯行或自动测试。

纯文档检查文档与提交；CSS/布局运行build和受影响真实页面检查；前端逻辑运行定向、前端test/build及规定探针；后端/装置运行受影响API、任务系统或跨进程/资源生命周期检查。涉及公共数据库、队列、lifespan、协议或依赖的广泛影响时说明理由并提前完整回归。并发/取消/快照及跨进程风险不能因降低频率而省掉定向验收。

当前T38仍必须补齐完整异常矩阵和八按钮同task请求、barrier、REST/UI/独立DB证据，不新跑G。T39在T38完成后正式执行两发审查探针并取得一次完整G；若已有受测输入完全相同的成功G，可逐项核验后引用。T25核对最终实现与该证据的适用性，相关输入已改变或缺证据时补一次完整G；后续纯文档T26–T28不重复全套。不得把T37自检或预诊断当作T38/T39的专项验收。

复用须给出受测commit、当前差异、相关生产/测试/依赖/装置/环境配置、原命令、日志及真实退出码；仅文档提交不使证据失效，相关输入变化后先重验受影响检查并在收口前更新完整回归。失败、未运行或缺原始输出不算通过；新增配置/fixture批次的必要现场验证不能以其他批次代替。报告明确本次运行与引用，不因阶段全量尚未到期阻塞已通过自身门槛的小task，也不提前宣称change完成。

本裁决不更改 §7.0 装置的事件、存储或进程通路，G 仍完整运行前端test/build、隔离库迁移和完整pytest及diff检查，不修改run_checks.ps1制造局部G。受控handler替代及其不能证明真实GPU/M6的范围、实际浏览器要求、安全边界和失败不重试规则保持原约束。无需新增脚本、选择框架、hash、缓存或登记系统。

### 10.7 第二轮审查修复与闭环报告（2026-09-09，需求方授权）

需求方要求Astra修正文档、派发Luna修复并在报告后循环复审至C011完成。审查目标`8f3c4bdc09aca70eb800dc99cd4923f1e3c67eb9`，报告`.work/c011/review-reaudit-20260909.md`；失败原文`probe-cancel-read-order-20260909-161111.stdout.log`。本节优先于历史完成声明，保留旧证据，不改变31条AC、17条追溯行、产品行为及§7.4已裁决限制。

| 问题、原AC与风险 | 必须成立的既有合同切片 |
|---|---|
| B11；AC-12/13/14；[并发] | 真正展开queued详情GET在途，cancel网络错误或409后，取消前GET迟到返回queued不能结束确认；最新权威读取完成前再次激活仍只有1次无body POST。原错误保留，每task最多一个在途详情GET，旧读完成后补必要新读取 |
| B12；AC-12/13/14；[并发] | cancel已返回合法canceled或running+cancel_requested_at，后续权威详情GET失败：原错误与待同步说明可见，取消保护保持、POST为1。既有详情重读/重连等正式通路取得最新状态后按其恢复，不增加轮询或重发mutation。列表GET正常成功、详情持续失败且没有新WS事件/重连/用户重读时，失败不得通过列表刷新再次触发详情GET；独立探针`probe-cancel-confirmation-loop.py`验证该无自触发读取循环切片 |
| B13；AC-11/15/16；[并发] | 已展开详情后切换仍匹配task的过滤条件，实际打开新socket；task在连接间隙终结。新列表与仍展开详情的status/progress/finished_at/error_msg/取消时间等于最新GET，零mutation；不要求刷新所有未展开缓存。task从结果消失时清除展开身份，重现时保持收起；用户再次显式展开须读取当前详情，不能把消失前ready缓存当最新GET，独立`probe-filter-reopen.py`覆盖此切片 |
| B14；AC-09；[常规] | ShotsPage与DirectorPage的changed均逐字显示“已变更（changed）”，normal无角标；选择、禁用、R8警示及几何不变 |
| B15；AC-19/22/23；[外部输入] | 八类页面逐项记录可达加载/空态/读取失败/动作失败，媒体页另记媒体失败；每页动作失败有本页草稿/导航/原message及恢复证据，不可达组合写具体原因及替代观测；资产页失败不能替代其他页，G不能替代人工矩阵 |

B11–B13各新增独立“任务系统 mock”回归文件，通过真实TasksPage、controller、parser/API helper、deferred fetch/WS验请求与DOM；既有测试及Astra探针只读。B14沿既定常规展示人工验收，不新增镜像测试。B15复用普通fixture/正式API、自有服务停止恢复、媒体改名恢复及受控屏障，没有新浏览器驱动、生产endpoint或事件通路；同生产与替代边界沿§7、§10.2，不能关闭校验、直接写Task状态或触发真实GPU。

本轮spec定稿后先核对追溯：B11/B12归两条取消行，B13归REST/WS与公开边界行，B14归既有功能状态行，B15归全局异常、全局浏览器及范围一致性行，均已存在，无缺行；随后才编写T40–T44。顺序T40→T41→T42→T43→T44→T39与受影响原任务重验→T25→T26–T28。G仅在本轮T39集成收口执行；后续纯文档不重复全量。未变化且输入可核对的八按钮/视觉成功切片可精确引用。

Luna每项报告根因、改动/commit、具体用例ID、原始命令/结果、操作→观测值及限制；Astra据报告继续派发、独立复验并退回问题。保持既定行为的根因修复在授权范围内继续，不要求用户逐次裁决实现缺陷；既有测试修改、产品语义变更、外部依赖缺失及安全阻断仍须报告。未完成专项不勾任务、不提交伪完成。最终交付同时有Luna完成报告与Astra独立结论，本轮不自行归档、推送或进入C012。

B15空态验收说明：带媒体的人工fixture有项目与风格，不能用它证明首页无项目、设置无风格；也不能因此把可达空态写为不适用。另用全新仅Alembic迁移的隔离空库、独立DATA_DIR与普通生产后端，经既有数据库/Alembic/Uvicorn/Vite命令实际打开这两页；不新增脚本、模拟响应、seed或生产接口。该空库的前置证据为Alembic current/check、独立current_database()身份及正式GET项目/风格精确空数组，模板集合仍是migration规定的四固定key。人工媒体fixture的verify不适用于有意保持为空的批次，仍须在所有使用该fixture的批次执行。此空态通路与生产API/存储/进程相同，仅初始业务数据为空；不证明媒体/任务/生成，正常迁移后的四模板集合为空属于不可达状态。

T44装置复核更正：`5535a85` 的导演台观察实际依赖后来删除的 `hold_clip_lock.py`，不能因删除而把自建装置排除在验收要求之外。该批次保留为诊断事实，T44恢复未完成；先单列T44A交付这一有明确用途的故障装置及自检，再重做仅导演台在途写失败切片。装置只在自有隔离库的独立连接上通过PostgreSQL原生事务与行锁阻塞指定Clip写入，不修改数据；生产仍为原浏览器点击、PATCH、事务、数据库和WS/REST恢复通路。它改变的是数据库锁竞争时序及人为停止后端，不替换响应或业务代码；能证明真实写请求在途遇断线时UI与事务恢复，不能证明自然网络故障概率、任务取消或真实GPU失败。必须保留装置源码、原始输出与进程退出/事务回滚证据，不建立生产锁机制、通用故障框架或第二套浏览器驱动。

空库验收允许复用从未加入业务数据、经本次迁移检查与正式API证明仍为空的既有自有隔离库；“全新”不要求为同一空态反复创建等价数据库。库身份、独立DATA_DIR、Alembic current/check与两个精确空数组仍须本次取得。T44任务取消切片依赖当前T23复验；修复前的TasksPage证据只能保留历史事实，不能称为同输入证据。以上仍映射既有AC-19/22/23及§9原追溯行，没有新增产品行为或AC。
