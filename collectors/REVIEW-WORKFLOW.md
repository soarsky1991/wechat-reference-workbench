# 人工独立审查与显式签收

抓取回执只证明一次响应被本地保存；它不替代文章审核。审查对象至少包括 `source.html`、`body.txt`、`extraction.json`、`fetch-receipt.json` 和来源发现记录。先核所有 SHA 与正文提取范围，再看首段、中段、尾段及完整闭合边界。

## 审查记录

每个对象分别记录：

- 精确 URL、稳定身份、原页 H1/标题、作者证据、发布时间原始字段及日期冲突；
- 原始 HTML、正文、提取说明和请求回执的路径/SHA；正文引用必须是连续原文并可按 UTF-8 文本偏移切片复核；
- `relevant`、`actionable`、`credible`、`author_increment`、`decision_value` 五项评分（0、0.5、1）与理由；
- 正文是否闭合完整、关键媒体是否影响理解、来源/事实冲突、适用人群和具体参考用途；
- 作者效果声明标 `SOURCE_REPORTED`；未独立操作/复现标 `NOT_TESTED`。未亲测本身不是拒绝理由；
- `PASS / NEEDS_EVIDENCE / EXCLUDE` 与计数建议。PASS 通常要求总分至少3.5、relevant/credible各至少0.5，且无核心事实或完整性阻断。所有状态仍由明确签收人决定。

工具不得自动给 Q、自动改审查决定或把 provider 成功、预览文本、旧版本和图像缺失推成质量结论。正文受限/付费、出现访问锁或截断时，停止补抓；不要绕过限制、换会话或寻找同篇非公开副本。

## 显式签收结构

签收文件使用 `public-workbench-signed-acceptance/v1`。顶层 `signoff` 至少含：

```json
{
  "schema": "public-workbench-signed-acceptance/v1",
  "signoff": {
    "status": "SIGNED",
    "reviewer": "审查人标识",
    "signed_at": "2026-11-08T12:00:00+08:00",
    "as_of": "2026-11-08T12:00:00+08:00",
    "record_ids": ["synthetic-pass-001"]
  },
  "records": [{
    "record_id": "synthetic-pass-001",
    "account_name": "合成来源",
    "account_id": "synthetic-only",
    "title": "【测试演示】合成签收示例",
    "source_url": "https://sspai.com/post/123456",
    "published_at": "",
    "Q": 4.0,
    "reference_status": "PASS",
    "counts_toward_target": true,
    "claim_verification": "SOURCE_REPORTED",
    "reason": "仅展示签收字段，不对应真实文章或审核结论。",
    "reason_codes": ["SYNTHETIC_TEST_ONLY"],
    "evidence_refs": ["synthetic-fixture"],
    "purpose": "展示本地 viewer 字段映射",
    "body_text": "合成演示正文：这不对应真实文章。",
    "body_sha256": "431f0da85904cf07906c361da05f94f6ceda780fcf387f95aab171e6b7ee8a49"
  }]
}
```

上例只用于读字段，包含的 URL/正文均为合成测试值，不能拿去发起捕获请求。真实签收文件应引用真实审核证据并由有权审查者明确签名。

每个 `records` 项须有唯一 `record_id`、标题/账号/原 URL、原始 `body_text`、其 UTF-8 `body_sha256`、`reference_status`、`Q`、理由、`reason_codes`、`evidence_refs`、作者声明验证状态与显式布尔值 `counts_toward_target`。签收 ID 集合须与 records 完全相同；PASS 要有 Q≥3.5；NEEDS/EXCLUDE 不可计数。`as_of` 必须是带时区 ISO 时间，供 viewer 复算时效显示。

`render-signed` 会校验这些字段及正文哈希，并把已签记录作为展示工作区；它不会判断签字真实性、重审内容或改变任何状态。签收文件/正文仍应由使用者按来源保存规则妥善保管。
