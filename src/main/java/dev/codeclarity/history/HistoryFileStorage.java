package dev.codeclarity.history;

import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static dev.codeclarity.history.HistoryJson.*;

import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.AccessDeniedException;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.FileSystemException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/** Bounded file IO and locked read-modify-write transaction with atomic replacement. */
final class HistoryFileStorage {
    private static final int MAX_BYTES = 32 * 1024 * 1024;
    private final Path root;
    private final Path directory;
    private final Path file;
    private final Path lockFile;
    private final HistoryValidator validator;

    HistoryFileStorage(Path root, HistoryValidator validator) {
        this.root = root;
        directory = root.resolve(".codeclarity");
        file = directory.resolve("review-history.json");
        lockFile = directory.resolve("review-history.lock");
        this.validator = validator;
    }

    Map<String, Object> mutate(Consumer<Map<String, Object>> mutation) {
        try {
            return locked(() -> {
                var previous = readUnlocked();
                var next = copy(previous);
                mutation.accept(next);
                HistoryProjection.derive(next);
                boolean changed = !next.equals(previous) || !Files.exists(file, LinkOption.NOFOLLOW_LINKS);
                if (changed) {
                    next.put("revision", Math.incrementExact((Integer) previous.get("revision")));
                    validator.validateState(next);
                    write(next);
                }
                return Map.of("status", changed ? "saved" : "unchanged", "revision", next.get("revision"),
                        "historyPath", ".codeclarity/review-history.json", "statistics", next.get("statistics"));
            });
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Review history update interrupted.", exception);
        } catch (IOException exception) {
            throw new IllegalStateException("Could not save review history: " + exception.getMessage(), exception);
        }
    }

    Map<String, Object> read() throws IOException {
        safePaths();
        // An empty read must not create a storage directory. Once it exists, readers use
        // the writer lock: an open Windows read handle can otherwise prevent replacement.
        if (Files.notExists(directory, LinkOption.NOFOLLOW_LINKS)) { return empty(); }
        try { return locked(this::readUnlocked); }
        catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IOException("Review history read interrupted.", exception);
        }
    }

    private Map<String, Object> readUnlocked() throws IOException {
        safePaths();
        if (Files.notExists(file, LinkOption.NOFOLLOW_LINKS)) {
            return empty();
        }
        byte[] bytes;
        try (var channel = FileChannel.open(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            safePaths();
            require(channel.size() <= MAX_BYTES, "Review history exceeds 32 MiB.");
            bytes = java.nio.channels.Channels.newInputStream(channel).readNBytes(MAX_BYTES + 1);
            require(bytes.length <= MAX_BYTES, "Review history exceeds 32 MiB.");
        }
        var history = object(JSON.readValue(bytes, Map.class));
        validator.validateState(history);
        return history;
    }

    private Map<String, Object> empty() {
        var empty = new LinkedHashMap<String, Object>();
        empty.put("schemaVersion", 1);
        empty.put("revision", 0);
        for (var name : List.of("reviews", "categories", "findings", "feedback", "ruleCandidates")) {
            empty.put(name, new ArrayList<>());
        }
        HistoryProjection.derive(empty);
        return empty;
    }

    private <T> T locked(IOOperation<T> operation) throws IOException, InterruptedException {
        safePaths();
        try { Files.createDirectory(directory); }
        catch (FileAlreadyExistsException ignored) { /* Validate the existing path below. */ }
        safePaths();
        try (var channel = FileChannel.open(lockFile, StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
            while (true) {
                java.nio.channels.FileLock lock = null;
                try { lock = channel.tryLock(); }
                catch (OverlappingFileLockException ignored) { /* Another thread in this JVM owns the same lock. */ }
                if (lock != null) {
                    try {
                        safePaths();
                        return operation.run();
                    } finally { lock.release(); }
                }
                require(System.nanoTime() < deadline, "Timed out waiting for review history lock.");
                Thread.sleep(25);
            }
        }
    }

    private void write(Map<String, Object> history) throws IOException, InterruptedException {
        byte[] bytes = JSON.writerWithDefaultPrettyPrinter().writeValueAsBytes(history);
        require(bytes.length <= MAX_BYTES, "Review history exceeds 32 MiB.");
        validator.validateState(object(JSON.readValue(bytes, Map.class)));
        safePaths();
        Path temporary = Files.createTempFile(directory, "review-history-", ".tmp");
        try {
            safePaths();
            safePath(temporary, false);
            try (var channel = FileChannel.open(temporary, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
                var buffer = ByteBuffer.wrap(bytes);
                while (buffer.hasRemaining()) { channel.write(buffer); }
                channel.force(true);
            }
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
            while (true) {
                safePaths();
                safePath(temporary, false);
                try {
                    Files.move(temporary, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
                    break;
                } catch (FileSystemException exception) {
                    if (!windowsSharingFailure(exception) || System.nanoTime() >= deadline) { throw exception; }
                    Thread.sleep(25);
                }
            }
        } finally { Files.deleteIfExists(temporary); }
    }

    private boolean windowsSharingFailure(FileSystemException exception) {
        if (!System.getProperty("os.name", "").startsWith("Windows")) { return false; }
        if (exception instanceof AccessDeniedException) { return true; }
        var reason = String.valueOf(exception.getReason()).toLowerCase(Locale.ROOT);
        return reason.contains("another process") || reason.contains("другим процессом");
    }

    private void safePaths() throws IOException {
        require(Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS) && root.toRealPath().equals(root),
                "Repository path must remain canonical.");
        safePath(directory, true);
        safePath(file, false);
        safePath(lockFile, false);
    }

    private void safePath(Path path, boolean isDirectory) throws IOException {
        BasicFileAttributes attributes;
        try { attributes = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); }
        catch (NoSuchFileException ignored) { return; }
        require(!attributes.isSymbolicLink() && path.toRealPath().equals(path),
                "History paths must not be symlinks, junctions or other redirected paths.");
        require(isDirectory ? attributes.isDirectory() : attributes.isRegularFile(),
                "History path has an unexpected file type: " + path.getFileName());
    }

    @FunctionalInterface
    private interface IOOperation<T> {
        T run() throws IOException, InterruptedException;
    }
}
