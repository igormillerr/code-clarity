package dev.codeclarity.languages.java;

import dev.codeclarity.lsp.JsonRpcProcess;
import dev.codeclarity.lsp.LanguageServerClient;
import tools.jackson.databind.JsonNode;

import java.io.IOException;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/** Minimal read-only JDT LS session. Build-tool imports and automatic builds are disabled. */
public final class JdtLanguageServer implements LanguageServerClient {
    private final JsonRpcProcess connection;
    private final Duration requestTimeout;
    private Path temporary;
    private final Map<String, Object> capabilities;

    public static JdtLanguageServer open(Path root, Map<String, String> environment) {
        var homeText = environment.get("CODECLARITY_JDTLS_HOME");
        if (homeText == null || homeText.isBlank()) { throw new JsonRpcProcess.Failure("Set CODECLARITY_JDTLS_HOME to an extracted Eclipse JDT LS distribution.", false); }
        Path temporary = null;
        try {
            var home = Path.of(homeText).toRealPath();
            List<Path> launchers;
            try (var paths = Files.list(home.resolve("plugins"))) {
                launchers = paths.filter(p -> p.getFileName().toString().matches("org\\.eclipse\\.equinox\\.launcher(?:_.*)?\\.jar"))
                        .sorted().toList();
            }
            if (launchers.size() != 1) { throw new IOException("Expected one equinox launcher in " + home); }
            String os = System.getProperty("os.name").toLowerCase(java.util.Locale.ROOT);
            String platform = os.contains("mac") ? "mac" : os.contains("win") ? "win" : "linux";
            var shared = home.resolve("config_" + platform);
            if (!Files.isDirectory(shared)) { throw new IOException("Missing platform config " + shared); }
            temporary = Files.createTempDirectory("codeclarity-jdtls-");
            var command = new ArrayList<>(List.of(environment.getOrDefault("CODECLARITY_JDTLS_JAVA",
                    Path.of(System.getProperty("java.home"), "bin", platform.equals("win") ? "java.exe" : "java").toString()),
                    "-Declipse.application=org.eclipse.jdt.ls.core.id1", "-Dosgi.bundles.defaultStartLevel=4",
                    "-Declipse.product=org.eclipse.jdt.ls.core.product", "-Dosgi.checkConfiguration=true",
                    "-Dosgi.sharedConfiguration.area=" + shared.toUri(), "-Dosgi.sharedConfiguration.area.readOnly=true",
                    "-Dosgi.configuration.cascaded=true", "-Djdk.xml.maxGeneralEntitySizeLimit=0", "-Djdk.xml.totalEntitySizeLimit=0",
                    "-Xmx512m", "--add-modules=ALL-SYSTEM", "--add-opens", "java.base/java.util=ALL-UNNAMED",
                    "--add-opens", "java.base/java.lang=ALL-UNNAMED", "-jar", launchers.getFirst().toString(),
                    "-configuration", temporary.resolve("config").toString(), "-data", temporary.resolve("workspace").toString()));
            var session = new JdtLanguageServer(root, command, timeout(environment, "CODECLARITY_LSP_STARTUP_TIMEOUT_MS", 30000),
                    timeout(environment, "CODECLARITY_LSP_REQUEST_TIMEOUT_MS", 10000));
            session.temporary = temporary;
            return session;
        } catch (IOException | RuntimeException exception) {
            remove(temporary);
            if (exception instanceof JsonRpcProcess.Failure failure) { throw failure; }
            throw new JsonRpcProcess.Failure("Cannot start JDT LS: " + exception.getMessage(), false);
        }
    }

