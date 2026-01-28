import requests
import time
import random

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from config import Config
from models import db, User, UserAnime

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- User loader для Flask-Login ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Создаем таблицы при старте
with app.app_context():
    db.create_all()

# --- Регистрация ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash("Имя уже занято", "danger")
            return redirect(url_for('register'))

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(username=username, password=hashed_pw)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Регистрация успешна!", "success")
        return redirect(url_for('index'))

    return render_template('register.html')

# --- Логин ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            flash("Вход успешен!", "success")
            return redirect(url_for('index'))
        flash("Неверное имя или пароль", "danger")

    return render_template('login.html')

# --- Логаут ---
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Вы вышли", "info")
    return redirect(url_for('index'))

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
        # Параметры
        params = []

        def add_param(key, value):
            if value:
                params.append(f"{key}={value}")

        add_param('type', request.args.get('type'))
        add_param('status', request.args.get('status'))
        add_param('rating', request.args.get('rating'))
        add_param('genres', request.args.get('genres'))

        # min/max год
        min_year = request.args.get('min_year')
        max_year = request.args.get('max_year')

        if min_year:
            add_param('start_date', f"{min_year}-01-01")
        if max_year:
            add_param('end_date', f"{max_year}-12-31")

        # NSFW
        sfw = 'true'  # По умолчанию безопасный контент
        if current_user.is_authenticated:
            sfw = 'false' if current_user.nsfw_allowed else 'true'
        add_param('sfw', sfw)

        query = '&'.join(params)
        limit = min(int(request.args.get('limit', 10)), 20)
        limit_per_page = 25

        # Запрос к Jikan
        url_first = f"https://api.jikan.moe/v4/anime?{query}&page=1&limit={limit_per_page}"
        resp = rate_limited_get(url_first)
        json_first = resp.json()
        total = json_first.get('pagination', {}).get('items', {}).get('total', 0)
        last_page = json_first.get('pagination', {}).get('last_visible_page', 1)

        if total == 0:
            return jsonify({'total': 0, 'data': []})

        page = random.randint(1, last_page)
        url_random = f"https://api.jikan.moe/v4/anime?{query}&page={page}&limit={limit_per_page}"
        resp = rate_limited_get(url_random)
        anime_list = resp.json().get('data', [])

        if not anime_list:
            return jsonify({'total': total, 'data': []})

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
    
@app.route('/api/set_nsfw', methods=['POST'])
@login_required
def set_nsfw():
    data = request.get_json()
    current_user.nsfw_allowed = bool(data.get('nsfw', False))
    db.session.commit()
    return jsonify({'success': True})

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        # Сохраняем настройки
        current_user.nsfw_allowed = bool(request.form.get('nsfw_allowed'))
        current_user.private_account = bool(request.form.get('private_account'))
        current_user.tag = request.form.get('tag', '')
        db.session.commit()
        flash("Настройки сохранены!", "success")
        return redirect(url_for('settings'))

    return render_template('settings.html', user=current_user)

@app.route('/my-list')
@login_required
def my_list():
    items = UserAnime.query.filter_by(user_id=current_user.id).all()

    anime_list = []
    for item in items:
        anime_list.append({
            'id': item.id,
            'mal_id': item.mal_id,
            'title': item.title,
            'image': item.image,
            'type': item.type,
            'episodes': item.episodes,
            'year': item.year,
            'synopsis': item.synopsis,
            'status': item.status,
            'score': item.score,
            'comment': item.comment,
            'is_private': item.is_private
        })

    return render_template('my_list.html', anime_list=anime_list)

@app.route('/api/add_to_list', methods=['POST'])
@login_required
def add_to_list():
    data = request.get_json()
    mal_id = data.get('mal_id')

    if not mal_id:
        return jsonify({'error': 'mal_id is required'}), 400

    # Проверка — уже есть в списке?
    exists = UserAnime.query.filter_by(
        user_id=current_user.id,
        mal_id=mal_id
    ).first()

    if exists:
        return jsonify({'message': 'already_added'}), 200

    anime = UserAnime(
        user_id=current_user.id,
        mal_id=mal_id,
        status='planned'
    )

    db.session.add(anime)
    db.session.commit()

    return jsonify({'success': True})

@app.route('/api/delete_from_list', methods=['POST'])
@login_required
def delete_from_list():
    data = request.get_json()
    anime_id = data.get('id')

    anime = UserAnime.query.filter_by(
        id=anime_id,
        user_id=current_user.id
    ).first_or_404()

    db.session.delete(anime)
    db.session.commit()

    return jsonify({'success': True})

@app.route('/api/update_status', methods=['POST'])
@login_required
def update_status():
    data = request.get_json()
    print("DATA:", data)
    anime_id = data.get('id')
    status = data.get('status')
    anime = UserAnime.query.filter_by(id=anime_id, user_id=current_user.id).first()
    if not anime:
        return jsonify({'success': False, 'error': 'Anime not found'}), 404
    anime.status = status
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/update_score', methods=['POST'])
@login_required
def update_score():
    data = request.get_json()
    anime_id = data.get('id')
    score = data.get('score')

    anime = UserAnime.query.filter_by(
        id=anime_id,
        user_id=current_user.id
    ).first_or_404()

    anime.score = score if score else None
    db.session.commit()

    return jsonify({'success': True})

@app.route('/api/toggle_list', methods=['POST'])
@login_required
def toggle_list():
    data = request.get_json()
    mal_id = data.get('mal_id')

    anime = UserAnime.query.filter_by(
        user_id=current_user.id,
        mal_id=mal_id
    ).first()

    if anime:
        db.session.delete(anime)
        db.session.commit()
        return jsonify({'status': 'removed'})

    anime = UserAnime(
        user_id=current_user.id,
        mal_id=mal_id,
        title=data.get('title'),
        image=data.get('image'),
        type=data.get('type'),
        episodes=data.get('episodes'),
        year=data.get('year'),
        synopsis=data.get('synopsis'),
        status='planned'
    )

    db.session.add(anime)
    db.session.commit()
    return jsonify({'status': 'added'})

@app.route('/api/update_private', methods=['POST'])
@login_required
def update_private():
    data = request.get_json()
    anime_id = data.get('id')
    is_private = bool(data.get('is_private'))

    anime = UserAnime.query.filter_by(id=anime_id, user_id=current_user.id).first_or_404()
    anime.is_private = is_private
    db.session.commit()

    return jsonify({'success': True})

@app.route('/api/update_comment', methods=['POST'])
@login_required
def update_comment():
    data = request.get_json()
    anime_id = data.get('id')
    comment = data.get('comment', '').strip()

    anime = UserAnime.query.filter_by(
        id=anime_id,
        user_id=current_user.id
    ).first_or_404()

    anime.comment = comment
    db.session.commit()

    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True)