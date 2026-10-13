# AI CV Builder

Local desktop application for tailoring a truthful CV to a job description.

The job description is pasted directly into the application as text. An existing CV may optionally be uploaded for local extraction.

## Stage 2 analysis

After entering the job description, click **Analyze job description**. Stage 2 sends the pasted job description to the provider configured by `AI_PROVIDER`, validates the JSON response locally, and calculates phrase counts locally. CV evidence and matching are kept separate for later stages. With the current Groq configuration, set `GROQ_API_KEY` in a local `.env` file before using this action. The analysis JSON remains editable so you can correct requirements before later stages.

The analysis output uses `literal_counts` for exact, case-insensitive occurrences of each `literal_phrases` entry across the full original job description. `total_literal_phrase_matches` is the deduplicated sum of those phrase matches; it is not a CV match score. Responsibility priority is `required` or `preferred` only when the source contains an explicit priority marker; otherwise an extracted responsibility is marked `unspecified` with `priority_basis: "explicit"`.

## Stage 0 setup

```powershell
C:/Python314/python.exe -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Run the desktop shell with:

```powershell
.venv/Scripts/python.exe app.py
```

The application keeps uploaded documents local. AI integration is intentionally not part of Stage 0–1.

## Supported CV files

PDF, DOCX, and TXT files are extracted locally. Legacy binary `.doc` files are detected and reported as unsupported unless converted to DOCX/TXT first. Scanned/image-only PDFs are reported as requiring OCR.
