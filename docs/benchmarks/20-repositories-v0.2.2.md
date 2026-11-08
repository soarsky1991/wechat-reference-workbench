# 20个新增仓库对标与采用记录 v0.2.2

日期：2026-11-08。本轮新增系统评审20个仓库，不重复上一轮WeRSS、RSSHub、FreshRSS、Karakeep、wallabag五个核心对象。按任务相关性和可迁移机制选取，不宣称是GitHub Star排行榜前20。

## 证据与方法

读取官方README；每项保存读取时间、原文SHA256、行号与短摘录，详见[sources-v0.2.2.json](sources-v0.2.2.json)。HEAD是读取时的可变引用，SHA绑定本轮读到的原文；不等于固定Git提交。原README全文仅在研究临时缓存，不随包复制；没有安装这20个项目或调用其服务。观察到入口/文档不等于已经实测功能。增长机制是推断，没有流量归因、A/B或Star增长因果证据。

候选BookStack的README大写文件路径首次404；随后官方GitHub页面明确标为由Codeberg管理。未把404解读为软件不可用，也未用迁移仓库充数，改用AFFiNE补足20个。保留[官方迁移提示](https://github.com/BookStackApp/BookStack)。

## 多维对比总表

| 编号 | 仓库 | 可核观察 | 借鉴后的具体动作 | 状态 |
|---|---|---|---|---|
| B01 | [RSSNext/Folo](https://github.com/RSSNext/Folo) | 按内容形式分段展示功能，并提供不同平台入口 | 图文导览拆成名录、正文、审查三步 | 本版采用 |
| B02 | [usememos/memos](https://github.com/usememos/memos) | Demo、Install、Docs分流，并单列升级说明 | 首页三条路径，补更新与版本说明 | 本版采用 |
| B03 | [linkwarden/linkwarden](https://github.com/linkwarden/linkwarden) | 把建议、路线图与社区项目列为独立入口 | 增加已实现/计划能力表和贡献任务 | 本版采用 |
| B04 | [sissbruecker/linkding](https://github.com/sissbruecker/linkding) | 明确写出可导入导出的格式 | 列出现有签收JSON输入与输出工作区契约 | 本版采用文档 |
| B05 | [miniflux/v2](https://github.com/miniflux/v2) | 将隐私安全与功能分组说明 | 导览单列数据位置、费用与实际边界 | 本版采用文档 |
| B06 | [readest/readest](https://github.com/readest/readest) | 已实现功能和计划功能分开列出 | 能力状态表分已提供/可选/未提供 | 本版采用 |
| B07 | [laurent22/joplin](https://github.com/laurent22/joplin) | 把网页剪藏入口与笔记产品连接 | 未来候选：轻量URL输入入口 | 未来候选 |
| B08 | [logseq/logseq](https://github.com/logseq/logseq) | 设有Why、使用方法及学习入口 | 增加适合谁、与纯阅读器的用途差别 | 本版采用文档 |
| B09 | [siyuan-note/siyuan](https://github.com/siyuan-note/siyuan) | 显式说明架构和生态 | 组件边界表标明DataX外部服务、非插件/MCP | 本版采用文档 |
| B10 | [TriliumNext/Trilium](https://github.com/TriliumNext/Trilium) | 单列迁移入口及项目延续说明 | 新增旧版用户文档迁移路径和保留历史说明 | 本版采用文档 |
| B11 | [outline/outline](https://github.com/outline/outline) | 安装与开发贡献分为独立章节 | 导览先体验，再列采集及开发贡献 | 本版采用文档 |
| B12 | [AppFlowy-IO/AppFlowy](https://github.com/AppFlowy-IO/AppFlowy) | 用户安装与源码开发入口分开 | 首页分首次体验/已有资料/开发贡献 | 本版采用 |
| B13 | [excalidraw/excalidraw](https://github.com/excalidraw/excalidraw) | 明确区分在线应用与组件库安装 | 醒目标注CLI+本地网页，不是插件或MCP | 本版采用文档 |
| B14 | [immich-app/immich](https://github.com/immich-app/immich) | 提供专门演示入口并解释用法 | 三条合成记录的图文导览与验收动作 | 本版采用本地演示 |
| B15 | [paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | 演示说明内容会重置，清楚标明演示环境 | 合成签收实例全程标测试，不冒充真实审查 | 本版采用 |
| B16 | [actualbudget/actual](https://github.com/actualbudget/actual) | 按首次使用和迁移用户分流 | 首页任务分流与旧版用户更新入口 | 本版采用 |
| B17 | [vuejs/vitepress](https://github.com/vuejs/vitepress) | 把详细文档、变更与贡献入口分离 | 简化首页导航，进阶与研究报告分开 | 本版采用 |
| B18 | [facebook/docusaurus](https://github.com/facebook/docusaurus) | 设有新贡献者可进入的小问题入口 | 新增文档复现/测试补充/适配提案三类任务 | 本版采用 |
| B19 | [toeverything/AFFiNE](https://github.com/toeverything/AFFiNE) | 首屏把在线体验、下载和文档连接 | 导览/下载/完整说明并列导航 | 本版采用文档 |
| B20 | [Athou/commafeed](https://github.com/Athou/commafeed) | 部署、更新与具体排错有独立章节 | FAQ说明端口、解释器、空列表及采集停止 | 本版采用文档 |

## 各项证据、推断与适用边界

### B01 · RSSNext/Folo

- 官方证据：[README第92行附近](https://raw.githubusercontent.com/RSSNext/Folo/HEAD/README.md)；短摘录：`### Every Format`。原文SHA：`45bd16f0b831734a06ebed60b8dd3d10e177e5c312d3b8117d0e8f18b01a5ca8`。
- 观察：按内容形式分段展示功能，并提供不同平台入口。
- 可迁移推断：按任务分屏展示，不让单张阅读截图代替全流程。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：图文导览拆成名录、正文、审查三步；状态：本版采用。
- 不采用/边界：不开发移动客户端，不借用其排行徽章。

### B02 · usememos/memos

- 官方证据：[README第34行附近](https://raw.githubusercontent.com/usememos/memos/HEAD/README.md)；短摘录：`## Quick start`。原文SHA：`441f879a482850273554612eb656bc10d25e85d565bb8b34fc1d4349cae56811`。
- 观察：Demo、Install、Docs分流，并单列升级说明。
- 可迁移推断：给体验者与维护者不同入口。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：首页三条路径，补更新与版本说明；状态：本版采用。
- 不采用/边界：没有部署公共在线演示。

### B03 · linkwarden/linkwarden

- 官方证据：[README第105行附近](https://raw.githubusercontent.com/linkwarden/linkwarden/HEAD/README.md)；短摘录：`## Roadmap`。原文SHA：`2813dd16022b0e23f9f2f19cbf216be22b201cb9a089cd3d38184dc7a62c7939`。
- 观察：把建议、路线图与社区项目列为独立入口。
- 可迁移推断：让反馈与未来工作关联。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：增加已实现/计划能力表和贡献任务；状态：本版采用。
- 不采用/边界：不承诺云托管、PDF归档或增长结果。

### B04 · sissbruecker/linkding

- 官方证据：[README第26行附近](https://raw.githubusercontent.com/sissbruecker/linkding/HEAD/README.md)；短摘录：`- Import and export bookmarks in Netscape HTML format`。原文SHA：`ee0d7ad2b5508071b9f36cde500286a90dee41f3251197ff6c81dcfd499c3e8c`。
- 观察：明确写出可导入导出的格式。
- 可迁移推断：先说清用户怎样带入已有资料。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：列出现有签收JSON输入与输出工作区契约；状态：本版采用文档。
- 不采用/边界：不虚构已支持Netscape书签导入。

### B05 · miniflux/v2

- 官方证据：[README第25行附近](https://raw.githubusercontent.com/miniflux/v2/HEAD/README.md)；短摘录：`### Privacy and Security`。原文SHA：`2a18e492d96193f6bb1122bd493944e07987920a06005a48651c304e310a4a48`。
- 观察：将隐私安全与功能分组说明。
- 可迁移推断：把信任建立在可核对边界上。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：导览单列数据位置、费用与实际边界；状态：本版采用文档。
- 不采用/边界：不采用访问绕过机制。

### B06 · readest/readest

- 官方证据：[README第29行附近](https://raw.githubusercontent.com/readest/readest/HEAD/README.md)；短摘录：`<a href="#planned-features">Planned Features</a> •`。原文SHA：`fb350e8b297a831bd8ab8f0badd8eb641ef2e055c13385f74891acdf9a14faa9`。
- 观察：已实现功能和计划功能分开列出。
- 可迁移推断：让用户知道现在能用什么。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：能力状态表分已提供/可选/未提供；状态：本版采用。
- 不采用/边界：不把计划能力写成可用。

### B07 · laurent22/joplin

- 官方证据：[README第17行附近](https://raw.githubusercontent.com/laurent22/joplin/HEAD/README.md)；短摘录：`The application is available for Windows, Linux, macOS, Android and iOS. A [Web Clipper](https://github.com/laurent22/joplin/blob/dev/readme/apps/clipper.md), to save web pages`。原文SHA：`b9444e9a16aa4d8b87124a368605847ce9ad368e603e5f6116c34f3121a86f69`。
- 观察：把网页剪藏入口与笔记产品连接。
- 可迁移推断：在发现内容的地方降低输入成本。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：未来候选：轻量URL输入入口；状态：未来候选。
- 不采用/边界：本版不新增浏览器扩展。

### B08 · logseq/logseq

- 官方证据：[README第58行附近](https://raw.githubusercontent.com/logseq/logseq/HEAD/README.md)；短摘录：`* [<g-emoji class="g-emoji" alias="thinking" fallback-src="https://github.githubassets.com/images/icons/emoji/unicode/1f914.png">🤔</g-emoji> Why Logseq?](#-why-logseq)`。原文SHA：`597bcf7218c37fdf053524467029e22db5c29faffd8fb21007512bbbd3affe56`。
- 观察：设有Why、使用方法及学习入口。
- 可迁移推断：解释为什么值得更换现有流程。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：增加适合谁、与纯阅读器的用途差别；状态：本版采用文档。
- 不采用/边界：不把双链或知识图谱写成本产品能力。

### B09 · siyuan-note/siyuan

- 官方证据：[README第40行附近](https://raw.githubusercontent.com/siyuan-note/siyuan/HEAD/README.md)；短摘录：`- [🏗️ Architecture and Ecosystem](#-architecture-and-ecosystem)`。原文SHA：`48e4316db80452ca4c60824009217bafe100e5c4bc53de00594e4069a2bbe51f`。
- 观察：显式说明架构和生态。
- 可迁移推断：区分核心功能、扩展与外部组件。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：组件边界表标明DataX外部服务、非插件/MCP；状态：本版采用文档。
- 不采用/边界：未复用第三方代码或主题。

### B10 · TriliumNext/Trilium

- 官方证据：[README第77行附近](https://raw.githubusercontent.com/TriliumNext/Trilium/HEAD/README.md)；短摘录：`### ⬆️Migrating from Zadam/Trilium?`。原文SHA：`087906667d44cbca6a47a4e198713c7b068c1766c8fe9a80daa9b4e7480eae95`。
- 观察：单列迁移入口及项目延续说明。
- 可迁移推断：解释已有用户如何更新。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：新增旧版用户文档迁移路径和保留历史说明；状态：本版采用文档。
- 不采用/边界：不新增数据库迁移工具。

### B11 · outline/outline

- 官方证据：[README第23行附近](https://raw.githubusercontent.com/outline/outline/HEAD/README.md)；短摘录：`# Installation`。原文SHA：`f726b4c7b465cfcf91a009fa897b5bafe24803d6ef03f68366011a3d5caf7f61`。
- 观察：安装与开发贡献分为独立章节。
- 可迁移推断：使用者无需先理解开发环境。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：导览先体验，再列采集及开发贡献；状态：本版采用文档。
- 不采用/边界：不照搬认证或托管架构。

### B12 · AppFlowy-IO/AppFlowy

- 官方证据：[README第53行附近](https://raw.githubusercontent.com/AppFlowy-IO/AppFlowy/HEAD/README.md)；短摘录：`## User Installation`。原文SHA：`10eb6aceebe3dba3912464e5bfaa72195c7e3697cb3f7670409880e697a12ec5`。
- 观察：用户安装与源码开发入口分开。
- 可迁移推断：按读者角色分流。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：首页分首次体验/已有资料/开发贡献；状态：本版采用。
- 不采用/边界：不声称桌面客户端已有打包。

### B13 · excalidraw/excalidraw

- 官方证据：[README第54行附近](https://raw.githubusercontent.com/excalidraw/excalidraw/HEAD/README.md)；短摘录：`The Excalidraw editor (npm package) supports:`。原文SHA：`011eea74cbbf38fd263ec93a221f379466c557dc7587acfe93797201193a7e7a`。
- 观察：明确区分在线应用与组件库安装。
- 可迁移推断：消除产品类型与安装误解。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：醒目标注CLI+本地网页，不是插件或MCP；状态：本版采用文档。
- 不采用/边界：不发布尚不存在的软件包。

### B14 · immich-app/immich

- 官方证据：[README第65行附近](https://raw.githubusercontent.com/immich-app/immich/HEAD/README.md)；短摘录：`## Demo`。原文SHA：`b37199a0b7b52d1a6a62c97d6ad1a4eea18f367b8f8dad378ac9a0926f351a34`。
- 观察：提供专门演示入口并解释用法。
- 可迁移推断：让访客先看到完整操作结果。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：三条合成记录的图文导览与验收动作；状态：本版采用本地演示。
- 不采用/边界：没有开放公网或触碰真实照片。

### B15 · paperless-ngx/paperless-ngx

- 官方证据：[README第24行附近](https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/HEAD/README.md)；短摘录：`Thanks to the generous folks at [Fyra Stack](https://fyrastack.com), a demo is available at [demo.paperless-ngx.com](https://demo.paperless-ngx.com) using login demo /`。原文SHA：`57aadae7f68c77d36a3ed5b2954129e8675b7e63c2453bf16c93bce774cdb7ec`。
- 观察：演示说明内容会重置，清楚标明演示环境。
- 可迁移推断：演示数据与生产资料边界清楚。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：合成签收实例全程标测试，不冒充真实审查；状态：本版采用。
- 不采用/边界：不引入OCR、扫描器或第三方原图。

### B16 · actualbudget/actual

- 官方证据：[README第38行附近](https://raw.githubusercontent.com/actualbudget/actual/HEAD/README.md)；短摘录：`### Are you migrating from other budgeting apps?`。原文SHA：`fd174335284daa65ef6345dc139649fb3f4926fd57f26b0cbf98f5bfaab4485d`。
- 观察：按首次使用和迁移用户分流。
- 可迁移推断：从用户当前处境组织文档。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：首页任务分流与旧版用户更新入口；状态：本版采用。
- 不采用/边界：不照搬其收费部署报价。

### B17 · vuejs/vitepress

- 官方证据：[README第16行附近](https://raw.githubusercontent.com/vuejs/vitepress/HEAD/README.md)；短摘录：`## Changelog`。原文SHA：`dc3dc2c3e4e0acf576dbb415d3587f95c04a4738814c2bb75e359350fb6b1206`。
- 观察：把详细文档、变更与贡献入口分离。
- 可迁移推断：首页保持短，逐层深入。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：简化首页导航，进阶与研究报告分开；状态：本版采用。
- 不采用/边界：不为文档引入新的构建依赖。

### B18 · facebook/docusaurus

- 官方证据：[README第70行附近](https://raw.githubusercontent.com/facebook/docusaurus/HEAD/README.md)；短摘录：`### Beginner-friendly bugs`。原文SHA：`c6800696de889e960173a7a17d5a12e41d71ae71b167c0ee5199adfa49b7e348`。
- 观察：设有新贡献者可进入的小问题入口。
- 可迁移推断：把欢迎贡献变成具体工作。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：新增文档复现/测试补充/适配提案三类任务；状态：本版采用。
- 不采用/边界：不捏造已有贡献者或创建虚假用户问题。

### B19 · toeverything/AFFiNE

- 官方证据：[README第27行附近](https://raw.githubusercontent.com/toeverything/AFFiNE/HEAD/README.md)；短摘录：`<a href="https://app.affine.pro">Live Demo</a> |`。原文SHA：`8d5be20062755f5b1ecc26bca4cf6d590efa28de7c4a64d2732bf26f66f78ae0`。
- 观察：首屏把在线体验、下载和文档连接。
- 可迁移推断：让访问者选择下一步动作。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：导览/下载/完整说明并列导航；状态：本版采用文档。
- 不采用/边界：不复制其视觉资产或宣传数字。

### B20 · Athou/commafeed

- 官方证据：[README第129行附近](https://raw.githubusercontent.com/Athou/commafeed/HEAD/README.md)；短摘录：`### Memory management`。原文SHA：`a347114a8eaf760f6963f68e09700cdd58e932fe397d96a70835ec0f9f4e40ec`。
- 观察：部署、更新与具体排错有独立章节。
- 可迁移推断：让用户遇到失败后仍找得到下一步。这是设计判断，不是已证实的涨粉原因。
- 本项目采用：FAQ说明端口、解释器、空列表及采集停止；状态：本版采用文档。
- 不采用/边界：不修改安全设置来绕过访问限制。

## 优先级与迭代合同

| 优先级 | 缺口 | 本版动作 | 验收标准 |
|---|---|---|---|
| P0 | 看懂产品但不知道该点哪里 | 首次体验/已有资料/贡献者三条入口 | 所有入口有目标文档与具体下一步 |
| P0 | 只有短文截图，过程不清楚 | 名录→筛选→阅读图文导览 | 使用运行中的合成界面截图，图片实际加载 |
| P0 | 手写签收JSON门槛高 | 提供填好的合成签收文件与离线运行示例 | render-signed实际生成1条，哈希与状态回读一致 |
| P0 | 宣传与能力混淆 | 已提供/可选/未提供分表 | 没有声称新增采集源、浏览器插件、MCP或公共服务 |
| P1 | 反馈无法变成贡献 | CONTRIBUTING与路线图 | 具体提交材料/可做任务/验收要求可查 |
| P1 | 首次使用经验缺失 | 小规模真实用户试用 | 后续需真实用户参与；本版不伪造满意度 |
| P2 | 缺公共在线演示、通用导入、桌面打包 | 仅记录候选，不实现 | 有明确范围和验收后另开工作 |

## 展示增长应怎样检验

关注访问→看懂→启动→完成任务→复用→反馈/分享。Star/Watch/Fork不是安装或留存，不以它们证明本次改版有效。演示、迁移、贡献入口可能降低摩擦；实际转化需后续用户验证。不给承诺Star数，不复制无证据徽章、排行榜或用户证言。

## 产出标准

20/20官方来源可读且各有独特可复用优点、证据短摘录和边界；采用动作可追溯；本地链接/清单/合成示例校验通过；真实GitHub页面图片与导航加载；不更改运行代码/真实数据/费用门禁。委员会为同一执行者模拟访客、操作者、维护者与事实核查四个视角，不是独立代理或真人用户测试。缺硬门槛不以综合分抵消。
