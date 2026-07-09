import type { ApiError, AppState } from "./types/index.ts";
import type { ChatMessage, DiagramResult, FileMeta, SourceType } from "../../shared/types/index.ts";
import { generateDiagram, getConfig, sendChatMessage } from "./api/client.ts";
import { inlineIcons } from "./generated/inline-icons.ts";
import { clearState, defaultState, loadState, saveState } from "./state/session.ts";
import { diagramSize, downloadPdf, downloadPng, downloadSvg, getCachedSvg, renderMermaid } from "./utils/export.ts";

const app = document.querySelector<HTMLDivElement>("#app");
const iconUrl = (name: string): string => `assets/icons/${encodeURIComponent(name)}`;
type AttachmentStatus = "loading" | "error" | "success" | "static";
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.25;
const RESULT_CHAT_WIDTH = 440;
const RESULT_TOOLBAR_HEIGHT = 72;
const CHAT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024;
const CHAT_ATTACHMENT_FORMATS = ["txt", "docx", "pdf", "xls", "xlsx", "csv"] as const;
const CHAT_ATTACHMENT_MIME_TYPES = new Set([
  "text/plain",
  "text/csv",
  "application/csv",
  "application/pdf",
  "application/msword",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
]);
const CHAT_ATTACHMENT_ACCEPT = CHAT_ATTACHMENT_FORMATS.map((format) => `.${format}`).join(",");
let state: AppState = loadState();
let selectedFile: File | undefined;
let sourceFile: File | undefined;
let chatFiles: File[] = [];
let isLoading = false;
let isChatLoading = false;
let isChatComposing = false;
let isFileChecking = false;
let fileCheckToken = 0;
let isDragging = false;
let dragStart = { x: 0, y: 0 };
let dragOrigin = { x: 0, y: 0 };
let downloadOpen = false;
let activeModal: "new" | "home" | null = null;
let exportState: "idle" | "exporting" | "error" = "idle";
let sourceDetailsOpen = false;
let pendingChatScroll = false;
let chatInputError = "";
let pendingActionType: "FREEFORM" | "GROUP_SEMANTIC_BLOCKS" | "SIMPLIFY" | "HIGHLIGHT_MAIN_PATH" | "RESTORE_PREVIOUS" = "FREEFORM";
const expandedUserMessages = new Set<string>();

void getConfig().then((config) => {
  state.config = config;
  persist();
  render();
});

function persist(): void {
  saveState(state);
}

function render(): void {
  if (!app) return;
  app.innerHTML = state.page === "result" && state.result ? resultPage() : startPage();
  bindEvents();
  updateSourceDetailsOverflow();
  updateUserMessagesOverflow();
  resizeChatTextarea();
  if (pendingChatScroll) {
    pendingChatScroll = false;
    window.requestAnimationFrame(() => scrollMessagesToEnd());
  }
}

function startPage(): string {
  const start = state.start;
  const isText = start.sourceType === "text-file";
  const isRecording = start.sourceType === "recording";
  const isLink = start.sourceType === "link";
  return `
    <main class="app-canvas">
      ${productNav()}
      ${start.error && !start.error.field ? generationToast() : ""}
      <section class="start-page">
        <div class="breadcrumbs"><span class="breadcrumb-link">Главная</span><span class="breadcrumb-separator" aria-hidden="true"></span><b class="breadcrumb-current">UX-архитектура</b></div>
        <h1>Превратите ТЗ в UX-архитектуру</h1>
        <p class="lead">Сервис соберет требования в понятную карту экранов и действий пользователя</p>

        <div class="start-layout">
          <section class="start-card source-${start.sourceType} ${isLoading ? "is-loading" : ""}">
            <div class="section-title">
              ${icon("Illustration 1.svg", "title-illustration")}
              <h2>Выберите источник</h2>
            </div>
            <div class="source-stack" role="radiogroup" aria-label="Источник технического задания">
              ${sourceOption("text-file", "Текстовый файл", isText, uploadSource(start.file))}
              ${sourceOption("recording", "Запись встречи", isRecording, uploadSource(start.recording))}
              ${sourceOption("link", "Ссылка на Jira/Confluence", isLink, linkSource())}
            </div>
            <div class="details-field">
              <span class="details-title">
                <span class="section-title">
                  ${icon("Illustration 2.svg", "title-illustration")}
                  <span>Детали задачи</span>
                </span>
                ${serviceButton()}
              </span>
              <textarea id="details" rows="4" aria-label="Детали задачи" placeholder="Введите описание или дополнительный контекст">${escapeHtml(start.details)}</textarea>
            </div>
          </section>

          <aside class="requirements-card">
            <h2>Что должно быть в ТЗ?</h2>
            <ul>
              <li>${icon("check-1.svg", "check-icon")}<span><b>Описание задачи</b><small>Какую проблему необходимо решить</small></span></li>
              <li>${icon("check-1.svg", "check-icon")}<span><b>Участники процесса</b><small>Кто взаимодействует с продуктом</small></span></li>
              <li>${icon("check-1.svg", "check-icon")}<span><b>Основные требования</b><small>Какие правила и ограничения важно учесть</small></span></li>
            </ul>
            <button class="sample-link" type="button">Скачать пример ТЗ</button>
            <button id="build" class="primary-action build-action ${isLoading ? "is-loading" : ""}" ${isLoading ? "disabled" : ""}>
              ${isLoading ? svgIcon("Content layer.svg", "spinner-icon") : svgIcon("sparkles.svg", "button-icon")}
              ${isLoading ? "" : "<span>Построить схему</span>"}
            </button>
          </aside>
        </div>
      </section>
    </main>
  `;
}

function productNav(): string {
  return `
    <nav class="product-nav" aria-label="Сервисы">
      <a>UMUX-Оценка</a>
      <a>UX Debt</a>
      <a>Тепловая карта</a>
      <a>CJM</a>
      <a class="active">UX-архитектура</a>
      <button class="gear-button" type="button" aria-label="Настройки">${svgIcon("sun.svg", "nav-icon")}</button>
    </nav>
  `;
}

