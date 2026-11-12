package dev.codeclarity;

import dev.codeclarity.core.AnalysisService;
import dev.codeclarity.core.LanguageRegistry;
import dev.codeclarity.git.GitRepository;
import dev.codeclarity.languages.java.JavaLanguageSupport;
import dev.codeclarity.languages.python.PythonLanguageSupport;

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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;

public final class Main {
    private static final Map<String, String> STRING = Map.of("type", "string");

    public static void main(String[] args) throws IOException {
        var git = new GitRepository(repositoryPath(args));
        var languages = new LanguageRegistry(List.of(new JavaLanguageSupport(), new PythonLanguageSupport()));
        var service = new AnalysisService(git, languages);
        List<SyncToolSpecification> tools = new ArrayList<>();
        tools.addAll(analysisTools(service,
                "get_changes", "analyze_changes", "inspect_symbol_ast", "Java and Python", "entity"));
        tools.add(tool("get_symbol_context",
                "Get committed Java/Python entity source, repository path, language, inclusive line range, calls and enclosing if branches. "
                        + "Select the adapter by file path. Truncated context is explicitly partial with warnings.",
                Map.of("commitSha", STRING, "path", STRING, "line", Map.of("type", "integer", "minimum", 1)),
                List.of("commitSha", "path", "line"),
                input -> service.getSymbolContext(required(input, "commitSha"), required(input, "path"), line(input))));
        tools.addAll(languageTools(new AnalysisService(git, languages, "java"), "java", "Java", "method"));
        tools.addAll(languageTools(new AnalysisService(git, languages, "python"), "python", "Python", "function"));
        var transport = new StdioServerTransportProvider(McpJsonDefaults.getMapper());

        McpServer.sync(transport)
                .serverInfo("codeclarity", "0.1.4")
                .capabilities(ServerCapabilities.builder().tools(false).build())
                .tools(tools.toArray(SyncToolSpecification[]::new))
                .build();
    }

    private static List<SyncToolSpecification> languageTools(AnalysisService service, String id,
                                                            String label, String entity) {
        return analysisTools(service, "list_" + id + "_changes", "analyze_" + id + "_changes",
                "inspect_" + id + "_" + entity, label, entity);
    }

    private static List<SyncToolSpecification> analysisTools(AnalysisService service, String listName,
                                                            String analyzeName, String inspectName,
                                                            String label, String entity) {
        return List.of(
                tool(listName,
                        "Find changed " + label + " files and line ranges between the merge base and target commit. "
                                + "Call first to resolve branch names into commit SHAs.",
                        Map.of("baseRef", STRING, "headRef", STRING), List.of("baseRef", "headRef"),
                        input -> service.listChanges(required(input, "baseRef"), required(input, "headRef"))),
                tool(analyzeName,
                        "Compare " + label + " numeric metrics (before, after, delta) and rule findings on the SHAs returned by " + listName
                                + ". Select the adapter automatically by file path. Pass paths in batches of up to "
                                + AnalysisService.MAX_ANALYSIS_FILES + " files.",
                        Map.of("baseSha", STRING, "headSha", STRING,
                                "paths", Map.of("type", "array", "items", STRING, "minItems", 1,
                                        "maxItems", AnalysisService.MAX_ANALYSIS_FILES)),
                        List.of("baseSha", "headSha"),
                        input -> service.analyzeChanges(required(input, "baseSha"), required(input, "headSha"), paths(input))),
                tool(inspectName,
                        "Show the " + label + " " + entity + " containing the given line, its calls and enclosing if branches.",
                        Map.of("commitSha", STRING, "path", STRING, "line", Map.of("type", "integer", "minimum", 1)),
                        List.of("commitSha", "path", "line"),
                        input -> service.inspectEntity(required(input, "commitSha"), required(input, "path"), line(input))));
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
                    } catch (RuntimeException exception) {
                        String message = exception.getMessage() == null ? exception.getClass().getSimpleName() : exception.getMessage();
                        return CallToolResult.builder().isError(true).textContent(List.of(message)).build();
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
