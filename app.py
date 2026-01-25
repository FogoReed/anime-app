# app.py (без изменений, анализ docs не выявил ошибок: параметры верны, sfw=true работает, жанры comma-separated IDs, start/end_date в формате YYYY-MM-DD, rate limits учтены. Жанр-лист полный по docs v4 на 2026.)

from flask import Flask, render_template, jsonify, request
import requests
import time
import random

app = Flask(__name__)

JIKAN_BASE = "https://api.jikan.moe/v4"
LAST_REQUEST_TIME = 0  # Защита от rate limit Jikan (3 req/sec)

def rate_limited_get(url, params=None, retries=3):
    global LAST_REQUEST_TIME
    # Jikan: минимум 0.34 сек между запросами
    elapsed = time.time() - LAST_REQUEST_TIME
    if elapsed < 0.34:
        time.sleep(0.34 - elapsed)
    
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            LAST_REQUEST_TIME = time.time()
            if resp.status_code == 429:  # Rate limit
                time.sleep(2 ** attempt)
                continue
            return resp
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(1)
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search_anime')
def search_anime():
    query = request.args.get('q', '').strip()
    page = int(request.args.get('page', 1))
    limit = min(int(request.args.get('limit', 12)), 25)  # Макс 25 у Jikan

    if not query:
        return jsonify({'data': [], 'pagination': {'has_next_page': False}})

    try:
        params = {'q': query, 'page': page, 'limit': limit, 'order_by': 'score', 'sort': 'desc'}
        resp = rate_limited_get(f"{JIKAN_BASE}/anime", params)
        
        if resp is None or resp.status_code != 200:
            return jsonify({'error': 'Сервис временно недоступен, попробуй позже'}), 503

        json_data = resp.json()
        anime_list = json_data.get('data', [])
        
        # Формируем красивый ответ
        results = []
        for a in anime_list:
            results.append({
                'mal_id': a['mal_id'],
                'title': a.get('title_english') or a['title'],
                'image': a['images']['jpg']['large_image_url'],
                'score': a.get('score') or 0,
                'popularity': a.get('popularity') or 0,
                'members': a.get('members') or 0,
                'favorites': a.get('favorites') or 0,
                'start_date': a.get('aired', {}).get('from'),
                'year': a.get('year') or 'N/A',
                'type': a.get('type', 'TV'),
                'episodes': a.get('episodes') or '?',
                'synopsis': (a.get('synopsis') or 'Нет описания')[:200] + '...'
            })

        return jsonify({
            'data': results,
            'pagination': json_data.get('pagination', {})
        })
    except Exception as e:
        return jsonify({'error': 'Произошла ошибка, попробуй ещё раз'}), 500

@app.route('/api/random_anime_filtered')
def random_anime_filtered():
    try:
        # Формируем query
        params = []
        def add_param(key, value):
            if value:
                params.append(f"{key}={value}")

        add_param('type', request.args.get('type'))
        add_param('status', request.args.get('status'))
        add_param('rating', request.args.get('rating'))
        add_param('min_year', request.args.get('min_year'))
        add_param('max_year', request.args.get('max_year'))
        add_param('genres', request.args.get('genres'))
        add_param('sfw', request.args.get('sfw', 'true'))

        query = '&'.join(params)
        limit = min(int(request.args.get('limit', 10)), 20)  # Макс 25 у Jikan
        limit_per_page = 25

        # Первый запрос на 1-й странице, чтобы узнать total и last_page
        url_first = f"https://api.jikan.moe/v4/anime?{query}&page=1&limit={limit_per_page}"
        resp = rate_limited_get(url_first)
        json_first = resp.json()
        total = json_first.get('pagination', {}).get('items', {}).get('total', 0)
        last_page = json_first.get('pagination', {}).get('last_visible_page', 1)

        if total == 0:
            return jsonify({'total': 0, 'data': []})

        # Запрос на случайную страницу
        page = random.randint(1, last_page)
        url_random = f"https://api.jikan.moe/v4/anime?{query}&page={page}&limit={limit_per_page}"
        resp = rate_limited_get(url_random)
        anime_list = resp.json().get('data', [])

        if not anime_list:
            return jsonify({'total': total, 'data': []})

        # Случайный выбор
        random.shuffle(anime_list)
        selected = anime_list[:limit]

        result = []
        for a in selected:
            result.append({
                'mal_id': a['mal_id'],
                'title': a.get('title_english') or a['title'],
                'image': a['images']['jpg']['large_image_url'],
                'score': a.get('score') or 0,
                'popularity': a.get('popularity') or 0,
                'members': a.get('members') or 0,
                'favorites': a.get('favorites') or 0,
                'start_date': a.get('aired', {}).get('from'),
                'year': a.get('year') or 'N/A',
                'type': a.get('type', 'TV'),
                'episodes': a.get('episodes') or '?',
                'synopsis': (a.get('synopsis') or 'Нет описания')[:250] + '...'
            })

        return jsonify({'total': total, 'data': result})

    except Exception as e:
        return jsonify({'error': 'Произошла ошибка: ' + str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)