# SPEC Mostrador

**Versión:** 1.0 (ampliada)
**Estado:** Referencia oficial del proyecto — este documento debe consultarse antes de tomar cualquier decisión de implementación. Cualquier desviación de la IA o de un colaborador respecto a este spec debe ser detectada y corregida contra este archivo.

---

## 1. QUÉ HACE LA APLICACIÓN

Mostrador (en la interfaz de usuario la plataforma se llama **DOCLY**; el código, los paquetes y este spec conservan el nombre Mostrador) es una plataforma que automatiza el proceso de mejorar y aplicar plantillas de formato a documentos subidos por el cliente. Analiza y convierte documentos a tres normas de citación/formato académico-profesional:

- **APA (7.ª Edición)**
- **IEEE**
- **Vancouver**

Además de aplicar la norma de citación, cada opción de formato incluye una **mejora de estilo visual** determinística (no ambigua — ver sección 4).

La opción principal del panel es **Mejora de formato** (`FormatStyle.IMPROVEMENT`, valor `mejora`): aplica solo la mejora de estilo visual (portada, índice, encabezados jerárquicos con acento, líneas separadoras, número de página) sin imponer ninguna norma de citación; los encabezados y las referencias conservan su texto, sin numerar. Las otras tres opciones son APA, IEEE y Vancouver.

---

## 2. FUNCIONALIDADES DE LA V1

- Panel web donde el usuario adjunta un documento Word (.docx o .doc)
- Selección de una opción de formato mediante tarjetas (Mejora de formato / APA / IEEE / Vancouver), cada una con su mejora de estilo incluida
- Un solo archivo a la vez: mientras un documento se procesa (o espera la confirmación de sobrescritura) la interfaz bloquea el selector, el archivo y el borrado, y el servidor responde 409 a cualquier subida adicional
- Procesamiento automático vía pipeline de 7 pasos (ver sección 5)
- Entrega del documento final en formato .docx, junto con una vista previa

---

## 3. ALCANCE DE ENTRADA Y SALIDA

### Formatos de entrada soportados en v1

| Formato | Soporte | Estrategia técnica |
|---|---|---|
| **.docx** | ✅ Soporte nativo, caso principal | Lectura directa vía `python-docx` + `lxml` (extracción de estructura semántica desde el XML/OpenXML) |
| **.doc** | ✅ Soportado vía conversión | Conversión previa a .docx usando LibreOffice headless, luego tratado como .docx |
| **.pdf** | ❌ Fuera de alcance v1 | No se acepta como entrada en esta versión. Ver sección 8 (Fuera de Alcance) |

**Justificación técnica:** DOCX es un archivo ZIP con XML estructurado (OpenXML), el mismo estándar usado para generar los documentos de salida. Esto permite leer directamente la estructura semántica del documento (heading, párrafo, lista, etc.) sin necesidad de heurísticas de reconstrucción, a diferencia de PDF, que es un formato de presentación visual sin estructura semántica explícita.

### Límites de entrada

- Tamaño máximo de archivo: **50MB**
- Documentos con contraseña/protegidos: **rechazados con mensaje de error claro**
- Documentos corruptos o no parseables: **rechazados antes de entrar al pipeline**, con mensaje de error específico al usuario

### Formato de salida

- **.docx** (formato final entregado al usuario)
- Vista previa renderizada (imagen PNG de la primera página, generada vía LibreOffice headless con `--convert-to png`; no se usa `pdftoppm`) — no editable, solo para revisión visual antes de descargar
- Vista previa completa en **PDF** (decisión posterior a la v1 inicial): `GET /api/documents/{id}/pdf` convierte el `.docx` resultante con LibreOffice headless (`--convert-to pdf`, perfil de usuario aislado para no chocar con el pipeline) la primera vez que se pide y lo guarda como `{id}.pdf` junto al `.docx`; las aperturas siguientes lo sirven sin reconvertir. Se muestra en un visor del panel antes de descargar. Es solo de lectura: la entrega sigue siendo el `.docx` (no cambia la sección 8, que excluye PDF como formato de salida final).

---

## 4. DEFINICIÓN DE "MEJORA DE ESTILO" (sin ambigüedad)

