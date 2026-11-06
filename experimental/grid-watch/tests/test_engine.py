"""Offline behavioral checks; no external services or paid model calls."""
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import Engine
from dataset import START
from rules import BY_ID

class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.e=Engine(self.temp.name)
    def tearDown(self):
        self.e.close();self.temp.cleanup()
    def triggers(self):
        return [n for n in self.e.snapshot()['notifications'] if n['kind']=='triggered']

    def test_all_four_scenarios_fire_once_at_expected_times_then_recover(self):
        self.e.advance(8)
        got={n['rule_id']:n['ts'] for n in self.triggers()}
        self.assertEqual(got,{'load_drop':'2026-07-22T18:05:00Z','reserves':'2026-07-22T18:05:00Z','congestion':'2026-07-22T18:05:00Z','forecast_gap':'2026-07-22T18:10:00Z'})
        self.assertEqual(len(self.triggers()),4)
        self.assertEqual(len(self.e.snapshot()['notifications']),8)
        self.assertTrue(all(r['result']=='clear' for r in self.e.snapshot()['rules']))
        self.assertEqual(self.e.checks,36)
        self.assertFalse(self.e.playing)

    def test_one_tick_ingests_five_minutes_and_evaluates_once(self):
        self.e.control('step')
        self.assertEqual(self.e.index,5)
        self.assertEqual(self.e.now,START+timedelta(minutes=5))
        self.assertEqual(self.e.checks,8)
        self.assertEqual(len(self.e.snapshot()['history']),6)
        checked=self.e.conn.execute('SELECT DISTINCT ts FROM checks ORDER BY ts').fetchall()
        self.assertEqual(checked,[(START,),(START+timedelta(minutes=5),)])
        self.e.control('jump')
        self.assertEqual(self.e.index,20)
        self.assertEqual(self.e.checks,20)
        self.e.control('finish')
        self.assertEqual(self.e.index,40)
        self.assertEqual(self.e.checks,36)

    def test_load_drop_is_strictly_greater_than_1000(self):
        old=self.e.conn.execute('SELECT actual_mw FROM load_readings WHERE ts=?',[START-timedelta(minutes=10)]).fetchone()[0]
        sql=BY_ID['load_drop'].sql
        self.e.conn.execute('UPDATE load_readings SET actual_mw=? WHERE ts=?',[old-1000,START])
        self.assertFalse(self.e.query(sql,[START])[0]['matched'])
        self.e.conn.execute('UPDATE load_readings SET actual_mw=? WHERE ts=?',[old-1000.1,START])
        self.assertTrue(self.e.query(sql,[START])[0]['matched'])

    def test_forecast_gap_is_strictly_above_five_percent(self):
        sql=BY_ID['forecast_gap'].sql
        for actual, expected in [(12600,False),(12601,True),(12599,False)]:
            self.e.conn.execute('UPDATE load_readings SET actual_mw=?, forecast_mw=12000 WHERE ts=?',[actual,START])
            self.assertEqual(self.e.query(sql,[START])[0]['matched'],expected)

    def test_no_future_data_and_baseline_excludes_current(self):
        self.assertEqual(len(self.e.snapshot()['history']),1)
        before=self.e.query(BY_ID['congestion'].sql,[START]*3)[0]
        self.e.conn.execute('INSERT INTO congestion_readings VALUES (?, ?, ?)',[START+timedelta(days=1),'NVA-DEMO-01',99999])
        self.e.conn.execute('UPDATE congestion_readings SET congestion_per_mwh=99999 WHERE ts=?',[START])
        after=self.e.query(BY_ID['congestion'].sql,[START]*3)[0]
        self.assertEqual(before['p95'],after['p95'])
        self.assertEqual(before['sample_count'],after['sample_count'])
        self.assertTrue(after['matched'])

    def test_missing_fresh_data_is_unknown_not_recovery(self):
        self.e.advance(5)
        self.assertEqual(self.e.states['reserves']['result'],'match')
        self.e.conn.execute('DELETE FROM reserve_readings WHERE ts=?',[self.e.now])
        self.e.evaluate()
        self.assertEqual(self.e.states['reserves']['result'],'unknown')
        recoveries=self.e.query("SELECT * FROM notifications WHERE rule_id='reserves' AND kind='recovered'")
        self.assertEqual(recoveries,[])

    def test_tasks_are_local_idempotent_and_can_be_automatic(self):
        self.e.update_rule('load_drop',auto_action=True)
        self.e.advance(5)
        alert=next(a for a in self.triggers() if a['rule_id']=='load_drop')
        first=self.e.create_task(alert['id']);second=self.e.create_task(alert['id'])
        self.assertEqual(first,second)
        self.assertEqual(len(self.e.snapshot()['tasks']),1)
        with self.assertRaises(ValueError): self.e.create_task('not-an-alert')

    def test_paused_watch_resumes_and_reset_rebuilds_cleanly(self):
        self.e.update_rule('load_drop',enabled=False)
        self.e.advance(4)
        self.assertEqual(self.triggers(),[])
        self.e.update_rule('load_drop',enabled=True)
        self.e.advance()
        self.assertIn('load_drop',[n['rule_id'] for n in self.triggers()])
        self.e.reset()
        self.assertEqual(self.e.index,0)
        self.assertEqual(self.e.snapshot()['notifications'],[])
        self.assertEqual(self.e.checks,4)

    def test_schema_changes_pause_replay(self):
        self.e.control('play')
        self.assertTrue(self.e.validate_schema()['unchanged'])
        self.e.conn.execute('ALTER TABLE load_readings ADD COLUMN test_column INTEGER')
        self.assertFalse(self.e.validate_schema()['unchanged'])
        self.assertFalse(self.e.playing)
        self.assertIsNotNone(self.e.error)

    def test_snapshot_contains_only_reported_measurement_watches(self):
        snapshot=self.e.snapshot()
        self.assertEqual({r['id'] for r in snapshot['rules']},{'load_drop','reserves','congestion','forecast_gap'})
        self.assertNotIn('events',snapshot)
        self.assertNotIn('review_summary',snapshot)
        self.assertNotIn('outage_count',snapshot['metrics'])
        tables={r[0] for r in self.e.conn.execute('SHOW TABLES').fetchall()}
        self.assertNotIn('source_events',tables)
        self.assertNotIn('line_readings',tables)

if __name__=='__main__':unittest.main()
