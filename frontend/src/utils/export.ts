const SVG_WIDTH = 980;
const SVG_HEIGHT = 520;

// Holds the last successfully rendered Mermaid SVG markup, so synchronous
// re-renders (triggered by unrelated state changes) can keep showing the
// most recent diagram instead of flashing back to a placeholder.
let cachedSvg = "";

interface MermaidApi {
  initialize: (options: Record<string, unknown>) => void;
  render: (id: string, code: string) => Promise<{ svg: string }>;
}

let mermaidApi: MermaidApi | null = null;

async function getMermaid(): Promise<MermaidApi> {
  if (mermaidApi) return mermaidApi;
  // Mermaid is copied into the frontend image during the build. Test and
  // production browsers must not depend on access to a public CDN.
  const moduleUrl = new URL("../../vendor/mermaid/mermaid.esm.min.mjs", import.meta.url).href;
  const mod = await import(moduleUrl) as {
    default: MermaidApi;
  };
  // suppressErrorRendering: mermaid otherwise injects its own error UI (a
  // "bomb" icon + raw parser error) directly into document.body on a parse
  // failure, regardless of whether the caller catches render()'s rejection --
  // that's the stray element that showed up under the chat panel.
  mod.default.initialize({ startOnLoad: false, securityLevel: "strict", suppressErrorRendering: true });
  mermaidApi = mod.default;
  return mermaidApi;
}

export async function renderMermaid(code: string): Promise<string> {
  try {
    const mermaid = await getMermaid();
    const id = `mermaid-${Date.now()}`;
    const { svg } = await mermaid.render(id, code);
    return svg;
  } catch (error) {
    console.error("Mermaid render error:", error);
    return renderErrorSvg();
  }
}

export function setCachedSvg(svg: string): void {
  cachedSvg = svg;
}

export function getCachedSvg(): string {
  return cachedSvg || fallbackSvg();
}

function fallbackSvg(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SVG_WIDTH} ${SVG_HEIGHT}" width="${SVG_WIDTH}" height="${SVG_HEIGHT}" role="img" aria-label="Схема загружается">
    <rect width="${SVG_WIDTH}" height="${SVG_HEIGHT}" fill="#f9f9f9" stroke="#ccc" />
    <text x="${SVG_WIDTH / 2}" y="${SVG_HEIGHT / 2}" text-anchor="middle" fill="#999" font-size="16">Схема загружается...</text>
  </svg>`;
}

function renderErrorSvg(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SVG_WIDTH} ${SVG_HEIGHT}" width="${SVG_WIDTH}" height="${SVG_HEIGHT}" role="img" aria-label="Не удалось отобразить схему">
    <rect width="${SVG_WIDTH}" height="${SVG_HEIGHT}" fill="#f9f9f9" stroke="#ccc" />
    <text x="${SVG_WIDTH / 2}" y="${SVG_HEIGHT / 2}" text-anchor="middle" fill="#999" font-size="16">Не удалось отобразить схему</text>
  </svg>`;
}

export function diagramSize(): { width: number; height: number } {
  const svg = document.querySelector<SVGElement>("#diagram-content svg");
  if (svg) {
    // Mermaid ships `width="100%"` and no `height` attribute at all (its
    // default useMaxWidth behavior) -- the real rendered dimensions live
    // only in viewBox. Reading width/height directly turns Number("100%")
    // into NaN and Number(null) into 0, so both always fell through to the
    // fixed SVG_WIDTH/SVG_HEIGHT constants regardless of the diagram's
    // actual shape, stretching it to that fixed aspect ratio on export.
    // Rounded to whole pixels: viewBox values are near-always fractional
    // (Mermaid emits things like "0 0 842.859375 391"), and downstream
    // consumers (canvas.width/height, and the PDF image XObject's /Width
    // and /Height in buildPdfFromJpeg -- required to be integers per the
    // PDF spec) need a whole number they can all agree on. The browser
    // silently truncates a fractional canvas.width, so a mismatched
    // fractional /Width there produced a PDF that opened but rendered its
    // image as blank in most viewers.
    const viewBox = svg.getAttribute("viewBox");
    if (viewBox) {
      const [, , vbWidth, vbHeight] = viewBox.trim().split(/\s+/).map(Number);
      if (vbWidth > 0 && vbHeight > 0) return { width: Math.round(vbWidth), height: Math.round(vbHeight) };
    }
    const width = Math.round(Number(svg.getAttribute("width"))) || SVG_WIDTH;
    const height = Math.round(Number(svg.getAttribute("height"))) || SVG_HEIGHT;
    return { width, height };
  }
  return { width: SVG_WIDTH, height: SVG_HEIGHT };
}

