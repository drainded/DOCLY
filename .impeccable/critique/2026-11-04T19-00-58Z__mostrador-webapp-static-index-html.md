---
target: panel de Mostrador
total_score: 23
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:C:\\Users\\aremdecay\\Documents\\Projects\\FORMATEADOR_DOCUMENTOS\\mostrador\\webapp\\static\\index.html"
target_fingerprint: "sha256:b13f028c339f52786bab805c9856e3e783e09351acd04d4f0726b7dca5033a2b"
target_path: "C:\\Users\\aremdecay\\Documents\\Projects\\FORMATEADOR_DOCUMENTOS\\mostrador\\webapp\\static\\index.html"
timestamp: 2026-11-04T19-00-58Z
slug: mostrador-webapp-static-index-html
---
# Critique: panel de Mostrador (mostrador/webapp/static/index.html)

Method: dual-agent (A: revision de diseno, B: detector y mediciones del navegador)

## Design Health Score: 23/40 (Aceptable)

| # | Heuristica | Nota | Problema clave |
|---|---|---|---|
| 1 | Visibilidad del estado | 2 | Espera sin progreso ni aria-live; formulario casi ilegible mientras procesa |
| 2 | Lenguaje del usuario | 3 | Formatos sin explicar; fechas en en-US |
| 3 | Control y libertad | 2 | No se puede cancelar el procesamiento; filas con error sin Reintentar |
| 4 | Consistencia | 2 | Descargar es un enlace azul sin estilo; botones en Arial |
| 5 | Prevencion de errores | 3 | Buen bloqueo; sin comprobacion de 50 MB en el cliente |
| 6 | Reconocimiento | 3 | Nada dice que hace cada formato |
| 7 | Flexibilidad | 2 | Sin arrastrar y soltar ni otro formato sobre el mismo archivo |
| 8 | Minimalismo | 3 | Mensaje informativo duplica el dialogo; historial largo |
| 9 | Recuperacion de errores | 2 | Error generico repetido, sin causa ni reintento |
| 10 | Ayuda | 1 | Sin ayuda de formato ni aviso de privacidad |

## Design Specificity Verdict

Mayormente generico; la metafora de DESIGN.md (El mostrador de la imprenta) no se ve en pantalla. Detector: 1 hallazgo CLI (broken-image, falso positivo: img del modal oculto) y 1 en navegador (overused-font: los botones calculan Arial, real).

## Priority Issues

- [P1] La espera no tiene progreso y es invisible a tecnologias de apoyo. Opacidad acumulada: boton de enviar ~1,6:1. Fix: role=status/aria-live, fases con tiempo, tranquilizar, no atenuar tarjeta elegida. Comando: animate + harden.
- [P1] El historial se rompe en movil (.doc-info 39 px, botones 26-29 px). Fix: apilar fila, objetivos de 44 px. Comando: adapt.
- [P1] El resultado es el momento mas debil: a.secondary sin estilo (enlace azul rgb(0,0,238)), botones en Arial, fila nueva sin resaltar, colores de estado sin variables. Comando: polish + layout.
- [P2] Dialogo de conflicto y errores no tranquilizan ni guian; faltan tildes y enes en la UI; fechas en en-US. Comando: clarify.
- [P2] Sin ayuda para elegir formato ni aviso de privacidad. Comando: onboard / clarify.

## Persona Red Flags

- Jordan: no entiende Mejora de formato; Sobrescribir suena a perder texto; ve una linea gris durante la espera.
- Sam: caja de estado sin anuncio; foco ambar 2,08:1 y solo en tarjetas; modal sin role=dialog ni Escape; Eliminar sin nombre de documento.
- Casey: lista rota en movil; botones de fila 26-29 px; Procesar 35 px.
- Priya: debe volver a elegir el archivo para probar otro formato; si sale mal solo puede borrar.

## Minor Observations

- Entrada de archivo nativa en ingles; tres iconos identicos; sin prefers-reduced-motion; recargar con conflicto pendiente pierde la subida sin avisar; historial de prueba con 6 de 11 errores.

## Questions to Consider

- Por que la pagina nunca muestra un documento? Y si el resultado fuera una vista previa grande con un unico Descargar?
- Mejora de formato deberia ser el flujo por defecto y las normas un segundo paso?
- Que diria una pantalla de espera segura de si misma?
