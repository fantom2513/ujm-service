export const TEST_MERMAID = `flowchart LR
Start((Вход в Copilot))
Source[Выбор источника ТЗ]
Generate[Построение Mermaid-схемы]
Result[Страница результата]
Chat[AI-чат]
Export[Скачивание схемы]
Success[✅ Схема готова]
Start -->|Открыть| Source
Source -->|Построить| Generate
Generate -->|Показать| Result
Result -->|Изменить| Chat
Result -->|Скачать| Export
Export -->|Сохранить| Success
classDef page fill:#FFFFFF,stroke:#333333
classDef success fill:#E8F5E9,stroke:#2E7D32,color:#1B5E20,stroke-width:2px
class Start,Source,Generate,Result,Chat,Export page
class Success success`;

// Mermaid flowchart directions: TB (top-bottom), TD (top-down, synonym of TB),
// BT, RL, LR. The generate/edit prompts instruct the model to start with
// `flowchart LR` or `flowchart TB` (TB for complex >12-node diagrams), so both
// must pass validation — accept the full set to be safe.
const FLOWCHART_HEADER = /^flowchart\s+(TB|TD|BT|RL|LR)\b/;

export function validateMermaid(code: string): { ok: true } | { ok: false; reason: string } {
  const trimmed = code.trim();
  if (!FLOWCHART_HEADER.test(trimmed)) {
    return { ok: false, reason: "Mermaid must start with 'flowchart' and a direction (LR/TB/TD/BT/RL)" };
  }
  if (/<script|<\/script|onerror=|onload=/i.test(trimmed)) {
    return { ok: false, reason: "Unsafe content in Mermaid" };
  }
  return { ok: true };
}
