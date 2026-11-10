package dev.codeclarity.core.model;

/** Equality identifies compatible measurements, including analyzer and algorithm versions. */
public record MetricDefinition(String id, String language, String analyzer, String algorithm) {}
