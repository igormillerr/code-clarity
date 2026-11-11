/** Build the editable CodeClarity deck with the bundled Artifact Tool runtime. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const workspaceDir = path.dirname(fileURLToPath(import.meta.url));
const modules = process.env.CODECLARITY_NODE_MODULES;
const skillDir = process.env.CODECLARITY_PRESENTATIONS_SKILL;
const pythonExecutable = process.env.CODECLARITY_RUNTIME_PYTHON;
if (!modules || !skillDir || !pythonExecutable) {
  throw new Error('Set CODECLARITY_NODE_MODULES, CODECLARITY_PRESENTATIONS_SKILL and CODECLARITY_RUNTIME_PYTHON to the bundled runtime paths.');
}
// The first-party finalizer launches an isolated import check in a child process.
process.env.RUNTIME_NODE_MODULES = modules;
const requireRuntime = createRequire(path.join(modules, '_codeclarity-resolver.cjs'));
const { Presentation, PresentationFile } = await import(pathToFileURL(requireRuntime.resolve('@oai/artifact-tool')).href);
const { finalizePresentation } = await import(pathToFileURL(path.join(skillDir, 'container_tools/artifact_tool_utils.mjs')).href);
const stage = path.join(workspaceDir, '.build');
const output = path.join(workspaceDir, 'output');
const previews = path.join(workspaceDir, 'previews');
await Promise.all([stage, output, previews].map(folder => fs.mkdir(folder, { recursive: true })));

const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = { navy: '#111827', ink: '#172033', muted: '#536174', paper: '#F7F9FC', white: '#FFFFFF', teal: '#0B7A70', mint: '#55DEC4', gold: '#F5BE6A', line: '#D8E0EA' };
const FONT = 'Arial';
function text(slide, name, value, x, y, w, h, size = 28, color = C.ink, bold = false) {
  const shape = slide.shapes.add({ name, geometry: 'textbox', position: { left: x, top: y, width: w, height: h }, fill: 'none', line: { fill: 'none', width: 0 } });
  shape.text = value;
  shape.text.style = { fontFamily: FONT, fontSize: size, bold, color, verticalAlignment: 'middle', wrap: true };
  return shape;
}
function slide(title, subtitle, dark = false) {
  const s = p.slides.add();
  s.background.fill = dark ? C.navy : C.paper;
  text(s, 'title', title, 72, 54, 1136, 74, 43, dark ? C.white : C.ink, true);
  if (subtitle) text(s, 'subtitle', subtitle, 74, 133, 1128, 50, 22, dark ? '#A9B7CC' : C.muted);
  return s;
}
function notes(s, value) { s.speakerNotes.text = value; }

// 1. Minimal title and concrete product purpose.
{
  const s = p.slides.add(); s.background.fill = C.navy;
  text(s, 'brand', 'CodeClarity', 72, 126, 1120, 112, 84, C.white, true);
  text(s, 'purpose', 'Читаемость изменений\nJava и Python', 77, 272, 1090, 140, 45, C.mint);
  text(s, 'benefit', 'Разработчик получает объяснение проблем\nдо ревью человеком', 79, 462, 1060, 100, 29, '#DCE5F1');
  text(s, 'provenance', 'Рабочий срез MVP   /   11 ноября 2026', 79, 631, 1080, 30, 18, '#A9B7CC');
  notes(s, 'Открытие, около 25 секунд. AI помогает создавать код, но команда всё ещё должна понять его назначение и стоимость сопровождения. CodeClarity проверяет читаемость Git-изменений перед человеческим ревью. В этой презентации целевой сценарий отделён от фактической готовности. Источники: CodeClarity_Agent_Concept_MVP.md, разделы 1–3; README ветки feature/python, ec6a3ed.');
}

// 2. An explicitly illustrative issue that complexity alone cannot resolve.
{
  const s = slide('Короткий код тоже требует ревью', 'Иллюстрация: читаемость кода, созданного с AI');
  text(s, 'code', 'def f(items):\n    return [item for item in items\n            if item.is_active]', 78, 248, 690, 184, 30, C.teal);
  text(s, 'observation-title', 'Неясное назначение', 818, 247, 374, 55, 29, C.ink, true);
  text(s, 'observation', 'Имя f не объясняет,\nкакой результат\nполучит вызывающий код', 818, 315, 374, 156, 28, C.muted);
  text(s, 'recommendation', 'Минимальная рекомендация: назвать функцию select_active_items', 79, 531, 1116, 82, 29, C.ink, true);
  notes(s, 'Около 35 секунд. Это иллюстрация, а не результат замера или проведённого Eval. Функция выполняет простую фильтрацию, но имя f не передаёт её назначение. Сначала независимое ревью формулирует наблюдение и указывает строки. Затем корреляция получает реальные числа из MCP. Низкая сложность не отменяет замечание Naming. Не приводить выдуманные значения CC/CogC. Источники: CodeClarity_Agent_Concept_MVP.md, разделы 4–5; Task03, LLM-03 и LLM-04.');
}

// 3. The process is an editable ordered text layout, not a bitmap diagram.
{
  const s = slide('Порядок проверки', 'Skills управляют ревью, Java Core возвращает проверяемые факты');
  const steps = [
    ['01', 'Git snapshots', 'Scope, SHA и изменённый код'],
    ['02', 'Independent Review', 'Находки до получения текущих метрик'],
    ['03', 'MCP metrics', 'Шесть измерений и статусы доступности'],
    ['04', 'Metrics Correlation', 'Проверка связи чисел и замечаний'],
    ['05', 'Report', 'JSON, Markdown, доказательства и вердикт'],
    ['06', 'Rule Discovery', 'История и предложение нового правила'],
  ];
  steps.forEach(([n, title, body], i) => {
    const col = i < 3 ? 0 : 1, row = i % 3;
    const x = 78 + col * 596, y = 217 + row * 127;
    text(s, `number-${n}`, n, x, y, 67, 49, 35, C.teal, true);
    text(s, `step-${n}`, title, x + 83, y, 443, 47, 29, C.ink, true);
    text(s, `body-${n}`, body, x + 83, y + 49, 443, 60, 22, C.muted);
  });
  text(s, 'architecture-boundary', 'Локальный Java 21 Core и MCP STDIO. Отдельный backend не требуется.', 79, 636, 1110, 37, 21, C.teal);
  notes(s, 'Около 45 секунд. Порядок обязателен: метрики текущего запуска не попадают на независимый этап. После фиксации исходных Findings выполняется анализ чисел. Четыре Skills обеспечивают логическое разделение этапов в одном контексте Codex, а не четыре изолированных LLM. AST доступен сейчас, LSP опционален и не блокирует этот процесс. Источник: CodeClarity_Agent_Concept_MVP.md, разделы 3 и 5, ADR-01, ADR-06, ADR-09.');
}

// 4. Six required metrics with the precise source-base readiness.
{
  const s = slide('Шесть метрик MVP', 'Фактическое состояние базовой ветки feature/python, ec6a3ed');
  const values = [
    ['Метрика', 'Java', 'Python'],
    ['Cyclomatic complexity', 'PMD', 'Собственный AST-алгоритм'],
    ['Cognitive complexity', 'PMD', 'UNSUPPORTED'],
    ['Function SLOC', 'Ожидает Core', 'Ожидает Python'],
    ['Max nesting depth', 'Ожидает Core', 'Ожидает Python'],
    ['Parameter count', 'Ожидает Core', 'Ожидает Python'],
    ['Return count', 'Ожидает Core', 'Ожидает Python'],
  ];
  const t = s.tables.add({ rows: 7, columns: 3, left: 78, top: 214, width: 1124, height: 341, columnWidths: [450, 250, 424], values });
  t.borders.assign({ fill: C.line, width: 0.8, style: 'solid' });
  t.cells.block({ row: 0, column: 0, rowCount: 7, columnCount: 3 }).assign({ textStyle: { fontFamily: FONT, fontSize: 23, color: C.ink }, margins: { left: 16, right: 14, top: 5, bottom: 5 }, fill: C.white });
  t.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 3 }).assign({ fill: C.navy, textStyle: { fontFamily: FONT, fontSize: 23, bold: true, color: C.white } });
  text(s, 'metrics-rule', 'Числа поступают только из MCP/Core.\nНедоступность сохраняет явный статус, delta требует совместимых алгоритмов.', 79, 584, 1120, 85, 24, C.teal);
  notes(s, 'Около 40 секунд. Таблица фиксирует именно исходную основу ec6a3ed, а не обещает завершённую интеграцию. В ней Java выдаёт CC и CogC через PMD 7.29.0, Python выдаёт CC через собственный алгоритм, Python CogC возвращает UNSUPPORTED. Остальные четыре метрики реализуют коллеги. Анализатор, его версия и алгоритм входят в определение измерения. Delta допустима только при двух доступных совместимых значениях. Return count остаётся информационной метрикой. Источники: README feature/python ec6a3ed, раздел Численные метрики; Task01 PY-02; Task02 JV-02.');
}

// 5. The candidate rule uses synthetic evidence and requires a human decision.
{
  const s = slide('Rule Discovery', 'Предложение правила на подготовленной тестовой истории', true);
  text(s, 'occurrences', '3', 79, 221, 170, 119, 94, C.mint, true);
  text(s, 'occurrences-label', 'отдельных обнаружения\nодной категории', 270, 230, 394, 103, 29, C.white);
  text(s, 'fixed', '2', 79, 360, 170, 119, 94, C.mint, true);
  text(s, 'fixed-label', 'исправления с внешним\nподтверждением', 270, 369, 394, 103, 29, C.white);
  text(s, 'candidate', 'PROPOSED', 765, 259, 430, 74, 47, C.gold, true);
  text(s, 'candidate-rule', 'Кандидат с примерами\nи исключениями.\nАктивацию решает человек.', 766, 352, 429, 148, 28, '#DCE5F1');
  text(s, 'history-caveat', 'Дополнительно: нет эквивалентного кандидата. Без оснований Skill не выводит предложение.', 79, 572, 1110, 89, 23, '#A9B7CC');
  notes(s, 'Около 45 секунд. Числа 3 и 2 обозначают стартовую эвристику, а не статистику реальных пользователей. Демонстрационная история синтетическая и должна иметь соответствующую метку. Два forward Eval сценария history-sufficient и history-insufficient проверили решение Skill и прошли, но не проверяли запись через Core. События внешнего подтверждения служат доказательством FIXED. Сам агент не может объявить свою находку исправленной человеком. Исчезновение нарушения или статический статус RESOLVED не заменяет подтверждение. Skill предлагает кандидат с примерами и исключениями. Атомарную идемпотентную запись JSON должен реализовать Core. В фактическом запуске history MCP Tools отсутствуют и Rule Discovery имеет статус UNAVAILABLE. Источники: Task03 LLM-05; концепция, разделы 5.4 и 8; evals/results/agent-forward.json и evals/results/codex-live.json.');
}

// 6. Observed installed-plugin run, with remaining MVP dependencies visible.
{
  const s = slide('Фактический запуск Codex', 'Установленный CodeClarity 0.2.0, смешанный Java/Python пример');
  text(s, 'observed-title', 'Проверено', 79, 218, 495, 47, 31, C.teal, true);
  text(s, 'observed', '4 Skills доступны в плагине\n8 реальных MCP-вызовов\n2 обоснованные AI-находки', 79, 279, 520, 150, 28, C.ink);
  text(s, 'verdict-title', 'INCOMPLETE', 708, 217, 494, 58, 39, C.teal, true);
  text(s, 'remaining', 'Часть метрик отсутствует\nИстория UNAVAILABLE\nРепетиция ещё не проведена', 709, 294, 496, 139, 26, C.ink);
  text(s, 'eval-result', '6 Evals PASS: 4 с реальным JAR, 2 с синтетической историей', 79, 480, 1123, 68, 29, C.ink, true);
  text(s, 'measurement-result', 'Java до / после: CC 1 / 7, CogC 0 / 21. Независимые находки зафиксированы до анализа.', 79, 566, 1123, 83, 23, C.muted);
  notes(s, 'Около 50 секунд. Это фактический запуск установленного плагина codeclarity@codeclarity-local, а не shell-эмуляция MCP. Codex CLI сделал 8 реальных вызовов: list_java_changes и list_python_changes, по два inspect каждого языка и analyze обоих языков. Независимый артефакт зафиксирован в JSONL eventIndex 37, анализы начались на 38 и 39. Финальный отчёт содержит две AI-находки: вложенные Java guards с metricRelation SUPPORTED и непрозрачные Python имена с UNRELATED. PMD вернул Java CC до 1, после 7, delta 6 и CogC до 0, после 21, delta 21. Шесть записей сравнения в отчёте не означают шесть реализованных видов метрик: две записи Java и четыре записи Python для старой и новой сигнатур. Python subtotal(line_items) и subtotal(a) не сопоставлены, поэтому численной delta нет. Итог INCOMPLETE отражает отсутствующие обязательные метрики, история UNAVAILABLE. Шесть forward Evals прошли: четыре на коде с реальным JAR и два исключительно на синтетической истории для проверки решения Skill, без persistence E2E. Один живой запуск не доказывает детерминированность модели. Совместная репетиция остаётся NOT_RUN. Источники: evals/results/codex-live.json, evals/results/agent-forward.json, plugin/plugin.json; общий runbook docs/llm-demo.md.');
}

await (await PresentationFile.exportPptx(p)).save(path.join(stage, 'candidate.pptx'));
for (const [i, s] of p.slides.items.entries()) {
  const png = await p.export({ slide: s, format: 'png', scale: 1 });
  await fs.writeFile(path.join(previews, `slide-${String(i + 1).padStart(2, '0')}.png`), new Uint8Array(await png.arrayBuffer()));
}
await fs.writeFile(path.join(stage, 'inspect.ndjson'), (await p.inspect({ kind: 'slide,textbox,table,notes', maxChars: 100000 })).ndjson);

const finalPath = path.join(output, process.env.CODECLARITY_DECK_FILENAME || 'CodeClarity_MVP_final.pptx');
const validation = await finalizePresentation({
  workspaceDir,
  candidatePath: path.join(stage, 'candidate.pptx'),
  finalPath,
  pythonExecutable,
  integrityValidatorPath: path.join(skillDir, 'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(skillDir, 'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu', '12192000,6858000', '--validate-bullet-geometry', '--validate-heading-fit', '--require-native-table-slide', '4'],
  explicitTotalSlideCount: 6,
  requiredNativeTableOwnerSlides: [4],
  fontPolicy: { basis: 'design', families: [FONT] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stage, `${path.basename(finalPath)}.validation.json`),
});
console.log(JSON.stringify({ finalPath, slides: p.slides.items.length, validation }, null, 2));
