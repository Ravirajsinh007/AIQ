from decimal import Decimal, InvalidOperation
from apps.questions.models import QuestionType, DifficultyLevel, BloomTaxonomy


VALID_QUESTION_TYPES = {c[0] for c in QuestionType.choices}
VALID_DIFFICULTIES = {c[0] for c in DifficultyLevel.choices}
VALID_BLOOM_TAXONOMIES = {c[0] for c in BloomTaxonomy.choices}


class CandidateValidationError(Exception):
    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(str(errors))


def validate_ai_candidate(candidate: dict) -> tuple[bool, dict, dict]:
    """
    Performs rigorous schema and business invariant validation on an AI question candidate.
    Returns:
        (is_valid: bool, cleaned_data: dict, error_dict: dict)
    """
    errors = {}
    cleaned = {}

    if not isinstance(candidate, dict):
        return False, {}, {'general': 'Candidate must be a JSON object.'}

    # 1. Check supported_by_source flag
    if candidate.get('supported_by_source') is False:
        errors['supported_by_source'] = "Candidate is flagged as unsupported by the provided source material."
        return False, {}, errors

    # 2. Question text
    text = str(candidate.get('question_text', '')).strip()
    if not text or len(text) < 5:
        errors['question_text'] = "Question text must be non-empty and at least 5 characters long."
    cleaned['question_text'] = text

    # 3. Question type
    q_type = str(candidate.get('question_type', '')).lower().strip()
    if q_type not in VALID_QUESTION_TYPES:
        errors['question_type'] = f"Invalid question type '{q_type}'. Allowed types: {sorted(list(VALID_QUESTION_TYPES))}"
    cleaned['question_type'] = q_type

    # 4. Difficulty
    diff = str(candidate.get('difficulty', DifficultyLevel.MEDIUM)).lower().strip()
    if diff not in VALID_DIFFICULTIES:
        diff = DifficultyLevel.MEDIUM
    cleaned['difficulty'] = diff

    # 5. Bloom taxonomy
    bloom = str(candidate.get('bloom_taxonomy', BloomTaxonomy.UNDERSTAND)).lower().strip()
    if bloom not in VALID_BLOOM_TAXONOMIES:
        bloom = BloomTaxonomy.UNDERSTAND
    cleaned['bloom_taxonomy'] = bloom

    # 6. Marks and negative marks
    raw_marks = candidate.get('marks', '1.00')
    raw_neg_marks = candidate.get('negative_marks', '0.00')
    try:
        marks = Decimal(str(raw_marks))
        if marks <= Decimal('0.00'):
            errors['marks'] = "Marks must be strictly positive."
    except (InvalidOperation, TypeError, ValueError):
        errors['marks'] = f"Invalid decimal value for marks: {raw_marks}"
        marks = Decimal('1.00')
    cleaned['marks'] = marks

    try:
        neg_marks = Decimal(str(raw_neg_marks))
        if neg_marks < Decimal('0.00'):
            errors['negative_marks'] = "Negative marks cannot be negative."
        elif neg_marks > marks:
            errors['negative_marks'] = "Negative marks cannot exceed positive marks."
    except (InvalidOperation, TypeError, ValueError):
        errors['negative_marks'] = f"Invalid decimal value for negative marks: {raw_neg_marks}"
        neg_marks = Decimal('0.00')
    cleaned['negative_marks'] = neg_marks

    # 7. Type-specific validations
    options = candidate.get('options', [])
    answer_key = candidate.get('answer_key') or {}
    rubrics = candidate.get('rubrics', [])
    code_metadata = candidate.get('code_metadata') or {}

    if q_type == QuestionType.MCQ:
        if not isinstance(options, list) or len(options) < 2:
            errors['options'] = "Multiple Choice Questions must have at least 2 options."
        else:
            cleaned_options = []
            has_correct = False
            for idx, opt in enumerate(options):
                if not isinstance(opt, dict):
                    errors[f'options_{idx}'] = "Option must be an object with option_key and option_text."
                    continue
                k = str(opt.get('option_key', chr(65 + idx))).strip().upper()
                t = str(opt.get('option_text', '')).strip()
                c = bool(opt.get('is_correct', False))
                e = str(opt.get('explanation', '')).strip()
                if not t:
                    errors[f'option_{idx}_text'] = f"Option {k} text cannot be empty."
                if c:
                    has_correct = True
                cleaned_options.append({
                    'option_key': k,
                    'option_text': t,
                    'is_correct': c,
                    'explanation': e,
                    'order': idx + 1
                })
            if not has_correct:
                errors['options'] = "At least one option must be marked as correct for MCQ."
            cleaned['options'] = cleaned_options

    elif q_type == QuestionType.TRUE_FALSE:
        if not isinstance(options, list) or len(options) != 2:
            errors['options'] = "True/False questions must have exactly 2 options."
        else:
            cleaned_options = []
            correct_count = 0
            for idx, opt in enumerate(options):
                if not isinstance(opt, dict):
                    errors[f'options_{idx}'] = "Option must be an object."
                    continue
                k = str(opt.get('option_key', chr(65 + idx))).strip().upper()
                t = str(opt.get('option_text', '')).strip()
                c = bool(opt.get('is_correct', False))
                e = str(opt.get('explanation', '')).strip()
                if c:
                    correct_count += 1
                cleaned_options.append({
                    'option_key': k,
                    'option_text': t,
                    'is_correct': c,
                    'explanation': e,
                    'order': idx + 1
                })
            if correct_count != 1:
                errors['options'] = "Exactly one option must be marked as correct for True/False."
            cleaned['options'] = cleaned_options

    elif q_type in [QuestionType.SHORT_ANSWER, QuestionType.LONG_ANSWER]:
        if not isinstance(answer_key, dict) or not str(answer_key.get('expected_answer', '')).strip():
            errors['answer_key'] = f"Expected answer key is required for {q_type}."
        else:
            cleaned['answer_key'] = {
                'expected_answer': str(answer_key.get('expected_answer', '')).strip(),
                'sample_solution': str(answer_key.get('sample_solution', '')).strip(),
                'keywords': answer_key.get('keywords', []) if isinstance(answer_key.get('keywords'), list) else [],
                'explanation': str(answer_key.get('explanation', '')).strip(),
            }

        # Validate optional rubrics
        if rubrics and isinstance(rubrics, list):
            cleaned_rubrics = []
            for r_idx, r in enumerate(rubrics, 1):
                if isinstance(r, dict) and r.get('criterion'):
                    try:
                        r_marks = Decimal(str(r.get('max_marks', '1.00')))
                    except Exception:
                        r_marks = Decimal('1.00')
                    cleaned_rubrics.append({
                        'criterion': str(r.get('criterion', '')).strip(),
                        'description': str(r.get('description', '')).strip(),
                        'max_marks': r_marks,
                        'order': r.get('order', r_idx)
                    })
            cleaned['rubrics'] = cleaned_rubrics

    elif q_type == QuestionType.CODING:
        lang = str(code_metadata.get('language', '')).strip() if isinstance(code_metadata, dict) else ''
        if not lang:
            errors['code_metadata'] = "Coding questions require 'language' in code_metadata."
        cleaned['code_metadata'] = {
            'language': lang,
            'starter_template': str(code_metadata.get('starter_template', '')).strip() if isinstance(code_metadata, dict) else ''
        }

        test_cases = answer_key.get('test_cases', []) if isinstance(answer_key, dict) else []
        if not isinstance(test_cases, list) or len(test_cases) == 0:
            errors['answer_key'] = "Coding questions require at least one test case in answer key."
        else:
            cleaned['answer_key'] = {
                'expected_answer': str(answer_key.get('expected_answer', 'Solution function')).strip(),
                'sample_solution': str(answer_key.get('sample_solution', '')).strip(),
                'test_cases': test_cases,
                'explanation': str(answer_key.get('explanation', '')).strip(),
                'keywords': []
            }

    # 8. Provenance Grounding Validation
    provenance = candidate.get('provenance')
    if not isinstance(provenance, dict):
        errors['provenance'] = "Candidate lacks provenance citation object."
    else:
        excerpt = str(provenance.get('excerpt', '')).strip()
        source_title = str(provenance.get('source_title', '')).strip()
        if not excerpt or len(excerpt) < 8:
            errors['provenance'] = "Provenance evidence excerpt is missing or too brief to prove grounding."
        cleaned['provenance'] = {
            'source_title': source_title or 'Authorized Source Material',
            'page_or_section': str(provenance.get('page_or_section', '')).strip(),
            'excerpt': excerpt,
            'relevance_note': str(provenance.get('relevance_note', '')).strip()
        }

    is_valid = len(errors) == 0
    return is_valid, cleaned, errors