Cada template de formato (APA / IEEE / Vancouver) debe tener definido explícitamente, en el `TEMPLATES` dict, lo siguiente — nada de esto se decide "on the fly" ni queda a interpretación de la IA en tiempo de ejecución:

1. **Paleta de colores**: colores exactos (hex) para líneas de separación, acentos de portada, y cualquier elemento decorativo. Una paleta fija por template, no generada dinámicamente.
2. **Estructura de portada**: campos exactos que incluye (título, autor, institución, fecha, etc.), su orden, y su disposición — definida como layout fijo, no "creativo".
3. **Líneas de separación**: dónde se insertan (ej. entre secciones de nivel 1), grosor y color, tomados de la paleta del template.
4. **Reglas de generación de índice**: si el índice se genera vía TOC nativo de Word (campo `TOC` de OpenXML) o se construye por código recorriendo los headings clasificados por Gemini. Debe especificarse cuál mecanismo se usa y por qué.
5. **Consistencia de estilo**: todos los elementos decorativos (color, tipografía, espaciado) deben provenir del mismo `TEMPLATES[style]` — la IA de clasificación (Gemini) nunca decide estilo visual, solo clasifica roles semánticos (`heading1`, `body`, `list_item`, `reference`, etc.)

### Decisiones de implementación: portada y referencias

Casos que el layout fijo no cubría y que aparecieron con documentos reales. Se resuelven en código determinístico (`template_engine.py`, `docx_builder.py`), nunca por la IA:

- **Orden de la portada**: los campos `cover_*` se agrupan por rol y se ordenan según `cover_field_order` del template. Dentro de un rol se conserva el orden original.
- **Etiquetas**: un bloque de portada cuyo texto termina en `:` (p. ej. "Alumnos:", "Materia:") toma el rol del campo de portada que lo sigue, para que el reordenado no lo separe de su valor.
- **Imágenes de portada**: las imágenes situadas antes del primer heading y antes o entre campos de portada (p. ej. el logo) pertenecen a la portada: se colocan al inicio de ella, a un ancho máximo de 2,2", y no pasan al cuerpo.
- **Líneas repetidas**: si un mismo rol de portada contiene dos líneas con el mismo texto (ignorando espacios), se conserva solo la primera (un cuadro de texto de portada puede repetir la institución). Solo aplica a la portada.
- **Espaciado**: se aplica un único hueco antes del primer bloque de cada grupo (autor, institución, curso) para que una portada típica quepa en una página.
- **Numeración de referencias**: si el texto de una referencia ya trae su número (`[3]`, `3.`, `3)`, `(3)`), se elimina antes de aplicar la numeración del template (IEEE `[n]`, Vancouver `n.`); así no se duplica. En APA el texto no se modifica.

### APA 7 por tipo de documento

El template APA sigue los trabajos de ejemplo oficiales de APA (carpeta `APA documents examples/`) y se distingue de IEEE/Vancouver por `TemplateSpec.apa_layout`: todo en negro, sin índice ni líneas decorativas, Times New Roman 12 a doble espacio, márgenes de 1", texto alineado a la izquierda con sangría de primera línea de 0,5", encabezados de nivel 1 (centrado, negrita), 2 (izquierda, negrita), 3 (izquierda, negrita cursiva) y 4 (sangrado, negrita), tablas solo con líneas horizontales (sobre y bajo el encabezado y al pie), rótulos "Table 1"/"Figure 1" en negrita seguidos del título en cursiva, referencias con sangría francesa sin numerar y número de página arriba a la derecha. El tipo de documento (Paso 3) decide la estructura; `template_engine.py` pone las marcas (`page_break_before`, bloques sintéticos) y `docx_builder.py` las dibuja:

| Caso | Estructura |
|---|---|
| `student_paper` (y `other`) | Portada (título en negrita, autor, institución, curso, profesor, fecha, centrados) → resumen y palabras clave en página propia, si existen → título repetido en negrita y centrado → texto → referencias (página nueva) → apéndices (página nueva cada uno). Sin encabezado de página: solo el número. |
| `professional_paper` | Igual, pero la portada lleva título, autores y afiliaciones y la **nota del autor** se queda en esa página; el encabezado de página lleva el título en mayúsculas (máx. 50 caracteres) a la izquierda y el número a la derecha. |
| `annotated_bibliography` | Portada → título repetido → entradas (sangría francesa) con su anotación sangrada debajo. No se antepone "Referencias". |

