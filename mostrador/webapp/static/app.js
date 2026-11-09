// webapp/static/app.js
// ======================
// Logica del panel de Mostrador (seccion 2). Sin build step ni frameworks:
// fetch() contra /api/* (webapp/api/routes.py) y manipulacion directa del DOM.
//
// Nota de seguridad: `original_filename` y los mensajes de error vienen del
// servidor pero en el fondo derivan de datos que el propio usuario (u otro
// usuario del panel) subio — nunca se insertan via innerHTML con
// interpolacion directa; todo texto de datos se asigna con textContent
// para evitar XSS almacenado.

// Sesion efimera: cada carga de la pagina genera su propio id (solo en memoria, asi que recargar
// da uno nuevo) y el servidor solo muestra los documentos de ese id. Al recargar o cerrar se
// avisa al servidor para que borre la sesion; si el aviso no llega, la borra por inactividad.
function newSessionId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16)); // http sin contexto seguro: sin randomUUID
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const SESSION_ID = newSessionId();

function api(path) {
  return `/api${path}${path.includes("?") ? "&" : "?"}sid=${SESSION_ID}`;
}

window.addEventListener("pagehide", () => {
  navigator.sendBeacon(api("/session/end"));
});

// Si el navegador restaura la pagina desde su cache (boton atras) la sesion ya se borro: empieza otra.
window.addEventListener("pageshow", (event) => {
  if (event.persisted) location.reload();
});

const STYLE_LABELS = { mejora: "Mejora de formato", apa: "APA", ieee: "IEEE", vancouver: "Vancouver" };

const form = document.getElementById("upload-form");
const formFields = document.getElementById("form-fields");
const fileInput = document.getElementById("file-input");
const submitBtn = document.getElementById("submit-btn");
const submitLabel = document.getElementById("submit-label");
const usageEl = document.getElementById("usage");
const maxSizeEl = document.getElementById("max-size");
const statusBox = document.getElementById("status-box");
const conflictDialog = document.getElementById("conflict-dialog");
const confirmOverwriteBtn = document.getElementById("confirm-overwrite-btn");
const cancelOverwriteBtn = document.getElementById("cancel-overwrite-btn");
const docList = document.getElementById("doc-list");
const emptyState = document.getElementById("empty-state");
const previewModal = document.getElementById("preview-modal");
const viewerTitle = document.getElementById("viewer-title");
const viewerDownload = document.getElementById("viewer-download");
const viewerNewTab = document.getElementById("viewer-newtab");
const viewerStatus = document.getElementById("viewer-status");
const viewerFrame = document.getElementById("viewer-frame");
const closePreviewBtn = document.getElementById("close-preview-btn");
const resultSection = document.getElementById("result");
const resultTitle = document.getElementById("result-title");
const resultPreviewBtn = document.getElementById("result-preview-btn");
const resultPreviewImg = document.getElementById("result-preview-img");
const resultName = document.getElementById("result-name");
const resultMeta = document.getElementById("result-meta");
const resultDownload = document.getElementById("result-download");
const resultPdfBtn = document.getElementById("result-pdf-btn");

const BASE_TITLE = document.title;

let pendingId = null;
let busy = false;
let elapsedTimer = null;
let lastSubmission = { name: "", style: "" }; // para rotular el resultado si el historial no lo trae
let resultId = null;
let resultStyle = "";
let usageExhausted = false; // el visitante agoto su cupo diario de documentos

