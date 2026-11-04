---
name: Mostrador
description: Panel sobrio de una sola pantalla donde un estudiante deja su borrador y recibe el documento pulido.
colors:
  ink-navy: "#2e4057"
  navy-wash: "#eef1f5"
  hairline: "#d8dee6"
  press-black: "#1c1f24"
  graphite: "#5b6472"
  paper-gray: "#f7f8fa"
  white-sheet: "#ffffff"
  proof-red: "#b3261e"
  proof-red-wash: "#fbe9e7"
  approved-green: "#1e6b3c"
  approved-green-wash: "#e6f4ea"
  caution-amber: "#f0c36d"
  caution-amber-wash: "#fff8e6"
  focus-amber: "#f0a500"
typography:
  title:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "1.4rem"
    fontWeight: 600
    lineHeight: 1.2
  headline:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "0.85rem"
    fontWeight: 400
    lineHeight: 1.4
  button:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 600
    lineHeight: 1.2
  card-name:
    fontFamily: "Segoe UI, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0.03em"
rounded:
  sm: "6px"
  md: "8px"
  card: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  xxl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.ink-navy}"
    textColor: "{colors.white-sheet}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "9px 16px"
  button-secondary:
    backgroundColor: "{colors.navy-wash}"
    textColor: "{colors.ink-navy}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "9px 16px"
  button-danger:
    backgroundColor: "{colors.proof-red-wash}"
    textColor: "{colors.proof-red}"
    typography: "{typography.button}"
    rounded: "{rounded.sm}"
    padding: "9px 16px"
  format-card:
    backgroundColor: "{colors.white-sheet}"
    textColor: "{colors.press-black}"
    typography: "{typography.card-name}"
    rounded: "{rounded.card}"
    padding: "14px 8px 12px"
  format-card-selected:
    backgroundColor: "{colors.navy-wash}"
    textColor: "{colors.press-black}"
  section-panel:
    backgroundColor: "{colors.white-sheet}"
    rounded: "{rounded.md}"
    padding: "20px"
  field-input:
    backgroundColor: "{colors.white-sheet}"
    textColor: "{colors.press-black}"
    rounded: "{rounded.sm}"
    padding: "8px"
  status-box-info:
    backgroundColor: "{colors.navy-wash}"
    textColor: "{colors.ink-navy}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  status-box-success:
    backgroundColor: "{colors.approved-green-wash}"
    textColor: "{colors.approved-green}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  status-box-error:
    backgroundColor: "{colors.proof-red-wash}"
    textColor: "{colors.proof-red}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  conflict-dialog:
    backgroundColor: "{colors.caution-amber-wash}"
    textColor: "{colors.press-black}"
    rounded: "{rounded.sm}"
    padding: "12px"
---

# Design System: Mostrador

## Overview

**Creative North Star: "El mostrador de la imprenta"**

Llegas con el borrador bajo el brazo, lo dejas en el mostrador y te lo devuelven pulido. Esa escena manda sobre todo lo visual: papel blanco sobre un fondo gris casi neutro, tinta azul marino para lo que importa, y ningún adorno que no sirva para entregar el trabajo. El panel es una herramienta de una sola pantalla para estudiantes con prisa; su serenidad es parte de la confianza que transmite.

El carácter es sobrio y de confianza, de tono académico y sin aire de startup. La interfaz no busca llamar la atención: pone al frente tres cosas (el archivo, el formato, el botón) y deja que el resultado hable. La profundidad no se construye con sombras sino con contraste de borde y de relleno; solo aparece un relieve como respuesta a un estado, nunca en reposo.

Se rechaza lo que sea decorativo o llamativo: gradientes, sombras difusas, adornos y el tono de startup.

**Key Characteristics:**
- Plano y firme: bordes definidos y relleno liso, sin sombras en reposo.
- Un solo acento (azul marino tinta) sobre una base de grises fríos.
- Los colores de estado (verde, rojo, ámbar) aparecen solo para comunicar resultado.
- Una columna centrada de 780 px; todo cabe en una pantalla.
- Tipografía del sistema (Segoe UI), sin fuentes externas.

## Colors

Paleta de tinta y papel: un azul marino profundo como único acento, grises fríos para la base y tres colores de estado.

### Primary
- **Azul Marino Tinta** (`#2e4057`): cabecera, botón principal, texto de los botones secundarios, borde y anillo de la tarjeta de formato elegida. Es el único acento del sistema.

