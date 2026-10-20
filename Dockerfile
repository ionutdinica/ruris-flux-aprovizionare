# Imaginea aplicației: „rețeta” după care Docker construiește un mini-calculator
# Linux care conține Python, bibliotecile și codul nostru.

FROM python:3.13-slim

# Python: fără fișiere .pyc și cu afișarea imediată a mesajelor în log.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Întâi doar lista de biblioteci: Docker refolosește acest pas din cache
# cât timp requirements.txt nu se schimbă, deci reconstruirea e rapidă.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Apoi codul aplicației.
COPY . .

# Aplicația nu rulează ca administrator (root) în container, din motive de securitate.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["sh", "docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
