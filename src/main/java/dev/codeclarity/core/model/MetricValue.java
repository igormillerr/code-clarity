package dev.codeclarity.core.model;

public record MetricValue(MetricDefinition definition, Status status, Double value, String reason) {
    public enum Status { AVAILABLE, UNSUPPORTED, MISSING, ERROR, ENTITY_ABSENT }

    public MetricValue {
        if (definition == null || status == null
                || (status == Status.AVAILABLE ? value == null || !Double.isFinite(value) : value != null)) {
            throw new IllegalArgumentException("Only available metrics must have a finite numeric value.");
        }
    }

    public static MetricValue available(MetricDefinition definition, double value) {
        return new MetricValue(definition, Status.AVAILABLE, value, null);
    }

    public static MetricValue unavailable(MetricDefinition definition, Status status, String reason) {
        return new MetricValue(definition, status, null, reason);
    }
}
