import json, os, random, shutil, sqlite3, statistics, sys, tempfile, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
HERE = os.path.dirname(os.path.abspath(__file__))
rng = random.Random(42)
NAMES = ['Анна', 'Игорь', 'Мария', 'Павел', 'Ольга', 'Дмитрий', 'Светлана', 'Сергей', 'Елена', 'Андрей']
END = datetime(2026, 10, 31, 23, 59, 59)
START = END - timedelta(days=730)
PHONES = [f'79{rng.randint(10**8, 10**9 - 1)}' for _ in range(N // 4)]   # у клиентов по нескольку заявок


def gen_rows():
    span = int((END - START).total_seconds())
    for _ in range(N):
        t = START + timedelta(seconds=rng.randint(0, span))
        age_days = (END - t).days
        if age_days < 3:
            status = rng.choices(['new', 'confirmed'], [80, 20])[0]
        else:
            status = rng.choices(['done', 'cancelled'], [88, 12])[0]
        yield (t.strftime('%Y-%m-%dT%H:%M:%S'), rng.choice(NAMES) + ' ' + rng.choice(NAMES)[:1] + '.',
               rng.choice(PHONES), rng.choice(db.PETS), rng.randint(1, 6), status)


def median_ms(fn, reps=15, warm=2):
    for _ in range(warm): fn()
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter(); fn(); ts.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(ts), 3)


def plan(conn, sql, params=()):
    return ' → '.join(r[3] for r in conn.execute('EXPLAIN QUERY PLAN ' + sql, params).fetchall())


tmp = tempfile.mkdtemp()
A, B = os.path.join(tmp, 'a_before.db'), os.path.join(tmp, 'b_after.db')
out = {'rows': N, 'python': sys.version.split()[0], 'sqlite': sqlite3.sqlite_version, 'queries': []}

ca = db.init_db(A, with_indexes=False)
t0 = time.perf_counter()
ca.executemany('INSERT INTO appointments (created_at, name, phone, pet, service_id, status) VALUES (?,?,?,?,?,?)', gen_rows())
ca.commit(); out['fill_s'] = round(time.perf_counter() - t0, 2)
ca.close()
shutil.copy(A, B)
cb = db.connect(B)
t0 = time.perf_counter(); db._run_script(cb, 'indexes.sql'); cb.commit(); out['index_build_s'] = round(time.perf_counter() - t0, 2)
out['size_mb'] = {'before': round(os.path.getsize(A) / 1e6, 1), 'after': round(os.path.getsize(B) / 1e6, 1)}
ca = db.connect(A)

phones = rng.sample(PHONES, 30)
month = ('2026-06-01T00:00:00', '2026-07-01T00:00:00')
SQL = {
 'Q1': ("Счётчик новых заявок", "SELECT COUNT(*) FROM appointments WHERE status = ?", lambda i: ('new',)),
 'Q2': ("История заявок клиента по телефону", "SELECT a.id, a.created_at, a.name, s.name FROM appointments a JOIN services s ON s.id = a.service_id WHERE a.phone = ? ORDER BY a.id DESC", lambda i: (phones[i % 30],)),
 'Q3': ("Отчёт за месяц по услугам", "SELECT s.name, COUNT(*) FROM appointments a JOIN services s ON s.id = a.service_id WHERE a.created_at >= ? AND a.created_at < ? GROUP BY s.id", lambda i: month),
}
for key, (title, sql, prm) in SQL.items():
    cnt = [0]
    def run(c):
        def f():
            c.execute(sql, prm(cnt[0])).fetchall(); cnt[0] += 1
        return f
    out['queries'].append({'id': key, 'title': title, 'sql': sql, 'plan_before': plan(ca, sql, prm(0)), 'plan_after': plan(cb, sql, prm(0)),
                           'ms_before': median_ms(run(ca)), 'ms_after': median_ms(run(cb))})

off_sql = 'SELECT a.id, a.created_at, a.name FROM appointments a ORDER BY a.id DESC LIMIT 50 OFFSET ?'
key_sql = 'SELECT a.id, a.created_at, a.name FROM appointments a WHERE a.id < ? ORDER BY a.id DESC LIMIT 50'
last = N - 150_000 + 1
out['queries'].append({'id': 'Q4', 'title': 'Страница №3001 списка заявок (50 на странице)', 'sql': off_sql + '  →  ' + key_sql,
    'plan_before': plan(cb, off_sql, (150_000,)), 'plan_after': plan(cb, key_sql, (last,)),
    'ms_before': median_ms(lambda: cb.execute(off_sql, (150_000,)).fetchall()), 'ms_after': median_ms(lambda: cb.execute(key_sql, (last,)).fetchall())})

def n_plus_one():
    for r in cb.execute('SELECT id, name, service_id FROM appointments ORDER BY id DESC LIMIT 50').fetchall():
        cb.execute('SELECT name FROM services WHERE id = ?', (r['service_id'],)).fetchone()
join_sql = 'SELECT a.id, a.name, s.name FROM appointments a JOIN services s ON s.id = a.service_id ORDER BY a.id DESC LIMIT 50'
out['queries'].append({'id': 'Q5', 'title': 'Последние 50 заявок с названием услуги', 'sql': '1 запрос + 50 запросов  →  один запрос с JOIN',
    'plan_before': '51 обращение к базе', 'plan_after': plan(cb, join_sql), 'ms_before': median_ms(n_plus_one), 'ms_after': median_ms(lambda: cb.execute(join_sql).fetchall())})

def single_inserts(path, k=300):
    c = db.connect(path); t0 = time.perf_counter()
    for i in range(k):
        db.add_appointment(c, 'Тест Тестов', f'7999000{i:04d}', 'Кошка', 'Вакцинация')
    dt = (time.perf_counter() - t0) * 1000 / k; c.close(); return round(dt, 2)
def batch_insert(path, k=20_000):
    c = db.connect(path); rows = [r for _, r in zip(range(k), gen_rows())]; t0 = time.perf_counter()
    c.executemany('INSERT INTO appointments (created_at, name, phone, pet, service_id, status) VALUES (?,?,?,?,?,?)', rows); c.commit()
    dt = (time.perf_counter() - t0); c.close(); return round(dt, 2)
ca.close(); cb.close()
out['insert'] = {'single_ms_before': single_inserts(A), 'single_ms_after': single_inserts(B),
                 'batch_s_before': batch_insert(A), 'batch_s_after': batch_insert(B)}
json.dump(out, open(os.path.join(HERE, 'benchmark_results.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for q in out['queries']:
    print(q['id'], q['title'], '|', q['ms_before'], '→', q['ms_after'], 'мс |', q['plan_before'][:70], '=>', q['plan_after'][:80])
print({k: out[k] for k in ('rows', 'fill_s', 'index_build_s', 'size_mb', 'insert')})
shutil.rmtree(tmp)
