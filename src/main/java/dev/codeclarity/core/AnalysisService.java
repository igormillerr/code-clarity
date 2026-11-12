package dev.codeclarity.core;

import dev.codeclarity.git.GitRepository;
import dev.codeclarity.core.model.SourceRange;
import dev.codeclarity.core.model.SourceEntity;
import dev.codeclarity.core.model.Finding;
import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.MetricDefinition;
import dev.codeclarity.core.model.MetricMeasurement;
import dev.codeclarity.core.model.MetricValue;
import static dev.codeclarity.core.model.MetricValue.Status.*;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public final class AnalysisService {
    public static final int MAX_ANALYSIS_FILES = 50;

    private final GitRepository git;
    private final LanguageRegistry languages;

    public AnalysisService(GitRepository git, LanguageRegistry languages) {
        this.git = git;
        this.languages = languages;
    }

    public AnalysisService(GitRepository git, LanguageRegistry languages, String languageId) {
        this(git, new LanguageRegistry(List.of(languages.require(languageId))));
    }

    public record Changes(String baseSha, String headSha, String status,
                          List<GitRepository.Change> files, List<String> warnings) {}

    public record Diagnostic(String method, String rule, String status, Finding before, Finding after) {}

    public record FileAnalysis(String oldPath, String newPath, String language,
                               List<String> changedMethods, List<Diagnostic> findings,
                               List<MetricComparison> metrics, Coverage coverage) {
        public FileAnalysis(String oldPath, String newPath, String language, List<String> changedMethods,
                            List<Diagnostic> findings, List<MetricComparison> metrics) {
            this(oldPath, newPath, language, changedMethods, findings, metrics,
                    new Coverage(CoverageSide.unknown(), CoverageSide.unknown()));
        }
    }

    public record Coverage(CoverageSide base, CoverageSide head) {}

    /** Line-based entity coverage, independent of transport success and metric availability. */
    public record CoverageSide(String status, List<SourceRange> outsideEntityLines, String reason) {
        static CoverageSide unknown() {
            return new CoverageSide("UNKNOWN", List.of(), "Source or file analysis did not complete.");
        }
    }

    public record Review(String baseSha, String headSha, String status, List<FileAnalysis> files, List<String> warnings) {}

    public record SymbolContext(String commitSha, String path, String language, String status,
                                String signature, SourceRange lines, String source,
                                List<EntityContext.Call> calls, boolean truncated, List<String> warnings) {}

    private record Version(List<SourceEntity> entities, List<Finding> findings, boolean complete, List<MetricMeasurement> metrics) {
        static Version empty(boolean complete) {
            return new Version(List.of(), List.of(), complete, List.of());
        }

        Set<String> touched(List<SourceRange> ranges) {
            Set<String> signatures = new LinkedHashSet<>();
            for (var method : entities) {
                if (ranges.stream().anyMatch(method.lines()::overlaps)) {
                    signatures.add(method.signature());
                }
            }
            return signatures;
        }

        Map<String, Finding> rules(String signature) {
            Map<String, Finding> rules = new LinkedHashMap<>();
            var matches = entities.stream().filter(method -> method.signature().equals(signature)).toList();
            if (matches.size() == 1) {
                var method = matches.getFirst();
                for (var finding : findings) {
                    if (method.lines().contains(finding.line())) {
                        var owner = entities.stream()
                                .filter(candidate -> candidate.lines().contains(finding.line()))
                                .min(java.util.Comparator.comparingInt(candidate ->
                                        candidate.lines().endLine() - candidate.lines().startLine()));
                        if (owner.orElseThrow() == method) {
                            rules.put(finding.rule(), finding);
                        }
                    }
                }
            }
            return rules;
        }

        MetricValue metric(String entity, MetricDefinition definition) {
            if (!complete) {
                return MetricValue.unavailable(definition, ERROR, "Incomplete source analysis.");
            }
            long count = entityCount(entity);
            if (count == 0) {
                return MetricValue.unavailable(definition, ENTITY_ABSENT, "No matching entity in this version.");
            }
            if (count > 1) {
                return MetricValue.unavailable(definition, ERROR, "Ambiguous entity signature.");
            }
            var values = metrics.stream().filter(value -> value.entity().equals(entity)
                    && value.metric().definition().id().equals(definition.id())).toList();
            if (values.size() != 1) {
                return MetricValue.unavailable(definition, values.isEmpty() ? MISSING : ERROR,
                        values.isEmpty() ? "Analyzer returned no measurement." : "Duplicate metric measurements.");
            }
            return values.getFirst().metric();
        }

        long entityCount(String signature) {
            return entities.stream().filter(method -> method.signature().equals(signature)).count();
        }
    }

    private record RoutedFile(GitRepository.ChangedFile file, LanguageSupport language) {}

    private List<RoutedFile> changedFiles(GitRepository.Snapshot snapshot) {
        List<RoutedFile> files = new ArrayList<>();
        for (var file : git.changedFiles(snapshot)) {
            var before = languages.find(file.oldPath()).orElse(null);
            var after = languages.find(file.newPath()).orElse(null);
            if (before != null && before == after) {
                files.add(new RoutedFile(file, before));
            } else {
                // A change of language is a deletion plus an addition, never an entity match.
                if (before != null) {
                    files.add(new RoutedFile(new GitRepository.ChangedFile(file.oldPath(), null), before));
                }
                if (after != null) {
                    files.add(new RoutedFile(new GitRepository.ChangedFile(null, file.newPath()), after));
                }
            }
        }
        return files;
    }

    public Changes listChanges(String baseRef, String headRef) {
        var snapshot = git.snapshot(baseRef, headRef);
        List<GitRepository.Change> changes = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        for (var routed : changedFiles(snapshot)) {
            var file = routed.file();
            try {
                changes.add(git.ranges(snapshot, file));
            } catch (RuntimeException exception) {
                warnings.add(file.path() + ": " + failure(exception));
                changes.add(new GitRepository.Change(file.oldPath(), file.newPath(), List.of(), List.of()));
            }
        }
        return new Changes(snapshot.baseSha(), snapshot.headSha(), warnings.isEmpty() ? "ok" : "partial",
                changes, warnings);
    }

    public Review analyzeChanges(String baseSha, String headSha, List<String> paths) {
        var snapshot = new GitRepository.Snapshot(git.commit(baseSha), git.commit(headSha));
        var changedFiles = changedFiles(snapshot);
        var selected = changedFiles.stream().filter(routed -> paths.isEmpty() || paths.contains(routed.file().path())).toList();
        var selectedPaths = selected.stream().map(routed -> routed.file().path()).toList();
        if (!selectedPaths.containsAll(paths)) {
            throw new IllegalArgumentException("paths must identify changed files supported by this service.");
        }
        if (selected.size() > MAX_ANALYSIS_FILES) {
            throw new IllegalArgumentException("Analysis selected " + selected.size() + " changed files. "
                    + "Use paths to analyze up to " + MAX_ANALYSIS_FILES + " files per call with the same commit SHAs.");
        }

        List<FileAnalysis> files = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        for (var routed : selected) {
            var file = routed.file();
            try {
                files.add(analyzeFile(snapshot, file, routed.language(), warnings));
            } catch (RuntimeException exception) {
                warnings.add(file.path() + ": " + failure(exception));
                files.add(new FileAnalysis(file.oldPath(), file.newPath(), routed.language().languageId(),
                        List.of(), List.of(), List.of()));
            }
        }
        return new Review(snapshot.baseSha(), snapshot.headSha(), warnings.isEmpty() ? "ok" : "partial", files, warnings);
    }

    public EntityContext inspectEntity(String sha, String path, int line) {
        return inspect(sha, path, line).context();
    }

    public SymbolContext getSymbolContext(String sha, String path, int line) {
        var inspected = inspect(sha, path, line);
        var context = inspected.context();
        var lines = inspected.source().lines().toList();
        if (!context.lines().contains(line) || context.lines().endLine() > lines.size()) {
            throw new IllegalStateException("Adapter returned an invalid entity range for " + path);
        }
        var warnings = context.truncated() ? List.of(path + ": Call context truncated to analyzer limit.") : List.<String>of();
        return new SymbolContext(inspected.sha(), path, inspected.language(), warnings.isEmpty() ? "ok" : "partial",
                context.signature(), context.lines(),
                String.join("\n", lines.subList(context.lines().startLine() - 1, context.lines().endLine())),
                context.calls(), context.truncated(), warnings);
    }

    private record InspectedEntity(String sha, String language, String source, EntityContext context) {}

    private InspectedEntity inspect(String sha, String path, int line) {
        var language = languages.find(path).orElseThrow(() -> new IllegalArgumentException("Unsupported path: " + path));
        var commit = git.commit(sha);
        String source = git.source(commit, path);
        return new InspectedEntity(commit, language.languageId(), source, language.inspect(path, source, line));
    }

    private FileAnalysis analyzeFile(GitRepository.Snapshot snapshot, GitRepository.ChangedFile file,
                                     LanguageSupport language, List<String> warnings) {
        var change = git.ranges(snapshot, file);
        Version before = load(snapshot.baseSha(), change.oldPath(), "base", language, warnings);
        Version after = load(snapshot.headSha(), change.newPath(), "head", language, warnings);
        Set<String> touched = before.touched(change.baseLines());
        touched.addAll(after.touched(change.headLines()));
        var coverage = new Coverage(coverage(before, change.baseLines()), coverage(after, change.headLines()));

        List<Diagnostic> findings = new ArrayList<>();
        List<MetricComparison> metrics = new ArrayList<>();
        for (String signature : touched) {
            Map<String, MetricDefinition> definitions = new LinkedHashMap<>();
            language.metricDefinitions().forEach(definition -> definitions.put(definition.id(), definition));
            java.util.stream.Stream.concat(before.metrics.stream(), after.metrics.stream())
                    .filter(value -> value.entity().equals(signature))
                    .forEach(value -> definitions.putIfAbsent(value.metric().definition().id(), value.metric().definition()));
            for (var definition : definitions.values()) {
                metrics.add(MetricComparison.compare(signature, definition.id(),
                        before.metric(signature, definition), after.metric(signature, definition)));
            }
            if (before.entityCount(signature) > 1 || after.entityCount(signature) > 1) {
                warnings.add(file.path() + ": ambiguous entity signature " + signature);
                continue;
            }
            var oldRules = before.rules(signature);
            var newRules = after.rules(signature);
            Set<String> rules = new LinkedHashSet<>(oldRules.keySet());
            rules.addAll(newRules.keySet());
            for (String rule : rules) {
                var oldFinding = oldRules.get(rule);
                var newFinding = newRules.get(rule);
                String status;
                if (!before.complete || !after.complete) {
                    status = "UNVERIFIED";
                } else if (oldFinding == null) {
                    status = change.oldPath() == null || before.entityCount(signature) == 1
                            ? "INTRODUCED" : "NO_BASE_MATCH";
                } else if (newFinding == null) {
                    status = after.entityCount(signature) == 1 ? "RESOLVED" : "NO_HEAD_MATCH";
                } else {
                    status = oldFinding.message().equals(newFinding.message()) ? "EXISTING" : "CHANGED";
                }
                findings.add(new Diagnostic(signature, rule, status, oldFinding, newFinding));
            }
        }
        return new FileAnalysis(change.oldPath(), change.newPath(), language.languageId(), List.copyOf(touched), findings, metrics, coverage);
    }

    private static CoverageSide coverage(Version version, List<SourceRange> changes) {
        if (!version.complete()) { return CoverageSide.unknown(); }
        var entities = version.entities().stream().map(SourceEntity::lines)
                .sorted(java.util.Comparator.comparingInt(SourceRange::startLine)).toList();
        List<SourceRange> outside = new ArrayList<>();
        for (var change : changes) {
            int cursor = change.startLine();
            for (var entity : entities) {
                if (entity.endLine() < cursor) { continue; }
                if (entity.startLine() > change.endLine()) { break; }
                if (entity.startLine() > cursor) {
                    outside.add(new SourceRange(cursor, entity.startLine() - 1));
                }
                cursor = Math.max(cursor, entity.endLine() + 1);
                if (cursor > change.endLine()) { break; }
            }
            if (cursor <= change.endLine()) { outside.add(new SourceRange(cursor, change.endLine())); }
        }
        return new CoverageSide(outside.isEmpty() ? "COMPLETE" : "OUTSIDE_SUPPORTED_ENTITIES", List.copyOf(outside),
                outside.isEmpty() ? null : "Changed lines outside supported entity ranges; entity metrics do not cover these lines.");
    }

    private Version load(String sha, String path, String side, LanguageSupport language, List<String> warnings) {
        if (path == null) {
            return Version.empty(true);
        }
        String label = side + " " + path + ": ";
        try {
            String source = git.source(sha, path);
            var result = language.analyze(path, source);
            result.warnings().forEach(message -> warnings.add(label + message));
            if (!result.complete() && result.warnings().isEmpty()) {
                warnings.add(label + "Incomplete language analysis.");
            }
            return new Version(result.entities(), result.findings(), result.complete(), result.metrics());
        } catch (RuntimeException exception) {
            warnings.add(label + failure(exception));
            return Version.empty(false);
        }
    }

    private static String failure(RuntimeException exception) {
        return exception.getClass().getSimpleName()
                + (exception.getMessage() == null ? "" : ": " + exception.getMessage());
    }
}
