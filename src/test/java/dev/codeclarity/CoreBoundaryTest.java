package dev.codeclarity;

import dev.codeclarity.core.AnalysisService;
import dev.codeclarity.core.LanguageRegistry;
import dev.codeclarity.core.LanguageSupport;
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
        public String languageId() { return "fixture"; }
        public boolean supports(String path) { return path.endsWith(".fixture"); }

        public AnalysisResult analyze(String path, String source) {
            var entity = new SourceEntity("opaque-key", new SourceRange(1, Math.toIntExact(source.lines().count())));
            var findings = source.contains("complex")
                    ? List.of(new Finding("branching", 1, 1, "complex")) : List.<Finding>of();
            return new AnalysisResult(List.of(entity), findings, !source.contains("incomplete"), List.of());
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

    private static void expectFailure(Runnable action) {
        try { action.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected rejection");
    }

    private static void check(boolean value, String message) {
        if (!value) { throw new AssertionError(message); }
    }
}