Reglas deterministas de apoyo: el título repetido se inserta si el documento no lo repite; si la IA dejó el título de portada como `heading1`, el primer `heading1` anterior a los campos de portada (y los `heading1` seguidos, si el título ocupa varias líneas) pasa a `cover_title`; si la IA no marcó ningún campo de portada en un trabajo de estudiante o artículo, las líneas cortas entre el título y "Author Note"/"Abstract" se asignan por posición (autor, institución, curso, profesor, fecha; en un artículo, autor y luego afiliaciones). El título "Referencias" ya presente en el documento se reutiliza en vez de duplicarlo. Los títulos de sección se reconocen en español e inglés (`engine/formatting/section_titles.py`).

---

## 5. PIPELINE TÉCNICO (7 pasos)

1. **Upload** — el usuario sube el documento vía panel web
2. **Extracción de contenido** — lectura de texto y estructura desde .docx (o .doc convertido) usando `python-docx` + `lxml`
3. **Detección de estructura (IA)** — Gemini clasifica cada bloque de contenido con un rol semántico estructurado (JSON): `heading1`, `heading2`, `body`, `list_item`, `reference`, etc. En la misma llamada devuelve el **tipo de documento** (`student_paper`, `professional_paper`, `annotated_bibliography`, `other`); la IA solo etiqueta, el formato de cada caso lo decide el código.
4. **Aplicación de template** — código determinístico (no IA) aplica el `TEMPLATES[style]` correspondiente sobre los roles clasificados
5. **Generación de .docx** — se construye el documento final vía `python-docx`, incluyendo `styles.xml` y `numbering.xml` personalizados
6. **Renderizado de preview** — conversión de la primera página a imagen PNG vía LibreOffice headless (`--convert-to png`) para vista previa. Paso no fatal: si falla, el `.docx` se entrega igual sin preview
7. **Entrega** — el archivo .docx final (y su preview) se entregan al usuario

### Principio arquitectónico clave: separación IA / determinístico

- **Gemini (Paso 3)**: solo clasificación semántica (roles y tipo de documento). Nunca decide estilo visual, colores, ni estructura de portada.
- **Código (Pasos 4–6)**: aplicación de estilo 100% determinística, basada en el `TEMPLATES` dict. Esto mantiene el sistema predecible, auditable, y evita que una alucinación de la IA afecte el resultado visual final.

---

## 6. CRITERIOS DE ACEPTACIÓN

Un documento se considera correctamente procesado cuando:

- El `.docx` de salida pasa validación contra el esquema XSD de OpenXML. Implementación: tras el Paso 5, `engine/document/xsd_validator.py` valida las partes WordprocessingML contra los XSD transitional de ECMA-376 (Parte 4) y `[Content_Types].xml`/`.rels` contra los de OPC (Parte 2), previa eliminación de las extensiones MCE (`mc:Ignorable`, `AlternateContent`). Si falla, el archivo de salida se descarta y el usuario recibe el error `OUTPUT_SCHEMA_INVALID` (defecto del motor, no del documento). Se puede desactivar con `ProcessingConfig.validate_output_xsd`. Los esquemas se versionan en `engine/document/schemas/ooxml/`
- La vista previa renderizada coincide visualmente con el template seleccionado (paleta, portada, líneas de separación, índice)
- No hay pérdida de contenido textual respecto al documento original (texto de entrada = texto de salida, solo cambia el formato) — salvo la numeración de referencias que reescribe el template y las líneas de portada duplicadas, ambas descritas en la sección 4
- Todos los headings clasificados por Gemini en el Paso 3 aparecen correctamente reflejados en el índice generado
- El documento final abre sin errores de corrupción en Word / LibreOffice

---

## 7. CASOS LÍMITE (edge cases)

