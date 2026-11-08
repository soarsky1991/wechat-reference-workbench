# 权利采用补充（2026-11-08）

发布负责人已明确确认有权授权自有代码和原创说明并采用MIT。根LICENSE已转为正式MIT，NOTICE和UPSTREAM明确复用范围；原文、第三方图片、服务商资料不随包分发。以下待确认表述保留为历史，不代表当前权利状态。技术终审90/100、critical=0；本次仅许可和发布说明整合，执行代码未变。

# 当前集成状态：0.2.0-preview.3（2026-11-08）

- 费用定点修复累计2/max2；collectors 13/13通过，独立相关复验确认0.02上限/0.03回执STOP、无staging且原回执与账本保留。使用mock，无真实API调用或费用。
- 全文专题一次实现，执行者报告关键前端逻辑10/10通过；主线真实浏览器核对38,452字符长文完整，正文起点1510→171px，读区320→667px，End/Home及返回列表可用。请求520×800窄屏的实际CSS宽481px，长文仍完整、无横溢且End到尾。
- 合成演示正文首段可见，审核可展开，console本次error/warn捕获为空；截图见docs/assets/。这不是人类用户测试，也不证明所有文章和设备均已检查。
- 参考库内部独立终验91/100、critical=0；571有效名录/201新增合格正文/18已核公众号。真实库不随软件分发。
- 公开包最终相关审查与自有MIT权利确认尚未关闭；未创建或发布公开仓库。以下v0.2记录为保留历史，不覆盖本节的当前UI观察。

---

# 费用回执定点返修 v0.3 自测补充

- 当前包版本：`0.2.0-preview.3`；累计 `repair_count=2/max=2`。
- 本次 collectors 全套：**13/13**；新增费用护栏定向用例：**2/2**（详见 `collectors-unittest.log` 与 `datax-billing-guard-test.log`）。覆盖合法等于/低于 cap、bool、NaN、Infinity、负值、缺失 amount/currency、错币种、amount/结构异常、超 cap。
- 异常分支逐项确认：原始回包和解析回执保留，attempt ledger 状态以 STOP 结尾，`datax-staging/` 不创建，transport 仅一次、`retry=NONE`。
- 本次外网调用/真实 API/真实 key/账户-run请求/费用均为0；mock单元测试在进程中仅设置非真实占位key以满足本地门禁，且所有传输均为mock；集成测试另使用本地回环HTTP。

---

# 本轮实现与自测摘要

- 包版本：`0.2.0-preview.2`；实际模型：`NOT_EXPOSED`。包内为3条合成示例，无真实文章、账号、图片、凭据或生产数据库。
- 本次实际运行：collectors Python **11/11**；viewer Python **16/16**；Node **4/4**。其中 collectors 集成mock覆盖RSS/元数据→正文暂存→显式SIGNED签收→viewer，以及首错停止和跨run不重试；DataX mock覆盖清洁副本文档准备、固定原文SHA、漂移/重定向/过期snapshot阻断、当前账户/额度门禁、单次调用和原回执查询。三套分开计数，不把历史测试或捕获manifest数混成测试轮次。详见同目录日志。
- 新端口本机HTTP冒烟：`127.0.0.1:8791`。首页HTML、runtime只读/合成标记、3条列表与PASS/NEEDS_EVIDENCE/EXCLUDE各1、3条合成正文详情、未知ID 404均通过；SQLite `mode=ro` 写入被拒，完整性为ok且SHA前后相同。日志：`http-smoke.log`。
- Host/Origin信任边界新增真实loopback测试：正常同源200；恶意Host与跨源Origin均421拒绝。
- 真实桌面浏览器验收**未通过/未完成**：Chrome标签显示“只允许本机同源请求”；随后启动桌面Chrome时，Computer Use提示Mac已锁定，无法继续。没有绕过来源边界，没有生成或加入演示截图。故不声称用户可视UI通过；需在解锁后的正常桌面浏览器环境重新打开并查看。
- DataX官方文档准备路径为可携带实现：包内固定三份已审核原文SHA/合同版本，`prepare-docs` 从官方URL逐一无重定向读取并验证，成功后生成当前本地snapshot；不需要私有内部目录或旧动态snapshot。mock覆盖source drift、redirect、过期snapshot和无内部路径清洁拷贝。此次未访问外网官方站、未查余额、未建run、未调用API、未收费；测试仅使用mock transport和本地回环HTTP。
- Parser self-check与CLI帮助输出保存在同目录；无第三方依赖安装。
- 项目里程碑数值仅按给定回执：571有效名录、201新增合格正文、18核实账号；30候选未计入。按给定基线235/62/$1.54算差额+336/+139/+$2.66，当前阶段DataX $4.20。provider key历史$13.60未归因；模型tokens/费用不可归因。参考库最终独立验收仍在途；31个public-native manifest只是捕获批次清单，不等于成功篇数或测试轮次。
- 自有代码MIT仅为候选提案，NOTICE保留OpenReader归因范围；未声称权利人签字或正式发布许可。整个包仍未发布，也未完成最终UI验收与发布权确认。
