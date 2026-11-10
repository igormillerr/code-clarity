package dev.codeclarity.core.model;

import java.util.List;

/** Syntactic context; enclosing conditions do not establish reachability. */
public record EntityContext(String signature, SourceRange lines, List<Call> calls, boolean truncated) {
    public record Guard(int line, String condition, String branch) {}
    public record Call(int line, String expression, List<Guard> enclosingIfs) {}
}
