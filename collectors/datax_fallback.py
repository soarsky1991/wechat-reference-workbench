"""Single-call DataXAPI fallback guarded by pinned public docs and live local evidence.

This module deliberately does not create runs or refresh balance/run state. The caller
must supply current, hashed readbacks and explicitly authorize one bounded GET.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

BASE_URL = "https://api.dataxapi.com"
DOCS_ROOT = (Path(os.environ["PUBLIC_WORKBENCH_DATAX_DOCS_DIR"]).expanduser().resolve()
             if os.environ.get("PUBLIC_WORKBENCH_DATAX_DOCS_DIR") else None)
EXPECTED_DOC_SHA = {
    "agents.md": "4a51542489503a9d3e286ffb8c37092b71299929b69d93e7fbb08f40b459eb74",
    "openapi.json": "82cad987f238f7e782df92872c9f9f7121bcfc55fb654543b441d42db9487765",
    "prices.json": "9742e226e7ca32eed3db92eba8d6020183af5d0369f7596c27fad65e9c2a29a4",
}
EXPECTED_CATALOG_REVISION = "3efbf7080dda485f"
EXPECTED_PRICEBOOK_VERSION = "12"
OFFICIAL_DOC_URLS = {
    "agents.md": "https://dataxapi.com/agents.md",
    "openapi.json": "https://dataxapi.com/openapi.json",
    "prices.json": "https://dataxapi.com/prices.json",
}
ALLOWED = {
    "list": ("/v1/wechat_mp/accounts/articles/list", "wechat_mp.accounts.articles.list"),
    "get": ("/v1/wechat_mp/articles/get", "wechat_mp.articles.get"),
}
MAX_EVIDENCE_AGE_SECONDS = 6 * 60 * 60
MAX_RESPONSE_BYTES = 20 * 1024 * 1024


class DataXGateError(RuntimeError):
    """Preflight or settlement evidence is missing, stale, or inconsistent."""


class DataXStop(RuntimeError):
    """One request was attempted; stop without retry."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> tuple[dict, str]:
    raw = path.expanduser().resolve().read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise DataXGateError(f"expected JSON object: {path.name}")
    return value, sha256_bytes(raw)


