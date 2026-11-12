package dev.codeclarity.git;

import dev.codeclarity.core.model.SourceRange;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

public final class GitRepository {
    private static final int MAX_OUTPUT = 4 * 1024 * 1024;
    private static final int MAX_SOURCE_CHARS = 250_000;
    private static final Pattern SHA = Pattern.compile("[a-f0-9]{40}|[a-f0-9]{64}");
    private static final Pattern HUNK = Pattern.compile(
            "^@@ -(\\d+)(?:,(\\d+))? \\+(\\d+)(?:,(\\d+))? @@.*$", Pattern.MULTILINE);

    private final Path root;

    public GitRepository(Path path) throws IOException {
        root = path.toRealPath();
        if (!git("rev-parse", "--is-inside-work-tree").strip().equals("true")
                || !Path.of(git("rev-parse", "--show-toplevel").strip()).toRealPath().equals(root)) {
            throw new IllegalArgumentException("Specify the root of a Git working tree.");
        }
    }

    public record ChangedFile(String oldPath, String newPath) {
        public String path() {
            return newPath != null ? newPath : oldPath;
        }
    }

    public record Change(String oldPath, String newPath, List<SourceRange> baseLines, List<SourceRange> headLines) {}

    public record Snapshot(String baseSha, String headSha) {}

    public Snapshot snapshot(String baseRef, String headRef) {
        String head = resolve(headRef);
        String base = resolve(baseRef);
        return new Snapshot(git("merge-base", base, head).strip(), head);
    }

    public String commit(String sha) {
        if (!SHA.matcher(sha).matches() || !resolve(sha).equals(sha)) {
            throw new IllegalArgumentException("Expected a full Git commit SHA.");
        }
        return sha;
    }

    private String resolve(String ref) {
        return git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip();
    }

    public List<ChangedFile> changedFiles(Snapshot snapshot) {
        String status = git("diff", "--no-ext-diff", "--no-textconv", "--find-renames",
                "--name-status", "-z", snapshot.baseSha, snapshot.headSha, "--");
        if (status.isEmpty()) {
            return List.of();
        }
        String[] fields = status.split("\u0000");
        List<ChangedFile> files = new ArrayList<>();
        for (int i = 0; i < fields.length; ) {
            char kind = fields[i++].charAt(0);
            String path = fields[i++];
            String oldPath = kind == 'A' ? null : path;
            String newPath = switch (kind) {
                case 'D' -> null;
                case 'R', 'C' -> fields[i++];
                default -> path;
            };
            if (oldPath != null || newPath != null) {
                files.add(new ChangedFile(oldPath, newPath));
            }
        }
        return files;
    }

    public Change ranges(Snapshot snapshot, ChangedFile file) {
        String oldPath = file.oldPath();
        String newPath = file.newPath();
        List<SourceRange> before = new ArrayList<>();
        List<SourceRange> after = new ArrayList<>();
        if (oldPath == null) {
            addRange(after, 1, Math.toIntExact(source(snapshot.headSha, newPath).lines().count()));
        } else if (newPath == null) {
            addRange(before, 1, Math.toIntExact(source(snapshot.baseSha, oldPath).lines().count()));
        } else {
            String patch = git("diff", "--text", "--no-color", "--no-ext-diff", "--no-textconv", "--unified=0", "--inter-hunk-context=0",
                    snapshot.baseSha + ":" + oldPath, snapshot.headSha + ":" + newPath, "--");
            var matcher = HUNK.matcher(patch);
            while (matcher.find()) {
                addRange(before, Integer.parseInt(matcher.group(1)), count(matcher.group(2)));
                addRange(after, Integer.parseInt(matcher.group(3)), count(matcher.group(4)));
            }
        }
        return new Change(oldPath, newPath, before, after);
    }

    private static int count(String group) {
        return group == null ? 1 : Integer.parseInt(group);
    }

    private static void addRange(List<SourceRange> ranges, int start, int count) {
        if (count > 0) {
            ranges.add(new SourceRange(start, start + count - 1));
        }
    }

    public String source(String commit, String path) {
        if (path == null || path.isEmpty() || path.startsWith("/") || path.indexOf('\u0000') >= 0
                || Arrays.stream(path.split("/", -1)).anyMatch(part ->
                        part.isEmpty() || part.equals(".") || part.equals(".."))) {
            throw new IllegalArgumentException("Expected a repository-relative file path.");
        }
        String source = git("cat-file", "blob", commit + ":" + path);
        if (source.length() > MAX_SOURCE_CHARS) {
            throw new IllegalArgumentException("Source exceeds 250,000 characters: " + path);
        }
        return source;
    }

    private String git(String... arguments) {
        List<String> command = new ArrayList<>(List.of("git", "-C", root.toString(), "--no-pager"));
        command.addAll(List.of(arguments));
        var builder = new ProcessBuilder(command);
        builder.environment().keySet().removeIf(key -> key.startsWith("GIT_"));
        builder.environment().put("GIT_TERMINAL_PROMPT", "0");
        builder.environment().put("GIT_OPTIONAL_LOCKS", "0");
        builder.environment().put("LC_ALL", "C");
        try (var readers = Executors.newVirtualThreadPerTaskExecutor()) {
            Process process = builder.start();
            try {
                process.getOutputStream().close();
                var stdout = readers.submit(() -> {
                    byte[] output = process.getInputStream().readNBytes(MAX_OUTPUT + 1);
                    if (output.length > MAX_OUTPUT) {
                        process.destroyForcibly();
                        throw new IOException("Git output exceeded 4 MiB.");
                    }
                    return output;
                });
                var stderr = readers.submit(() -> process.getErrorStream().readNBytes(4096));
                if (!process.waitFor(15, TimeUnit.SECONDS)) {
                    throw new IOException("Git command timed out: " + arguments[0]);
                }
                byte[] output = stdout.get(2, TimeUnit.SECONDS);
                if (process.exitValue() != 0) {
                    throw new IllegalArgumentException("Git " + arguments[0] + ": "
                            + new String(stderr.get(2, TimeUnit.SECONDS), StandardCharsets.UTF_8).strip());
                }
                return StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(output)).toString();
            } finally {
                process.destroyForcibly();
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Git command interrupted.", exception);
        } catch (ExecutionException exception) {
            throw new IllegalArgumentException("Could not read Git output: " + exception.getCause().getMessage(), exception);
        } catch (IOException | java.util.concurrent.TimeoutException exception) {
            throw new IllegalArgumentException("Could not read Git data: " + exception.getMessage(), exception);
        }
    }
}
