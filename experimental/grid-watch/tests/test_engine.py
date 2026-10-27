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

    def test_all_five_scenarios_fire_once_at_expected_times_then_recover(self):
        self.e.advance(40)
        got={n['rule_id']:n['ts'] for n in self.triggers()}
        self.assertEqual(got,{'line_out':'2026-07-22T18:00:00Z','load_drop':'2026-07-22T18:02:00Z','reserves':'2026-07-22T18:04:00Z','congestion':'2026-07-22T18:05:00Z','combined':'2026-07-22T18:07:00Z'})
        self.assertEqual(len(self.triggers()),5)
        self.assertEqual(len(self.e.snapshot()['notifications']),10)
        self.assertTrue(all(r['result']=='clear' for r in self.e.snapshot()['rules']))
        self.assertEqual(self.e.checks,205)
        self.assertFalse(self.e.playing)

    def test_distractor_outages_do_not_match_voltage_or_region(self):
        self.e.advance(19)
        self.assertEqual(self.triggers(),[])
        self.assertEqual(self.e.states['line_out']['result'],'clear')
        self.e.advance()
        self.assertEqual([a['rule_id'] for a in self.triggers()],['line_out'])

    def test_load_drop_is_strictly_greater_than_1000(self):
        old=self.e.conn.execute('SELECT actual_mw FROM load_readings WHERE ts=?',[START-timedelta(minutes=10)]).fetchone()[0]
        sql=BY_ID['load_drop'].sql
        self.e.conn.execute('UPDATE load_readings SET actual_mw=? WHERE ts=?',[old-1000,START])
        self.assertFalse(self.e.query(sql,[START])[0]['matched'])
        self.e.conn.execute('UPDATE load_readings SET actual_mw=? WHERE ts=?',[old-1000.1,START])
        self.assertTrue(self.e.query(sql,[START])[0]['matched'])

    def test_combined_requires_both_conditions(self):
        sql=BY_ID['combined'].sql
        self.e.conn.execute('UPDATE load_readings SET actual_mw=13000, forecast_mw=12000 WHERE ts=?',[START])
        self.assertFalse(self.e.query(sql,[START])[0]['matched'])
        self.e.conn.execute("UPDATE line_readings SET status='out' WHERE line_id='NVA-230-01' AND ts=?",[START])
        self.assertTrue(self.e.query(sql,[START])[0]['matched'])
        self.e.conn.execute('UPDATE load_readings SET actual_mw=12600 WHERE ts=?',[START])
        self.assertFalse(self.e.query(sql,[START])[0]['matched'])

    def test_no_future_data_or_events_and_baseline_excludes_current(self):
        self.assertEqual(self.e.snapshot()['events'],[])
        self.assertEqual(len(self.e.snapshot()['history']),1)
        before=self.e.query(BY_ID['congestion'].sql,[START]*3)[0]
        self.e.conn.execute('INSERT INTO congestion_readings VALUES (?, ?, ?)',[START+timedelta(days=1),'NVA-DEMO-01',99999])
        self.e.conn.execute('UPDATE congestion_readings SET congestion_per_mwh=99999 WHERE ts=?',[START])
        after=self.e.query(BY_ID['congestion'].sql,[START]*3)[0]
        self.assertEqual(before['p95'],after['p95'])
        self.assertEqual(before['sample_count'],after['sample_count'])
        self.assertTrue(after['matched'])

    def test_missing_fresh_data_is_unknown_not_recovery(self):
        self.e.advance(24)
        self.assertEqual(self.e.states['reserves']['result'],'match')
        self.e.conn.execute('DELETE FROM reserve_readings WHERE ts=?',[self.e.now])
        self.e.evaluate()
        self.assertEqual(self.e.states['reserves']['result'],'unknown')
        recoveries=self.e.query("SELECT * FROM notifications WHERE rule_id='reserves' AND kind='recovered'")
        self.assertEqual(recoveries,[])

    def test_tasks_are_local_idempotent_and_can_be_automatic(self):
        self.e.update_rule('line_out',auto_action=True)
        self.e.advance(20)
        alert=self.triggers()[0]
        first=self.e.create_task(alert['id']);second=self.e.create_task(alert['id'])
        self.assertEqual(first,second)
        self.assertEqual(len(self.e.snapshot()['tasks']),1)
        with self.assertRaises(ValueError): self.e.create_task('not-an-alert')

    def test_paused_watch_resumes_and_reset_rebuilds_cleanly(self):
        self.e.update_rule('line_out',enabled=False)
        self.e.advance(20)
        self.assertEqual(self.triggers(),[])
        self.e.update_rule('line_out',enabled=True)
        self.e.advance()
        self.assertEqual(self.triggers()[0]['rule_id'],'line_out')
        self.e.reset()
        self.assertEqual(self.e.index,0)
        self.assertEqual(self.e.snapshot()['notifications'],[])
        self.assertEqual(self.e.checks,5)

    def test_schema_changes_pause_replay(self):
        self.e.control('play')
        self.assertTrue(self.e.validate_schema()['unchanged'])
        self.e.conn.execute('ALTER TABLE load_readings ADD COLUMN test_column INTEGER')
        self.assertFalse(self.e.validate_schema()['unchanged'])
        self.assertFalse(self.e.playing)
        self.assertIsNotNone(self.e.error)

    def test_review_tracks_main_and_distractor_changes_in_order(self):
        self.e.advance(40)
        events=self.e.snapshot()['events']
        self.assertEqual(len(events),9)
        self.assertEqual(events,sorted(events,key=lambda e:e['ts']))
        self.assertIn('115 kV',events[0]['description'])
        self.assertIn('returns to service',events[-1]['description'])

if __name__=='__main__':unittest.main()
