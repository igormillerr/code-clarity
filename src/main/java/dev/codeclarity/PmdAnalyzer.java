package dev.codeclarity;

import net.sourceforge.pmd.PMDConfiguration;
import net.sourceforge.pmd.PmdAnalysis;
import net.sourceforge.pmd.lang.LanguageRegistry;
import net.sourceforge.pmd.lang.document.FileId;

import java.util.ArrayList;
import java.util.List;

final class PmdAnalyzer {
    record Finding(String rule, int line, int column, String message) {}

    record Result(List<Finding> findings, List<String> warnings) {}

    Result analyze(String path, String source) {
        PMDConfiguration config = new PMDConfiguration();
        config.setThreads(1);
        config.setIgnoreIncrementalAnalysis(true);
        config.setDefaultLanguageVersion(LanguageRegistry.PMD.getLanguageById("java").getVersion("21"));
        try (var analysis = PmdAnalysis.create(config)) {
            analysis.addRuleSet(analysis.newRuleSetLoader().loadFromResource("codeclarity-rules.xml"));
            if (!analysis.files().addSourceFile(FileId.fromPathLikeString(path), source)) {
                throw new IllegalArgumentException("PMD did not accept this Java source.");
            }
            var report = analysis.performAnalysisAndCollectReport();
            var findings = report.getViolations().stream()
                    .map(v -> new Finding(v.getRule().getName(), v.getBeginLine(), v.getBeginColumn(), v.getDescription()))
                    .toList();
            List<String> warnings = new ArrayList<>();
            report.getProcessingErrors().forEach(error -> warnings.add(error.getMsg()));
            report.getConfigurationErrors().forEach(error -> warnings.add(error.issue()));
            return new Result(findings, warnings);
        }
    }
}
