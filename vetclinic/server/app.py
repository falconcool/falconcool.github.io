import base64
import hmac
import html
import mimetypes
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DIR = os.path.join(ROOT, 'site')
DB_PATH = os.environ.get('CLINIC_DB', os.path.join(ROOT, 'data', 'clinic.db'))
MAX_BODY = 10_000        
RATE_LIMIT = (int(os.environ.get('RATE_MAX', '5')), 60)  
_hits = {}                 


class Handler(BaseHTTPRequestHandler):
    server_version = 'VetClinic/1.0'

    def send_text(self, code, body, ctype='text/html; charset=utf-8', headers=None):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def send_error_page(self, code, message):
        self.send_text(code, f'<!DOCTYPE html><meta charset="utf-8"><title>Ошибка {code}</title>'
                             f'<p>{html.escape(message)}</p><p><a href="/">На главную</a></p>')

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/admin':
            return self.admin(url)
        path = '/index.html' if url.path == '/' else url.path
        full = os.path.realpath(os.path.join(SITE_DIR, path.lstrip('/')))
        if not full.startswith(os.path.realpath(SITE_DIR) + os.sep) or not os.path.isfile(full):
            page = os.path.join(SITE_DIR, '404.html')
            body = open(page, 'rb').read() if os.path.isfile(page) else b'404'
            return self.send_text(404, body)
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype in ('application/xml', 'image/svg+xml'):
            ctype += '; charset=utf-8'
        self.send_text(200, open(full, 'rb').read(), ctype)

    def do_POST(self):
        if urlparse(self.path).path != '/api/appointments':
            return self.send_error_page(404, 'Такого адреса нет')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send_error_page(400, 'Неверная длина запроса')
        if length > MAX_BODY:
            return self.send_error_page(413, 'Слишком большой запрос')
        ip = self.client_address[0]
        now = time.time()
        recent = [t for t in _hits.get(ip, []) if now - t < RATE_LIMIT[1]]
        if len(recent) >= RATE_LIMIT[0]:
            return self.send_error_page(429, 'Слишком много заявок. Попробуйте через минуту.')
        _hits[ip] = recent + [now]

        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode('utf-8', 'replace')).items()}
        if form.get('website'):
            return self.redirect('/spasibo.html')     
        conn = db.connect(DB_PATH)
        try:
            db.add_appointment(conn, form.get('name'), form.get('phone'), form.get('pet'), form.get('service'))
        except ValueError as e:
            return self.send_error_page(400, f'Заявка не принята: {e}. Вернитесь назад и проверьте данные.')
        finally:
            conn.close()
        self.redirect('/spasibo.html')

    def redirect(self, where):
        self.send_text(303, '', headers={'Location': where})

    def authorized(self):
        password = os.environ.get('ADMIN_PASSWORD')
        if not password:
            return None            
        header = self.headers.get('Authorization', '')
        if header.startswith('Basic '):
            try:
                user, _, given = base64.b64decode(header[6:]).decode('utf-8').partition(':')
            except Exception:
                return False
            return hmac.compare_digest(user, os.environ.get('ADMIN_USER', 'admin')) and hmac.compare_digest(given, password)
        return False

    def admin(self, url):
        ok = self.authorized()
        if ok is None:
            return self.send_error_page(404, 'Админка выключена: не задан ADMIN_PASSWORD')
        if not ok:
            return self.send_text(401, 'Нужен пароль', 'text/plain; charset=utf-8',
                                  {'WWW-Authenticate': 'Basic realm="Admin", charset="UTF-8"'})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        status = q.get('status') if q.get('status') in ('new', 'confirmed', 'done', 'cancelled') else None
        phone = db.normalize_phone(q['phone']) if q.get('phone') else None
        before = int(q['before']) if q.get('before', '').isdigit() else None
        conn = db.connect(DB_PATH)
        try:
            rows = db.list_appointments(conn, status, phone, before, 50)
            total = conn.execute('SELECT COUNT(*) FROM appointments').fetchone()[0]
        finally:
            conn.close()
        e = html.escape    
        body = ''.join(
            f'<tr><td>{r["id"]}</td><td>{e(r["created_at"])}</td><td>{e(r["name"])}</td><td>{e(r["phone"])}</td>'
            f'<td>{e(r["pet"])}</td><td>{e(r["service"])}</td><td>{e(r["status"])}</td></tr>' for r in rows)
        nxt = f'<p><a href="/admin?before={rows[-1]["id"]}{"&status=" + status if status else ""}">Дальше →</a></p>' if len(rows) == 50 else ''
        self.send_text(200, f'''<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>Заявки — админка</title><style>body{{font-family:Arial,sans-serif;margin:24px;color:#222}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:6px 10px;text-align:left}}th{{background:#eee}}a{{color:#1a4f8a}}</style></head><body>
<h1>Заявки с сайта</h1><p>Всего заявок: {total}. Фильтр:
<a href="/admin">все</a> · <a href="/admin?status=new">новые</a> · <a href="/admin?status=confirmed">подтверждённые</a> ·
<a href="/admin?status=done">выполненные</a></p>
<table><tr><th>№</th><th>Создана</th><th>Имя</th><th>Телефон</th><th>Питомец</th><th>Услуга</th><th>Статус</th></tr>{body}</table>{nxt}
</body></html>''')


def main():
    db.init_db(DB_PATH).close()
    port = int(os.environ.get('PORT', '8000'))
    print(f'Сайт: http://localhost:{port}   База данных: {DB_PATH}')
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()


if __name__ == '__main__':
    main()