function serviceButton(): string {
  return `
    <button class="service-button" type="button" aria-label="Подсказка по деталям задачи" aria-describedby="details-service-tooltip">
      ${svgIcon("Service.svg", "help-icon")}
      <span id="details-service-tooltip" class="service-tooltip" role="tooltip">Например, укажите, для кого строить схему, какие этапы добавить или исключить и какой дополнительный сценарий учесть</span>
    </button>
  `;
}

function sourceOption(type: SourceType, title: string, selected: boolean, body: string): string {
  return `
    <div class="source-option ${selected ? "selected" : ""}" data-state="${selected ? "selected" : "default"}">
      <button class="source-head" data-source="${type}" role="radio" aria-checked="${selected}" type="button">
        <span class="source-dot"></span>
        <span>${title}</span>
      </button>
      ${selected ? `<div class="source-body">${body}</div>` : ""}
    </div>
  `;
}

function uploadSource(file?: FileMeta): string {
  const isRecording = state.start.sourceType === "recording";
  const accept = isRecording ? ".mp3,.m4a,.mp4,.webm" : ".txt,.docx,.pdf";
  const error = state.start.error?.field === "attachment" ? state.start.error.message : "";
  const attachmentState = file ? attachmentStatus(error) : "static";
  const uploadState = isFileChecking ? "checking" : error ? "error" : file ? "uploaded" : "default";
  const uploadCopy = isFileChecking
    ? `
      ${icon("Content layer.svg", "dropzone-spinner")}
      <span class="upload-copy">
        <b>Проверка файла...</b>
        <small>Дождитесь окончания проверки</small>
      </span>
    `
    : `
      ${icon("cloud-upload.svg", "upload-icon")}
      <span class="upload-copy">
        <b>Перетащите файл сюда</b>
        <small>${isRecording ? "MP3, M4A, MP4, WebM, файл не должен превышать 100MB" : "PDF, DOCX, TXT, файл не должен превышать 10MB"}</small>
      </span>
      <span class="upload-button">Загрузить файл</span>
    `;
  return `
    <label class="upload-inline ${error ? "has-error" : ""}" data-upload-dropzone="true" data-state="${uploadState}">
      <input id="source-file" type="file" accept="${accept}" ${isLoading ? "disabled" : ""} />
      ${uploadCopy}
    </label>
    ${file ? attachmentRow(file, attachmentState) : ""}
    ${error ? `<em class="inline-error">${escapeHtml(error)}</em>` : ""}
  `;
}

function linkSource(): string {
  const error = state.start.error?.field === "link" ? state.start.error.message : "";
  return `
    <label class="link-field ${error ? "has-error" : ""}">
      <span class="input-shell">
        <span class="input-label">Ссылка на задачу <i>*</i></span>
        <input id="link" value="${escapeHtml(state.start.link)}" placeholder="https://jira.company.ru" ${isLoading ? "disabled" : ""} />
      </span>
      ${error ? `<em class="inline-error">${escapeHtml(error)}</em>` : ""}
    </label>
  `;
}

function attachmentStatus(error: string): AttachmentStatus {
  if (isFileChecking) return "loading";
  if (error) return "error";
  return selectedFile ? "success" : "static";
}

function attachmentRow(file: FileMeta, status: AttachmentStatus): string {
  const isLoadingStatus = status === "loading";
  const isError = status === "error";
  const isSuccess = status === "success";
  const canDownload = Boolean(selectedFile) && !isLoadingStatus;
  const detail = isLoadingStatus
    ? "Проверка файла..."
    : isError
      ? "Не удалось загрузить файл"
      : `${file.format} · ${formatBytes(file.size)}`;
  return `
    <div class="attachment-row" data-state="${status}">
      ${icon("File badge.svg", "attachment-icon")}
      <span class="attachment-meta">
        ${canDownload
          ? `<button class="attachment-download text-link" type="button">${escapeHtml(file.name)}</button>`
          : `<b>${escapeHtml(file.name)}</b>`}
        <small>${escapeHtml(detail)}</small>
        ${isLoadingStatus ? `<span class="attachment-progress" aria-hidden="true"><span></span></span>` : ""}
      </span>
      <span class="attachment-actions">
        ${isLoadingStatus ? `<button type="button" class="attachment-remove icon-action" aria-label="Отменить загрузку">${svgIcon("trash.svg", "button-icon")}</button>` : ""}
        ${isError ? `<button type="button" class="attachment-retry icon-action" aria-label="Повторить загрузку">${svgIcon("reload.svg", "button-icon")}</button><button type="button" class="attachment-remove icon-action" aria-label="Удалить файл">${svgIcon("trash.svg", "button-icon")}</button>` : ""}
        ${isSuccess ? `${icon("check.svg", "attachment-ok")}<button type="button" class="attachment-remove icon-action" aria-label="Удалить файл">${svgIcon("trash.svg", "button-icon")}</button>` : ""}
      </span>
    </div>
  `;
}

function resultPage(): string {
  const result = state.result as DiagramResult;
  state.view.scale = clampZoom(state.view.scale);
  const isMinZoom = state.view.scale <= MIN_ZOOM + 0.001;
  const isMaxZoom = state.view.scale >= MAX_ZOOM - 0.001;
  return `
    <main class="result-canvas">
      <header class="result-toolbar">
        <button id="go-home" class="secondary-action back-action">${svgIcon("arrow-left.svg", "button-icon")}<span>На главную</span></button>
        <div class="toolbar-actions">
          <button id="new-diagram" class="secondary-action">${svgIcon("plus.svg", "button-icon")}<span>Новая схема</span></button>
          <div class="download-wrap">
            <button id="download-button" class="primary-action" aria-expanded="${downloadOpen}" aria-controls="download-menu">${svgIcon("download.svg", "button-icon")}<span>Скачать схему</span></button>
            ${downloadOpen ? downloadMenu() : ""}
          </div>
        </div>
      </header>

      <section class="workspace">
        <aside class="chat-panel">
          ${chatBlock(result)}
        </aside>
        <section class="diagram-panel">
          <div id="diagram-viewport" class="diagram-viewport">
            <div id="diagram-content" class="diagram-content">${getCachedSvg()}</div>
          </div>
          <div class="diagram-controls">
            <button id="zoom-out" title="Уменьшить" ${isMinZoom ? "disabled" : ""}>${svgIcon("minus.svg", "control-icon")}</button>
            <strong>${Math.round(state.view.scale * 100)}%</strong>
            <button id="zoom-in" title="Увеличить" ${isMaxZoom ? "disabled" : ""}>${svgIcon("plus.svg", "control-icon")}</button>
          </div>
        </section>
      </section>
      ${activeModal ? modal(activeModal) : ""}
    </main>
  `;
}