| Caso | Comportamiento esperado |
|---|---|
| Documento corrupto / no parseable | Rechazo inmediato antes del pipeline, mensaje de error claro al usuario |
| Documento ya formateado con estilos propios conflictivos | Se detecta el conflicto y se avisa al usuario; el usuario decide si sobrescribir los estilos existentes o no |
| Documento escaneado (imagen, sin texto seleccionable) | Fuera de alcance v1 — no hay OCR. Debe rechazarse o marcarse como no soportado |
| Tablas embebidas | Se les aplica el estilo del template también |
| Ecuaciones embebidas (OMML) | Se preservan sin modificar |
| Imágenes embebidas en el documento original | Se conservan en su posición relativa |
| Documento vacío o solo con portada | Rechazo con mensaje de error |
| Documento en idioma distinto al español/inglés | Hay soporte multi-idioma en v1 |

---

## 8. FUERA DE ALCANCE PARA V1 (explícito)

Para evitar que la IA o cualquier colaborador "mejore" el proyecto agregando funcionalidad no solicitada, se declara explícitamente fuera de alcance en v1:

- Soporte de entrada **PDF** (pospuesto a versión futura)
- OCR para documentos escaneados
- Edición colaborativa en tiempo real
- Historial de versiones de documentos procesados
- Autenticación de usuarios / cuentas (a menos que se especifique en requisitos no funcionales)
- Personalización manual de la paleta de colores por parte del usuario (las paletas son fijas por template en v1)
- Exportación a formatos distintos de .docx (ej. PDF final editable, HTML)

---

## 9. REQUISITOS NO FUNCIONALES

- **Tiempo de procesamiento esperado**: Procesamiento **síncrono** — el usuario espera en el panel mientras se ejecuta el pipeline completo. Implicación directa: la latencia del Paso 3 (llamada a Gemini) impacta directamente la percepción de velocidad de la app; debe monitorearse de cerca.
- **Costos de API**:
  - **Estrategia v1**: operar dentro del tier gratuito de Gemini (modelos Flash / Flash-Lite). No se contempla presupuesto en dólares para v1 — costo objetivo: $0.
  - **Límites del free tier de Gemini (verificar en Google AI Studio, cambian sin aviso)**: aprox. 5-15 solicitudes por minuto y hasta 1,000-1,500 solicitudes diarias según el modelo (Flash-Lite tiene el límite más alto). Con concurrencia = 1 documento a la vez (ver punto de Concurrencia), esto es suficiente para v1 sin acercarse al límite en uso normal.
  - **Regla de una llamada por documento**: en v1 no se hace chunking — cada documento genera una sola llamada a Gemini en el Paso 3. Si un documento requiere ser dividido en múltiples llamadas por su tamaño, se rechaza (ver Límites de entrada, sección 3) en vez de fragmentar.
  - **Aviso de privacidad relevante**: en el tier gratuito, Google puede usar los prompts/respuestas enviados a Gemini para mejorar sus modelos. Esto debe reflejarse en el aviso de privacidad de la plataforma, ya que se procesan documentos de usuarios.
  - **Estrategia si se excede el límite diario/por minuto**: la solicitud a Gemini falla con error de rate limit → el documento se marca como "error temporal, reintentar más tarde" (no se descarta permanentemente) → no hay reintento automático inmediato en v1, el usuario reintenta manualmente.
  - **Proveedor de respaldo (fallback) — implementado y opcional**: se activa solo si se configura `GROQ_API_KEY`. Groq (modelos open-source vía LPU, free tier de hasta ~14,400 solicitudes/día, API compatible con el SDK de OpenAI, lo que facilita el fallback). Si se implementa, debe usarse solo cuando Gemini devuelva error de rate limit, no como balanceo de carga activo.
  - **Punto de revisión**: si el volumen de documentos procesados se acerca de forma sostenida al 70% del límite diario gratuito, se evalúa pasar a tier de pago de Gemini o activar el fallback a Groq de forma permanente.
