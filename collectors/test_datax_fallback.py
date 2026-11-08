from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collectors import datax_fallback as datax

from collectors.datax_fallback import (
    DataXGateError,
    datax_check_original_receipt,
    datax_once_from_preflight,
    sha256_bytes,
)


class DataXFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.run_id = str(uuid.uuid4())
        self.params = {"url": "https://mp.weixin.qq.com/s?__biz=abc&mid=123&idx=1&sn=abcd"}
        self.original_docs_root = datax.DOCS_ROOT
        self.original_doc_shas = datax.EXPECTED_DOC_SHA
        self.docs_root = self.root / "verified-contract-cache"
        self.docs_root.mkdir()
        documents = self.contract_fixture()
        datax.EXPECTED_DOC_SHA = {name: sha256_bytes(raw) for name, raw in documents.items()}
        datax.DOCS_ROOT = self.docs_root
        for name, raw in documents.items():
            (self.docs_root / name).write_bytes(raw)
        snapshot = {"schema": "public-workbench-datax-docs-cache/v1", "verification_status": "VERIFIED_PUBLIC_CONTRACT_ONLY_NOT_ACCOUNT_OR_RUN",
                    "retrieved_at": self.now.isoformat(), "base_url": "https://api.dataxapi.com",
                    "catalog_revision": datax.EXPECTED_CATALOG_REVISION, "pricebook_version": "12",
                    "documents": datax.EXPECTED_DOC_SHA}
        self._write(self.docs_root / "snapshot.json", snapshot)
        self.snapshot, _, _, self.doc_hashes = datax._docs(self.docs_root, now=self.now)
        self.balance_path = self.root / "account-readback.json"
        self.run_path = self.root / "run-readback.json"
        self._write(self.balance_path, {
            "code": "ok", "request_id": str(uuid.uuid4()),
            "data": {"balance": "5.80", "currency": "USD", "key": None,
                     "rate": {"tier": "test", "per_minute": 10, "concurrent": 1}},
        })
        self._write(self.run_path, {
            "code": "ok", "request_id": str(uuid.uuid4()),
            "data": {"run_id": self.run_id, "task_id": "t", "task_revision": "1",
                     "max_amount": "1.00", "settled": "0.00", "held": "0.00",
                     "remaining_amount": "0.98", "max_calls": 10, "calls_used": 1,
                     "remaining_calls": 9, "expires_at": (self.now + timedelta(hours=1)).isoformat(),
                     "expired": False},
        })
        self.preflight_path = self.root / "preflight.json"
        self._make_preflight()
        os.environ["DATAXAPI_API_KEY"] = "test-only-not-real"

    def tearDown(self):
        os.environ.pop("DATAXAPI_API_KEY", None)
        datax.DOCS_ROOT = self.original_docs_root
        datax.EXPECTED_DOC_SHA = self.original_doc_shas
        self.tmp.cleanup()

    def contract_fixture(self):
        pricing_get = {"per": "call", "price": "0.02", "max_charge": "0.02", "charge_when_empty": "0", "charge_when_not_found": "0.02"}
        pricing_list = {"per": "call", "price": "0.02", "max_charge": "0.02", "charge_when_empty": "0.02"}
        openapi = {
            "servers": [{"url": "https://api.dataxapi.com"}],
            "paths": {
                "/v1/wechat_mp/articles/get": {"get": {"operationId": "wechat_mp.articles.get", "x-capability": {"pricing": pricing_get},
                    "parameters": [{"name": "url", "in": "query", "required": True, "schema": {"type": "string"}}]}},
                "/v1/wechat_mp/accounts/articles/list": {"get": {"operationId": "wechat_mp.accounts.articles.list", "x-capability": {"pricing": pricing_list},
                    "parameters": [{"name": "id", "in": "query", "required": True, "schema": {"type": "string"}}]}},
                "/v1/runs": {"post": {"requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "required": ["task_id", "task_revision", "max_amount", "max_calls"],
                    "properties": {"ttl_seconds": {"minimum": 60, "maximum": 86400}}}}}}}},
            },
            "components": {"parameters": {
                "X-Run-Step": {"schema": {"pattern": r"^\d{1,6}$"}},
                "X-Run-Iteration": {"schema": {"pattern": r"^\d{1,6}$"}},
                "Idempotency-Key": {"schema": {"type": "string", "pattern": r"^[\x21-\x7e]{1,255}$"}},
                "X-Max-Price": {"schema": {"type": "string", "pattern": r"^\d{1,7}(\.\d{1,6})?$"}},
                "X-Run-Id": {"schema": {"type": "string", "format": "uuid"}},
            }},
        }
        prices = {"revision": datax.EXPECTED_CATALOG_REVISION, "prices": {"version": "12"},
                  "base_url": "https://api.dataxapi.com", "endpoints": [
                      {"id": "wechat_mp.articles.get", "path": "/v1/wechat_mp/articles/get", **pricing_get},
                      {"id": "wechat_mp.accounts.articles.list", "path": "/v1/wechat_mp/accounts/articles/list", **pricing_list}]}
        return {"agents.md": b"GET https://api.dataxapi.com/v1/account\n",
                "openapi.json": json.dumps(openapi, separators=(",", ":")).encode(),
                "prices.json": json.dumps(prices, separators=(",", ":")).encode()}

    def _write(self, path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    def _evidence(self, path):
        return {"path": str(path), "sha256": sha256_bytes(path.read_bytes()), "observed_at": self.now.isoformat()}

    def _make_preflight(self, *, max_price="0.02", balance_observed=None, operation="get", params=None):
        params = params or self.params
        approval_hash = sha256_bytes(json.dumps(params, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode())
        preflight = {
            "schema": "public-workbench-datax-preflight/v1", "created_at": self.now.isoformat(),
            "authorized_single_call": True, "catalog_revision": self.snapshot["catalog_revision"],
            "pricebook_version": "12", "docs_hashes": self.doc_hashes, "run_id": self.run_id,
            "run_scope": {"task_id": "t", "task_revision": "1"},
            "run_step": "1", "run_iteration": "1", "max_price": max_price,
            "scope": {"operation": operation, "params": params},
            "balance_evidence": self._evidence(self.balance_path),
            "run_evidence": self._evidence(self.run_path),
            "human_approval": {"approved": True, "operation": operation, "params_sha256": approval_hash,
                               "max_price": max_price, "run_id": self.run_id,
                               "run_scope": {"task_id": "t", "task_revision": "1"},
                               "run_step": "1", "run_iteration": "1"},
        }
        if balance_observed:
            preflight["balance_evidence"]["observed_at"] = balance_observed
        self._write(self.preflight_path, preflight)

    def _success_transport(self, calls):
        def transport(request, timeout):
            calls.append(request)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("X-max-price"), "0.02")
            self.assertEqual(request.get_header("X-run-id"), self.run_id)
            self.assertRegex(request.get_header("X-run-step"), r"^\d{1,6}$")
            return 200, {}, json.dumps({"code": "ok", "request_id": str(uuid.uuid4()),
                                        "data": {"item": {"title": "synthetic", "text": "Synthetic body text."}},
                                        "meta": {"billing": {"amount": "0.02", "currency": "USD"}}}).encode(), request.full_url
        return transport

    def test_one_paid_get_passes_all_gates_and_cannot_repeat(self):
        calls = []
        result = datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                           True, self._success_transport(calls), self.now)
        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 1)
        receipt = self.workspace / result["receipt"]
        self.assertTrue(receipt.exists())
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        pending_path = self.workspace / result["staging_file"]
        pending = json.loads(pending_path.read_text())
        self.assertEqual(pending["qualification"], "PENDING_INDEPENDENT_REVIEW")
        self.assertEqual(pending["Q"], None)
        self.assertFalse(pending["counts_toward_target"])
        self.assertEqual(pending["body_sha256"], sha256_bytes((pending_path.parent / "body.txt").read_bytes()))
        # A new run id does not make the same endpoint+parameters eligible for a second charge.
        new_run_id = str(uuid.uuid4())
        run_doc = json.loads(self.run_path.read_text())
        run_doc["data"]["run_id"] = new_run_id
        self._write(self.run_path, run_doc)
        self.run_id = new_run_id
        preflight = json.loads(self.preflight_path.read_text())
        preflight["run_id"] = new_run_id
        preflight["run_evidence"] = self._evidence(self.run_path)
        preflight["human_approval"]["run_id"] = new_run_id
        self._write(self.preflight_path, preflight)
        with self.assertRaises(DataXGateError):
            datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                      True, self._success_transport(calls), self.now)
        self.assertEqual(len(calls), 1)

    def test_success_billing_accepts_only_amounts_at_or_below_authorized_cap(self):
        for index, (amount, expected) in enumerate((("0.02", "0.02"), (0.01, "0.01"))):
            with self.subTest(amount=amount):
                params = {"url": self.params["url"] + f"&within_cap={index}"}
                self._make_preflight(params=params)
                calls = []
                def transport(request, timeout):
                    calls.append(request)
                    payload = {"code": "ok", "request_id": str(uuid.uuid4()),
                               "data": {"item": {"title": "synthetic", "text": "Synthetic body text."}},
                               "meta": {"billing": {"amount": amount, "currency": "USD"}}}
                    return 200, {}, json.dumps(payload).encode(), request.full_url
                result = datax_once_from_preflight(self.workspace, self.preflight_path, "get", params,
                                                   True, transport, self.now)
                self.assertTrue(result["success"])
                self.assertEqual(result["billing_amount"], expected)
                self.assertTrue((self.workspace / result["staging_file"]).is_file())
                receipt = json.loads((self.workspace / result["receipt"]).read_text())
                self.assertEqual(receipt["billing_validation"]["status"], "VALID_WITHIN_CAP")
                self.assertEqual(len(calls), 1)

    def test_invalid_or_over_cap_success_billing_preserves_receipt_and_stops_without_staging(self):
        cases = [
            ("boolean", {"amount": True, "currency": "USD"}),
            ("nan", {"amount": float("nan"), "currency": "USD"}),
            ("positive-infinity", {"amount": float("inf"), "currency": "USD"}),
            ("infinity", {"amount": "Infinity", "currency": "USD"}),
            ("negative", {"amount": "-0.01", "currency": "USD"}),
            ("extreme-exponent", {"amount": "1e999", "currency": "USD"}),
            ("missing-billing", {}),
            ("missing-amount", {"currency": "USD"}),
            ("missing-currency", {"amount": "0.01"}),
            ("wrong-currency", {"amount": "0.01", "currency": "CNY"}),
            ("amount-object", {"amount": {"value": "0.01"}, "currency": "USD"}),
            ("billing-array", ["0.01", "USD"]),
            ("meta-array", None),
            ("over-cap", {"amount": "0.020001", "currency": "USD"}),
        ]
        for index, (label, billing) in enumerate(cases):
            with self.subTest(case=label):
                params = {"url": self.params["url"] + f"&billing_case={index}"}
                self._make_preflight(params=params)
                payload = {"code": "ok", "request_id": str(uuid.uuid4()),
                           "data": {"item": {"title": "synthetic", "text": "Must not stage."}},
                           "meta": {"billing": billing}}
                if label == "meta-array":
                    payload["meta"] = ["malformed"]
                calls = []
                raw_response = json.dumps(payload, allow_nan=True).encode()
                def transport(request, timeout):
                    calls.append(request)
                    return 200, {}, raw_response, request.full_url
                result = datax_once_from_preflight(self.workspace, self.preflight_path, "get", params,
                                                   True, transport, self.now)
                self.assertFalse(result["success"])
                self.assertIn("STOP", result["state"])
                self.assertEqual(result["retry"], "NONE")
                self.assertEqual(len(calls), 1)
                receipt_path = self.workspace / result["receipt"]
                self.assertTrue(receipt_path.is_file())
                receipt = json.loads(receipt_path.read_text())
                self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o600)
                raw_path = self.workspace / receipt["raw_response_file"]
                self.assertEqual(raw_path.read_bytes(), raw_response)
                self.assertEqual(sha256_bytes(raw_path.read_bytes()), receipt["raw_response_sha256"])
                self.assertEqual(json.dumps(receipt["raw_response"]["meta"], sort_keys=True),
                                 json.dumps(payload["meta"], sort_keys=True))
                self.assertIn(receipt["settlement_state"], {"SETTLEMENT_UNKNOWN_STOP", "BILLING_OVER_CAP_STOP"})
                ledger = json.loads((self.workspace / "state/datax-attempts.json").read_text())
                attempt = next(row for row in ledger["attempts"].values()
                               if row.get("scope_sha256") == datax.sha256_bytes(json.dumps(
                                   ["get", "/v1/wechat_mp/articles/get", sorted(params.items())],
                                   ensure_ascii=False, separators=(",", ":")).encode()))
                self.assertEqual(attempt["status"], receipt["settlement_state"])
                self.assertFalse((self.workspace / "datax-staging").exists())
    def test_stale_balance_docs_or_price_mismatch_blocks_before_transport(self):
        calls = []
        self._make_preflight(balance_observed=(self.now - timedelta(hours=7)).isoformat())
        with self.assertRaises(DataXGateError):
            datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                      True, self._success_transport(calls), self.now)
        self.assertEqual(calls, [])
        self._make_preflight(max_price="0.01")
        with self.assertRaises(DataXGateError):
            datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                      True, self._success_transport(calls), self.now)
        self.assertEqual(calls, [])
        preflight = json.loads(self.preflight_path.read_text())
        preflight["docs_hashes"]["openapi.json"] = "0" * 64
        self._write(self.preflight_path, preflight)
        with self.assertRaises(DataXGateError):
            datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                      True, self._success_transport(calls), self.now)
        self.assertEqual(calls, [])
        self._make_preflight()
        run_doc = json.loads(self.run_path.read_text())
        run_doc["data"]["remaining_calls"] = 0
        self._write(self.run_path, run_doc)
        self._make_preflight()
        with self.assertRaises(DataXGateError):
            datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                      True, self._success_transport(calls), self.now)
        self.assertEqual(calls, [])

    def test_unknown_charge_stops_and_only_original_receipt_lookup_is_allowed_once(self):
        calls = []
        request_id = str(uuid.uuid4())
        def unknown(request, timeout):
            calls.append(request)
            return 500, {}, json.dumps({"code": "settlement_unknown", "request_id": request_id,
                                        "charged": None, "retry": "same_key"}).encode(), request.full_url
        result = datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                           True, unknown, self.now)
        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "SETTLEMENT_UNKNOWN_STOP")
        self.assertEqual(len(calls), 1)
        checks = []
        def check(request, timeout):
            checks.append(request)
            self.assertEqual(request.full_url, f"https://api.dataxapi.com/v1/calls/{request_id}")
            return 200, {}, json.dumps({"code": "ok", "request_id": str(uuid.uuid4()),
                                        "data": {"request_id": request_id, "charged": "0.02",
                                                 "status": "settled"}}).encode(), request.full_url
        checked = datax_check_original_receipt(self.workspace, result["receipt"], check)
        self.assertEqual(checked["state"], "RESOLVED")
        self.assertEqual(len(checks), 1)
        with self.assertRaises(DataXGateError):
            datax_check_original_receipt(self.workspace, result["receipt"], check)
        self.assertEqual(len(checks), 1)

    def test_missing_confirmation_and_bad_step_are_local_blocks(self):
        calls = []
        with self.assertRaises(DataXGateError):
            datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                      False, self._success_transport(calls), self.now)
        preflight = json.loads(self.preflight_path.read_text())
        preflight["run_step"] = "1234567"
        self._write(self.preflight_path, preflight)
        with self.assertRaises(DataXGateError):
            datax_once_from_preflight(self.workspace, self.preflight_path, "get", self.params,
                                      True, self._success_transport(calls), self.now)
        self.assertEqual(calls, [])

    def test_empty_list_is_still_capped_at_the_documented_paid_price(self):
        params = {"id": "gh_synthetic_account"}
        self._make_preflight(operation="list", params=params)
        calls = []
        def transport(request, timeout):
            calls.append(request)
            payload = {"code": "ok", "request_id": str(uuid.uuid4()), "data": {"items": []},
                       "meta": {"billing": {"amount": "0.02", "currency": "USD"}}}
            return 200, {}, json.dumps(payload).encode(), request.full_url
        result = datax_once_from_preflight(self.workspace, self.preflight_path, "list", params,
                                           True, transport, self.now)
        self.assertTrue(result["success"])
        self.assertEqual(result["billing_amount"], "0.02")
        self.assertEqual(len(calls), 1)
        staged = json.loads((self.workspace / result["staging_file"]).read_text())
        self.assertEqual(staged["candidate_count"], 0)
        self.assertEqual(staged["state"], "METADATA_CANDIDATES_ONLY")

    def test_clean_package_copy_prepares_user_cache_and_blocks_changed_or_stale_contract(self):
        documents = self.contract_fixture()
        clean_root = self.root / "clean-copy"
        collectors = clean_root / "collectors"
        collectors.mkdir(parents=True)
        module_file = collectors / "datax_fallback.py"
        module_file.write_bytes(Path(datax.__file__).read_bytes())
        previous_env = os.environ.pop("PUBLIC_WORKBENCH_DATAX_DOCS_DIR", None)
        try:
            spec = importlib.util.spec_from_file_location("clean_copy_datax_fallback", module_file)
            clean = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(clean)
            self.assertIsNone(clean.DOCS_ROOT)
            clean.EXPECTED_DOC_SHA = {name: sha256_bytes(raw) for name, raw in documents.items()}
            calls = []
            by_url = {clean.OFFICIAL_DOC_URLS[name]: raw for name, raw in documents.items()}
            def transport(request, timeout):
                calls.append(request.full_url)
                self.assertEqual(request.get_method(), "GET")
                self.assertIsNone(request.get_header("Cookie"))
                self.assertIsNone(request.get_header("Referer"))
                self.assertIsNone(request.get_header("User-agent"))
                return 200, {"Content-Type": "application/json"}, by_url[request.full_url], request.full_url
            cache = clean_root / "user-workspace" / "datax-contracts" / "run-a"
            result = clean.prepare_docs(cache, transport, now=self.now)
            self.assertEqual(len(calls), 3)
            self.assertEqual(result["verification_status"], "VERIFIED_PUBLIC_CONTRACT_ONLY_NOT_ACCOUNT_OR_RUN")
            self.assertEqual(result["API_calls"], 0)
            snap, _, _, hashes = clean._docs(cache, now=self.now)
            self.assertEqual(hashes["openapi.json"], clean.EXPECTED_DOC_SHA["openapi.json"])
            self.assertEqual(snap["retrieved_at"], self.now.isoformat())

            changed_cache = clean_root / "user-workspace" / "datax-contracts" / "changed"
            changed_calls = []
            def changed_transport(request, timeout):
                changed_calls.append(request.full_url)
                raw = by_url[request.full_url]
                if request.full_url == clean.OFFICIAL_DOC_URLS["openapi.json"]:
                    raw += b"\n"
                return 200, {}, raw, request.full_url
            with self.assertRaises(clean.DataXGateError):
                clean.prepare_docs(changed_cache, changed_transport, now=self.now)
            self.assertEqual(len(changed_calls), 2)
            self.assertFalse(changed_cache.exists())

            redirect_cache = clean_root / "user-workspace" / "datax-contracts" / "redirected"
            redirect_calls = []
            def redirect_transport(request, timeout):
                redirect_calls.append(request.full_url)
                return 302, {"Location": "https://dataxapi.com/other"}, b"", "https://dataxapi.com/other"
            with self.assertRaises(clean.DataXGateError):
                clean.prepare_docs(redirect_cache, redirect_transport, now=self.now)
            self.assertEqual(len(redirect_calls), 1)
            self.assertFalse(redirect_cache.exists())

            openapi_path = cache / "openapi.json"
            openapi_original = openapi_path.read_bytes()
            openapi_path.write_bytes(openapi_original + b" ")
            with self.assertRaises(clean.DataXGateError):
                clean._docs(cache, now=self.now)
            openapi_path.write_bytes(openapi_original)
            snapshot_path = cache / "snapshot.json"
            snapshot = json.loads(snapshot_path.read_text())
            snapshot["retrieved_at"] = (self.now - timedelta(hours=7)).isoformat()
            self._write(snapshot_path, snapshot)
            with self.assertRaises(clean.DataXGateError):
                clean._docs(cache, now=self.now)
        finally:
            if previous_env is not None:
                os.environ["PUBLIC_WORKBENCH_DATAX_DOCS_DIR"] = previous_env


if __name__ == "__main__":
    unittest.main()
