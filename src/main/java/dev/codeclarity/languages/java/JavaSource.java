package dev.codeclarity.languages.java;

import dev.codeclarity.core.model.SourceRange;
import dev.codeclarity.core.model.EntityContext;
import dev.codeclarity.core.model.EntityContext.Call;
import dev.codeclarity.core.model.EntityContext.Guard;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.CallableDeclaration;
import com.github.javaparser.ast.body.CompactConstructorDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.EnumConstantDeclaration;
import com.github.javaparser.ast.body.InitializerDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.RecordDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.expr.SimpleName;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.IfStmt;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

final class JavaSource {
    record Method(String signature, SourceRange lines, Node node, SimpleName name,
                  BlockStmt body, int parameterCount) {}

    static List<Method> methods(String source) {
        var configuration = new ParserConfiguration().setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21)
                .setStoreTokens(true);
        var result = new JavaParser(configuration).parse(source);
        if (!result.isSuccessful()) {
            throw new IllegalArgumentException(result.getProblems().getFirst().getVerboseMessage());
        }
        var unit = result.getResult().orElseThrow();
        String packagePrefix = unit.getPackageDeclaration().map(p -> p.getNameAsString() + ".").orElse("");
        List<CallableDeclaration<?>> declarations = new ArrayList<>(unit.findAll(MethodDeclaration.class));
        declarations.addAll(unit.findAll(ConstructorDeclaration.class));
        List<Method> methods = new ArrayList<>();
        for (var node : declarations) {
            var body = node instanceof MethodDeclaration method ? method.getBody().orElse(null)
                    : ((ConstructorDeclaration) node).getBody();
            methods.add(method(packagePrefix, node, node.getSignature().asString(), node.getName(),
                    body, node.getParameters().size()));
        }
        for (var node : unit.findAll(CompactConstructorDeclaration.class)) {
            var record = (RecordDeclaration) node.getParentNode().orElseThrow();
            var canonical = new ConstructorDeclaration().setName(node.getNameAsString());
            record.getParameters().forEach(parameter -> canonical.addParameter(parameter.clone()));
            methods.add(method(packagePrefix, node, canonical.getSignature().asString(), node.getName(),
                    node.getBody(), record.getParameters().size()));
        }
        return methods.stream()
                .sorted(Comparator.comparing(method -> method.node.getBegin().orElseThrow()))
                .toList();
    }

    private static Method method(String prefix, Node node, String signature, SimpleName name,
                                 BlockStmt body, int parameters) {
        var range = node.getRange().orElseThrow();
        return new Method(prefix + owner(node) + "#" + signature,
                new SourceRange(range.begin.line, range.end.line), node, name, body, parameters);
    }

    private static String owner(Node node) {
        List<String> parts = new ArrayList<>();
        for (Node parent = node.getParentNode().orElse(null); parent != null;
                parent = parent.getParentNode().orElse(null)) {
            if (parent instanceof TypeDeclaration<?> type) {
                parts.addFirst(type.getNameAsString());
            } else if (parent instanceof ObjectCreationExpr creation && creation.getAnonymousClassBody().isPresent()) {
                parts.addFirst(anonymousOwner(creation));
            } else if (parent instanceof EnumConstantDeclaration constant) {
                parts.addFirst("enum(" + constant.getNameAsString() + ")");
            } else if (parent instanceof InitializerDeclaration initializer) {
                var siblings = initializer.getParentNode().orElseThrow().getChildNodes().stream()
                        .filter(candidate -> candidate instanceof InitializerDeclaration other
                                && other.isStatic() == initializer.isStatic()).toList();
                parts.addFirst((initializer.isStatic() ? "static-initializer(" : "initializer(")
                        + identityOrdinal(siblings, initializer) + ")");
            } else if (parent instanceof CallableDeclaration<?> enclosingMethod) {
                parts.addFirst(enclosingMethod.getSignature().asString());
            } else if (parent instanceof CompactConstructorDeclaration constructor) {
                parts.addFirst(constructor.getNameAsString());
            }
        }
        return String.join(".", parts);
    }

    private static Node anonymousAnchor(ObjectCreationExpr creation) {
        for (Node parent = creation.getParentNode().orElseThrow(); ; parent = parent.getParentNode().orElseThrow()) {
            if (parent instanceof VariableDeclarator || parent instanceof CallableDeclaration<?>
                    || parent instanceof CompactConstructorDeclaration || parent instanceof TypeDeclaration<?>
                    || parent instanceof InitializerDeclaration || parent instanceof EnumConstantDeclaration
                    || parent instanceof ObjectCreationExpr outer && outer.getAnonymousClassBody().isPresent()) {
                return parent;
            }
        }
    }

    private static String anonymousOwner(ObjectCreationExpr creation) {
        Node anchor = anonymousAnchor(creation);
        // A variable name survives edits and unrelated field insertions. Within an unlabelled
        // expression use lexical order, never absolute line numbers, to distinguish siblings.
        String label = anchor instanceof VariableDeclarator variable ? variableLabel(variable) : "expression";
        var siblings = anchor.findAll(ObjectCreationExpr.class).stream()
                .filter(candidate -> candidate.getAnonymousClassBody().isPresent() && anonymousAnchor(candidate) == anchor)
                .sorted(Comparator.comparing(candidate -> candidate.getBegin().orElseThrow())).toList();
        return "anonymous(" + label + ":" + identityOrdinal(siblings, creation) + ")";
    }

    private static Node lexicalScope(Node node) {
        for (Node parent = node.getParentNode().orElseThrow(); ; parent = parent.getParentNode().orElseThrow()) {
            if (parent instanceof CallableDeclaration<?> || parent instanceof CompactConstructorDeclaration
                    || parent instanceof TypeDeclaration<?> || parent instanceof InitializerDeclaration
                    || parent instanceof EnumConstantDeclaration
                    || parent instanceof ObjectCreationExpr creation && creation.getAnonymousClassBody().isPresent()) {
                return parent;
            }
        }
    }

    private static String variableLabel(VariableDeclarator variable) {
        var scope = lexicalScope(variable);
        var siblings = scope.findAll(VariableDeclarator.class).stream()
                .filter(candidate -> candidate.getNameAsString().equals(variable.getNameAsString())
                        && lexicalScope(candidate) == scope)
                .sorted(Comparator.comparing(candidate -> candidate.getBegin().orElseThrow())).toList();
        int ordinal = identityOrdinal(siblings, variable);
        return variable.getNameAsString() + (ordinal == 1 ? "" : "~" + ordinal);
    }

    private static int identityOrdinal(List<? extends Node> siblings, Node node) {
        for (int i = 0; i < siblings.size(); i++) {
            if (siblings.get(i) == node) { return i + 1; }
        }
        throw new IllegalStateException("Node missing from its lexical owner.");
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

    static EntityContext context(Method method) {
        var calls = method.node.findAll(MethodCallExpr.class).stream()
                .filter(call -> belongsTo(call, method.node))
                .limit(101)
                .map(call -> new Call(call.getBegin().orElseThrow().line, abbreviate(call.toString()), guards(call, method.node)))
                .toList();
        return new EntityContext(method.signature, method.lines, calls.stream().limit(100).toList(), calls.size() > 100);
    }

    private static boolean belongsTo(Node node, Node method) {
        for (Node parent = node.getParentNode().orElse(null); parent != null;
                parent = parent.getParentNode().orElse(null)) {
            if (parent instanceof CallableDeclaration<?> || parent instanceof CompactConstructorDeclaration) {
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
