package dev.codeclarity.lsp;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.BiConsumer;
import java.util.function.BiFunction;

/** Bounded Content-Length JSON-RPC transport; independent of MCP and of a particular language server. */
public final class JsonRpcProcess implements AutoCloseable {
    public static final class Failure extends RuntimeException {
        private final boolean timeout;
        public Failure(String message, boolean timeout) { super(message); this.timeout = timeout; }
        public boolean timeout() { return timeout; }
    }
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final Map<Long, Process> ACTIVE = new ConcurrentHashMap<>();
    static {
        Runtime.getRuntime().addShutdownHook(new Thread(() -> ACTIVE.values().forEach(JsonRpcProcess::kill), "codeclarity-lsp-cleanup"));
    }
    private final Process process;
    private final ExecutorService readers = Executors.newVirtualThreadPerTaskExecutor();
    private final ExecutorService writer = Executors.newSingleThreadExecutor(Thread.ofVirtual().factory());
    private final Map<Long, CompletableFuture<JsonNode>> pending = new ConcurrentHashMap<>();
    private final AtomicLong sequence = new AtomicLong();
    private final StringBuilder stderr = new StringBuilder();
    private volatile boolean closed;

    public JsonRpcProcess(List<String> command, Path directory, BiFunction<String, JsonNode, Object> requests,
                          BiConsumer<String, JsonNode> notifications) {
        try {
            var builder = new ProcessBuilder(command).directory(directory.toFile());
            // JDT LS otherwise may inherit an editor's socket transport selection.
            builder.environment().keySet().removeIf(k -> k.startsWith("CLIENT_") || k.equals("SERVER_PORT"));
            process = builder.start();
        } catch (IOException exception) { readers.shutdownNow(); writer.shutdownNow(); throw new Failure("Cannot start LSP: " + exception.getMessage(), false); }
        ACTIVE.put(process.pid(), process);
        readers.submit(() -> {
            try {
                byte[] buffer = new byte[4096];
                int count;
                while ((count = process.getErrorStream().read(buffer)) >= 0) {
                    synchronized (stderr) {
                        stderr.append(new String(buffer, 0, count, StandardCharsets.UTF_8));
                        if (stderr.length() > 8192) { stderr.delete(0, stderr.length() - 8192); }
                    }
                }
            } catch (IOException ignored) { /* Process streams close during shutdown. */ }
        });
        readers.submit(() -> {
            try {
                while (!closed) {
                    JsonNode message = readFrame();
                    if (message.has("method")) {
                        String method = message.get("method").asString();
                        if (message.has("id")) {
                            Map<String, Object> reply = new LinkedHashMap<>();
                            reply.put("jsonrpc", "2.0");
                            reply.put("id", message.get("id"));
                            try { reply.put("result", requests.apply(method, message.get("params"))); }
                            catch (RuntimeException exception) { reply.put("error", Map.of("code", -32601, "message", exception.getMessage())); }
                            send(reply);
                        } else { notifications.accept(method, message.get("params")); }
                    } else if (message.has("id") && message.get("id").isNumber()) {
                        var future = pending.remove(message.get("id").asLong());
                        if (future != null) {
                            if (message.has("error")) { future.completeExceptionally(new Failure("LSP error: " + message.get("error"), false)); }
                            else { future.complete(message.get("result")); }
                        }
                    }
                }
            } catch (Exception exception) {
                var failure = new Failure("LSP stream closed/invalid: " + exception.getMessage(), false);
                pending.values().forEach(f -> f.completeExceptionally(failure));
                pending.clear();
            }
        });
    }

    public JsonNode request(String method, Object params, Duration timeout) {
        long id = sequence.incrementAndGet();
        var response = new CompletableFuture<JsonNode>();
        pending.put(id, response);
        long deadline = System.nanoTime() + timeout.toNanos();
        try {
            await(send(message(method, params, id)), remaining(deadline));
            return await(response, remaining(deadline));
        } finally { pending.remove(id); }
    }

