package dev.codeclarity;

import dev.codeclarity.languages.java.JdtLanguageServer;
import dev.codeclarity.languages.java.JavaLanguageSupport;
import dev.codeclarity.core.LanguageRegistry;
import dev.codeclarity.lsp.JsonRpcProcess;
import dev.codeclarity.lsp.LanguageServerClient;
import dev.codeclarity.lsp.LanguageServerSessions;
import dev.codeclarity.lsp.SemanticNavigationService;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Controlled protocol tests; the separate smoke script verifies real Eclipse JDT LS. */
public final class LspClientTest {
    public static void main(String[] args) throws Exception {
        var root = Path.of(args[2]);
        Files.createDirectories(root.resolve("src/main/java"));
        Files.createDirectories(root.resolve("src/test/java"));
        for (var mode : List.of("normal", "links", "stderr", "hang-init", "hang-request", "hang-write", "malformed", "eof")) {
            var pidPath = root.resolve(mode + ".pid");
            long start = System.nanoTime();
            boolean failed = false;
            try (var client = new JdtLanguageServer(root, List.of(args[0], args[1], mode, pidPath.toString()),
                    Duration.ofMillis(800), Duration.ofMillis(250))) {
                var uri = root.resolve("Main.java").toUri();
                var source = mode.equals("hang-write") ? "x".repeat(500000) : "class Main { /* π🚀 */ }";
                var values = client.definition(uri, source, new LanguageServerClient.Position(0, 6));
                check(values.size() == 1 && values.getFirst().uri().equals(uri), mode + " definition");
                check(values.getFirst().range().start().line() == 2 && values.getFirst().range().start().character() == 8,
                        "Location/LocationLink selection range");
                check(client.references(uri, source, new LanguageServerClient.Position(0, 6), true).size() == 1, "include declaration");
                check(client.references(uri, source, new LanguageServerClient.Position(0, 6), false).isEmpty(), "exclude declaration");
            } catch (JsonRpcProcess.Failure failure) {
                failed = true;
                if (mode.startsWith("hang")) { check(failure.timeout(), mode + " timeout classification"); }
            }
            boolean expected = !List.of("normal", "links", "stderr").contains(mode);
            check(failed == expected, mode + " expected failure=" + expected);
            check(Duration.ofNanos(System.nanoTime() - start).toSeconds() < 6, mode + " bounded completion");
            long pid = Long.parseLong(Files.readString(pidPath));
            check(ProcessHandle.of(pid).map(ProcessHandle::isAlive).orElse(false) == false, mode + " process leaked");
            if (!expected) {
                check(Files.exists(Path.of(pidPath + ".shutdown")) && Files.exists(Path.of(pidPath + ".exit")), "graceful lifecycle");
            }
        }
        var java = new JavaLanguageSupport();
        String source = "class Main { int answer() { return 42; } }";
        Files.writeString(root.resolve("Main.java"), source);
        var before = java.analyze("Main.java", source);
        var navigation = new SemanticNavigationService(root.toRealPath(), new LanguageRegistry(List.of(java)), Map.of("java",
                () -> new JdtLanguageServer(root, List.of(args[0], args[1], "hang-request", root.resolve("navigation.pid").toString()),
                        Duration.ofMillis(800), Duration.ofMillis(150))));
        var timedOut = navigation.definition("Main.java", 1, 7);
        check(timedOut.status().equals("timeout") && !timedOut.warnings().isEmpty() && timedOut.locations().isEmpty(), "optional timeout result");
        check(java.analyze("Main.java", source).equals(before) && before.metrics().size() == 6, "LSP timeout changed Java metrics");
        navigation.close();
        sessionReuse(root, args[0], args[1]);
        idleLifecycle();
        System.out.println("Passed: byte-framed duplex LSP, configuration callbacks, UTF-8, Location/LocationLink, references, "
                + "stderr draining, startup/request/write timeouts, EOF/malformed frames, process termination, metric isolation, "
                + "session reuse, fresh documents, serialized requests, crash/startup recovery and idle cleanup.");
    }

