"""Run the shipped Python/Node examples against a local fake API, never real services."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

requests = []
attempts = {'submit': 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, status, value, **headers):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        for key, value_ in headers.items():
            self.send_header(key, str(value_))
        self.end_headers()
        self.wfile.write(json.dumps(value, ensure_ascii=False).encode())

    def do_POST(self):
        assert self.path == '/api/open/v1/transcriptions'
        assert self.headers['Authorization'] == 'Bearer test-credential-only'
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append((self.headers['Idempotency-Key'], body))
        attempts['submit'] += 1
        if attempts['submit'] == 1:
            return self.send_json(503, {'error': {'code': 'RECOVERING'}}, **{'Retry-After': 1})
        return self.send_json(202, {'data': {'task_id': 'example-task'}})

    def do_GET(self):
        assert self.path == '/api/open/v1/transcriptions/example-task'
        assert self.headers['Authorization'] == 'Bearer test-credential-only'
        self.send_json(200, {'data': {'task_id': 'example-task', 'status': 'succeeded', 'result': {'text': '示例验证通过'}, 'video_url': None, 'cover_url': None}})


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
root = Path(__file__).resolve().parents[1] / 'public' / 'examples'
try:
    for command in ([sys.executable, '-P', str(root / 'freevideo_open_api.py')], ['node', str(root / 'freevideo_open_api.mjs')]):
        requests.clear()
        attempts['submit'] = 0
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'FREEVIDEO_BASE_URL': f'http://127.0.0.1:{server.server_port}/api/open/v1',
               'FREEVIDEO_API_KEY': 'test-credential-only', 'FREEVIDEO_URL': 'https://www.douyin.com/video/7420000000000000000',
               'FREEVIDEO_IDEMPOTENCY_KEY': 'persisted-before-first-attempt', 'FREEVIDEO_ALLOW_ASR': 'false', 'FREEVIDEO_TASK_ID': ''}
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0, result.stderr
        assert 'example-task' in result.stdout and '示例验证通过' in result.stdout
        assert len(requests) == 2 and requests[0] == requests[1] and requests[0][1]['allow_asr'] is False
        requests.clear()
        env['FREEVIDEO_TASK_ID'] = 'example-task'
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0 and not requests, result.stderr
        print('PASS', Path(command[-1]).name, 'same-key retry, result and resume')
finally:
    server.shutdown()
    server.server_close()
