# DataX 单次请求 preflight 格式

此适配器只读本地证据后才可能执行一个 `get` 或 `list`。它不调用 `/v1/account`、不创建/续期 run、不自动翻页。preflight 文件应由操作者在当前账户与已存在 run 已核验之后创建；其中路径都指向操作者私有目录里的原始成功回包 JSON。命令使用前必须现场核对账户与 run 仍有效。

新工作区先运行 `python3 collectors/cli.py prepare-docs --cache-dir <新本地目录>`。它只请求三份固定官方文档各一次，验证发布版审核过的原文 SHA 和合同字段后生成当前 snapshot。snapshot 的抓取时间是新值，原文 SHA 与合同 revision 必须保持被审核值；任何文档漂移、价格变化、OpenAPI 参数变化或重定向都会停止，不生成可用 cache。公开包不要求也不读取项目内部 `release-preparation/` 目录。

## 必需字段

```json
{
  "schema": "public-workbench-datax-preflight/v1",
  "created_at": "带时区的 ISO 时间",
  "authorized_single_call": true,
  "catalog_revision": "3efbf7080dda485f",
  "pricebook_version": "12",
  "docs_hashes": {
    "agents.md": "4a51542489503a9d3e286ffb8c37092b71299929b69d93e7fbb08f40b459eb74",
    "openapi.json": "82cad987f238f7e782df92872c9f9f7121bcfc55fb654543b441d42db9487765",
    "prices.json": "9742e226e7ca32eed3db92eba8d6020183af5d0369f7596c27fad65e9c2a29a4",
    "snapshot.json": "prepare-docs刚生成的snapshot.json文件SHA-256"
  },
  "run_id": "00000000-0000-4000-8000-000000000001",
  "run_scope": {"task_id": "已存在run中的原值", "task_revision": "已存在run中的原值"},
  "run_step": "1",
  "run_iteration": "1",
  "max_price": "0.02",
  "scope": {
    "operation": "get",
    "params": {"url": "完整公开 mp.weixin.qq.com URL 原样粘贴"}
  },
  "balance_evidence": {
    "path": "/private/local/path/account-response.json",
    "sha256": "该原始 JSON 文件 SHA-256",
    "observed_at": "该次免费 /v1/account GET 的带时区时间"
  },
  "run_evidence": {
    "path": "/private/local/path/existing-run-response.json",
    "sha256": "该原始 JSON 文件 SHA-256",
    "observed_at": "该次免费 /v1/runs/{id} GET 的带时区时间"
  },
  "human_approval": {
    "approved": true,
    "operation": "get",
    "params_sha256": "SHA256(compact sorted-key UTF-8 JSON of scope.params)",
    "max_price": "0.02",
    "run_id": "与顶层run_id相同",
    "run_scope": {"task_id": "与顶层run_scope相同", "task_revision": "与顶层run_scope相同"},
    "run_step": "1",
    "run_iteration": "1"
  }
}
```

这是字段说明，含路径与 SHA 的占位内容**不可直接执行**。`params_sha256` 算法为 `json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")` 再 SHA-256。JSON 的 `scope` 必须与 CLI 中 `--operation`、`--params-json` 完全一致；批准对象还要逐字段绑定 operation、params hash、cap、run ID、task/revision、step 和 iteration。命令行 `--confirm-paid-transfer` 是执行前最后的单次确认。`get` 仅接受安全校验后的完整公开微信 URL；`list` 的必需参数为 OpenAPI 所列原始账号 `id`，可选参数只能是同一 operation 在锁定 OpenAPI 中声明的字段。

校验会核实 balance/run 原始 JSON 文件哈希和≤6小时观察时间、USD余额、API key scope/日/月/总预算（若响应提供）、现有 run 的 task/revision/ID、未过期状态、remaining_amount 与 remaining_calls。step 和 iteration 各为1–6位数字。单次 cap 必须等于该 endpoint 最大扣费且不超余额、key预算或 run 剩余额。

快照状态只表示公开契约已核验，不表示账户已连接，也不证明余额/run 仍有效。动态 snapshot SHA 只校验当前本地缓存未漂移，固定三原文 SHA 与合同字段校验新旧合同一致；任一不一致即拒绝调用，须由维护者重新核对 OpenAPI schema 与价格，而不是静默更新指纹后直接试请求。
