package dev.codeclarity;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.CallableDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.stmt.IfStmt;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

final class JavaSource {
    record Method(String signature, GitRepository.Lines lines, CallableDeclaration<?> node) {}

    record Guard(int line, String condition, String branch) {}

    record Call(int line, String expression, List<Guard> enclosingIfs) {}

    record MethodContext(String signature, GitRepository.Lines lines, List<Call> calls, boolean truncated) {}

    static List<Method> methods(String source) {
        var configuration = new ParserConfiguration().setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        var result = new JavaParser(configuration).parse(source);
        if (!result.isSuccessful()) {
            throw new IllegalArgumentException(result.getProblems().getFirst().getVerboseMessage());
        }
        var unit = result.getResult().orElseThrow();
        String packagePrefix = unit.getPackageDeclaration().map(p -> p.getNameAsString() + ".").orElse("");
        List<CallableDeclaration<?>> declarations = new ArrayList<>(unit.findAll(MethodDeclaration.class));
        declarations.addAll(unit.findAll(ConstructorDeclaration.class));
        return declarations.stream()
                .map(node -> {
                    var range = node.getRange().orElseThrow();
                    return new Method(packagePrefix + owner(node) + "#" + node.getSignature().asString(),
                            new GitRepository.Lines(range.begin.line, range.end.line), node);
                })
                .sorted(Comparator.comparing(method -> method.node.getBegin().orElseThrow()))
                .toList();
    }

    private static String owner(Node node) {
        List<String> parts = new ArrayList<>();
        for (Node parent = node.getParentNode().orElse(null); parent != null;
                parent = parent.getParentNode().orElse(null)) {
            if (parent instanceof TypeDeclaration<?> type) {
                parts.addFirst(type.getNameAsString());
            } else if (parent instanceof CallableDeclaration<?> enclosingMethod) {
                parts.addFirst(enclosingMethod.getSignature().asString());
            }
        }
        return String.join(".", parts);
    }

    static Method methodAt(List<Method> methods, int line) {
        var candidates = methods.stream()
                .filter(method -> method.lines.contains(line))
                .sorted(Comparator.comparingInt(method -> method.lines.endLine() - method.lines.startLine()))
                .toList();
        if (candidates.isEmpty()) {
            throw new IllegalArgumentException("No Java method or constructor contains line " + line + ".");
        }
        if (candidates.size() > 1 && candidates.get(0).lines.equals(candidates.get(1).lines)) {
            throw new IllegalArgumentException("Multiple declarations share that line; choose a more specific line.");
        }
        return candidates.getFirst();
    }

    static MethodContext context(Method method) {
        var calls = method.node.findAll(MethodCallExpr.class).stream()
                .filter(call -> belongsTo(call, method.node))
                .limit(101)
                .map(call -> new Call(call.getBegin().orElseThrow().line, abbreviate(call.toString()), guards(call, method.node)))
                .toList();
        return new MethodContext(method.signature, method.lines, calls.stream().limit(100).toList(), calls.size() > 100);
    }

    private static boolean belongsTo(Node node, Node method) {
        for (Node parent = node.getParentNode().orElse(null); parent != null;
                parent = parent.getParentNode().orElse(null)) {
            if (parent instanceof CallableDeclaration<?>) {
                return parent == method;
            }
        }
        return false;
    }

    private static List<Guard> guards(Node call, Node method) {
        List<Guard> guards = new ArrayList<>();
        Node child = call;
        for (Node parent = child.getParentNode().orElseThrow(); parent != method;
                parent = parent.getParentNode().orElseThrow()) {
            if (parent instanceof IfStmt statement && child != statement.getCondition()) {
                String branch = child == statement.getThenStmt() ? "then" : "else";
                guards.addFirst(new Guard(statement.getBegin().orElseThrow().line,
                        abbreviate(statement.getCondition().toString()), branch));
            }
            child = parent;
        }
        return guards;
    }

    private static String abbreviate(String text) {
        return text.length() <= 200 ? text : text.substring(0, 199) + "…";
    }
}
