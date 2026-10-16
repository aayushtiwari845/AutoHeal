# AutoHeal academic report source plan

The final report will be built from implementation evidence, measured run summaries and actual UI screenshots. It is a joint Generative AI laboratory submission for Aayush Kumar Tiwari (16014223003, LY AI & DS B2) and Prateeksha Kini (16014223061, LY AI & DS B3).

Repository: https://github.com/aayushtiwari845/AutoHeal

## Planned structure

The final structure contains 26 substantive pages after adding separate readable semantic-failure and actual live-repair evidence. The initial 24-page budget was expanded to preserve evidence readability, not to add filler.

1. Model-driven code execution and self correction overview, authors, abstract, repository, revision and concise ReAct/Reflexion foundations.
2. Problem statement, project objectives and assessment coverage against the supplied 10-mark rubric.
3. Functional requirements, local setup, dependencies and reproducibility.
4. System architecture and data flow, with an explanatory diagram.
5. Automatic and manual control flow, explicit state machine and termination conditions.
6. Module responsibilities, API routes, trace records and persistence boundaries.
7. Local Ollama and optional API providers, request contracts, secrets and bounded repair feedback.
8. Constrained execution, real CPython tracing, timeouts, output limits and operating-system controls.
9. Fixed datasets, task algorithms and independent reference outputs.
10. Validation semantics, metrics and the boundary between successful execution and a correct answer.
11. Screenshot walkthrough of the Win95-inspired application and its task controls.
12. Screenshot walkthrough of the manual candidate and the paused execution boundary.
13. Successful execution followed by an independently detected semantic failure.
14. Actual runtime failure and recorded local-state observations, with separate run identities.
15. Screenshot walkthrough of structured reflection and bounded feedback.
16. Full-size screenshot walkthrough of the repaired replay candidate.
17. Full-size source-diff screenshot and explanation of the actual stored source comparison.
18. Screenshot walkthrough of independent validation and successful termination.
19. Separate actual local-model repair source, paused before execution and labelled as unvalidated at capture.
20. Screenshot walkthrough of automatic progression and JSON export.
21. Automated verification, regressions, measured tests and cross-platform CI evidence.
22. Current live evaluation results, historical diagnostic distinction and small-sample interpretation.
23. Failure taxonomy and evidence-based analysis of non-convergence.
24. Supervisor demonstration sequence and concise viva questions with answers.
25. Limitations, privacy, ethics, academic disclosure and future work.
26. Conclusion, source revision, reproducibility details and source references.

The page budget may be reduced if complete content fits naturally. It must not be expanded using empty cover pages or unreadable screenshots. Sustained prose uses 11-point type or larger on Letter pages. All titles and headings remain black. Final PDF is exported from the editable DOCX through the packaged renderer so both share the same layout.

## Evidence contract

Before final generation, provide `docs/course-report/evidence.json` containing:

```json
{
  "version": "2.0.0",
  "source_commit": "implementation commit hash",
  "report_date": "16 October 2026",
  "python_version": "observed runtime version",
  "hardware": "observed laptop configuration",
  "test_count": 0,
  "test_seconds": 0,
  "test_log": "docs/evidence/test-results.txt",
  "live_summary": "docs/evidence/live-summary.json",
  "screenshot_index": "docs/screenshots/index.json",
  "api_live_tested": false
}
```

The values above illustrate the schema only. The builder must reject incomplete evidence, absent screenshot files and unresolved replacement fields. No zero counts or illustrative values may appear in the final report.

The screenshot index maps stage keys to file, caption and observed evidence. Preferred stage keys are `overview`, `manual_candidate`, `execution_failure`, `reflection`, `repaired_candidate`, `diff`, `trace`, `live_repair`, `validation`, `automatic`, and `export`. A `provider_settings` view may be added where useful. Each entry should identify the run ID and actual mode when relevant. Captions must say whether a candidate was generated live, a controlled first failure, or scripted replay.

Measured live summaries may be lists of records with provider, flow, mode, seeded, preset, status, attempts, duration_ms and trace fields. They must identify the current code revision. Earlier version results may be discussed only with an explicit historical label.

## Authoring and QA gate

Do not create DOCX or PDF artifacts before the parent confirms the required edit markers have run. Preparing this plan and the builder source is allowed. After generation, run the current packaged `render_docx.py` with the bundled Python, the isolated LibreOffice under the parent workspace `tmp/tools/LibreOffice/program`, and bundled Poppler. Inspect every page image at original resolution, repair layout, and re-render before delivering.
