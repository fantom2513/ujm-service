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
  const mod = await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs") as {
    default: MermaidApi;
  };
  mod.default.initialize({ startOnLoad: false, securityLevel: "strict" });
  mermaidApi = mod.default;
  return mermaidApi;
}

export async function renderMermaid(code: string): Promise<string> {
  try {
    const mermaid = await getMermaid();
    const id = `mermaid-${Date.now()}`;
    const { svg } = await mermaid.render(id, code);
    cachedSvg = svg;
    return svg;
  } catch (error) {
    console.error("Mermaid render error:", error);
    return cachedSvg || fallbackSvg();
  }
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

export function diagramSize(): { width: number; height: number } {
  const svg = document.querySelector<SVGElement>("#diagram-content svg");
  if (svg) {
    const width = Number(svg.getAttribute("width")) || SVG_WIDTH;
    const height = Number(svg.getAttribute("height")) || SVG_HEIGHT;
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

export async function downloadPng(): Promise<void> {
  const svg = getCachedSvg();
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const image = await loadImage(url);
    const { width, height } = diagramSize();
    const canvas = document.createElement("canvas");
    canvas.width = width * 2;
    canvas.height = height * 2;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas is unavailable");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((value) => value ? resolve(value) : reject(new Error("PNG export failed")), "image/png");
    });
    downloadBlob(blob, filename("png"));
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function downloadPdf(): void {
  // MVP behavior: a real Mermaid SVG can't be trivially embedded as vector
  // PDF content without pulling in a proper PDF-generation library, which is
  // out of scope for this task. Rather than ship a ".pdf" file that isn't
  // actually a PDF (which would silently confuse users and break PDF
  // viewers), fall back to downloading the same cached SVG content that
  // downloadSvg() uses. The "PDF" menu entry in the UI still triggers this
  // distinct call site (exportDiagram() in main.ts), so swapping in a real
  // PDF exporter later is a localized change.
  downloadBlob(new Blob([getCachedSvg()], { type: "image/svg+xml" }), filename("svg"));
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
