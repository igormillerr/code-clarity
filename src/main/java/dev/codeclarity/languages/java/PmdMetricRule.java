package dev.codeclarity.languages.java;

import java.util.List;
import net.sourceforge.pmd.lang.java.ast.ASTConstructorDeclaration;
import net.sourceforge.pmd.lang.java.ast.ASTCompactConstructorDeclaration;
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
        super(ASTMethodDeclaration.class, ASTConstructorDeclaration.class, ASTCompactConstructorDeclaration.class);
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

    @Override
    public Object visit(ASTCompactConstructorDeclaration node, Object data) {
        // PMD's CYCLO and COGNITIVE_COMPLEXITY APIs require ASTExecutableDeclaration;
        // its compact record constructor node does not implement that interface.
        var location = node.getReportLocation();
        values.add(new Values(location.getStartLine(), location.getStartColumn(), null, null));
        return data;
    }

    private Object collect(ASTExecutableDeclaration node, Object data) {
        var location = node.getReportLocation();
        values.add(new Values(location.getStartLine(), location.getStartColumn(),
                node.getBody() != null && JavaMetrics.CYCLO.supports(node) ? MetricsUtil.computeMetric(JavaMetrics.CYCLO, node) : null,
                node.getBody() != null && JavaMetrics.COGNITIVE_COMPLEXITY.supports(node)
                        ? MetricsUtil.computeMetric(JavaMetrics.COGNITIVE_COMPLEXITY, node) : null));
        return data;
    }
}
