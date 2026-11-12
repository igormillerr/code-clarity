package dev.codeclarity.lsp;

import dev.codeclarity.core.LanguageRegistry;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;

/** Optional WORKTREE navigation, deliberately outside the metric-analysis path. */
public final class SemanticNavigationService implements AutoCloseable {
    @FunctionalInterface public interface Factory extends java.util.function.Supplier<LanguageServerClient> {
        LanguageServerClient start();
        @Override default LanguageServerClient get() { return start(); }
    }
    public record Position(int line, int column) {}
    /** One-based UTF-16 positions; range end remains exclusive, as in LSP. */
    public record Range(Position start, Position end) {}
    public record Location(String uri, String path, boolean external, Range range) {}
    public record Result(String scope, String status, String language, String path, int line, int column,
                         List<Location> locations, List<String> warnings) {}
    private final Path root;
    private final LanguageRegistry languages;
    private final Map<String, Factory> providers;
    private final LanguageServerSessions sessions;

    public SemanticNavigationService(Path root, LanguageRegistry languages, Map<String, Factory> providers) {
        this(root, languages, providers, Duration.ofMinutes(2));
    }
    public SemanticNavigationService(Path root, LanguageRegistry languages, Map<String, Factory> providers, Duration idleTimeout) {
        this.root = root; this.languages = languages; this.providers = Map.copyOf(providers);
        this.sessions = new LanguageServerSessions(this.providers, idleTimeout);
    }
    public Result definition(String path, int line, int column) { return query(path, line, column, false, false); }
    public Result references(String path, int line, int column, boolean includeDeclaration) { return query(path, line, column, true, includeDeclaration); }

    private Result query(String path, int line, int column, boolean references, boolean includeDeclaration) {
        var language = languages.find(path).orElseThrow(() -> new IllegalArgumentException("Unsupported path: " + path)).languageId();
        Path document;
        String source;
        try {
            var relative = Path.of(path);
            if (relative.isAbsolute() || !root.resolve(relative).normalize().startsWith(root)) { throw new IllegalArgumentException("Expected repository-relative path."); }
            document = root.resolve(relative).toRealPath();
            if (!document.startsWith(root) || !Files.isRegularFile(document)) { throw new IllegalArgumentException("Document must be inside repository."); }
            if (Files.size(document) > 1_000_000) { throw new IllegalArgumentException("LSP document exceeds size limit."); }
            source = Files.readString(document, StandardCharsets.UTF_8);
            var lines = source.lines().toList();
            if (line < 1 || column < 1 || line > lines.size() || column > lines.get(line - 1).length() + 1) {
                throw new IllegalArgumentException("Expected a valid one-based line/UTF-16 column.");
            }
        } catch (IOException exception) { throw new IllegalArgumentException("Could not read LSP document: " + exception.getMessage(), exception); }
        if (!providers.containsKey(language)) { return result("unavailable", language, path, line, column, List.of(), "No LSP provider for " + language); }
        try {
            var position = new LanguageServerClient.Position(line - 1, column - 1);
            var locations = sessions.execute(language, client -> references
                    ? client.references(document.toUri(), source, position, includeDeclaration)
                    : client.definition(document.toUri(), source, position));
            return result("ok", language, path, line, column, locations.stream().map(this::location).distinct().toList(), null);
        } catch (JsonRpcProcess.Failure failure) {
            return result(failure.timeout() ? "timeout" : "unavailable", language, path, line, column, List.of(), failure.getMessage());
        } catch (RuntimeException exception) {
            return result("error", language, path, line, column, List.of(), "LSP failed: " + exception.getMessage());
        }
    }
    @Override public void close() { sessions.close(); }
    private Result result(String status, String language, String path, int line, int column, List<Location> locations, String warning) {
        return new Result("WORKTREE", status, language, path, line, column, locations, warning == null ? List.of() : List.of(warning));
    }
    private Location location(LanguageServerClient.Location value) {
        URI uri = value.uri();
        String path = null;
        boolean external = true;
        if (uri.getScheme().equalsIgnoreCase("file")) {
            var target = Path.of(uri).toAbsolutePath().normalize();
            external = !target.startsWith(root);
            path = (external ? target : root.relativize(target)).toString().replace(java.io.File.separatorChar, '/');
        }
        var start = value.range().start(); var end = value.range().end();
        return new Location(uri.toString(), path, external, new Range(new Position(start.line() + 1, start.character() + 1),
                new Position(end.line() + 1, end.character() + 1)));
    }
}
