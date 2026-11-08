#!/usr/bin/env python3
"""Public Workbench local workflow CLI. No command modifies the production library."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT=Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0,str(PACKAGE_ROOT))

from collectors.workflow import (StopBatch, capture_run, discover_feed, ensure_private_workspace,
                                 materialize_signed_workspace, new_run, validate_public_url)
from collectors.datax_fallback import datax_once_from_preflight, datax_check_original_receipt, prepare_docs


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    discover=sub.add_parser("discover",help="从用户URL建候选，或一次读取Appinn/SSPai RSS")
    discover.add_argument("--workspace",required=True)
    discover.add_argument("--run-id",required=True)
    group=discover.add_mutually_exclusive_group(required=True)
    group.add_argument("--url",action="append",help="重复多次，最多20个文章URL；仅记元数据，不请求文章")
    group.add_argument("--feed",help="Appinn/SSPai HTTPS RSS/Atom URL；仅单次读取Feed")
    capture=sub.add_parser("capture",help="顺序获取唯一新URL；首错持久STOP、零重试")
    capture.add_argument("--workspace",required=True)
    capture.add_argument("--run-id",required=True)
    signed=sub.add_parser("render-signed",help="从显式SIGNED结构化签收生成只读viewer工作区")
    signed.add_argument("--acceptance",required=True)
    signed.add_argument("--output",required=True)
    datax=sub.add_parser("datax-once",help="满足当前官方证据与单次费用门禁后最多发一个DataX GET")
    datax.add_argument("--workspace",required=True)
    datax.add_argument("--preflight",required=True)
    datax.add_argument("--docs-dir",help="prepare-docs生成的本地官方合同缓存目录；也可设环境变量PUBLIC_WORKBENCH_DATAX_DOCS_DIR")
    datax.add_argument("--operation",choices=["list","get"],required=True)
    datax.add_argument("--params-json",required=True)
    datax.add_argument("--confirm-paid-transfer",action="store_true")
    datax_receipt=sub.add_parser("datax-check-receipt",help="只查原请求回执一次，不重发原请求")
    datax_receipt.add_argument("--workspace",required=True)
    datax_receipt.add_argument("--receipt",required=True,help="workspace内原始datax-receipts/*.json相对路径")
    docs=sub.add_parser("prepare-docs",help="一次读取三份固定官方文档并与已审核原文SHA比较；不查账户、不收费")
    docs.add_argument("--cache-dir",required=True,help="新的本地docs缓存目录，不覆盖已有非空目录")
    args=parser.parse_args(argv)
    try:
        if args.command=="discover":
            workspace=ensure_private_workspace(args.workspace)
            if args.feed:
                result=discover_feed(workspace,args.run_id,args.feed)
            else:
                if len(args.url)>20:raise ValueError("maximum 20 URLs per batch")
                rows=[]
                for value in args.url:
                    url,_=validate_public_url(value)
                    rows.append({"url":url,"title":""})
                run_dir=new_run(workspace,args.run_id,rows)
                result={"run_id":args.run_id,"candidate_count":len(rows),
                        "metadata_file":(run_dir/"metadata-candidates.json").relative_to(workspace).as_posix(),
                        "article_requests":0}
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if args.command=="capture":
            workspace=ensure_private_workspace(args.workspace)
            result=capture_run(workspace,args.run_id)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 2 if result["state"]=="STOPPED" else 0
        if args.command=="render-signed":
            source=Path(args.acceptance).expanduser().resolve()
            output=Path(args.output).expanduser()
            result=materialize_signed_workspace(source,output)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if args.command=="datax-once":
            workspace=ensure_private_workspace(args.workspace)
            params=json.loads(args.params_json)
            if not isinstance(params,dict):raise ValueError("params-json must be an object")
            result=datax_once_from_preflight(workspace,Path(args.preflight),args.operation,params,
                                             explicit_confirmation=args.confirm_paid_transfer,
                                             docs_dir=Path(args.docs_dir) if args.docs_dir else None)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get("success") else 2
        if args.command=="datax-check-receipt":
            workspace=ensure_private_workspace(args.workspace)
            result=datax_check_original_receipt(workspace,args.receipt)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 0 if result.get("state")=="RESOLVED" else 2
        if args.command=="prepare-docs":
            result=prepare_docs(Path(args.cache_dir))
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except StopBatch as error:
        print(json.dumps({"state":"STOPPED","reason":error.reason,"retry":"NONE"},ensure_ascii=False),file=sys.stderr)
        return 2
    except Exception as error:
        print(json.dumps({"state":"BLOCKED","reason":type(error).__name__,"message":str(error)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 2


if __name__=="__main__":
    raise SystemExit(main())
