import json
import logging
import re
from django.conf import settings

logger = logging.getLogger(__name__)


class AIConfigurationError(Exception):
    """Raised when AI provider settings or API keys are missing or invalid."""
    pass


class AIProviderError(Exception):
    """Raised when external AI provider fails, times out, or encounters a rate limit."""
    pass


class AISchemaError(Exception):
    """Raised when the AI model returns invalid, malformed, or unparseable JSON output."""
    pass


def clean_json_markdown_response(raw_text: str) -> str:
    """
    Cleans markdown code fences (```json ... ```) or leading/trailing whitespace.
    """
    text = raw_text.strip()
    # Match markdown code block
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


class BaseAIProvider:
    """Abstract interface for LLM Question Generation providers."""

    def generate_questions(
        self,
        subject_name: str,
        subject_code: str,
        unit_title: str | None,
        topic_title: str | None,
        learning_outcome_desc: str | None,
        source_passages: list[dict],
        requested_types: list[str],
        num_questions: int,
        difficulty_distribution: dict,
        bloom_distribution: dict,
        language: str = 'English'
    ) -> tuple[list[dict], dict]:
        raise NotImplementedError


class GoogleGeminiProvider(BaseAIProvider):
    """
    Production-grade Google Gemini AI provider implementation using google-genai SDK.
    Enforces grounding against source passages and structured JSON responses.
    """

    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', '')
        self.model_name = model_name or getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')

        if not self.api_key or not self.api_key.strip():
            raise AIConfigurationError(
                "Google Gemini API key is missing. Please set 'GEMINI_API_KEY' in the environment."
            )

    def _get_client(self):
        try:
            from google import genai
            return genai.Client(api_key=self.api_key)
        except ImportError as err:
            raise AIConfigurationError("google-genai package is not available.") from err
        except Exception as exc:
            raise AIConfigurationError(f"Failed to initialize Google Gemini client: {str(exc)}") from exc

    def _build_prompt(
        self,
        subject_name: str,
        subject_code: str,
        unit_title: str | None,
        topic_title: str | None,
        learning_outcome_desc: str | None,
        source_passages: list[dict],
        requested_types: list[str],
        num_questions: int,
        difficulty_distribution: dict,
        bloom_distribution: dict,
        language: str = 'English'
    ) -> tuple[str, str]:
        """
        Builds system instruction and prompt for grounded question generation.
        """
        system_instruction = (
            "You are an expert academic curriculum assessment author. "
            "Your task is to generate rigorous, high-quality examination questions strictly grounded in the provided source passages.\n"
            "MANDATORY GROUNDING RULES:\n"
            "1. You must ONLY use facts, concepts, definitions, formulas, and principles present in the provided source material.\n"
            "2. Never hallucinate or extrapolate facts beyond the provided passages.\n"
            "3. For EVERY question candidate, you MUST cite the source title, page/section, and a verbatim supporting passage excerpt.\n"
            "4. If the source material lacks sufficient evidence to construct a valid question for a requested type, "
            "set 'supported_by_source': false with a clear explanation.\n"
            "5. Output ONLY a valid JSON array of question objects. Do not include introductory text, markdown commentary, or explanations outside the JSON."
        )

        formatted_passages = []
        for i, p in enumerate(source_passages, 1):
            title = p.get('source_title', 'Academic Document')
            page = p.get('page_number', 'N/A')
            content = p.get('content', '')
            formatted_passages.append(
                f"[Source Passage {i} | Document: '{title}' | Page: {page}]\n{content}"
            )
        passages_text = "\n\n".join(formatted_passages)

        user_prompt = f"""
ACADEMIC CONTEXT:
- Subject: {subject_name} ({subject_code})
- Unit: {unit_title or 'General Curriculum'}
- Topic: {topic_title or 'Comprehensive'}
- Target Learning Outcome: {learning_outcome_desc or 'General Course Proficiency'}
- Language: {language}

SPECIFICATIONS:
- Number of Questions Requested: {num_questions}
- Allowed Question Types: {', '.join(requested_types)}
- Difficulty Distribution Target: {json.dumps(difficulty_distribution)}
- Bloom's Taxonomy Distribution Target: {json.dumps(bloom_distribution)}

AUTHORIZED SOURCE PASSAGES:
{passages_text}

JSON OUTPUT FORMAT SCHEMA:
Output an array of objects with the following schema:
[
  {{
    "question_type": "mcq" | "true_false" | "short_answer" | "long_answer" | "coding",
    "question_text": "Stem of the question",
    "difficulty": "easy" | "medium" | "hard",
    "bloom_taxonomy": "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create",
    "marks": 2.0,
    "negative_marks": 0.5,
    "options": [
      {{
        "option_key": "A",
        "option_text": "Text for option A",
        "is_correct": true,
        "explanation": "Why this is correct or why other distractors are wrong"
      }},
      {{
        "option_key": "B",
        "option_text": "Text for option B",
        "is_correct": false,
        "explanation": "Distractor rationale"
      }}
    ],
    "answer_key": {{
      "expected_answer": "Complete expected solution or model answer",
      "sample_solution": "Detailed worked steps",
      "keywords": ["keyword1", "keyword2"],
      "test_cases": [
        {{ "input": "...", "expected_output": "...", "is_hidden": false }}
      ]
    }},
    "rubrics": [
      {{ "criterion": "Definition", "description": "Accurately defines the principle", "max_marks": 2.0, "order": 1 }}
    ],
    "code_metadata": {{
      "language": "python",
      "starter_template": "def solve():\\n    pass"
    }},
    "provenance": {{
      "source_title": "Document Title",
      "page_or_section": "Page 3",
      "excerpt": "Verbatim quote from source passage demonstrating grounding",
      "relevance_note": "Justification of alignment"
    }},
    "supported_by_source": true
  }}
]
"""
        return system_instruction, user_prompt

    def generate_questions(
        self,
        subject_name: str,
        subject_code: str,
        unit_title: str | None,
        topic_title: str | None,
        learning_outcome_desc: str | None,
        source_passages: list[dict],
        requested_types: list[str],
        num_questions: int,
        difficulty_distribution: dict,
        bloom_distribution: dict,
        language: str = 'English'
    ) -> tuple[list[dict], dict]:
        """
        Invokes Gemini API and returns (candidates_list, safe_diagnostics).
        """
        system_instruction, user_prompt = self._build_prompt(
            subject_name=subject_name,
            subject_code=subject_code,
            unit_title=unit_title,
            topic_title=topic_title,
            learning_outcome_desc=learning_outcome_desc,
            source_passages=source_passages,
            requested_types=requested_types,
            num_questions=num_questions,
            difficulty_distribution=difficulty_distribution,
            bloom_distribution=bloom_distribution,
            language=language
        )

        client = self._get_client()

        try:
            # Call Gemini generate_content
            response = client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config={
                    'system_instruction': system_instruction,
                    'temperature': 0.2,
                    'response_mime_type': 'application/json'
                }
            )

            raw_text = response.text or ''
            clean_text = clean_json_markdown_response(raw_text)

            if not clean_text:
                raise AISchemaError("Gemini returned an empty response.")

            try:
                parsed_data = json.loads(clean_text)
            except json.JSONDecodeError as json_err:
                logger.warning("Failed to decode JSON from Gemini: %s", raw_text[:200])
                raise AISchemaError(f"Model response is not valid JSON: {str(json_err)}") from json_err

            if not isinstance(parsed_data, list):
                if isinstance(parsed_data, dict) and 'questions' in parsed_data:
                    parsed_data = parsed_data['questions']
                else:
                    raise AISchemaError("Model response JSON must be a list of question candidates.")

            diagnostics = {
                'provider': 'google_gemini',
                'model_name': self.model_name,
                'total_passages_supplied': len(source_passages),
                'candidates_returned': len(parsed_data),
            }

            return parsed_data, diagnostics

        except (AIConfigurationError, AISchemaError):
            raise
        except Exception as exc:
            err_str = str(exc)
            if 'RESOURCE_EXHAUSTED' in err_str or '429' in err_str:
                raise AIProviderError("Gemini API rate limit or quota exceeded. Please retry later.") from exc
            if 'DEADLINE_EXCEEDED' in err_str or 'timeout' in err_str.lower():
                raise AIProviderError("Gemini API request timed out.") from exc
            raise AIProviderError(f"AI Provider error during question generation: {err_str}") from exc
