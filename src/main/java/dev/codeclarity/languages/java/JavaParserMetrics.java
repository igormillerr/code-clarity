package dev.codeclarity.languages.java;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.expr.LambdaExpr;
import com.github.javaparser.ast.expr.SwitchExpr;
import com.github.javaparser.ast.stmt.DoStmt;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.ForStmt;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.ReturnStmt;
import com.github.javaparser.ast.stmt.SwitchStmt;
import com.github.javaparser.ast.stmt.SynchronizedStmt;
import com.github.javaparser.ast.stmt.TryStmt;
import com.github.javaparser.ast.stmt.WhileStmt;
import dev.codeclarity.core.model.MetricDefinition;
import dev.codeclarity.core.model.MetricMeasurement;
import dev.codeclarity.core.model.MetricValue;

import java.io.IOException;
import java.util.HashSet;
import java.util.List;
import java.util.Properties;

/** Versioned lexical SLOC and executable-body metrics, independent of diagnostic thresholds. */
final class JavaParserMetrics {
    private static final String ANALYZER = "javaparser/" + parserVersion();
    private static final MetricDefinition SLOC = definition("function_sloc", "physical-code-lines/v1");
    private static final MetricDefinition NESTING = definition("max_nesting_depth", "control-nesting/v1");
    private static final MetricDefinition PARAMETERS = definition("parameter_count", "formal-parameters/v1");
    private static final MetricDefinition RETURNS = definition("return_count", "owned-return-statements/v1");

    static List<MetricDefinition> definitions() { return List.of(SLOC, NESTING, PARAMETERS, RETURNS); }

    static List<MetricMeasurement> measure(JavaSource.Method method) {
        var body = method.body();
        return List.of(
                measurement(method, MetricValue.available(SLOC, sloc(method.node()))),
                measurement(method, body == null ? noBody(NESTING) : MetricValue.available(NESTING, nesting(body, 0))),
                measurement(method, MetricValue.available(PARAMETERS, method.parameterCount())),
                measurement(method, body == null ? noBody(RETURNS) : MetricValue.available(RETURNS, returns(body))));
    }

    private static MetricMeasurement measurement(JavaSource.Method method, MetricValue metric) {
        return new MetricMeasurement(method.signature(), metric);
    }

    private static MetricValue noBody(MetricDefinition definition) {
        return MetricValue.unavailable(definition, MetricValue.Status.UNSUPPORTED, "Declaration has no body.");
    }

    private static MetricDefinition definition(String id, String algorithm) {
        return new MetricDefinition(id, "java", ANALYZER, "codeclarity/java/" + algorithm);
    }

    private static String parserVersion() {
        try (var stream = JavaParser.class.getResourceAsStream(
                "/META-INF/maven/com.github.javaparser/javaparser-core/pom.properties")) {
            if (stream == null) { throw new IllegalStateException("Missing JavaParser version metadata."); }
            var properties = new Properties();
            properties.load(stream);
            var version = properties.getProperty("version");
            if (version == null || version.isBlank()) { throw new IllegalStateException("Missing JavaParser version."); }
            return version;
        } catch (IOException exception) {
            throw new IllegalStateException("Could not read JavaParser version.", exception);
        }
    }

    private static int sloc(Node declaration) {
        var lines = new HashSet<Integer>();
        for (var token : declaration.getTokenRange().orElseThrow()) {
            if (token.getCategory().isWhitespaceOrComment()) { continue; }
            int line = token.getRange().orElseThrow().begin.line;
            // Token categories distinguish actual comments from comment markers inside strings/text blocks.
            for (var part : token.getText().split("\\R", -1)) {
                if (!part.isBlank()) { lines.add(line); }
                line++;
            }
        }
        return lines.size();
    }

    private static boolean separateScope(Node node) {
        // Includes local/anonymous class members and their initializers; lambda returns belong to the lambda.
        return node instanceof BodyDeclaration<?> || node instanceof LambdaExpr;
    }

    private static int returns(Node node) {
        if (separateScope(node)) { return 0; }
        int count = node instanceof ReturnStmt ? 1 : 0;
        for (var child : node.getChildNodes()) { count += returns(child); }
        return count;
    }

    private static int nesting(Node node, int depth) {
        if (separateScope(node)) { return depth; }
        boolean control = node instanceof IfStmt || node instanceof ForStmt || node instanceof ForEachStmt
                || node instanceof WhileStmt || node instanceof DoStmt || node instanceof SwitchStmt
                || node instanceof SwitchExpr || node instanceof TryStmt || node instanceof SynchronizedStmt;
        int current = depth + (control ? 1 : 0);
        int maximum = current;
        for (var child : node.getChildNodes()) {
            // An else-if is another alternative at the same nesting level.
            int childDepth = node instanceof IfStmt statement && child instanceof IfStmt
                    && statement.getElseStmt().orElse(null) == child ? depth : current;
            maximum = Math.max(maximum, nesting(child, childDepth));
        }
        return maximum;
    }
}
