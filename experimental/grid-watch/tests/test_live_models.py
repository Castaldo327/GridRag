"""Offline tests for the live path: no API calls are made here."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataset import START
from engine import Engine
from live_models import guarded_query, validation_connection, validate_plan
from rules import RULES
from gridrag.db import QueryRejected

class FakeModel:
    decision_model='test-decision-model'
    plans={r.id:r.sql.replace('?', '$as_of') for r in RULES}
    def prepare(self):pass
    def usage(self):return {'calls':1,'decision_model':self.decision_model}
    def decide(self,evidence):
        # Deliberately disagree with the SQL matched flag, proving the live model
        # (rather than that flag) selects the alert result.
        return {rid:{'result':'match' if rid=='reserves' else 'clear','probabilities':[]} for rid in evidence['readings']}

class LivePathTests(unittest.TestCase):
    def test_sql_guard_blocks_writes_files_extra_statements_and_other_tables(self):
        c=validation_connection()
        try:
            for sql in ("DELETE FROM load_readings", "SELECT * FROM read_csv('/etc/passwd')", 'SELECT $as_of; SELECT 2', 'SELECT * FROM information_schema.tables', 'SELECT * FROM checks'):
                with self.subTest(sql=sql),self.assertRaises((QueryRejected,ValueError)):
                    guarded_query(c,sql,START)
        finally:c.close()

    def test_sql_requires_bound_time_and_checks_future_leakage(self):
        c=validation_connection()
        try:
            with self.assertRaises(ValueError):guarded_query(c,'SELECT * FROM load_readings',START)
            sql="SELECT ts, actual_mw, forecast_mw, round(100.0*(actual_mw/forecast_mw-1),2) AS above_forecast_pct FROM load_readings WHERE zone='Dominion' AND ts=$as_of"
            with self.assertRaises(ValueError):validate_plan(c,'forecast_gap',sql.replace('ts=$as_of','ts>=$as_of'))
            validate_plan(c,'forecast_gap',sql)
        finally:c.close()

    def test_live_decision_controls_result(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            e=Engine(tmp,model=FakeModel())
            try:
                self.assertEqual(e.states['reserves']['result'],'match')
                self.assertFalse(e.states['reserves']['evidence']['matched'])
                self.assertEqual(e.snapshot()['mode'],'live')
                self.assertEqual(e.states['reserves']['decision_source'],'test-decision-model')
            finally:e.close()

    def test_model_failure_is_unknown_and_pauses_without_scripted_fallback(self):
        class Broken(FakeModel):
            def decide(self,evidence):raise RuntimeError('Model unavailable')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            e=Engine(tmp,model=Broken())
            try:
                self.assertTrue(all(s['result']=='unknown' for s in e.states.values()))
                self.assertFalse(e.playing)
                self.assertEqual(e.snapshot()['notifications'],[])
                self.assertEqual(e.error,'Model unavailable')
                with self.assertRaises(ValueError):e.control('play')
            finally:e.close()

    def test_retry_rechecks_same_minute_after_provider_failure(self):
        class Once(FakeModel):
            failed=False
            def decide(self,evidence):
                if not self.failed:
                    self.failed=True
                    raise RuntimeError('decision model call failed (InternalServerError). No scripted fallback was used.')
                return super().decide(evidence)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            e=Engine(tmp,model=Once())
            try:
                e.control('retry')
                self.assertIsNone(e.error)
                self.assertEqual(e.index,0)
                self.assertEqual(e.states['reserves']['result'],'match')
                self.assertEqual(len(e.snapshot()['notifications']),1)
            finally:e.close()

if __name__=='__main__':unittest.main()
