package dev.codeclarity.languages.java;

import dev.codeclarity.core.LanguageSupport;
import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.SourceEntity;

public final class JavaLanguageSupport implements LanguageSupport {
    private final PmdAnalyzer pmd = new PmdAnalyzer();

    @Override
    public String languageId() { return "java"; }

    @Override
    public boolean supports(String path) { return path != null && path.endsWith(".java"); }

    @Override
    public AnalysisResult analyze(String path, String source) {
        var entities = JavaSource.methods(source).stream()
                .map(method -> new SourceEntity(method.signature(), method.lines())).toList();
        var result = pmd.analyze(path, source);
        return new AnalysisResult(entities, result.findings(), result.warnings().isEmpty(), result.warnings());
    }

    @Override
    public EntityContext inspect(String path, String source, int line) {
        return JavaSource.context(JavaSource.methodAt(JavaSource.methods(source), line));
    }
}
