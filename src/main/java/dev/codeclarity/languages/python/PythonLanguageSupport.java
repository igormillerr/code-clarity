package dev.codeclarity.languages.python;

import dev.codeclarity.core.LanguageSupport;
import dev.codeclarity.core.model.EntityContext;
import io.modelcontextprotocol.json.McpJsonDefaults;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Uses the Python standard library; repository code is parsed, never executed. */
public final class PythonLanguageSupport implements LanguageSupport {
    private static final int MAX_OUTPUT = 4 * 1024 * 1024;
    private final String executable;

    public PythonLanguageSupport() {
        this(System.getenv().getOrDefault("CODECLARITY_PYTHON", "python"));
    }

    public PythonLanguageSupport(String executable) {
        this.executable = executable;
    }

    public record Response(AnalysisResult analysis, EntityContext context, String error) {}

    @Override
    public String languageId() { return "python"; }

    @Override
    public boolean supports(String path) { return path != null && path.endsWith(".py"); }

    @Override
    public AnalysisResult analyze(String path, String source) {
        var response = invoke(Map.of("operation", "analyze", "path", path, "source", source));
        if (response.analysis() == null) {
            throw new IllegalArgumentException("Python analyzer returned no analysis.");
        }
        return response.analysis();
    }

    @Override
    public EntityContext inspect(String path, String source, int line) {
        var response = invoke(Map.of("operation", "inspect", "path", path, "source", source, "line", line));
        if (response.context() == null) {
            throw new IllegalArgumentException("Python analyzer returned no context.");
        }
        return response.context();
    }

    private Response invoke(Map<String, Object> request) {
        try (var readers = Executors.newVirtualThreadPerTaskExecutor();
             InputStream resource = PythonLanguageSupport.class.getResourceAsStream("/python_analyzer.py")) {
            if (resource == null) {
                throw new IllegalArgumentException("Missing Python analyzer resource.");
            }
            // Avoid Windows command-line quoting of embedded Python strings.
            String encoded = Base64.getEncoder().encodeToString(resource.readAllBytes());
            String bootstrap = "exec(compile(__import__('base64').b64decode('" + encoded
                    + "'),'<codeclarity-python>','exec'))";
            Process process = new ProcessBuilder(executable, "-I", "-X", "utf8", "-c", bootstrap).start();
            try {
                var stdout = readers.submit(() -> {
                    byte[] output = process.getInputStream().readNBytes(MAX_OUTPUT + 1);
                    if (output.length > MAX_OUTPUT) {
                        process.destroyForcibly();
                        throw new IOException("Python output exceeded 4 MiB.");
                    }
                    return output;
                });
                var stderr = readers.submit(() -> process.getErrorStream().readNBytes(4096));
                var writer = readers.submit(() -> {
                    try (var input = process.getOutputStream()) {
                        input.write(McpJsonDefaults.getMapper().writeValueAsString(request).getBytes(StandardCharsets.UTF_8));
                    }
                    return null;
                });
                if (!process.waitFor(15, TimeUnit.SECONDS)) {
                    throw new IOException("Python analysis timed out.");
                }
                writer.get(2, TimeUnit.SECONDS);
                if (process.exitValue() != 0) {
                    throw new IOException(new String(stderr.get(2, TimeUnit.SECONDS), StandardCharsets.UTF_8).strip());
                }
                var response = McpJsonDefaults.getMapper().readValue(
                        new String(stdout.get(2, TimeUnit.SECONDS), StandardCharsets.UTF_8), Response.class);
                if (response.error() != null) {
                    throw new IllegalArgumentException("Python analysis: " + response.error());
                }
                return response;
            } finally {
                process.destroyForcibly();
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalArgumentException("Python analysis interrupted.", exception);
        } catch (IOException | ExecutionException | TimeoutException exception) {
            throw new IllegalArgumentException("Could not run Python analyzer (" + executable
                    + "). Install Python 3.10+ or set CODECLARITY_PYTHON. " + exception.getMessage(), exception);
        }
    }
}