### Neutral
- **Gris Papel** (`#f7f8fa`): fondo de la página.
- **Hoja Blanca** (`#ffffff`): superficie de cada sección y de las tarjetas.
- **Lavado Marino** (`#eef1f5`): relleno de botones secundarios, de la tarjeta elegida, de los mensajes informativos y del hover de las tarjetas.
- **Filo Gris** (`#d8dee6`): bordes de secciones, campos y separadores de la lista.
- **Negro de Prensa** (`#1c1f24`): texto principal y trazo de las tarjetas de formato en reposo.
- **Grafito** (`#5b6472`): etiquetas, metadatos y texto secundario.

### Estado
- **Rojo de Prueba** (`#b3261e`) sobre su lavado (`#fbe9e7`): errores y acciones destructivas.
- **Verde Aprobado** (`#1e6b3c`) sobre su lavado (`#e6f4ea`): documento procesado.
- **Ámbar de Aviso** (`#f0c36d`) sobre su lavado (`#fff8e6`): diálogo de conflicto de estilos.
- **Ámbar de Foco** (`#f0a500`): contorno de foco con teclado en las tarjetas.

### Named Rules
**The One Ink Rule.** El azul marino es el único acento. Verde, rojo y ámbar no decoran: solo informan de un resultado o de un riesgo.

**The Quiet Gray Rule.** Toda superficie es blanca o gris frío. No se introducen tintes cálidos ni degradados en el fondo.

## Typography

**Display Font:** Segoe UI (con system-ui, sans-serif)
**Body Font:** Segoe UI (con system-ui, sans-serif)

**Character:** una sola familia del sistema, sin fuentes externas: neutra, legible y propia de una herramienta. La jerarquía sale del peso y del tamaño, no de combinar familias.

### Hierarchy
- **Title** (600, 1.4rem, 1.2): nombre «Mostrador» en la cabecera.
- **Headline** (600, 1.05rem, 1.3): título de cada sección («Subir documento», «Documentos procesados»).
- **Body** (400, 0.95rem, 1.5): campos, mensajes y texto corriente.
- **Label** (400, 0.85rem, 1.4): etiquetas de campo y metadatos, en Grafito.
- **Button** (600, 0.9rem): texto de todos los botones.
- **Card name** (700, 0.8rem, 0.03em, mayúsculas): nombre del formato bajo su icono.

### Named Rules
**The Plain Sans Rule.** Una sola familia. El énfasis se logra con peso y mayúsculas contenidas, nunca con una segunda fuente.

## Layout

Una sola columna centrada de 780 px como máximo, con 16 px de margen lateral y 24 px arriba. Las secciones (subir, historial) se apilan con 24 px entre sí y 20 px de relleno interno. El ritmo de espaciado es de 4, 8, 12, 16, 20 y 24 px.

Las cuatro tarjetas de formato se reparten la fila con 12 px de hueco; «Mejora de formato» es 1,35 veces más ancha por ser la opción principal. Por debajo de 560 px las tarjetas pasan a dos filas. La lista de documentos usa filas con separador de un píxel y las acciones a la derecha.

## Elevation & Depth

El sistema es plano. En reposo ninguna superficie lleva sombra: la separación sale de bordes de un píxel en Filo Gris y del contraste entre Hoja Blanca y Gris Papel. La profundidad aparece solo como respuesta a un estado.

### Shadow Vocabulary
- **Anillo de selección** (`box-shadow: 0 0 0 3px #2e4057`): rodea la tarjeta de formato elegida, sumado a su borde azul marino.
- **Velo del modal** (`background: rgba(0, 0, 0, 0.6)`): oscurece la página bajo la vista previa.

### Named Rules
**The Flat-By-Default Rule.** Las superficies son planas en reposo. Un anillo o un velo solo se muestran como respuesta a selección, foco o un modal abierto.

## Shapes

Esquinas suaves pero contenidas, con un radio por tipo de objeto: 6 px en botones, campos y mensajes; 8 px en las secciones; 16 px en las tarjetas de formato, que son el único elemento con carácter propio; píxeles completos (999 px) en las insignias de estado. Los iconos de las tarjetas usan trazo de 3 unidades con terminales redondeados, sin relleno, salvo la estrella de «Mejora de formato», que se rellena con el azul marino.

## Components

### Buttons
- **Shape:** esquinas suaves (6 px).
- **Primary:** fondo Azul Marino Tinta, texto blanco, relleno 9 px × 16 px, peso 600. Deshabilitado baja la opacidad al 50 % y muestra cursor de no permitido.
- **Secondary:** fondo Lavado Marino con texto azul marino; para descargar y ver la vista previa.
- **Danger:** fondo Lavado Rojo con texto Rojo de Prueba; para eliminar, con confirmación en la propia fila («¿Seguro?» / «No»).

