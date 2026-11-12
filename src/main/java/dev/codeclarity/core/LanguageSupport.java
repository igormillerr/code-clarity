package dev.codeclarity.core;

import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.Finding;
import dev.codeclarity.core.model.SourceEntity;
import dev.codeclarity.core.model.MetricDefinition;
import dev.codeclarity.core.model.MetricMeasurement;
import java.util.List;

/** Language tools, AST objects and the meaning of entity matching keys stay behind this boundary. */
public interface LanguageSupport {
    String languageId();
    boolean supports(String path);
    AnalysisResult analyze(String path, String source);
    EntityContext inspect(String path, String source, int line);
    default List<MetricDefinition> metricDefinitions() { return List.of(); }

    /** complete is entity/finding coverage; a failed metric uses its own status and warnings. */
    record AnalysisResult(List<SourceEntity> entities, List<Finding> findings,
                          boolean complete, List<String> warnings, List<MetricMeasurement> metrics) {
        public AnalysisResult(List<SourceEntity> entities, List<Finding> findings,
                              boolean complete, List<String> warnings) {
            this(entities, findings, complete, warnings, List.of());
        }

        public AnalysisResult {
            entities = List.copyOf(entities);
            findings = List.copyOf(findings);
            warnings = List.copyOf(warnings);
            metrics = List.copyOf(metrics);
        }
    }
}
