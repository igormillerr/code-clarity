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
  text(s, 'provenance', 'Интеграция Python   /   12 ноября 2026', 79, 631, 1080, 30, 18, '#A9B7CC');
  notes(s, 'Открытие, около 25 секунд. AI помогает создавать код, но команда всё ещё должна понять его назначение и стоимость сопровождения. CodeClarity проверяет читаемость Git-изменений перед человеческим ревью. Текущая интеграция: Python dc9d957 влит merge-коммитом a922e40, пакет CodeClarity 0.3.2. Python возвращает все шесть метрик, включая Cognitive Complexity через complexipy 8.3.0. Java пока возвращает CC и CogC. История и LSP недоступны, совместная репетиция не проведена. Источники: CodeClarity_Agent_Concept_MVP.md; plugin/plugin.json; target/checks/report.json.');
}

// 2. The controlled naming example preserves all measured metric values.
{
  const s = slide('Имена меняются при одинаковых метриках', 'remaining: остаток вместимости после бронирования');
  text(s, 'before-label', 'До', 79, 213, 500, 48, 29, C.teal, true);
  text(s, 'after-label', 'После', 686, 213, 508, 48, 29, C.teal, true);
  text(s, 'before-code', 'def remaining(a, b):\n    c = a - b\n    if c < 0:\n        return 0\n    return c', 79, 279, 510, 210, 27, C.ink);
  text(s, 'after-code', 'def remaining(capacity, reserved):\n    available = capacity - reserved\n    if available < 0:\n        return 0\n    return available', 686, 279, 520, 210, 27, C.ink);
  text(s, 'naming-measurements', 'Все 6 метрик совпадают: CC 2, CogC 1, SLOC 5, глубина 1, параметры 2, возвраты 2', 79, 531, 1121, 88, 26, C.teal, true);
  notes(s, 'Около 45 секунд. Это контролируемый пример experiments/python_readability/naming, а не вымышленная иллюстрация измерений. Назначение remaining задано манифестом: max(capacity − reserved, 0) для неотрицательных целых. В обоих снимках все шесть значений равны: CC 2, CogC 1, SLOC 5, nesting 1, parameters 2, returns 2; дельты нулевые. Новые matchingKey сохраняют соответствие функции при переименовании параметров. В этом заданном контексте capacity/reserved и available раскрывают роли лучше a/b/c. Числа не оценивают качество имён. 20 подготовленных входных наборов дали ожидаемые результаты обеих версий, что не доказывает эквивалентность на всех возможных Python-значениях. Запуск python_experiments проверяет измерения и поведение контролируемых фикстур, но сам по себе не является независимым AI-ревью. Источники: experiments/python_readability/README.md, naming/before.py, naming/after.py; свежие target/experiments/run.json и summary.md.');
}

// 3. The process is an editable ordered text layout, not a bitmap diagram.
{
  const s = slide('Порядок проверки', 'Skills управляют ревью, Java Core возвращает проверяемые факты');
  const steps = [
    ['01', 'Git snapshots', 'Scope, SHA и изменённый код'],
    ['02', 'Independent Review', 'Находки до получения текущих метрик'],
    ['03', 'MCP metrics', 'Измерения Core и статусы доступности'],
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
  notes(s, 'Около 45 секунд. Порядок обязателен: метрики текущего запуска не попадают на независимый этап. После фиксации исходных Findings выполняется анализ чисел. Четыре Skills обеспечивают логическое разделение этапов в одном контексте Codex, а не четыре изолированных LLM. В текущей интеграции Python измеряет все шесть метрик через общий Core, Java выдаёт CC и CogC. AST доступен, LSP недоступен и не блокирует этот процесс. Ошибка истории не уничтожает основной отчёт. Источник: CodeClarity_Agent_Concept_MVP.md, разделы 3 и 5, ADR-01, ADR-06, ADR-09; интеграция a922e40.');
}

// 4. Python integration readiness and actual structural experiment values.
{
  const s = slide('Шесть метрик Python', 'shipping_fee: структурный пример после интеграции a922e40');
  const values = [
    ['Метрика', 'Java', 'Python до / после'],
    ['Cyclomatic complexity', 'PMD', '5 / 5'],
    ['Cognitive complexity', 'PMD', '12 / 4'],
    ['Function SLOC', 'Ожидает Core', '12 / 10'],
    ['Max nesting depth', 'Ожидает Core', '4 / 1'],
    ['Parameter count', 'Ожидает Core', '1 / 1'],
    ['Return count', 'Ожидает Core', '1 / 5'],
  ];
  const t = s.tables.add({ rows: 7, columns: 3, left: 78, top: 214, width: 1124, height: 341, columnWidths: [450, 250, 424], values });
  t.borders.assign({ fill: C.line, width: 0.8, style: 'solid' });
  t.cells.block({ row: 0, column: 0, rowCount: 7, columnCount: 3 }).assign({ textStyle: { fontFamily: FONT, fontSize: 23, color: C.ink }, margins: { left: 16, right: 14, top: 5, bottom: 5 }, fill: C.white });
  t.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 3 }).assign({ fill: C.navy, textStyle: { fontFamily: FONT, fontSize: 23, bold: true, color: C.white } });
  text(s, 'metrics-rule', 'Рост Return Count с 1 до 5 сам по себе не доказывает дефект.\nПоведение совпало на 32 подготовленных входных наборах.', 79, 584, 1120, 85, 24, C.teal);
  notes(s, 'Около 50 секунд. После интеграции Python dc9d957 через merge a922e40 Python Core возвращает все шесть метрик. Cognitive Complexity считает complexipy 8.3.0, структурные метрики используют ast и исходный текст. В shipping_fee CC осталась 5, CogC снизилась с 12 до 4, SLOC с 12 до 10, глубина с 4 до 1, параметры остались 1, return вырос с 1 до 5. Это реальные ответы MCP свежего target/experiments, не числа, рассчитанные моделью. Ранние выходы изменили структуру управления, поэтому рост return_count сам по себе не является дефектом. Подготовленные 32 набора входов дали одинаковые ожидаемые результаты, но не доказывают общую семантическую эквивалентность или более быстрое понимание человеком. Восемь наборов проверок интегрированного Core прошли на JDK21 и Python3.13.2, включая fixture метрик и MCP. Java пока имеет только CC/CogC, четыре структурных метрики остаются зависимостью от Core-разработчика. Источники: experiments/python_readability/README.md; свежие target/experiments/run.json, summary.md и target/checks/report.json. Packaged JAR SHA256 3c4bc878473fe264accf50224a4066060bad8832a318901a4bee79882841da69.');
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
  notes(s, 'Около 45 секунд. Числа 3 и 2 обозначают стартовую эвристику, а не статистику реальных пользователей. Демонстрационная история синтетическая и должна иметь соответствующую метку. Новый forward Eval проверил обе ветви решения: history-sufficient дал RULE_SUGGESTED с кандидатом PROPOSED, history-insufficient дал NO_SUGGESTION с пустым пользовательским сообщением. Эти проверки прошли, но не проверяют запись через Core. События внешнего подтверждения служат доказательством FIXED. Сам агент не может объявить свою находку исправленной человеком. Исчезновение нарушения или статический статус RESOLVED не заменяет подтверждение. Skill предлагает кандидат с примерами и исключениями. Атомарную идемпотентную запись JSON должен реализовать Core. В пакете 0.3.2 history MCP Tools отсутствуют, поэтому реальный путь хранения недоступен. Источники: Task03 LLM-05; концепция, разделы 5.4 и 8; evals/results/agent-python-integration-summary.json.');
}

