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

const STYLE_LABELS = { apa: "APA", ieee: "IEEE", vancouver: "Vancouver" };

const form = document.getElementById("upload-form");
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

let pendingId = null;

function setStatus(kind, message) {
  statusBox.className = kind || "";
  statusBox.textContent = message || "";
}

function setBusy(busy) {
  submitBtn.disabled = busy;
  submitBtn.textContent = busy ? "Procesando..." : "Procesar documento";
}

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

function handleProcessingResult(result) {
  if (result.pending_id) {
    pendingId = result.pending_id;
    conflictDialog.classList.add("visible");
    setStatus("info", "Esperando tu confirmacion para continuar.");
    return;
  }
  conflictDialog.classList.remove("visible");
  pendingId = null;

  if (result.success) {
    setStatus("success", result.message || "Documento procesado correctamente.");
  } else {
    setStatus("error", result.message || "No se pudo procesar el documento.");
  }
  loadDocuments();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const fileInput = document.getElementById("file-input");
  const styleSelect = document.getElementById("style-select");
  if (!fileInput.files.length) return;

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("style", styleSelect.value);

  setBusy(true);
  setStatus("info", "Subiendo y procesando el documento...");
  conflictDialog.classList.remove("visible");

  try {
    const response = await fetch("/api/upload", { method: "POST", body: formData });
    const result = await parseJsonOrThrow(response);
    handleProcessingResult(result);
    form.reset();
  } catch (err) {
    setStatus("error", err.message);
  } finally {
    setBusy(false);
  }
});

confirmOverwriteBtn.addEventListener("click", async () => {
  if (!pendingId) return;
  setBusy(true);
  setStatus("info", "Sobrescribiendo estilos y continuando...");
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
  conflictDialog.classList.remove("visible");
  try {
    await fetch(`/api/documents/${idToCancel}/cancel-overwrite`, { method: "POST" });
  } catch (err) {
    /* cancelacion best-effort */
  }
  setStatus("info", "Subida cancelada.");
});

async function loadDocuments() {
  let documents = [];
  try {
    const response = await fetch("/api/documents");
    documents = await parseJsonOrThrow(response);
  } catch (err) {
    setStatus("error", `No se pudo cargar el historial: ${err.message}`);
    return;
  }

  docList.innerHTML = "";
  emptyState.style.display = documents.length ? "none" : "block";

  for (const doc of documents) {
    docList.appendChild(renderDocumentItem(doc));
  }
}

function renderDocumentItem(doc) {
  const li = document.createElement("li");
  li.className = "doc-item";

  const info = document.createElement("div");
  info.className = "doc-info";

  const nameEl = document.createElement("div");
  nameEl.className = "name";
  nameEl.textContent = doc.original_filename; // textContent: nunca innerHTML con datos de usuario

  const badge = document.createElement("span");
  badge.className = `badge ${doc.success ? "ok" : "fail"}`;
  badge.textContent = doc.success ? "Listo" : "Error";
  nameEl.appendChild(badge);

  const metaEl = document.createElement("div");
  metaEl.className = "meta";
  const styleLabel = STYLE_LABELS[doc.style] || doc.style;
  const date = new Date(doc.created_at).toLocaleString();
  metaEl.textContent = doc.success
    ? `${styleLabel} · ${date}`
    : `${styleLabel} · ${date} · ${doc.error_message || "fallo el procesamiento"}`;

  info.appendChild(nameEl);
  info.appendChild(metaEl);

  const actions = document.createElement("div");
  actions.className = "doc-actions";

  if (doc.success) {
    const downloadLink = document.createElement("a");
    downloadLink.href = `/api/documents/${doc.processing_id}/download`;
    downloadLink.className = "secondary";
    downloadLink.textContent = "Descargar";
    actions.appendChild(downloadLink);
  }

  if (doc.has_preview) {
    const previewBtn = document.createElement("button");
    previewBtn.className = "secondary";
    previewBtn.textContent = "Vista previa";
    previewBtn.addEventListener("click", () => openPreview(doc.processing_id));
    actions.appendChild(previewBtn);
  }

  actions.appendChild(renderDeleteControl(doc.processing_id));

  li.appendChild(info);
  li.appendChild(actions);
  return li;
}

// Confirmacion inline en la propia fila en vez de window.confirm(): mismo
// patron que el dialogo de conflicto de estilos, y evita depender de
// dialogos nativos del navegador (algunos entornos los bloquean).
function renderDeleteControl(processingId) {
  const container = document.createElement("span");

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "danger";
  deleteBtn.textContent = "Eliminar";

  const confirmBtn = document.createElement("button");
  confirmBtn.className = "danger";
  confirmBtn.textContent = "¿Seguro?";
  confirmBtn.hidden = true;

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "secondary";
  cancelBtn.textContent = "No";
  cancelBtn.hidden = true;

  deleteBtn.addEventListener("click", () => {
    deleteBtn.hidden = true;
    confirmBtn.hidden = false;
    cancelBtn.hidden = false;
  });
  cancelBtn.addEventListener("click", () => {
    deleteBtn.hidden = false;
    confirmBtn.hidden = true;
    cancelBtn.hidden = true;
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
    loadDocuments();
  } catch (err) {
    setStatus("error", `No se pudo eliminar: ${err.message}`);
  }
}

function openPreview(processingId) {
  previewImage.src = `/api/documents/${processingId}/preview`;
  previewModal.classList.add("visible");
}

function closePreview() {
  previewModal.classList.remove("visible");
  previewImage.src = "";
}

closePreviewBtn.addEventListener("click", closePreview);
previewModal.addEventListener("click", (event) => {
  if (event.target === previewModal) closePreview();
});

loadDocuments();