function downloadMenu(): string {
  const content = exportState === "exporting"
    ? `<button disabled>Подготовка файла</button>`
    : exportState === "error"
      ? `<button disabled>Не удалось скачать</button>`
      : `
        <button data-download="pdf" role="menuitem">${svgIcon("file.svg", "menu-icon")}<span>PDF</span></button>
        <button data-download="png" role="menuitem">${svgIcon("photo.svg", "menu-icon")}<span>PNG</span></button>
        <button data-download="svg" role="menuitem">${svgIcon("vector.svg", "menu-icon")}<span>SVG</span></button>
      `;
  return `<div id="download-menu" class="download-menu" role="menu">${content}</div>`;
}

function contextBlock(result: DiagramResult): string {
  const source = result.sourceContext;
  const details = result.details ? `<div class="context-item"><b>Детали</b><span>${escapeHtml(result.details)}</span></div>` : "";
  return `
    <section class="context-card">
      <div class="context-attachment">
        ${icon("File badge.svg", "attachment-icon")}
        <span>
          <b>${escapeHtml(source.title)}</b>
          <small>${escapeHtml(source.description)}</small>
        </span>
      </div>
      <button class="context-select" type="button"><span>В архитектуре обязательно присутствуют уровни вложенности: Главная - Категори...</span>${svgIcon("chevron-down.svg", "context-chevron")}</button>
      ${details}
    </section>
  `;
}

function chatBlock(result: DiagramResult): string {
  const attachments = getChatAttachments();
  const hasText = Boolean(state.chatDraft.trim());
  const hasFiles = attachments.length > 0;
  const canSend = (hasText || hasFiles) && !isChatLoading;
  const messages = [
    sourceMessage(result),
    assistantIntro(),
    ...result.chat.map(chatMessage),
    isChatLoading ? generatingMessage() : "",
    result.chat.length || isChatLoading ? "" : quickActions()
  ].filter(Boolean).join("");
  const attachmentList = hasFiles ? `
    <div class="chat-file-strip" aria-label="Прикреплённые файлы">
      ${attachments.map(chatAttachmentCard).join("")}
    </div>` : "";
  const error = chatInputError ? `<em class="chat-input-error">${escapeHtml(chatInputError)}</em>` : "";
  return `
    <section class="chat-card">
      <div class="messages" data-chat-scroll="true">${messages}</div>
      <div class="chat-input ${hasText || hasFiles ? "has-content" : ""} ${hasFiles ? "has-files" : ""} ${chatInputError ? "has-error" : ""} ${isChatLoading ? "is-loading" : ""}">
        ${attachmentList}
        <div class="chat-compose-row">
          <textarea id="chat-message" rows="1" placeholder="Чем тебе помочь?" ${isChatLoading ? "disabled" : ""}>${escapeHtml(state.chatDraft)}</textarea>
          <div class="chat-input-actions">
            <label class="attach-button ${isChatLoading ? "is-disabled" : ""}" aria-label="Прикрепить файл">
              ${svgIcon("paperclip.svg", "chat-attach-icon")}
              <input id="chat-file" type="file" accept="${CHAT_ATTACHMENT_ACCEPT}" multiple ${isChatLoading ? "disabled" : ""} />
            </label>
            <button id="send-chat" class="send-button" ${canSend ? "" : "disabled"}><span>Отправить</span></button>
          </div>
        </div>
        ${error}
      </div>
    </section>
  `;
}

function chatAttachmentCard(file: FileMeta, index: number): string {
  return `
    <div class="chat-file-card">
      ${icon("File badge.svg", "chat-file-icon")}
      <span class="chat-file-info">
        <span class="chat-file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
        <small>${escapeHtml(file.format)} · ${formatBytes(file.size)}</small>
      </span>
      <button type="button" class="chat-file-remove" data-remove-chat-file="${index}" aria-label="Удалить файл" ${isChatLoading ? "disabled" : ""}>${svgIcon("trash.svg", "chat-file-remove-icon")}</button>
    </div>
  `;
}

function sourceMessage(result: DiagramResult): string {
  const source = result.sourceContext;
  const file = source.file;
  const title = file?.name || source.title;
  const meta = file ? `${file.format} · ${formatBytes(file.size)}` : source.description;
  const details = (result.details || "").trim();
  return `
    <article class="source-message">
      <div class="source-file-card">
        <span class="source-file-badge">${icon("File badge.svg", "source-file-icon")}</span>
        <span class="source-file-meta">
          <button class="source-file-link" type="button" data-source-download="true" ${sourceFile ? "" : "disabled"}>${escapeHtml(title)}</button>
          <small>${escapeHtml(meta)}</small>
        </span>
      </div>
      ${details ? `
        <button class="source-details ${sourceDetailsOpen ? "is-open" : ""}" type="button" data-source-details-toggle="true" aria-expanded="${sourceDetailsOpen}">
          <span class="source-details-text">${escapeHtml(details)}</span>
          <span class="source-details-toggle" aria-hidden="true">${svgIcon("chevron-down.svg", "source-details-icon")}</span>
        </button>
      ` : ""}
    </article>
  `;
}

