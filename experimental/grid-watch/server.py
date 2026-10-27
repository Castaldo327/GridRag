"""Run: .venv/bin/python experimental/grid-watch/server.py --port 8011"""
import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlsplit

from engine import Engine
ROOT=Path(__file__).resolve().parent
ASSETS={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/app.css':('app.css','text/css; charset=utf-8')}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass

    def send(self,status,body,kind='application/json'):
        data=json.dumps(body).encode() if kind=='application/json' else body
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path=urlsplit(self.path).path
        if path in ASSETS:
            name,kind=ASSETS[path]
            return self.send(200,(ROOT/'static'/name).read_bytes(),kind)
        if path=='/api/state': return self.send(200,self.server.engine.snapshot())
        if path=='/api/events': return self.events()
        if path=='/api/dataset': return self.send(200,(self.server.engine.directory/'replay.csv').read_bytes(),'text/csv; charset=utf-8')
        return self.send(404,{'error':'Not found'})

    def events(self):
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.send_header('Cache-Control','no-store')
        self.send_header('Connection','keep-alive')
        self.end_headers()
        engine=self.server.engine
        version=-1
        try:
            while not engine.stop.is_set():
                payload=engine.snapshot()
                if payload['version']!=version:
                    self.wfile.write(('data: '+json.dumps(payload)+'\n\n').encode())
                    version=payload['version']
                else:
                    engine.stop.wait(0.25)
                    continue
                self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,TimeoutError): pass

    def do_POST(self):
        host=self.headers.get('Host','')
        if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
            return self.send(403,{'error':'Local requests only.'})
        origin=self.headers.get('Origin')
        if origin and origin != 'http://'+host: return self.send(403,{'error':'Same-origin requests only.'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json': return self.send(415,{'error':'Expected JSON.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8192: raise ValueError('Invalid request size.')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict): raise ValueError('Expected an object.')
            engine=self.server.engine
            if self.path=='/api/control': engine.control(body.get('action'),body.get('value'))
            elif self.path=='/api/rules': engine.update_rule(body.get('id'),body.get('enabled'),body.get('auto_action'))
            elif self.path=='/api/tasks':
                task=engine.create_task(body.get('alert_id'))
                return self.send(200,{'task':task})
            elif self.path=='/api/review':
                return self.send(200,engine.generate_review())
            elif self.path=='/api/schema': return self.send(200,engine.validate_schema())
            else: return self.send(404,{'error':'Not found'})
            return self.send(200,engine.snapshot())
        except (ValueError,TypeError,UnicodeDecodeError) as exc: return self.send(400,{'error':str(exc)})
        except Exception:
            logging.exception('Request failed')
            return self.send(500,{'error':'Request failed. See the local server log.'})

class Server(ThreadingHTTPServer):
    daemon_threads=True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8011)
    parser.add_argument('--play',action='store_true',help='Start the replay immediately.')
    parser.add_argument('--offline',action='store_true',help='Use scripted SQL and decisions without API calls.')
    args=parser.parse_args()
    model=None
    if not args.offline:
        from live_models import LiveModels
        model=LiveModels()
    engine=Engine(model=model)
    server=Server(('127.0.0.1',args.port),Handler)
    server.engine=engine
    if args.play: engine.control('play')
    worker=threading.Thread(target=engine.loop,daemon=True)
    worker.start()
    print(f'Grid Watch local demo: http://127.0.0.1:{args.port}',flush=True)
    print(f'Fictional data · DuckDB · {"LIVE models" if model else "scripted decisions"} · actions stay local',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        engine.stop.set()
        worker.join(timeout=3)
        engine.close()

if __name__=='__main__': main()
