import base64, http.client, json, os, subprocess, sys, tempfile, time
from urllib.parse import urlencode

HERE = os.path.dirname(os.path.abspath(__file__))
PORT, PASSWORD = 8095, 'test-pass'
tmp = tempfile.mkdtemp()
DB = os.path.join(tmp, 'test.db')
env = dict(os.environ, PORT=str(PORT), CLINIC_DB=DB, ADMIN_PASSWORD=PASSWORD, RATE_MAX='1000')
srv = subprocess.Popen([sys.executable, os.path.join(HERE, 'app.py')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.2)


def request(method, path, body=None, headers=None):
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse(); data = r.read(); c.close()
    return r.status, dict(r.getheaders()), data


def post(fields, extra=None):
    body = urlencode(fields)
    return request('POST', '/api/appointments', body, {'Content-Type': 'application/x-www-form-urlencoded', **(extra or {})})


def count():
    import sqlite3
    c = sqlite3.connect(DB); n = c.execute('SELECT COUNT(*) FROM appointments').fetchone()[0]; c.close(); return n


AUTH = {'Authorization': 'Basic ' + base64.b64encode(f'admin:{PASSWORD}'.encode()).decode()}
good = {'name': 'Анна Петрова', 'phone': '8 (999) 123-45-67', 'pet': 'Кошка', 'service': 'Вакцинация'}
R = []
def check(name, expected, actual, ok): R.append({'n': name, 'exp': expected, 'act': actual, 'ok': bool(ok)})

try:
    s, h, _ = post(good)
    import sqlite3; row = sqlite3.connect(DB).execute('SELECT name, phone, pet, status FROM appointments').fetchone()
    check('Корректная заявка', 'Код 303, переход на /spasibo.html, запись в БД', f'код {s}, Location: {h.get("Location")}, запись: {row}', s == 303 and h.get('Location') == '/spasibo.html' and row == ('Анна Петрова', '79991234567', 'Кошка', 'new'))
    n = count(); s, _, _ = post({**good, 'phone': '12345'})
    check('Неверный телефон', 'Код 400, запись не создаётся', f'код {s}, записей добавлено: {count() - n}', s == 400 and count() == n)
    n = count(); s, _, _ = post({**good, 'name': ' '})
    check('Пустое имя', 'Код 400, запись не создаётся', f'код {s}, записей добавлено: {count() - n}', s == 400 and count() == n)
    n = count(); s, _, _ = post({**good, 'service': 'Несуществующая услуга'})
    check('Неизвестная услуга', 'Код 400, запись не создаётся', f'код {s}, записей добавлено: {count() - n}', s == 400 and count() == n)
    n = count(); inj = "Robert'); DROP TABLE appointments;--"
    s, _, _ = post({**good, 'name': inj}); saved = sqlite3.connect(DB).execute('SELECT name FROM appointments ORDER BY id DESC LIMIT 1').fetchone()[0]
    check('SQL-инъекция в имени', 'Текст сохраняется как обычная строка, таблица цела', f'код {s}, сохранено: «{saved}», записей: {count()}', saved == inj and count() == n + 1)
    xss = '<script>alert(1)</script>'; post({**good, 'name': xss})
    s, _, page = request('GET', '/admin', headers=AUTH); t = page.decode()
    check('XSS в имени (вывод в админке)', 'Теги экранируются, скрипт не выполняется', f'код {s}; «&lt;script&gt;» в странице: {"&lt;script&gt;" in t}; сырой <script>alert: {"<script>alert" in t}', s == 200 and '&lt;script&gt;' in t and '<script>alert' not in t)
    n = count(); s, _, _ = post({**good, 'website': 'http://spam.example'})
    check('Скрытое поле заполнено (робот)', 'Код 303 (без подсказки роботу), запись не создаётся', f'код {s}, записей добавлено: {count() - n}', s == 303 and count() == n)
    s, _, _ = request('POST', '/api/appointments', 'x=' + 'a' * 20000, {'Content-Type': 'application/x-www-form-urlencoded'})
    check('Слишком большой запрос', 'Код 413', f'код {s}', s == 413)
    s, _, _ = request('GET', '/admin')
    check('Админка без пароля', 'Код 401', f'код {s}', s == 401)
    s, _, _ = request('GET', '/admin', headers={'Authorization': 'Basic ' + base64.b64encode(b'admin:wrong').decode()})
    check('Админка с неверным паролем', 'Код 401', f'код {s}', s == 401)
    s, _, _ = request('GET', '/admin?status=new', headers=AUTH)
    check('Админка с верным паролем', 'Код 200', f'код {s}', s == 200)
    s, _, _ = request('GET', '/admin?status=new%27%20OR%201=1--', headers=AUTH)
    check('SQL-инъекция в фильтре админки', 'Код 200, лишних данных нет (значение отбрасывается)', f'код {s}', s == 200)
    s, _, body = request('GET', '/../server/db.py')
    check('Выход за пределы папки site', 'Исходный код сервера не отдаётся (404)', f'код {s}', s == 404 and b'sqlite3' not in body)
    s, h, _ = request('GET', '/index.html')
    check('Отдача страницы сайта', 'Код 200, тип text/html', f'код {s}, {h.get("Content-Type")}', s == 200 and h.get('Content-Type', '').startswith('text/html'))
    s, _, _ = request('GET', '/net-takoj-stranicy.html')
    check('Несуществующая страница', 'Код 404 и страница ошибки сайта', f'код {s}', s == 404)
    env2 = dict(env, PORT='8096', RATE_MAX='5', CLINIC_DB=os.path.join(tmp, 'rate.db'))
    srv2 = subprocess.Popen([sys.executable, os.path.join(HERE, 'app.py')], env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2); codes = []
    for i in range(6):
        c = http.client.HTTPConnection('127.0.0.1', 8096, timeout=5)
        c.request('POST', '/api/appointments', urlencode({**good, 'phone': f'8999123456{i}'}), {'Content-Type': 'application/x-www-form-urlencoded'})
        codes.append(c.getresponse().status); c.close()
    srv2.terminate()
    check('Ограничение частоты (5 заявок в минуту)', 'Шестая подряд заявка отклоняется кодом 429', f'коды ответов: {codes}', codes[:5] == [303] * 5 and codes[5] == 429)
finally:
    srv.terminate()

json.dump(R, open(os.path.join(HERE, 'test_results.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for r in R: print('OK  ' if r['ok'] else 'FAIL', r['n'], '|', r['act'])
print(f'Итого: {sum(r["ok"] for r in R)} из {len(R)}')
sys.exit(0 if all(r['ok'] for r in R) else 1)
