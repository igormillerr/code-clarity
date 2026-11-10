package dev.codeclarity.core;

import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.Finding;
import dev.codeclarity.core.model.SourceEntity;
import java.util.List;

/** Language tools and AST objects must stay behind this boundary. */
public interface LanguageSupport {
    String languageId();
    boolean supports(String path);
    AnalysisResult analyze(String path, String source);
    EntityContext inspect(String path, String source, int line);

    record AnalysisResult(List<SourceEntity> entities, List<Finding> findings,
                          boolean complete, List<String> warnings) {
        public AnalysisResult {
            entities = List.copyOf(entities);
            findings = List.copyOf(findings);
            warnings = List.copyOf(warnings);
        }
    }
}
