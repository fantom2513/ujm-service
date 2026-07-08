const svgWidth = 980;
const svgHeight = 520;

export function renderDiagramSvg(): string {
  const boxes = [
    ["Вход в Copilot", 40, 210, 145, 76],
    ["Выбор источника", 230, 210, 160, 76],
    ["Построение схемы", 440, 210, 170, 76],
    ["Страница результата", 665, 210, 180, 76],
    ["AI-чат", 665, 84, 180, 70],
    ["Скачивание", 665, 360, 180, 70],
    ["✓ Схема готова", 875, 360, 70, 70]
  ] as const;
  const arrows = [
    [185, 248, 230, 248, "Открыть"],
    [390, 248, 440, 248, "Построить"],
    [610, 248, 665, 248, "Показать"],
    [755, 210, 755, 154, "Изменить"],
    [755, 286, 755, 360, "Скачать"],
    [845, 395, 875, 395, "Сохранить"]
  ] as const;

  const arrowMarkup = arrows.map(([x1, y1, x2, y2, label]) => `
    <path d="M ${x1} ${y1} L ${x2} ${y2}" class="edge" marker-end="url(#arrow)" />
    <text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 10}" class="edge-label">${label}</text>
  `).join("");

  const boxMarkup = boxes.map(([label, x, y, w, h]) => {
    const isSuccess = label.includes("✓");
    return `
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" class="${isSuccess ? "success-node" : "page-node"}" />
      <text x="${x + w / 2}" y="${y + h / 2 + 5}" class="${isSuccess ? "success-label" : "node-label"}">${label}</text>
    `;
  }).join("");

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${svgWidth} ${svgHeight}" width="${svgWidth}" height="${svgHeight}" role="img" aria-label="Тестовая Mermaid-схема">
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#405060" />
      </marker>
    </defs>
    <rect width="${svgWidth}" height="${svgHeight}" fill="transparent" />
    <g>${arrowMarkup}${boxMarkup}</g>
  </svg>`;
}

export function diagramSize(): { width: number; height: number } {
  return { width: svgWidth, height: svgHeight };
}

export function filename(extension: "svg" | "png" | "pdf"): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}`;
  return `ux_arch_${stamp}.${extension}`;
}

export function downloadSvg(): void {
  downloadBlob(new Blob([renderDiagramSvg()], { type: "image/svg+xml" }), filename("svg"));
}

export async function downloadPng(): Promise<void> {
  const svg = renderDiagramSvg();
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const image = await loadImage(url);
    const canvas = document.createElement("canvas");
    canvas.width = svgWidth * 2;
    canvas.height = svgHeight * 2;
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
  const content = [
    "0.93 0.95 0.97 rg 40 430 120 48 re f",
    "0 0 0 rg BT /F1 12 Tf 62 456 Td (Start) Tj ET",
    "0.93 0.95 0.97 rg 200 430 130 48 re f",
    "0 0 0 rg BT /F1 12 Tf 228 456 Td (Source) Tj ET",
    "0.93 0.95 0.97 rg 370 430 145 48 re f",
    "0 0 0 rg BT /F1 12 Tf 395 456 Td (Generate) Tj ET",
    "0.93 0.95 0.97 rg 555 430 145 48 re f",
    "0 0 0 rg BT /F1 12 Tf 585 456 Td (Result) Tj ET",
    "0.9 0.97 0.9 rg 555 330 145 48 re f",
    "0 0 0 rg BT /F1 12 Tf 590 356 Td (Export) Tj ET",
    "0 0 0 RG 160 454 m 200 454 l S 330 454 m 370 454 l S 515 454 m 555 454 l S"
  ].join("\n");
  const pdf = createSimplePdf(content);
  downloadBlob(new Blob([pdf], { type: "application/pdf" }), filename("pdf"));
}

function createSimplePdf(content: string): string {
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 760 560] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`
  ];
  let result = "%PDF-1.4\n";
  const offsets = [0];
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(result.length);
    result += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
  }
  const xrefStart = result.length;
  result += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) {
    result += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  result += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;
  return result;
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