    private static void sessionReuse(Path root, String python, String peer) throws Exception {
        var starts = new AtomicInteger();
        var pids = new ArrayList<Long>();
        var registry = new LanguageRegistry(List.of(new JavaLanguageSupport()));
        var pidPath = root.resolve("reuse.pid");
        var navigation = new SemanticNavigationService(root.toRealPath(), registry, Map.of("java", () -> {
            starts.incrementAndGet();
            var client = new JdtLanguageServer(root, List.of(python, peer, "stateful", pidPath.toString()),
                    Duration.ofSeconds(2), Duration.ofMillis(750));
            pids.add(client.processId());
            return client;
        }));
        try {
            check(starts.get() == 0, "server starts lazily");
            check(navigation.definition("Main.java", 1, 7).status().equals("ok"), "first request");
            Files.writeString(root.resolve("Main.java"), "class Main { int changed() { return 17; } }");
            check(navigation.references("Main.java", 1, 7, true).status().equals("ok"), "second request");
            check(starts.get() == 1 && ProcessHandle.of(pids.getFirst()).orElseThrow().isAlive(), "reuse live server");
            Files.writeString(root.resolve("Other.java"), "class Other {}");
            try (var workers = Executors.newFixedThreadPool(4)) {
                var tasks = new ArrayList<java.util.concurrent.Future<?>>();
                for (int i = 0; i < 8; i++) {
                    String path = i % 2 == 0 ? "Main.java" : "Other.java";
                    tasks.add(workers.submit(() -> {
                        var result = navigation.definition(path, 1, 7);
                        check(result.status().equals("ok") && result.locations().getFirst().path().equals(path), "document isolation: " + result);
                    }));
                }
                for (var task : tasks) { task.get(5, TimeUnit.SECONDS); }
            }
            check(starts.get() == 1, "concurrent requests share server");
            var documents = Files.readAllLines(Path.of(pidPath + ".documents"));
            check(documents.size() == 10 && documents.get(1).contains("changed()"), "latest source delivered on reused session");
            var process = ProcessHandle.of(pids.getFirst()).orElseThrow();
            process.destroyForcibly();
            process.onExit().get(2, TimeUnit.SECONDS);
            check(!navigation.definition("Main.java", 1, 7).status().equals("ok"), "dead server reported");
            check(navigation.definition("Main.java", 1, 7).status().equals("ok") && starts.get() == 2, "next request restarts server");
        } finally { navigation.close(); }
        navigation.close();
        for (long pid : pids) { check(!ProcessHandle.of(pid).map(ProcessHandle::isAlive).orElse(false), "reused process leaked"); }
        check(Files.exists(Path.of(pidPath + ".shutdown")) && Files.exists(Path.of(pidPath + ".exit")), "reused graceful shutdown");
        check(!navigation.definition("Main.java", 1, 7).status().equals("ok") && starts.get() == 2, "closed service cannot restart");

        var attempts = new AtomicInteger();
        try (var recovering = new SemanticNavigationService(root.toRealPath(), registry, Map.of("java", () -> {
            if (attempts.incrementAndGet() == 1) { throw new JsonRpcProcess.Failure("deliberate startup failure", false); }
            return new JdtLanguageServer(root, List.of(python, peer, "stateful", root.resolve("recovered.pid").toString()),
                    Duration.ofSeconds(2), Duration.ofMillis(750));
        }))) {
            check(recovering.definition("Main.java", 1, 7).status().equals("unavailable"), "startup failure exposed");
            check(recovering.definition("Main.java", 1, 7).status().equals("ok") && attempts.get() == 2, "startup retry");
        }

        var timeoutStarts = new AtomicInteger();
        var timeoutPids = new ArrayList<Long>();
        try (var recovering = new SemanticNavigationService(root.toRealPath(), registry, Map.of("java", () -> {
            String mode = timeoutStarts.incrementAndGet() == 1 ? "hang-request" : "stateful";
            var client = new JdtLanguageServer(root, List.of(python, peer, mode, root.resolve("timeout-recovery.pid").toString()),
                    Duration.ofSeconds(2), Duration.ofMillis(150));
            timeoutPids.add(client.processId());
            return client;
        }))) {
            check(recovering.definition("Main.java", 1, 7).status().equals("timeout"), "request timeout exposed");
            check(!ProcessHandle.of(timeoutPids.getFirst()).map(ProcessHandle::isAlive).orElse(false), "timed out process discarded");
            check(recovering.definition("Main.java", 1, 7).status().equals("ok") && timeoutStarts.get() == 2, "timeout recovery");
            check(recovering.references("Main.java", 1, 7, true).status().equals("ok") && timeoutStarts.get() == 2, "recovered session reused");
        }
        for (long pid : timeoutPids) { check(!ProcessHandle.of(pid).map(ProcessHandle::isAlive).orElse(false), "recovery process leaked"); }
    }

    private static void idleLifecycle() throws Exception {
        var starts = new AtomicInteger();
        var closes = new AtomicInteger();
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        try (var sessions = new LanguageServerSessions(Map.of("java", () -> {
            starts.incrementAndGet();
            return new LanguageServerClient() {
                public List<Location> definition(java.net.URI uri, String source, Position position) { return List.of(); }
                public List<Location> references(java.net.URI uri, String source, Position position, boolean include) { return List.of(); }
                public void close() { closes.incrementAndGet(); }
            };
        }), Duration.ofMillis(80)); var worker = Executors.newSingleThreadExecutor()) {
            var active = worker.submit(() -> sessions.execute("java", client -> {
                entered.countDown();
                try { check(release.await(2, TimeUnit.SECONDS), "release active request"); }
                catch (InterruptedException e) { throw new AssertionError(e); }
                check(closes.get() == 0, "idle cleanup closed active request");
                return true;
            }));
            try {
                check(entered.await(2, TimeUnit.SECONDS), "active request entered");
                Thread.sleep(200);
                check(closes.get() == 0, "active session retained beyond idle duration");
            } finally { release.countDown(); }
            check(active.get(2, TimeUnit.SECONDS), "request completed");
            long deadline = System.nanoTime() + Duration.ofSeconds(3).toNanos();
            while (closes.get() == 0 && System.nanoTime() < deadline) { Thread.sleep(10); }
            check(closes.get() == 1, "idle session closed automatically");
            sessions.execute("java", client -> true);
            check(starts.get() == 2, "idle session recreated");
        }
        check(closes.get() == 2, "manager close cleans up remaining session");
    }
    private static void check(boolean condition, String message) { if (!condition) { throw new AssertionError(message); } }
}
