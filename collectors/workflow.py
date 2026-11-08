"""Offline-testable, single-attempt public-source capture workflow."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager, closing

from .native_adapters import parse_page, source_family
from .subscription_gate import SubscriptionLockDetected

MAX_BATCH = 20
MAX_RESPONSE_BYTES = 15 * 1024 * 1024
TIMEOUT_SECONDS = 30
SECRET_QUERY_NAMES = {"token", "pass_ticket", "auth", "authorization", "session", "sessionid", "cookie", "access_token"}
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


class StopBatch(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def ensure_private_workspace(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if root == PACKAGE_ROOT or PACKAGE_ROOT in root.parents:
        raise ValueError("raw captures must be written outside the public package")
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_public_url(value: str, *, feed: bool = False) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(value.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if (parts.scheme.lower() != "https" or parts.username or parts.password or
            not parts.hostname or parts.fragment):
        raise ValueError("URL must be HTTPS, have no credentials, and contain no fragment")
    if host not in {"appinn.com", "sspai.com"}:
        raise ValueError("only appinn.com and sspai.com public URLs are supported")
    query_names = {k.lower() for k, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)}
    if query_names & SECRET_QUERY_NAMES:
        raise ValueError("sensitive session query parameter refused")
    if feed:
        return value.strip(), host
    family = source_family(value)
    return value.strip(), family


def normalized_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    path = re.sub(r"/{2,}", "/", parts.path or "/").rstrip("/") or "/"
    query = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True)))
    return urllib.parse.urlunsplit((parts.scheme.lower(), host + port, path, query, ""))


def page_identity(value: str, family: str) -> str:
    parts = urllib.parse.urlsplit(value)
    if family == "sspai":
        match = re.fullmatch(r"/post/(\d+)/?", parts.path)
        if match:
            return "sspai-post:" + match.group(1)
    return "url-sha256:" + sha256(normalized_url(value).encode("utf-8"))


def _empty_ledger() -> dict:
    return {"schema": "public-workbench-attempt-ledger/v1", "attempts": {}, "aliases": {}}


def read_ledger(workspace: Path) -> dict:
    path = workspace / "state" / "attempt-ledger.json"
    if not path.exists():
        return _empty_ledger()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "public-workbench-attempt-ledger/v1" or not isinstance(data.get("attempts"), dict):
        raise ValueError("attempt ledger invalid; fail closed")
    data.setdefault("aliases", {})
    return data


def save_ledger(workspace: Path, ledger: dict) -> None:
    atomic_json(workspace / "state" / "attempt-ledger.json", ledger)


@contextmanager
def _ledger_lock(workspace: Path):
    lock_path = workspace / "state" / "attempt-ledger.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        else:
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _attempt_keys(url: str, family: str) -> list[str]:
    return ["url:" + sha256(normalized_url(url).encode()), "page:" + page_identity(url, family)]


def _seen(ledger: dict, keys: list[str]) -> str | None:
    for key in keys:
        if key in ledger["attempts"] or key in ledger["aliases"]:
            return key
    return None


def _safe_run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value):
        raise ValueError("run-id must be 1-64 ASCII letters, digits, dot, underscore or hyphen")
    return value


def new_run(workspace: Path, run_id: str, rows: list[dict], discovery: dict | None = None) -> Path:
    workspace = Path(workspace).expanduser().resolve()
    run_id = _safe_run_id(run_id)
    if not 0 < len(rows) <= MAX_BATCH:
        raise ValueError(f"a batch must contain 1-{MAX_BATCH} unique candidates")
    run_dir = workspace / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    ledger = read_ledger(workspace)
    seen_in_batch: set[str] = set()
    records = []
    for index, row in enumerate(rows):
        url, family = validate_public_url(row["url"])
        keys = _attempt_keys(url, family)
        identity = page_identity(url, family)
        duplicate_in_batch = identity in seen_in_batch or keys[0] in seen_in_batch
        seen_in_batch.update([identity, keys[0]])
        previous = _seen(ledger, keys)
        records.append({
            "candidate_index": index,
            "url_observed": url,
            "normalized_url": normalized_url(url),
            "publisher": family,
            "page_identity": identity,
            "attempt_keys": keys,
            "title_observed": str(row.get("title") or "")[:500],
            "feed_date_observed_unverified": str(row.get("feed_date") or "")[:128],
            "discovery_source": discovery or {"kind": "user_url"},
            "status": "DUPLICATE_IN_BATCH" if duplicate_in_batch else "PREVIOUSLY_ATTEMPTED" if previous else "METADATA_CANDIDATE",
            "prior_identity_key": previous,
            "request_count_this_run": 0,
            "publication_time": None,
        })
    atomic_json(run_dir / "metadata-candidates.json", {
        "schema": "public-workbench-metadata-candidates/v1",
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "records": records,
        "qualification": "NOT_REVIEWED",
    })
    atomic_json(run_dir / "run-manifest.json", {
        "schema": "public-workbench-run/v1", "run_id": run_id, "state": "DISCOVERED",
        "created_at_utc": utc_now(), "stop": None, "request_order": [],
        "unattempted_indices": [r["candidate_index"] for r in records if r["status"] == "METADATA_CANDIDATE"],
    })
    return run_dir


def parse_feed(raw: bytes, feed_url: str) -> list[dict]:
    root = ET.fromstring(raw)
    rows = []
    for node in root.iter():
        local = node.tag.rsplit("}", 1)[-1].lower()
        if local not in {"item", "entry"}:
            continue
        title = next(((x.text or "").strip() for x in node if x.tag.rsplit("}", 1)[-1].lower() == "title"), "")
        link = ""
        date = ""
        for child in node:
            name = child.tag.rsplit("}", 1)[-1].lower()
            if name == "link":
                link = child.attrib.get("href") or (child.text or "").strip()
                if child.attrib.get("rel") in {None, "alternate"} and link:
                    break
            elif name in {"pubdate", "published", "updated"} and not date:
                date = (child.text or "").strip()
        if link:
            rows.append({"url": urllib.parse.urljoin(feed_url, link), "title": title, "feed_date": date})
    return rows


def discover_feed(workspace: Path, run_id: str, feed_url: str, transport=None) -> dict:
    """Fetch one supplied Appinn/SSPai feed once, then create metadata candidates."""
    if transport is None:
        transport = request_once
    run_id = _safe_run_id(run_id)
    feed_url, host = validate_public_url(feed_url, feed=True)
    workspace = ensure_private_workspace(workspace)
    if (workspace/"runs"/run_id).exists(): raise FileExistsError("run id already exists; refusing overwrite before feed request")
    feed_key = "feed:" + sha256(normalized_url(feed_url).encode())
    with _ledger_lock(workspace):
        ledger = read_ledger(workspace)
        if _seen(ledger, [feed_key]):
            raise StopBatch("FEED_ALREADY_ATTEMPTED_NO_RETRY")
        ledger["attempts"][feed_key] = {"run_id":run_id,"status":"STARTED_NO_RETRY",
            "requested_url_sha256":sha256(normalized_url(feed_url).encode()),"started_at_utc":utc_now()}
        save_ledger(workspace,ledger)
    folder=workspace/"discovery"/("feed-"+feed_key[-16:])
    folder.mkdir(parents=True,exist_ok=False)
    receipt_path=folder/"fetch-receipt.json"
    receipt={"schema":"public-workbench-feed-receipt/v1","run_id":run_id,"requested_url":feed_url,
        "attempt_number":1,"retry_count":0,"redirect_followed":False,"proxy_configured":False,
        "custom_user_agent":False,"cookie_sent":False,"request_started_at_utc":utc_now()}
    atomic_json(receipt_path,receipt)
    response=transport(feed_url,cap=5*1024*1024)
    raw=response.get("body",b"")
    raw_path=folder/"feed.xml"
    if raw:raw_path.write_bytes(raw)
    receipt.update({"request_finished_at_utc":utc_now(),"http_status":response.get("http_status"),
        "final_url":response.get("final_url"),"content_type":response.get("content_type"),
        "response_complete":bool(response.get("response_complete")),"source_sha256":sha256(raw) if raw else None,
        "source_bytes":len(raw),"source_path":raw_path.relative_to(workspace).as_posix() if raw else None,
        "transport_error":response.get("transport_error")})
    reason=None
    if response.get("transport_error"):reason="TRANSPORT_"+response["transport_error"]
    elif response.get("http_status")!=200:reason="HTTP_NOT_200_OR_REDIRECT"
    elif response.get("final_url")!=feed_url:reason="FINAL_URL_CHANGED"
    elif not response.get("response_complete") or len(raw)>5*1024*1024:reason="FEED_INCOMPLETE_OR_TOO_LARGE"
    elif not raw.lstrip().startswith((b"<?xml",b"<rss",b"<feed")):reason="NOT_XML_FEED"
    candidates=[]
    if reason is None:
        try:
            observed=parse_feed(raw,feed_url)
            valid=[]
            seen=set()
            for item in observed:
                try:
                    url,family=validate_public_url(item["url"])
                except ValueError:
                    continue
                ident=page_identity(url,family)
                if ident not in seen:
                    seen.add(ident);valid.append(item)
            candidates=valid[:MAX_BATCH]
            if not candidates:reason="NO_SUPPORTED_ARTICLE_URLS_IN_FEED"
        except Exception as error:
            reason="FEED_PARSE_"+type(error).__name__
    if reason:
        receipt.update({"result":"STOPPED","stop_reason":reason,"retry_count":0})
        atomic_json(receipt_path,receipt)
        with _ledger_lock(workspace):
            ledger=read_ledger(workspace)
            ledger["attempts"][feed_key].update({"status":"FAILED_NO_RETRY","finished_at_utc":utc_now(),
                "receipt_path":receipt_path.relative_to(workspace).as_posix()})
            save_ledger(workspace,ledger)
        raise StopBatch(reason)
    run_dir=new_run(workspace,run_id,candidates,{"kind":"rss","feed_url":feed_url,
        "feed_sha256":sha256(raw),"feed_date_is_unverified":True})
    metadata_path=run_dir/"metadata-candidates.json"
    metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["feed_receipt"]={"path":receipt_path.relative_to(workspace).as_posix(),"sha256":sha256(receipt_path.read_bytes())}
    metadata["feed_items_observed"] = len(observed)
    metadata["supported_unique_items"] = len(candidates)
    metadata["beyond_batch_limit_unselected"] = max(0,len(valid)-MAX_BATCH)
    atomic_json(metadata_path,metadata)
    receipt.update({"result":"DISCOVERED_METADATA_CANDIDATES","run_id":run_id,"candidate_count":len(candidates)})
    atomic_json(receipt_path,receipt)
    with _ledger_lock(workspace):
        ledger=read_ledger(workspace)
        ledger["attempts"][feed_key].update({"status":"SUCCEEDED_NO_RETRY","finished_at_utc":utc_now(),
            "receipt_path":receipt_path.relative_to(workspace).as_posix(),"source_sha256":sha256(raw)})
        save_ledger(workspace,ledger)
    return {"run_id":run_id,"candidate_count":len(candidates),"metadata_file":metadata_path.relative_to(workspace).as_posix(),
            "feed_sha256":sha256(raw),"unselected_over_20":max(0,len(valid)-MAX_BATCH)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_response(response, cap: int) -> tuple[bytes, bool]:
    chunks, total = [], 0
    while total <= cap:
        chunk = response.read(min(65536, cap + 1 - total))
        if not chunk:
            return b"".join(chunks), True
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), False


def request_once(url: str, *, cap: int = MAX_RESPONSE_BYTES, timeout: int = TIMEOUT_SECONDS) -> dict:
    """One direct HTTPS GET. No proxy, custom headers, cookies, or redirects."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, method="GET")
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body, complete = _read_response(response, cap)
            status = getattr(response, "status", None)
            if status is None:
                status = getattr(response, "code", None)
            return {"http_status": status,
                    "final_url": response.geturl(),
                    "content_type": response.headers.get("Content-Type", ""),
                    "headers": {k: response.headers.get(k) for k in ("Content-Length", "ETag", "Last-Modified", "Location") if response.headers.get(k)},
                    "body": body, "response_complete": complete, "transport_error": None}
    except Exception as error:
        return {"http_status": None, "final_url": None, "content_type": "", "headers": {}, "body": b"",
                "response_complete": False, "transport_error": type(error).__name__}


