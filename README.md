# DOCLY (Mostrador)

Reformatea un `.docx` o `.doc` a APA, IEEE o Vancouver, o mejora su formato. Gemini solo asigna roles
semánticos a los bloques; el estilo visual lo aplican plantillas deterministas.

Documentación del proyecto: `SPEC.md` (spec oficial), `CLAUDE.md` (guía de trabajo), `DESIGN.md` (diseño).

## Desarrollo local

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
cp .env.example .env            # y completa GEMINI_API_KEY
.venv/Scripts/python.exe -m uvicorn --app-dir mostrador webapp.main:app --port 8000
```

## Desplegar gratis en Render

1. Sube el repositorio a GitHub (puede ser **privado**). El archivo `.env` no se sube: está en `.gitignore`.
2. En [render.com](https://render.com): **New → Blueprint**, conecta el repositorio y aplica. Render lee
   `render.yaml`, construye el `Dockerfile` y crea el servicio `docly` en el plan gratuito.
3. Cuando te lo pida, escribe `GEMINI_API_KEY` (y `GROQ_API_KEY` si la usas). Son secretos: solo viven en Render.
4. Espera la construcción (pestaña **Logs**; la primera vez tarda varios minutos por LibreOffice).
5. La aplicación queda en `https://docly.onrender.com` (o el nombre que Render asigne).

Los límites del despliegue (3 documentos por IP y día, 10 MB por archivo, sesiones que se borran al
recargar o tras una hora) están en las variables de entorno del `Dockerfile` y se cambian en
**Environment** del servicio, sin tocar el código.

### Qué esperar del plan gratuito

- El servicio **se duerme tras 15 minutos sin visitas** y tarda cerca de un minuto en despertar; durante ese
  tiempo Render muestra su propia pantalla de espera. Si la pestaña ya estaba abierta, DOCLY avisa en el primer clic.
- Tiene **512 MB de RAM**. LibreOffice (vista previa y PDF) es lo más pesado: si Render reinicia el servicio con el
  motivo *out of memory* (pestaña **Events**), este plan no alcanza.
- El contador diario vive en memoria: se pierde cuando el servicio se duerme o se reinicia.

### Comprobar tras el primer despliegue

- `https://<tu-servicio>.onrender.com/health` responde `{"status":"ok"}`.
- **Procesa un documento real** y abre su vista previa en PDF: es lo que más memoria usa. Mira la pestaña
  **Metrics** de Render durante la conversión.
- **El contador diario es por IP.** Procesa un documento desde una red y abre la aplicación desde otra (wifi y datos
  móviles): en la segunda, «Hoy te quedan» debe seguir en 3. Si baja en las dos, el servidor no ve la IP real:
  ajusta `MOSTRADOR_CLIENT_IP_HEADER` / `MOSTRADOR_TRUSTED_PROXY_HOPS` (ver `mostrador/webapp/api/limits.py`).

### Privacidad

El contenido de los documentos se envía a Gemini. En el nivel gratuito de la API de Gemini, Google puede
usar esos datos para mejorar sus productos y personas pueden revisarlos (ver los
[términos de la API de Gemini](https://ai.google.dev/gemini-api/terms)); no subas información sensible o
confidencial, o activa la facturación de la clave para pasar a los términos de pago.
