package dev.codeclarity;

import dev.codeclarity.core.AnalysisService;
import dev.codeclarity.core.LanguageRegistry;
import dev.codeclarity.core.LanguageSupport;
import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.Finding;
import dev.codeclarity.core.model.MetricDefinition;
import dev.codeclarity.core.model.MetricMeasurement;
import dev.codeclarity.core.model.MetricValue;
import dev.codeclarity.core.model.SourceEntity;
import dev.codeclarity.core.model.SourceRange;
import dev.codeclarity.git.GitRepository;

import java.nio.file.Path;
import java.util.List;

/** Exercises routing and failures using only core + Git, without either real language adapter. */
public final class CoreRoutingTest {
    private record FakeLanguage(String languageId, String extension) implements LanguageSupport {
        public boolean supports(String path) { return path.endsWith(extension); }
        public List<MetricDefinition> metricDefinitions() {
            return List.of(new MetricDefinition("score", languageId, "fake/1", "score/v1"));
        }
        public AnalysisResult analyze(String path, String source) {
            if (source.contains("crash")) { throw new IllegalStateException("Deliberate worker failure"); }
            var entity = new SourceEntity("shared-key", new SourceRange(1, 1));
            // Malformed output must be isolated even if it fails during comparison, after analyze() returned.
            var value = source.contains("malformed") ? null
                    : MetricValue.available(metricDefinitions().getFirst(), source.contains("complex") ? 9 : 1);
            return new AnalysisResult(List.of(entity), List.of(new Finding("rule", 1, 1, "finding")),
                    !source.contains("incomplete"), List.of(), List.of(new MetricMeasurement(entity.signature(), value)));
        }
        public EntityContext inspect(String path, String source, int line) {
            return new EntityContext(languageId, new SourceRange(1, 1), List.of(), false);
        }
    }

    public static void main(String[] args) throws Exception {
        var one = new FakeLanguage("one", ".one");
        var two = new FakeLanguage("two", ".two");
        var registry = new LanguageRegistry(List.of(one, two));
        check(registry.find("a.one").orElseThrow() == one && registry.find("b.two").orElseThrow() == two,
                "automatic routing");
        check(registry.find("ignored.txt").isEmpty() && registry.find(null).isEmpty(), "unsupported/absent side");
        var ambiguous = new LanguageRegistry(List.of(one, new FakeLanguage("overlap", ".one")));
        expectFailure(() -> ambiguous.find("a.one"));
        var service = new AnalysisService(new GitRepository(Path.of(args[0])), registry);
        var changes = service.listChanges("main", "HEAD");
        check(changes.status().equals("partial") && changes.warnings().stream().anyMatch(w -> w.contains("oversized.one")),
                "discovery retains file read failures");
        check(changes.files().size() == 8 && changes.files().stream().noneMatch(f -> "ignored.txt".equals(f.newPath())),
                "both languages and cross-language rename are discovered");
        var review = service.analyzeChanges(changes.baseSha(), changes.headSha(), List.of());
        check(review.status().equals("partial") && review.files().size() == 8, "all files retained on failure");
        for (var path : List.of("a-good.one", "z-good.two")) {
            var file = file(review, path);
            check(file.metrics().getFirst().delta() == 8 && !file.findings().isEmpty(), "healthy file: " + path);
            check(file.metrics().getFirst().after().definition().language().equals(file.language()), "language provenance");
        }
        check(file(review, "crash.one").metrics().getFirst().after().status() == MetricValue.Status.ERROR
                && file(review, "crash.one").metrics().getFirst().delta() == null, "crashed side cannot produce a delta");
        check(review.warnings().stream().anyMatch(w -> w.contains("crash.one") && w.contains("IllegalStateException")),
                "runtime failure warning");
        check(file(review, "malformed.one").metrics().isEmpty()
                && review.warnings().stream().anyMatch(w -> w.contains("malformed.one")), "comparison failure isolated");
        check(file(review, "oversized.one").metrics().isEmpty(), "range/read failure isolated");
        check(file(review, "incomplete.two").metrics().getFirst().after().status() == MetricValue.Status.ERROR
                && review.warnings().stream().anyMatch(w -> w.contains("incomplete.two")), "silent incomplete analysis");
        var removed = file(review, "cross.one").metrics().getFirst();
        var added = file(review, "cross.two").metrics().getFirst();
        check(removed.after().status() == MetricValue.Status.ENTITY_ABSENT && removed.delta() == null
                && added.before().status() == MetricValue.Status.ENTITY_ABSENT && added.delta() == null,
                "same signatures in different languages must not match");
        var selected = service.analyzeChanges(changes.baseSha(), changes.headSha(), List.of("a-good.one", "z-good.two"));
        check(selected.status().equals("ok") && selected.warnings().isEmpty() && selected.files().size() == 2,
                "healthy mixed batch is complete");
        check(service.analyzeChanges(changes.headSha(), changes.headSha(), List.of()).files().isEmpty(), "empty diff");
        check(service.inspectEntity(changes.headSha(), "a-good.one", 1).signature().equals("one")
                && service.inspectEntity(changes.headSha(), "z-good.two", 1).signature().equals("two"), "inspection routes by path");
        expectFailure(() -> service.inspectEntity(changes.headSha(), "ignored.txt", 1));
        expectFailure(() -> service.analyzeChanges(changes.baseSha(), changes.headSha(), List.of("ignored.txt")));
        System.out.println("Passed: automatic routing, mixed batches, cross-language rename, runtime/comparison/read failures, "
                + "partial status, retained healthy results and language-independent core.");
    }

    private static AnalysisService.FileAnalysis file(AnalysisService.Review review, String path) {
        return review.files().stream().filter(f -> path.equals(f.oldPath()) || path.equals(f.newPath())).findFirst().orElseThrow();
    }
    private static void check(boolean condition, String message) {
        if (!condition) { throw new AssertionError(message); }
    }
    private static void expectFailure(Runnable action) {
        try { action.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected failure");
    }
}