### Cards / Containers
- **Section panel:** fondo Hoja Blanca, borde de 1 px en Filo Gris, radio 8 px, relleno 20 px, sin sombra.
- **Format card:** caja de 2 px en Negro de Prensa, radio 16 px, icono de documento de 56 px arriba y nombre en mayúsculas abajo. En hover rellena con Lavado Marino. Elegida: borde y anillo en azul marino más el mismo relleno. Foco con teclado: contorno de 3 px en Ámbar de Foco con 3 px de separación. Bloqueada (mientras se procesa): la elegida conserva todo su contraste y las demás bajan al 50 % de opacidad, con cursor de no permitido y sin cambio de hover.

### Inputs / Fields
- **Style:** borde de 1 px en Filo Gris, fondo blanco, radio 6 px, relleno 8 px, ancho completo.
- **Etiqueta:** encima del campo, en Grafito a 0.85 rem.
- **Disabled:** el bloqueo se aplica al conjunto de campos con cursor de no permitido; etiquetas y archivo siguen legibles, solo se atenúan las opciones no elegidas.

### Status
- **Mensaje de estado:** caja de 6 px de radio con relleno 10 px × 12 px; información en Lavado Marino, éxito en Verde Aprobado, error en Rojo de Prueba, cada uno con su lavado de fondo.
- **Diálogo de conflicto:** caja de Ámbar de Aviso con borde de 1 px, aparece bajo el formulario con dos acciones.
- **Procesando:** la caja informativa muestra el mensaje en peso 600, el tiempo transcurrido a la derecha (cifras tabulares) y una barra indeterminada de 3 px en Azul Marino Tinta sobre Filo Gris, con la frase «Tu contenido no se modifica, solo se reorganiza». El movimiento es solo de la barra (1,4 s); con `prefers-reduced-motion` pasa a una barra fija y el contador sigue avanzando. Es la región viva de la página: `role="status"` (o `alert` en errores) y recibe el foco al empezar. El botón de enviar conserva su contraste y muestra «Procesando...».
- **Insignia:** píxeles completos, 0.72 rem, 700 y mayúsculas; «Listo» en verde, «Error» en rojo.

### Result
Lo primero que se ve al terminar. Es una sección con borde de 1 px en Azul Marino Tinta (la única con acento), título «Tu documento está listo» (1.25 rem) y dos columnas: a la izquierda la primera página del documento como una hoja blanca con borde fino sobre un fondo Lavado Marino (280 px); a la derecha el nombre del archivo, el formato y «Descargar .docx» como botón principal grande (12 px × 22 px, 1 rem). En pantallas estrechas se apila. Entra con un desvanecimiento y un desplazamiento de 8 px en 0,3 s (sin movimiento con `prefers-reduced-motion`), y su título recibe el foco, que es lo que anuncia el resultado a un lector de pantalla. Pulsar la hoja abre la vista previa ampliada.

### Document list
Los enlaces de acción (descargar) se ven y se comportan como botones. Filas con separador de 1 px; nombre en peso 600 con elipsis, metadatos en Grafito a 0.8 rem y acciones de 0.8 rem alineadas a la derecha. En pantallas de 560 px o menos, o con puntero táctil, la fila se apila: nombre completo (con ajuste de línea) y metadatos arriba, y las acciones debajo repartiéndose el ancho en botones de al menos 44 px de alto (0.875 rem); el paso de confirmar el borrado puede pasar a una segunda línea.

### Preview modal
Velo oscuro a pantalla completa, imagen centrada sobre fondo blanco con radio 6 px y botón de cerrar arriba a la derecha.

## Do's and Don'ts

### Do:
- **Do** usar Azul Marino Tinta (`#2e4057`) como único acento y reservar verde, rojo y ámbar para resultados y avisos.
- **Do** mantener las superficies planas en reposo; el relieve (anillo de 3 px, velo del modal) solo como respuesta a un estado.
- **Do** bloquear con cursor de no permitido todo control que no deba tocarse mientras se procesa, sin apagar el formulario entero: lo elegido y las etiquetas siguen legibles.
- **Do** usar Segoe UI (system-ui como respaldo) para todo el texto, con peso y tamaño para la jerarquía.
- **Do** escribir toda la interfaz en español claro, sin jerga de Word ni de la norma.
- **Do** dar a cada control un contorno de foco visible (3 px, `#f0a500`) para uso con teclado.

### Don't:
- **Don't** usar gradientes, sombras difusas ni adornos decorativos.
- **Don't** darle a la interfaz un tono de startup: ni lenguaje promocional ni efectos llamativos.
- **Don't** añadir un segundo color de acento ni usar los colores de estado como decoración.
- **Don't** introducir una segunda familia tipográfica ni fuentes externas.
- **Don't** mostrar sombras en reposo ni elevar tarjetas o botones sin que haya un estado que lo justifique.