function assistantIntro(): string {
  return `
    <div class="assistant-intro">
      <p>Готово. Я построил UX-архитектуру по вашему ТЗ.</p>
      <p>Если что-то нужно подправить, просто напишите мне или выберите действие ниже:</p>
    </div>
  `;
}

function quickActions(): string {
  return `
    <div class="quick-actions">
      <button data-quick="Разбить схему на смысловые блоки">${svgIcon("layout-grid.svg", "quick-icon")}<span>Разбить схему на смысловые блоки</span></button>
      <button data-quick="Упростить схему">${svgIcon("schema.svg", "quick-icon")}<span>Упростить схему</span></button>
      <button data-quick="Выделить основной путь">${svgIcon("line.svg", "quick-icon")}<span>Выделить основной путь</span></button>
    </div>
  `;
}

function quickActionType(label: string): "GROUP_SEMANTIC_BLOCKS" | "SIMPLIFY" | "HIGHLIGHT_MAIN_PATH" | "FREEFORM" {
  if (label === "Разбить схему на смысловые блоки") return "GROUP_SEMANTIC_BLOCKS";
  if (label === "Упростить схему") return "SIMPLIFY";
  if (label === "Выделить основной путь") return "HIGHLIGHT_MAIN_PATH";
  return "FREEFORM";
}

function generatingMessage(): string {
  return `<div class="message-generating"><span>Анализирую</span>${svgIcon("chevron-down.svg", "generating-icon")}</div>`;
}

function chatMessage(message: ChatMessage): string {
  const attachments = message.attachments?.length ? message.attachments : message.attachment ? [message.attachment] : [];
  const attachmentCards = attachments.length ? `<div class="message-attachments">${attachments.map(messageAttachmentCard).join("")}</div>` : "";
  const actions = message.role === "assistant" && !message.temporary ? aiMessageActions(message) : "";
  if (message.role !== "user") {
    return `<div class="message ${message.role}" data-message-id="${escapeHtml(message.id)}"><p>${escapeHtml(message.text)}</p>${attachmentCards}${actions}</div>`;
  }

  const hasText = Boolean(message.text.trim());
  const hasAttachments = attachments.length > 0;
  const isOpen = expandedUserMessages.has(message.id);
  const textBlock = hasText ? `
    <div class="user-message-content">
      <p class="user-message-text ${isOpen ? "is-open" : "is-collapsed"}">${escapeHtml(message.text)}</p>
      <button class="user-message-toggle" type="button" data-user-message-toggle="${escapeHtml(message.id)}" aria-expanded="${isOpen}" aria-label="${isOpen ? "Свернуть сообщение" : "Развернуть сообщение"}">${svgIcon("chevron-down.svg", "user-message-toggle-icon")}</button>
    </div>` : "";
  return `<div class="message user ${isOpen ? "is-open" : ""} ${hasAttachments ? "has-attachments" : ""}" data-message-id="${escapeHtml(message.id)}">${attachmentCards}${textBlock}</div>`;
}

function messageAttachmentCard(file: FileMeta): string {
  return `
    <div class="message-file-card">
      ${icon("File badge.svg", "message-file-icon")}
      <span class="message-file-info">
        <span class="message-file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
        <small>${escapeHtml(file.format)} · ${formatBytes(file.size)}</small>
      </span>
    </div>
  `;
}

function aiMessageActions(message: ChatMessage): string {
  return `
    <div class="ai-actions" aria-label="Действия с ответом">
      <button type="button" data-feedback="up" data-message-id="${escapeHtml(message.id)}" aria-pressed="${message.feedback === "up"}" aria-label="Положительная оценка">${svgIcon("thumb-up.svg", "ai-action-icon")}</button>
      <button type="button" data-feedback="down" data-message-id="${escapeHtml(message.id)}" aria-pressed="${message.feedback === "down"}" aria-label="Отрицательная оценка">${svgIcon("thumb-down.svg", "ai-action-icon")}</button>
      <button type="button" data-copy-message="${escapeHtml(message.id)}" aria-label="Скопировать ответ">${svgIcon("copy-left.svg", "ai-action-icon")}</button>
    </div>
  `;
}
function modal(type: "new" | "home"): string {
  const isNew = type === "new";
  return `
    <div class="modal-backdrop">
      <section class="modal">
        <button class="modal-close" data-modal-cancel="true" aria-label="Закрыть"><span></span></button>
        <h2>${isNew ? "Создать новую схему?" : "Покинуть страницу?"}</h2>
        <p>${isNew ? "Текущие данные будут удалены. Схема не сохранится." : "Текущие данные будут удалены. Схема не сохранится."}</p>
        <div class="modal-actions">
          <button class="secondary-action modal-download" type="button">${svgIcon("download.svg", "button-icon")}<span>Скачать текущую схему</span></button>
          <div class="modal-actions-right">
            ${isNew ? '<button data-modal-cancel="true" class="secondary-action">Отмена</button><button id="modal-confirm" class="primary-action">Создать</button>' : '<button id="modal-confirm" class="secondary-action">На главную</button><button data-modal-cancel="true" class="primary-action">Остаться</button>'}
          </div>
        </div>
      </section>
    </div>
  `;
}

function generationToast(): string {
  return `
    <div class="generation-toast" role="status">
      <span class="toast-mark">!</span>
      <span><b>Схема не сформирована</b><small>Перезагрузите страницу<br />или повторите попытку позже</small></span>
      <button type="button" aria-label="Закрыть"></button>
    </div>
  `;
}

function icon(name: string, className = "icon", alt = ""): string {
  const altAttribute = alt ? `alt="${escapeHtml(alt)}"` : 'alt="" aria-hidden="true"';
  return `<img class="${className}" src="${iconUrl(name)}" ${altAttribute} />`;
}

function svgIcon(name: string, className = "button-icon"): string {
  const svg = inlineIcons[name];
  if (!svg) return icon(name, className);
  return svg.replace("<svg", `<svg class="${escapeHtml(className)}" aria-hidden="true" focusable="false"`);
}

