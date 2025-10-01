# fabrica/settings.py
from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------
# Segurança / Debug
# -----------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "mude-esta-chave-em-producao")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")

def _split_env_list(val: str) -> list[str]:
    return [h.strip() for h in (val or "").split(",") if h.strip()]

def _hosts_to_origins(hosts: list[str]) -> list[str]:
    origins: list[str] = []
    for h in hosts:
        if h.startswith(("http://", "https://")):
            origins.append(h)
        else:
            origins.extend((f"http://{h}", f"https://{h}"))
    return origins

# -----------------------------
# Hosts / CSRF
# -----------------------------
if DEBUG:
    ALLOWED_HOSTS = _split_env_list(os.getenv("DJANGO_ALLOWED_HOSTS")) or ["*"]
    _csrf_env = _split_env_list(os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS"))
    CSRF_TRUSTED_ORIGINS = _csrf_env or _hosts_to_origins([h for h in ALLOWED_HOSTS if h != "*"])
else:
    host_source = os.getenv("DJANGO_ALLOWED_HOSTS") or os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
    ALLOWED_HOSTS = _split_env_list(host_source)
    forced = "camisas-js8k.onrender.com"
    if forced and forced not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(forced)
    _csrf_env = _split_env_list(os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS"))
    CSRF_TRUSTED_ORIGINS = _csrf_env or _hosts_to_origins(ALLOWED_HOSTS)

# -----------------------------
# Apps
# -----------------------------
INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Terceiros
    "widget_tweaks",

    # Apps do projeto
    "camisas",
]

# Cloudinary só quando habilitado
USE_CLOUDINARY = os.getenv("USE_CLOUDINARY", "0").lower() in ("1", "true", "yes")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")  # ex: cloudinary://API_KEY:API_SECRET@CLOUD_NAME

if USE_CLOUDINARY:
    INSTALLED_APPS += ["cloudinary", "cloudinary_storage"]

# -----------------------------
# Middleware
# -----------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "camisas.middleware.CurrentRequestMiddleware",
]

ROOT_URLCONF = "fabrica.urls"
WSGI_APPLICATION = "fabrica.wsgi.application"

# -----------------------------
# Templates
# -----------------------------
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

# -----------------------------
# Banco
# -----------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
_db_url = os.getenv("DATABASE_URL")
if _db_url:
    DATABASES["default"] = dj_database_url.parse(
        _db_url, conn_max_age=600, ssl_require=not DEBUG
    )

# -----------------------------
# Auth
# -----------------------------
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -----------------------------
# Locale
# -----------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Araguaina"
USE_I18N = True
USE_TZ = True

# -----------------------------
# Static / Media
# -----------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# MEDIA: usa Cloudinary se habilitado e configurado; senão, FileSystemStorage
if USE_CLOUDINARY and CLOUDINARY_URL:
    # Configuração Cloudinary
    DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"
    MEDIA_URL = "/media/"  # usado em templates; a URL real virá do Cloudinary
    MEDIA_ROOT = BASE_DIR / "media"  # não é usado, mas mantemos por compatibilidade
else:
    # Fallback/local (dev ou quando não há credenciais)
    DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

# Em PRODUÇÃO: se você realmente precisa Cloudinary, previna subida sem credenciais
if not DEBUG and USE_CLOUDINARY and not CLOUDINARY_URL:
    raise RuntimeError("USE_CLOUDINARY=1 mas CLOUDINARY_URL não foi definido.")

# -----------------------------
# Padrões
# -----------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = True

# -----------------------------
# Segurança PROD
# -----------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    # HSTS depois de validar HTTPS:
    # SECURE_HSTS_SECONDS = 31536000
    # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # SECURE_HSTS_PRELOAD = True

# -----------------------------
# Logging
# -----------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
