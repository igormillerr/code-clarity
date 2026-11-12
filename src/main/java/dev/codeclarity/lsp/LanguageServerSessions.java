package dev.codeclarity.lsp;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;
import java.util.function.Supplier;

/** Owns lazy per-language sessions. Requests to one server are serialized, including document notifications. */
public final class LanguageServerSessions implements AutoCloseable {
    private final Map<String, ? extends Supplier<LanguageServerClient>> factories;
    private final Map<String, Session> sessions = new ConcurrentHashMap<>();
    private final ScheduledExecutorService cleanup;
    private final long idleNanos;
    private volatile boolean closed;

    private static final class Session {
        LanguageServerClient client;
        long lastUsed;

        void discard() {
            var previous = client;
            client = null;
            if (previous != null) {
                try { previous.close(); }
                catch (RuntimeException ignored) { /* A broken session must not prevent recovery or cleanup. */ }
            }
        }
    }

    public LanguageServerSessions(Map<String, ? extends Supplier<LanguageServerClient>> factories, Duration idleTimeout) {
        idleNanos = idleTimeout.toNanos();
        if (idleNanos <= 0) { throw new IllegalArgumentException("LSP idle timeout must be positive."); }
        this.factories = Map.copyOf(factories);
        cleanup = Executors.newSingleThreadScheduledExecutor(task -> {
            var thread = new Thread(task, "codeclarity-lsp-idle");
            thread.setDaemon(true);
            return thread;
        });
        cleanup.scheduleWithFixedDelay(this::expireIdle, idleNanos, idleNanos, TimeUnit.NANOSECONDS);
    }

    public <T> T execute(String language, Function<LanguageServerClient, T> operation) {
        if (closed) { throw new JsonRpcProcess.Failure("LSP sessions are closed.", false); }
        var factory = factories.get(language);
        if (factory == null) { throw new IllegalArgumentException("No LSP provider for " + language); }
        var session = sessions.computeIfAbsent(language, ignored -> new Session());
        synchronized (session) {
            if (closed) { throw new JsonRpcProcess.Failure("LSP sessions are closed.", false); }
            try {
                if (session.client == null) { session.client = factory.get(); }
                return operation.apply(session.client);
            } catch (RuntimeException exception) {
                // Do not retry the same request invisibly. The next request starts a fresh server.
                session.discard();
                throw exception;
            } finally { session.lastUsed = System.nanoTime(); }
        }
    }

    private void expireIdle() {
        for (var session : sessions.values()) {
            synchronized (session) {
                if (session.client != null && System.nanoTime() - session.lastUsed >= idleNanos) { session.discard(); }
            }
        }
    }

    @Override public void close() {
        closed = true;
        cleanup.shutdownNow();
        for (var session : sessions.values()) {
            synchronized (session) { session.discard(); }
        }
    }
}