    public void notify(String method, Object params, Duration timeout) { await(send(message(method, params, null)), timeout); }
    public long processId() { return process.pid(); }
    public String diagnostics() { synchronized (stderr) { return stderr.toString(); } }

    private static Map<String, Object> message(String method, Object params, Long id) {
        Map<String, Object> message = new LinkedHashMap<>();
        message.put("jsonrpc", "2.0"); message.put("method", method);
        if (params != null) { message.put("params", params); }
        if (id != null) { message.put("id", id); }
        return message;
    }

    private CompletableFuture<Void> send(Object message) {
        return CompletableFuture.runAsync(() -> {
            if (closed || !process.isAlive()) { throw new Failure("LSP process is not running.", false); }
            byte[] body = JSON.writeValueAsBytes(message);
            if (body.length > 8 * 1024 * 1024) { throw new Failure("LSP message exceeds 8 MiB.", false); }
            try {
                var output = process.getOutputStream();
                output.write(("Content-Length: " + body.length + "\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                output.write(body); output.flush();
            } catch (IOException exception) { throw new Failure("Cannot write LSP: " + exception.getMessage(), false); }
        }, writer);
    }

    private JsonNode readFrame() throws IOException {
        var input = process.getInputStream();
        var header = new StringBuilder();
        while (!header.toString().endsWith("\r\n\r\n")) {
            int value = input.read();
            if (value < 0) { throw new EOFException("LSP stdout EOF"); }
            header.append((char) value);
            if (header.length() > 8192) { throw new IOException("LSP header too large"); }
        }
        int length = -1;
        for (String line : header.toString().split("\r\n")) {
            if (line.toLowerCase(java.util.Locale.ROOT).startsWith("content-length:")) {
                if (length != -1) { throw new IOException("Duplicate Content-Length"); }
                length = Integer.parseInt(line.substring(line.indexOf(':') + 1).trim());
            }
        }
        if (length < 0 || length > 8 * 1024 * 1024) { throw new IOException("Invalid LSP Content-Length"); }
        byte[] body = input.readNBytes(length);
        if (body.length != length) { throw new EOFException("Incomplete LSP body"); }
        return JSON.readTree(body);
    }

    public static Duration remaining(long deadline) {
        long nanos = deadline - System.nanoTime();
        if (nanos <= 0) { throw new Failure("LSP timed out.", true); }
        return Duration.ofNanos(nanos);
    }

    public static <T> T await(CompletableFuture<T> future, Duration timeout) {
        try { return future.get(timeout.toNanos(), TimeUnit.NANOSECONDS); }
        catch (java.util.concurrent.TimeoutException exception) { throw new Failure("LSP timed out.", true); }
        catch (InterruptedException exception) { Thread.currentThread().interrupt(); throw new Failure("LSP interrupted.", false); }
        catch (java.util.concurrent.ExecutionException exception) {
            if (exception.getCause() instanceof Failure failure) { throw failure; }
            throw new Failure("LSP failed: " + exception.getCause().getMessage(), false);
        }
    }

    @Override public void close() {
        if (closed) { return; }
        try {
            if (process.isAlive()) {
                try { request("shutdown", null, Duration.ofMillis(750)); notify("exit", null, Duration.ofMillis(250)); }
                catch (RuntimeException ignored) { /* Force-stop unresponsive servers below. */ }
                if (!process.waitFor(750, TimeUnit.MILLISECONDS)) { kill(process); process.waitFor(1, TimeUnit.SECONDS); }
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        } finally {
            closed = true;
            if (process.isAlive()) { kill(process); }
            ACTIVE.remove(process.pid());
            pending.values().forEach(f -> f.completeExceptionally(new Failure("LSP closed.", false)));
            pending.clear();
            writer.shutdownNow(); readers.shutdownNow();
            try { process.getOutputStream().close(); process.getInputStream().close(); process.getErrorStream().close(); } catch (IOException ignored) {}
        }
    }

    private static void kill(Process process) {
        try { process.descendants().forEach(ProcessHandle::destroyForcibly); }
        catch (RuntimeException ignored) { /* Restricted platforms can forbid process enumeration. */ }
        finally { process.destroyForcibly(); }
    }
}
