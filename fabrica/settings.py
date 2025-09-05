# fabrica/settings.py
from pathlib import Path
import os
import dj_database_url  # <- adicionar no requirements.txt

# -------------------------------------------------
# Base
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------------------------------
# Segurança / Debug
# -------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "mude-esta-chave-em-producao")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")

# Hosts permitidos
if DEBUG:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
else:
    # Ex.: "app.onrender.com,www.seudominio.com"
    _hosts = os.getenv("DJANGO_ALLOWED_HOSTS", "")
    ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]

# Domínios confiáveis para CSRF (produção)
# Ex.: "https://app.onrender.com,https://www.seudominio.com"
_csrf = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [u.strip() for u in _csrf.split(",") if u.strip()]

# -------------------------------------------------
# Apps
# -------------------------------------------------
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Apps do projeto
    "camisas",

    # Terceiros
    "widget_tweaks",
]

# -------------------------------------------------
# Middleware
# -------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # Whitenoise deve ficar logo após SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # Seu middleware (se existir)
    "camisas.middleware.CurrentRequestMiddleware",
]

# -------------------------------------------------
# URL / WSGI
# -------------------------------------------------
ROOT_URLCONF = "fabrica.urls"
WSGI_APPLICATION = "fabrica.wsgi.application"

# -------------------------------------------------
# Templates
# -------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# -------------------------------------------------
# Banco de Dados
# -------------------------------------------------
# Padrão: SQLite em dev. Em produção, usar DATABASE_URL (Neon).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    # Neon exige sslmode=require; conn_max_age ajuda no pooling
    DATABASES["default"] = dj_database_url.parse(
        _db_url,
        conn_max_age=600,
        ssl_require=True
    )

# -------------------------------------------------
# Autenticação
# -------------------------------------------------
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -------------------------------------------------
# Internacionalização / Fuso
# -------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Araguaina"
USE_I18N = True
USE_TZ = True

# -------------------------------------------------
# Arquivos estáticos e de mídia
# -------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Opcional durante o desenvolvimento; remova se não usar a pasta
STATICFILES_DIRS = [BASE_DIR / "static"]

# Whitenoise: servir estáticos em produção
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# -------------------------------------------------
# Padrões
# -------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = True

# -------------------------------------------------
# Segurança adicional para produção
# -------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    # HSTS (opcional; ative após validar HTTPS OK)
    # SECURE_HSTS_SECONDS = 31536000
    # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # SECURE_HSTS_PRELOAD = True

# -------------------------------------------------
# Logging básico (útil na Render)
# -------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
