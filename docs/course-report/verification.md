# Report verification

Verified 16 October 2026.

- Final report is 26 Letter pages with editable DOCX and a PDF exported from that same DOCX by the packaged render_docx.py.
- Used the bundled Python, isolated LibreOffice and bundled Poppler; the user's installed office application was not used.
- Inspected all 26 page images at original resolution, then re-inspected every changed diagram, screenshot and factual-correction page. No overflow pages, clipped document text, overlapping diagram labels or footer collisions remain.
- Embedded 12 authentic UI and JSON captures plus two explanatory diagrams. The screenshot index also preserves the supplemental authors capture. Scrollable views are described as visible excerpts; complete source and JSON remain in the repository.
- Final runtime capture visibly records EXECUTION FAILED, Exit 1 and the real TypeError at generated line 1. Live source is explicitly labelled model-generated, while scripted walkthrough source is identified as replay.
- Reported 63 passing software tests in 13.496 seconds and all six post-fix live cases from saved terminal traces. The historical 3-of-6 diagnostic is separately labelled; no live external API measurement is claimed.
- Caught exception events are distinguished from failed attempts. Provider deadline expiration is configured but is not claimed as covered by the current automated tests.
- Verified both student names, IDs and class details, the 10-mark assessment mapping, implementation revision and absence of unresolved template fields or replacement characters.
- PDF contains three clickable annotations for the full GitHub repository URL: title page and two on the final reference page. Total external URI annotations: 15.
- Source implementation reference: c3ba20afe522a9c41b921342fc22444d8e17b4a0. Evidence manifest: docs/course-report/evidence.json.

- Final metadata refresh re-rendered the same 26-page document and re-inspected pages 1, 21, 22 and 26 at original resolution. These pages have at least 50 points of measured body-to-footer clearance.
- Current software verification uses docs/evidence/post-ci-test-results.txt: 63 passing tests in 13.496 seconds. Windows and Linux CI passed in run 38936939670 for c3ba20a.
- The six live model cases were measured at 075598e. The later HTTP-only correction leaves generation, execution and validation unchanged; the report states this provenance explicitly rather than claiming a fresh model benchmark.

## Deliverable SHA256

- AutoHeal_Project_Report.docx: `01917400471feb223675cacc68e9cbeef9ecc50b338b0cb5da31926c586c98e0`
- AutoHeal_Project_Report.pdf: `f0ceffc493d737a8d4fd2ad29c464a94fc6c60526eb862645fe0894fd4682640`
