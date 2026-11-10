package dev.codeclarity;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class CodeClarity {
    static final int MAX_ANALYSIS_FILES = 50;

    private final GitRepository git;
    private final PmdAnalyzer pmd = new PmdAnalyzer();

    CodeClarity(GitRepository git) {
        this.git = git;
    }

    record Changes(String baseSha, String headSha, List<GitRepository.Change> files) {}

    record Diagnostic(String method, String rule, String status, PmdAnalyzer.Finding before, PmdAnalyzer.Finding after) {}

    record FileAnalysis(String oldPath, String newPath, List<String> changedMethods, List<Diagnostic> findings) {}

    record Review(String baseSha, String headSha, String status, List<FileAnalysis> files, List<String> warnings) {}

    private record Version(List<JavaSource.Method> methods, List<PmdAnalyzer.Finding> findings, boolean complete) {
        static Version empty(boolean complete) {
            return new Version(List.of(), List.of(), complete);
        }

        Set<String> touched(List<GitRepository.Lines> ranges) {
            Set<String> signatures = new LinkedHashSet<>();
            for (var method : methods) {
                if (ranges.stream().anyMatch(method.lines()::overlaps)) {
                    signatures.add(method.signature());
                }
            }
            return signatures;
        }

        Map<String, PmdAnalyzer.Finding> rules(String signature) {
            Map<String, PmdAnalyzer.Finding> rules = new LinkedHashMap<>();
            var matches = methods.stream().filter(method -> method.signature().equals(signature)).toList();
            if (matches.size() == 1) {
                var method = matches.getFirst();
                for (var finding : findings) {
                    if (method.lines().contains(finding.line())) {
                        var owner = methods.stream()
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

        long methodCount(String signature) {
            return methods.stream().filter(method -> method.signature().equals(signature)).count();
        }
    }

    Changes listChanges(String baseRef, String headRef) {
        var snapshot = git.snapshot(baseRef, headRef);
        var changes = git.changedFiles(snapshot).stream().map(file -> git.ranges(snapshot, file)).toList();
        return new Changes(snapshot.baseSha(), snapshot.headSha(), changes);
    }

    Review analyzeChanges(String baseSha, String headSha, List<String> paths) {
        var snapshot = new GitRepository.Snapshot(git.commit(baseSha), git.commit(headSha));
        var changedFiles = git.changedFiles(snapshot);
        var selected = changedFiles.stream().filter(file -> paths.isEmpty() || paths.contains(file.path())).toList();
        var selectedPaths = selected.stream().map(GitRepository.ChangedFile::path).toList();
        if (!selectedPaths.containsAll(paths)) {
            throw new IllegalArgumentException("paths must identify changed Java files from list_java_changes.");
        }
        if (selected.size() > MAX_ANALYSIS_FILES) {
            throw new IllegalArgumentException("Analysis selected " + selected.size() + " changed Java files. "
                    + "Use paths to analyze up to " + MAX_ANALYSIS_FILES + " files per call with the same commit SHAs.");
        }

        List<FileAnalysis> files = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
        for (var file : selected) {
            files.add(analyzeFile(snapshot, file, warnings));
        }
        return new Review(baseSha, headSha, warnings.isEmpty() ? "ok" : "partial", files, warnings);
    }

    JavaSource.MethodContext inspectMethod(String sha, String path, int line) {
        String source = git.source(git.commit(sha), path);
        return JavaSource.context(JavaSource.methodAt(JavaSource.methods(source), line));
    }

    private FileAnalysis analyzeFile(GitRepository.Snapshot snapshot, GitRepository.ChangedFile file, List<String> warnings) {
        var change = git.ranges(snapshot, file);
        Version before = load(snapshot.baseSha(), change.oldPath(), "base", warnings);
        Version after = load(snapshot.headSha(), change.newPath(), "head", warnings);
        Set<String> touched = before.touched(change.baseLines());
        touched.addAll(after.touched(change.headLines()));

        List<Diagnostic> findings = new ArrayList<>();
        for (String signature : touched) {
            if (before.methodCount(signature) > 1 || after.methodCount(signature) > 1) {
                warnings.add(file.path() + ": ambiguous method signature " + signature);
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
                    status = change.oldPath() == null || before.methodCount(signature) == 1
                            ? "INTRODUCED" : "NO_BASE_MATCH";
                } else if (newFinding == null) {
                    status = after.methodCount(signature) == 1 ? "RESOLVED" : "NO_HEAD_MATCH";
                } else {
                    status = oldFinding.message().equals(newFinding.message()) ? "EXISTING" : "CHANGED";
                }
                findings.add(new Diagnostic(signature, rule, status, oldFinding, newFinding));
            }
        }
        return new FileAnalysis(change.oldPath(), change.newPath(), List.copyOf(touched), findings);
    }

    private Version load(String sha, String path, String side, List<String> warnings) {
        if (path == null) {
            return Version.empty(true);
        }
        String label = side + " " + path + ": ";
        try {
            String source = git.source(sha, path);
            var methods = JavaSource.methods(source);
            var result = pmd.analyze(path, source);
            result.warnings().forEach(message -> warnings.add(label + message));
            return new Version(methods, result.findings(), result.warnings().isEmpty());
        } catch (IllegalArgumentException exception) {
            warnings.add(label + exception.getMessage());
            return Version.empty(false);
        }
    }
}
