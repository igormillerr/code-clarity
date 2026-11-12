package dev.codeclarity.core.model;

/** Adapter-owned identity; warnings preserve measurements but prevent unsafe snapshot comparisons. */
public record SourceEntity(String signature, SourceRange lines, String matchingKey, boolean matchingAmbiguous,
                           String matchingWarning) {
    public SourceEntity(String signature, SourceRange lines) {
        this(signature, lines, signature, false, null);
    }

    public SourceEntity(String signature, SourceRange lines, String matchingKey) {
        this(signature, lines, matchingKey, false, null);
    }

    public SourceEntity(String signature, SourceRange lines, String matchingKey, boolean matchingAmbiguous) {
        this(signature, lines, matchingKey, matchingAmbiguous, null);
    }

    public SourceEntity {
        if (matchingKey == null) {
            matchingKey = signature;
        }
    }
}
