# Imagen de Mostrador para hostings con contenedores (Render, Cloud Run, Fly.io...).
#
# Construir y probar en local:
#   docker build -t mostrador .
#   docker run --rm -p 7860:7860 -e GEMINI_API_KEY=... mostrador
#   -> http://localhost:7860
#
# Las claves (GEMINI_API_KEY, GROQ_API_KEY) NO van en la imagen: se configuran como secretos o
# variables de entorno en el hosting. El contenedor no necesita disco persistente: los documentos
# viven por sesion en /tmp y se borran al recargar la pagina o tras una hora sin actividad.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# LibreOffice (vista previa y PDF) y fuentes metricamente compatibles con las de Word:
# Liberation ~ Times New Roman/Arial/Courier, Carlito ~ Calibri, Caladea ~ Cambria.
# Sin ellas el PDF cambia de paginado respecto al .docx.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY mostrador ./mostrador

# Usuario sin privilegios (LibreOffice necesita un HOME escribible).
RUN useradd --create-home --uid 1000 mostrador
USER mostrador

# Valores por defecto del despliegue gratuito; todos se pueden sobrescribir en el hosting.
ENV MOSTRADOR_STORAGE_DIR=/tmp/mostrador/storage \
    OUTPUT_DIR=/tmp/mostrador/output \
    LIBREOFFICE_BIN=libreoffice \
    MAX_FILE_SIZE_BYTES=10485760 \
    MOSTRADOR_DAILY_LIMIT=3 \
    MOSTRADOR_SESSION_TTL_MINUTES=60 \
    MOSTRADOR_TRUSTED_PROXY_HOPS=auto \
    MOSTRADOR_CLIENT_IP_HEADER=cf-connecting-ip

# Render y Cloud Run inyectan su propio PORT; 7860 es el valor por defecto fuera de ellos.
EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','7860'), timeout=4)"

# Un solo proceso: el bloqueo de "un documento a la vez" y las sesiones viven en memoria.
CMD ["sh", "-c", "exec uvicorn --app-dir mostrador webapp.main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
