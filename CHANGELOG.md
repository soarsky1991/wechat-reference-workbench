# 0.2.1-preview.1 — 2026-11-08

Documentation-only release: rewrite README around first-time users; add module/data-flow diagram, clone/download instructions, guided three-record demo, FAQ and progressive links. Preserve previous technical detail in docs/advanced-guide.md. Runtime, collection support, data, fees and API behavior are unchanged.

# 变更记录

## 0.2.0-preview.3

- 修复 DataX 成功回包费用未校验授权上限的问题：金额以有界 `Decimal` 验证，拒绝 bool、非有限值、负数、畸形结构、缺失值及非 USD 币种；超 cap 或异常回执保留原文、账本 STOP、零重试且不 staging。
- Mock 覆盖 cap 等值/低于 cap 成功及异常/超限分支；本次 collectors 全套 13/13 通过。未发真实 API 或产生费用。

## 0.2.0-preview.2

- 可携带 DataX 文档缓存：移除内部归档路径和旧动态 snapshot 哈希依赖；新增固定官方文档准备入口，核对已审原文 SHA、公开合同和价格后生成新鲜本地 snapshot。源码漂移、重定向、schema/价格变化和过期快照均 fail closed。
- 增加清洁拷贝 mock 覆盖；本轮 collectors 11/11、viewer 15/15、Node 4/4。无真实账户、run、API 或费用调用。
- README 加入正式数量与阶段费用边界、候选/manifest口径和三条实操教训。桌面浏览器验收受本地UI运行环境阻断，仍未通过；发布截图未生成。
- 许可证仍为自有代码 MIT 候选，不表示权利人签字或包已可发布。

## 0.2.0-preview.1

- 增加可携带 Appinn/SSPai RSS 与用户 URL 候选流程、跨 run 成功/失败防重、整页订阅锁检查、单次正文捕获、持久 STOP 和待独立审查产物。
- 增加只接受显式 SIGNED 结构化输入的本地 viewer 工作区物化步骤；不打分、不改判。
- 实现 DataXAPI `get` / `list` 受控兜底：固定官方原文 SHA 与 schema，用户本地 `prepare-docs` cache，当前 balance/run 证据、额度、单次 max-price 与确认门禁；mock 测试，无账户请求和收费调用。
- 保留测试演示 viewer 与合成三态样例；默认回环地址；修复 SQLite 只读连接关闭与 macOS 临时路径别名。
- 增加自有代码 MIT 提案、NOTICE 和清单；许可仍待发布负责人最终确认。

## 0.1.0-demo.1

- 建立默认加载三条合成样例的本地只读 viewer。
- 增加显式外部数据根变量 `PUBLIC_WORKBENCH_DATA_DIR`，默认监听 `127.0.0.1`。
