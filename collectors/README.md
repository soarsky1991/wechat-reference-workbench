# 本地候选工作流

本目录的 CLI 用于公开网页候选发现、一次捕获、待审产物和显式签收展示。它不会改生产 CSV/SQLite/approved，不提供自动质量准入或自动发布。完整说明见包根 README 与 [`REVIEW-WORKFLOW.md`](REVIEW-WORKFLOW.md)。

- `workflow.py`：RSS/用户 URL 元数据、跨 run 单次尝试账本、Appinn/SSPai 捕获、持久 STOP、SIGNED 工作区物化。
- `native_adapters.py`：复用已核验的 Appinn/SSPai 静态闭合容器提取规则及日期/署名证据。
- `subscription_gate.py`：在解析前检查完整 HTML 中已知订阅锁；未命中不表示没有访问限制。
- `datax_fallback.py`：仅在完整 DataX preflight 和明确付费确认后，最多调用一个官方限定 GET；不创建 run、不刷新 balance、不重试。细节见 [`DATAX-PREFLIGHT.md`](DATAX-PREFLIGHT.md)。
- `cli.py`：本地命令入口。

运行原生页面适配自检和所有离线测试：

```sh
python3 -c 'from collectors.native_adapters import parser_self_check; print(parser_self_check())'
python3 -m unittest discover -s collectors -p 'test_*.py' -v
```

所有测试 transport 均为内存 mock/合成输入，不调用网络或收费 API。未知扣费只允许按原 request ID 查原回执；不要重发原请求或创建新 run。
