import importlib.util
import tempfile
import sqlite3
import hashlib
import unittest
import csv
import json
import base64
import threading
import urllib.error
import urllib.request
from contextlib import closing
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location('viewer', Path(__file__).parents[1] / 'server.py')
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)

class CollectionView(unittest.TestCase):
    def test_http_boundary_rejects_untrusted_host_and_cross_origin(self):
        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(('127.0.0.1', 0), viewer.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            good = urllib.request.Request(base + '/api/runtime-info', headers={'Origin': base})
            with opener.open(good) as response:
                self.assertEqual(response.status, 200)
            bad_host = urllib.request.Request(base + '/api/runtime-info', headers={'Host': 'untrusted.invalid'})
            with self.assertRaises(urllib.error.HTTPError) as host_error:
                opener.open(bad_host)
            self.assertEqual(host_error.exception.code, 421)
            host_error.exception.close()
            bad_origin = urllib.request.Request(base + '/api/runtime-info', headers={'Origin': 'http://evil.invalid'})
            with self.assertRaises(urllib.error.HTTPError) as origin_error:
                opener.open(bad_origin)
            self.assertEqual(origin_error.exception.code, 421)
            origin_error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_media_manifest_is_fail_closed_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'manifest.json'
            assets = root / 'assets'
            assets.mkdir()
            old = (viewer.MEDIA_MANIFEST, viewer.MEDIA_ASSETS)
            viewer.MEDIA_MANIFEST, viewer.MEDIA_ASSETS = manifest, assets
            try:
                manifest.write_text(json.dumps({'version': '1.0', 'articles': {}}))
                self.assertEqual(viewer.article_media('missing')['status'], 'NOT_COLLECTED')
                self.assertEqual(viewer.article_media('missing')['images'], [])
                blob = base64.b64decode('R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=')
                digest = hashlib.sha256(blob).hexdigest()
                (assets / f'{digest}.gif').write_bytes(blob)
                image = {'sha256': digest, 'file': f'{digest}.gif', 'mime': 'image/gif', 'width': 1, 'height': 1,
                         'source_url': 'https://public.example/image.gif', 'captured_at': '2026-11-06T10:00:00+08:00',
                         'position': 'source img[1]', 'caption': '封面'}
                manifest.write_text(json.dumps({'version': '1.0', 'articles': {'record': {'status': 'VERIFIED', 'limitation': '仅供内部研究', 'images': [image]}}}))
                self.assertEqual(viewer.article_media('record')['images'][0]['sha256'], digest)
                image['sha256'] = '0' * 64
                manifest.write_text(json.dumps({'version': '1.0', 'articles': {'record': {'status': 'VERIFIED', 'limitation': '', 'images': [image]}}}))
                self.assertEqual(viewer.article_media('record')['status'], 'BLOCKED')
                image['sha256'] = digest
                image['file'] = '../' + f'{digest}.gif'
                manifest.write_text(json.dumps({'version': '1.0', 'articles': {'record': {'status': 'VERIFIED', 'limitation': '', 'images': [image]}}}))
                self.assertEqual(viewer.article_media('record')['images'], [])
                image['file'] = f'{digest}.gif'
                image['mime'] = 'image/svg+xml'
                manifest.write_text(json.dumps({'version': '1.0', 'articles': {'record': {'status': 'VERIFIED', 'limitation': '', 'images': [image]}}}))
                self.assertEqual(viewer.article_media('record')['status'], 'BLOCKED')
                image['mime'] = 'image/gif'
                image['source_url'] = 'https://user:pass@public.example/image.gif'
                manifest.write_text(json.dumps({'version': '1.0', 'articles': {'record': {'status': 'VERIFIED', 'limitation': '', 'images': [image]}}}))
                self.assertEqual(viewer.article_media('record')['status'], 'BLOCKED')
                manifest.write_text('{broken')
                self.assertEqual(viewer.article_media('record')['status'], 'BLOCKED')
            finally:
                viewer.MEDIA_MANIFEST, viewer.MEDIA_ASSETS = old

    def test_media_endpoint_only_serves_registered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / 'x.gif'
            blob = base64.b64decode('R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=')
            asset.write_bytes(blob)
            handler = object.__new__(viewer.Handler)
            handler.path = '/media/record/x.gif'
            handler.wfile = __import__('io').BytesIO()
            with patch.object(viewer, 'load_digital_life_articles', return_value=[{'id': 'record'}]), \
                 patch.object(viewer, 'article_media', return_value={'status': 'VERIFIED', 'limitation': '', 'images': [{'file': 'x.gif', 'mime': 'image/gif', 'sha256': hashlib.sha256(blob).hexdigest(), 'width': 1, 'height': 1}]}), \
                 patch.object(viewer, 'MEDIA_ASSETS', Path(directory)), patch.object(handler, 'send_response') as status, \
                 patch.object(handler, 'send_header'), patch.object(handler, 'end_headers'):
                handler.do_GET()
                status.assert_called_once_with(200)
                self.assertEqual(handler.wfile.getvalue(), blob)
                handler.path = '/media/record/../x.gif'
                handler.wfile = __import__('io').BytesIO()
                status.reset_mock()
                handler.do_GET()
                status.assert_called_once_with(404)

    def test_digital_detail_appends_media_without_changing_article_state(self):
        handler = object.__new__(viewer.Handler)
        handler.path = '/api/digital-life-articles/record'
        media = {'status': 'NOT_COLLECTED', 'limitation': '原图未采集', 'images': []}
        article = {'id': 'record', 'status': 'pending', 'body_hash': 'private'}
        with patch.object(viewer, 'load_digital_life_articles', return_value=[article]), \
             patch.object(viewer, 'matched_body', return_value=(None, None)), \
             patch.object(viewer, 'article_media', return_value=media), patch.object(handler, 'respond') as response:
            handler.do_GET()
        payload = response.call_args.args[0]
        self.assertEqual(payload['media'], media)
        self.assertEqual(payload['article']['status'], 'pending')
        self.assertNotIn('body_hash', payload['article'])

    def test_review_status_survives_technical_overlay_and_note_is_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / 'catalog.csv'
            notes = Path(directory) / 'notes.json'
            notes.write_text(json.dumps({'record': {'body_sha256': 'frozen', 'text': '<script>untrusted()</script>'}}))
            for review in ('READY_FOR_HUMAN_REVIEW', 'ORIGINAL_BODY_TECHNICALLY_ACCEPTED_QUALITY_NEEDS_EVIDENCE'):
                with self.subTest(review=review):
                    with catalog.open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=['record_id', 'metadata_state'])
                        writer.writeheader()
                        writer.writerow({'record_id': 'record', 'metadata_state': review})
                    technical = {'record': {'status': 'accepted', 'body_hash': 'frozen', 'updated_at': '2026-11-06'}}
                    with patch.object(viewer, 'DIGITAL_LIFE_CATALOG', catalog), patch.object(viewer, 'RESEARCH_NOTES', notes), patch.object(viewer, 'collection_index', return_value=technical), patch.object(viewer, 'matched_body', return_value=('body', 'local')):
                        article = viewer.load_digital_life_articles()[0]
                        self.assertEqual(article['status'], 'accepted')
                        self.assertEqual(article['review_status'], review)
                        self.assertEqual(article['research_note'], '<script>untrusted()</script>')
                        technical['record']['body_hash'] = 'changed'
                        self.assertNotIn('research_note', viewer.load_digital_life_articles()[0])

    def test_incomplete_markup_flushes_text(self):
        self.assertIn("保留正文", viewer.body_text("保留正文 <unfinished"))

    def test_plain_text_reader_preserves_yaml_indentation_entities_and_literal_tags(self):
        raw = "title: 示例\nconfig:\n  nested:\n    value: '&amp; <tag>'\n"
        self.assertEqual(viewer.body_text(raw, plain=True), raw)
        self.assertEqual(viewer.body_text("x" * (viewer.MAX_BODY_CHARS + 3), plain=True), "x" * viewer.MAX_BODY_CHARS)

    def test_matched_body_uses_plain_reader_only_for_known_source_contracts(self):
        raw = "title: 示例\nconfig:\n  nested:\n    value: '&amp; <tag>'\n"
        contracts = (
            'DataXAPI /v1/wechat_mp/articles/get; internal research only',
            'Publisher-native public HTML; not WeChat original; internal reference pending review',
        )
        for collector in contracts:
            with self.subTest(collector=collector), tempfile.TemporaryDirectory() as d:
                old = viewer.DATABASE
                viewer.DATABASE = Path(d) / 'test.db'
                try:
                    digest = hashlib.sha256(raw.encode()).hexdigest()
                    with closing(sqlite3.connect(viewer.DATABASE)) as db:
                        db.execute('create table public_article_bodies(body text, collector text, body_sha256 text)')
                        db.execute('insert into public_article_bodies values(?,?,?)', (raw, collector, digest))
                        db.commit()
                    self.assertEqual(viewer.matched_body({'body_hash': digest}), (raw, collector))
                    with closing(sqlite3.connect(viewer.DATABASE)) as db:
                        db.execute('update public_article_bodies set collector=?', ('unrecognized HTML source',))
                        db.commit()
                    text, source = viewer.matched_body({'body_hash': digest})
                    self.assertEqual(source, 'unrecognized HTML source')
                    self.assertEqual(text, "title: 示例\nconfig:\nnested:\nvalue: '& '")
                finally:
                    viewer.DATABASE = old

    def test_url_preserves_public_parameters(self):
        url = 'https://mp.weixin.qq.com/s?__biz=a&mid=1&idx=1&sn=b&chksm=c'
        self.assertEqual(viewer.safe_article_url(url), url)
        self.assertEqual(viewer.safe_article_url('https://mp.weixin.qq.com/s/abc_-'), 'https://mp.weixin.qq.com/s/abc_-')
        for url in ['https://mp.weixin.qq.com/s?__biz=a&mid=1&idx=1', 'https://mp.weixin.qq.com/s/a?sessionid=secret', 'https://mp.weixin.qq.com@evil.test/s/a']:
            self.assertIsNone(viewer.safe_article_url(url))

    def test_calendar_windows(self):
        self.assertEqual(viewer.recency('2026-10-05T08:00:00+08:00', '2026-11-05T08:00:00+08:00'), ('近1个月', 1.5))
        self.assertEqual(viewer.recency('2026-08-05T08:00:00+08:00', '2026-11-05T08:00:00+08:00'), ('1-3个月', 1.25))
        self.assertEqual(viewer.recency('2026-02-28T00:00:00+08:00', '2026-03-31T00:00:00+08:00'), ('近1个月', 1.5))
        self.assertEqual(viewer.recency('', '2026-11-05'), ('日期缺失', None))
        self.assertEqual(viewer.recency('2027-01-01', '2026-11-05'), ('日期缺失', None))

    def test_hash_checked_before_render(self):
        with tempfile.TemporaryDirectory() as d:
            old = viewer.DATABASE
            viewer.DATABASE = Path(d) / 'test.db'
            try:
                with closing(sqlite3.connect(viewer.DATABASE)) as db:
                    db.execute('create table public_article_bodies(body text, collector text, body_sha256 text)')
                    body = '真实正文<script>secret()</script>'
                    digest = hashlib.sha256(body.encode()).hexdigest()
                    db.execute('insert into public_article_bodies values(?,?,?)', (body, 'local', digest))
                    db.commit()
                self.assertEqual(viewer.matched_body({'body_hash': digest}), ('真实正文', 'local'))
                with closing(sqlite3.connect(viewer.DATABASE)) as db:
                    db.execute("update public_article_bodies set body='tampered'")
                    db.commit()
                self.assertEqual(viewer.matched_body({'body_hash': digest}), (None, None))
                self.assertEqual(viewer.collection_index(), {})
            finally:
                viewer.DATABASE = old

if __name__ == '__main__':
    unittest.main()
