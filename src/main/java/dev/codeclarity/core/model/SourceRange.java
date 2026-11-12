package dev.codeclarity.core.model;

public record SourceRange(int startLine, int endLine) {
    public SourceRange {
        if (startLine < 1 || endLine < startLine) {
            throw new IllegalArgumentException("Invalid source line range.");
        }
    }

    public boolean overlaps(SourceRange other) {
        return startLine <= other.endLine && other.startLine <= endLine;
    }

    public boolean contains(int line) {
        return startLine <= line && line <= endLine;
    }
}
