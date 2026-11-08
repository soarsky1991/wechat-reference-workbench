#!/usr/bin/env python3
"""Local, read-only viewer for the existing WeChat research ledger."""

from __future__ import annotations

import argparse
import csv
import calendar
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import struct
from contextlib import closing
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEMO_WORKSPACE = PACKAGE_ROOT / "demo-workspace"
_external_workspace = os.environ.get("PUBLIC_WORKBENCH_DATA_DIR", "").strip()
DATA_ROOT = Path(_external_workspace).expanduser().resolve() if _external_workspace else DEMO_WORKSPACE.resolve()
DATA_MODE = "explicit-external-local-workspace" if _external_workspace else "bundled-synthetic-demo"
LEDGER = DATA_ROOT / "ledger.csv"
DIGITAL_LIFE_CATALOG = DATA_ROOT / "digital_life_catalog.csv"
DATABASE = DATA_ROOT / "reference.sqlite3"
WEB = PACKAGE_ROOT / "app" / "web"
ACCEPTED = {"ACCEPTED", "ACCEPTED_RECONSTRUCTED"}
MAX_BODY_CHARS = 800_000
PLAIN_TEXT_COLLECTORS = {
    "dataxapi /v1/wechat_mp/articles/get; internal research only",
    "publisher-native public html; not wechat original; internal reference pending review",
}
REFERENCE_APPROVED = DATA_ROOT / "approved.json"
RESEARCH_NOTES = DATA_ROOT / "research-notes.json"
MEDIA_DIR = DATA_ROOT / "media"
MEDIA_MANIFEST = MEDIA_DIR / "manifest.json"
MEDIA_ASSETS = MEDIA_DIR / "assets"
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def research_notes() -> dict:
    """Read only the fixed local sidecar; never accept a client file path."""
    try:
        if RESEARCH_NOTES.stat().st_size > 64_000:
            return {}
        data = json.loads(RESEARCH_NOTES.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def approved_references() -> dict:
    """Only the independent approval sidecar grants reference decisions."""
    try:
        if REFERENCE_APPROVED.stat().st_size > 8_000_000:
            return {}
        data = json.loads(REFERENCE_APPROVED.read_text(encoding="utf-8"))
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            return {}
        result, seen = {}, set()
        for record in records:
            if not isinstance(record, dict):
                continue
            key = record.get("record_id")
            if not isinstance(key, str) or not key:
                continue
            if key in seen:
                result.pop(key, None)  # Ambiguous approvals fail closed, regardless of order.
                continue
            seen.add(key)
            if (not isinstance(record.get("body_hash"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", record["body_hash"])
                    or record.get("reference_status") not in {"PASS", "NEEDS_EVIDENCE", "EXCLUDE"}
                    or record.get("claim_verification") not in {"SOURCE_REPORTED", "INDEPENDENTLY_TESTED", "NOT_APPLICABLE"}
                    or "Q" not in record
                    or (record.get("Q") is not None and (type(record["Q"]) not in (int, float)
                        or not math.isfinite(record["Q"]) or not 0 <= record["Q"] <= 5))
                    or (record.get("reference_status") == "PASS" and (record.get("Q") is None or record["Q"] < 3.5))
                    or not isinstance(record.get("reason"), str)
                    or not all(isinstance(record.get(field), list) and all(isinstance(v, str) for v in record[field])
                               for field in ("reason_codes", "evidence_refs"))
                    or type(record.get("counts_toward_target")) is not bool
                    or (record["counts_toward_target"] and record["reference_status"] != "PASS")):
                continue
            result[key] = record
        return result
    except (OSError, ValueError):
        return {}


def reference_decision(article: dict, approvals: dict) -> dict:
    record = approvals.get(article["id"])
    if not record:
        return {"reference_status": "UNAPPROVED", "reference_reason": "未独立批准或批准记录无效", "counts_toward_target": False}
    if not article["body_available"] or record["body_hash"] != article["body_hash"]:
        return {"reference_status": "UNAPPROVED", "reference_reason": "批准正文哈希不匹配或正文不可核验", "counts_toward_target": False}
    multiplier = article.get("recency_multiplier")
    return {
        "reference_status": record["reference_status"],
        "claim_verification": record["claim_verification"],
        "reference_Q": record["Q"],
        "reference_weighted_score": round(record["Q"] * float(multiplier), 4) if record["Q"] is not None and multiplier not in (None, "") else None,
        "reference_reason": record["reason"],
        "reference_reason_codes": record["reason_codes"],
        "reference_evidence_refs": record["evidence_refs"],
        "counts_toward_target": record["counts_toward_target"],
    }


def reference_counts(rows: list) -> dict:
    counts = {status: sum(r["reference_status"] == status for r in rows)
              for status in ("PASS", "NEEDS_EVIDENCE", "EXCLUDE", "UNAPPROVED")}
    # Same approved body can contribute to the target only once.
    counts["counts_toward_target"] = len({r["body_hash"] for r in rows if r["counts_toward_target"]})
    return counts


def article_media(record_id: str) -> dict:
    """Resolve only manifest-listed, hash-matched local raster images."""
    empty = {"status": "NOT_COLLECTED", "limitation": "原图未采集；此状态不表示原文没有图片。", "images": []}
    try:
        if MEDIA_MANIFEST.is_symlink() or MEDIA_MANIFEST.stat().st_size > 2_000_000:
            raise ValueError("manifest path/size invalid")
        manifest = json.loads(MEDIA_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("version") != "1.0" or not isinstance(manifest.get("articles"), dict):
            raise ValueError("manifest schema invalid")
        entry = manifest["articles"].get(record_id)
        if entry is None:
            return empty
        if (not isinstance(entry, dict) or entry.get("status") not in {"VERIFIED", "PARTIAL", "BLOCKED"}
                or not isinstance(entry.get("limitation"), str) or not isinstance(entry.get("images"), list)):
            raise ValueError("article media entry invalid")
        if entry["status"] == "BLOCKED":
            return {"status": "BLOCKED", "limitation": entry["limitation"], "images": []}
        if entry["status"] == "VERIFIED" and not entry["images"]:
            raise ValueError("verified media entry has no images")
        result = []
        for image in entry["images"]:
            if not isinstance(image, dict):
                raise ValueError("image entry invalid")
            digest, filename, mime = image.get("sha256"), image.get("file"), image.get("mime")
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or not isinstance(filename, str) or Path(filename).name != filename
                    or not isinstance(mime, str) or MEDIA_TYPES.get(Path(filename).suffix.lower()) != mime
                    or filename != f"{digest}{Path(filename).suffix.lower()}"
                    or type(image.get("width")) is not int or image["width"] <= 0
                    or type(image.get("height")) is not int or image["height"] <= 0
                    or not isinstance(image.get("source_url"), str)
                    or urlparse(image["source_url"]).scheme != "https"
                    or not urlparse(image["source_url"]).hostname
                    or urlparse(image["source_url"]).username is not None
                    or urlparse(image["source_url"]).password is not None
                    or not isinstance(image.get("captured_at"), str)
                    or not isinstance(image.get("position"), str)
                    or not re.fullmatch(r"source img\[\d+\]", image["position"])
                    or not isinstance(image.get("caption"), str)):
                raise ValueError("image metadata invalid")
            captured = datetime.fromisoformat(image["captured_at"].replace("Z", "+00:00"))
            if captured.tzinfo is None:
                raise ValueError("capture time must include timezone")
            asset = MEDIA_ASSETS / filename
            if asset.is_symlink() or not asset.is_file() or asset.resolve().parent != MEDIA_ASSETS.resolve():
                raise ValueError("asset path invalid")
            content = asset.read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("asset hash mismatch")
            if len(content) > 25_000_000 or not _image_signature_matches(content, mime):
                raise ValueError("asset mime/signature mismatch")
            dimensions = _image_dimensions(content, mime)
            if (dimensions != (image["width"], image["height"]) or image["width"] * image["height"] > 50_000_000):
                raise ValueError("asset dimensions mismatch")
            result.append({k: image[k] for k in ("sha256", "file", "mime", "width", "height", "source_url", "captured_at", "position", "caption")})
        return {"status": entry["status"], "limitation": entry["limitation"], "images": result}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"status": "BLOCKED", "limitation": "媒体登记或本地文件校验失败，已停止展示。", "images": []}


def _image_signature_matches(content: bytes, mime: str) -> bool:
    if mime == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    if mime == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def _image_dimensions(content: bytes, mime: str) -> tuple[int, int] | None:
    try:
        if mime == "image/png" and len(content) >= 24:
            return struct.unpack(">II", content[16:24])
        if mime == "image/gif" and len(content) >= 10:
            return struct.unpack("<HH", content[6:10])
        if mime == "image/webp" and len(content) >= 30:
            kind = content[12:16]
            if kind == b"VP8X":
                return (1 + int.from_bytes(content[24:27], "little"), 1 + int.from_bytes(content[27:30], "little"))
            if kind == b"VP8 " and len(content) >= 30 and content[23:26] == b"\x9d\x01\x2a":
                return (int.from_bytes(content[26:28], "little") & 0x3fff, int.from_bytes(content[28:30], "little") & 0x3fff)
            if kind == b"VP8L" and len(content) >= 25 and content[20] == 0x2f:
                bits = int.from_bytes(content[21:25], "little")
                return ((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1)
        if mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff"):
            i = 2
            while i + 9 < len(content):
                if content[i] != 0xff:
                    i += 1
                    continue
                marker = content[i + 1]
                i += 2
                if marker in {0xd8, 0xd9} or 0xd0 <= marker <= 0xd7:
                    continue
                if i + 2 > len(content):
                    break
                size = int.from_bytes(content[i:i + 2], "big")
                if size < 2 or i + size > len(content):
                    break
                if marker in {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf} and size >= 7:
                    return (int.from_bytes(content[i + 5:i + 7], "big"), int.from_bytes(content[i + 3:i + 5], "big"))
                i += size
    except (IndexError, ValueError, struct.error):
        return None
    return None


class PlainText(HTMLParser):
    """Discard markup and active content before returning text to the UI."""

    blocked = {"script", "style", "iframe", "object", "svg", "form", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.blocked:
            self.skip_depth += 1
        elif not self.skip_depth and tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.blocked and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def body_text(raw: str, plain: bool = False) -> str:
    if plain:
        return raw[:MAX_BODY_CHARS]
    parser = PlainText()
    parser.feed(raw[:MAX_BODY_CHARS])
    parser.close()
    text = "".join(parser.parts)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "\n[图片]\n", text)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]*\)", r"\1", text, flags=re.IGNORECASE)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def safe_article_url(value: str) -> str | None:
    # Display only a complete public sharing URL; never reconstruct a fetch URL.
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "mp.weixin.qq.com" or not re.fullmatch(r"/s(?:/[A-Za-z0-9_-]+)?", parsed.path):
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - {"__biz", "mid", "idx", "sn", "chksm", "scene"}:
        return None
    if parsed.path == "/s" and not all(query.get(k, [""])[0] for k in ("__biz", "mid", "idx", "sn")):
        return None
    return parsed._replace(fragment="").geturl()


def recency(published: str, as_of: str) -> tuple:
    try:
        now = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        date = datetime.fromisoformat(published.replace("Z", "+00:00"))
        zone = ZoneInfo("Asia/Shanghai")
        now = now.replace(tzinfo=zone) if now.tzinfo is None else now.astimezone(zone)
        date = date.replace(tzinfo=zone) if date.tzinfo is None else date.astimezone(zone)
        if date > now:
            return "日期缺失", None
        for months, label, multiplier in [(1, "近1个月", 1.5), (3, "1-3个月", 1.25), (6, "3-6个月", 1.0), (12, "6-12个月", .75)]:
            year, month = divmod(now.year * 12 + now.month - 1 - months, 12)
            boundary = now.replace(year=year, month=month + 1, day=min(now.day, calendar.monthrange(year, month + 1)[1]))
            if date >= boundary:
                return label, multiplier
        return "1年以上", .5
    except (ValueError, TypeError):
        return "日期缺失", None


def collection_index() -> dict:
    if not DATABASE.exists():
        return {}
    with closing(sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collector_articles'").fetchone():
            return {}
        return {r["record_id"]: dict(r) for r in db.execute("SELECT * FROM collector_articles")}


def collection_batches() -> list:
    with closing(sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='collector_batches'").fetchone():
            return []
        rows = []
        for r in db.execute("SELECT batch_id,status,created_at,summary_json FROM collector_batches ORDER BY created_at DESC LIMIT 20"):
            row = dict(r)
            row["summary"] = json.loads(row.pop("summary_json") or "{}")
            rows.append(row)
        return rows


def matched_body(article: dict) -> tuple:
    if not article.get("body_hash"):
        return None, None
    with closing(sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)) as db:
        row = db.execute("SELECT body,collector FROM public_article_bodies WHERE body_sha256=? AND length(body)>0 LIMIT 1", (article["body_hash"],)).fetchone()
        if row:
            # Body hashes are checked on each read, not just at collection time.
            if hashlib.sha256(row[0].encode()).hexdigest() == article["body_hash"]:
                collector = (row[1] or "").strip().casefold()
                return body_text(row[0], plain=collector in PLAIN_TEXT_COLLECTORS), row[1]
    return None, None


def load_articles() -> list[dict[str, str]]:
    with LEDGER.open(encoding="utf-8-sig", newline="") as source:
        rows = csv.DictReader(source)
        articles = []
        seen: set[str] = set()
        for row in rows:
            if row.get("target_status") not in ACCEPTED:
                continue
            identity = (row.get("article_identity") or "").strip()
            key = hashlib.sha256(identity.encode()).hexdigest() if identity else ""
            if not key or key in seen:
                continue
            seen.add(key)
            articles.append({
                "id": key,
                "topic_id": row.get("topic_id", ""),
                "topic": row.get("topic", ""),
                "account": row.get("account_name", ""),
                "title": row.get("title", ""),
                "published_at": row.get("published_at", ""),
                "status": row.get("target_status", ""),
                "quality": row.get("internal_quality_score_0_to_5", ""),
                "body_hash": row.get("body_sha256", ""),
                "url": safe_article_url(identity),
            })
        articles.sort(key=lambda row: (bool(row["published_at"]), row["published_at"]), reverse=True)
        return articles


def load_digital_life_articles() -> list[dict[str, str]]:
    if not DIGITAL_LIFE_CATALOG.is_file():
        return []
    index = collection_index()
    notes = research_notes()
    approvals = approved_references()
    with DIGITAL_LIFE_CATALOG.open(encoding="utf-8-sig", newline="") as source:
        articles = []
        for row in csv.DictReader(source):
            articles.append({
                "id": row.get("record_id", ""),
                "topic_id": row.get("topic_id", ""),
                "topic": "AI工具与工作流" if row.get("topic_id") == "C06" else "消费数码与软件工具",
                "account": row.get("account_name", ""),
                "title": row.get("title", ""),
                "published_at": row.get("published_at", ""),
                "time_window": row.get("time_window_as_of_2026-11-06") or row.get("time_window_as_of_2026-11-05", ""),
                "recency_multiplier": row.get("recency_multiplier", ""),
                "status": row.get("metadata_state", ""),
                "review_status": row.get("metadata_state", ""),
                "quality": row.get("quality_score_0_to_5", ""),
                "recency_weighted_score": row.get("recency_weighted_score", ""),
                "url": safe_article_url(row.get("article_url_clean", "") or ""),
                "body_hash": "",
            })
        for article in articles:
            collected = index.get(article["id"])
            if collected:
                article.update(status=collected["status"], body_hash=collected.get("body_hash") or "",
                               error_category=collected.get("error_category") or "",
                               error_message=collected.get("error_message") or "",
                               is_new=bool(collected.get("is_new")))
                article["published_at"] = collected.get("published_at") or article["published_at"]
                window, multiplier = recency(article["published_at"], collected.get("as_of") or collected["updated_at"])
                article["time_window"] = window
                article["recency_multiplier"] = multiplier
                article["recency_as_of"] = collected.get("as_of") or collected["updated_at"]
                article["recency_weighted_score"] = float(article["quality"]) * multiplier if article.get("quality") and multiplier else None
            else:
                article["status"] = "pending"
            if not article["published_at"]:
                article["time_window"], article["recency_multiplier"] = "日期缺失", None
            note = notes.get(article["id"], {})
            if (isinstance(note, dict) and article.get("body_hash")
                    and note.get("body_sha256") == article["body_hash"]
                    and isinstance(note.get("text"), str)):
                article["research_note"] = note["text"][:4000]
            article["body_available"] = bool(matched_body(article)[0])
            article.update(reference_decision(article, approvals))
        articles.sort(key=lambda row: (bool(row["published_at"]), row["published_at"]), reverse=True)
        return articles


def available_body_hashes() -> set[str]:
    uri = f"file:{DATABASE}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return {row[0] for row in db.execute(
            "SELECT DISTINCT body_sha256 FROM public_article_bodies WHERE length(body)>0"
        )}