function setSourceFile(file: File): void {
  selectedFile = file;
  const meta = fileMeta(file);
  if (state.start.sourceType === "recording") state.start.recording = meta;
  else state.start.file = meta;
  state.start.error = undefined;
  isFileChecking = true;
  const checkToken = ++fileCheckToken;
  persist();
  render();

  window.setTimeout(() => {
    if (checkToken !== fileCheckToken) return;
    state.start.error = validateSelectedFile(file);
    isFileChecking = false;
    persist();
    render();
  }, 250);
}

function clearSourceFile(): void {
  selectedFile = undefined;
  sourceFile = undefined;
  if (state.start.sourceType === "recording") state.start.recording = undefined;
  else state.start.file = undefined;
  if (state.start.error?.field === "attachment") state.start.error = undefined;
  isFileChecking = false;
  fileCheckToken += 1;
  persist();
  render();
}

function handleDropzoneHover(event: DragEvent): void {
  event.preventDefault();
  if (isLoading) return;
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  (event.currentTarget as HTMLElement).classList.add("is-drag-over");
}

function downloadLocalFile(file: File | Blob): void {
  const objectUrl = URL.createObjectURL(file);
  triggerDownload(objectUrl, file instanceof File ? file.name : "source-file");
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function downloadSampleFile(): void {
  triggerDownload(`/${encodeURIComponent("Пример ТЗ.docx")}`, "Пример ТЗ.docx");
}

function triggerDownload(href: string, filename: string): void {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}

function bindEvents(): void {
  document.removeEventListener("click", closeDownloadOnOutside);
  document.removeEventListener("keydown", closeDownloadOnEscape);

  document.querySelectorAll<HTMLButtonElement>("[data-source]").forEach((button) => {
    button.addEventListener("click", () => {
      state.start.sourceType = button.dataset.source as SourceType;
      state.start.error = undefined;
      state.start.file = undefined;
      state.start.recording = undefined;
      state.start.link = "";
      selectedFile = undefined;
      sourceFile = undefined;
      isFileChecking = false;
      fileCheckToken += 1;
      persist();
      render();
    });
  });

  const sourceInput = document.querySelector<HTMLInputElement>("#source-file");
  sourceInput?.addEventListener("click", () => {
    sourceInput.value = "";
  });
  sourceInput?.addEventListener("change", (event) => {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setSourceFile(file);
  });

  const dropzone = document.querySelector<HTMLElement>("[data-upload-dropzone]");
  dropzone?.addEventListener("dragenter", handleDropzoneHover);
  dropzone?.addEventListener("dragover", handleDropzoneHover);
  dropzone?.addEventListener("dragleave", () => dropzone.classList.remove("is-drag-over"));
  dropzone?.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-drag-over");
    const file = event.dataTransfer?.files?.[0];
    if (!file || isLoading) return;
    setSourceFile(file);
  });

  document.querySelector<HTMLInputElement>("#link")?.addEventListener("input", (event) => {
    const input = event.target as HTMLInputElement;
    state.start.link = input.value;
    state.start.error = undefined;
    const field = input.closest(".link-field");
    field?.classList.remove("has-error");
    field?.querySelector(".inline-error")?.remove();
    persist();
  });

  document.querySelector<HTMLTextAreaElement>("#details")?.addEventListener("input", (event) => {
    state.start.details = (event.target as HTMLTextAreaElement).value;
    persist();
  });

  document.querySelector<HTMLButtonElement>(".attachment-remove")?.addEventListener("click", clearSourceFile);
  document.querySelector<HTMLButtonElement>(".attachment-retry")?.addEventListener("click", () => {
    if (selectedFile) {
      setSourceFile(selectedFile);
      return;
    }
    document.querySelector<HTMLInputElement>("#source-file")?.click();
  });
  document.querySelector<HTMLButtonElement>(".attachment-download")?.addEventListener("click", () => {
    if (selectedFile) downloadLocalFile(selectedFile);
  });
  document.querySelector<HTMLButtonElement>(".sample-link")?.addEventListener("click", downloadSampleFile);

  document.querySelector<HTMLButtonElement>("#build")?.addEventListener("click", () => void buildDiagram());
  bindResultEvents();
}

