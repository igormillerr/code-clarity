package dev.codeclarity.core.model;

/** Signature is opaque; an adapter can flag identities that are unsafe across snapshots. */
public record SourceEntity(String signature, SourceRange lines, String matchingWarning) {
    public SourceEntity(String signature, SourceRange lines) {
        this(signature, lines, null);
    }
}
