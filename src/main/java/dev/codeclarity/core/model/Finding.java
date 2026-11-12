package dev.codeclarity.core.model;

/** A rule violation, not a numeric metric. */
public record Finding(String rule, int line, int column, String message) {}