    /** Command injection here is for protocol tests/custom launchers; no shell is involved. */
    public JdtLanguageServer(Path root, List<String> command, Duration startupTimeout, Duration requestTimeout) {
        this.requestTimeout = requestTimeout;
        var ready = new CompletableFuture<Void>();
        var standardSources = List.of("src/main/java", "src/test/java").stream().filter(p -> Files.isDirectory(root.resolve(p))).toList();
        // Source roots must not nest: do not add src on top of Maven-style roots.
        var sources = standardSources.isEmpty() ? List.of(Files.isDirectory(root.resolve("src")) ? "src" : ".") : standardSources;
        var javaSettings = Map.of("import", Map.of("gradle", Map.of("enabled", false), "maven", Map.of("enabled", false),
                        "generatesMetadataFilesAtProjectRoot", false), "autobuild", Map.of("enabled", false),
                "configuration", Map.of("updateBuildConfiguration", "disabled"),
                "project", Map.of("sourcePaths", sources, "referencedLibraries", List.of()));
        var settings = Map.of("java", javaSettings);
        var folders = List.of(Map.of("uri", root.toUri().toString(), "name", root.getFileName().toString()));
        connection = new JsonRpcProcess(command, root, (method, params) -> switch (method) {
            case "workspace/configuration" -> {
                var values = new ArrayList<Object>();
                for (var item : params.get("items")) {
                    String section = item.has("section") ? item.get("section").asString() : "";
                    Object value = settings;
                    if (!section.isEmpty()) {
                        for (String part : section.split("\\.")) {
                            value = value instanceof Map<?, ?> map ? map.get(part) : null;
                        }
                    }
                    values.add(value);
                }
                yield values;
            }
            case "workspace/workspaceFolders" -> folders;
            case "client/registerCapability", "client/unregisterCapability", "window/workDoneProgress/create" -> null;
            case "workspace/applyEdit" -> Map.of("applied", false, "failureReason", "CodeClarity navigation is read-only.");
            default -> throw new IllegalArgumentException("Unsupported LSP server request: " + method);
        }, (method, params) -> {
            if (method.equals("language/status") && params != null && params.has("type")) {
                if (params.get("type").asString().equals("ServiceReady")) { ready.complete(null); }
                if (params.get("type").asString().equals("Error")) { ready.completeExceptionally(new JsonRpcProcess.Failure("JDT LS initialization: " + params, false)); }
            }
        });
        long deadline = System.nanoTime() + startupTimeout.toNanos();
        try {
            var result = connection.request("initialize", Map.of("processId", ProcessHandle.current().pid(),
                    "clientInfo", Map.of("name", "codeclarity", "version", "0.1.7"), "rootUri", root.toUri().toString(),
                    "workspaceFolders", folders, "capabilities", Map.of("workspace", Map.of("configuration", true,
                            "workspaceFolders", true, "applyEdit", false), "general", Map.of("positionEncodings", List.of("utf-16")),
                            "textDocument", Map.of("definition", Map.of("linkSupport", true))),
                    "initializationOptions", Map.of("settings", settings, "extendedClientCapabilities", Map.of("progressReportProvider", true))),
                    JsonRpcProcess.remaining(deadline));
            var caps = result.get("capabilities");
            if (caps == null) { throw new JsonRpcProcess.Failure("LSP initialize returned no capabilities.", false); }
            if (caps.has("positionEncoding") && !caps.get("positionEncoding").asString().equals("utf-16")) {
                throw new JsonRpcProcess.Failure("Unsupported LSP position encoding.", false);
            }
            capabilities = Map.of("definition", supported(caps.get("definitionProvider")), "references", supported(caps.get("referencesProvider")));
            connection.notify("initialized", Map.of(), JsonRpcProcess.remaining(deadline));
            JsonRpcProcess.await(ready, JsonRpcProcess.remaining(deadline));
        } catch (RuntimeException exception) {
            connection.close();
            throw new JsonRpcProcess.Failure(exception.getMessage() + " " + connection.diagnostics(),
                    exception instanceof JsonRpcProcess.Failure failure && failure.timeout());
        }
    }

    private static boolean supported(JsonNode value) { return value != null && !value.isNull() && (!value.isBoolean() || value.asBoolean()); }
    private static Duration timeout(Map<String, String> environment, String key, int fallback) {
        long millis = Long.parseLong(environment.getOrDefault(key, "" + fallback));
        if (millis < 100 || millis > 120000) { throw new IllegalArgumentException(key + " must be between 100 and 120000 ms."); }
        return Duration.ofMillis(millis);
    }

    @Override public List<Location> definition(URI document, String source, Position position) { return query("definition", document, source, position, false); }
    @Override public List<Location> references(URI document, String source, Position position, boolean includeDeclaration) {
        return query("references", document, source, position, includeDeclaration);
    }
    private List<Location> query(String operation, URI document, String source, Position position, boolean includeDeclaration) {
        if (!Boolean.TRUE.equals(capabilities.get(operation))) { throw new JsonRpcProcess.Failure("LSP does not support " + operation, false); }
        connection.notify("textDocument/didOpen", Map.of("textDocument", Map.of("uri", document.toString(), "languageId", "java", "version", 1, "text", source)), requestTimeout);
        RuntimeException queryFailure = null;
        try {
            var params = new java.util.LinkedHashMap<String, Object>();
            params.put("textDocument", Map.of("uri", document.toString())); params.put("position", position);
            if (operation.equals("references")) { params.put("context", Map.of("includeDeclaration", includeDeclaration)); }
            var result = connection.request("textDocument/" + operation, params, requestTimeout);
            if (result == null || result.isNull()) { return List.of(); }
            var values = new ArrayList<JsonNode>();
            if (result.isArray()) { result.forEach(values::add); } else { values.add(result); }
            return values.stream().map(value -> {
                var uri = value.get(value.has("targetUri") ? "targetUri" : "uri").asString();
                var range = value.get(value.has("targetSelectionRange") ? "targetSelectionRange" : "range");
                return new Location(URI.create(uri), new Range(position(range.get("start")), position(range.get("end"))));
            }).toList();
        } catch (RuntimeException exception) {
            queryFailure = exception;
            throw exception;
        } finally {
            try { connection.notify("textDocument/didClose", Map.of("textDocument", Map.of("uri", document.toString())), Duration.ofMillis(250)); }
            catch (RuntimeException exception) {
                if (queryFailure == null) { throw exception; }
                queryFailure.addSuppressed(exception);
            }
        }
    }
    private static Position position(JsonNode node) { return new Position(node.get("line").asInt(), node.get("character").asInt()); }
    public long processId() { return connection.processId(); }
    @Override public void close() { connection.close(); remove(temporary); }
    private static void remove(Path directory) {
        if (directory == null) { return; }
        try (var files = Files.walk(directory)) {
            for (var path : files.sorted(Comparator.reverseOrder()).toList()) { Files.deleteIfExists(path); }
        } catch (IOException ignored) { /* A locked cache must not break analysis or shutdown. */ }
    }
}
