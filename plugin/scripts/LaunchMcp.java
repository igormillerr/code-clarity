import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;

/** Packaging launcher only. Analysis and MCP remain in the team's supplied JAR. */
public final class LaunchMcp {
    public static void main(String[] args) throws IOException, InterruptedException {
        if (args.length == 0 || !Files.isRegularFile(Path.of(args[0]))) {
            System.err.println("CodeClarity launcher: supply an existing MCP JAR path.");
            System.exit(2);
        }
        String home = System.getProperty("user.home");
        String executable = System.getProperty("os.name").startsWith("Windows") ? "java.exe" : "java";
        var command = new ArrayList<String>();
        command.add(Path.of(System.getProperty("java.home"), "bin", executable).toString());
        command.add("-Duser.home=" + home);
        command.add("-jar");
        command.add(Path.of(args[0]).toAbsolutePath().toString());
        command.addAll(Arrays.asList(args).subList(1, args.length));
        var builder = new ProcessBuilder(command).inheritIO();

        // Explicit environment remains supported for CLI users. A local config
        // also works when the plugin host filters inherited custom variables.
        String selected = System.getenv("CODECLARITY_PYTHON");
        if (selected == null || selected.isBlank()) {
            Path config = Path.of(home, ".codeclarity", "python-path.txt");
            try {
                if (Files.isRegularFile(config)) {
                    if (Files.size(config) > 8192) {
                        throw new IOException("python-path.txt exceeds 8192 bytes");
                    }
                    selected = Files.readString(config, StandardCharsets.UTF_8).replaceFirst("^\\uFEFF", "").strip();
                    if (selected.isBlank() || selected.indexOf('\n') >= 0 || selected.indexOf('\r') >= 0
                            || !Path.of(selected).isAbsolute()) {
                        throw new IOException("python-path.txt must contain one absolute interpreter path");
                    }
                }
            } catch (IOException | RuntimeException error) {
                System.err.println("CodeClarity launcher: invalid Python configuration; using the server default. "
                        + error.getMessage());
                selected = null;
            }
        }
        if (selected != null && !selected.isBlank()) {
            builder.environment().put("CODECLARITY_PYTHON", selected);
        }
        forwardOptionalPath(builder, home, "CODECLARITY_JDTLS_HOME", "jdtls-home.txt");
        forwardOptionalPath(builder, home, "CODECLARITY_JDTLS_JAVA", "jdtls-java.txt");

        Process process = builder.start();
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            if (process.isAlive()) {
                process.destroy();
                try {
                    if (!process.waitFor(3, TimeUnit.SECONDS)) { process.destroyForcibly(); }
                } catch (InterruptedException error) {
                    process.destroyForcibly();
                    Thread.currentThread().interrupt();
                }
            }
        }, "codeclarity-launcher-shutdown"));
        try {
            System.exit(process.waitFor());
        } catch (InterruptedException error) {
            process.destroyForcibly();
            Thread.currentThread().interrupt();
            throw error;
        }
    }

    private static void forwardOptionalPath(ProcessBuilder builder, String home, String variable, String fileName) {
        String selected = System.getenv(variable);
        if (selected != null && !selected.isBlank()) { return; }
        Path config = Path.of(home, ".codeclarity", fileName);
        try {
            if (!Files.isRegularFile(config)) { return; }
            if (Files.size(config) > 8192) { throw new IOException(fileName + " exceeds 8192 bytes"); }
            selected = Files.readString(config, StandardCharsets.UTF_8).replaceFirst("^\\uFEFF", "").strip();
            if (selected.isBlank() || selected.indexOf('\n') >= 0 || selected.indexOf('\r') >= 0
                    || !Path.of(selected).isAbsolute()) {
                throw new IOException(fileName + " must contain one absolute path");
            }
            builder.environment().put(variable, selected);
        } catch (IOException | RuntimeException error) {
            System.err.println("CodeClarity launcher: invalid " + variable + " configuration; using the server default. "
                    + error.getMessage());
        }
    }
}
