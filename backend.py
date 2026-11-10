# -*- coding: utf-8 -*-
"""
Тестовый бэкенд для кейса «Показ попапа определенному сегменту профилей».

Что делает:
  GET /check?phone=+79000000000
    1) выгружает профили сегмента через API Altcraft (profiles/segstatic/list);
    2) ищет среди них телефон из запроса;
    3) отвечает JSON: {"allowed": true/false, "profile_id": "..."}

  Страница success.html при allowed=true пушит в Менеджер тегов матчинг
  по profile_id — и попап показывается с данными этого профиля.

Запуск:
  python backend.py

Проверка руками (в браузере):
  http://localhost:8000/check?phone=%2B79000000000   -> {"allowed": true, ...}
  http://localhost:8000/check?phone=%2B79991112233   -> {"allowed": false, ...}
"""

import json
import re
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------- настройки ----------------------
API_URL    = 'https://ru.altkraft.com/api/v1.1/profiles/segstatic/list'
API_TOKEN  = 'c7f8da60094e4a7291cac53d8f2bffff'  # токен с правами на чтение сегментов
SEGMENT_ID = 179                                 # ID статического сегмента
PORT       = 8000                                # порт, на котором слушает бэкенд
PAGE_SIZE  = 50                                  # сколько профилей запрашивать за раз
# --------------------------------------------------------


def normalize_phone(value):
    """Оставляет только цифры: '+7 900 000-00-00' -> '79000000000'."""
    return re.sub(r'\D', '', value or '')


def segment_members():
    """Выгружает профили сегмента постранично. Возвращает список профилей."""
    members = []
    from_id = None
    from_db = None
    for _ in range(50):  # предохранитель от бесконечного цикла
        body = {'id': SEGMENT_ID, 'count': PAGE_SIZE, 'fields': ['phones']}
        if from_id:
            body['from_id'] = from_id
            body['from_db'] = from_db
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + API_TOKEN,
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data.get('error'):
            raise RuntimeError('Altcraft API: %s' % data.get('error_text'))
        page = ((data.get('data') or {}).get('data')) or []
        members.extend(page)
        # Пагинация: если сервер вернул next_id — запрашиваем следующую страницу
        # начиная с последнего профиля текущей.
        if not page or not data.get('next_id'):
            break
        from_id = page[-1].get('profile_id')
        from_db = page[-1].get('db_id')
    return members


def check_phone(phone):
    """Ищет телефон среди профилей сегмента. Возвращает (allowed, profile_id)."""
    wanted = normalize_phone(phone)
    if not wanted:
        return False, None
    for member in segment_members():
        phones = ((member.get('profile') or {}).get('phones')) or []
        for p in phones:
            if normalize_phone(p.get('phone')) == wanted:
                return True, member.get('profile_id')
    return False, None


class Handler(BaseHTTPRequestHandler):

    def _send(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        # Страница лежит на github.io (другой домен), поэтому без CORS браузер
        # не даст ей прочитать ответ бэкенда.
        self.send_header('Access-Control-Allow-Origin', '*')
        # Chrome требует разрешение для запросов с HTTPS-страницы на localhost
        # (Private Network Access) — отвечает на preflight-запрос OPTIONS.
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # Preflight-запрос браузера: подтверждаем, что CORS разрешён.
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.end_headers()

    def do_GET(self):
        if not self.path.startswith('/check'):
            self._send({'error': 'используйте /check?phone=...'}, 404)
            return
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        phone = (params.get('phone') or [''])[0]
        try:
            allowed, profile_id = check_phone(phone)
            self._send({'allowed': allowed, 'profile_id': profile_id})
        except Exception as e:
            # Ошибка обращения к платформе — попап не показываем, причину возвращаем для отладки.
            self._send({'allowed': False, 'profile_id': None, 'error': str(e)}, 502)

    def log_message(self, fmt, *args):
        # Краткий лог запросов в консоль.
        print('[%s] %s' % (self.log_date_time_string(), fmt % args))


if __name__ == '__main__':
    print('Бэкенд запущен: http://localhost:%d' % PORT)
    print('Проверка сегмента %d. Остановить: Ctrl+C' % SEGMENT_ID)
    HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
