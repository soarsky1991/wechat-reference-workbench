from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

from collectors.workflow import capture_run, discover_feed, materialize_signed_workspace, sha256


PACKAGE = Path(__file__).resolve().parents[1]
SERVER_PATH = PACKAGE / "app" / "server.py"


def synthetic_sspai_html(post_id="12345", title="演示文章：三步整理任务"):
    return f'''<!doctype html><html><head>
<link rel="canonical" href="https://sspai.com/post/{post_id}">
<script type="application/ld+json">{{"@type":"Article","headline":"{title}","datePublished":"2026-11-08T01:00:00Z","author":{{"name":"演示作者"}}}}</script>
</head><body><h1>{title}</h1><div class="article-body"><p>第一步：把收件箱中的任务按截止时间排序。</p><p>第二步：为每项补上下一动作和负责人。</p><p>第三步：每天结束时复核未完成项。</p></div></body></html>'''.encode()


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "private-workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_rss_to_pending_review_then_explicit_signed_viewer(self):
        feed_url = "https://sspai.com/feed"
        feed_raw = '''<?xml version="1.0"?><rss><channel><item><title>观察标题</title><link>https://sspai.com/post/12345</link><pubDate>Sun, 08 Nov 2026 01:00:00 GMT</pubDate></item></channel></rss>'''.encode()
        feed_calls = []
        def feed_transport(url, cap):
            feed_calls.append((url, cap))
            return {"http_status": 200, "final_url": url, "content_type": "application/rss+xml",
                    "body": feed_raw, "response_complete": True, "transport_error": None}

        discovered = discover_feed(self.workspace, "demo-run", feed_url, transport=feed_transport)
        self.assertEqual(len(feed_calls), 1)
        metadata_path = self.workspace / discovered["metadata_file"]
        metadata = json.loads(metadata_path.read_text())
        self.assertEqual(metadata["qualification"], "NOT_REVIEWED")
        self.assertEqual(metadata["records"][0]["status"], "METADATA_CANDIDATE")
        self.assertFalse(metadata["records"][0]["publication_time"])

        capture_calls = []
        page = synthetic_sspai_html()
        def capture_transport(url):
            capture_calls.append(url)
            return {"http_status": 200, "final_url": url, "content_type": "text/html; charset=utf-8",
                    "body": page, "response_complete": True, "transport_error": None, "headers": {}}

        captured = capture_run(self.workspace, "demo-run", transport=capture_transport)
        self.assertEqual(captured["state"], "CAPTURED_OR_SKIPPED")
        self.assertEqual(len(capture_calls), 1)
        pending = json.loads((self.workspace / "runs/demo-run/pending-review.json").read_text())
        row = pending["records"][0]
        folder = self.workspace / row["capture_folder"]
        raw = (folder / "source.html").read_bytes()
        body = (folder / "body.txt").read_bytes()
        extraction = json.loads((folder / "extraction.json").read_text())
        receipt = json.loads((folder / "fetch-receipt.json").read_text())
        self.assertEqual(row["review_status"], "PENDING_INDEPENDENT_REVIEW")
        self.assertIsNone(row["Q"])
        self.assertFalse(row["counts_toward_target"])
        self.assertEqual(row["source_html_sha256"], sha256(raw))
        self.assertEqual(row["body_sha256"], sha256(body))
        self.assertEqual(extraction["body_sha256"], sha256(body))
        self.assertEqual(receipt["source_html_sha256"], sha256(raw))
        self.assertIn("第一步", body.decode())

        body_text = body.decode()
        signed_rows = [{
            "record_id": "signed-pass", "account_name": "合成来源甲", "account_id": "synthetic-a",
            "title": row["title_page"], "source_url": row["url"], "published_at": row["published_at"],
            "Q": 4.0, "reference_status": "PASS", "counts_toward_target": True,
            "claim_verification": "SOURCE_REPORTED", "reason": "仅测试签收展示路径",
            "reason_codes": ["SYNTHETIC_TEST"], "evidence_refs": [row["capture_folder"]],
            "purpose": "合成测试记录", "body_text": body_text, "body_sha256": sha256(body),
        }, {
            "record_id": "signed-needs", "account_name": "合成来源乙", "account_id": "synthetic-b",
            "title": "合成待证条目", "source_url": "https://sspai.com/post/12346", "published_at": "",
            "Q": 3.0, "reference_status": "NEEDS_EVIDENCE", "counts_toward_target": False,
            "claim_verification": "NOT_APPLICABLE", "reason": "合成待证",
            "reason_codes": ["SYNTHETIC_TEST"], "evidence_refs": [], "body_text": "待证正文",
            "body_sha256": hashlib.sha256("待证正文".encode()).hexdigest(),
        }, {
            "record_id": "signed-exclude", "account_name": "合成来源丙", "account_id": "synthetic-c",
            "title": "合成排除条目", "source_url": "https://sspai.com/post/12347", "published_at": "",
            "Q": 1.0, "reference_status": "EXCLUDE", "counts_toward_target": False,
            "claim_verification": "NOT_APPLICABLE", "reason": "合成排除",
            "reason_codes": ["SYNTHETIC_TEST"], "evidence_refs": [], "body_text": "排除正文",
            "body_sha256": hashlib.sha256("排除正文".encode()).hexdigest(),
        }]
        acceptance = self.root / "signed-acceptance.json"
        acceptance.write_text(json.dumps({
            "schema": "public-workbench-signed-acceptance/v1",
            "signoff": {"status": "SIGNED", "reviewer": "synthetic-test", "signed_at": "2026-11-08T00:00:00+00:00",
                        "as_of": "2026-11-08T00:00:00+00:00",
                        "record_ids": [r["record_id"] for r in signed_rows]},
            "records": signed_rows,
        }, ensure_ascii=False, indent=2))
        viewer_root = self.root / "materialized-viewer"
        outcome = materialize_signed_workspace(acceptance, viewer_root)
        self.assertTrue(outcome["destination_created"])
        self.assertFalse(outcome["decisions_recomputed"])

        spec = importlib.util.spec_from_file_location("public_workbench_test_server", SERVER_PATH)
        server_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server_module)
        server_module.DATA_ROOT = viewer_root
        server_module.LEDGER = viewer_root / "ledger.csv"
        server_module.DIGITAL_LIFE_CATALOG = viewer_root / "digital_life_catalog.csv"
        server_module.DATABASE = viewer_root / "reference.sqlite3"
        server_module.REFERENCE_APPROVED = viewer_root / "approved.json"
        server_module.RESEARCH_NOTES = viewer_root / "research-notes.json"
        server_module.MEDIA_DIR = viewer_root / "media"
        server_module.MEDIA_MANIFEST = viewer_root / "media/manifest.json"
        server_module.MEDIA_ASSETS = viewer_root / "media/assets"
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            request = urllib.request.Request(base + "/api/digital-life-articles", headers={"Origin": base})
            listing = json.loads(urllib.request.urlopen(request).read())
            self.assertEqual(listing["reference_counts"]["PASS"], 1)
            self.assertEqual(listing["reference_counts"]["NEEDS_EVIDENCE"], 1)
            self.assertEqual(listing["reference_counts"]["EXCLUDE"], 1)
            self.assertEqual(listing["reference_counts"]["counts_toward_target"], 1)
            detail_req = urllib.request.Request(base + "/api/digital-life-articles/signed-pass", headers={"Origin": base})
            detail = json.loads(urllib.request.urlopen(detail_req).read())
            self.assertEqual(detail["body"], body_text)
            self.assertEqual(detail["article"]["reference_status"], "PASS")
            unknown = urllib.request.Request(base + "/api/digital-life-articles/no-such-id", headers={"Origin": base})
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(unknown)
            missing.exception.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_first_failure_stops_batch_and_cross_run_never_retries_previous_success_or_failure(self):
        from collectors.workflow import new_run
        urls = ["https://sspai.com/post/22331", "https://sspai.com/post/22332", "https://sspai.com/post/22333"]
        new_run(self.workspace, "stop-run", [{"url": u, "title": "synthetic"} for u in urls])
        calls = []
        def stop_transport(url):
            calls.append(url)
            if url.endswith("22331"):
                return {"http_status": 200, "final_url": url, "content_type": "text/html",
                        "body": synthetic_sspai_html("22331"), "response_complete": True,
                        "transport_error": None, "headers": {}}
            return {"http_status": 403, "final_url": url, "content_type": "text/html",
                    "body": b"forbidden", "response_complete": True,
                    "transport_error": None, "headers": {}}
        result = capture_run(self.workspace, "stop-run", transport=stop_transport)
        self.assertEqual(result["state"], "STOPPED")
        self.assertEqual(calls, urls[:2])
        manifest = json.loads((self.workspace / "runs/stop-run/run-manifest.json").read_text())
        self.assertEqual(manifest["unattempted_indices"], [2])
        new_run(self.workspace, "repeat-run", [{"url": u, "title": "synthetic"} for u in urls[:2]])
        no_calls = []
        repeat = capture_run(self.workspace, "repeat-run", transport=lambda url: no_calls.append(url))
        self.assertEqual(no_calls, [])
        self.assertEqual(repeat["captured"], 0)
        rows = json.loads((self.workspace / "runs/repeat-run/metadata-candidates.json").read_text())["records"]
        self.assertTrue(all(r["status"] == "PREVIOUSLY_ATTEMPTED" for r in rows))


if __name__ == "__main__":
    unittest.main()