- **Almacenamiento y seguridad de documentos**: Se almacenan todos los documentos procesados (originales y resultantes). El usuario tiene un botón para eliminar cada documento individualmente desde el panel. **Pendiente afinar**: cifrado en reposo, retención por defecto si el usuario nunca elimina manualmente. **Decisión posterior (almacenamiento efímero por sesión)**: cada carga de la página es una sesión nueva (uuid4 generado por el navegador, solo en memoria) y sus documentos viven en `{storage}/{sid}/`; una sesión solo ve los suyos. Recargar o cerrar la página llama a `POST /api/session/end` (sendBeacon) y borra la sesión; como respaldo, un barrido cada 5 min elimina las que llevan más de `MOSTRADOR_SESSION_TTL_MINUTES` (60 por defecto) sin actividad. Esto sustituye al historial compartido y resuelve la retención por defecto; el borrado individual se mantiene. Sigue pendiente el cifrado en reposo. **Decisión posterior (despliegue gratuito)**: el servidor se empaqueta con el `Dockerfile` de la raíz (LibreOffice y fuentes compatibles con Word incluidos, un solo proceso, sin disco persistente). Único control de uso: **límite diario de documentos por IP** (`MOSTRADOR_DAILY_LIMIT`, 3 por defecto, 0 = sin límite; día UTC; cuentan solo los documentos procesados con éxito; el contador vive en memoria y se pierde si el servidor se reinicia). Tras un proxy, la IP real se lee de `X-Forwarded-For` según `MOSTRADOR_TRUSTED_PROXY_HOPS` (un número de proxies de confianza, o `auto`: la entrada más a la derecha que sea una IP pública; es el valor por defecto del contenedor, porque los hostings no documentan cuántos proxies hay). Además, `MOSTRADOR_CLIENT_IP_HEADER` (`cf-connecting-ip` en el contenedor) da prioridad a la cabecera que el proxy de confianza sobrescribe: Render pone Cloudflare delante y no limpia `X-Forwarded-For`. Destino elegido: **Render, plan gratuito** (`render.yaml` + `Dockerfile`; Hugging Face Spaces dejó de permitir Docker en cuentas gratuitas nuevas). El `README.md` raíz tiene los pasos y las comprobaciones posteriores (512 MB de RAM: la conversión a PDF es lo que más memoria usa). `GET /api/limits` informa del cupo restante y del tamaño máximo (10 MB en el contenedor); `GET /health` responde de inmediato. La conversión a PDF usa el mismo bloqueo que el pipeline: nunca dos LibreOffice a la vez. La interfaz muestra una pantalla de carga con el logo y un porcentaje mientras comprueba que el servidor responde y, si tarda más de 6 s (servidor dormido), muestra la página y avisa en el primer clic.
- **Concurrencia**: v1 procesa **1 documento a la vez** (sin cola paralela). Cualquier solicitud adicional espera a que termine la que está en curso.
- **Disponibilidad**: **Mejor esfuerzo (best effort)** en v1 — sin SLA formal comprometido con el usuario. Se recomienda definir un SLO interno (tiempo de respuesta objetivo, ej. p95) una vez haya datos reales de uso, y revisar la formalización de un SLA tras las primeras semanas en producción.

---

## 9.1 ARQUITECTURA DEL PROYECTO (estructura de carpetas)

**Decisión:** Estructura **Modular por Dominio (Domain-First)**, con separación explícita entre el motor de procesamiento y la capa de servicio web.

### Razón de la decisión

Mostrador tiene un requisito a futuro: poder extraerse e integrarse como módulo dentro de otro proyecto. Esto descarta una estructura por capas basada en pasos secuenciales (`step1_...py`, `step2_...py`), porque acopla la lógica de negocio al orden de ejecución interno en vez de a los dominios del problema (extracción, clasificación, formato). Una estructura por dominio permite:

- Importar solo el dominio necesario (ej. `classification/`) sin arrastrar el resto del pipeline
- Tener un contrato de datos explícito (`models.py`) entre el paso de IA (clasificación) y el paso determinístico (aplicación de estilo), reforzando el principio de separación IA/código del spec (sección 5)
- Añadir un proveedor de respaldo (Groq, sección 9) sin tocar el resto del sistema
- Trabajar en paralelo sobre distintos dominios sin conflictos de merge

### Estructura de carpetas

