package dev.codeclarity.languages.java;

import java.util.List;
import net.sourceforge.pmd.lang.java.ast.ASTConstructorDeclaration;
import net.sourceforge.pmd.lang.java.ast.ASTExecutableDeclaration;
import net.sourceforge.pmd.lang.java.ast.ASTMethodDeclaration;
import net.sourceforge.pmd.lang.java.metrics.JavaMetrics;
import net.sourceforge.pmd.lang.java.rule.AbstractJavaRulechainRule;
import net.sourceforge.pmd.lang.metrics.MetricsUtil;
import net.sourceforge.pmd.lang.rule.Rule;

/** Collects numeric values in the same PMD pass as threshold diagnostics. */
final class PmdMetricRule extends AbstractJavaRulechainRule {
    record Values(int line, int column, Integer cyclomatic, Integer cognitive) {}
    private final List<Values> values;

    PmdMetricRule(List<Values> values) {
        super(ASTMethodDeclaration.class, ASTConstructorDeclaration.class);
        this.values = values;
        setLanguage(net.sourceforge.pmd.lang.LanguageRegistry.PMD.getLanguageById("java"));
        setName("CodeClarityMetrics");
        setMessage("Numeric metric collector");
        setDescription("Collect method metrics without reporting violations.");
    }

    @Override
    public Rule deepCopy() { return new PmdMetricRule(values); }

    @Override
    public Object visit(ASTMethodDeclaration node, Object data) { return collect(node, data); }

    @Override
    public Object visit(ASTConstructorDeclaration node, Object data) { return collect(node, data); }

    private Object collect(ASTExecutableDeclaration node, Object data) {
        var location = node.getReportLocation();
        values.add(new Values(location.getStartLine(), location.getStartColumn(),
                node.getBody() != null && JavaMetrics.CYCLO.supports(node) ? MetricsUtil.computeMetric(JavaMetrics.CYCLO, node) : null,
                node.getBody() != null && JavaMetrics.COGNITIVE_COMPLEXITY.supports(node)
                        ? MetricsUtil.computeMetric(JavaMetrics.COGNITIVE_COMPLEXITY, node) : null));
        return data;
    }
}
