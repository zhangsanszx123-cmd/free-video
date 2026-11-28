"""Python 3 standard-library example. Keep credentials on YOUR SERVER.

Required env: FREEVIDEO_BASE_URL (ends /api/open/v1), FREEVIDEO_API_KEY.
New task: FREEVIDEO_URL and a persisted FREEVIDEO_IDEMPOTENCY_KEY.
Resume: FREEVIDEO_TASK_ID. Optional FREEVIDEO_ALLOW_ASR=true authorizes ASR quota use.
"""
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = os.environ['FREEVIDEO_BASE_URL'].rstrip('/')
TOKEN = os.environ['FREEVIDEO_API_KEY']
parsed = urlsplit(BASE)
if parsed.username or parsed.password or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost'))):
    raise SystemExit('Use HTTPS in production; HTTP is allowed only for local development.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never forward a credential to a redirected origin


opener = build_opener(NoRedirect)


def call(path, body=None):
    headers = {'Authorization': 'Bearer ' + TOKEN}
    if body is not None:
        headers.update({'Content-Type': 'application/json', 'Idempotency-Key': os.environ['FREEVIDEO_IDEMPOTENCY_KEY']})
    req = Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with opener.open(req, timeout=20) as res:
            return json.load(res)
    except HTTPError as exc:
        if exc.code in (429, 502, 503, 504):
            delay = exc.headers.get('Retry-After', '5')
            raise Temporary(min(60, max(1, int(delay) if delay.isdigit() else 5))) from None
        try:
            message = json.load(exc).get('error', {}).get('message', 'Request failed')
        except (ValueError, AttributeError):
            message = 'Request failed'
        raise SystemExit(f'HTTP {exc.code}: {message}') from None
    except (URLError, TimeoutError):
        raise Temporary(5) from None


class Temporary(Exception):
    pass


def main():
    task_id = os.getenv('FREEVIDEO_TASK_ID')
    if not task_id:
        body = {'url': os.environ['FREEVIDEO_URL'], 'allow_asr': os.getenv('FREEVIDEO_ALLOW_ASR') == 'true'}
        # Never generate a new idempotency key on a timeout. Save it before the FIRST call.
        for _ in range(3):
            try:
                task_id = call('/transcriptions', body)['data']['task_id']
                break
            except Temporary as exc:
                time.sleep(exc.args[0])
        if not task_id:
            raise SystemExit('Submission not confirmed. Retry with the SAME persisted idempotency key and parameters.')
    print('task_id=' + task_id, flush=True)  # save this ID to resume later
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            data = call('/transcriptions/' + task_id)['data']
        except Temporary as exc:
            time.sleep(exc.args[0])
            continue
        state = data['status']
        if state == 'succeeded':
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return
        if state in ('failed', 'uncertain'):
            print(json.dumps(data, ensure_ascii=False, indent=2))
            raise SystemExit('Stop: inspect the original task; NEVER automatically resubmit uncertain audio.')
        time.sleep(5)
    raise SystemExit('Polling stopped. Save task_id and resume querying; do not create a replacement task.')


if __name__ == '__main__':
    main()
