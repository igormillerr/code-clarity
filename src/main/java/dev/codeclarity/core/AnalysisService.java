package dev.codeclarity.core;

import dev.codeclarity.git.GitRepository;
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
    private final LanguageSupport language;

    public AnalysisService(GitRepository git, LanguageRegistry languages, String languageId) {
        this.git = git;
        this.language = languages.require(languageId);
    }

    public record Changes(String baseSha, String headSha, List<GitRepository.Change> files) {}

    public record Diagnostic(String method, String rule, String status, Finding before, Finding after) {}

    public record FileAnalysis(String oldPath, String newPath, List<String> changedMethods, List<Diagnostic> findings,
                               List<MetricComparison> metrics, List<EntityMatcher.Match> matches) {}

    public record Review(String baseSha, String headSha, String status, List<FileAnalysis> files, List<String> warnings) {}

    private record Version(List<SourceEntity> entities, List<Finding> findings, boolean complete, List<MetricMeasurement> metrics) {
        static Version empty(boolean complete) {
            return new Version(List.of(), List.of(), complete, List.of());
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

        MetricValue metric(List<SourceEntity> candidates, MetricDefinition definition) {
            if (!complete) {
                return MetricValue.unavailable(definition, ERROR, "Incomplete source analysis.");
            }
            int count = candidates.size();
            if (count == 0) {
                return MetricValue.unavailable(definition, ENTITY_ABSENT, "No matching entity in this version.");
            }
            if (count > 1 || candidates.stream().anyMatch(SourceEntity::matchingAmbiguous)) {
                return MetricValue.unavailable(definition, ERROR, "Ambiguous entity matching key.");
            }
            String entity = candidates.getFirst().signature();
            var values = metrics.stream().filter(value -> value.entity().equals(entity)
                    && value.metric().definition().id().equals(definition.id())).toList();
            if (values.size() != 1) {
                return MetricValue.unavailable(definition, values.isEmpty() ? MISSING : ERROR,
                        values.isEmpty() ? "Analyzer returned no measurement." : "Duplicate metric measurements.");
            }
            return values.getFirst().metric();
        }
    }

    private List<GitRepository.ChangedFile> changedFiles(GitRepository.Snapshot snapshot) {
        return git.changedFiles(snapshot).stream()
                .map(file -> new GitRepository.ChangedFile(
                        file.oldPath() != null && language.supports(file.oldPath()) ? file.oldPath() : null,
                        file.newPath() != null && language.supports(file.newPath()) ? file.newPath() : null))
                .filter(file -> file.oldPath() != null || file.newPath() != null)
                .toList();
    }

    public Changes listChanges(String baseRef, String headRef) {
        var snapshot = git.snapshot(baseRef, headRef);
        var changes = changedFiles(snapshot).stream().map(file -> git.ranges(snapshot, file)).toList();
        return new Changes(snapshot.baseSha(), snapshot.headSha(), changes);
    }

    public Review analyzeChanges(String baseSha, String headSha, List<String> paths) {
        var snapshot = new GitRepository.Snapshot(git.commit(baseSha), git.commit(headSha));
        var changedFiles = changedFiles(snapshot);
        var selected = changedFiles.stream().filter(file -> paths.isEmpty() || paths.contains(file.path())).toList();
        var selectedPaths = selected.stream().map(GitRepository.ChangedFile::path).toList();
        if (!selectedPaths.containsAll(paths)) {
            throw new IllegalArgumentException("paths must identify changed files for the selected language.");
        }
        if (selected.size() > MAX_ANALYSIS_FILES) {
            throw new IllegalArgumentException("Analysis selected " + selected.size() + " changed files. "
                    + "Use paths to analyze up to " + MAX_ANALYSIS_FILES + " files per call with the same commit SHAs.");
        }

        List<FileAnalysis> files = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        for (var file : selected) {
            files.add(analyzeFile(snapshot, file, warnings));
        }
        return new Review(baseSha, headSha, warnings.isEmpty() ? "ok" : "partial", files, warnings);
    }

    public EntityContext inspectEntity(String sha, String path, int line) {
        String source = git.source(git.commit(sha), path);
        if (!language.supports(path)) {
            throw new IllegalArgumentException("Unsupported path for " + language.languageId() + ": " + path);
        }
        return language.inspect(path, source, line);
    }

    private FileAnalysis analyzeFile(GitRepository.Snapshot snapshot, GitRepository.ChangedFile file, List<String> warnings) {
        var change = git.ranges(snapshot, file);
        Version before = load(snapshot.baseSha(), change.oldPath(), "base", warnings);
        Version after = load(snapshot.headSha(), change.newPath(), "head", warnings);
        var matches = EntityMatcher.match(before.entities, after.entities, change.baseLines(), change.headLines(),
                before.complete, after.complete);

        List<Diagnostic> findings = new ArrayList<>();
        List<MetricComparison> metrics = new ArrayList<>();
        for (var match : matches) {
            String signature = match.displaySignature();
            var oldSignature = match.before().size() == 1 ? match.before().getFirst().signature() : null;
            var newSignature = match.after().size() == 1 ? match.after().getFirst().signature() : null;
            Set<String> signatures = new LinkedHashSet<>();
            match.before().forEach(entity -> signatures.add(entity.signature()));
            match.after().forEach(entity -> signatures.add(entity.signature()));
            Map<String, MetricDefinition> definitions = new LinkedHashMap<>();
            language.metricDefinitions().forEach(definition -> definitions.put(definition.id(), definition));
            java.util.stream.Stream.concat(before.metrics.stream(), after.metrics.stream())
                    .filter(value -> signatures.contains(value.entity()))
                    .forEach(value -> definitions.putIfAbsent(value.metric().definition().id(), value.metric().definition()));
            for (var definition : definitions.values()) {
                metrics.add(MetricComparison.compare(signature, definition.id(),
                        before.metric(match.before(), definition), after.metric(match.after(), definition)));
            }
            if (match.status() == EntityMatcher.Status.AMBIGUOUS) {
                warnings.add(file.path() + ": ambiguous entity matching key " + match.key());
                continue;
            }
            var oldRules = oldSignature == null ? Map.<String, Finding>of() : before.rules(oldSignature);
            var newRules = newSignature == null ? Map.<String, Finding>of() : after.rules(newSignature);
            Set<String> rules = new LinkedHashSet<>(oldRules.keySet());
            rules.addAll(newRules.keySet());
            for (String rule : rules) {
                var oldFinding = oldRules.get(rule);
                var newFinding = newRules.get(rule);
                String status;
                if (!before.complete || !after.complete) {
                    status = "UNVERIFIED";
                } else if (oldFinding == null) {
                    status = change.oldPath() == null || !match.before().isEmpty()
                            ? "INTRODUCED" : "NO_BASE_MATCH";
                } else if (newFinding == null) {
                    status = !match.after().isEmpty() ? "RESOLVED" : "NO_HEAD_MATCH";
                } else {
                    status = oldFinding.message().equals(newFinding.message()) ? "EXISTING" : "CHANGED";
                }
                findings.add(new Diagnostic(signature, rule, status, oldFinding, newFinding));
            }
        }
        return new FileAnalysis(change.oldPath(), change.newPath(),
                matches.stream().map(EntityMatcher.Match::displaySignature).toList(), findings, metrics, matches);
    }

    private Version load(String sha, String path, String side, List<String> warnings) {
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
        } catch (IllegalArgumentException exception) {
            warnings.add(label + exception.getMessage());
            return Version.empty(false);
        }
    }
}
