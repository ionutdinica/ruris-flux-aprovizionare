"""
Setările aplicației.

Valorile care diferă de la un mediu la altul (calculatorul dezvoltatorului,
Docker, serverul online) NU sunt scrise aici, ci citite din variabile de mediu
sau din fișierul `.env` (vezi `.env.example` pentru lista completă).
Astfel același cod rulează peste tot, iar parolele nu ajung în Git.
"""

from decimal import Decimal
from pathlib import Path

import environ
from django.contrib.messages import constants as message_constants

BASE_DIR = Path(__file__).resolve().parent.parent

# Variabilele de mediu și valorile implicite (folosite dacă variabila lipsește).
# Valorile implicite sunt alese pentru dezvoltare locală.
env = environ.Env(
    DEBUG=(bool, False),
    USE_HTTPS=(bool, None),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    SITE_URL=(str, "http://127.0.0.1:8000"),
    DEFAULT_FROM_EMAIL=(str, "Aprovizionare RURIS <aprovizionare@ruris.local>"),
    PRICE_TOLERANCE_PERCENT=(str, "0"),
    NOTIFICATION_HOUR=(int, 8),
)
# Fișierul .env e opțional: pe serverul online variabilele vin direct din mediu.
environ.Env.read_env(BASE_DIR / ".env")


# --- Securitate ---------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY")  # obligatorie: fără ea aplicația nu pornește
DEBUG = env("DEBUG")  # True doar local: afișează erorile detaliat
ALLOWED_HOSTS = env("ALLOWED_HOSTS")  # domeniile de pe care răspunde aplicația
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Aplicația e servită prin HTTPS? Implicit: da în producție (DEBUG=False).
# Docker Compose local setează USE_HTTPS=False (rulează pe http://localhost).
USE_HTTPS = env("USE_HTTPS") if env("USE_HTTPS") is not None else not DEBUG

if USE_HTTPS:
    # Online, aplicația rulează în spatele unui proxy care face HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True  # cookie-ul de sesiune se trimite doar pe HTTPS
    CSRF_COOKIE_SECURE = True


# --- Module -------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Biblioteci externe
    "auditlog",  # jurnalul automat al modificărilor (cine, ce, când)
    # Modulele aplicației (vezi PLAN.md, capitolul 1.2)
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.catalog",
    "apps.purchasing",
    "apps.warehouse",
    "apps.invoicing",
    "apps.currency",
    "apps.notifications",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # fișierele statice în producție
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Toate paginile cer autentificare, cu excepția celor marcate explicit
    # (pagina de login). „Sigur în mod implicit”: o pagină nouă nu poate
    # rămâne publică din greșeală.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    # Rețin utilizatorul și IP-ul cererii curente, ca jurnalul de audit să știe
    # CINE a făcut fiecare acțiune: primul pentru modificările de câmpuri
    # (django-auditlog), al doilea pentru evenimentele de business.
    "auditlog.middleware.AuditlogMiddleware",
    "apps.audit.context.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # șabloanele comune (layout, login)
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.dashboard.context_processors.navigation",  # meniul pe rol
            ],
        },
    },
]


# --- Baza de date ---------------------------------------------------------------
# Implicit SQLite (un fișier local, zero instalare). În Docker și online se
# setează DATABASE_URL=postgres://utilizator:parola@server:5432/nume_baza

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Utilizatori și autentificare ---------------------------------------------

AUTH_USER_MODEL = "accounts.User"  # modelul propriu, cu rol

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"  # după login
LOGOUT_REDIRECT_URL = "accounts:login"  # după logout

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Limbă, fus orar ----------------------------------------------------------

LANGUAGE_CODE = "ro"
TIME_ZONE = "Europe/Bucharest"
USE_I18N = True
USE_TZ = True  # datele se salvează în UTC și se afișează în ora României
USE_THOUSAND_SEPARATOR = True  # 1.250,00 (format românesc)


# --- Fișiere statice (CSS, JavaScript, imagini) ---------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # unde le adună `collectstatic` pentru producție

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # În producție, WhiteNoise comprimă fișierele și le adaugă o amprentă în nume
    # (ex. app.3f2a1b.css), ca browserele să nu folosească o versiune veche din cache.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}


# --- Mesaje (confirmări / erori afișate utilizatorului) ------------------------

# Bootstrap numește „danger” ce Django numește „error”.
MESSAGE_TAGS = {message_constants.ERROR: "danger"}


# --- Jurnal de audit (django-auditlog) -----------------------------------------
# Lista modelelor urmărite, într-un singur loc. Orice creare / modificare /
# ștergere a lor se înregistrează automat: cine, când, IP, câmp vechi → nou.
# Se completează în fiecare capitol, pe măsură ce apar modele noi.

# Câmpuri tehnice, recalculate la fiecare salvare: ar fi doar zgomot în jurnal.
_TIMESTAMPS = ["created_at", "updated_at", "search_text"]

AUDITLOG_INCLUDE_TRACKING_MODELS = (
    {
        "model": "accounts.User",
        "exclude_fields": ["last_login"],  # se schimbă la fiecare login: zgomot
        "mask_fields": ["password"],  # se vede că s-a schimbat, nu și valoarea
    },
    {"model": "catalog.Supplier", "exclude_fields": _TIMESTAMPS},
    {"model": "catalog.Product", "exclude_fields": _TIMESTAMPS},
    {"model": "purchasing.PurchaseOrder", "exclude_fields": _TIMESTAMPS},
    {"model": "purchasing.PurchaseOrderLine", "exclude_fields": _TIMESTAMPS},
    {"model": "warehouse.GoodsReceipt", "exclude_fields": _TIMESTAMPS},
    {"model": "warehouse.GoodsReceiptLine", "exclude_fields": _TIMESTAMPS},
    {"model": "warehouse.Discrepancy", "exclude_fields": _TIMESTAMPS},
    {"model": "warehouse.StockMovement", "exclude_fields": _TIMESTAMPS},
)
AUDITLOG_MASK_CALLABLE = "apps.audit.utils.mask_completely"
AUDITLOG_STORE_JSON_CHANGES = True  # modificările se salvează structurat (JSON)


# --- Email ------------------------------------------------------------------------
# Implicit: emailurile se afișează în terminal (nu pleacă nicăieri).
# Cu Mailpit (Docker): EMAIL_URL=smtp://localhost:1025
# Online: EMAIL_URL=smtp+tls://utilizator:parola@server-smtp:587

vars().update(env.email("EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")


# --- Setări specifice aplicației ------------------------------------------------

# Adresa publică a aplicației, folosită în link-urile din emailuri.
SITE_URL = env("SITE_URL")

# Toleranța de preț la potrivirea facturilor, în procente (docs/01-ipoteze.md, I-22).
# Decimal, nu float: la bani nu se acceptă erori de rotunjire.
PRICE_TOLERANCE_PERCENT = Decimal(env("PRICE_TOLERANCE_PERCENT"))

# Ora la care pleacă rezumatul zilnic pe email (docs/05-reguli-business.md, §5).
NOTIFICATION_HOUR = env("NOTIFICATION_HOUR")
