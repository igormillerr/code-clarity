package dev.codeclarity;

import dev.codeclarity.core.AnalysisService;
import dev.codeclarity.core.LanguageRegistry;
import dev.codeclarity.git.GitRepository;
import dev.codeclarity.languages.java.JavaLanguageSupport;

import io.modelcontextprotocol.json.McpJsonDefaults;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.server.transport.StdioServerTransportProvider;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.ServerCapabilities;
import io.modelcontextprotocol.spec.McpSchema.Tool;
import io.modelcontextprotocol.spec.McpSchema.ToolAnnotations;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

public final class Main {
    private static final Map<String, String> STRING = Map.of("type", "string");

    public static void main(String[] args) throws IOException {
        var service = new AnalysisService(new GitRepository(repositoryPath(args)),
                new LanguageRegistry(List.of(new JavaLanguageSupport())), "java");
        var transport = new StdioServerTransportProvider(McpJsonDefaults.getMapper());

        McpServer.sync(transport)
                .serverInfo("codeclarity", "0.1.1")
                .capabilities(ServerCapabilities.builder().tools(false).build())
                .tools(
                        tool("list_java_changes",
                                "Find changed Java files and line ranges between the merge base and target commit. "
                                        + "Call first to resolve branch names into commit SHAs.",
                                Map.of("baseRef", STRING, "headRef", STRING), List.of("baseRef", "headRef"),
                                input -> service.listChanges(required(input, "baseRef"), required(input, "headRef"))),
                        tool("analyze_java_changes",
                                "Compare PMD method-complexity findings on the two commit SHAs returned by "
                                        + "list_java_changes. For larger comparisons, pass paths in batches of up to "
                                        + AnalysisService.MAX_ANALYSIS_FILES + " changed files with the same SHAs.",
                                Map.of("baseSha", STRING, "headSha", STRING,
                                        "paths", Map.of("type", "array", "items", STRING, "minItems", 1,
                                                "maxItems", AnalysisService.MAX_ANALYSIS_FILES)),
                                List.of("baseSha", "headSha"),
                                input -> service.analyzeChanges(required(input, "baseSha"), required(input, "headSha"), paths(input))),
                        tool("inspect_java_method",
                                "Show the Java method or constructor containing the given line, including its calls "
                                        + "and enclosing if branches in the selected commit.",
                                Map.of("commitSha", STRING, "path", STRING,
                                        "line", Map.of("type", "integer", "minimum", 1)),
                                List.of("commitSha", "path", "line"),
                                input -> service.inspectEntity(required(input, "commitSha"), required(input, "path"), line(input))))
                .build();
    }

    private static SyncToolSpecification tool(String name, String description, Map<String, ?> properties,
                                               List<String> required, Function<Map<String, Object>, Object> action) {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("properties", properties);
        schema.put("required", required);
        schema.put("additionalProperties", false);
        return SyncToolSpecification.builder()
                .tool(Tool.builder(name, schema)
                        .description(description)
                        .annotations(ToolAnnotations.builder().readOnlyHint(true).build())
                        .build())
                .callHandler((exchange, request) -> {
                    try {
                        var input = request.arguments() == null ? Map.<String, Object>of() : request.arguments();
                        if (!properties.keySet().containsAll(input.keySet())) {
                            throw new IllegalArgumentException("Unexpected tool argument.");
                        }
                        Object result = action.apply(input);
                        String json = McpJsonDefaults.getMapper().writeValueAsString(result);
                        return CallToolResult.builder().structuredContent(result).textContent(List.of(json)).build();
                    } catch (IllegalArgumentException exception) {
                        return CallToolResult.builder().isError(true).textContent(List.of(exception.getMessage())).build();
                    } catch (IOException exception) {
                        System.err.println("Could not encode tool result: " + exception.getMessage());
                        return CallToolResult.builder().isError(true).textContent(List.of("Could not encode tool result.")).build();
                    }
                })
                .build();
    }

    private static String required(Map<String, Object> input, String key) {
        if (input.get(key) instanceof String value && !value.isBlank()) {
            return value;
        }
        throw new IllegalArgumentException(key + " must be a non-empty string.");
    }

    private static int line(Map<String, Object> input) {
        if (input.get("line") instanceof Number value
                && value.doubleValue() == value.intValue() && value.intValue() > 0) {
            return value.intValue();
        }
        throw new IllegalArgumentException("line must be a positive integer.");
    }

    private static List<String> paths(Map<String, Object> input) {
        if (!input.containsKey("paths")) {
            return List.of();
        }
        if (input.get("paths") instanceof List<?> values && !values.isEmpty()
                && values.size() <= AnalysisService.MAX_ANALYSIS_FILES
                && values.stream().allMatch(value -> value instanceof String path && !path.isBlank())) {
            return values.stream().map(String.class::cast).toList();
        }
        throw new IllegalArgumentException("paths must contain 1 to " + AnalysisService.MAX_ANALYSIS_FILES + " non-empty paths.");
    }

    private static Path repositoryPath(String[] args) throws IOException {
        if (args.length == 2 && args[0].equals("--repo-root")) {
            return Path.of(args[1]);
        }
        if (args.length == 0) {
            Path config = Path.of(System.getProperty("user.home"), ".codeclarity", "repo-root.txt");
            if (Files.isRegularFile(config)) {
                return Path.of(Files.readString(config).strip());
            }
        }
        throw new IllegalArgumentException("Use --repo-root <path> or set ~/.codeclarity/repo-root.txt.");
    }
}
