package dev.codeclarity.core.model;

/** Signature is an opaque matching key supplied by the language implementation. */
public record SourceEntity(String signature, SourceRange lines) {}