def _dt(value: object) -> datetime:
    if not isinstance(value, str):
        raise DataXGateError("timestamp missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataXGateError("invalid timestamp") from exc
    if result.tzinfo is None:
        raise DataXGateError("timestamp must include timezone")
    return result.astimezone(timezone.utc)


def _freshness(ts: datetime, now: datetime, label: str) -> None:
    age = (now - ts).total_seconds()
    if age < -300 or age > MAX_EVIDENCE_AGE_SECONDS:
        raise DataXGateError(f"{label} evidence is future-dated or older than six hours")


def _decimal(value: object, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DataXGateError(f"invalid {label}") from exc
    if not number.is_finite() or number < 0:
        raise DataXGateError(f"invalid {label}")
    return number


def _success_billing_validation(payload: dict, cap: Decimal) -> tuple[dict, Decimal | None, str]:
    """Validate provider-reported successful-call billing before any result is staged."""
    meta = payload.get("meta")
    billing = meta.get("billing") if isinstance(meta, dict) else None
    if not isinstance(billing, dict):
        return {"status": "INVALID", "reason": "billing object missing or malformed"}, None, "SETTLEMENT_UNKNOWN_STOP"
    amount = billing.get("amount")
    currency = billing.get("currency")
    if type(amount) not in (str, int, float):  # bool is deliberately not a monetary number.
        return {"status": "INVALID", "reason": "billing amount missing or has an unsupported type"}, None, "SETTLEMENT_UNKNOWN_STOP"
    if type(amount) is int and amount.bit_length() > 220:
        return {"status": "INVALID", "reason": "billing amount exceeds the decimal input bound"}, None, "SETTLEMENT_UNKNOWN_STOP"
    try:
        amount_text = str(amount)
    except (ValueError, OverflowError):
        return {"status": "INVALID", "reason": "billing amount cannot be represented as a decimal"}, None, "SETTLEMENT_UNKNOWN_STOP"
    if len(amount_text) > 64 or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", amount_text):
        return {"status": "INVALID", "reason": "billing amount is not a bounded decimal"}, None, "SETTLEMENT_UNKNOWN_STOP"
    try:
        amount_decimal = _decimal(amount, "billing amount")
    except DataXGateError:
        return {"status": "INVALID", "reason": "billing amount is non-finite or negative"}, None, "SETTLEMENT_UNKNOWN_STOP"
    if (amount_decimal.adjusted() > 100 or amount_decimal.adjusted() < -100
            or abs(amount_decimal.as_tuple().exponent) > 100):
        return {"status": "INVALID", "reason": "billing amount exponent is outside the accepted range"}, None, "SETTLEMENT_UNKNOWN_STOP"
    if not isinstance(currency, str) or currency != "USD":
        return {"status": "INVALID", "amount_decimal": str(amount_decimal),
                "reason": "billing currency missing or not USD"}, None, "SETTLEMENT_UNKNOWN_STOP"
    if amount_decimal > cap:
        return {"status": "OVER_AUTHORIZED_CAP", "amount_decimal": str(amount_decimal),
                "currency": currency, "authorized_cap": str(cap),
                "reason": "provider-reported charge exceeds the authorized per-call cap"}, amount_decimal, "BILLING_OVER_CAP_STOP"
    return {"status": "VALID_WITHIN_CAP", "amount_decimal": str(amount_decimal),
            "currency": currency, "authorized_cap": str(cap)}, amount_decimal, "RESPONSE_RECORDED"


def safe_run_id(value: str) -> str:
    import uuid
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise DataXGateError("run_id must be a UUID from an existing run") from exc


def public_article_url(value: str) -> str:
    parts = urllib.parse.urlsplit(value)
    secret = {"token", "pass_ticket", "auth", "authorization", "session", "sessionid", "cookie", "access_token"}
    query_names = {name.lower() for name, _ in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)}
    if (parts.scheme != "https" or parts.hostname != "mp.weixin.qq.com" or parts.username or parts.password
            or parts.fragment or query_names & secret):
        raise DataXGateError("only a clean public HTTPS mp.weixin.qq.com URL is accepted")
    return value


def idempotency_key(run_id: str, endpoint: str, params: dict) -> str:
    """Keep the local probe's deterministic helper algorithm, bound to the exact input."""
    run_id = safe_run_id(run_id)
    payload = json.dumps([run_id, endpoint, sorted(params.items())], ensure_ascii=False, separators=(",", ":"))
    return "wechat-matrix-" + hashlib.sha256(payload.encode()).hexdigest()


def response_succeeded(status: int, payload: object) -> bool:
    return 200 <= status < 300 and isinstance(payload, dict) and payload.get("code") == "ok"


def _resolve_ref(openapi: dict, schema: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/components/parameters/"):
        raise DataXGateError("unsupported parameter reference in pinned OpenAPI")
    node: object = openapi
    for part in ref[2:].split("/"):
        node = node[part]
    if not isinstance(node, dict):
        raise DataXGateError("invalid parameter reference in pinned OpenAPI")
    return node


def _contract(operation: str, params: dict, openapi: dict, prices: dict) -> tuple[str, str, Decimal, dict]:
    if operation not in ALLOWED:
        raise DataXGateError("only documented list/get operations are allowed")
    path, op_id = ALLOWED[operation]
    op = openapi.get("paths", {}).get(path, {}).get("get")
    if not isinstance(op, dict) or op.get("operationId") != op_id:
        raise DataXGateError("pinned OpenAPI endpoint contract mismatch")
    params_spec = {}
    for entry in op.get("parameters", []):
        item = _resolve_ref(openapi, entry)
        if item.get("in") == "query":
            params_spec[item["name"]] = item
    required = {name for name, spec in params_spec.items() if spec.get("required")}
    if not required.issubset(params) or set(params) - set(params_spec):
        raise DataXGateError("query parameters do not match the pinned OpenAPI schema")
    for name, value in params.items():
        if not isinstance(value, str) or not value:
            raise DataXGateError(f"query parameter {name} must be a non-empty string")
        schema = params_spec[name].get("schema", {})
        if schema.get("type") != "string":
            raise DataXGateError(f"unsupported query parameter type for {name}")
        if schema.get("enum") and value not in schema["enum"]:
            raise DataXGateError(f"query parameter {name} is outside the documented enum")
        if schema.get("pattern") and re.fullmatch(schema["pattern"], value) is None:
            raise DataXGateError(f"query parameter {name} does not match the documented pattern")
        if schema.get("maxLength") is not None and len(value) > schema["maxLength"]:
            raise DataXGateError(f"query parameter {name} exceeds the documented length")
    if operation == "get":
        public_article_url(params["url"])
    price_entry = next((row for row in prices.get("endpoints", []) if row.get("path") == path and row.get("id") == op_id), None)
    pricing = op.get("x-capability", {}).get("pricing") or op.get("pricing")
    if not price_entry or not isinstance(pricing, dict):
        raise DataXGateError("endpoint price missing from the verified pricebook/OpenAPI")
    price = _decimal(price_entry.get("max_charge", price_entry.get("price")), "endpoint max charge")
    if price_entry.get("price") != pricing.get("price") or price_entry.get("max_charge") != pricing.get("max_charge"):
        raise DataXGateError("OpenAPI and pricebook endpoint prices disagree")
    return path, op_id, price, params_spec


def _validate_contract(agents: str, openapi: dict, prices: dict) -> None:
    if prices.get("revision") != EXPECTED_CATALOG_REVISION or prices.get("prices", {}).get("version") != EXPECTED_PRICEBOOK_VERSION:
        raise DataXGateError("official catalog/pricebook revision differs from the reviewed contract")
    if prices.get("base_url") != BASE_URL:
        raise DataXGateError("pricebook base URL differs from the reviewed contract")
    if "GET https://api.dataxapi.com/v1/account" not in agents and "/v1/account" not in agents:
        raise DataXGateError("agents document does not describe the reviewed account endpoint")
    if openapi.get("servers", [{}])[0].get("url") != BASE_URL:
        raise DataXGateError("OpenAPI server URL differs from the reviewed base URL")
    for operation, (path, op_id) in ALLOWED.items():
        op = openapi.get("paths", {}).get(path, {}).get("get", {})
        if op.get("operationId") != op_id:
            raise DataXGateError(f"OpenAPI operation changed: {operation}")
        price = next((row for row in prices.get("endpoints", []) if row.get("path") == path and row.get("id") == op_id), None)
        pricing = op.get("x-capability", {}).get("pricing") or op.get("pricing")
        if not isinstance(price, dict) or not isinstance(pricing, dict):
            raise DataXGateError(f"pricing schema missing for {operation}")
        for field in ("price", "max_charge", "charge_when_empty"):
            if price.get(field) != pricing.get(field):
                raise DataXGateError(f"OpenAPI/pricebook mismatch for {operation}.{field}")
        if operation == "get" and price.get("charge_when_not_found") != pricing.get("charge_when_not_found"):
            raise DataXGateError("OpenAPI/pricebook mismatch for get.charge_when_not_found")
        if operation == "get" and price.get("charge_when_not_found") != "0.02":
            raise DataXGateError("reviewed get not-found charge semantics changed")
        if operation == "list" and price.get("charge_when_empty") != "0.02":
            raise DataXGateError("reviewed list empty-result charge semantics changed")
        query = {item.get("name"): item for item in op.get("parameters", []) if item.get("in") == "query"}
        required_query = "url" if operation == "get" else "id"
        if (required_query not in query or not query[required_query].get("required")
                or query[required_query].get("schema", {}).get("type") != "string"):
            raise DataXGateError(f"required query schema changed for {operation}")
    run_post = openapi.get("paths", {}).get("/v1/runs", {}).get("post", {})
    run_schema = run_post.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    if not run_post.get("requestBody", {}).get("required") or not {"task_id", "task_revision", "max_amount", "max_calls"}.issubset(set(run_schema.get("required", []))):
        raise DataXGateError("run POST required request fields changed")
    ttl = run_schema.get("properties", {}).get("ttl_seconds", {})
    if ttl.get("minimum") != 60 or ttl.get("maximum") != 86400:
        raise DataXGateError("run ttl contract changed")
    params = openapi.get("components", {}).get("parameters", {})
    expected_header_patterns = {
        "Idempotency-Key": r"^[\x21-\x7e]{1,255}$",
        "X-Max-Price": r"^\d{1,7}(\.\d{1,6})?$",
        "X-Run-Step": r"^\d{1,6}$",
        "X-Run-Iteration": r"^\d{1,6}$",
    }
    for key, pattern in expected_header_patterns.items():
        if params.get(key, {}).get("schema", {}).get("pattern") != pattern:
            raise DataXGateError(f"request header contract changed: {key}")
    if params.get("X-Run-Id", {}).get("schema", {}).get("format") != "uuid":
        raise DataXGateError("X-Run-Id contract changed")
    for key, pattern in (("X-Run-Step", r"^\d{1,6}$"), ("X-Run-Iteration", r"^\d{1,6}$")):
        if params.get(key, {}).get("schema", {}).get("pattern") != pattern:
            raise DataXGateError(f"run header contract changed: {key}")
    if "Idempotency-Key" not in params or "X-Max-Price" not in params:
        raise DataXGateError("required idempotency/price-cap headers disappeared")


def _docs(docs_root: Path | None = None, *, now: datetime | None = None) -> tuple[dict, dict, dict, dict]:
    root = docs_root or DOCS_ROOT
    if root is None:
        raise DataXGateError("verified docs cache missing; run prepare-docs and pass --docs-dir")
    root = Path(root).expanduser().resolve()
    files = {}
    hashes = {}
    for name, expected in EXPECTED_DOC_SHA.items():
        data = (root / name).read_bytes()
        actual = sha256_bytes(data)
        if actual != expected:
            raise DataXGateError(f"pinned official document hash mismatch: {name}")
        hashes[name] = actual
        files[name] = json.loads(data) if name.endswith(".json") else data.decode("utf-8")
    agents = files["agents.md"]
    snap, snap_sha = _read_json(root / "snapshot.json")
    if (snap.get("schema") != "public-workbench-datax-docs-cache/v1" or
            snap.get("verification_status") != "VERIFIED_PUBLIC_CONTRACT_ONLY_NOT_ACCOUNT_OR_RUN"):
        raise DataXGateError("official contract snapshot is not in verified-public-only state")
    for name, expected in EXPECTED_DOC_SHA.items():
        if snap.get("documents", {}).get(name) != expected:
            raise DataXGateError("official document hashes are not bound by the snapshot")
    if snap.get("base_url") != BASE_URL or snap.get("catalog_revision") != EXPECTED_CATALOG_REVISION:
        raise DataXGateError("official base URL mismatch")
    if snap.get("pricebook_version") != EXPECTED_PRICEBOOK_VERSION:
        raise DataXGateError("official snapshot pricebook version mismatch")
    _freshness(_dt(snap.get("retrieved_at")), now or datetime.now(timezone.utc), "official docs snapshot")
    _validate_contract(agents, files["openapi.json"], files["prices.json"])
    return snap, files["openapi.json"], files["prices.json"], {**hashes, "snapshot.json": snap_sha}


def _fetch_official_doc(url: str, transport: Callable | None = None) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json, text/markdown, text/plain"})
    status, headers, body, final_url = (transport or request_once)(request, 30)
    if status != 200 or final_url != url:
        raise DataXGateError("official docs request did not return HTTP 200 at the exact URL; no redirect accepted")
    if len(body) > MAX_RESPONSE_BYTES:
        raise DataXGateError("official docs response exceeded local size limit")
    return body, {"http_status": status, "final_url": final_url, "content_type": headers.get("Content-Type") if hasattr(headers, "get") else None}


def prepare_docs(cache_dir: Path, transport: Callable | None = None, *, now: datetime | None = None) -> dict:
    """Fetch the three reviewed official source documents once; drift blocks before writing."""
    target = Path(cache_dir).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise DataXGateError("docs cache target must be new or empty; preserve previous snapshots")
    fetched, responses = {}, {}
    for name, url in OFFICIAL_DOC_URLS.items():
        raw, response = _fetch_official_doc(url, transport)
        actual = sha256_bytes(raw)
        if actual != EXPECTED_DOC_SHA[name]:
            raise DataXGateError(f"official source changed from reviewed SHA: {name}; preserve and review before updating")
        fetched[name] = raw
        responses[name] = response
    agents = fetched["agents.md"].decode("utf-8")
    openapi = json.loads(fetched["openapi.json"])
    prices = json.loads(fetched["prices.json"])
    _validate_contract(agents, openapi, prices)
    retrieved = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    snapshot = {"schema": "public-workbench-datax-docs-cache/v1", "vendor": "DataXAPI",
                "verification_status": "VERIFIED_PUBLIC_CONTRACT_ONLY_NOT_ACCOUNT_OR_RUN",
                "retrieved_at": retrieved, "final_hostname": "dataxapi.com", "base_url": BASE_URL,
                "catalog_revision": EXPECTED_CATALOG_REVISION, "pricebook_version": EXPECTED_PRICEBOOK_VERSION,
                "documents": {name: sha256_bytes(raw) for name, raw in fetched.items()},
                "responses": responses, "API_calls": 0, "account_balance": "NOT_CALLED",
                "run": "NOT_CREATED", "secrets_saved": False}
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".tmp-" + hashlib.sha256(retrieved.encode()).hexdigest()[:8])
    if staging.exists():
        raise DataXGateError("temporary docs cache path already exists")
    staging.mkdir(mode=0o700)
    try:
        for name, raw in fetched.items():
            (staging / name).write_bytes(raw)
            (staging / name).chmod(0o600)
        (staging / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "snapshot.json").chmod(0o600)
        if target.exists():
            target.rmdir()
        os.replace(staging, target)
    except Exception:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"cache_dir": str(target), "snapshot_sha256": sha256_bytes((target / "snapshot.json").read_bytes()),
            "document_hashes": snapshot["documents"], "verification_status": snapshot["verification_status"],
            "API_calls": 0, "account_balance": "NOT_CALLED", "run": "NOT_CREATED"}


