# Academic report source

The editable Word report and its matching PDF are saved under `docs/report/`. The manuscript is `course_report.json`; the builder is `tools/build_project_report.py`. The project URL appears visibly and as a clickable link in the report's opening and reference sections.

The builder reads a recorded evidence manifest, a passing unittest log, current v2 run traces and a screenshot index. It does not run evaluations or infer live-model results from scripted examples. The validation step rejects missing evidence and unresolved fields.

```text
python tools/build_project_report.py --check
python tools/build_project_report.py
```

Report authoring requires `python-docx` and Pillow in addition to Python; these are optional documentation dependencies, not requirements for running the standard-library application. The builder uses Calibri on Windows or DejaVu Sans on Linux for explanatory diagrams. For a matching PDF, export the generated DOCX through Word or LibreOffice, then verify the pages visually. The released PDF is produced from the same DOCX layout.

The report distinguishes real screenshots from implementation diagrams. Screenshot files remain unmodified, and captions identify their observed stage and run mode. Source revision metadata refers to the implementation commit used for evaluation; the subsequent documentation commit can contain the finished report without requiring the report to predict its own Git hash.

See `report_plan.md` for the evidence-manifest fields and screenshot stage keys. Test results, run summaries and screenshots must be refreshed whenever a new implementation changes the behavior being documented.
