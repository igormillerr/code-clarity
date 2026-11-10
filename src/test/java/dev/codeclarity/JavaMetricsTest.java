package dev.codeclarity;

import dev.codeclarity.languages.java.JavaLanguageSupport;
import dev.codeclarity.core.model.MetricValue;

/** Runs against PMD itself, including below-threshold and ambiguous-line declarations. */
public final class JavaMetricsTest {
    public static void main(String[] args) {
        var language = new JavaLanguageSupport();
        var result = language.analyze("Example.java", """
                abstract class Example {
                    Example() { if (true) {} }
                    @Deprecated
                    void annotated() { if (true) { if (true) {} } }
                    void one() {} void two() { if (true) {} }
                    abstract void absent();
                    void outer() { class Local { void inner() { if (true) {} } } }
                }
                """);
        if (!result.complete() || !result.warnings().isEmpty() || !result.findings().isEmpty()) {
            throw new AssertionError(result);
        }
        for (var entity : result.entities()) {
            for (var definition : language.metricDefinitions()) {
                var measurement = result.metrics().stream().filter(m -> m.entity().equals(entity.signature())
                        && m.metric().definition().id().equals(definition.id())).findFirst().orElseThrow();
                var metric = measurement.metric();
                if (entity.signature().endsWith("#absent()")) {
                    if (metric.status() != MetricValue.Status.UNSUPPORTED) { throw new AssertionError(metric); }
                } else {
                    boolean cognitive = definition.id().equals("cognitive_complexity");
                    double expected = entity.signature().endsWith("#annotated()") ? 3
                            : entity.signature().endsWith("#outer()") ? (cognitive ? 2 : 1)
                            : entity.signature().endsWith("#one()") ? (cognitive ? 0 : 1) : (cognitive ? 1 : 2);
                    if (metric.status() != MetricValue.Status.AVAILABLE || metric.value() != expected) {
                        throw new AssertionError(entity.signature() + " expected " + expected + ": " + metric);
                    }
                }
            }
        }
        System.out.println("Passed: PMD numeric metrics, constructors, annotations, same-line methods, nested and abstract methods.");
    }
}
