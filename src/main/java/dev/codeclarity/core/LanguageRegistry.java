package dev.codeclarity.core;

import java.util.List;
import java.util.Optional;

public final class LanguageRegistry {
    private final List<LanguageSupport> languages;

    public LanguageRegistry(List<LanguageSupport> languages) {
        this.languages = List.copyOf(languages);
        if (this.languages.stream().map(LanguageSupport::languageId).distinct().count() != languages.size()) {
            throw new IllegalArgumentException("Duplicate language id.");
        }
    }

    public LanguageSupport require(String id) {
        return languages.stream().filter(language -> language.languageId().equals(id)).findFirst()
                .orElseThrow(() -> new IllegalArgumentException("Unsupported language: " + id));
    }

    /** Unknown extensions are ignored; overlapping adapters are a configuration error. */
    public Optional<LanguageSupport> find(String path) {
        if (path == null) { return Optional.empty(); }
        var matches = languages.stream().filter(language -> language.supports(path)).toList();
        if (matches.size() > 1) {
            throw new IllegalArgumentException("Multiple language adapters support: " + path);
        }
        return matches.stream().findFirst();
    }
}
