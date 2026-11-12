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
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.function.Consumer;

/** Bounded file IO and locked read-modify-write transaction with atomic replacement. */
final class HistoryFileStorage {
    private static final int MAX_BYTES = 32 * 1024 * 1024;
    private final Path directory;
    private final Path file;
    private final HistoryValidator validator;

    HistoryFileStorage(Path root, HistoryValidator validator) {
        directory = root.resolve(".codeclarity");
        file = directory.resolve("review-history.json");
        this.validator = validator;
    }

    Map<String, Object> mutate(Consumer<Map<String, Object>> mutation) {
        try {
            safePaths();
            Files.createDirectories(directory);
            var lockPath = directory.resolve("review-history.lock");
            require(!Files.isSymbolicLink(lockPath), "History lock must not be a symlink.");
            try (var channel = FileChannel.open(lockPath, StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
                long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(15);
                while (true) {
                    java.nio.channels.FileLock lock = null;
                    try { lock = channel.tryLock(); }
                    catch (OverlappingFileLockException ignored) { /* Another thread in this JVM owns the same lock. */ }
                    if (lock != null) {
                        try {
                            var previous = read();
                            var next = copy(previous);
                            mutation.accept(next);
                            HistoryProjection.derive(next);
                            boolean changed = !next.equals(previous) || !Files.exists(file);
                            if (changed) {
                                next.put("revision", Math.incrementExact((Integer) previous.get("revision")));
                                validator.validateState(next);
                                write(next);
                            }
                            return Map.of("status", changed ? "saved" : "unchanged", "revision", next.get("revision"),
                                    "historyPath", ".codeclarity/review-history.json", "statistics", next.get("statistics"));
                        } finally { lock.release(); }
                    }
                    require(System.nanoTime() < deadline, "Timed out waiting for review history lock.");
                    Thread.sleep(25);
                }
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Review history update interrupted.", exception);
        } catch (IOException exception) {
            throw new IllegalStateException("Could not save review history: " + exception.getMessage(), exception);
        }
    }

    Map<String, Object> read() throws IOException {
        safePaths();
        if (Files.notExists(file, LinkOption.NOFOLLOW_LINKS)) {
            var empty = new LinkedHashMap<String, Object>();
            empty.put("schemaVersion", 1);
            empty.put("revision", 0);
            for (var name : List.of("reviews", "categories", "findings", "feedback", "ruleCandidates")) {
                empty.put(name, new ArrayList<>());
            }
            HistoryProjection.derive(empty);
            return empty;
        }
        try (var channel = FileChannel.open(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            require(channel.size() <= MAX_BYTES, "Review history exceeds 32 MiB.");
            var bytes = java.nio.channels.Channels.newInputStream(channel).readNBytes(MAX_BYTES + 1);
            require(bytes.length <= MAX_BYTES, "Review history exceeds 32 MiB.");
            var history = object(JSON.readValue(bytes, Map.class));
            validator.validateState(history);
            return history;
        }
    }

    private void write(Map<String, Object> history) throws IOException {
        byte[] bytes = JSON.writerWithDefaultPrettyPrinter().writeValueAsBytes(history);
        require(bytes.length <= MAX_BYTES, "Review history exceeds 32 MiB.");
        validator.validateState(object(JSON.readValue(bytes, Map.class)));
        Path temporary = Files.createTempFile(directory, "review-history-", ".tmp");
        try {
            try (var channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
                var buffer = ByteBuffer.wrap(bytes);
                while (buffer.hasRemaining()) { channel.write(buffer); }
                channel.force(true);
            }
            Files.move(temporary, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temporary); }
    }

    private void safePaths() {
        require(!Files.isSymbolicLink(directory) && !Files.isSymbolicLink(file), "History paths must not be symlinks.");
    }

}
