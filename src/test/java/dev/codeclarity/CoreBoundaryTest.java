package dev.codeclarity;

import dev.codeclarity.core.AnalysisService;
import dev.codeclarity.core.LanguageRegistry;
import dev.codeclarity.core.LanguageSupport;
import dev.codeclarity.core.MetricComparison;
import dev.codeclarity.core.model.MetricDefinition;
import dev.codeclarity.core.model.MetricMeasurement;
import dev.codeclarity.core.model.MetricValue;
import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.Finding;
import dev.codeclarity.core.model.SourceEntity;
import dev.codeclarity.core.model.SourceRange;
import dev.codeclarity.git.GitRepository;
import java.nio.file.Path;
import java.util.List;

/** Integration checks compiled with only core + Git, without Java tooling dependencies. */
public final class CoreBoundaryTest {
    private static final class FixtureLanguage implements LanguageSupport {
        private final MetricDefinition score = new MetricDefinition("score", "fixture", "fixture/1", "score/v1");
        private final MetricDefinition missing = new MetricDefinition("missing", "fixture", "fixture/1", "missing/v1");
        private final MetricDefinition unsupported = new MetricDefinition("unsupported", "fixture", "fixture/1", "unsupported");
        public String languageId() { return "fixture"; }
        public boolean supports(String path) { return path.endsWith(".fixture"); }
        public List<MetricDefinition> metricDefinitions() { return List.of(score, missing, unsupported); }

        public AnalysisResult analyze(String path, String source) {
            var entity = new SourceEntity("opaque-key", new SourceRange(1, Math.toIntExact(source.lines().count())));
            var findings = source.contains("complex")
                    ? List.of(new Finding("branching", 1, 1, "complex")) : List.<Finding>of();
            return new AnalysisResult(List.of(entity), findings, !source.contains("incomplete"), List.of(), List.of(
                    new MetricMeasurement(entity.signature(), MetricValue.available(score, source.contains("complex") ? 10 : 1)),
                    new MetricMeasurement(entity.signature(), MetricValue.unavailable(unsupported,
                            MetricValue.Status.UNSUPPORTED, "Not supported."))));
        }

        public EntityContext inspect(String path, String source, int line) {
            return new EntityContext("opaque-key", new SourceRange(1, 1), List.of(), false);
        }
    }

    public static void main(String[] args) throws Exception {
        var git = new GitRepository(Path.of(args[0]));
        var language = new FixtureLanguage();
        var registry = new LanguageRegistry(List.of(language));
        var service = new AnalysisService(git, registry, "fixture");
        var changes = service.listChanges("main", "HEAD");
        check(git.changedFiles(new GitRepository.Snapshot(changes.baseSha(), changes.headSha())).stream()
                .anyMatch(file -> "ignored.txt".equals(file.path())), "Git must expose non-language files");
        check(git.source(changes.headSha(), "ignored.txt").contains("changed"), "Git must read non-Java files");
        check(changes.files().size() == 5, "language filtering");
        check(changes.files().stream().anyMatch(file -> file.oldPath() == null
                && "entered.fixture".equals(file.newPath())), "rename into language");
        check(changes.files().stream().anyMatch(file -> file.newPath() == null
                && "left.fixture".equals(file.oldPath())), "rename out of language");
        var review = service.analyzeChanges(changes.baseSha(), changes.headSha(), List.of());
        check(review.status().equals("partial"), "incomplete adapter result must make report partial");
        check(!review.warnings().isEmpty(), "incomplete result needs a warning");
        check(status(review, "changed.fixture").equals("INTRODUCED"), "new rule violation");
        check(status(review, "deleted.fixture").equals("RESOLVED"), "deletion-only edit");
        check(status(review, "incomplete.fixture").equals("UNVERIFIED"), "incomplete comparison");
        var numeric = metric(review, "changed.fixture", "score");
        check(numeric.before().value() == 1 && numeric.after().value() == 10 && numeric.delta() == 9, "positive delta");
        check(metric(review, "deleted.fixture", "score").delta() == -9, "deletion-only negative delta");
        check(metric(review, "entered.fixture", "score").before().status() == MetricValue.Status.ENTITY_ABSENT,
                "new entity has no fabricated zero baseline");
        check(metric(review, "left.fixture", "score").after().status() == MetricValue.Status.ENTITY_ABSENT,
                "removed entity has no fabricated zero head");
        check(metric(review, "changed.fixture", "missing").after().status() == MetricValue.Status.MISSING, "missing measurement");
        check(metric(review, "changed.fixture", "unsupported").after().status() == MetricValue.Status.UNSUPPORTED,
                "unsupported measurement");
        check(metric(review, "incomplete.fixture", "score").after().status() == MetricValue.Status.ERROR
                && metric(review, "incomplete.fixture", "score").delta() == null, "incomplete analysis has no delta");
        var v1 = MetricValue.available(language.score, 2);
        var v2 = MetricValue.available(new MetricDefinition("score", "fixture", "fixture/2", "score/v1"), 4);
        var incompatible = MetricComparison.compare("entity", "score", v1, v2);
        check(incompatible.status().equals("INCOMPATIBLE") && incompatible.delta() == null, "analyzer version mismatch");
        var otherAlgorithm = MetricValue.available(new MetricDefinition("score", "fixture", "fixture/1", "score/v2"), 4);
        check(MetricComparison.compare("entity", "score", v1, otherAlgorithm).delta() == null, "algorithm mismatch");
        check(MetricComparison.compare("entity", "score", v1, v1).delta() == 0, "unchanged metric");
        expectFailure(() -> MetricValue.available(language.score, Double.NaN));
        check(service.inspectEntity(changes.headSha(), "changed.fixture", 1).signature().equals("opaque-key"),
                "inspection delegated to language");
        expectFailure(() -> service.analyzeChanges(changes.baseSha(), changes.headSha(), List.of("ignored.txt")));
        expectFailure(() -> service.inspectEntity(changes.headSha(), "ignored.txt", 1));
        expectFailure(() -> registry.require("missing"));
        expectFailure(() -> new LanguageRegistry(List.of(language, language)));
        System.out.println("Passed: core without Java tooling, custom language, filtering, cross-extension renames, "
                + "deletion-only changes, incomplete results and inspection.");
    }

    private static String status(AnalysisService.Review review, String path) {
        return review.files().stream().filter(file -> path.equals(file.newPath())).findFirst().orElseThrow()
                .findings().getFirst().status();
    }

    private static MetricComparison metric(AnalysisService.Review review, String path, String id) {
        return review.files().stream().filter(file -> path.equals(file.newPath()) || path.equals(file.oldPath()))
                .findFirst().orElseThrow().metrics().stream().filter(value -> value.metric().equals(id)).findFirst().orElseThrow();
    }

    private static void expectFailure(Runnable action) {
        try { action.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected rejection");
    }

    private static void check(boolean value, String message) {
        if (!value) { throw new AssertionError(message); }
    }
}
