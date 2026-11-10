package dev.codeclarity.core;

import java.util.List;

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
}