function bindResultEvents(): void {
  if (state.page !== "result" || !state.result) return;

  document.querySelector<HTMLButtonElement>("#zoom-in")?.addEventListener("click", () => setZoom(state.view.scale + ZOOM_STEP));
  document.querySelector<HTMLButtonElement>("#zoom-out")?.addEventListener("click", () => setZoom(state.view.scale - ZOOM_STEP));
  document.querySelector<HTMLButtonElement>("#download-button")?.addEventListener("click", (event) => {
    event.stopPropagation();
    downloadOpen = !downloadOpen;
    render();
  });

  document.querySelectorAll<HTMLButtonElement>("[data-download]").forEach((button) => {
    const downloadType = button.dataset.download as "png" | "svg" | "pdf";
    button.addEventListener("click", () => void exportDiagram(downloadType));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " " && event.key !== "Space") return;
      event.preventDefault();
      void exportDiagram(downloadType);
    });
  });

  document.querySelector<HTMLButtonElement>("#new-diagram")?.addEventListener("click", () => {
    activeModal = "new";
    render();
  });
  document.querySelector<HTMLButtonElement>("#go-home")?.addEventListener("click", () => {
    activeModal = "home";
    render();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-modal-cancel]").forEach((button) => button.addEventListener("click", () => {
    activeModal = null;
    render();
  }));
  document.querySelector<HTMLButtonElement>(".modal-download")?.addEventListener("click", () => downloadSvg());
  document.querySelector<HTMLButtonElement>("#modal-confirm")?.addEventListener("click", () => {
    const target = activeModal;
    clearState();
    state = structuredClone(defaultState);
    activeModal = null;
    if (target === "home") {
      window.location.href = state.config.productHomeUrl;
      return;
    }
    persist();
    render();
  });

  document.querySelectorAll<HTMLButtonElement>("[data-quick]").forEach((button) => {
    button.addEventListener("click", () => {
      const label = button.dataset.quick || "";
      pendingActionType = quickActionType(label);
      state.chatDraft = label;
      persist();
      void sendChat();
    });
  });

  document.querySelector<HTMLButtonElement>("[data-source-download]")?.addEventListener("click", () => {
    if (sourceFile) downloadLocalFile(sourceFile);
  });

  document.querySelector<HTMLButtonElement>("[data-source-details-toggle]")?.addEventListener("click", (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    if (!button.closest(".source-message")?.classList.contains("has-overflow")) return;
    sourceDetailsOpen = !sourceDetailsOpen;
    render();
  });

  document.querySelectorAll<HTMLButtonElement>("[data-user-message-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.userMessageToggle || "";
      const message = state.result?.chat.find((item) => item.id === id);
      const messageNode = button.closest(".message.user");
      if (!message || !messageNode?.classList.contains("has-overflow")) return;
      if (expandedUserMessages.has(id)) expandedUserMessages.delete(id);
      else expandedUserMessages.add(id);
      render();
    });
  });

  document.querySelectorAll<HTMLButtonElement>("[data-feedback]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.messageId || "";
      const value = button.dataset.feedback as "up" | "down";
      const message = state.result?.chat.find((item) => item.id === id);
      if (!message) return;
      message.feedback = message.feedback === value ? undefined : value;
      persist();
      render();
    });
  });

  document.querySelectorAll<HTMLButtonElement>("[data-copy-message]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.copyMessage || "";
      const message = state.result?.chat.find((item) => item.id === id);
      if (!message) return;
      void navigator.clipboard?.writeText(message.text);
    });
  });

  const chatTextarea = document.querySelector<HTMLTextAreaElement>("#chat-message");
  const syncChatTextarea = (event: Event): void => {
    state.chatDraft = (event.target as HTMLTextAreaElement).value;
    chatInputError = "";
    syncChatComposerState();
    persist();
    resizeChatTextarea();
  };
  chatTextarea?.addEventListener("input", syncChatTextarea);
  chatTextarea?.addEventListener("change", syncChatTextarea);
  chatTextarea?.addEventListener("keyup", syncChatTextarea);
  chatTextarea?.addEventListener("compositionstart", () => {
    isChatComposing = true;
  });
  chatTextarea?.addEventListener("compositionend", () => {
    isChatComposing = false;
  });
  chatTextarea?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing || isChatComposing) return;
    event.preventDefault();
    void sendChat();
  });
  document.querySelector<HTMLButtonElement>("#send-chat")?.addEventListener("click", () => void sendChat());
  document.querySelector<HTMLInputElement>("#chat-file")?.addEventListener("change", (event) => {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files || []);
    input.value = "";
    if (!files.length || isChatLoading) return;
    addChatFiles(files);
    persist();
    render();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-remove-chat-file]").forEach((button) => {
    button.addEventListener("click", () => {
      if (isChatLoading) return;
      const index = Number(button.dataset.removeChatFile);
      removeChatFile(index);
      persist();
      render();
    });
  });

  document.querySelector<HTMLDivElement>("[data-chat-scroll]")?.addEventListener("scroll", () => {
    pendingChatScroll = false;
  });

  const viewport = document.querySelector<HTMLDivElement>("#diagram-viewport");
  const content = document.querySelector<HTMLDivElement>("#diagram-content");
  if (viewport && content) {
    applyTransform(content);
    viewport.addEventListener("wheel", (event) => {
      event.preventDefault();
      setZoom(state.view.scale + (event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP));
    }, { passive: false });
    viewport.addEventListener("pointerdown", (event) => {
      isDragging = true;
      dragStart = { x: event.clientX, y: event.clientY };
      dragOrigin = { x: state.view.x, y: state.view.y };
      viewport.setPointerCapture(event.pointerId);
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!isDragging) return;
      state.view.x = dragOrigin.x + event.clientX - dragStart.x;
      state.view.y = dragOrigin.y + event.clientY - dragStart.y;
      applyTransform(content);
      persist();
    });
    viewport.addEventListener("pointerup", () => { isDragging = false; });
  }

  document.addEventListener("click", closeDownloadOnOutside);
  document.addEventListener("keydown", closeDownloadOnEscape);
  window.onresize = () => {
    updateSourceDetailsOverflow();
    updateUserMessagesOverflow();
  };
}

async function renderMermaidAndUpdate(code: string): Promise<void> {
  await renderMermaid(code);
  const content = document.querySelector<HTMLDivElement>("#diagram-content");
  if (content) {
    content.innerHTML = getCachedSvg();
    state.view = centeredView();
    applyTransform(content);
    persist();
  }
}

async function buildDiagram(): Promise<void> {
  if (isLoading) return;
  state.start.error = validateBeforeSubmit();
  if (state.start.error) {
    persist();
    render();
    return;
  }

  isLoading = true;
  render();
  try {
    const form = new FormData();
    form.set("sourceType", state.start.sourceType);
    form.set("details", state.start.details);
    if (state.start.sourceType === "link") form.set("link", state.start.link);
    if (selectedFile) form.set("file", selectedFile);
    const result = await generateDiagram(form) as DiagramResult;
    result.details = state.start.details;
    sourceFile = selectedFile;
    sourceDetailsOpen = false;
    state.result = result;
    state.page = "result";
    state.view = centeredView();
    queueChatScroll(true);
    state.start.error = undefined;
    persist();
    void renderMermaidAndUpdate(result.mermaidCode);
  } catch (error) {
    state.start.error = normalizeApiError(error);
  } finally {
    isLoading = false;
    render();
  }
}

