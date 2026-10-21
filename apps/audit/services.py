from .models import AuditEvent


SAFE_METADATA_KEYS = {
    'from_status',
    'to_status',
    'generation_version',
    'question_count',
    'scheduled_for',
    'reason_code',
    'changed_fields',
    'job_status',
    'role',
    'membership_status',
    'outcome',
}


def _safe_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}
    safe = {}
    for key, value in metadata.items():
        if key not in SAFE_METADATA_KEYS:
            continue
        if key == 'changed_fields' and isinstance(value, list):
            safe[key] = [item for item in value if isinstance(item, str)][:30]
        elif isinstance(value, (str, int, float, bool, type(None))):
            safe[key] = value
    return safe


def institute_for_resource(resource, depth=0):
    if resource is None or depth > 4:
        return None
    institute = getattr(resource, 'institute', None)
    if institute is not None:
        return institute
    for relation_name in (
        'subject', 'program', 'batch', 'department', 'semester',
        'academic_year', 'blueprint', 'section', 'teacher', 'student',
        'unit', 'topic', 'program_outcome', 'learning_outcome', 'paper_question', 'paper',
    ):
        relation = getattr(resource, relation_name, None)
        if relation is not None:
            institute = institute_for_resource(relation, depth + 1)
            if institute is not None:
                return institute
    return None


def record_audit_event(
    *,
    action,
    resource_type,
    resource_id='',
    actor=None,
    institute=None,
    outcome='success',
    metadata=None,
):
    return AuditEvent.objects.create(
        institute=institute,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id or ''),
        outcome=outcome,
        metadata=_safe_metadata(metadata or {}),
    )
