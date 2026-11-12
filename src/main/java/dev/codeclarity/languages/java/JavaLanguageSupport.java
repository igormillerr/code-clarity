package dev.codeclarity.languages.java;

import dev.codeclarity.core.LanguageSupport;
import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.SourceEntity;
import dev.codeclarity.core.model.MetricDefinition;
import dev.codeclarity.core.model.MetricMeasurement;
import dev.codeclarity.core.model.MetricValue;
import java.util.ArrayList;
import java.util.List;

public final class JavaLanguageSupport implements LanguageSupport {
    private final PmdAnalyzer pmd = new PmdAnalyzer();
    private static final MetricDefinition CYCLO = new MetricDefinition("cyclomatic_complexity", "java",
            "pmd/" + net.sourceforge.pmd.PMDVersion.VERSION, "pmd-java/CYCLO/default-options");
    private static final MetricDefinition COGNITIVE = new MetricDefinition("cognitive_complexity", "java",
            "pmd/" + net.sourceforge.pmd.PMDVersion.VERSION, "pmd-java/COGNITIVE_COMPLEXITY/default-options");

    @Override
    public List<MetricDefinition> metricDefinitions() {
        var definitions = new ArrayList<>(List.of(CYCLO, COGNITIVE));
        definitions.addAll(JavaParserMetrics.definitions());
        return List.copyOf(definitions);
    }

    @Override
    public String languageId() { return "java"; }

    @Override
    public boolean supports(String path) { return path != null && path.endsWith(".java"); }

    @Override
    public AnalysisResult analyze(String path, String source) {
        var methods = JavaSource.methods(source);
        var entities = methods.stream()
                .map(method -> new SourceEntity(method.signature(), method.lines())).toList();
        var result = pmd.analyze(path, source);
        List<MetricMeasurement> metrics = new ArrayList<>();
        for (var method : methods) {
            metrics.addAll(JavaParserMetrics.measure(method));
            var position = method.name().getBegin().orElseThrow();
            var matches = result.metrics().stream()
                    .filter(value -> value.line() == position.line && value.column() == position.column).toList();
            if (matches.size() == 1) {
                var values = matches.getFirst();
                metrics.add(new MetricMeasurement(method.signature(), metric(CYCLO, values.cyclomatic())));
                metrics.add(new MetricMeasurement(method.signature(), metric(COGNITIVE, values.cognitive())));
            }
        }
        return new AnalysisResult(entities, result.findings(), result.warnings().isEmpty(), result.warnings(), metrics);
    }

    private static MetricValue metric(MetricDefinition definition, Integer value) {
        return value == null
                ? MetricValue.unavailable(definition, MetricValue.Status.UNSUPPORTED, "PMD does not support this declaration.")
                : MetricValue.available(definition, value);
    }

    @Override
    public EntityContext inspect(String path, String source, int line) {
        return JavaSource.context(JavaSource.methodAt(JavaSource.methods(source), line));
    }
}
