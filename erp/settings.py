from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file explicitly
load_dotenv(dotenv_path=BASE_DIR / '.env')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or 'dev-insecure-secret-key-change-me'


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG') == 'True'

# ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS').split(',')
# ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1','localhost').split(',')
# ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
# For local development
# ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
raw_allowed_hosts = os.getenv('DJANGO_ALLOWED_HOSTS', '')
if raw_allowed_hosts:
    ALLOWED_HOSTS = [h.strip() for h in raw_allowed_hosts.split(',') if h.strip()]
else:
    # Default to allow local development hosts
    ALLOWED_HOSTS = []

# Always include local development hosts
if '127.0.0.1' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('127.0.0.1')
if 'localhost' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('localhost')


# ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', '127.0.0.1').split(',')


SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'company',
    'client',
    'transport',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'erp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'erp.context_processors.global_data',
            ],
        },
    },
]

WSGI_APPLICATION = 'erp.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        # 'HOST': os.getenv('DB_HOST'),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        # 'PORT': os.getenv('DB_PORT', '3306'),
        'PORT': int(os.getenv('DB_PORT', 3306)),
        'OPTIONS': {
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'
USE_TZ = True
USE_I18N = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = '/assets/'
STATICFILES_DIRS  = [BASE_DIR / "assets"]

STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

#SESSION_COOKIE_SECURE = False
#CSRF_COOKIE_SECURE = False
#SECURE_SSL_REDIRECT = False
#SECURE_HSTS_SECONDS = 31536000
#SECURE_HSTS_INCLUDE_SUBDOMAINS = True
#SECURE_HSTS_PRELOAD = True
#SECURE_BROWSER_XSS_FILTER = True
#SECURE_CONTENT_TYPE_NOSNIFF = True