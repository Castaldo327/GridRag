"""Local replay, SQL polling, alert state and a local-only action destination."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import threading
import time

import duckdb
from dataset import START, END, SCHEMA, frame, ingest, seed, export_fixture
from rules import RULES, BY_ID, explain

ROOT=Path(__file__).resolve().parent
POLL_MINUTES=5

def clean(value):
    if isinstance(value, datetime): return value.isoformat()+'Z'
    if isinstance(value, dict): return {k:clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [clean(v) for v in value]
    return value

class Engine:
    def __init__(self, directory=None, tick_seconds=2.0, model=None):
        self.directory=Path(directory) if directory else ROOT/'runtime'
        self.directory.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.changed=threading.Condition(self.lock)
        self.stop=threading.Event()
        self.tick_seconds=tick_seconds
        self.model=model
        self.phase="ready"
        self.conn=None
        self.version=0
        self.playing=False
        self.error=None
        self.reset()

    def query(self, sql, params=()):
        cursor=self.conn.execute(sql,params)
        columns=[x[0] for x in cursor.description]
        return [dict(zip(columns,row)) for row in cursor.fetchall()]

    def reset(self):
        with self.lock:
            self.playing=False
            if self.conn: self.conn.close()
            path=self.directory/'grid.duckdb'
            if path.exists(): path.unlink()
            self.conn=duckdb.connect(str(path),config={'memory_limit':'256MB','threads':2,'temp_directory':''})
            self.conn.execute('SET enable_external_access=false')
            seed(self.conn)
            self.conn.execute('SET lock_configuration=true')
            if self.model: self.model.prepare()
            self.phase="ready"
            self.conn.execute('''CREATE TABLE notifications(id VARCHAR PRIMARY KEY, rule_id VARCHAR, ts TIMESTAMP, kind VARCHAR, summary VARCHAR, evidence JSON);
CREATE TABLE tasks(id VARCHAR PRIMARY KEY, alert_id VARCHAR UNIQUE, created_at TIMESTAMP, title VARCHAR, status VARCHAR);
CREATE TABLE checks(ts TIMESTAMP, rule_id VARCHAR, result VARCHAR, summary VARCHAR, evidence JSON, elapsed_ms DOUBLE);''')
            self.index=0
            self.enabled={r.id:True for r in RULES}
            self.auto_action={r.id:False for r in RULES}
            self.states={}
            self.checks=0
            self.error=None
            self.schema_fingerprint=self.fingerprint()
            self.schema_checked_at=START
            self.next_schema_check=time.monotonic()+86400
            self.evaluate()
            export_fixture(self.directory)
            (self.directory/'saved_rules.json').write_text(json.dumps([{**asdict(r),'sql':self.model.plans[r.id] if self.model else r.sql} for r in RULES],indent=2))
            self.publish()

    @property
    def now(self): return frame(self.index)['ts']

    def fingerprint(self):
        columns=self.conn.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_name IN ('load_readings','reserve_readings','reserve_history','congestion_readings') ORDER BY 1,2").fetchall()
        return hashlib.sha256(repr(columns).encode()).hexdigest()[:12]

    def validate_schema(self):
        with self.lock:
            current=self.fingerprint()
            same=current == self.schema_fingerprint
            self.schema_checked_at=self.now
            self.next_schema_check=time.monotonic()+86400
            if not same:
                self.playing=False
                self.error='The database structure changed. Replay paused; restart the demo to rebuild its saved queries.'
            self.publish()
            return {'unchanged':same,'fingerprint':current}

    def evaluate(self):
        readings={}
        timings={}
        valid_rows={}
        for rule in RULES:
            if not self.enabled[rule.id]: continue
            started=time.perf_counter()
            try:
                if self.model:
                    from live_models import guarded_query
                    result_rows=guarded_query(self.conn,self.model.plans[rule.id],self.now)
                else:
                    result_rows=self.query(rule.sql,[self.now]*rule.sql.count('?'))
                row=result_rows[0] if len(result_rows)==1 else None
                valid=row is not None and row.get('ts')==self.now
                if rule.id in ('reserves','congestion') and row is not None:
                    valid=valid and row.get('sample_count',0)>0
                if not self.model:valid=valid and row.get('matched') is not None if row else False
            except Exception as exc:
                row=None;valid=False
                self.playing=False
                self.error=f'A saved query failed ({type(exc).__name__}). Reset the demo to rebuild its database.'
            readings[rule.id]=clean(row)
            valid_rows[rule.id]=valid
            timings[rule.id]=round((time.perf_counter()-started)*1000,2)
        decisions={}
        if self.model and readings:
            self.phase='deciding'
            self.publish()
            try:
                decisions=self.model.decide({'as_of':clean(self.now),'readings':readings})
            except Exception as exc:
                self.playing=False
                self.error=str(exc)
            finally:self.phase='ready'
        for rule in RULES:
            if rule.id not in readings:continue
            row=readings[rule.id]
            decision=decisions.get(rule.id,{})
            if self.model:result=decision.get('result','unknown')
            else:result=('match' if row['matched'] else 'clear') if valid_rows[rule.id] else 'unknown'
            if not valid_rows[rule.id] or result not in ('match','clear','unknown'):result='unknown'
            summary=explain(rule.id,{**row,'matched':result=='match'}) if row and result!='unknown' else 'Not enough fresh data or a valid model answer to decide.'
            self.checks+=1
            state={'result':result,'summary':summary,'evidence':row,'checked_at':clean(self.now),'elapsed_ms':timings[rule.id],
                   'decision_source':self.model.decision_model if self.model else 'scripted','probabilities':decision.get('probabilities',[])}
            self.states[rule.id]=state
            self.conn.execute('INSERT INTO checks VALUES (?, ?, ?, ?, ?, ?)',[self.now,rule.id,result,summary,json.dumps(row),timings[rule.id]])
            open_incident=self.query("SELECT kind FROM notifications WHERE rule_id=? ORDER BY ts DESC, id DESC LIMIT 1",[rule.id])
            incident_active=bool(open_incident and open_incident[0]['kind']=='triggered')
            kind=None
            if result=='match' and not incident_active:kind='triggered'
            elif result=='clear' and incident_active:kind='recovered'
            if kind:
                key=f'{rule.id}:{self.index}:{kind}'
                self.conn.execute('INSERT INTO notifications VALUES (?, ?, ?, ?, ?, ?)',[key,rule.id,self.now,kind,summary,json.dumps(row)])
                if kind=='triggered' and self.auto_action[rule.id]:self.make_task(key)

    def advance(self, steps=1):
        with self.lock:
            if self.error: raise ValueError(self.error)
            for _ in range(steps):
                if self.index>=40:
                    self.playing=False
                    break
                self.conn.execute('BEGIN TRANSACTION')
                old_index=self.index
                old_states=self.states.copy()
                old_checks=self.checks
                try:
                    next_index=min(40,self.index+POLL_MINUTES)
                    for minute in range(self.index+1,next_index+1):
                        ingest(self.conn,frame(minute))
                    self.index=next_index
                    self.evaluate()
                    self.conn.execute('COMMIT')
                    self.publish()
                except Exception:
                    self.conn.execute('ROLLBACK')
                    self.index=old_index; self.states=old_states; self.checks=old_checks
                    self.playing=False
                    raise
                if self.error:break
            if self.index==40: self.playing=False
            self.publish()

    def control(self, action, value=None):
        with self.lock:
            if action=='play':
                if self.error: raise ValueError(self.error)
                if self.index==40: raise ValueError('Replay finished. Reset to start again.')
                self.playing=True
            elif action=='retry':
                if not self.model or not self.error or not self.error.startswith('decision model call failed'):
                    raise ValueError('Only a failed live decision can be retried. Reset after database changes.')
                self.playing=False
                self.error=None
                self.evaluate()
            elif action=='pause': self.playing=False
            elif action=='step': self.playing=False;self.advance()
            elif action=='jump': self.playing=False;self.advance(max(0,(20-self.index+POLL_MINUTES-1)//POLL_MINUTES))
            elif action=='finish': self.playing=False;self.advance((40-self.index+POLL_MINUTES-1)//POLL_MINUTES)
            elif action=='speed':
                if value not in (0.5,1,2,4): raise ValueError('Choose a supported replay speed.')
                self.tick_seconds=float(value)
            elif action=='reset': self.reset()
            else: raise ValueError('Unknown playback action.')
            self.publish()

    def update_rule(self,rule_id,enabled=None,auto_action=None):
        with self.lock:
            if rule_id not in BY_ID: raise ValueError('Unknown rule.')
            if enabled is not None:
                if not isinstance(enabled,bool): raise ValueError('enabled must be true or false.')
                self.enabled[rule_id]=enabled
            if auto_action is not None:
                if not isinstance(auto_action,bool): raise ValueError('auto_action must be true or false.')
                self.auto_action[rule_id]=auto_action
            self.publish()

    def make_task(self,alert_id):
        with self.lock:
            alert=self.query("SELECT * FROM notifications WHERE id=? AND kind='triggered'",[alert_id])
            if not alert: raise ValueError('Choose a triggered alert.')
            existing=self.query('SELECT * FROM tasks WHERE alert_id=?',[alert_id])
            if existing: return clean(existing[0])
            task={'id':f'TASK-{self.conn.execute("SELECT count(*)+1 FROM tasks").fetchone()[0]:03}',
                  'alert_id':alert_id,'created_at':self.now,'title':f"Review {BY_ID[alert[0]['rule_id']].title.lower()}",'status':'open'}
            self.conn.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, ?)',list(task.values()))
            return clean(task)

    def create_task(self,alert_id):
        with self.lock:
            task=self.make_task(alert_id)
            self.publish()
            return task

    def publish(self):
        self.version+=1
        self.cached=self._snapshot()
        self.changed.notify_all()

    def _snapshot(self):
        history=self.query('SELECT * FROM load_readings WHERE ts>=? AND ts<=? ORDER BY ts',[START,self.now])
        notifications=self.query('SELECT * FROM notifications ORDER BY ts DESC, id')
        for n in notifications:
            n['title']=BY_ID[n['rule_id']].title
            n['evidence']=json.loads(n['evidence'])
        current=history[-1]
        reserves=self.query('SELECT * FROM reserve_readings WHERE ts=?',[self.now])[0]
        congestion=self.query('SELECT * FROM congestion_readings WHERE ts=?',[self.now])[0]
        rules=[{**asdict(r),'sql':self.model.plans[r.id] if self.model else r.sql,'enabled':self.enabled[r.id],'auto_action':self.auto_action[r.id],**self.states.get(r.id,{})} for r in RULES]
        counts={name:self.conn.execute(f'SELECT count(*) FROM {name}').fetchone()[0] for name in ('load_readings','reserve_readings','reserve_history','congestion_readings','checks')}
        return clean({'version':self.version,'now':self.now,'start':START,'end':END,'index':self.index,'playing':self.playing,
            'poll_minutes':POLL_MINUTES,'tick_seconds':self.tick_seconds,'error':self.error,'mode':'live' if self.model else 'scripted','database':'DuckDB','phase':self.phase,
            'usage':self.model.usage() if self.model else None,
            'rules':rules,'notifications':notifications,'tasks':self.query('SELECT * FROM tasks ORDER BY created_at DESC'),
            'history':history,
            'metrics':{**current,'reserve_mw':reserves['reserve_mw'],'congestion_per_mwh':congestion['congestion_per_mwh']},
            'counts':counts,'checks':self.checks,'schema_fingerprint':self.schema_fingerprint,'schema_checked_at':self.schema_checked_at})


    def snapshot(self):
        return self.cached  # Published snapshots are replaced atomically, never mutated.

    def loop(self):
        deadline=time.monotonic()+self.tick_seconds
        while not self.stop.wait(0.1):
            with self.lock:
                if time.monotonic() >= self.next_schema_check: self.validate_schema()
                if not self.playing:
                    deadline=time.monotonic()+self.tick_seconds
                    continue
                if time.monotonic()<deadline: continue
                try: self.advance()
                except Exception as exc:
                    self.error=f'Replay stopped: {type(exc).__name__}'
                    self.playing=False
                    self.publish()
                deadline=time.monotonic()+self.tick_seconds

    def close(self):
        self.stop.set()
        with self.lock:
            self.changed.notify_all()
            self.conn.close()
