import json
import logging
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder
from apps.questions.models import (
    Question,
    QuestionOption,
    AnswerKey,
    QuestionRubric,
    QuestionSourceReference,
    QuestionOrigin,
    QuestionStatus,
)
from apps.ai_generation.models import (
    QuestionGenerationJob,
    GeneratedCandidateRecord,
    GenerationJobStatus,
    CandidateStatus,
    SourceDocumentChunk,
)
from .gemini_service import (
    GoogleGeminiProvider,
    AIConfigurationError,
    AIProviderError,
    AISchemaError,
)
from .validator import validate_ai_candidate

logger = logging.getLogger(__name__)


def _audit_job_status(job):
    from apps.audit.services import record_audit_event

    record_audit_event(
        action='generation_job.status_changed',
        resource_type='generation_job',
        resource_id=job.pk,
        actor=job.requested_by,
        institute=job.institute,
        outcome='failed' if job.status == GenerationJobStatus.FAILED else 'success',
        metadata={'job_status': job.status},
    )


def _save_job_state(job, update_fields=None):
    with transaction.atomic():
        if update_fields is None:
            job.save()
        else:
            job.save(update_fields=update_fields)
        _audit_job_status(job)


def serialize_for_json(data):
    if not data:
        return {}
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def execute_question_generation_job(job: QuestionGenerationJob, provider=None) -> QuestionGenerationJob:
    """
    Executes an AI question generation job synchronously or in background worker.
    1. Gathers authorized source text chunks.
    2. Calls provider with grounding constraints.
    3. Validates each candidate against strict M3 rules and grounding.
    4. Persists valid candidates into M3 Question Bank in draft status.
    5. Saves diagnostic candidate records.
    """
    job.status = GenerationJobStatus.PROCESSING
    _save_job_state(job, ['status', 'updated_at'])

    # 1. Gather source passages
    source_docs = job.source_documents.all()
    if not source_docs.exists():
        # Fall back to completed source documents for this subject in the same institute
        source_docs = job.subject.source_documents.filter(
            institute=job.institute,
            processing_status='completed'
        )

    chunks_qs = SourceDocumentChunk.objects.filter(
        document__in=source_docs
    ).select_related('document').order_by('document', 'chunk_index')

    if not chunks_qs.exists():
        job.status = GenerationJobStatus.FAILED
        job.error_message = "No processed source document passages available for question generation."
        _save_job_state(job, ['status', 'error_message', 'updated_at'])
        return job

    # Build passages list (limit to 15 chunks max to avoid overflowing context)
    passages = []
    for chunk in chunks_qs[:15]:
        passages.append({
            'source_title': chunk.document.title,
            'page_number': chunk.page_number or 'N/A',
            'content': chunk.content
        })

    # 2. Initialize provider
    if provider is None:
        try:
            provider = GoogleGeminiProvider()
        except AIConfigurationError as config_err:
            job.status = GenerationJobStatus.FAILED
            job.error_message = str(config_err)
            _save_job_state(job, ['status', 'error_message', 'updated_at'])
            return job

    # 3. Call AI Provider
    try:
        raw_candidates, diagnostics = provider.generate_questions(
            subject_name=job.subject.name,
            subject_code=job.subject.code,
            unit_title=job.unit.title if job.unit else None,
            topic_title=job.topic.title if job.topic else None,
            learning_outcome_desc=job.learning_outcome.description if job.learning_outcome else None,
            source_passages=passages,
            requested_types=job.question_types,
            num_questions=job.num_questions_requested,
            difficulty_distribution=job.difficulty_distribution,
            bloom_distribution=job.bloom_taxonomy_distribution,
            language=job.language
        )
        job.safe_diagnostics = diagnostics

    except (AIConfigurationError, AIProviderError, AISchemaError) as ai_err:
        job.status = GenerationJobStatus.FAILED
        job.error_message = str(ai_err)
        _save_job_state(job, ['status', 'error_message', 'safe_diagnostics', 'updated_at'])
        return job
    except Exception as exc:
        job.status = GenerationJobStatus.FAILED
        job.error_message = f"Unexpected generation error: {str(exc)}"
        _save_job_state(job, ['status', 'error_message', 'updated_at'])
        return job

    # 4. Validate and Persist Candidates
    saved_count = 0
    failed_count = 0

    for idx, raw_cand in enumerate(raw_candidates, 1):
        is_valid, cleaned, errors = validate_ai_candidate(raw_cand)

        if is_valid:
            try:
                # Save into M3 Question Bank atomically
                with transaction.atomic():
                    question = Question.objects.create(
                        institute=job.institute,
                        subject=job.subject,
                        unit=job.unit,
                        topic=job.topic,
                        learning_outcome=job.learning_outcome,
                        question_type=cleaned['question_type'],
                        question_text=cleaned['question_text'],
                        difficulty=cleaned['difficulty'],
                        bloom_taxonomy=cleaned['bloom_taxonomy'],
                        marks=cleaned['marks'],
                        negative_marks=cleaned['negative_marks'],
                        origin_type=QuestionOrigin.AI_GENERATED,
                        status=QuestionStatus.DRAFT,  # STRICT DRAFT ONLY
                        current_version=1,
                        created_by=job.requested_by,
                        code_metadata=cleaned.get('code_metadata', {})
                    )

                    # Options (MCQ, True/False)
                    for opt in cleaned.get('options', []):
                        QuestionOption.objects.create(question=question, **opt)

                    # Answer key
                    ak_data = cleaned.get('answer_key')
                    if ak_data:
                        AnswerKey.objects.create(question=question, **ak_data)

                    # Rubrics
                    for rubric in cleaned.get('rubrics', []):
                        QuestionRubric.objects.create(question=question, **rubric)

                    # Source reference / Provenance
                    prov = cleaned.get('provenance', {})
                    if prov:
                        QuestionSourceReference.objects.create(
                            question=question,
                            source_title=prov.get('source_title', 'Authorized Source Document'),
                            page_or_section=prov.get('page_or_section', ''),
                            excerpt=prov.get('excerpt', ''),
                            relevance_note=prov.get('relevance_note', '')
                        )

                    # Record successful candidate
                    GeneratedCandidateRecord.objects.create(
                        job=job,
                        persisted_question=question,
                        candidate_number=idx,
                        question_type=cleaned['question_type'],
                        status=CandidateStatus.SAVED,
                        candidate_data=serialize_for_json(cleaned),
                        provenance_info=serialize_for_json(prov)
                    )
                    from apps.audit.services import record_audit_event

                    record_audit_event(
                        action='question.created',
                        resource_type='question',
                        resource_id=question.pk,
                        actor=job.requested_by,
                        institute=job.institute,
                        metadata={'to_status': question.status},
                    )
                    saved_count += 1

            except Exception as persist_err:
                logger.error("Failed to persist question candidate %d: %s", idx, str(persist_err))
                failed_count += 1
                GeneratedCandidateRecord.objects.create(
                    job=job,
                    candidate_number=idx,
                    question_type=cleaned.get('question_type', 'unknown'),
                    status=CandidateStatus.VALIDATION_FAILED,
                    candidate_data=serialize_for_json(cleaned),
                    validation_errors={'persistence': f"Failed database persistence: {str(persist_err)}"},
                    provenance_info=serialize_for_json(cleaned.get('provenance', {}))
                )

        else:
            failed_count += 1
            cand_status = (
                CandidateStatus.UNSUPPORTED_CONTENT
                if 'supported_by_source' in errors
                else CandidateStatus.VALIDATION_FAILED
            )
            GeneratedCandidateRecord.objects.create(
                job=job,
                candidate_number=idx,
                question_type=raw_cand.get('question_type', 'unknown'),
                status=cand_status,
                candidate_data=serialize_for_json(raw_cand),
                validation_errors=serialize_for_json(errors),
                provenance_info=serialize_for_json(raw_cand.get('provenance', {}))
            )

    job.num_questions_generated = saved_count
    job.num_questions_failed_validation = failed_count

    if saved_count > 0 and failed_count == 0:
        job.status = GenerationJobStatus.COMPLETED
    elif saved_count > 0 and failed_count > 0:
        job.status = GenerationJobStatus.PARTIALLY_COMPLETED
    else:
        job.status = GenerationJobStatus.FAILED
        job.error_message = "All generated question candidates failed validation or lacked source evidence."

    _save_job_state(job)
    return job
