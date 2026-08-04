# Agent Rules

1. Work only on the current MVP task in docs/BUILD_STATE.json.
2. Do not create a parallel project or replace the architecture.
3. Do not mark a task complete without its acceptance tests.
4. Do not skip, delete, weaken, or xfail a failing test.
5. Do not fabricate counts, metadata, approval, or release status.
6. Never store raw personal data in logs or issue details.
7. Do not bypass CAPTCHA, access controls, source disable flags, or rate limits.
8. Do not add LLM, vector DB, graph DB, web UI, queues, or distributed infrastructure.
9. Published raw/canonical/release artifacts are immutable.
10. Update only docs/BUILD_STATE.json for progress.
11. Keep changes small and run targeted tests after each task.
12. Final completion requires every command in the MVP acceptance gate to pass.
