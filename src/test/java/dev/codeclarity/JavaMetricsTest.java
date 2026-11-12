package dev.codeclarity;

import dev.codeclarity.languages.java.JavaLanguageSupport;
import dev.codeclarity.core.model.MetricValue;
import dev.codeclarity.core.LanguageSupport.AnalysisResult;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/** Runs against PMD itself, including below-threshold and ambiguous-line declarations. */
public final class JavaMetricsTest {
    public static void main(String[] args) {
        var language = new JavaLanguageSupport();
        check(language.metricDefinitions().stream().map(d -> d.id()).collect(Collectors.toSet()).equals(Set.of(
                "cyclomatic_complexity", "cognitive_complexity", "function_sloc", "max_nesting_depth",
                "parameter_count", "return_count")), "six unique metric definitions");
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
                check(definition.analyzer().matches("(pmd|javaparser)/[0-9].*")
                        && !definition.algorithm().isBlank(), "versioned analyzer and algorithm");
                if (!definition.analyzer().startsWith("pmd/")) { continue; }
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
        structuralMetrics(language);
        System.out.println("Passed: all six Java metrics, below-threshold values, comments/text blocks, nested scopes, "
                + "control nesting, parameters, constructors (including compact records), bodyless methods and versions.");
    }

    private static void structuralMetrics(JavaLanguageSupport language) {
        var result = language.analyze("Sample.java", """
                abstract class Sample {
                    /** documentation */
                    @Deprecated
                    int work(int first, String... rest) {
                        // comment-only line

                        String marker = "/* not a comment */"; /* real comment */
                        /* block comment
                           continued */
                        if (first > 0) {
                            for (String item : rest) {
                                if (item.isEmpty()) return first;
                            }
                        } else if (first < 0) {
                            return -1;
                        }
                        return 0;
                    }
                    abstract int absent(int count, String... names);
                    native void external();
                    void empty() {}
                    Sample(int x, String... names) { if (x < 0) return; }
                    int scopes() {
                        java.util.function.IntSupplier supplier = () -> { if (true) { return 9; } return 0; };
                        class Local { int inner() { if (true) { if (true) return 1; } return 0; } }
                        Object anonymous = new Object() { int inner() { if (true) return 1; return 0; } };
                        return 2;
                    }
                    void chain() { if (true) {} else if (false) {} else if (true) {} }
                    void blocks() { { { int value = 0; } } }
                }
                record Pair(int left, int right) {
                    Pair { if (left < 0) throw new IllegalArgumentException(); }
                }
                """);
        check(result.complete(), "complete structural fixture: " + result.warnings());
        for (var entity : result.entities()) {
            check(result.metrics().stream().filter(m -> m.entity().equals(entity.signature())).count() == 6,
                    "six measurements for " + entity.signature());
        }
        values(result, "Sample#work(int, String[])", Map.of(
                "function_sloc", 12, "parameter_count", 2, "return_count", 3, "max_nesting_depth", 3));
        values(result, "Sample#absent(int, String[])", Map.of("function_sloc", 1, "parameter_count", 2));
        values(result, "Sample#external()", Map.of("function_sloc", 1, "parameter_count", 0));
        for (var signature : Set.of("Sample#absent(int, String[])", "Sample#external()")) {
            for (var id : Set.of("cyclomatic_complexity", "cognitive_complexity", "max_nesting_depth", "return_count")) {
                var metric = metric(result, signature, id);
                check(metric.status() == MetricValue.Status.UNSUPPORTED && metric.value() == null
                        && metric.reason() != null, "bodyless " + signature + ": " + metric);
            }
        }
        values(result, "Sample#empty()", Map.of("function_sloc", 1, "parameter_count", 0,
                "return_count", 0, "max_nesting_depth", 0, "cyclomatic_complexity", 1, "cognitive_complexity", 0));
        values(result, "Sample#Sample(int, String[])", Map.of("parameter_count", 2, "return_count", 1, "max_nesting_depth", 1));
        values(result, "Sample#scopes()", Map.of("function_sloc", 6, "return_count", 1, "max_nesting_depth", 0));
        values(result, "Sample#chain()", Map.of("max_nesting_depth", 1));
        values(result, "Sample#blocks()", Map.of("max_nesting_depth", 0));
        values(result, "Pair#Pair(int, int)", Map.of("parameter_count", 2, "return_count", 0,
                "max_nesting_depth", 1));
        for (var id : Set.of("cyclomatic_complexity", "cognitive_complexity")) {
            check(metric(result, "Pair#Pair(int, int)", id).status() == MetricValue.Status.UNSUPPORTED,
                    "PMD does not expose compact constructors as executable declarations");
        }

        var controls = language.analyze("Controls.java", """
                class Controls {
                    int f(int x) {
                        try {
                            synchronized (this) {
                                while (x > 0) {
                                    do {
                                        switch (x) { case 1: return x; default: break; }
                                    } while (false);
                                }
                            }
                        } catch (RuntimeException e) {
                            if (x < 0) return -1;
                        } finally { x++; }
                        return switch (x) { case 0 -> 0; default -> 1; };
                    }
                }
                """);
        check(controls.complete(), "complete controls fixture");
        values(controls, "Controls#f(int)", Map.of("max_nesting_depth", 5, "return_count", 3));

        var text = language.analyze("Text.java", "class Text {\r\n"
                + "  String text() {\r\n    return \"\"\"\r\n      // literal\r\n\r\n      /* literal */\r\n"
                + "      \"\"\"; // comment\r\n  }\r\n}\r\n");
        check(text.complete(), "complete text block fixture");
        values(text, "Text#text()", Map.of("function_sloc", 6, "return_count", 1));
    }

    private static MetricValue metric(AnalysisResult result, String entity, String id) {
        return result.metrics().stream().filter(m -> m.entity().equals(entity) && m.metric().definition().id().equals(id))
                .findFirst().orElseThrow(() -> new AssertionError("Missing " + entity + "/" + id
                        + "; entities: " + result.entities())).metric();
    }

    private static void values(AnalysisResult result, String entity, Map<String, Integer> expected) {
        expected.forEach((id, value) -> {
            var metric = metric(result, entity, id);
            check(metric.status() == MetricValue.Status.AVAILABLE && metric.value() == value.doubleValue(),
                    entity + "/" + id + " expected " + value + ": " + metric);
        });
    }

    private static void check(boolean condition, String message) {
        if (!condition) { throw new AssertionError(message); }
    }
}