def _evidence_file(evidence: object, label: str, now: datetime) -> tuple[dict, str]:
    if not isinstance(evidence, dict) or not evidence.get("path") or not evidence.get("sha256"):
        raise DataXGateError(f"{label} requires path and SHA-256 evidence")
    value, digest = _read_json(Path(evidence["path"]))
    if digest != evidence["sha256"]:
        raise DataXGateError(f"{label} file hash mismatch")
    observed = _dt(evidence.get("observed_at"))
    _freshness(observed, now, label)
    return value, digest


def _unwrap(value: dict, key: str) -> dict:
    data = value.get("data")
    if isinstance(data, dict) and isinstance(data.get(key), dict):
        return data[key]
    if isinstance(data, dict):
        return data
    raise DataXGateError(f"{key} evidence response has no data object")


def _no_redirect_opener():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def _stage_datax_result(workspace: Path, operation: str, params: dict, payload: dict,
                        receipt_path: Path, request_key: str) -> dict:
    """Persist provider output as unreviewed evidence; never create an approval."""
    data = payload.get("data")
    folder = workspace / "datax-staging" / request_key
    folder.mkdir(parents=True, exist_ok=False)
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    common = {"request_id": payload.get("request_id"), "operation": operation,
              "receipt_path": receipt_path.relative_to(workspace).as_posix(),
              "receipt_sha256": sha256_bytes(receipt_path.read_bytes()),
              "source_response_sha256": sha256_bytes(json.dumps(payload, ensure_ascii=False,
                                      sort_keys=True, separators=(",", ":")).encode()),
              "qualification": "PENDING_INDEPENDENT_REVIEW", "Q": None,
              "counts_toward_target": False, "author_claim_status": "SOURCE_REPORTED",
              "independent_test_status": "NOT_TESTED"}
    if operation == "get":
        if not isinstance(data, dict) or "item" not in data:
            raise DataXGateError("successful get response omitted required data.item field")
        item = data.get("item")
        if item is not None and not isinstance(item, dict):
            raise DataXGateError("successful get response has invalid data.item type")
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"]:
            result = {"schema": "public-workbench-datax-pending-review/v1", **common,
                      "state": "NO_BODY_RETURNED", "reason": "DataX response contained no readable item text",
                      "original_url": params.get("url"), "body_file": None, "body_sha256": None}
        else:
            body = item["text"].encode("utf-8")
            body_path = folder / "body.txt"
            body_path.write_bytes(body)
            try:
                body_path.chmod(0o600)
            except OSError:
                pass
            result = {"schema": "public-workbench-datax-pending-review/v1", **common,
                      "state": "PENDING_INDEPENDENT_REVIEW", "publisher": "WeChat provider response; not raw HTML",
                      "original_url": params["url"], "provider_item_url": item.get("url"),
                      "identity_match": item.get("url") == params["url"] if item.get("url") else None,
                      "title": item.get("title"), "author": item.get("author"),
                      "published_at": item.get("published_at"), "body_file": "body.txt",
                      "body_sha256": sha256_bytes(body), "body_characters": len(item["text"]),
                      "media_downloaded": False,
                      "limitations": ["SOURCE_REPORTED", "NOT_TESTED", "provider response is not original page HTML"]}
    else:
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise DataXGateError("successful list response has no schema-conforming data.items array")
        records = []
        seen = set()
        identities_path = workspace / "state" / "datax-article-identities.json"
        identities_path.parent.mkdir(parents=True, exist_ok=True)
        identities = json.loads(identities_path.read_text()) if identities_path.exists() else {
            "schema": "public-workbench-datax-article-identities/v1", "urls": {}}
        for index, item in enumerate(items[:20]):
            if not isinstance(item, dict):
                raise DataXGateError("successful list response contains a non-object item")
            url = item.get("url")
            if not isinstance(url, str) or not url:
                continue
            identity = sha256_bytes(url.encode("utf-8"))
            duplicate = identity in seen or identity in identities["urls"]
            seen.add(identity)
            if not duplicate:
                identities["urls"][identity] = {"status": "OBSERVED_IN_LIST", "first_request_id": payload.get("request_id")}
            summary = item.get("text")
            records.append({"candidate_index": index, "identity_sha256": identity, "url_observed": url,
                            "title_observed": item.get("title"),
                            "summary_observed": summary[:1000] if isinstance(summary, str) else None,
                            "summary_truncated": isinstance(summary, str) and len(summary) > 1000,
                            "published_at_observed": item.get("published_at"),
                            "author_observed": item.get("author"), "account_id": params.get("id"),
                            "status": "PREVIOUSLY_LISTED" if duplicate else "METADATA_CANDIDATE",
                            "qualification": "NOT_REVIEWED"})
        identities_tmp = identities_path.with_suffix(".tmp")
        identities_tmp.write_text(json.dumps(identities, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(identities_tmp, identities_path)
        try:
            identities_path.chmod(0o600)
        except OSError:
            pass
        result = {"schema": "public-workbench-datax-metadata-candidates/v1", **common,
                  "state": "METADATA_CANDIDATES_ONLY", "account_id": params.get("id"),
                  "returned_item_count": len(items), "candidate_count": len(records), "records": records,
                  "note": "List success is metadata only; no article body was requested or approved."}
    result_path = folder / ("pending-review.json" if operation == "get" else "metadata-candidates.json")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        result_path.chmod(0o600)
    except OSError:
        pass
    return {"staging_file": result_path.relative_to(workspace).as_posix(),
            "staging_sha256": sha256_bytes(result_path.read_bytes()), "state": result["state"]}


def request_once(request: urllib.request.Request, timeout: int = 30):
    try:
        response = _no_redirect_opener().open(request, timeout=timeout)
        with response:
            return response.status, response.headers, response.read(MAX_RESPONSE_BYTES + 1), response.geturl()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read(MAX_RESPONSE_BYTES + 1), error.geturl()


def _workspace_lock(workspace: Path):
    from contextlib import contextmanager
    @contextmanager
    def lock():
        folder = workspace / "state"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "datax-single-call.lock"
        with path.open("a+b") as stream:
            try:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                yield
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except ImportError:
                yield
    return lock()


def datax_once_from_preflight(workspace: Path, preflight_path: Path, operation: str, params: dict,
                              explicit_confirmation: bool = False, transport: Callable | None = None,
                              now: datetime | None = None, docs_dir: Path | None = None) -> dict:
    """Perform no more than one documented paid GET after a complete local preflight.

    No balance/run discovery and no run creation happen here. Transport injection is
    for offline tests only; production CLI uses stdlib urllib with redirects disabled.
    """
    workspace = Path(workspace).expanduser().resolve()
    if not explicit_confirmation:
        raise DataXGateError("explicit --confirm-paid-transfer is required for this one paid GET")
    preflight, preflight_sha = _read_json(Path(preflight_path))
    if preflight.get("schema") != "public-workbench-datax-preflight/v1" or preflight.get("authorized_single_call") is not True:
        raise DataXGateError("preflight must explicitly authorize exactly one call")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise DataXGateError("test/current time must include timezone")
    _freshness(_dt(preflight.get("created_at")), clock, "preflight")
    snapshot, openapi, prices, docs_hashes = _docs(docs_dir, now=clock)
    if preflight.get("docs_hashes") != docs_hashes:
        raise DataXGateError("preflight official-doc/snapshot hashes mismatch")
    if preflight.get("catalog_revision") != snapshot.get("catalog_revision") or preflight.get("pricebook_version") != "12":
        raise DataXGateError("preflight catalog or pricebook revision mismatch")
    run_id = safe_run_id(preflight.get("run_id", ""))
    if preflight.get("scope") != {"operation": operation, "params": params}:
        raise DataXGateError("operation/parameters differ from the authorized preflight scope")
    path, capability, endpoint_max, _ = _contract(operation, params, openapi, prices)
    balance_doc, balance_sha = _evidence_file(preflight.get("balance_evidence"), "balance", clock)
    run_doc, run_sha = _evidence_file(preflight.get("run_evidence"), "run", clock)
    if balance_doc.get("code") != "ok" or balance_doc.get("request_id") is None:
        raise DataXGateError("balance evidence is not a successful account GET readback")
    if run_doc.get("code") != "ok" or run_doc.get("request_id") is None:
        raise DataXGateError("run evidence is not a successful existing-run GET readback")
    account = _unwrap(balance_doc, "account")
    run = _unwrap(run_doc, "run")
    if account.get("currency") != "USD":
        raise DataXGateError("account balance currency is not USD")
    balance = _decimal(account.get("balance"), "account balance")
    key_info = account.get("key")
    if isinstance(key_info, dict):
        scopes = key_info.get("scopes")
        if scopes is not None and capability not in scopes:
            raise DataXGateError("current key scope does not include the documented capability")
        budget = key_info.get("budget", {})
        for period in ("daily", "monthly", "total"):
            remaining_period = budget.get(period, {}).get("remaining")
            if remaining_period is not None and _decimal(remaining_period, f"key {period} remaining budget") < endpoint_max:
                raise DataXGateError(f"current key {period} budget is below the endpoint maximum charge")
    run_id_in_doc = safe_run_id(run.get("run_id", ""))
    if run_id_in_doc != run_id or run.get("expired") is not False:
        raise DataXGateError("run evidence does not match an active, unexpired existing run")
    if preflight.get("run_scope") != {"task_id": run.get("task_id"), "task_revision": run.get("task_revision")}:
        raise DataXGateError("preflight task scope does not match the existing run")
    if isinstance(key_info, dict) and key_info.get("expires_at") and _dt(key_info["expires_at"]) <= clock:
        raise DataXGateError("current API key evidence indicates an expired key")
    if run_doc.get("request_id") is None:
        raise DataXGateError("run readback receipt missing")
    if _dt(run.get("expires_at")) <= clock:
        raise DataXGateError("existing run has expired")
    remaining = _decimal(run.get("remaining_amount"), "run remaining amount")
    if int(run.get("remaining_calls", 0)) < 1:
        raise DataXGateError("existing run has no remaining calls")
    cap = _decimal(preflight.get("max_price"), "per-call max_price")
    if cap != endpoint_max or cap > balance or cap > remaining:
        raise DataXGateError("per-call cap exceeds endpoint, balance, or existing-run remaining budget")
    expected_approval = {"approved": True, "operation": operation,
                         "params_sha256": sha256_bytes(json.dumps(params, ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")).encode()),
                         "max_price": str(cap), "run_id": run_id,
                         "run_scope": preflight["run_scope"],
                         "run_step": str(preflight.get("run_step", "")),
                         "run_iteration": str(preflight.get("run_iteration", ""))}
    if preflight.get("human_approval") != expected_approval:
        raise DataXGateError("human approval does not bind exact operation, parameters, and price cap")
    key = os.environ.get("DATAXAPI_API_KEY", "")
    if not key:
        raise DataXGateError("DATAXAPI_API_KEY must be present in the environment; never stored in files")
    if not re.fullmatch(r"\d{1,6}", str(preflight.get("run_step", ""))) or not re.fullmatch(r"\d{1,6}", str(preflight.get("run_iteration", ""))):
        raise DataXGateError("run_step and run_iteration must each be 1-6 digits")
    q = urllib.parse.urlencode(params)
    url = BASE_URL + path + ("?" + q if q else "")
    idem = idempotency_key(run_id, path, params)
    request_id = sha256_bytes((idem + "\n" + preflight_sha).encode())[:24]
    receipts = workspace / "datax-receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    try:
        receipts.chmod(0o700)
    except OSError:
        pass
    receipt_path = receipts / f"{request_id}.json"
    ledger_path = workspace / "state" / "datax-attempts.json"
    with _workspace_lock(workspace):
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"schema": "public-workbench-datax-attempts/v1", "attempts": {}}
        existing = ledger["attempts"].get(idem)
        scope_hash = sha256_bytes(json.dumps([operation, path, sorted(params.items())], ensure_ascii=False,
                                             separators=(",", ":")).encode())
        if existing or any(row.get("scope_sha256") == scope_hash for row in ledger["attempts"].values()):
            raise DataXGateError("this run/endpoint/parameter scope was already attempted; no resend")
        attempt = {"status": "STARTED_NO_RETRY", "started_at": clock.isoformat(), "operation": operation,
                   "path": path, "run_id": run_id, "idempotency_key_sha256": sha256_bytes(idem.encode()),
                   "scope_sha256": scope_hash,
                   "preflight_sha256": preflight_sha, "balance_sha256": balance_sha, "run_evidence_sha256": run_sha,
                   "docs_hashes": docs_hashes, "max_price": str(cap), "receipt_file": receipt_path.relative_to(workspace).as_posix()}
        ledger["attempts"][idem] = attempt
        temp = ledger_path.with_suffix(".tmp")
        temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, ledger_path)
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "Idempotency-Key": idem,
        "X-Max-Price": str(cap),
        "X-Run-Id": run_id,
        "X-Run-Step": str(preflight.get("run_step", "")),
        "X-Run-Iteration": str(preflight.get("run_iteration", "")),
        "X-Source": "public-workbench",
    })
    try:
        status, headers, raw, final_url = (transport or request_once)(req, 30)
        raw_response_path = receipts / f"{request_id}.response.bin"
        raw_response_path.write_bytes(raw)
        try:
            raw_response_path.chmod(0o600)
        except OSError:
            pass
        raw_sha = sha256_bytes(raw)
        def persist_unparsed_stop(state: str, reason: str, provider_request_id: str | None = None) -> dict:
            receipt = {"schema": "public-workbench-datax-receipt/v1", "request_key": request_id,
                       "requested_at": clock.isoformat(), "http_status": int(status), "final_url": final_url,
                       "operation": operation, "params": params, "run_id": run_id,
                       "run_step": str(preflight["run_step"]), "run_iteration": str(preflight["run_iteration"]),
                       "max_price": str(cap), "idempotency_key_sha256": sha256_bytes(idem.encode()),
                       "raw_response_file": raw_response_path.relative_to(workspace).as_posix(),
                       "raw_response_sha256": raw_sha, "raw_response": None, "docs_hashes": docs_hashes,
                       "provider_request_id": provider_request_id,
                       "balance_evidence_sha256": balance_sha, "run_evidence_sha256": run_sha,
                       "settlement_state": state, "stop_reason": reason, "retry": "NONE"}
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                receipt_path.chmod(0o600)
            except OSError:
                pass
            ledger = json.loads(ledger_path.read_text())
            ledger["attempts"][idem].update({"status": state, "http_status": int(status),
                                            "receipt_sha256": sha256_bytes(receipt_path.read_bytes())})
            temp = ledger_path.with_suffix(".tmp")
            temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
            os.replace(temp, ledger_path)
            return {"success": False, "state": state, "receipt": receipt_path.relative_to(workspace).as_posix(),
                    "receipt_sha256": sha256_bytes(receipt_path.read_bytes()), "retry": "NONE"}
        if len(raw) > MAX_RESPONSE_BYTES:
            provider_request_id = None
            try:
                oversized_payload = json.loads(raw)
                provider_request_id = oversized_payload.get("request_id") if isinstance(oversized_payload, dict) else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            return persist_unparsed_stop("RESPONSE_TOO_LARGE_SETTLEMENT_UNKNOWN_STOP", "response exceeded local capture limit", provider_request_id)
        try:
            parsed = json.loads(raw) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return persist_unparsed_stop("RESPONSE_PARSE_UNKNOWN_STOP", "response was not valid JSON")
        error_data = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        error_payload = parsed.get("data", {}) if isinstance(parsed, dict) else {}
        charged = parsed.get("charged") if isinstance(parsed, dict) else None
        if charged is None and isinstance(error_data, dict):
            charged = error_data.get("charged")
        if charged is None and isinstance(error_payload, dict):
            charged = error_payload.get("charged")
        successful_envelope = response_succeeded(status, parsed)
        billing_validation, billing_amount, billing_state = (None, None, None)
        if successful_envelope:
            billing_validation, billing_amount, billing_state = _success_billing_validation(parsed, cap)
            settlement_unknown = billing_state == "SETTLEMENT_UNKNOWN_STOP"
        elif not isinstance(parsed, dict):
            settlement_unknown = True
        elif status >= 400:
            settlement_unknown = charged is None
        else:
            meta = parsed.get("meta")
            billing = meta.get("billing") if isinstance(meta, dict) else None
            settlement_unknown = not isinstance(billing, dict) or billing.get("amount") is None
        receipt = {
            "schema": "public-workbench-datax-receipt/v1", "request_key": request_id,
            "requested_at": clock.isoformat(), "http_status": int(status), "final_url": final_url,
            "operation": operation, "params": params, "run_id": run_id, "run_step": str(preflight["run_step"]),
            "run_iteration": str(preflight["run_iteration"]), "max_price": str(cap),
            "idempotency_key_sha256": sha256_bytes(idem.encode()), "raw_response_sha256": sha256_bytes(raw),
            "raw_response_file": raw_response_path.relative_to(workspace).as_posix(),
            "raw_response": parsed, "docs_hashes": docs_hashes,
            "balance_evidence_sha256": balance_sha, "run_evidence_sha256": run_sha,
            "settlement_state": (billing_state if successful_envelope else
                                 ("SETTLEMENT_UNKNOWN_STOP" if settlement_unknown else "RESPONSE_RECORDED")),
            "retry": "NONE",
        }
        if billing_validation is not None:
            receipt["billing_validation"] = billing_validation
        if final_url != url or 300 <= int(status) < 400:
            receipt["settlement_state"] = "REDIRECT_STOP_CHECK_ORIGINAL_RECEIPT"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        try:
            receipt_path.chmod(0o600)
        except OSError:
            pass
        ledger = json.loads(ledger_path.read_text())
        ledger["attempts"][idem].update({"status": receipt["settlement_state"], "http_status": int(status),
                                        "receipt_sha256": sha256_bytes(receipt_path.read_bytes())})
        temp = ledger_path.with_suffix(".tmp")
        temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, ledger_path)
        if receipt["settlement_state"] != "RESPONSE_RECORDED" or not response_succeeded(status, parsed):
            return {"success": False, "state": receipt["settlement_state"], "receipt": receipt_path.relative_to(workspace).as_posix(),
                    "receipt_sha256": sha256_bytes(receipt_path.read_bytes()), "retry": "NONE"}
        provider_request_id = parsed.get("request_id")
        import uuid
        try:
            uuid.UUID(provider_request_id)
        except (ValueError, TypeError, AttributeError):
            receipt["settlement_state"] = "RESPONSE_SCHEMA_INVALID_STOP"
            receipt["stop_reason"] = "successful envelope has no valid request_id"
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                receipt_path.chmod(0o600)
            except OSError:
                pass
            ledger = json.loads(ledger_path.read_text())
            ledger["attempts"][idem].update({"status": receipt["settlement_state"],
                                            "receipt_sha256": sha256_bytes(receipt_path.read_bytes())})
            temp = ledger_path.with_suffix(".tmp")
            temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
            os.replace(temp, ledger_path)
            return {"success": False, "state": receipt["settlement_state"],
                    "receipt": receipt_path.relative_to(workspace).as_posix(),
                    "receipt_sha256": sha256_bytes(receipt_path.read_bytes()), "retry": "NONE"}
        try:
            staging = _stage_datax_result(workspace, operation, params, parsed, receipt_path, request_id)
        except Exception as stage_error:
            receipt["staging_state"] = "STAGING_BLOCKED_NO_RETRY"
            receipt["staging_error_type"] = type(stage_error).__name__
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                receipt_path.chmod(0o600)
            except OSError:
                pass
            ledger = json.loads(ledger_path.read_text())
            ledger["attempts"][idem].update({"status": receipt["settlement_state"],
                                            "receipt_sha256": sha256_bytes(receipt_path.read_bytes())})
            temp = ledger_path.with_suffix(".tmp")
            temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
            os.replace(temp, ledger_path)
            return {"success": False, "state": "RESPONSE_RECORDED_STAGING_BLOCKED",
                    "receipt": receipt_path.relative_to(workspace).as_posix(),
                    "receipt_sha256": sha256_bytes(receipt_path.read_bytes()), "retry": "NONE"}
        return {"success": True, "state": "RESPONSE_RECORDED", "receipt": receipt_path.relative_to(workspace).as_posix(),
                "receipt_sha256": sha256_bytes(receipt_path.read_bytes()), "retry": "NONE",
                "billing_amount": str(billing_amount), **staging}
    except Exception as error:
        # There is no retry. Persist the exact local failure summary without the secret header.
        ledger = json.loads(ledger_path.read_text())
        ledger["attempts"][idem].update({"status": "TRANSPORT_UNKNOWN_STOP", "error_type": type(error).__name__})
        temp = ledger_path.with_suffix(".tmp")
        temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, ledger_path)
        raise DataXStop("one request may have reached the provider; inspect the original request receipt; never resend") from error


