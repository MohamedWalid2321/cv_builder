"""Main window for local file import and extracted-text review."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent.job_analyzer import JobAnalysisError, JobAnalyzer
from models.schemas import JobProfile
from services.file_extractor import ExtractionError, ExtractionResult, extract_text, extract_text_content
from services.job_profile import synchronize_profile_links
from services.skill_counter import count_requirement_mentions


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI CV Builder — Import and Review")
        self.resize(900, 650)
        self._job_result: ExtractionResult | None = None
        self._cv_result: ExtractionResult | None = None
        self._analysis_profile: JobProfile | None = None

        central = QWidget()
        layout = QVBoxLayout(central)
        intro = QLabel(
            "Stage 0–1: choose a job description and optionally an existing CV. "
            "Files are extracted locally and shown below for review."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.status_label = QLabel("Dependency status: checking…")
        layout.addWidget(self.status_label)

        layout.addWidget(QLabel("Paste job description"))
        self.job_input = QPlainTextEdit()
        self.job_input.setPlaceholderText("Paste the complete job description here…")
        self.job_input.setMinimumHeight(150)
        layout.addWidget(self.job_input)
        self.job_button = QPushButton("Use pasted job description")
        self.job_button.clicked.connect(self._use_pasted_job_description)
        layout.addWidget(self.job_button)
        self.job_label = QLabel("No job description entered")
        layout.addWidget(self.job_label)

        self.cv_button = QPushButton("Upload existing CV (optional)")
        self.cv_button.clicked.connect(lambda: self._choose_file("cv"))
        layout.addWidget(self.cv_button)
        self.cv_label = QLabel("No existing CV selected")
        layout.addWidget(self.cv_label)

        layout.addWidget(QLabel("Extracted CV text review"))
        self.preview = QPlainTextEdit()
        self.preview.setPlaceholderText("Extracted CV text will appear here after selecting an existing CV.")
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.preview, 1)

        self.analyze_button = QPushButton("Analyze job description")
        self.analyze_button.clicked.connect(self._analyze_job_description)
        layout.addWidget(self.analyze_button)
        self.analysis_label = QLabel("No job analysis yet")
        layout.addWidget(self.analysis_label)

        layout.addWidget(QLabel("Job analysis review (editable JSON)"))
        self.analysis_output = QPlainTextEdit()
        self.analysis_output.setPlaceholderText("The structured job analysis will appear here.")
        self.analysis_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.analysis_output, 1)
        self.apply_analysis_button = QPushButton("Apply analysis corrections")
        self.apply_analysis_button.clicked.connect(self._apply_analysis_corrections)
        self.apply_analysis_button.setEnabled(False)
        layout.addWidget(self.apply_analysis_button)

        self.setCentralWidget(central)
        self._update_dependency_status()

    def _update_dependency_status(self) -> None:
        checks: list[str] = []
        for package, import_name in (("PyMuPDF", "pymupdf"), ("python-docx", "docx"), ("google-genai", "google.genai")):
            try:
                __import__(import_name)
                checks.append(f"{package}: available")
            except ImportError:
                checks.append(f"{package}: missing")
        try:
            import shutil

            compiler = next((name for name in ("tectonic", "pdflatex") if shutil.which(name)), None)
        except Exception:
            compiler = None
        checks.append(f"LaTeX compiler: {compiler or 'not found (needed in a later stage)'}")
        provider = os.getenv("AI_PROVIDER", "gemini").lower()
        key_name = "GROQ_API_KEY" if provider == "groq" else "GEMINI_API_KEY"
        checks.append(f"{provider} API key: {'configured' if os.getenv(key_name) else 'not configured'}")
        self.status_label.setText("Dependency status: " + " | ".join(checks))

    def _choose_file(self, kind: str) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select a document",
            str(Path.home()),
            "Documents (*.pdf *.doc *.docx *.txt);;All files (*.*)",
        )
        if not selected:
            return
        try:
            result = extract_text(selected)
        except ExtractionError as exc:
            QMessageBox.warning(self, "Could not import file", str(exc))
            return

        self._cv_result = result
        self.cv_label.setText(f"Existing CV: {result.path.name} ({result.file_type})")
        self.preview.setPlainText(result.text)
        if result.warning:
            QMessageBox.information(self, "Import warning", result.warning)

    def _use_pasted_job_description(self) -> None:
        try:
            result = extract_text_content(self.job_input.toPlainText(), "pasted job description")
        except ExtractionError as exc:
            QMessageBox.warning(self, "Could not use job description", str(exc))
            return

        self._job_result = result
        self.job_label.setText("Job description: pasted text")

    def _analyze_job_description(self) -> None:
        if self._job_result is None:
            QMessageBox.warning(self, "Job description required", "Paste and use a job description first.")
            return

        try:
            profile = JobAnalyzer().analyze(self._job_result.text)
        except JobAnalysisError as exc:
            QMessageBox.warning(self, "Could not analyze job description", str(exc))
            return

        self._analysis_profile = profile
        self._show_analysis(profile)
        self.analysis_label.setText(f"Analysis ready: {profile.job_title}")
        self.apply_analysis_button.setEnabled(True)

    def _show_analysis(self, profile: JobProfile) -> None:
        synchronize_profile_links(profile, self._job_result.text)  # type: ignore[union-attr]
        payload = profile.model_dump()
        for item, requirement in zip(payload["requirements"], profile.requirements):
            counts = count_requirement_mentions(self._job_result.text, requirement)  # type: ignore[union-attr]
            item["requirement_id"] = requirement.requirement_id
            item["count_source"] = "original_job_description"
            item["literal_counts"] = counts.literal_counts
            item["total_literal_phrase_matches"] = counts.total_literal_phrase_matches
        for item in payload["responsibilities"]:
            item.pop("related_requirement_names", None)
        self.analysis_output.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))

    def _apply_analysis_corrections(self) -> None:
        try:
            profile = JobProfile.model_validate(json.loads(self.analysis_output.toPlainText()))
        except (json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid analysis", f"Please correct the JSON structure.\n{exc}")
            return

        self._analysis_profile = profile
        self._show_analysis(profile)
        self.analysis_label.setText(f"Corrections applied: {profile.job_title}")