export function filename(extension: "svg" | "png" | "pdf"): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}`;
  return `ux_arch_${stamp}.${extension}`;
}

export function downloadSvg(): void {
  downloadBlob(new Blob([getCachedSvg()], { type: "image/svg+xml" }), filename("svg"));
}

// Shared by downloadPng() and downloadPdf(): rasterizes the current diagram
// at 2x its real size (diagramSize(), now read from viewBox -- see above) so
// both exports keep the diagram's real proportions instead of a fixed box.
async function renderDiagramToCanvas(): Promise<HTMLCanvasElement> {
  const svg = getCachedSvg();
  const dataUrl = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;
  const image = await loadImage(dataUrl);
  const { width, height } = diagramSize();
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is unavailable");
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas;
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((value) => value ? resolve(value) : reject(new Error(`${type} export failed`)), type, quality);
  });
}

export async function downloadPng(): Promise<void> {
  const canvas = await renderDiagramToCanvas();
  const blob = await canvasToBlob(canvas, "image/png");
  downloadBlob(blob, filename("png"));
}

export async function downloadPdf(): Promise<void> {
  // No PDF library is pulled in: the diagram is rasterized the same way as
  // downloadPng() (JPEG instead of PNG here, since a hand-built PDF can
  // embed a JPEG byte-for-byte via /DCTDecode -- PDF's own image filter for
  // JPEG data -- with no re-encoding), then wrapped in a minimal one-page
  // PDF built by hand (buildPdfFromJpeg). Raster, not vector: fine for
  // sharing/printing, but zooming in or copying text out isn't possible --
  // see docs/superpowers/specs/2026-09-17-prod-crit-fixes-design.md #6 for
  // the vector-PDF alternative if that's ever needed.
  const canvas = await renderDiagramToCanvas();
  const jpegBlob = await canvasToBlob(canvas, "image/jpeg", 0.92);
  const jpegBytes = new Uint8Array(await jpegBlob.arrayBuffer());
  const { width, height } = diagramSize();
  downloadBlob(buildPdfFromJpeg(jpegBytes, width, height), filename("pdf"));
}

// Builds the smallest valid single-page PDF that shows one full-page JPEG:
// Catalog -> Pages -> Page (whose /Contents just draws the image XObject
// scaled to the page's MediaBox) -> the image XObject itself, followed by
// an xref table so PDF readers can jump straight to each object. The page
// is sized in points at diagramSize()'s (non-oversampled) dimensions, one
// point per source pixel -- the 2x-oversampled JPEG stays sharp when a
// viewer zooms in past 100%.
function buildPdfFromJpeg(jpegBytes: Uint8Array, width: number, height: number): Blob {
  const encoder = new TextEncoder();
  const parts: BlobPart[] = [];
  const objectOffsets: number[] = [];
  let length = 0;

  const pushBytes = (bytes: Uint8Array) => {
    parts.push(bytes);
    length += bytes.length;
  };
  const pushText = (text: string) => pushBytes(encoder.encode(text));
  const beginObject = (index: number) => {
    objectOffsets[index - 1] = length;
    pushText(`${index} 0 obj\n`);
  };

  pushText("%PDF-1.4\n");

  beginObject(1);
  pushText("<< /Type /Catalog /Pages 2 0 R >>\nendobj\n");

  beginObject(2);
  pushText("<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n");

  beginObject(3);
  pushText(
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] ` +
    `/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>\nendobj\n`
  );

  beginObject(4);
  pushText(
    `<< /Type /XObject /Subtype /Image /Width ${width * 2} /Height ${height * 2} ` +
    `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBytes.length} >>\nstream\n`
  );
  pushBytes(jpegBytes);
  pushText("\nendstream\nendobj\n");

  beginObject(5);
  const content = `q ${width} 0 0 ${height} 0 0 cm /Im0 Do Q`;
  pushText(`<< /Length ${content.length} >>\nstream\n${content}\nendstream\nendobj\n`);

  const xrefOffset = length;
  pushText(`xref\n0 ${objectOffsets.length + 1}\n0000000000 65535 f \n`);
  for (const offset of objectOffsets) {
    pushText(`${String(offset).padStart(10, "0")} 00000 n \n`);
  }
  pushText(`trailer\n<< /Size ${objectOffsets.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`);

  return new Blob(parts, { type: "application/pdf" });
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Image load failed"));
    image.src = url;
  });
}

function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
