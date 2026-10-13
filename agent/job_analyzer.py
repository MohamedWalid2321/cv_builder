"""Provider-backed job-description analysis."""

from __future__ import annotations

import json
import os

from models.schemas import JobProfile


class JobAnalysisError(RuntimeError):
    """A user-facing failure while analyzing a job description."""


class JobAnalyzer:
    """Analyze a job description with the provider configured in ``.env``."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        self.provider = (provider or os.getenv("AI_PROVIDER", "gemini")).strip().lower()
        self.api_key = api_key if api_key is not None else self._read_api_key()
        default_model = "openai/gpt-oss-20b" if self.provider == "groq" else "gemini-2.5-flash-lite"
        self.model = model or os.getenv("AI_MODEL", default_model)

    def analyze(self, job_description: str) -> JobProfile:
        if not job_description.strip():
            raise JobAnalysisError("Enter a job description before analysis.")
        if self.provider not in {"gemini", "groq"}:
            raise JobAnalysisError(f"Unsupported AI_PROVIDER '{self.provider}'. Use 'gemini' or 'groq'.")
        if not self.api_key:
            key_name = "GROQ_API_KEY" if self.provider == "groq" else "GEMINI_API_KEY"
            raise JobAnalysisError(f"{key_name} is not configured in the local environment.")

        if self.provider == "groq":
            return self._analyze_groq(job_description)
        return self._analyze_gemini(job_description)

    def _read_api_key(self) -> str | None:
        key_name = "GROQ_API_KEY" if self.provider == "groq" else "GEMINI_API_KEY"
        return os.getenv(key_name)

    def _analyze_gemini(self, job_description: str) -> JobProfile:

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise JobAnalysisError("Gemini support is unavailable: install google-genai.") from exc

        prompt = self._build_prompt(job_description)
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=JobProfile,
                ),
            )
            if not response.text:
                raise JobAnalysisError("The AI returned an empty analysis.")
            return JobProfile.model_validate_json(response.text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise JobAnalysisError(f"Gemini returned data that did not match the job-analysis schema: {exc}") from exc
        except JobAnalysisError:
            raise
        except Exception as exc:
            raise JobAnalysisError(f"Job analysis failed: {exc}") from exc

    def _analyze_groq(self, job_description: str) -> JobProfile:
        try:
            from groq import Groq
        except ImportError as exc:
            raise JobAnalysisError("Groq support is unavailable: install groq.") from exc

        try:
            client = Groq(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Extract the job profile and return only the requested structured JSON. "
                        "Do not include markdown, commentary, or extra fields.",
                    },
                    {"role": "user", "content": self._build_prompt(job_description)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "job_profile",
                        "strict": True,
                        "schema": _strict_json_schema(JobProfile),
                    },
                },
                max_completion_tokens=4096,
                reasoning_effort="low",
                reasoning_format="hidden",
                temperature=0,
            )
            content = response.choices[0].message.content
            if not content:
                raise JobAnalysisError("The AI returned an empty analysis.")
            return JobProfile.model_validate_json(content)
        except (json.JSONDecodeError, ValueError) as exc:
            raise JobAnalysisError(f"Groq returned data that did not match the job-analysis schema: {exc}") from exc
        except JobAnalysisError:
            raise
        except Exception as exc:
            raise JobAnalysisError(f"Groq job analysis failed: {exc}") from exc

    @staticmethod
    def _build_prompt(job_description: str) -> str:
        return f"""Analyze the supplied job description and return only JSON matching the requested schema.

Rules:
- Extract the target job title, responsibilities, and requirements.
- Keep responsibilities in the responsibilities array; do not turn a whole responsibility into one combined skill.
- Put independently scorable skills, education, experience, certifications, seniority, and competencies in requirements.
- Categorize each requirement as hard_skill, soft_skill, education, experience, certification, seniority, experience_level, operational_competency, technical_competency, learning, working_arrangement, or keyword.
- Use working_arrangement for supervision, guidance, or working-context statements; do not label those soft skills unless the posting describes an interpersonal capability.
- Use operational_competency or technical_competency for project support; never classify technical project support as a soft skill.
- Mark requirement priority as required only when the posting explicitly makes it mandatory; use preferred only for explicit preferred wording, otherwise unspecified.
- Set priority_basis to explicit when the posting states the priority, inferred only when the wording supports an inference, otherwise unspecified.
- requirement_id should use a category prefix and sequence, such as HS001 or ED001.
- Put only contiguous, exact phrases from the job description in literal_phrases. Never invent a long phrase by joining separate list items.
- Put broader non-contiguous ideas such as configuration and maintenance in related_concepts; they are not literal phrase counts.
- Preserve explicit operation, configuration, maintenance, upgrades, implementations, testing, incident documentation, escalation, resolution, policy/procedure compliance, and staying-current requirements when present.
- Put only employer/job-posting evidence in job_evidence; never include candidate or CV statements.
- Include a short job_evidence snippet of no more than 20 words for each item.
- Set source_span to an exact contiguous excerpt copied from the original job description.
- Set source_section to a concise section label when the posting has headings; otherwise use job_description.
- Add related_requirement_names to responsibilities when a responsibility is supported by independently listed requirements.
- Include every explicit duty from the posting, including policy compliance, continuous improvement, staying current, testing, and cross-functional coordination. An explicit duty is not automatically a required hiring criterion.
- Return no more than 10 responsibilities and 25 requirements.
- Do not invent requirements, qualifications, or candidate experience.

JOB DESCRIPTION:
{job_description}
"""


def _strict_json_schema(model: type[JobProfile]) -> dict[str, object]:
    """Inline Pydantic references and make every object field strict-schema required."""

    source = model.model_json_schema()
    definitions = source.pop("$defs", {})

    def clean(node: object) -> object:
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            reference = str(node["$ref"]).rsplit("/", maxsplit=1)[-1]
            return clean(definitions[reference])

        result: dict[str, object] = {}
        for key in ("type", "enum", "description", "items"):
            if key in node:
                result[key] = clean(node[key])
        if "properties" in node:
            properties = {name: clean(value) for name, value in node["properties"].items()}
            result["type"] = "object"
            result["properties"] = properties
            result["required"] = list(properties)
            result["additionalProperties"] = False
        return result

    return clean(source)  # type: ignore[return-value]


# Backwards-compatible name for existing imports and tests.
GeminiJobAnalyzer = JobAnalyzer