def local_request_allowed(handler) -> bool:
    """Reject hostile Host/Origin before serving any local workspace data."""
    server = getattr(handler, "server", None)
    if server is None:  # Direct unit calls have no socket or network boundary.
        return True
    host_header = handler.headers.get("Host", "")
    try:
        parsed = urlparse("//" + host_header)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    if host not in {"127.0.0.1", "localhost"} or port != server.server_port:
        return False
    origin = handler.headers.get("Origin")
    if origin:
        try:
            parsed_origin = urlparse(origin)
            origin_host = (parsed_origin.hostname or "").lower()
            origin_port = parsed_origin.port
        except ValueError:
            return False
        if parsed_origin.scheme != "http" or origin_host != host or origin_port != port:
            return False
    fetch_site = handler.headers.get("Sec-Fetch-Site")
    if fetch_site and fetch_site not in {"same-origin", "none"}:
        return False
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "PublicWorkbench/0.1"

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()

    def respond(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not local_request_allowed(self):
            self.respond({"error": "只允许本机同源请求"}, 421)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path == "/api/runtime-info":
            self.respond({"data_mode": DATA_MODE, "read_only": True, "network_collection": False})
            return
        if parsed.path == "/api/collection-batches":
            self.respond({"batches": collection_batches()})
            return
        if parsed.path == "/api/digital-life-articles":
            params = parse_qs(parsed.query)
            account = params.get("account", [""])[0].casefold()
            query = params.get("q", [""])[0].casefold().strip()
            topic = params.get("topic", [""])[0]
            window = params.get("window", [""])[0]
            rows = load_digital_life_articles()
            if account:
                rows = [r for r in rows if account in r["account"].casefold()]
            if query:
                rows = [r for r in rows if query in f"{r['title']} {r['account']}".casefold()]
            if topic:
                rows = [r for r in rows if r["topic_id"] == topic]
            if window:
                rows = [r for r in rows if r["time_window"] == window]
            body_filter = params.get("body", [""])[0]
            if body_filter in {"available", "missing"}:
                rows = [r for r in rows if r["body_available"] == (body_filter == "available")]
            status_filter = params.get("status", [""])[0]
            if status_filter:
                rows = [r for r in rows if r["status"] == status_filter]
            for param, field in (("reference", "reference_status"), ("claim", "claim_verification")):
                value = params.get(param, [""])[0]
                if value:
                    rows = [r for r in rows if r.get(field) == value]
            counts = reference_counts(rows)
            rows = [{k: v for k, v in row.items() if k != "body_hash"} for row in rows]
            self.respond({"count": len(rows), "articles": rows, "reference_counts": counts})
            return

        if parsed.path.startswith("/api/digital-life-articles/"):
            article_id = parsed.path.rsplit("/", 1)[-1]
            article = next((r for r in load_digital_life_articles() if r["id"] == article_id), None)
            if not article:
                self.respond({"error": "文章不存在"}, 404)
                return
            body, source = matched_body(article)
            media = article_media(article_id)
            for image in media["images"]:
                image["url"] = f"/media/{quote(article_id, safe='')}/{quote(image['file'], safe='')}"
            self.respond({"article": {k: v for k, v in article.items() if k != "body_hash"}, "body": body, "body_source": source, "media": media})
            return

        if parsed.path.startswith("/media/"):
            parts = parsed.path.split("/")
            if len(parts) != 4:
                self.respond({"error": "未找到"}, 404)
                return
            article_id, filename = unquote(parts[2]), unquote(parts[3])
            if not any(a["id"] == article_id for a in load_digital_life_articles()):
                self.respond({"error": "未找到"}, 404)
                return
            media = article_media(article_id)
            image = next((image for image in media["images"] if image["file"] == filename), None)
            if not image:
                self.respond({"error": "未找到"}, 404)
                return
            asset = MEDIA_ASSETS / filename
            try:
                fd = os.open(asset, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("not a regular image")
                    content = stream.read(25_000_001)
            except (OSError, ValueError):
                self.respond({"error": "未找到"}, 404)
                return
            dimensions = _image_dimensions(content, image["mime"])
            if (len(content) > 25_000_000 or hashlib.sha256(content).hexdigest() != image["sha256"]
                    or not _image_signature_matches(content, image["mime"])
                    or dimensions != (image["width"], image["height"])):
                self.respond({"error": "未找到"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", MEDIA_TYPES[asset.suffix.lower()])
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if parsed.path == "/api/articles":
            params = parse_qs(parsed.query)
            topic = params.get("topic", [""])[0]
            account = params.get("account", [""])[0].casefold()
            query = params.get("q", [""])[0].casefold().strip()
            month = params.get("month", [""])[0]
            body_filter = params.get("body", [""])[0]
            rows = load_articles()
            body_hashes = available_body_hashes()
            if topic:
                rows = [r for r in rows if r["topic_id"] == topic]
            if account:
                rows = [r for r in rows if account in r["account"].casefold()]
            if re.fullmatch(r"\d{4}-\d{2}", month):
                rows = [r for r in rows if r["published_at"].startswith(month)]
            if query:
                rows = [r for r in rows if query in f"{r['title']} {r['account']} {r['topic']}".casefold()]
            if body_filter in {"available", "missing"}:
                rows = [r for r in rows if (r["body_hash"] in body_hashes) == (body_filter == "available")]
            rows = [{k: v for k, v in row.items() if k != "body_hash"} | {"body_available": row["body_hash"] in body_hashes} for row in rows]
            self.respond({"count": len(rows), "articles": rows})
            return

        if parsed.path.startswith("/api/articles/"):
            article_id = parsed.path.rsplit("/", 1)[-1]
            article = next((r for r in load_articles() if r["id"] == article_id), None)
            if not article:
                self.respond({"error": "文章不存在"}, 404)
                return
            body = None
            body_source = None
            if article["body_hash"]:
                uri = f"file:{DATABASE}?mode=ro"
                with closing(sqlite3.connect(uri, uri=True)) as db:
                    row = db.execute(
                        "SELECT body, collector FROM public_article_bodies WHERE body_sha256=? AND length(body)>0 LIMIT 1",
                        (article["body_hash"],),
                    ).fetchone()
                    if row and hashlib.sha256(row[0].encode()).hexdigest() == article["body_hash"]:
                        body = body_text(row[0])
                        collector = (row[1] or "").casefold()
                        body_source = "DataXAPI" if "dataxapi" in collector else "Firecrawl" if "firecrawl" in collector else "本地研究库（来源类型未归一）"
            self.respond({"article": {k: v for k, v in article.items() if k != "body_hash"}, "body": body, "body_source": body_source})
            return

        if parsed.path in {"/", "/index.html"}:
            return self.static("index.html", "text/html; charset=utf-8")
        if parsed.path in {"/app.css", "/app.js", "/favicon.svg"}:
            name = parsed.path.lstrip("/")
            mime = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8" if name.endswith(".js") else "image/svg+xml"
            return self.static(name, mime)
        self.respond({"error": "未找到"}, 404)

    def static(self, name: str, mime: str) -> None:
        path = WEB / name
        if not path.is_file() or path.resolve().parent != WEB.resolve():
            return self.respond({"error": "未找到"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="本地只读参考资料工作台（默认使用包内合成演示数据）")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    required = (LEDGER, DIGITAL_LIFE_CATALOG, DATABASE, REFERENCE_APPROVED)
    missing = [p.name for p in required if not p.is_file()]
    if missing:
        raise SystemExit("工作区缺少必需文件：" + ", ".join(missing) + "。默认使用包内 demo-workspace；外部工作区须显式设置 PUBLIC_WORKBENCH_DATA_DIR。")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"参考资料工作台运行于 http://127.0.0.1:{args.port} （只读，仅本机；数据模式：{DATA_MODE}）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
