import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_collection_view import viewer


class ReferenceView(unittest.TestCase):
    def record(self, **changes):
        return dict(record_id='one', body_hash='a' * 64, reference_status='PASS',
                    claim_verification='SOURCE_REPORTED', Q=4,
                    reason_codes=['SOURCE_ONLY'], reason='未亲测，可参考作者方法',
                    evidence_refs=['review.md#one'], counts_toward_target=True) | changes

    def article(self, **changes):
        return dict(id='one', body_hash='a' * 64, body_available=True,
                    recency_multiplier=1.5, status='accepted', review_status='OLD') | changes

    def test_approved_cases_do_not_infer_testing_or_quality(self):
        cases = [('PASS', '未亲测可参考', True), ('NEEDS_EVIDENCE', '缺图待核', False),
                 ('EXCLUDE', '关键错误排除', False), ('EXCLUDE', '摘要截断', False),
                 ('EXCLUDE', '重复', False)]
        for status, reason, counted in cases:
            with self.subTest(reason=reason):
                article = self.article()
                result = viewer.reference_decision(article, {'one': self.record(
                    reference_status=status, reason=reason, counts_toward_target=counted)})
                self.assertEqual(result['reference_status'], status)
                self.assertEqual(result['reference_reason'], reason)
                self.assertEqual(result['claim_verification'], 'SOURCE_REPORTED')
                self.assertEqual(result['counts_toward_target'], counted)
                self.assertEqual(result['reference_weighted_score'], 6)
                self.assertEqual(article['review_status'], 'OLD')
        self.assertIsNone(viewer.reference_decision(self.article(recency_multiplier=None),
                          {'one': self.record()})['reference_weighted_score'])

    def test_unknown_quality_is_preserved_only_for_nonpassing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            approved = Path(directory) / 'approved.json'
            with patch.object(viewer, 'REFERENCE_APPROVED', approved):
                for status in ('NEEDS_EVIDENCE', 'EXCLUDE'):
                    approved.write_text(json.dumps({'records': [self.record(
                        reference_status=status, Q=None, counts_toward_target=False)]}))
                    records = viewer.approved_references()
                    self.assertIn('one', records)
                    self.assertIsNone(viewer.reference_decision(self.article(), records)['reference_weighted_score'])
                missing = self.record(reference_status='NEEDS_EVIDENCE', counts_toward_target=False)
                del missing['Q']
                approved.write_text(json.dumps({'records': [missing]}))
                self.assertEqual(viewer.approved_references(), {})
                for quality in (None, 3):
                    approved.write_text(json.dumps({'records': [self.record(Q=quality)]}))
                    self.assertEqual(viewer.approved_references(), {})

    def test_missing_unapproved_hash_mismatch_and_fee_clear_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            approved = Path(directory) / 'approved.json'
            with patch.object(viewer, 'REFERENCE_APPROVED', approved):
                self.assertEqual(viewer.approved_references(), {})
                for raw in ('{broken', '{"records":{}}'):
                    approved.write_text(raw)
                    self.assertEqual(viewer.approved_references(), {})
                approved.write_text(json.dumps({'records': [self.record(), self.record()]}))
                self.assertEqual(viewer.approved_references(), {})
                approved.write_text(json.dumps({'records': [self.record()]}))
                self.assertIn('one', viewer.approved_references())
                for change in ({'Q': True}, {'counts_toward_target': 'false'}, {'Q': float('nan')},
                               {'reference_status': 'EXCLUDE'}, {'evidence_refs': 'file'}):
                    approved.write_text(json.dumps({'records': [self.record(**change)]}))
                    self.assertEqual(viewer.approved_references(), {})
        for article, approvals in [
            (self.article(review_status='FEE_CLEARED_NOT_REVIEWED'), {}),
            (self.article(body_hash='b' * 64), {'one': self.record()}),
            (self.article(body_available=False), {'one': self.record()}),
        ]:
            result = viewer.reference_decision(article, approvals)
            self.assertEqual(result['reference_status'], 'UNAPPROVED')
            self.assertFalse(result['counts_toward_target'])

    def test_endpoint_filters_and_counts_unique_bodies(self):
        rows = []
        for key, status in [('one', 'PASS'), ('copy', 'PASS'), ('needs', 'NEEDS_EVIDENCE')]:
            row = self.article(id=key, account='作者', title='文章', topic_id='C06', time_window='近1个月')
            row.update(viewer.reference_decision(row, {key: self.record(
                record_id=key, reference_status=status, counts_toward_target=status == 'PASS')}))
            rows.append(row)
        handler = object.__new__(viewer.Handler)
        handler.path = '/api/digital-life-articles?reference=PASS&claim=SOURCE_REPORTED'
        with patch.object(viewer, 'load_digital_life_articles', return_value=rows), patch.object(handler, 'respond') as response:
            handler.do_GET()
            payload = response.call_args.args[0]
        self.assertEqual(payload['count'], 2)
        self.assertEqual(payload['reference_counts']['counts_toward_target'], 1)
        self.assertEqual(payload['reference_counts']['NEEDS_EVIDENCE'], 0)
        self.assertNotIn('body_hash', payload['articles'][0])

    def test_loader_matches_sidecar_and_keeps_old_states(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / 'catalog.csv'
            catalog.write_text('record_id,metadata_state,published_at,quality_score_0_to_5,recency_multiplier\none,OLD,,3,1.5\n')
            technical = {'one': {'status': 'accepted', 'body_hash': 'a' * 64, 'updated_at': '2026-11-06'}}
            with patch.object(viewer, 'DIGITAL_LIFE_CATALOG', catalog), patch.object(viewer, 'collection_index', return_value=technical), patch.object(viewer, 'approved_references', return_value={'one': self.record()}), patch.object(viewer, 'matched_body', return_value=('body', 'local')):
                row = viewer.load_digital_life_articles()[0]
                self.assertEqual((row['status'], row['review_status'], row['quality']), ('accepted', 'OLD', '3'))
                self.assertEqual(row['reference_Q'], 4)
                self.assertIsNone(row['reference_weighted_score'])
                self.assertEqual(row['time_window'], '日期缺失')
                technical['one']['body_hash'] = 'b' * 64
                self.assertEqual(viewer.load_digital_life_articles()[0]['reference_status'], 'UNAPPROVED')
