from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db import transaction
from drf_spectacular.utils import extend_schema, OpenApiResponse
from apps.accounts.permissions import EnforcePasswordChange
from .permissions import CanManageSourceMaterials, CanGenerateQuestions, can_access_institute
from .models import (
    SourceDocument,
    SourceDocumentChunk,
    QuestionGenerationJob,
    GeneratedCandidateRecord,
    DocumentProcessingStatus,
)
from .serializers import (
    SourceDocumentSerializer,
    SourceDocumentUploadSerializer,
    SourceDocumentChunkSerializer,
    QuestionGenerationJobRequestSerializer,
    QuestionGenerationJobSerializer,
    GeneratedCandidateRecordSerializer,
)
from .services.extractor import (
    extract_document_content,
    chunk_extracted_content,
    DocumentExtractionError,
)
from .services.orchestrator import execute_question_generation_job


class SourceDocumentViewSet(viewsets.ModelViewSet):
    """
    CRUD API for uploading, processing, and listing academic source materials.
    Automatically extracts readable text and splits into provenance-preserving chunks.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanManageSourceMaterials]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ['institute', 'subject', 'processing_status', 'file_type']
    search_fields = ['title', 'subject__code', 'subject__name']
    ordering_fields = ['created_at', 'title', 'file_size']

    def get_serializer_class(self):
        if self.action == 'create':
            return SourceDocumentUploadSerializer
        return SourceDocumentSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return SourceDocument.objects.none()
        user = self.request.user
        if not user or not user.is_authenticated:
            return SourceDocument.objects.none()
        if user.is_platform_admin:
            return SourceDocument.objects.all().select_related(
                'institute', 'subject', 'unit', 'topic', 'uploaded_by'
            ).prefetch_related('chunks')

        user_institutes = user.memberships.filter(
            role__in=['institute_admin', 'teacher', 'exam_staff'],
            status='active',
        ).values_list('institute_id', flat=True)
        return SourceDocument.objects.filter(institute_id__in=user_institutes).select_related(
            'institute', 'subject', 'unit', 'topic', 'uploaded_by'
        ).prefetch_related('chunks')

    @extend_schema(
        summary="Upload Source Material Document",
        responses={201: SourceDocumentSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        upload_file = serializer.validated_data['file']
        if not can_access_institute(request.user, serializer.validated_data['institute'].id):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied('You are not authorized to upload source material for this institute.')
        with transaction.atomic():
            instance = serializer.save(
                uploaded_by=request.user,
                processing_status=DocumentProcessingStatus.PROCESSING
            )
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='source_document.uploaded',
                resource_type='source_document',
                resource_id=instance.pk,
                actor=request.user,
                institute=instance.institute,
            )

        # Immediate extraction and chunking
        try:
            extraction_result = extract_document_content(upload_file, upload_file.name)
            instance.file_type = extraction_result['file_type']
            instance.extracted_text = extraction_result['extracted_text']
            instance.total_pages = extraction_result['total_pages']
            instance.file_size = upload_file.size
            instance.processing_status = DocumentProcessingStatus.COMPLETED
            instance.error_message = ''
            instance.save()

            # Create chunks
            chunks_data = chunk_extracted_content(extraction_result['page_records'])
            chunks_to_create = [
                SourceDocumentChunk(
                    document=instance,
                    chunk_index=c['chunk_index'],
                    section_title=c['section_title'],
                    page_number=c['page_number'],
                    content=c['content'],
                    char_count=c['char_count']
                )
                for c in chunks_data
            ]
            SourceDocumentChunk.objects.bulk_create(chunks_to_create)

        except DocumentExtractionError as ext_err:
            instance.processing_status = DocumentProcessingStatus.FAILED
            instance.error_message = str(ext_err)
            instance.file_size = upload_file.size if upload_file else 0
            instance.save()
        except Exception as exc:
            instance.processing_status = DocumentProcessingStatus.FAILED
            instance.error_message = f"Internal extraction error: {str(exc)}"
            instance.file_size = upload_file.size if upload_file else 0
            instance.save()

        from apps.audit.services import record_audit_event

        record_audit_event(
            action='source_document.processed',
            resource_type='source_document',
            resource_id=instance.pk,
            actor=request.user,
            institute=instance.institute,
            outcome='success' if instance.processing_status == DocumentProcessingStatus.COMPLETED else 'failed',
            metadata={'job_status': instance.processing_status},
        )
        return Response(SourceDocumentSerializer(instance).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="List Document Text Chunks",
        responses={200: SourceDocumentChunkSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='chunks')
    def chunks(self, request, pk=None):
        document = self.get_object()
        chunks = document.chunks.all().order_by('chunk_index')
        page = self.paginate_queryset(chunks)
        if page is not None:
            serializer = SourceDocumentChunkSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = SourceDocumentChunkSerializer(chunks, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class QuestionGenerationJobViewSet(viewsets.ModelViewSet):
    """
    API for managing AI Question Generation Jobs.
    Enforces tenant boundaries, prompt grounding, schema validation, and persistence to draft question bank.
    """
    permission_classes = [IsAuthenticated, EnforcePasswordChange, CanGenerateQuestions]
    filterset_fields = ['institute', 'subject', 'status']
    ordering_fields = ['created_at', 'status']

    def get_serializer_class(self):
        if self.action == 'create':
            return QuestionGenerationJobRequestSerializer
        return QuestionGenerationJobSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return QuestionGenerationJob.objects.none()
        user = self.request.user
        if not user or not user.is_authenticated:
            return QuestionGenerationJob.objects.none()
        if user.is_platform_admin:
            return QuestionGenerationJob.objects.all().select_related(
                'institute', 'subject', 'unit', 'topic', 'learning_outcome', 'requested_by'
            ).prefetch_related('source_documents', 'candidates')

        user_institutes = user.memberships.filter(
            role__in=['institute_admin', 'teacher', 'exam_staff'],
            status='active',
        ).values_list('institute_id', flat=True)
        return QuestionGenerationJob.objects.filter(institute_id__in=user_institutes).select_related(
            'institute', 'subject', 'unit', 'topic', 'learning_outcome', 'requested_by'
        ).prefetch_related('source_documents', 'candidates')

    @extend_schema(
        summary="Request AI Question Generation",
        responses={201: QuestionGenerationJobSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = QuestionGenerationJobRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not can_access_institute(request.user, data['institute'].id):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied('You are not authorized to generate questions for this institute.')

        source_docs = data.pop('source_document_ids', [])

        with transaction.atomic():
            job = QuestionGenerationJob.objects.create(
                institute=data['institute'],
                subject=data['subject'],
                unit=data.get('unit'),
                topic=data.get('topic'),
                learning_outcome=data.get('learning_outcome'),
                requested_by=request.user,
                question_types=data.get('question_types', ['mcq']),
                num_questions_requested=data.get('num_questions', 5),
                difficulty_distribution=data.get('difficulty_distribution', {}),
                bloom_taxonomy_distribution=data.get('bloom_taxonomy_distribution', {}),
                default_marks=data.get('default_marks', 1.0),
                default_negative_marks=data.get('default_negative_marks', 0.0),
                language=data.get('language', 'English')
            )

            if source_docs:
                job.source_documents.set(source_docs)
            from apps.audit.services import record_audit_event

            record_audit_event(
                action='generation_job.created',
                resource_type='generation_job',
                resource_id=job.pk,
                actor=request.user,
                institute=job.institute,
                metadata={'job_status': job.status},
            )

        # Synchronous execution within request boundary
        executed_job = execute_question_generation_job(job)

        return Response(
            QuestionGenerationJobSerializer(executed_job).data,
            status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Get Generation Job Candidates and Validation Diagnostics",
        responses={200: GeneratedCandidateRecordSerializer(many=True)}
    )
    @action(detail=True, methods=['get'], url_path='candidates')
    def candidates(self, request, pk=None):
        job = self.get_object()
        candidates = job.candidates.all().order_by('candidate_number')
        serializer = GeneratedCandidateRecordSerializer(candidates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
