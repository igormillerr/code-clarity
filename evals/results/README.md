# Evaluation evidence

`scenarios.json` defines six scenarios. Protocol results, model results and manual
observations are different evidence levels. A successful protocol run does not
prove Codex discovery, Skill use or Rule Discovery persistence.

Run the reproducible commands in `evals/README.md`. Every fresh result starts as
`NOT_RUN`. Record a failed/unavailable run as such; never replace it with the
expected answer. `protocol.json` is generated only from the real Java JAR.

Synthetic history fixtures are labelled test data. They are not real developer
feedback. The current JAR has no history tools, so history integration remains
unavailable until the Java Core owner supplies them.