```
mostrador/
├── engine/                    # Motor de procesamiento — el módulo reusable/embebible.
│   │                          # No debe depender de FastAPI/Flask, rutas HTTP, ni sesiones de usuario.
│   │                          # Punto de entrada público: engine.process_document(doc, style=...)
│   ├── __init__.py
│   ├── core/
│   │   ├── pipeline.py        # Orquestador: ensambla y ejecuta los 7 pasos (§5)
│   │   └── exceptions.py      # Errores de dominio (DocumentCorrupt, UnsupportedFormat, etc.)
│   │
│   ├── document/
│   │   ├── extractor.py       # Paso 2: python-docx + lxml → estructura semántica
│   │   ├── validator.py       # Validación semántica, límites de entrada (§3, §7)
│   │   ├── xsd_validator.py   # Validación XSD del .docx de salida (§6); esquemas en schemas/ooxml/
│   │   ├── store.py           # Almacenamiento + eliminación (§9)
│   │   └── models.py          # Dataclasses: SemanticBlock, DocumentMeta (contrato IA ↔ código)
│   │
│   ├── classification/
│   │   ├── gemini_classifier.py  # Paso 3: llamada a Gemini → roles semánticos (JSON)
│   │   └── fallback.py           # Groq como fallback ante rate limit (§9), opcional vía GROQ_API_KEY
│   │
│   ├── formatting/
│   │   ├── templates.py       # TEMPLATES dict: APA, IEEE, Vancouver (§4)
│   │   ├── template_engine.py # Paso 4: aplica TEMPLATES[style] a roles clasificados
│   │   ├── docx_builder.py    # Paso 5: genera .docx + styles.xml / numbering.xml
│   │   └── preview_renderer.py # Paso 6: LibreOffice headless (--convert-to png)
│   │
│   └── config.py              # Configuración inyectable (API keys, límites) —
│                               # NUNCA hardcodeada ni leída de env globales dentro del motor;
│                               # se pasa como parámetro al invocar engine.process_document()
│
├── webapp/                    # Capa de servicio HTTP — solo para v1 standalone
│   ├── main.py                # Entrada del servidor web (FastAPI/Flask)
│   ├── api/
│   │   └── routes.py          # Endpoints: /upload, /download, /delete
│   └── static/                # Frontend del panel web (HTML/JS)
│
└── tests/
    ├── document/
    ├── classification/
    ├── formatting/
    └── fixtures/               # .docx de prueba validados
```

### Principio de diseño clave: `engine/` es agnóstico del contexto de ejecución

- `engine/` no debe importar ni depender de nada relacionado con HTTP, sesiones, ni el framework web usado en v1.
- Toda configuración (credenciales de Gemini, `TEMPLATES`, límites de tamaño) se inyecta como parámetros o un objeto de configuración al invocar el motor — nunca se lee directamente de variables de entorno globales dentro de `engine/`.
- `webapp/` es una capa delgada que traduce peticiones HTTP en llamadas a `engine.core.pipeline`. Si en el futuro Mostrador se integra en otro proyecto, **solo se lleva la carpeta `engine/`** (o se publica como paquete instalable interno) — `webapp/` no se reutiliza.

### Nota sobre escala v1

Con concurrencia = 1 documento a la vez (sección 9) y un solo desarrollador, esta estructura puede sentirse como más archivos de lo estrictamente necesario al inicio. Es una decisión intencional: se prioriza la extensibilidad futura (integración como módulo, fallback a Groq, soporte PDF en v2) sobre la simplicidad máxima de arranque.

---

## 10. TECNOLOGÍAS Y STACK

- **Lenguaje/runtime**: Python
- **Manipulación de documentos**: `python-docx`, `lxml`, esquema OpenXML (validado vía XSD)
- **Clasificación semántica (IA)**: Google Gemini (structured output / function calling)
- **Renderizado de preview**: LibreOffice headless (`--convert-to png`)
- **Conversión de formato**: LibreOffice headless (DOC → DOCX)
- **Artefactos del proyecto**: `doc_formatter.py`, `styles.xml` (styleIds personalizados), `numbering.xml`, documentos `.docx` de prueba validados

---

## 11. NOTAS DE USO DE ESTE DOCUMENTO

Este spec es la fuente de verdad del proyecto. Durante la implementación:

- Cualquier decisión de estilo, estructura o comportamiento debe poder rastrearse a una sección de este documento
- Los campos marcados **[definir]** son huecos conocidos — deben resolverse y actualizarse aquí antes de que el código dependa de ellos, no decidirse implícitamente durante la implementación
- Si la IA (o un colaborador) toma una decisión no cubierta aquí, esa decisión debe añadirse a este spec, no quedar solo en el código o en el historial de conversación
