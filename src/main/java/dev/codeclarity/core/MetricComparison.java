package dev.codeclarity.core;

import dev.codeclarity.core.model.MetricValue;

public record MetricComparison(String entity, String metric, String status,
                               MetricValue before, MetricValue after, Double delta) {
    public static MetricComparison compare(String entity, String metric, MetricValue before, MetricValue after) {
        if (before.status() != MetricValue.Status.AVAILABLE || after.status() != MetricValue.Status.AVAILABLE) {
            return new MetricComparison(entity, metric, "UNAVAILABLE", before, after, null);
        }
        if (!before.definition().equals(after.definition())) {
            return new MetricComparison(entity, metric, "INCOMPATIBLE", before, after, null);
        }
        return new MetricComparison(entity, metric, "COMPARED", before, after, after.value() - before.value());
    }
}
