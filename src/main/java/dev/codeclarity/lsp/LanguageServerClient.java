package dev.codeclarity.lsp;

import java.net.URI;
import java.util.List;

/** Language-neutral navigation boundary. Positions follow LSP: zero-based UTF-16, end-exclusive ranges. */
public interface LanguageServerClient extends AutoCloseable {
    record Position(int line, int character) {
        public Position { if (line < 0 || character < 0) { throw new IllegalArgumentException("Negative LSP position."); } }
    }
    record Range(Position start, Position end) {
        public Range {
            if (end.line() < start.line() || end.line() == start.line() && end.character() < start.character()) {
                throw new IllegalArgumentException("Invalid LSP range.");
            }
        }
    }
    record Location(URI uri, Range range) {}
    List<Location> definition(URI document, String source, Position position);
    List<Location> references(URI document, String source, Position position, boolean includeDeclaration);
    @Override void close();
}
