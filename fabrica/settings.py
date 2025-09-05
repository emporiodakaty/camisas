# fabrica/settings.py
from pathlib import Path
import os
import dj_database_url  # requirements: dj-database-url
# Cloudinary storage para MEDIA
# requirements: cloudinary, django-cloudinary-storage
import cloudinary
import cloudinary.uploader
import cloudinary.api

# -------------------------------------------------
# Base
# -------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------------------------------
# Segurança / Debug
# -------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "mude-esta-chave-em-producao")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")

# -------------------------------------------------
# Hosts / CSRF (com fallback para Render)
# -------------------------------------------------
if DEBUG:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
else:
    # 1) tenta DJANGO_ALLOWED_HOSTS; 2) cai para RENDER_EXTERNAL_HOSTNAME
    host_source = os.getenv("DJANGO_ALLOWED_HOSTS") or os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
    ALLOWED_HOSTS = [h.strip() for h in host_source.split(",") if h.strip()]
    # 3) garante o domínio do serviço (ajuste aqui se mudar o subdomínio)
    forced = "camisas-js8k.onrender.com"
    if forced not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(forced)

# CSRF TRUSTED ORIGINS com fallback
_csrf = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "")
if not _csrf:
    base_host = os.getenv("RENDER_EXTERNAL_HOSTNAME") or "camisas-js8k.onrender.com"
    _csrf = f"https://{base_host}"
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

    # Terceiros
    "widget_tweaks",
    "cloudinary",
    "cloudinary_storage",

    # Apps do projeto
    "camisas",
]

# -------------------------------------------------
# Middleware
# -------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # Whitenoise (estáticos) — mantenha logo após SecurityMiddleware
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
# Banco de Dados (Neon via DATABASE_URL)
# -------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
_db_url = os.getenv("DATABASE_URL")
if _db_url:
    DATABASES["default"] = dj_database_url.parse(
        _db_url, conn_max_age=600, ssl_require=True
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
# Estáticos (Whitenoise) e Mídia (Cloudinary)
# -------------------------------------------------
# Static (build-time)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media (runtime) -> Cloudinary
# defina CLOUDINARY_URL nas env vars (ex.: cloudinary://API_KEY:API_SECRET@CLOUD_NAME)
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")  # NÃO coloque valor aqui no código!
if not CLOUDINARY_URL and not DEBUG:
    # evita subir sem CLOUDINARY_URL em produção
    raise RuntimeError("CLOUDINARY_URL não configurada nas variáveis de ambiente.")

cloudinary.config(cloudinary_url=CLOUDINARY_URL)

DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"
MEDIA_URL = "/media/"  # Django ainda usa essa URL base em templates; Cloudinary cuida das entregas
MEDIA_ROOT = BASE_DIR / "media"  # não será usado para upload quando Cloudinary estiver ativo

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
    # HSTS (ative após validar HTTPS por completo)
    # SECURE_HSTS_SECONDS = 31536000
    # SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # SECURE_HSTS_PRELOAD = True

# -------------------------------------------------
# Logging (Render mostra no painel de Logs)
# -------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
if not DEBUG:
    import logging
    logging.getLogger(__name__).info("ALLOWED_HOSTS=%s", ALLOWED_HOSTS)
    logging.getLogger(__name__).info("CSRF_TRUSTED_ORIGINS=%s", CSRF_TRUSTED_ORIGINS)