async function sendChat(): Promise<void> {
  if (!state.result || isChatLoading) return;
  const text = state.chatDraft.trim();
  const attachments = getChatAttachments();
  if (!text && !attachments.length) return;
  const draftBeforeSend = state.chatDraft;

  const userMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: "user",
    text: text || (attachments.length === 1 ? "Прикреплён файл" : `Прикреплено файлов: ${attachments.length}`),
    createdAt: new Date().toISOString(),
    attachment: attachments[0],
    attachments
  };

  const shouldScroll = isMessagesNearBottom();
  const actionType = pendingActionType;
  pendingActionType = "FREEFORM";
  const attachmentFile = chatFiles[0];
  state.result.chat.push(userMessage);
  state.chatDraft = "";
  chatInputError = "";
  isChatLoading = true;
  if (shouldScroll) queueChatScroll(true);
  persist();
  render();

  try {
    const form = new FormData();
    form.set("mermaidCode", state.result.mermaidCode);
    form.set("previousMermaidCode", state.previousMermaidCode ?? "");
    form.set("message", text);
    form.set("actionType", actionType);
    form.set("sourceText", state.result.sourceText ?? "");
    form.set("additionalDetails", state.result.details ?? "");
    if (attachmentFile) form.set("file", attachmentFile);

    const result = await sendChatMessage(form) as { mermaidCode: string; previousMermaidCode: string; message: string };
    if (!state.result) return;

    state.previousMermaidCode = result.previousMermaidCode;
    state.result.mermaidCode = result.mermaidCode;
    state.result.chat.push({
      id: crypto.randomUUID(),
      role: "assistant",
      text: result.message,
      createdAt: new Date().toISOString()
    });
    chatFiles = [];
    state.chatAttachment = undefined;
    state.chatAttachments = undefined;
    if (shouldScroll) queueChatScroll(true);
    void renderMermaidAndUpdate(result.mermaidCode);
  } catch (error) {
    state.chatDraft = draftBeforeSend;
    if (state.result) {
      const apiError = normalizeApiError(error);
      state.result.chat.push({
        id: crypto.randomUUID(),
        role: "assistant",
        text: apiError.message,
        createdAt: new Date().toISOString(),
        temporary: true
      });
    }
  } finally {
    isChatLoading = false;
    persist();
    render();
  }
}
async function exportDiagram(type: "png" | "svg" | "pdf"): Promise<void> {
  exportState = "exporting";
  render();
  try {
    if (type === "png") await downloadPng();
    if (type === "svg") downloadSvg();
    if (type === "pdf") downloadPdf();
    downloadOpen = false;
    exportState = "idle";
  } catch {
    exportState = "error";
  }
  render();
}

function validateBeforeSubmit(): AppState["start"]["error"] {
  if (state.start.sourceType === "link") {
    if (!state.start.link.trim()) return { code: "link-required", message: "Поле обязательно для заполнения", field: "link" };
    if (!/https?:\/\/.+/i.test(state.start.link) || !/(jira|confluence|wiki)/i.test(state.start.link)) {
      return { code: "invalid-link", message: "Неверный формат ссылки", field: "link" };
    }
    return undefined;
  }

  if (!selectedFile) return { code: "file-required", message: "Необходимо прикрепить файл", field: "attachment" };
  return validateSelectedFile(selectedFile);
}

function validateSelectedFile(file: File): AppState["start"]["error"] {
  const extension = extensionOf(file.name);
  if (state.start.sourceType === "recording") {
    if (file.size > 100 * 1024 * 1024) return { code: "file-size", message: "Файл превышает 100 МБ", field: "attachment" };
    if (!["mp3", "m4a", "mp4", "webm"].includes(extension)) return { code: "file-format", message: "Некорректный формат файла", field: "attachment" };
    return undefined;
  }
  if (file.size > 10 * 1024 * 1024) return { code: "file-size", message: "Файл превышает 10 МБ", field: "attachment" };
  if (!["txt", "docx", "pdf"].includes(extension)) return { code: "file-format", message: "Некорректный формат файла", field: "attachment" };
  return undefined;
}

function setZoom(next: number): void {
  const nextScale = clampZoom(next);
  if (Math.abs(state.view.scale - nextScale) < 0.001) return;
  state.view.scale = nextScale;
  persist();
  render();
}

function clampZoom(next: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(next.toFixed(4))));
}

function centeredView(): { scale: number; x: number; y: number } {
  const size = diagramSize();
  const viewportWidth = Math.max(320, window.innerWidth - RESULT_CHAT_WIDTH);
  const viewportHeight = Math.max(320, window.innerHeight - RESULT_TOOLBAR_HEIGHT);
  const scale = Math.min(1, Math.max(MIN_ZOOM, Math.min(viewportWidth / size.width, viewportHeight / size.height)));
  return {
    scale,
    x: Math.round((viewportWidth - size.width * scale) / 2),
    y: Math.round((viewportHeight - size.height * scale) / 2)
  };
}

function applyTransform(content: HTMLElement): void {
  content.style.transform = `translate(${state.view.x}px, ${state.view.y}px) scale(${state.view.scale})`;
}

function queueChatScroll(force = false): void {
  if (force || isMessagesNearBottom()) pendingChatScroll = true;
}

function isMessagesNearBottom(): boolean {
  const messages = document.querySelector<HTMLDivElement>("[data-chat-scroll]");
  if (!messages) return true;
  return messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
}

function scrollMessagesToEnd(): void {
  const messages = document.querySelector<HTMLDivElement>("[data-chat-scroll]");
  if (!messages) return;
  messages.scrollTop = messages.scrollHeight;
}

function resizeChatTextarea(): void {
  const textarea = document.querySelector<HTMLTextAreaElement>("#chat-message");
  if (!textarea) return;
  textarea.style.height = "auto";
  const maxHeight = 208;
  const nextHeight = Math.min(Math.max(textarea.scrollHeight, 20), maxHeight);
  textarea.style.height = `${nextHeight}px`;
  textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
}