def _attempt_record(workspace: Path, record: dict, run_id: str, receipt_path: Path) -> None:
    with _ledger_lock(workspace):
        ledger = read_ledger(workspace)
        keys = record["attempt_keys"]
        if _seen(ledger, keys):
            raise StopBatch("IDENTITY_ALREADY_ATTEMPTED")
        started = {"run_id": run_id, "url_identity": keys[0], "page_identity": keys[1],
                   "requested_url_sha256": sha256(record["normalized_url"].encode()),
                   "status": "STARTED_NO_RETRY", "started_at_utc": utc_now(),
                   "receipt_path": receipt_path.relative_to(workspace).as_posix()}
        for key in keys:
            ledger["attempts"][key] = started.copy()
        save_ledger(workspace, ledger)


def _finish_attempt(workspace: Path, record: dict, status: str, receipt: dict, canonical: str | None = None) -> None:
    with _ledger_lock(workspace):
        ledger = read_ledger(workspace)
        for key in record["attempt_keys"]:
            entry = ledger["attempts"].setdefault(key, {})
            entry.update(status=status, finished_at_utc=utc_now(), receipt_sha256=sha256((json.dumps(receipt, ensure_ascii=False, indent=2)+"\n").encode()))
        if canonical:
            family = record["publisher"]
            for alias in _attempt_keys(canonical, family):
                ledger["aliases"][alias] = {"status": status, "canonical_of": record["attempt_keys"][0], "run_id": record["run_id"]}
        save_ledger(workspace, ledger)


