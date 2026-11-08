# 可以怎样帮助改进

先选择一个小任务，不需要先读完整个仓库。

| 任务 | 提交什么 | 怎样验收 |
|---|---|---|
| 文档复现 | 卡在哪一步、系统/Python版本、命令和脱敏输出 | 维护者能用同样步骤复现；修订链接可打开 |
| 合成测试补充 | 完整、无版权争议的小fixture及预期结果 | 离线运行，失败原因与状态明确 |
| 来源适配提案 | 公开来源、允许访问的依据、预期结构、停止条件 | 先讨论范围；不提交登录态、Cookie或绕限制方案 |
| 阅读体验问题 | 合成记录、窗口大小、动作、预期和实际截图 | 真实运行环境复现，不以DOM有全文代替可读性 |

提案走[Issues](https://github.com/soarsky1991/wechat-reference-workbench/issues/new/choose)，交流场景走[Discussions](https://github.com/soarsky1991/wechat-reference-workbench/discussions)。不要为了证明贡献而提交无实际内容的PR。

## 开发检查

运行使用Python标准库；Node只用于下面的前端逻辑测试。

```sh
python3 -m unittest discover -s collectors -p 'test_*.py' -v
python3 -m unittest discover -s app/tests -p 'test_*.py' -v
node --test app/tests/test_review_display.cjs app/tests/test_reader_display.cjs
```

只改文档时，检查本地链接、示例命令与相关截图即可，不要求重复跑无关采集测试。涉及安全、费用或数据完整性的改动，请附对应回归测试。PR写清变更原因、验证、未测范围，不附密钥或真实文章全集。

提交PR表示你有权按本仓库许可提交相应内容；第三方资料须保留其自身许可和来源。维护者不会因功能请求存在就承诺接受或上线日期。
