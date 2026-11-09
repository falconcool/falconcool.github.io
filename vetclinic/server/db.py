"""Работа с базой данных: создание таблиц, добавление и выбор заявок.

Главное правило безопасности: значения из формы НИКОГДА не вставляются в текст
SQL-запроса напрямую. Мы пишем в запросе знаки ? и передаём значения отдельно —
так база сама экранирует их, и SQL-инъекция невозможна.
"""
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICES = [
    ('Приём ветеринара-терапевта', 1900),
    ('Хирургия для животных', 6000),
    ('Стерилизация и кастрация', 4500),
    ('УЗИ и анализы', 1200),
    ('Вакцинация', 900),
    ('Вызов ветеринара на дом', 2500),
]
PETS = ('Кошка', 'Собака', 'Другое')


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _run_script(conn, filename):
    with open(os.path.join(HERE, filename), encoding='utf-8') as f:
        conn.executescript(f.read())


def init_db(path, with_indexes=True):
    """Создаёт таблицы (и по желанию индексы), заполняет справочник услуг."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = connect(path)
    _run_script(conn, 'schema.sql')
    if with_indexes:
        _run_script(conn, 'indexes.sql')
    conn.executemany('INSERT OR IGNORE INTO services (name, price_from) VALUES (?, ?)', SERVICES)
    conn.commit()
    return conn


def normalize_phone(raw):
    """Приводит телефон к виду 79991234567 или возвращает None, если номер неверный."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) == 10:
        digits = '7' + digits
    if len(digits) == 11 and digits[0] == '8':
        digits = '7' + digits[1:]
    return digits if len(digits) == 11 and digits[0] == '7' else None


def clean_name(raw):
    """Убирает управляющие символы и лишние пробелы; None, если имя не подходит."""
    name = re.sub(r'[\x00-\x1f\x7f]', ' ', raw or '')
    name = ' '.join(name.split())
    return name if 2 <= len(name) <= 100 else None


def add_appointment(conn, name, phone, pet, service_name):
    """Добавляет заявку. Бросает ValueError, если данные неверны."""
    name, phone = clean_name(name), normalize_phone(phone)
    if not name or not phone or pet not in PETS:
        raise ValueError('Некорректные данные заявки')
    row = conn.execute('SELECT id FROM services WHERE name = ?', (service_name,)).fetchone()
    if row is None:
        raise ValueError('Неизвестная услуга')
    cur = conn.execute(
        'INSERT INTO appointments (name, phone, pet, service_id) VALUES (?, ?, ?, ?)',
        (name, phone, pet, row['id']))
    conn.commit()
    return cur.lastrowid


LIST_SQL = '''
SELECT a.id, a.created_at, a.name, a.phone, a.pet, s.name AS service, a.status
FROM appointments a JOIN services s ON s.id = a.service_id
{where}
ORDER BY a.id DESC
LIMIT ?
'''


def list_appointments(conn, status=None, phone=None, before_id=None, limit=50):
    """Список заявок, свежие сверху. Постраничность «по ключу»: before_id — id последней
    показанной заявки (так запрос не перебирает пропущенные строки, как OFFSET)."""
    conds, params = [], []
    if status:
        conds.append('a.status = ?'); params.append(status)
    if phone:
        conds.append('a.phone = ?'); params.append(phone)
    if before_id:
        conds.append('a.id < ?'); params.append(before_id)
    where = ('WHERE ' + ' AND '.join(conds)) if conds else ''
    return conn.execute(LIST_SQL.format(where=where), params + [limit]).fetchall()
