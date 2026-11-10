SECRET_KEY = "test-secret-key"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django_admin_runner",
    "tests.testapp",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        # django-tasks' db_worker refuses SQLite transactions that aren't EXCLUSIVE
        "OPTIONS": {"transaction_mode": "EXCLUSIVE"},
    }
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.request",
            ]
        },
    }
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ROOT_URLCONF = "tests.urls"

# ImmediateBackend — runs tasks inline, no worker needed. Django < 6.0 has no
# django.tasks, so the tests use the django-tasks backport there.
import importlib.util  # noqa: E402

HAS_DJANGO_TASKS_BUILTIN = importlib.util.find_spec("django.tasks") is not None
HAS_DJANGO_TASKS_BACKPORT = importlib.util.find_spec("django_tasks") is not None
# django-tasks 0.12 moved its database backend out into its own package
HAS_DJANGO_TASKS_DB = (
    HAS_DJANGO_TASKS_BACKPORT
    and importlib.util.find_spec("django_tasks.backends.database") is not None
)

_TASKS_PKG = "django.tasks" if HAS_DJANGO_TASKS_BUILTIN else "django_tasks"

TASKS = {
    "default": {
        "BACKEND": f"{_TASKS_PKG}.backends.immediate.ImmediateBackend",
    }
}
if not HAS_DJANGO_TASKS_BUILTIN:
    # The backport waits for the transaction to commit, which a test
    # transaction never does (Django 6.0 dropped the option).
    TASKS["default"]["ENQUEUE_ON_COMMIT"] = False

if HAS_DJANGO_TASKS_BACKPORT:
    INSTALLED_APPS += ["django_tasks"]
if HAS_DJANGO_TASKS_DB:
    INSTALLED_APPS += ["django_tasks.backends.database"]