function stopElapsed() {
  statusRain.stop();
  if (elapsedTimer !== null) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

// La caja de estado es una region viva: "status" anuncia con calma, "alert" interrumpe en errores.
function setStatus(kind, message) {
  stopElapsed();
  statusBox.className = kind || "";
  statusBox.setAttribute("role", kind === "error" ? "alert" : "status");
  statusBox.textContent = message || "";
}

function formatElapsed(seconds) {
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

// El servidor procesa de forma sincrona y no informa fases, asi que no se
// inventan: se muestra lo cierto (que sigue trabajando y cuanto lleva).
function setWorkingStatus(message) {
  stopElapsed();
  statusBox.className = "info working";
  statusBox.setAttribute("role", "status");

  const line = document.createElement("div");
  line.className = "status-line";
  const text = document.createElement("span");
  text.textContent = message;
  const time = document.createElement("span");
  time.className = "status-time";
  time.setAttribute("aria-hidden", "true"); // el contador no se anuncia cada segundo
  time.textContent = formatElapsed(0);
  line.append(text, time);

  const bar = document.createElement("div");
  bar.className = "status-bar";
  bar.setAttribute("aria-hidden", "true");

  const hint = document.createElement("div");
  hint.className = "status-hint";
  hint.textContent = "Tu contenido no se modifica, solo se reorganiza. No cierres esta página.";

  statusBox.replaceChildren(line, bar, hint);
  statusRain.mount(statusBox); // lluvia de texto arcoiris de fondo
  // Al bloquearse el formulario el foco se pierde: se lleva a la caja de estado,
  // que es lo que el usuario necesita leer, y no a un control deshabilitado.
  if (busy) statusBox.focus();

  const startedAt = Date.now();
  elapsedTimer = setInterval(() => {
    time.textContent = formatElapsed(Math.floor((Date.now() - startedAt) / 1000));
  }, 1000);
}

// Un documento a la vez: mientras se procesa (o espera la confirmacion de
// sobrescritura) se bloquea todo lo que pueda interferir con el sistema.
function refreshLock() {
  formFields.disabled = busy || pendingId !== null;
  form.setAttribute("aria-busy", String(busy));
  submitBtn.classList.toggle("busy", busy);
  submitBtn.disabled = usageExhausted;
  submitLabel.textContent = busy ? "Procesando..." : "Procesar documento";
  // Con un documento adjuntado y el formulario libre, las letras del boton llevan el arcoiris continuo.
  submitBtn.classList.toggle("ready", !busy && pendingId === null && fileInput.files.length > 0);
  if (busy) document.title = `Procesando... · ${BASE_TITLE}`;
  else if (document.title.startsWith("Procesando")) document.title = BASE_TITLE;
  confirmOverwriteBtn.disabled = busy;
  cancelOverwriteBtn.disabled = busy;
  for (const btn of docList.querySelectorAll("button.danger, button.secondary.delete-cancel")) {
    btn.disabled = busy;
  }
}

function setBusy(value) {
  busy = value;
  refreshLock();
}

// Al elegir un formato una linea arcoiris recorre el borde de su tarjeta y deja un rastro y una punta que se difuminan (ver .card-box.flash, 1,2 s).
for (const radio of form.querySelectorAll('input[name="style"]')) {
  radio.addEventListener("change", () => {
    for (const box of form.querySelectorAll(".card-box.flash")) box.classList.remove("flash");
    const box = radio.nextElementSibling;
    void box.offsetWidth; // reinicia la animacion si se vuelve a elegir pronto
    box.classList.add("flash");
    setTimeout(() => box.classList.remove("flash"), 1300);
  });
}

fileInput.addEventListener("change", refreshLock);

window.addEventListener("beforeunload", (event) => {
  if (busy) event.preventDefault();
});

async function parseJsonOrThrow(response) {
  let body = null;
  try {
    body = await response.json();
  } catch (err) {
    /* respuesta sin cuerpo JSON */
  }
  if (!response.ok) {
    const detail = (body && (body.detail || body.message)) || `Error HTTP ${response.status}`;
    throw new Error(detail);
  }
  return body;
}

// Cupo diario y tamano maximo (GET /api/limits): lo decide el servidor, el panel solo lo muestra.
function renderLimits(limits) {
  maxSizeEl.textContent = `${limits.max_file_mb} MB`;
  usageExhausted = limits.remaining === 0;
  usageEl.classList.toggle("exhausted", usageExhausted);
  if (limits.remaining === null) usageEl.textContent = "";
  else if (usageExhausted) usageEl.textContent = `Alcanzaste el límite de ${limits.daily_limit} documentos por día. Vuelve mañana.`;
  else {
    const verb = limits.remaining === 1 ? "queda" : "quedan";
    usageEl.textContent = `Hoy te ${verb} ${limits.remaining} de ${limits.daily_limit} documentos.`;
  }
  refreshLock();
}

async function loadLimits() {
  try {
    const response = await fetch("/api/limits");
    if (response.ok) renderLimits(await response.json());
  } catch (_) {
    // sin red o servidor dormido: el panel funciona igual y el servidor aplica el limite
  }
}

// Servidor dormido (splash.js no recibio respuesta a tiempo): el primer clic avisa de que la primera
// accion puede tardar; el aviso se retira solo cuando el servidor despierta.
const WAKE_MESSAGE = "El servidor estaba dormido y está despertando. La primera acción puede tardar hasta un minuto.";
document.addEventListener(
  "click",
  () => {
    if (window.serverState.awake || busy) return;
    setStatus("info", WAKE_MESSAGE);
    window.serverState.whenAwake(() => {
      if (statusBox.textContent === WAKE_MESSAGE) setStatus("", "");
      loadLimits();
    });
  },
  { capture: true, once: true },
);

function hideResult() {
  resultSection.hidden = true;
  resultId = null;
  resultPreviewImg.removeAttribute("src");
}

// El resultado es lo primero que ve el usuario al terminar: vista previa de la
// primera pagina y la descarga como accion principal. Su titulo recibe el foco
// (y con eso se anuncia), asi que la caja de estado se limpia.
function showResult(processingId, filename, styleKey, hasPreview) {
  resultId = processingId;
  resultStyle = styleKey;
  resultName.textContent = filename; // textContent: el nombre lo puso el usuario
  resultMeta.textContent = `Formato: ${STYLE_LABELS[styleKey] || styleKey}`;
  resultDownload.href = api(`/documents/${processingId}/download`);

  resultSection.classList.toggle("no-preview", !hasPreview);
  resultPreviewBtn.hidden = !hasPreview;
  if (hasPreview) {
    resultPreviewImg.onerror = () => {
      resultPreviewBtn.hidden = true;
      resultSection.classList.add("no-preview");
    };
    resultPreviewImg.src = api(`/documents/${processingId}/preview`);
  } else {
    resultPreviewImg.removeAttribute("src");
  }

  resultSection.hidden = false;
  resultTitle.focus({ preventScroll: true });
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  resultSection.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
}

function openResultPreview() {
  if (resultId) openPreview(resultId, resultName.textContent, resultStyle);
}

resultPreviewBtn.addEventListener("click", openResultPreview);
resultPdfBtn.addEventListener("click", openResultPreview);

function handleProcessingResult(result) {
  if (result.pending_id) {
    pendingId = result.pending_id;
    conflictDialog.classList.add("visible");
    setStatus("", ""); // el aviso lo da el propio dialogo, que recibe el foco
    refreshLock();
    conflictDialog.focus();
    return;
  }
  conflictDialog.classList.remove("visible");
  pendingId = null;
  refreshLock();
  loadLimits();

  if (result.success) {
    setStatus("", "");
    if (document.hidden) document.title = `Listo · ${BASE_TITLE}`; // aviso si la pestana esta en segundo plano
    loadDocuments().then((documents) => {
      const doc = documents.find((d) => d.processing_id === result.processing_id);
      showResult(
        result.processing_id,
        doc ? doc.original_filename : lastSubmission.name,
        doc ? doc.style : lastSubmission.style,
        doc ? doc.has_preview : false,
      );
    });
  } else {
    setStatus("error", result.message || "No se pudo procesar el documento.");
    loadDocuments();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || pendingId !== null || !fileInput.files.length) return;
  const styleInput = form.querySelector('input[name="style"]:checked');

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("style", styleInput.value);
  lastSubmission = { name: fileInput.files[0].name, style: styleInput.value };

  hideResult();
  setBusy(true);
  setWorkingStatus("Procesando tu documento...");
  conflictDialog.classList.remove("visible");

  try {
    const response = await fetch(api("/upload"), { method: "POST", body: formData });
    const result = await parseJsonOrThrow(response);
    handleProcessingResult(result);
    fileInput.value = ""; // el formato elegido se conserva
  } catch (err) {
    setStatus("error", err.message);
  } finally {
    setBusy(false);
  }
});

confirmOverwriteBtn.addEventListener("click", async () => {
  if (!pendingId) return;
  hideResult();
  conflictDialog.classList.remove("visible"); // ya confirmado: el aviso se retira (pendingId mantiene el bloqueo)
  setBusy(true);
  setWorkingStatus("Sobrescribiendo estilos y procesando...");
  try {
    const response = await fetch(api(`/documents/${pendingId}/confirm-overwrite`), { method: "POST" });
    const result = await parseJsonOrThrow(response);
    handleProcessingResult(result);
  } catch (err) {
    setStatus("error", err.message);
    // Si la peticion fallo sin respuesta del motor, la subida sigue pendiente: se vuelve a
    // mostrar el aviso para poder reintentar o cancelar (si no, el formulario quedaria bloqueado).
    if (pendingId !== null) conflictDialog.classList.add("visible");
  } finally {
    setBusy(false);
  }
});

cancelOverwriteBtn.addEventListener("click", async () => {
  if (!pendingId) return;
  const idToCancel = pendingId;
  pendingId = null;
  refreshLock();
  conflictDialog.classList.remove("visible");
  try {
    await fetch(api(`/documents/${idToCancel}/cancel-overwrite`), { method: "POST" });
  } catch (err) {
    /* cancelacion best-effort */
  }
  setStatus("info", "Subida cancelada.");
  fileInput.focus();
});

async function loadDocuments() {
  let documents = [];
  try {
    const response = await fetch(api("/documents"));
    documents = await parseJsonOrThrow(response);
  } catch (err) {
    setStatus("error", `No se pudo cargar el historial: ${err.message}`);
    return [];
  }

  docList.innerHTML = "";
  emptyState.style.display = documents.length ? "none" : "block";

  for (const doc of documents) {
    docList.appendChild(renderDocumentItem(doc));
  }
  refreshLock();
  return documents;
}

function renderDocumentItem(doc) {
  const li = document.createElement("li");
  li.className = "doc-item";

  const info = document.createElement("div");
  info.className = "doc-info";

  const nameEl = document.createElement("div");
  nameEl.className = "name";
  nameEl.textContent = doc.original_filename; // textContent: nunca innerHTML con datos de usuario
  nameEl.title = doc.original_filename; // nombre completo cuando la fila lo recorta

  const badge = document.createElement("span");
  badge.className = `badge ${doc.success ? "ok" : "fail"}`;
  badge.textContent = doc.success ? "Listo" : "Error";
  nameEl.appendChild(badge);

  const metaEl = document.createElement("div");
  metaEl.className = "meta";
  const styleLabel = STYLE_LABELS[doc.style] || doc.style;
  const date = new Date(doc.created_at).toLocaleString("es", { dateStyle: "medium", timeStyle: "short" });
  metaEl.textContent = doc.success
    ? `${styleLabel} · ${date}`
    : `${styleLabel} · ${date} · ${doc.error_message || "falló el procesamiento"}`;

  info.appendChild(nameEl);
  info.appendChild(metaEl);

  const actions = document.createElement("div");
  actions.className = "doc-actions";

  if (doc.success) {
    const downloadLink = document.createElement("a");
    downloadLink.href = api(`/documents/${doc.processing_id}/download`);
    downloadLink.className = "secondary";
    downloadLink.textContent = "Descargar";
    downloadLink.setAttribute("aria-label", `Descargar ${doc.original_filename}`);
    actions.appendChild(downloadLink);
  }

  if (doc.success) {
    const previewBtn = document.createElement("button");
    previewBtn.className = "secondary";
    previewBtn.textContent = "Vista previa";
    previewBtn.setAttribute("aria-label", `Vista previa en PDF de ${doc.original_filename}`);
    previewBtn.addEventListener("click", () => openPreview(doc.processing_id, doc.original_filename, doc.style));
    actions.appendChild(previewBtn);
  }

  actions.appendChild(renderDeleteControl(doc.processing_id, doc.original_filename));

  li.appendChild(info);
  li.appendChild(actions);
  return li;
}

// Confirmacion inline en la propia fila en vez de window.confirm(): mismo
// patron que el dialogo de conflicto de estilos, y evita depender de
// dialogos nativos del navegador (algunos entornos los bloquean).
function renderDeleteControl(processingId, filename) {
  const container = document.createElement("span");

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "danger";
  deleteBtn.textContent = "Eliminar";
  deleteBtn.setAttribute("aria-label", `Eliminar ${filename}`);

  const confirmBtn = document.createElement("button");
  confirmBtn.className = "danger";
  confirmBtn.textContent = "¿Seguro?";
  confirmBtn.setAttribute("aria-label", `Confirmar la eliminación de ${filename}`);
  confirmBtn.hidden = true;

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "secondary delete-cancel";
  cancelBtn.textContent = "No";
  cancelBtn.hidden = true;

  // El boton que tenia el foco se oculta: el foco pasa al siguiente paso para no perderse.
  deleteBtn.addEventListener("click", () => {
    deleteBtn.hidden = true;
    confirmBtn.hidden = false;
    cancelBtn.hidden = false;
    confirmBtn.focus();
  });
  cancelBtn.addEventListener("click", () => {
    deleteBtn.hidden = false;
    confirmBtn.hidden = true;
    cancelBtn.hidden = true;
    deleteBtn.focus();
  });
  confirmBtn.addEventListener("click", () => deleteDocument(processingId));

  container.appendChild(deleteBtn);
  container.appendChild(confirmBtn);
  container.appendChild(cancelBtn);
  return container;
}

async function deleteDocument(processingId) {
  try {
    const response = await fetch(api(`/documents/${processingId}`), { method: "DELETE" });
    await parseJsonOrThrow(response);
    if (processingId === resultId) hideResult();
    await loadDocuments();
    document.getElementById("history-title").focus(); // la fila borrada ya no existe
  } catch (err) {
    setStatus("error", `No se pudo eliminar: ${err.message}`);
  }
}

// Visor de la vista previa: el PDF completo del documento ya formateado, antes de descargarlo.
// El servidor lo convierte con LibreOffice la primera vez (unos segundos) y lo guarda; por eso
// se pide con fetch(): permite mostrar la espera y un mensaje claro si la conversion falla, algo
// que un iframe apuntando directo a la URL no deja ver.
let previewOpener = null;
let previewAbort = null;
let previewBlobUrl = null;

function setViewerStatus(message, isError) {
  viewerStatus.textContent = message;
  viewerStatus.classList.toggle("error", Boolean(isError));
}

function releaseViewerPdf() {
  if (previewAbort) previewAbort.abort();
  previewAbort = null;
  viewerFrame.hidden = true;
  viewerFrame.removeAttribute("src");
  if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
  previewBlobUrl = null;
}

async function openPreview(processingId, filename, styleKey) {
  previewOpener = document.activeElement;
  releaseViewerPdf();

  const pdfUrl = api(`/documents/${processingId}/pdf`);
  viewerTitle.textContent = `${filename} · ${STYLE_LABELS[styleKey] || styleKey}`;
  viewerTitle.title = viewerTitle.textContent; // el titulo se recorta con puntos suspensivos
  viewerDownload.href = api(`/documents/${processingId}/download`);
  viewerNewTab.href = pdfUrl;
  setViewerStatus("Preparando la vista previa… la primera vez puede tardar unos segundos.", false);
  previewModal.classList.add("visible");
  closePreviewBtn.focus();

  // Los moviles (Android) no muestran PDF dentro de la pagina: se ofrece abrirlo aparte.
  if (navigator.pdfViewerEnabled === false) {
    setViewerStatus("Este navegador no muestra PDF dentro de la página. Usa «Abrir el PDF aparte».", false);
    return;
  }

  const controller = new AbortController();
  previewAbort = controller;
  try {
    const response = await fetch(pdfUrl, { signal: controller.signal });
    if (!response.ok) {
      let detail = `Error HTTP ${response.status}`;
      try {
        detail = (await response.json()).detail || detail;
      } catch (_) {
        // el cuerpo no era JSON: se deja el codigo HTTP
      }
      throw new Error(detail);
    }
    const blob = await response.blob();
    if (controller.signal.aborted) return;
    previewBlobUrl = URL.createObjectURL(blob);
    viewerFrame.src = `${previewBlobUrl}#navpanes=0`;
    viewerFrame.hidden = false;
    setViewerStatus("", false);
  } catch (err) {
    if (controller.signal.aborted) return; // el usuario cerro el visor
    setViewerStatus(err.message, true);
  }
}

function closePreview() {
  previewModal.classList.remove("visible");
  releaseViewerPdf();
  setViewerStatus("", false);
  if (previewOpener && previewOpener.isConnected) previewOpener.focus();
  previewOpener = null;
}

closePreviewBtn.addEventListener("click", closePreview);
previewModal.addEventListener("click", (event) => {
  if (event.target === previewModal) closePreview();
});

// Visor modal: Escape lo cierra y el foco no escapa a la pagina de fondo.
document.addEventListener("keydown", (event) => {
  if (previewModal.classList.contains("visible") && event.key === "Escape") closePreview();
});
document.addEventListener("focusin", (event) => {
  if (previewModal.classList.contains("visible") && !previewModal.contains(event.target)) {
    closePreviewBtn.focus();
  }
});

loadLimits();
loadDocuments();