def datax_check_original_receipt(workspace: Path, receipt_relative_path: str,
                                 transport: Callable | None = None) -> dict:
    """One free documented GET /v1/calls/{id}; never repeats the original paid request."""
    workspace = Path(workspace).expanduser().resolve()
    target = (workspace / receipt_relative_path).resolve()
    if workspace not in target.parents:
        raise DataXGateError("receipt path must remain inside the selected private workspace")
    original, original_sha = _read_json(target)
    payload = original.get("raw_response")
    request_id = payload.get("request_id") if isinstance(payload, dict) else original.get("provider_request_id")
    import uuid
    try:
        request_id = str(uuid.UUID(request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DataXGateError("original response has no valid request_id; do not issue a replacement call") from exc
    if original.get("settlement_state") not in {"SETTLEMENT_UNKNOWN_STOP", "REDIRECT_STOP_CHECK_ORIGINAL_RECEIPT"}:
        raise DataXGateError("receipt lookup is reserved for an original call with unknown settlement")
    key = os.environ.get("DATAXAPI_API_KEY", "")
    if not key:
        raise DataXGateError("DATAXAPI_API_KEY must be present in the environment; never stored in files")
    ledger_path = workspace / "state" / "datax-receipt-lookups.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lookup_key = request_id
    with _workspace_lock(workspace):
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"schema": "public-workbench-datax-receipt-lookups/v1", "lookups": {}}
        if lookup_key in ledger["lookups"]:
            raise DataXGateError("original receipt lookup already attempted; no retry")
        ledger["lookups"][lookup_key] = {"status": "STARTED_NO_RETRY", "original_receipt_sha256": original_sha}
        temp = ledger_path.with_suffix(".tmp")
        temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, ledger_path)
    url = BASE_URL + "/v1/calls/" + request_id
    req = urllib.request.Request(url, method="GET", headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        status, headers, raw, final_url = (transport or request_once)(req, 30)
        parsed = json.loads(raw) if raw else None
        output = workspace / "datax-receipts" / ("lookup-" + request_id + ".json")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            output.parent.chmod(0o700)
        except OSError:
            pass
        result = {"schema": "public-workbench-datax-receipt-lookup/v1", "request_id": request_id,
                  "original_receipt_sha256": original_sha, "http_status": int(status), "final_url": final_url,
                  "raw_response_sha256": sha256_bytes(raw), "raw_response": parsed, "retry": "NONE"}
        receipt_data = parsed.get("data") if isinstance(parsed, dict) else None
        matches_call = (isinstance(receipt_data, dict) and receipt_data.get("request_id") == request_id
                        and receipt_data.get("charged") is not None
                        and receipt_data.get("status") in {"settled", "released"})
        result["settlement_state"] = "RESOLVED" if (int(status) == 200 and final_url == url and
            isinstance(parsed, dict) and parsed.get("code") == "ok" and matches_call) else "STILL_UNKNOWN_STOP"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        try:
            output.chmod(0o600)
        except OSError:
            pass
        ledger = json.loads(ledger_path.read_text())
        ledger["lookups"][lookup_key].update({"status": result["settlement_state"], "result_sha256": sha256_bytes(output.read_bytes())})
        temp = ledger_path.with_suffix(".tmp")
        temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, ledger_path)
        return {"state": result["settlement_state"], "receipt": output.relative_to(workspace).as_posix(),
                "receipt_sha256": sha256_bytes(output.read_bytes()), "retry": "NONE"}
    except Exception as error:
        ledger = json.loads(ledger_path.read_text())
        ledger["lookups"][lookup_key].update({"status": "LOOKUP_UNKNOWN_STOP", "error_type": type(error).__name__})
        temp = ledger_path.with_suffix(".tmp")
        temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp, ledger_path)
        raise DataXStop("free original-receipt lookup attempted once; stop and preserve uncertainty") from error