def capture_run(workspace: Path, run_id: str, transport=request_once) -> dict:
    workspace = Path(workspace).expanduser().resolve()
    run_id = _safe_run_id(run_id)
    run_dir = workspace / "runs" / run_id
    meta_path, manifest_path = run_dir / "metadata-candidates.json", run_dir / "run-manifest.json"
    if not run_dir.is_dir() or not meta_path.is_file() or not manifest_path.is_file():
        raise ValueError("run not found or incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("state") != "DISCOVERED":
        raise ValueError("run is not in DISCOVERED state; reruns are blocked")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    records = metadata["records"]
    manifest["state"] = "CAPTURING"
    atomic_json(manifest_path, manifest)
    pending = {"schema": "public-workbench-pending-review/v1", "run_id": run_id,
               "created_at_utc": utc_now(), "qualification": "PENDING_INDEPENDENT_REVIEW", "records": []}
    for index, record in enumerate(records):
        if record["status"] != "METADATA_CANDIDATE":
            continue
        workspace_root = workspace.resolve()
        run_root = run_dir.resolve()
        folder = run_root / ("article-" + record["page_identity"].replace(":", "-").replace("/", "-")[-48:])
        folder.mkdir(parents=True, exist_ok=False)
        receipt_path = folder / "fetch-receipt.json"
        record["run_id"] = run_id
        receipt = {"schema":"public-workbench-fetch-receipt/v1", "run_id":run_id,
                   "requested_url":record["url_observed"], "attempt_number":1,
                   "retry_count":0, "redirect_followed":False, "proxy_configured":False,
                   "custom_user_agent":False, "cookie_sent":False, "request_headers":{},
                   "request_started_at_utc":utc_now(), "response_complete":False,
                   "qualification":"NOT_EVALUATED"}
        atomic_json(receipt_path, receipt)
        try:
            _attempt_record(workspace, record, run_id, receipt_path)
        except StopBatch:
            record["status"]="PREVIOUSLY_ATTEMPTED"
            record["request_count_this_run"]=0
            receipt.update({"result":"SKIPPED_PRIOR_ATTEMPT","retry_count":0,"receipt_finalized_at_utc":utc_now()})
            atomic_json(receipt_path,receipt)
            manifest["unattempted_indices"].remove(index)
            metadata["records"][index]=record
            atomic_json(meta_path,metadata)
            atomic_json(manifest_path,manifest)
            continue
        record["request_count_this_run"] = 1
        manifest["request_order"].append(index)
        manifest["unattempted_indices"].remove(index)
        atomic_json(manifest_path, manifest)
        try:
            response = transport(record["url_observed"])
            raw = response.get("body", b"")
            raw_path = folder / "source.html"
            if raw:
                raw_path.write_bytes(raw)
            receipt.update({"request_finished_at_utc":utc_now(), "http_status":response.get("http_status"),
                            "content_type":response.get("content_type"), "response_headers":response.get("headers", {}),
                            "final_url":response.get("final_url"), "source_html_path":raw_path.relative_to(workspace).as_posix() if raw else None,
                            "source_html_sha256":sha256(raw) if raw else None, "source_html_bytes":len(raw),
                            "response_complete":bool(response.get("response_complete")),
                            "transport_error":response.get("transport_error"), "retry_count":0})
            atomic_json(receipt_path, receipt)
            if response.get("transport_error"):
                raise StopBatch("TRANSPORT_" + response["transport_error"])
            if response.get("http_status") != 200:
                raise StopBatch("HTTP_NOT_200_OR_REDIRECT")
            if response.get("final_url") != record["url_observed"]:
                raise StopBatch("FINAL_URL_CHANGED")
            if not response.get("response_complete") or len(raw) > MAX_RESPONSE_BYTES:
                raise StopBatch("RESPONSE_INCOMPLETE_OR_TOO_LARGE")
            if "html" not in str(response.get("content_type", "")).lower():
                raise StopBatch("NON_HTML_RESPONSE")
            # parse_page runs the full-response subscription guard before parsing.
            extracted = parse_page(record["url_observed"], raw)
            body = extracted["body_text"].encode("utf-8")
            body_path = folder / "body.txt"
            body_path.write_bytes(body)
            extraction = {k:v for k,v in extracted.items() if k != "body_text"}
            extraction.update({"source_html_sha256":sha256(raw), "body_sha256":sha256(body),
                               "body_file":"body.txt", "body_bytes":len(body),
                               "response_complete":True, "qualification":"PENDING_INDEPENDENT_REVIEW"})
            extraction_path = folder / "extraction.json"
            atomic_json(extraction_path, extraction)
            receipt.update({"result":"CAPTURED_PENDING_REVIEW", "body_sha256":sha256(body),
                            "extraction_sha256":sha256(extraction_path.read_bytes()),
                            "receipt_finalized_at_utc":utc_now()})
            atomic_json(receipt_path, receipt)
            record.update(status="CAPTURED_PENDING_REVIEW", capture_folder=folder.relative_to(workspace).as_posix(),
                           title_page=extracted["title"], author_evidence=extracted["author_evidence"],
                           publication_time=extracted["published_at"], source_html_sha256=sha256(raw), body_sha256=sha256(body))
            pending["records"].append({"candidate_index":index, "publisher":record["publisher"],
                "url":record["url_observed"], "title_observed":record["title_observed"],
                "title_page":extracted["title"], "author_evidence":extracted["author_evidence"],
                "published_at":extracted["published_at"], "body_sha256":sha256(body),
                "source_html_sha256":sha256(raw), "review_status":"PENDING_INDEPENDENT_REVIEW",
                "capture_folder":folder.relative_to(workspace).as_posix(),
                "Q":None,"counts_toward_target":False})
            _finish_attempt(workspace, record, "SUCCEEDED_NO_RETRY", receipt, extracted["canonical_url"])
        except Exception as error:
            reason = error.reason if isinstance(error, StopBatch) else "GUARD_OR_EXTRACTION_" + type(error).__name__
            if isinstance(error, SubscriptionLockDetected): reason = "FULL_RESPONSE_SUBSCRIPTION_LOCK"
            receipt.update({"result":"STOPPED", "stop_reason":reason, "retry_count":0,
                            "receipt_finalized_at_utc":utc_now()})
            atomic_json(receipt_path, receipt)
            record.update(status="STOPPED", stop_reason=reason,
                          source_html_sha256=receipt.get("source_html_sha256"))
            _finish_attempt(workspace, record, "FAILED_NO_RETRY", receipt)
            manifest.update(state="STOPPED", stop={"candidate_index":index,"reason":reason,"retry":"NONE"})
            break
        metadata["records"][index] = record
        atomic_json(meta_path, metadata)
        atomic_json(manifest_path, manifest)
    metadata["records"] = records
    atomic_json(meta_path, metadata)
    if manifest["state"] == "CAPTURING": manifest["state"] = "CAPTURED_OR_SKIPPED"
    manifest["completed_count"] = len(pending["records"])
    manifest["qualification"] = "PENDING_INDEPENDENT_REVIEW"
    atomic_json(manifest_path, manifest)
    atomic_json(run_dir / "pending-review.json", pending)
    return {"run_id":run_id,"state":manifest["state"],"captured":len(pending["records"]),
            "stop":manifest.get("stop"),"pending_review_file":"pending-review.json"}


def load_signed_records(path: Path) -> list[dict]:
    data=json.loads(path.read_text(encoding="utf-8"))
    signoff=data.get("signoff",{})
    if data.get("schema")!="public-workbench-signed-acceptance/v1" or signoff.get("status")!="SIGNED":
        raise ValueError("requires a structured SIGNED acceptance record")
    if not signoff.get("reviewer") or not signoff.get("signed_at"):
        raise ValueError("signoff reviewer and signed_at are required")
    if not signoff.get("as_of"):
        raise ValueError("signoff as_of timestamp is required for deterministic viewer recency")
    try:
        parsed_as_of = datetime.fromisoformat(str(signoff["as_of"]).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("signoff as_of must be ISO datetime with timezone") from error
    if parsed_as_of.tzinfo is None:
        raise ValueError("signoff as_of must include timezone")
    ids=set(signoff.get("record_ids",[]))
    rows=data.get("records")
    if not isinstance(rows,list) or not rows or not 1<=len(rows)<=1000:
        raise ValueError("signed acceptance must contain 1-1000 records")
    seen=set()
    for row in rows:
        if row.get("record_id") not in ids or row["record_id"] in seen:
            raise ValueError("record ids must be unique and covered by explicit signoff")
        seen.add(row["record_id"])
        if row.get("reference_status") not in {"PASS","NEEDS_EVIDENCE","EXCLUDE"}:
            raise ValueError("signoff record has an unsupported reference status")
        if type(row.get("counts_toward_target")) is not bool:
            raise ValueError("counts_toward_target must be an explicit signed boolean")
        if row["counts_toward_target"] and row["reference_status"]!="PASS":
            raise ValueError("only explicitly signed PASS records may count")
        body=row.get("body_text")
        digest=row.get("body_sha256")
        if not isinstance(body,str) or not re.fullmatch(r"[0-9a-f]{64}",str(digest)) or sha256(body.encode())!=digest:
            raise ValueError("signed body hash mismatch")
        if row.get("reference_status")=="PASS" and (not isinstance(row.get("Q"),(int,float)) or row["Q"]<3.5):
            raise ValueError("signed PASS Q must be at least 3.5")
    if seen != ids:
        raise ValueError("signoff record_ids must exactly match included records")
    return rows


def materialize_signed_workspace(signoff_path: Path, destination: Path) -> dict:
    """Materialize an already-signed structure; never scores or changes decisions."""
    signoff = json.loads(signoff_path.read_text(encoding="utf-8"))["signoff"]
    rows=load_signed_records(signoff_path)
    destination=destination.expanduser().resolve()
    if destination.exists(): raise FileExistsError("destination exists; refusing overwrite")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="public-workbench-export-",dir=destination.parent) as temp:
        root=Path(temp)/"workspace"
        (root/"media"/"assets").mkdir(parents=True)
        fields=["record_id","account_name","account_id","topic_id","title","article_url_clean","published_at",
                "time_window_as_of_2026-11-06","quality_score_0_to_5","recency_multiplier","recency_weighted_score",
                "metadata_state","source_request_id","source_response_file","url_normalization","body_hash"]
        import csv, sqlite3
        with (root/"digital_life_catalog.csv").open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
            for r in rows:
                writer.writerow({"record_id":r["record_id"],"account_name":r.get("account_name",r.get("account","")),
                    "account_id":r.get("account_id","synthetic-or-signed"),"topic_id":r.get("topic_id","C08"),
                    "title":r["title"],"article_url_clean":r.get("source_url",""),"published_at":r.get("published_at") or "",
                    "time_window_as_of_2026-11-06":r.get("time_window_as_of_2026-11-06",""),
                    "quality_score_0_to_5":r.get("Q"),"recency_multiplier":r.get("recency_multiplier"),
                    "recency_weighted_score":r.get("recency_weighted_score"),"metadata_state":"SIGNED_PRESENTATION_ONLY",
                    "source_request_id":r.get("source_request_id","signed-acceptance"),
                    "source_response_file":"signed-acceptance.json","url_normalization":"signed-input",
                    "body_hash":r["body_sha256"]})
        (root/"ledger.csv").write_text("article_identity,account_name,title,published_at,target_status,topic_id,topic,internal_quality_score_0_to_5,body_sha256\n",encoding="utf-8-sig")
        (root/"research-notes.json").write_text('{"dataset_notice":"SIGNED INPUT; LOCAL VIEW ONLY","notes":{}}\n',encoding="utf-8")
        (root/"media"/"manifest.json").write_text('{"version":"1.0","articles":{}}\n',encoding="utf-8")
        approved={"schema":"signed-presentation-approvals/v1","dataset_notice":"Materialized only from explicit SIGNED input; no quality decisions added.","records":[]}
        with closing(sqlite3.connect(root/"reference.sqlite3")) as db:
            db.executescript("CREATE TABLE collector_articles(record_id TEXT PRIMARY KEY, identity TEXT, title TEXT, account TEXT, published_at TEXT, status TEXT, body_hash TEXT, error_category TEXT, error_message TEXT, source TEXT, is_new INTEGER, updated_at TEXT, as_of TEXT); CREATE TABLE public_article_bodies(url TEXT NOT NULL, body_sha256 TEXT NOT NULL, account_name TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, source_file TEXT NOT NULL, fetched_at TEXT NOT NULL, collector TEXT NOT NULL, PRIMARY KEY(url,body_sha256));")
            for r in rows:
                url=r.get("source_url","")
                db.execute("INSERT INTO collector_articles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["record_id"],url,r["title"],r.get("account_name",r.get("account","")),r.get("published_at"),
                     "accepted",r["body_sha256"],"","","signed-acceptance",1,
                     r.get("signed_at") or signoff["signed_at"],r.get("recency_as_of") or signoff["as_of"]))
                db.execute("INSERT INTO public_article_bodies VALUES(?,?,?,?,?,?,?,?)",
                    (url,r["body_sha256"],r.get("account_name",r.get("account","")),r["title"],r["body_text"],
                     "signed-acceptance.json",r.get("signed_at",""),"Publisher-native public HTML; not WeChat original; internal reference pending review"))
                approved["records"].append({"record_id":r["record_id"],"body_hash":r["body_sha256"],
                    "reference_status":r["reference_status"],"Q":r.get("Q"),"reason_codes":r.get("reason_codes",["SIGNED_PRESENTATION_ONLY"]),
                    "reason":r.get("reason","Signed status preserved as provided."),"purpose":r.get("purpose",""),
                    "claim_verification":r.get("claim_verification","SOURCE_REPORTED"),
                    "counts_toward_target":r["counts_toward_target"],"evidence_refs":r.get("evidence_refs",[])})
            db.commit()
        (root/"approved.json").write_text(json.dumps(approved,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (root/"ledger.csv").write_text("article_identity,account_name,title,published_at,target_status,topic_id,topic,internal_quality_score_0_to_5,body_sha256\n",encoding="utf-8-sig")
        os.replace(root,destination)
    return {"destination_created":True,"records":len(rows),"input_signoff_sha256":sha256(signoff_path.read_bytes()),
            "decisions_recomputed":False,"counts_changed":False}
