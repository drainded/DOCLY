# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Estudiantes universitarios que deben entregar trabajos, informes o tesis en la norma que pide su institución. Llegan con un documento de Word ya escrito y poco tiempo; suelen tener poca experiencia con estilos de Word. Su trabajo en el panel es subir un archivo, elegir qué formato quieren y descargar el resultado. Confirmado por el usuario; otros perfiles (investigadores, docentes) no están confirmados.

## Product Purpose

DOCLY (antes Mostrador; el código y los paquetes conservan ese nombre) reformatea un documento `.docx` o `.doc` y lo devuelve como `.docx`. Ofrece cuatro opciones: Mejora de formato (solo mejora visual, sin norma de citación; es la opción principal), APA 7, IEEE y Vancouver. El éxito es que el estudiante descargue un documento correcto sin haber tocado un estilo de Word y sin perder contenido.

## Positioning

Lee el documento y lo reconstruye: la IA identifica qué es cada parte (portada, resumen, encabezados, referencias, tablas) y el tipo de documento (trabajo de estudiante, artículo, bibliografía anotada), y el código aplica el formato completo de forma determinística. No es una plantilla que el usuario rellene a mano. Confirmado por el usuario.

## Operating Context

- Panel web de una sola pantalla: subir un archivo, elegir formato en tarjetas, procesar, y lista de documentos procesados con descarga, vista previa y eliminación.
- Un documento a la vez; el procesamiento es síncrono y el usuario espera en el panel. Mientras se procesa se bloquean los controles que puedan interferir.
- Si el documento trae estilos propios que chocan con el formato elegido, se pide confirmación antes de sobrescribirlos.
- Los documentos procesados se guardan en el servidor; el usuario puede eliminarlos uno a uno.
- El contenido del documento se envía a un servicio de IA (Gemini) para clasificarlo; el aviso de privacidad correspondiente está pendiente en el spec.
- Entrada hasta 50 MB; se rechazan documentos corruptos, con contraseña, vacíos o escaneados.

## Capabilities and Constraints

- Sin cuentas ni autenticación en v1.
- Interfaz y mensajes en español (confirmado). El motor reconoce documentos en español e inglés.
- Salida siempre `.docx` más una vista previa de la primera página.
- La IA solo etiqueta roles semánticos; nunca decide estilo visual. Toda la apariencia sale de plantillas fijas.
- Frontend de HTML, CSS y JS planos, sin paso de build, servido por FastAPI.
- Pendiente de definir en el spec: cifrado en reposo y retención de documentos.

## Evidence on Hand

- `SPEC.md` (fuente de verdad del producto) y `CLAUDE.md`.
- `APA documents examples/`: 11 trabajos de ejemplo oficiales de APA usados como referencia.
- No hay testimonios, métricas de uso ni logotipo de marca; no inventarlos.

## Product Principles

- El contenido del usuario nunca se pierde ni se reescribe: se reorganiza y se le da formato.
- Un solo camino claro: subir, elegir, descargar. Cada control extra debe ganarse su lugar.
- El estado del proceso siempre es visible y, mientras trabaja, nada permite al usuario estropearlo.
- Lo determinístico manda: lo que ve el usuario sale de reglas y plantillas, no de la improvisación de la IA.
- Hablarle al estudiante en español claro, sin jerga de Word ni de la norma.