// 6. Installed-plugin Python run and separate real-JAR Naming evaluation.
{
  const s = slide('Python: два проверенных сценария', 'CodeClarity 0.3.2: установленный плагин и отдельный forward Eval');
  text(s, 'installed-title', 'Codex CLI: PASS', 79, 218, 520, 54, 34, C.teal, true);
  text(s, 'installed-result', '2 файла, 6 MCP-вызовов\n12 сравнений метрик\nОбоснованных находок нет', 79, 291, 520, 148, 27, C.ink);
  text(s, 'forward-title', 'Naming Eval: WARN', 708, 218, 494, 54, 32, C.teal, true);
  text(s, 'forward-result', '1 находка opaque_names\nСвязь с метриками UNRELATED\nРеальный JAR, отдельный Eval', 709, 291, 496, 148, 25, C.ink);
  text(s, 'pass-boundary', 'PASS относится к выбранному Python scope и не доказывает идеальное качество кода.', 79, 489, 1123, 87, 27, C.ink, true);
  text(s, 'remaining', 'История UNAVAILABLE. Java: ещё 4 метрики. Совместная репетиция NOT_RUN.', 79, 609, 1123, 63, 22, C.muted);
  notes(s, 'Около 60 секунд. Левая колонка показывает завершённый реальный Codex CLI прогон установленного пакета 0.3.2 на двух Python-файлах с улучшенным head. Это шесть реальных MCP-вызовов: list_python_changes, четыре inspect_python_function и analyze_python_changes. Независимый этап рассмотрел 4/4 SNAPSHOT_ENTITY до текущих метрик; окончательный анализ охватил 2/2 MATCH_GROUP. Отчёт сохраняет 12 точных сравнений Core: все шесть видов метрик для каждой из двух сопоставленных функций, обе стороны AVAILABLE. Новых обоснованных находок нет и вердикт выбранного scope PASS. Main report и frozen independent artifact сохранены неизменными. История UNAVAILABLE, записи feedback/history нет. Справа отдельный forward Eval на source-built target JAR, а не установленный plugin E2E: регрессия имён invoice_totals.py получила WARN с одной opaque_names находкой и metricRelation UNRELATED, хотя CC и CogC низкие. В нём все шесть пар COMPARED, две snapshot сущности сопоставлены в одну match group. Эти результаты относятся к разным fixtures и не противоречат друг другу. Проверки артефактов, evaluator и launcher прошли, как и восемь Core-наборов, валидация четырёх Skills и полная JSON Schema. Один Codex-прогон не доказывает детерминированность модели. За рамками готового Python-сценария остаются четыре Java-метрики, history persistence, LSP и совместная репетиция. Источники: evals/results/codex-python-integration.json; evals/results/agent-python-integration-summary.json; .codeclarity/codex-python-integration-final/report.final.json и validation.json; plugin/plugin.json.');
}

await (await PresentationFile.exportPptx(p)).save(path.join(stage, 'candidate.pptx'));
for (const [i, s] of p.slides.items.entries()) {
  const png = await p.export({ slide: s, format: 'png', scale: 1 });
  await fs.writeFile(path.join(previews, `slide-${String(i + 1).padStart(2, '0')}.png`), new Uint8Array(await png.arrayBuffer()));
}
await fs.writeFile(path.join(stage, 'inspect.ndjson'), (await p.inspect({ kind: 'slide,textbox,table,notes', maxChars: 100000 })).ndjson);

const finalPath = path.join(output, process.env.CODECLARITY_DECK_FILENAME || 'CodeClarity_Python_Integration.pptx');
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