function syncChatComposerState(): void {
  const composer = document.querySelector<HTMLElement>(".chat-input");
  const textarea = document.querySelector<HTMLTextAreaElement>("#chat-message");
  const sendButton = document.querySelector<HTMLButtonElement>("#send-chat");
  if (!composer || !textarea) return;

  const hasText = Boolean(textarea.value.trim());
  const hasFiles = getChatAttachments().length > 0;
  const hasContent = hasText || hasFiles;

  composer.classList.toggle("has-content", hasContent);
  composer.classList.toggle("has-files", hasFiles);
  composer.classList.toggle("has-error", Boolean(chatInputError));
  composer.classList.toggle("is-loading", isChatLoading);

  const errorNode = composer.querySelector<HTMLElement>(".chat-input-error");
  if (errorNode && !chatInputError) errorNode.remove();
  if (sendButton) sendButton.disabled = !hasContent || isChatLoading;
}

function getChatAttachments(): FileMeta[] {
  if (state.chatAttachments?.length) return state.chatAttachments;
  return state.chatAttachment ? [state.chatAttachment] : [];
}

function addChatFiles(files: File[]): void {
  chatInputError = "";
  for (const file of files) {
    const validationError = validateChatFile(file);
    if (validationError) {
      chatInputError = validationError;
      continue;
    }
    chatFiles.push(file);
  }
  state.chatAttachments = chatFiles.map(fileMeta);
  state.chatAttachment = state.chatAttachments[0];
}

function removeChatFile(index: number): void {
  if (!Number.isInteger(index) || index < 0) return;
  chatInputError = "";
  chatFiles.splice(index, 1);
  const next = chatFiles.map(fileMeta);
  state.chatAttachments = next.length ? next : undefined;
  state.chatAttachment = next[0];
}

function validateChatFile(file: File): string {
  if (file.size > CHAT_ATTACHMENT_MAX_BYTES) return "Размер файла не должен превышать 10 МБ";

  const extension = extensionOf(file.name);
  if (!isAllowedChatAttachmentExtension(extension)) return "Этот формат файла не поддерживается";
  if (file.type && !CHAT_ATTACHMENT_MIME_TYPES.has(file.type)) return "Этот формат файла не поддерживается";
  if (chatFiles.some((item) => isSameFile(item, file))) return "Файл уже добавлен";
  return "";
}

function isAllowedChatAttachmentExtension(extension: string): boolean {
  return CHAT_ATTACHMENT_FORMATS.includes(extension as typeof CHAT_ATTACHMENT_FORMATS[number]);
}

function isSameFile(left: File, right: File): boolean {
  return left.name === right.name && left.size === right.size && left.lastModified === right.lastModified;
}

function updateSourceDetailsOverflow(): void {
  const source = document.querySelector<HTMLElement>(".source-message");
  const details = document.querySelector<HTMLElement>(".source-details");
  const text = document.querySelector<HTMLElement>(".source-details-text");
  if (!source || !details || !text) return;

  const hasOverflow = hasOverflowAfterLines(text, 2);

  source.classList.toggle("has-overflow", hasOverflow);
  details.setAttribute("aria-expanded", String(sourceDetailsOpen && hasOverflow));
}

function hasOverflowAfterLines(element: HTMLElement, lines: number): boolean {
  const styles = window.getComputedStyle(element);
  const lineHeight = Number.parseFloat(styles.lineHeight) || 20;
  const collapsedHeight = lineHeight * lines;
  const clone = element.cloneNode(true) as HTMLElement;

  clone.style.position = "absolute";
  clone.style.visibility = "hidden";
  clone.style.pointerEvents = "none";
  clone.style.left = "-10000px";
  clone.style.top = "0";
  clone.style.width = `${element.getBoundingClientRect().width}px`;
  clone.style.height = "auto";
  clone.style.maxHeight = "none";
  clone.style.display = "block";
  clone.style.overflow = "visible";
  clone.style.webkitLineClamp = "unset";
  clone.style.webkitBoxOrient = "initial";
  clone.style.whiteSpace = "pre-wrap";
  clone.style.overflowWrap = "anywhere";
  clone.style.wordBreak = "break-word";

  document.body.appendChild(clone);
  const fullHeight = clone.scrollHeight;
  clone.remove();

  return fullHeight > collapsedHeight + 1;
}

function updateUserMessagesOverflow(): void {
  document.querySelectorAll<HTMLElement>(".message.user").forEach((messageNode) => {
    const text = messageNode.querySelector<HTMLElement>(".user-message-text");
    const toggle = messageNode.querySelector<HTMLButtonElement>(".user-message-toggle");
    if (!text || !toggle) return;

    const lineHeight = Number.parseFloat(window.getComputedStyle(text).lineHeight) || 20;
    const collapsedHeight = lineHeight * 2;
    const isOpen = text.classList.contains("is-open");
    const hasOverflow = isOpen
      ? text.scrollHeight > collapsedHeight + 1
      : text.scrollHeight > text.clientHeight + 1;

    messageNode.classList.toggle("has-overflow", hasOverflow);
    toggle.hidden = !hasOverflow;
    toggle.setAttribute("aria-expanded", String(isOpen && hasOverflow));
  });
}

function fileMeta(file: File): FileMeta {
  return {
    name: file.name,
    format: extensionOf(file.name).toUpperCase(),
    size: file.size
  };
}

function extensionOf(name: string): string {
  return name.toLowerCase().split(".").pop() || "";
}

function normalizeApiError(error: unknown): ApiError {
  if (error && typeof error === "object" && "message" in error) return error as ApiError;
  return { code: "diagram-generation", message: "Схема не сформирована. Перезагрузите страницу или повторите попытку позже" };
}

function closeDownloadOnOutside(event: Event): void {
  if (!downloadOpen) return;
  const target = event.target as HTMLElement;
  if (target.closest(".download-wrap")) return;
  downloadOpen = false;
  render();
}

function closeDownloadOnEscape(event: KeyboardEvent): void {
  if (event.key !== "Escape" || !downloadOpen) return;
  downloadOpen = false;
  render();
}

function formatBytes(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} МБ`;
  return `${Math.max(1, Math.round(size / 1024))} КБ`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

window.addEventListener("popstate", () => {
  state = loadState();
  render();
});

render();
