package dev.codeclarity.core.model;

/** Adapter-owned identity; matchingAmbiguous also covers an ambiguous enclosing declaration. */
public record SourceEntity(String signature, SourceRange lines, String matchingKey, boolean matchingAmbiguous) {
    public SourceEntity(String signature, SourceRange lines) {
        this(signature, lines, signature, false);
    }

    public SourceEntity(String signature, SourceRange lines, String matchingKey) {
        this(signature, lines, matchingKey, false);
    }

    public SourceEntity {
        if (matchingKey == null) {
            matchingKey = signature;
        }
    }
}
