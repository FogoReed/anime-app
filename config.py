import os
from dotenv import load_dotenv

load_dotenv()  # загружаем .env

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")  # для dev, заменяется на prod
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///anime_app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DEBUG = os.environ.get('FLASK_DEBUG', '1') == '0'  # Включаем отладку, если переменная окружения FLASK_DEBUG установлена в '1'