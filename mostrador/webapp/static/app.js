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

const STYLE_LABELS = { mejora: "Mejora de formato", apa: "APA", ieee: "IEEE", vancouver: "Vancouver" };

const form = document.getElementById("upload-form");
const formFields = document.getElementById("form-fields");
const fileInput = document.getElementById("file-input");
const submitBtn = document.getElementById("submit-btn");
const statusBox = document.getElementById("status-box");
const conflictDialog = document.getElementById("conflict-dialog");
const confirmOverwriteBtn = document.getElementById("confirm-overwrite-btn");
const cancelOverwriteBtn = document.getElementById("cancel-overwrite-btn");
const docList = document.getElementById("doc-list");
const emptyState = document.getElementById("empty-state");
const previewModal = document.getElementById("preview-modal");
const previewImage = document.getElementById("preview-image");
const closePreviewBtn = document.getElementById("close-preview-btn");
const resultSection = document.getElementById("result");
const resultTitle = document.getElementById("result-title");
const resultPreviewBtn = document.getElementById("result-preview-btn");
const resultPreviewImg = document.getElementById("result-preview-img");
const resultName = document.getElementById("result-name");
const resultMeta = document.getElementById("result-meta");
const resultDownload = document.getElementById("result-download");

const BASE_TITLE = document.title;

let pendingId = null;
let busy = false;
let elapsedTimer = null;
let lastSubmission = { name: "", style: "" }; // para rotular el resultado si el historial no lo trae
let resultId = null;

function stopElapsed() {
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
  submitBtn.textContent = busy ? "Procesando..." : "Procesar documento";
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
  resultName.textContent = filename; // textContent: el nombre lo puso el usuario
  resultMeta.textContent = `Formato: ${STYLE_LABELS[styleKey] || styleKey}`;
  resultDownload.href = `/api/documents/${processingId}/download`;

  resultSection.classList.toggle("no-preview", !hasPreview);
  resultPreviewBtn.hidden = !hasPreview;
  if (hasPreview) {
    resultPreviewImg.onerror = () => {
      resultPreviewBtn.hidden = true;
      resultSection.classList.add("no-preview");
    };
    resultPreviewImg.src = `/api/documents/${processingId}/preview`;
  } else {
    resultPreviewImg.removeAttribute("src");
  }

  resultSection.hidden = false;
  resultTitle.focus({ preventScroll: true });
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  resultSection.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
}

resultPreviewBtn.addEventListener("click", () => {
  if (resultId) openPreview(resultId);
});

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
    const response = await fetch("/api/upload", { method: "POST", body: formData });
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
  setBusy(true);
  setWorkingStatus("Sobrescribiendo estilos y procesando...");
  try {
    const response = await fetch(`/api/documents/${pendingId}/confirm-overwrite`, { method: "POST" });
    const result = await parseJsonOrThrow(response);
    handleProcessingResult(result);
  } catch (err) {
    setStatus("error", err.message);
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
    await fetch(`/api/documents/${idToCancel}/cancel-overwrite`, { method: "POST" });
  } catch (err) {
    /* cancelacion best-effort */
  }
  setStatus("info", "Subida cancelada.");
  fileInput.focus();
});

async function loadDocuments() {
  let documents = [];
  try {
    const response = await fetch("/api/documents");
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
    downloadLink.href = `/api/documents/${doc.processing_id}/download`;
    downloadLink.className = "secondary";
    downloadLink.textContent = "Descargar";
    downloadLink.setAttribute("aria-label", `Descargar ${doc.original_filename}`);
    actions.appendChild(downloadLink);
  }

  if (doc.has_preview) {
    const previewBtn = document.createElement("button");
    previewBtn.className = "secondary";
    previewBtn.textContent = "Vista previa";
    previewBtn.setAttribute("aria-label", `Vista previa de ${doc.original_filename}`);
    previewBtn.addEventListener("click", () => openPreview(doc.processing_id));
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
    const response = await fetch(`/api/documents/${processingId}`, { method: "DELETE" });
    await parseJsonOrThrow(response);
    if (processingId === resultId) hideResult();
    await loadDocuments();
    document.getElementById("history-title").focus(); // la fila borrada ya no existe
  } catch (err) {
    setStatus("error", `No se pudo eliminar: ${err.message}`);
  }
}

let previewOpener = null;

function openPreview(processingId) {
  previewOpener = document.activeElement;
  previewImage.src = `/api/documents/${processingId}/preview`;
  previewModal.classList.add("visible");
  closePreviewBtn.focus();
}

function closePreview() {
  previewModal.classList.remove("visible");
  previewImage.src = "";
  if (previewOpener && previewOpener.isConnected) previewOpener.focus();
  previewOpener = null;
}

closePreviewBtn.addEventListener("click", closePreview);
previewModal.addEventListener("click", (event) => {
  if (event.target === previewModal) closePreview();
});

// Visor modal: Escape lo cierra y el foco no escapa a la pagina de fondo
// (su unico control es el boton de cerrar).
document.addEventListener("keydown", (event) => {
  if (!previewModal.classList.contains("visible")) return;
  if (event.key === "Escape") closePreview();
  else if (event.key === "Tab") {
    event.preventDefault();
    closePreviewBtn.focus();
  }
});

loadDocuments();
