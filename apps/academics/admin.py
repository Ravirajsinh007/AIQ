from django.contrib import admin
from .models import (
    Department,
    Program,
    AcademicYear,
    Semester,
    Batch,
    Section,
    Subject,
    ProgramSemesterSubject,
    Unit,
    Topic,
    LearningOutcome,
    SyllabusMapping,
    TeacherAssignment,
    StudentAcademicPlacement,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'institute', 'status', 'created_at')
    list_filter = ('institute', 'status')
    search_fields = ('code', 'name')


class SemesterInline(admin.TabularInline):
    model = Semester
    extra = 0


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'department', 'qualification_type', 'duration_years', 'total_semesters', 'status')
    list_filter = ('institute', 'department', 'qualification_type', 'status')
    search_fields = ('code', 'name')
    inlines = [SemesterInline]


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('label', 'institute', 'start_date', 'end_date', 'is_current', 'status')
    list_filter = ('institute', 'is_current', 'status')
    search_fields = ('label',)


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ('label', 'program', 'semester_number', 'status')
    list_filter = ('program__institute', 'program', 'status')
    search_fields = ('label',)


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('name', 'program', 'admission_year', 'status')
    list_filter = ('institute', 'program', 'status')
    search_fields = ('name',)
    inlines = [SectionInline]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'batch', 'status')
    list_filter = ('batch__program__institute', 'status')
    search_fields = ('name',)


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 0


class LearningOutcomeInline(admin.TabularInline):
    model = LearningOutcome
    extra = 0


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'institute', 'department', 'credit_hours', 'status')
    list_filter = ('institute', 'department', 'status')
    search_fields = ('code', 'name')
    inlines = [UnitInline, LearningOutcomeInline]


@admin.register(ProgramSemesterSubject)
class ProgramSemesterSubjectAdmin(admin.ModelAdmin):
    list_display = ('program', 'semester', 'subject', 'credits', 'is_mandatory', 'syllabus_version')
    list_filter = ('program__institute', 'program', 'is_mandatory')
    search_fields = ('subject__code', 'subject__name')


class TopicInline(admin.TabularInline):
    model = Topic
    extra = 0


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('unit_number', 'title', 'subject')
    list_filter = ('subject__institute', 'subject')
    search_fields = ('title',)
    inlines = [TopicInline]


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('title', 'unit', 'order')
    list_filter = ('unit__subject__institute', 'unit__subject')
    search_fields = ('title',)


@admin.register(LearningOutcome)
class LearningOutcomeAdmin(admin.ModelAdmin):
    list_display = ('code', 'subject', 'category')
    list_filter = ('subject__institute', 'category')
    search_fields = ('code', 'description')


@admin.register(SyllabusMapping)
class SyllabusMappingAdmin(admin.ModelAdmin):
    list_display = ('subject', 'academic_year', 'syllabus_version', 'status')
    list_filter = ('subject__institute', 'academic_year', 'status')
    search_fields = ('syllabus_reference',)


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'subject', 'academic_year', 'batch', 'section', 'status')
    list_filter = ('subject__institute', 'status', 'academic_year')
    search_fields = ('teacher__user__email', 'subject__code')


@admin.register(StudentAcademicPlacement)
class StudentAcademicPlacementAdmin(admin.ModelAdmin):
    list_display = ('student', 'program', 'batch', 'semester', 'section', 'status', 'effective_start_date', 'effective_end_date')
    list_filter = ('program__institute', 'status', 'program', 'batch', 'semester')
    search_fields = ('student__user__email', 'student__identifier')
