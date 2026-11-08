# 第一份参考资料：完整离线例子

这个例子演示“填好的签收输入→校验→生成阅读工作区”。没有联网采集、付费调用或真实质量审核；签收身份和正文均为合成测试值，不计入任何真实合格目标。

## 1. 先准备仓库

按[首页](../README.md#先把界面跑起来)下载或克隆后，进入包含app和collectors的目录。输入文件已填好：[examples/synthetic-acceptance.json](../examples/synthetic-acceptance.json)。不用先学JSON字段或填写空表。

## 2. 生成新工作区

以下命令适用于macOS/Linux终端；Windows可在兼容shell运行，其他Windows环境未在本轮验收。

```sh
python3 collectors/cli.py render-signed \
  --acceptance examples/synthetic-acceptance.json \
  --output ../my-first-reference-demo
```

输出应包含 `destination_created: true`、`records: 1`、`decisions_recomputed: false`。这表示保留了输入的演示状态，不表示软件重新评价文章质量。

如果输出目录已经存在，程序会拒绝覆盖；改用新的目录名，不删除既有资料。

## 3. 打开生成的工作区

```sh
PUBLIC_WORKBENCH_DATA_DIR=../my-first-reference-demo python3 app/server.py --port 8791
```

打开 http://127.0.0.1:8791/ ，应看到一条标题带“合成示例”的记录。预期正文包含填写完整的事项、负责人、期限和验收条件。若页面无法加载，请保留终端报错，并在反馈中提供系统、Python版本、访问地址和脱敏输出。

## 4. 观察产生了什么

| 文件 | 用途 |
|---|---|
| digital_life_catalog.csv | 文章名录 |
| reference.sqlite3 | 只读阅读所用的正文与记录 |
| approved.json | 原样物化的演示签收资格 |
| media/manifest.json | 演示媒体登记；本例为空 |

原输入JSON包含正文SHA；生成器核对它。你修改body_text但不更新hash会被拒绝；不要用更新hash掩盖真实内容被改写，真实资料需重新审核。

## 5. 换成真实文章前

先读[审查规则](../collectors/REVIEW-WORKFLOW.md)，真实保存原始页面、正文、回执和审查依据。复制合成PASS或合成reviewer到真实文章，不构成审核。本例只降低字段学习成本，不降低真实准入标准。
