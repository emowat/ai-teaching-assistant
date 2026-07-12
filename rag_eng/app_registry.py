"""Aurora-backed application users, sections, and memberships."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
import uuid

from dotenv import load_dotenv

from rag_eng.auth.models import CurrentUser
from rag_eng.course_admin import CourseNotFoundError
from rag_eng.config import get_runtime_policy_config
from rag_eng.schemas import (
    AdminSection,
    AdminSectionCreate,
    AdminSectionMembershipCreate,
    AdminSectionMembershipUpdate,
    AdminSectionUpdate,
    AdminUser,
    AdminUserCreate,
    AdminUserUpdate,
    StudentBootstrapEndpoints,
    StudentBootstrapResponse,
    StudentBootstrapSection,
    StudentLaunchConfig,
    StudentBootstrapUser,
    ProfessorSectionStudent,
    ProfessorSectionAnalytics,
    ProfessorSectionAnalyticsPoint,
    ProfessorSectionStudentAnalytics,
    ProfessorSectionStudentAnalyticsPoint,
    ProfessorSectionSummary,
    ProfessorSectionStudentInviteCreate,
    ProfessorTeachingPlan,
    ProfessorTeachingPlanUpdate,
    ProfessorTeachingPlanWeek,
    ProfessorTeachingPlanWeekReference,
    ProfessorTeachingPlanWeekReferenceCreate,
    ProfessorTeachingPlanWeekCreate,
    ProfessorTeachingPlanWeekUpdate,
    ProfessorTeachingPlanWeekReferenceUpdate,
    SectionInstructionSettings,
    SectionInstructionSettingsUpdate,
    SectionLaunchConfig,
    SectionMembershipSummary,
)


load_dotenv()


class AppRegistryError(RuntimeError):
    """Base class for Aurora application-registry errors."""


class AppUserConflictError(AppRegistryError):
    """Raised when a user or membership would violate a unique constraint."""


class AppUserDisabledError(PermissionError):
    """Raised when an application user is disabled."""


class AppUserNotFoundError(LookupError):
    """Raised when an application user row cannot be found."""


class AppUserNotProvisionedError(PermissionError):
    """Raised when an authenticated user has no provisioned Aurora record."""


class MembershipConflictError(AppRegistryError):
    """Raised when a section membership already exists."""


class MembershipNotFoundError(LookupError):
    """Raised when a section membership cannot be found."""


class MembershipAccessDeniedError(PermissionError):
    """Raised when a membership does not authorize a requested action."""


class SectionConflictError(AppRegistryError):
    """Raised when a section would violate a unique constraint."""


class SectionNotFoundError(LookupError):
    """Raised when a section cannot be found."""


@dataclass(frozen=True)
class AppRegistryRuntimeConfig:
    """Runtime settings for the application registry helpers."""

    database_url: str | None
    connect_timeout_seconds: int


def _connect_postgres(database_url: str, connect_timeout_seconds: int):
    """Create a psycopg connection lazily so tests can stub it."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised only when missing
        raise RuntimeError("psycopg is required for app registry operations.") from exc

    return psycopg.connect(database_url, connect_timeout=connect_timeout_seconds)


def load_app_registry_runtime_config(
    env: Mapping[str, str] | None = None,
) -> AppRegistryRuntimeConfig:
    """Load Aurora app-registry settings from the current process environment."""
    source = env or os.environ
    return AppRegistryRuntimeConfig(
        database_url=source.get("COURSE_REGISTRY_DATABASE_URL") or source.get("DATABASE_URL"),
        connect_timeout_seconds=int(
            source.get(
                "COURSE_REGISTRY_CONNECT_TIMEOUT_SECONDS",
                source.get("INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS", "5"),
            )
        ),
    )


def _format_timestamp(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _clean_text(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_email(value: object | None) -> str:
    return _clean_text(value).casefold()


def _user_summary_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        user_id,
        cognito_sub,
        email,
        display_name,
        primary_role,
        status,
        consent_status,
        created_at,
        updated_at,
    ) = row[:9]
    return {
        "user_id": str(user_id),
        "cognito_sub": str(cognito_sub) if cognito_sub is not None else None,
        "email": _clean_text(email),
        "display_name": _clean_text(display_name),
        "primary_role": _clean_text(primary_role),
        "status": _clean_text(status),
        "consent_status": _clean_text(consent_status) or "pending",
        "created_at": _format_timestamp(created_at),
        "updated_at": _format_timestamp(updated_at),
    }


def _membership_summary_from_user_row(row: tuple[Any, ...]) -> SectionMembershipSummary:
    (
        user_id,
        section_id,
        section_display_name,
        course_id,
        course_display_name,
        role_in_section,
        status,
        created_at,
        updated_at,
    ) = row[:9]
    return SectionMembershipSummary(
        section_id=_clean_text(section_id),
        user_id=_clean_text(user_id),
        section_display_name=_clean_text(section_display_name),
        course_id=_clean_text(course_id),
        course_display_name=_clean_text(course_display_name),
        role_in_section=_clean_text(role_in_section),
        status=_clean_text(status),
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
    )


def _section_summary_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        section_id,
        course_id,
        course_display_name,
        display_name,
        term,
        is_active,
        created_at,
        updated_at,
    ) = row[:8]
    return {
        "section_id": _clean_text(section_id),
        "course_id": _clean_text(course_id),
        "course_display_name": _clean_text(course_display_name),
        "display_name": _clean_text(display_name),
        "term": _clean_text(term),
        "is_active": bool(is_active),
        "created_at": _format_timestamp(created_at),
        "updated_at": _format_timestamp(updated_at),
    }


def _membership_summary_from_section_row(row: tuple[Any, ...]) -> SectionMembershipSummary:
    (
        section_id,
        user_id,
        _cognito_sub,
        _email,
        _display_name,
        role_in_section,
        status,
        section_display_name,
        course_id,
        course_display_name,
        created_at,
        updated_at,
    ) = row[:12]
    return SectionMembershipSummary(
        section_id=_clean_text(section_id),
        user_id=_clean_text(user_id),
        section_display_name=_clean_text(section_display_name),
        course_id=_clean_text(course_id),
        course_display_name=_clean_text(course_display_name),
        role_in_section=_clean_text(role_in_section),
        status=_clean_text(status),
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
    )


def _student_row_from_tuple(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        user_id,
        cognito_sub,
        email,
        display_name,
        membership_status,
        role_in_section,
        session_count,
        last_session_at,
    ) = row[:8]
    return {
        "user_id": str(user_id),
        "cognito_sub": str(cognito_sub) if cognito_sub is not None else None,
        "email": _clean_text(email),
        "display_name": _clean_text(display_name),
        "membership_status": _clean_text(membership_status),
        "role_in_section": _clean_text(role_in_section),
        "session_count": int(session_count or 0),
        "last_session_at": _format_timestamp(last_session_at),
    }


def _student_section_from_row(
    row: tuple[Any, ...],
    *,
    launch_configs: list[StudentLaunchConfig] | None = None,
) -> StudentBootstrapSection:
    (
        section_id,
        course_id,
        course_display_name,
        display_name,
        term,
        is_active,
        membership_status,
        _created_at,
        _updated_at,
    ) = row[:9]
    return StudentBootstrapSection(
        section_id=_clean_text(section_id),
        course_id=_clean_text(course_id),
        course_display_name=_clean_text(course_display_name),
        display_name=_clean_text(display_name),
        term=_clean_text(term),
        is_active=bool(is_active),
        membership_status=_clean_text(membership_status),
        launch_configs=launch_configs or [],
    )


def _section_instruction_settings_from_row(
    row: tuple[Any, ...],
) -> SectionInstructionSettings:
    (
        section_id,
        student_access_enabled,
        week_resolution_mode,
        manual_current_week_number,
        teaching_plan_prompt_enabled,
        references_prompt_enabled,
        references_retrieval_enabled,
        created_at,
        updated_at,
    ) = row[:9]
    return SectionInstructionSettings(
        section_id=_clean_text(section_id),
        student_access_enabled=bool(student_access_enabled),
        week_resolution_mode=_clean_text(week_resolution_mode) or "manual",
        manual_current_week_number=(
            int(manual_current_week_number) if manual_current_week_number is not None else None
        ),
        teaching_plan_prompt_enabled=bool(teaching_plan_prompt_enabled),
        references_prompt_enabled=bool(references_prompt_enabled),
        references_retrieval_enabled=bool(references_retrieval_enabled),
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
    )


def _fetch_one_row(connection, query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


def _fetch_all_rows(connection, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def _require_database_url(runtime: AppRegistryRuntimeConfig) -> str:
    if not runtime.database_url:
        raise RuntimeError("Aurora course registry database URL is not configured.")
    return runtime.database_url


def _group_admin_users(
    user_rows: list[tuple[Any, ...]],
    membership_rows: list[tuple[Any, ...]],
) -> list[AdminUser]:
    memberships_by_user: dict[str, list[SectionMembershipSummary]] = defaultdict(list)
    for row in membership_rows:
        user_id = _clean_text(row[0])
        memberships_by_user[user_id].append(_membership_summary_from_user_row(row))

    users: list[AdminUser] = []
    for row in user_rows:
        user_data = _user_summary_from_row(row)
        users.append(
            AdminUser(
                **user_data,
                section_memberships=memberships_by_user.get(user_data["user_id"], []),
            )
        )
    return users


def _group_admin_sections(
    section_rows: list[tuple[Any, ...]],
    membership_rows: list[tuple[Any, ...]],
) -> list[AdminSection]:
    memberships_by_section: dict[str, list[SectionMembershipSummary]] = defaultdict(list)
    counts_by_section: dict[str, dict[str, int]] = defaultdict(
        lambda: {"professor": 0, "ta": 0, "student": 0}
    )

    for row in membership_rows:
        section_id = _clean_text(row[0])
        membership = _membership_summary_from_section_row(row)
        memberships_by_section[section_id].append(membership)
        if membership.status == "active" and membership.role_in_section in counts_by_section[section_id]:
            counts_by_section[section_id][membership.role_in_section] += 1

    sections: list[AdminSection] = []
    for row in section_rows:
        section_data = _section_summary_from_row(row)
        counts = counts_by_section.get(section_data["section_id"], {})
        sections.append(
            AdminSection(
                **section_data,
                professor_count=counts.get("professor", 0),
                ta_count=counts.get("ta", 0),
                student_count=counts.get("student", 0),
                memberships=memberships_by_section.get(section_data["section_id"], []),
            )
        )
    return sections


def _group_professor_sections(
    section_rows: list[tuple[Any, ...]],
    membership_rows: list[tuple[Any, ...]],
) -> list[ProfessorSectionSummary]:
    counts_by_section: dict[str, dict[str, int]] = defaultdict(
        lambda: {"professor": 0, "ta": 0, "student": 0}
    )

    for row in membership_rows:
        section_id = _clean_text(row[0])
        role_in_section = _clean_text(row[5])
        status = _clean_text(row[6])
        if status == "active" and role_in_section in counts_by_section[section_id]:
            counts_by_section[section_id][role_in_section] += 1

    sections: list[ProfessorSectionSummary] = []
    for row in section_rows:
        section_data = _section_summary_from_row(row)
        counts = counts_by_section.get(section_data["section_id"], {})
        sections.append(
            ProfessorSectionSummary(
                **section_data,
                professor_count=counts.get("professor", 0),
                ta_count=counts.get("ta", 0),
                student_count=counts.get("student", 0),
            )
        )
    return sections


def _insert_or_update_claim(
    connection,
    *,
    user_id: str,
    cognito_sub: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE users
            SET cognito_sub = %s,
                status = CASE WHEN status = 'disabled' THEN status ELSE 'active' END,
                updated_at = now()
            WHERE user_id = %s
            """,
            (cognito_sub, user_id),
        )


def _load_user_by_id(connection, user_id: str) -> tuple[Any, ...] | None:
    return _fetch_one_row(
        connection,
        """
        SELECT
          user_id,
          cognito_sub,
          email,
          display_name,
          primary_role,
          status,
          consent_status,
          created_at,
          updated_at
        FROM users
        WHERE user_id = %s
        """,
        (user_id,),
    )


def _load_user_by_email(connection, email: str) -> tuple[Any, ...] | None:
    return _fetch_one_row(
        connection,
        """
        SELECT
          user_id,
          cognito_sub,
          email,
          display_name,
          primary_role,
          status,
          consent_status,
          created_at,
          updated_at
        FROM users
        WHERE lower(email) = lower(%s)
        """,
        (email,),
    )


def _load_user_by_cognito_sub(connection, cognito_sub: str) -> tuple[Any, ...] | None:
    return _fetch_one_row(
        connection,
        """
        SELECT
          user_id,
          cognito_sub,
          email,
          display_name,
          primary_role,
          status,
          consent_status,
          created_at,
          updated_at
        FROM users
        WHERE cognito_sub = %s
        """,
        (cognito_sub,),
    )


def _assert_user_row(row: tuple[Any, ...] | None, cognito_sub: str) -> tuple[Any, ...]:
    if row is None:
        raise AppUserNotFoundError(f"No application user exists for cognito_sub={cognito_sub}.")
    return row


def grant_user_consent(
    user_id: str,
    *,
    runtime: "AppRegistryRuntimeConfig | None" = None,
) -> None:
    """Mark a student's consent as granted in the users table.

    Only transitions from 'pending' → 'granted'; no-ops if already granted.
    Withdrawn consent is permanent and cannot be re-granted via this function.
    """
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE users
                SET consent_status = 'granted',
                    consent_granted_at = now(),
                    updated_at = now()
                WHERE user_id = %s
                  AND consent_status = 'pending'
                """,
                (user_id,),
            )
        connection.commit()


def _load_section_by_id(connection, section_id: str) -> tuple[Any, ...] | None:
    return _fetch_one_row(
        connection,
        """
        SELECT
          s.section_id,
          s.course_id,
          c.display_name,
          s.display_name,
          s.term,
          s.is_active,
          s.created_at,
          s.updated_at
        FROM sections AS s
        INNER JOIN courses AS c ON c.course_id = s.course_id
        WHERE s.section_id = %s
        """,
        (section_id,),
    )


def _load_section_instruction_settings_row(
    connection,
    section_id: str,
) -> tuple[Any, ...] | None:
    return _fetch_one_row(
        connection,
        """
        SELECT
          section_id,
          student_access_enabled,
          week_resolution_mode,
          manual_current_week_number,
          teaching_plan_prompt_enabled,
          references_prompt_enabled,
          references_retrieval_enabled,
          created_at,
          updated_at
        FROM section_instruction_settings
        WHERE section_id = %s
        """,
        (section_id,),
    )


def _load_section_memberships_by_section(
    connection,
    section_id: str,
) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          sm.section_id,
          u.user_id,
          u.cognito_sub,
          u.email,
          u.display_name,
          sm.role_in_section,
          sm.status,
          s.display_name,
          s.course_id,
          c.display_name,
          sm.created_at,
          sm.updated_at
        FROM section_memberships AS sm
        INNER JOIN users AS u ON u.user_id = sm.user_id
        INNER JOIN sections AS s ON s.section_id = sm.section_id
        INNER JOIN courses AS c ON c.course_id = s.course_id
        WHERE sm.section_id = %s
        ORDER BY u.email ASC, sm.role_in_section ASC
        """,
        (section_id,),
    )


def _load_all_section_rows(connection) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          s.section_id,
          s.course_id,
          c.display_name,
          s.display_name,
          s.term,
          s.is_active,
          s.created_at,
          s.updated_at
        FROM sections AS s
        INNER JOIN courses AS c ON c.course_id = s.course_id
        ORDER BY s.section_id ASC
        """,
    )


def _load_accessible_section_rows(connection, user_id: str) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          s.section_id,
          s.course_id,
          c.display_name,
          s.display_name,
          s.term,
          s.is_active,
          s.created_at,
          s.updated_at
        FROM sections AS s
        INNER JOIN courses AS c ON c.course_id = s.course_id
        WHERE EXISTS (
          SELECT 1
          FROM section_memberships AS sm
          WHERE sm.section_id = s.section_id
            AND sm.user_id = %s
            AND sm.status = 'active'
            AND sm.role_in_section IN ('professor', 'ta')
        )
          AND s.is_active = TRUE
        ORDER BY s.section_id ASC
        """,
        (user_id,),
    )


def _load_all_user_rows(connection) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          user_id,
          cognito_sub,
          email,
          display_name,
          primary_role,
          status,
          consent_status,
          created_at,
          updated_at
        FROM users
        ORDER BY email ASC
        """,
    )


def _load_user_membership_rows(connection) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          u.user_id,
          s.section_id,
          s.display_name,
          s.course_id,
          c.display_name,
          sm.role_in_section,
          sm.status,
          sm.created_at,
          sm.updated_at
        FROM section_memberships AS sm
        INNER JOIN users AS u ON u.user_id = sm.user_id
        INNER JOIN sections AS s ON s.section_id = sm.section_id
        INNER JOIN courses AS c ON c.course_id = s.course_id
        ORDER BY u.email ASC, s.section_id ASC
        """,
    )


def _load_student_rows_for_section(
    connection,
    section_id: str,
    *,
    include_inactive: bool = False,
) -> list[tuple[Any, ...]]:
    status_clause = "" if include_inactive else "AND sm.status = 'active'"
    return _fetch_all_rows(
        connection,
        f"""
        SELECT
          u.user_id,
          u.cognito_sub,
          u.email,
          u.display_name,
          sm.status,
          sm.role_in_section,
          COALESCE(stats.session_count, 0) AS session_count,
          stats.last_session_at
        FROM section_memberships AS sm
        INNER JOIN users AS u ON u.user_id = sm.user_id
        LEFT JOIN (
          SELECT
            user_sub,
            COUNT(*) AS session_count,
            MAX(last_seen_at) AS last_session_at
          FROM tutor_sessions
          WHERE section_id = %s
          GROUP BY user_sub
        ) AS stats ON stats.user_sub = u.cognito_sub
        WHERE sm.section_id = %s
          AND sm.role_in_section = 'student'
          {status_clause}
        ORDER BY
          CASE sm.status
            WHEN 'active' THEN 0
            WHEN 'invited' THEN 1
            WHEN 'dropped' THEN 2
            WHEN 'disabled' THEN 3
            ELSE 4
          END,
          u.display_name ASC,
          u.email ASC
        """,
        (section_id, section_id),
    )


def student_surface_allowed_roles(primary_role: str | None) -> set[str]:
    """Return the section membership roles allowed on the student surface."""
    role = _clean_text(primary_role)
    if role in {"admin", "professor"}:
        return {"student", "professor", "ta"}
    return {"student"}


def _load_student_section_rows(
    connection,
    user_id: str,
    *,
    allowed_roles: set[str] | None = None,
) -> list[tuple[Any, ...]]:
    allowed = {role for role in (allowed_roles or {"student"}) if role in {"student", "professor", "ta"}}
    if not allowed:
        return []

    if allowed == {"student"}:
        sql = """
        SELECT
          s.section_id,
          s.course_id,
          c.display_name,
          s.display_name,
          s.term,
          s.is_active,
          sm.status,
          s.created_at,
          s.updated_at
        FROM section_memberships AS sm
        INNER JOIN sections AS s ON s.section_id = sm.section_id
        INNER JOIN courses AS c ON c.course_id = s.course_id
        LEFT JOIN section_instruction_settings AS sis ON sis.section_id = s.section_id
        WHERE sm.user_id = %s
          AND sm.role_in_section = 'student'
          AND sm.status = 'active'
          AND s.is_active = TRUE
          AND COALESCE(sis.student_access_enabled, TRUE) = TRUE
        ORDER BY s.section_id ASC
        """
    else:
        sql = """
        SELECT
          s.section_id,
          s.course_id,
          c.display_name,
          s.display_name,
          s.term,
          s.is_active,
          sm.status,
          s.created_at,
          s.updated_at
        FROM section_memberships AS sm
        INNER JOIN sections AS s ON s.section_id = sm.section_id
        INNER JOIN courses AS c ON c.course_id = s.course_id
        LEFT JOIN section_instruction_settings AS sis ON sis.section_id = s.section_id
        WHERE sm.user_id = %s
          AND sm.role_in_section IN ('student', 'professor', 'ta')
          AND sm.status = 'active'
          AND s.is_active = TRUE
          AND COALESCE(sis.student_access_enabled, TRUE) = TRUE
        ORDER BY s.section_id ASC
        """
    return _fetch_all_rows(connection, sql, (user_id,))


def _load_section_launch_config_rows(
    connection,
    section_id: str,
) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          section_id,
          launch_id,
          label,
          repo_url,
          template_url,
          default_branch,
          enabled,
          sort_order
        FROM section_launch_configs
        WHERE section_id = %s
        ORDER BY sort_order ASC, launch_id ASC
        """,
        (section_id,),
    )


def _launch_config_from_row(
    row: tuple[Any, ...],
    *,
    model_cls: type[SectionLaunchConfig] = StudentLaunchConfig,
) -> SectionLaunchConfig:
    (
        _section_id,
        launch_id,
        label,
        repo_url,
        template_url,
        default_branch,
        enabled,
        sort_order,
    ) = row[:8]
    return model_cls(
        launch_id=_clean_text(launch_id),
        label=_clean_text(label),
        repo_url=_clean_text(repo_url),
        template_url=_clean_text(template_url),
        default_branch=_clean_text(default_branch) or "main",
        enabled=bool(enabled),
        sort_order=int(sort_order or 0),
    )


def _json_list_from_value(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if isinstance(value, tuple):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            cleaned = _clean_text(value)
            return [cleaned] if cleaned else []
        if isinstance(parsed, list):
            return [_clean_text(item) for item in parsed if _clean_text(item)]
        cleaned = _clean_text(parsed)
        return [cleaned] if cleaned else []
    cleaned = _clean_text(value)
    return [cleaned] if cleaned else []


def _load_section_teaching_plan_row(connection, section_id: str) -> tuple[Any, ...] | None:
    return _fetch_one_row(
        connection,
        """
        SELECT
          teaching_plan_id,
          section_id,
          version,
          status,
          title,
          summary,
          created_by,
          published_by,
          published_at,
          created_at,
          updated_at
        FROM teaching_plans
        WHERE section_id = %s
        """,
        (section_id,),
    )


def _load_section_teaching_plan_week_rows(
    connection,
    teaching_plan_id: str,
) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          week_id,
          teaching_plan_id,
          week_number,
          title,
          topic,
          start_date,
          end_date,
          learning_objectives,
          instructional_guidance,
          status,
          student_visibility_status,
          available_from,
          available_until,
          created_at,
          updated_at
        FROM teaching_plan_weeks
        WHERE teaching_plan_id = %s
        ORDER BY week_number ASC, week_id ASC
        """,
        (teaching_plan_id,),
    )


def _load_section_teaching_plan_week_reference_rows(
    connection,
    teaching_plan_id: str,
) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          r.reference_id,
          r.week_id,
          r.section_id,
          r.title,
          r.reference_type,
          r.url,
          r.course_document_key,
          r.notes,
          r.enabled,
          r.include_in_prompt,
          r.include_in_retrieval,
          r.sort_order,
          r.created_at,
          r.updated_at
        FROM teaching_plan_week_references AS r
        INNER JOIN teaching_plan_weeks AS tw
          ON tw.week_id = r.week_id
        WHERE tw.teaching_plan_id = %s
        ORDER BY tw.week_number ASC, r.sort_order ASC, r.reference_id ASC
        """,
        (teaching_plan_id,),
    )


def _load_section_teaching_plan_week_reference_rows_for_week(
    connection,
    section_id: str,
    week_id: str,
) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
        SELECT
          r.reference_id,
          r.week_id,
          r.section_id,
          r.title,
          r.reference_type,
          r.url,
          r.course_document_key,
          r.notes,
          r.enabled,
          r.include_in_prompt,
          r.include_in_retrieval,
          r.sort_order,
          r.created_at,
          r.updated_at
        FROM teaching_plan_week_references AS r
        INNER JOIN teaching_plan_weeks AS tw
          ON tw.week_id = r.week_id
        INNER JOIN teaching_plans AS tp
          ON tp.teaching_plan_id = tw.teaching_plan_id
        WHERE tp.section_id = %s
          AND tw.week_id = %s
        ORDER BY r.sort_order ASC, r.reference_id ASC
        """,
        (section_id, week_id),
    )


def _teaching_plan_week_reference_from_row(
    row: tuple[Any, ...],
) -> ProfessorTeachingPlanWeekReference:
    (
        reference_id,
        week_id,
        section_id,
        title,
        reference_type,
        url,
        course_document_key,
        notes,
        enabled,
        include_in_prompt,
        include_in_retrieval,
        sort_order,
        created_at,
        updated_at,
    ) = row[:14]
    return ProfessorTeachingPlanWeekReference(
        reference_id=_clean_text(reference_id),
        week_id=_clean_text(week_id),
        section_id=_clean_text(section_id),
        title=_clean_text(title),
        reference_type=_clean_text(reference_type) or "course_doc",
        url=_clean_text(url),
        course_document_key=_clean_text(course_document_key),
        notes=_clean_text(notes),
        enabled=bool(enabled),
        include_in_prompt=bool(include_in_prompt),
        include_in_retrieval=bool(include_in_retrieval),
        sort_order=int(sort_order or 0),
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
    )


def _teaching_plan_week_from_row(
    row: tuple[Any, ...],
    *,
    references: list[ProfessorTeachingPlanWeekReference] | None = None,
) -> ProfessorTeachingPlanWeek:
    (
        week_id,
        teaching_plan_id,
        week_number,
        title,
        topic,
        start_date,
        end_date,
        learning_objectives,
        instructional_guidance,
        status,
        student_visibility_status,
        available_from,
        available_until,
        created_at,
        updated_at,
    ) = row[:15]
    return ProfessorTeachingPlanWeek(
        week_id=_clean_text(week_id),
        teaching_plan_id=_clean_text(teaching_plan_id),
        week_number=int(week_number or 0),
        title=_clean_text(title),
        topic=_clean_text(topic),
        start_date=_format_timestamp(start_date) or None,
        end_date=_format_timestamp(end_date) or None,
        learning_objectives=_json_list_from_value(learning_objectives),
        instructional_guidance=_clean_text(instructional_guidance),
        status=_clean_text(status) or "draft",
        student_visibility_status=_clean_text(student_visibility_status) or "hidden",
        available_from=_format_timestamp(available_from) or None,
        available_until=_format_timestamp(available_until) or None,
        references=list(references or []),
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
    )


def _teaching_plan_from_row(
    row: tuple[Any, ...] | None,
    *,
    weeks: list[ProfessorTeachingPlanWeek] | None = None,
) -> ProfessorTeachingPlan:
    if row is None:
        return ProfessorTeachingPlan(section_id="")

    (
        teaching_plan_id,
        section_id,
        version,
        status,
        title,
        summary,
        created_by,
        published_by,
        published_at,
        created_at,
        updated_at,
    ) = row[:11]
    return ProfessorTeachingPlan(
        teaching_plan_id=_clean_text(teaching_plan_id) or None,
        section_id=_clean_text(section_id),
        version=int(version or 1),
        status=_clean_text(status) or "draft",
        title=_clean_text(title),
        summary=_clean_text(summary),
        created_by_user_id=_clean_text(created_by) or None,
        published_by_user_id=_clean_text(published_by) or None,
        published_at=_format_timestamp(published_at) or None,
        weeks=list(weeks or []),
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
    )


def _load_professor_section_teaching_plan(
    connection,
    section_id: str,
) -> ProfessorTeachingPlan:
    plan_row = _load_section_teaching_plan_row(connection, section_id)
    if plan_row is None:
        return ProfessorTeachingPlan(section_id=section_id)
    teaching_plan_id = _clean_text(plan_row[0])
    week_rows = _load_section_teaching_plan_week_rows(connection, teaching_plan_id)
    reference_rows = _load_section_teaching_plan_week_reference_rows(
        connection,
        teaching_plan_id,
    )
    references_by_week_id: dict[str, list[ProfessorTeachingPlanWeekReference]] = defaultdict(list)
    for reference_row in reference_rows:
        reference = _teaching_plan_week_reference_from_row(reference_row)
        references_by_week_id[reference.week_id].append(reference)
    weeks = [
        _teaching_plan_week_from_row(
            week_row,
            references=references_by_week_id.get(_clean_text(week_row[0]) or "", []),
        )
        for week_row in week_rows
    ]
    return _teaching_plan_from_row(plan_row, weeks=weeks)


def _load_professor_section_teaching_plan_week(
    connection,
    section_id: str,
    week_id: str,
) -> ProfessorTeachingPlanWeek | None:
    row = _fetch_one_row(
        connection,
        """
        SELECT
          tw.week_id,
          tw.teaching_plan_id,
          tw.week_number,
          tw.title,
          tw.topic,
          tw.start_date,
          tw.end_date,
          tw.learning_objectives,
          tw.instructional_guidance,
          tw.status,
          tw.student_visibility_status,
          tw.available_from,
          tw.available_until,
          tw.created_at,
          tw.updated_at
        FROM teaching_plan_weeks AS tw
        INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id
        WHERE tp.section_id = %s
          AND tw.week_id = %s
        """,
        (section_id, week_id),
    )
    if row is None:
        return None

    reference_rows = _load_section_teaching_plan_week_reference_rows_for_week(
        connection,
        section_id,
        week_id,
    )
    references = [
        _teaching_plan_week_reference_from_row(reference_row)
        for reference_row in reference_rows
    ]
    return _teaching_plan_week_from_row(row, references=references)


def _build_week_references_prompt_block(
    *,
    section_id: str,
    week_number: int,
    references: list[ProfessorTeachingPlanWeekReference],
) -> str:
    prompt_references = [
        reference
        for reference in references
        if reference.enabled and reference.include_in_prompt
    ]
    retrieval_references = [
        reference
        for reference in references
        if reference.enabled and reference.include_in_retrieval
    ]
    if not prompt_references and not retrieval_references:
        return ""

    lines = [
        "[Section_Week_References]",
        f"Section ID: {section_id}",
        f"Week: {week_number}",
    ]
    if prompt_references:
        lines.append("Prompt References:")
        for reference in prompt_references:
            details = [f"title={reference.title or 'Untitled Reference'}"]
            details.append(f"type={reference.reference_type}")
            if reference.course_document_key:
                details.append(f"course_document_key={reference.course_document_key}")
            if reference.url:
                details.append(f"url={reference.url}")
            if reference.notes:
                details.append(f"notes={reference.notes}")
            lines.append(f"- {'; '.join(details)}")
    if retrieval_references:
        lines.append("Retrieval References:")
        for reference in retrieval_references:
            details = [f"title={reference.title or 'Untitled Reference'}"]
            details.append(f"type={reference.reference_type}")
            if reference.course_document_key:
                details.append(f"course_document_key={reference.course_document_key}")
            if reference.url:
                details.append(f"url={reference.url}")
            lines.append(f"- {'; '.join(details)}")

    lines.append(
        "Advisory Notes: Use these section-approved references only as supplemental context. Do not browse beyond the listed resources."
    )
    return "\n".join(lines)


def _ensure_professor_section_teaching_plan(
    connection,
    *,
    section_id: str,
    created_by_user_id: str,
) -> str:
    plan_row = _load_section_teaching_plan_row(connection, section_id)
    if plan_row is not None:
        return _clean_text(plan_row[0])

    teaching_plan_id = str(uuid.uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO teaching_plans (
              teaching_plan_id,
              section_id,
              created_by
            )
            VALUES (%s, %s, %s)
            """,
            (teaching_plan_id, section_id, created_by_user_id),
        )
    return teaching_plan_id


def _load_most_recent_student_section_id(connection, user_sub: str) -> str | None:
    row = _fetch_one_row(
        connection,
        """
        SELECT section_id
        FROM tutor_sessions
        WHERE user_sub = %s
          AND section_id IS NOT NULL
        ORDER BY last_seen_at DESC, updated_at DESC
        LIMIT 1
        """,
        (user_sub,),
    )
    if row is None:
        return None
    return _clean_text(row[0]) or None


def resolve_application_user(
    current_user: CurrentUser,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Resolve or claim the Aurora application user for a Cognito identity."""
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    if current_user.primary_role not in {"admin", "professor", "student"}:
        raise AppUserNotProvisionedError(
            "Application user resolution is only required for admin, professor, and student roles."
        )

    cognito_sub = _clean_text(current_user.cognito_sub)
    if not cognito_sub:
        raise AppUserNotProvisionedError("Current user does not include a Cognito subject claim.")

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        row = _load_user_by_cognito_sub(connection, cognito_sub) if cognito_sub else None
        if row is not None:
            if _clean_text(row[5]) == "disabled":
                raise AppUserDisabledError(f"Application user {current_user.email or cognito_sub} is disabled.")
            if _clean_text(row[5]) != "active":
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE users
                        SET status = 'active',
                            updated_at = now()
                        WHERE user_id = %s
                        """,
                        (str(row[0]),),
                    )
                row = _load_user_by_cognito_sub(connection, cognito_sub) or row
        else:
            email = _normalize_email(current_user.email)
            if not email:
                raise AppUserNotProvisionedError("Current user does not include an email claim.")
            row = _load_user_by_email(connection, email)
            if row is None:
                raise AppUserNotProvisionedError(
                    f"No invited application user exists for {email}."
                )
            existing_cognito_sub = _clean_text(row[1])
            if existing_cognito_sub and existing_cognito_sub != cognito_sub:
                raise AppUserConflictError(
                    f"Application user {email} is already linked to another Cognito identity."
                )
            if _clean_text(row[5]) == "disabled":
                raise AppUserDisabledError(f"Application user {email} is disabled.")
            if existing_cognito_sub != cognito_sub:
                _insert_or_update_claim(connection, user_id=str(row[0]), cognito_sub=cognito_sub)
            if _clean_text(row[5]) != "active":
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE users
                        SET status = 'active',
                            updated_at = now()
                        WHERE user_id = %s
                        """,
                        (str(row[0]),),
                    )
            row = _load_user_by_cognito_sub(connection, cognito_sub) or _load_user_by_email(connection, email)

    return _user_summary_from_row(_assert_user_row(row, cognito_sub))


def sync_application_user(
    current_user: CurrentUser,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> dict[str, Any] | None:
    """Best-effort claim of an invited Aurora application user after login."""
    if current_user.primary_role not in {"admin", "professor", "student"}:
        return None
    return resolve_application_user(current_user, runtime=runtime)


def require_section_membership(
    current_user: CurrentUser,
    section_id: str,
    *,
    allowed_roles: set[str] | None = None,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Ensure the current user is actively enrolled in a section."""
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    app_user = resolve_application_user(current_user, runtime=runtime)
    allowed = allowed_roles or {"professor", "ta"}

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        membership = _fetch_one_row(
            connection,
            """
            SELECT role_in_section, status
            FROM section_memberships
            WHERE section_id = %s
              AND user_id = %s
            """,
            (section_id, app_user["user_id"]),
        )

    if membership is None:
        raise MembershipAccessDeniedError(
            f"User is not assigned to section {section_id}."
        )

    role_in_section, status = membership[:2]
    if _clean_text(status) != "active" or _clean_text(role_in_section) not in allowed:
        raise MembershipAccessDeniedError(
            f"User does not have an active permitted membership for section {section_id}."
        )
    return app_user


def require_student_section_access(
    current_user: CurrentUser,
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Ensure a student-surface request is allowed for the requested section."""
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    app_user = require_section_membership(
        current_user,
        section_id,
        allowed_roles=student_surface_allowed_roles(current_user.primary_role),
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        row = _load_section_instruction_settings_row(connection, section_id)
    if row is not None and not bool(row[1]):
        raise MembershipAccessDeniedError(
            f"Student access is paused for section {section_id}."
        )
    return app_user


def list_admin_users(
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[AdminUser]:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        user_rows = _load_all_user_rows(connection)
        membership_rows = _load_user_membership_rows(connection)

    return _group_admin_users(user_rows, membership_rows)


def get_admin_user(
    user_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminUser:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        user_row = _load_user_by_id(connection, user_id)
        if user_row is None:
            raise AppUserNotFoundError(f"User {user_id} was not found.")
        membership_rows = _fetch_all_rows(
            connection,
            """
            SELECT
              u.user_id,
              s.section_id,
              s.display_name,
              s.course_id,
              c.display_name,
              sm.role_in_section,
              sm.status,
              sm.created_at,
              sm.updated_at
            FROM section_memberships AS sm
            INNER JOIN users AS u ON u.user_id = sm.user_id
            INNER JOIN sections AS s ON s.section_id = sm.section_id
            INNER JOIN courses AS c ON c.course_id = s.course_id
            WHERE u.user_id = %s
            ORDER BY s.section_id ASC
            """,
            (user_id,),
        )

    return _group_admin_users([user_row], membership_rows)[0]


def create_admin_user(
    payload: AdminUserCreate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminUser:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    email = _normalize_email(payload.email)
    display_name = _clean_text(payload.display_name)
    primary_role = _clean_text(payload.primary_role)
    status = _clean_text(payload.status)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        if _load_user_by_email(connection, email) is not None:
            raise AppUserConflictError(f"User with email {email} already exists.")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (
                  cognito_sub,
                  email,
                  display_name,
                  primary_role,
                  status
                )
                VALUES (NULL, %s, %s, %s, %s)
                RETURNING user_id
                """,
                (email, display_name, primary_role, status),
            )
            user_id = str(cursor.fetchone()[0])

    return get_admin_user(user_id, runtime=runtime)


def update_admin_user(
    user_id: str,
    payload: AdminUserUpdate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminUser:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    fields: list[str] = []
    values: list[Any] = []

    if payload.display_name is not None:
        fields.append("display_name = %s")
        values.append(_clean_text(payload.display_name))
    if payload.primary_role is not None:
        fields.append("primary_role = %s")
        values.append(_clean_text(payload.primary_role))
    if payload.status is not None:
        fields.append("status = %s")
        values.append(_clean_text(payload.status))

    if not fields:
        raise ValueError("At least one user field must be provided.")

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE users
                SET {", ".join(fields)},
                    updated_at = now()
                WHERE user_id = %s
                """,
                tuple(values + [user_id]),
            )
            if cursor.rowcount == 0:
                raise AppUserNotFoundError(f"User {user_id} was not found.")

    return get_admin_user(user_id, runtime=runtime)


def list_admin_sections(
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[AdminSection]:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        section_rows = _load_all_section_rows(connection)
        membership_rows = _fetch_all_rows(
            connection,
            """
            SELECT
              sm.section_id,
              u.user_id,
              u.cognito_sub,
              u.email,
              u.display_name,
              sm.role_in_section,
              sm.status,
              s.display_name,
              s.course_id,
              c.display_name,
              sm.created_at,
              sm.updated_at
            FROM section_memberships AS sm
            INNER JOIN users AS u ON u.user_id = sm.user_id
            INNER JOIN sections AS s ON s.section_id = sm.section_id
            INNER JOIN courses AS c ON c.course_id = s.course_id
            ORDER BY sm.section_id ASC, u.email ASC
            """,
        )

    return _group_admin_sections(section_rows, membership_rows)


def get_admin_section(
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminSection:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        section_row = _load_section_by_id(connection, section_id)
        if section_row is None:
            raise SectionNotFoundError(f"Section {section_id} was not found.")
        membership_rows = _load_section_memberships_by_section(connection, section_id)

    return _group_admin_sections([section_row], membership_rows)[0]


def _ensure_course_exists(connection, course_id: str) -> None:
    row = _fetch_one_row(
        connection,
        "SELECT course_id FROM courses WHERE course_id = %s",
        (course_id,),
    )
    if row is None:
        raise CourseNotFoundError(course_id)


def create_admin_section(
    payload: AdminSectionCreate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminSection:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    section_id = _clean_text(payload.section_id)
    course_id = _clean_text(payload.course_id)
    display_name = _clean_text(payload.display_name)
    term = _clean_text(payload.term)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        if _load_section_by_id(connection, section_id) is not None:
            raise SectionConflictError(f"Section {section_id} already exists.")
        _ensure_course_exists(connection, course_id)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sections (
                  section_id,
                  course_id,
                  display_name,
                  term,
                  is_active
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (section_id, course_id, display_name, term, payload.is_active),
            )

    return get_admin_section(section_id, runtime=runtime)


def update_admin_section(
    section_id: str,
    payload: AdminSectionUpdate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminSection:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    fields: list[str] = []
    values: list[Any] = []

    if payload.display_name is not None:
        fields.append("display_name = %s")
        values.append(_clean_text(payload.display_name))
    if payload.term is not None:
        fields.append("term = %s")
        values.append(_clean_text(payload.term))
    if payload.is_active is not None:
        fields.append("is_active = %s")
        values.append(bool(payload.is_active))

    if not fields:
        raise ValueError("At least one section field must be provided.")

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE sections
                SET {", ".join(fields)},
                    updated_at = now()
                WHERE section_id = %s
                """,
                tuple(values + [section_id]),
            )
            if cursor.rowcount == 0:
                raise SectionNotFoundError(f"Section {section_id} was not found.")

    return get_admin_section(section_id, runtime=runtime)


def create_section_membership(
    section_id: str,
    payload: AdminSectionMembershipCreate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminSection:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    user_id = _clean_text(payload.user_id)
    role_in_section = _clean_text(payload.role_in_section)
    status = _clean_text(payload.status)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        if _load_section_by_id(connection, section_id) is None:
            raise SectionNotFoundError(f"Section {section_id} was not found.")
        if _load_user_by_id(connection, user_id) is None:
            raise AppUserNotFoundError(f"User {user_id} was not found.")
        existing = _fetch_one_row(
            connection,
            """
            SELECT section_id
            FROM section_memberships
            WHERE section_id = %s
              AND user_id = %s
            """,
            (section_id, user_id),
        )
        if existing is not None:
            raise MembershipConflictError(
                f"Membership for user {user_id} in section {section_id} already exists."
            )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO section_memberships (
                  section_id,
                  user_id,
                  role_in_section,
                  status
                )
                VALUES (%s, %s, %s, %s)
                """,
                (section_id, user_id, role_in_section, status),
            )

    return get_admin_section(section_id, runtime=runtime)


def update_section_membership(
    section_id: str,
    user_id: str,
    payload: AdminSectionMembershipUpdate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> AdminSection:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    fields: list[str] = []
    values: list[Any] = []

    if payload.role_in_section is not None:
        fields.append("role_in_section = %s")
        values.append(_clean_text(payload.role_in_section))
    if payload.status is not None:
        fields.append("status = %s")
        values.append(_clean_text(payload.status))

    if not fields:
        raise ValueError("At least one membership field must be provided.")

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE section_memberships
                SET {", ".join(fields)},
                    updated_at = now()
                WHERE section_id = %s
                  AND user_id = %s
                """,
                tuple(values + [section_id, user_id]),
            )
            if cursor.rowcount == 0:
                raise MembershipNotFoundError(
                    f"Membership for user {user_id} in section {section_id} was not found."
                )

    return get_admin_section(section_id, runtime=runtime)


def list_professor_sections(
    current_user: CurrentUser,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[ProfessorSectionSummary]:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    app_user = resolve_application_user(current_user, runtime=runtime)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        section_rows = _load_accessible_section_rows(connection, app_user["user_id"])
        membership_rows = _fetch_all_rows(
            connection,
            """
            SELECT
              sm.section_id,
              u.user_id,
              u.cognito_sub,
              u.email,
              u.display_name,
              sm.role_in_section,
              sm.status,
              s.display_name,
              s.course_id,
              c.display_name,
              sm.created_at,
              sm.updated_at
            FROM section_memberships AS sm
            INNER JOIN users AS u ON u.user_id = sm.user_id
            INNER JOIN sections AS s ON s.section_id = sm.section_id
            INNER JOIN courses AS c ON c.course_id = s.course_id
            WHERE sm.section_id IN (
              SELECT s2.section_id
              FROM sections AS s2
              WHERE s2.is_active = TRUE
                AND EXISTS (
                  SELECT 1
                  FROM section_memberships AS sm2
                  WHERE sm2.section_id = s2.section_id
                    AND sm2.user_id = %s
                    AND sm2.status = 'active'
                    AND sm2.role_in_section IN ('professor', 'ta')
                )
            )
            ORDER BY sm.section_id ASC, u.email ASC
            """,
            (app_user["user_id"],),
        )

    return _group_professor_sections(section_rows, membership_rows)


def get_professor_section_analytics(
    current_user: CurrentUser,
    section_id: str,
    *,
    tz: str = "America/Los_Angeles",
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorSectionAnalytics:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    import pytz

    if tz not in pytz.all_timezones:
        raise ValueError("Invalid timezone")

    pt_tz = pytz.timezone(tz)
    now = datetime.now(pt_tz)
    timeline: dict[str, dict[str, int | str]] = {}
    for days_ago in range(6, -1, -1):
        day = (now - timedelta(days=days_ago)).strftime("%a")
        timeline[day] = {"day": day, "sessions": 0, "active_students": 0}

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        section_row = _load_section_by_id(connection, section_id)
        if section_row is None:
            raise SectionNotFoundError(f"Section {section_id} was not found.")

        membership_rows = _load_section_memberships_by_section(connection, section_id)
        counts = {"professor": 0, "ta": 0, "student": 0}
        for row in membership_rows:
            role_in_section = _clean_text(row[5])
            status = _clean_text(row[6])
            if status == "active" and role_in_section in counts:
                counts[role_in_section] += 1

        section_summary = ProfessorSectionSummary(
            **_section_summary_from_row(section_row),
            professor_count=counts["professor"],
            ta_count=counts["ta"],
            student_count=counts["student"],
        )

        totals_row = _fetch_one_row(
            connection,
            """
            SELECT
              COUNT(*) AS session_count,
              COUNT(DISTINCT user_sub) AS active_students
            FROM tutor_sessions
            WHERE section_id = %s
              AND last_seen_at >= (CURRENT_TIMESTAMP AT TIME ZONE %s)::DATE - INTERVAL '6 days'
            """,
            (section_id, tz),
        )
        totals = {
            "sessions": int(totals_row[0]) if totals_row and totals_row[0] is not None else 0,
            "active_students": int(totals_row[1]) if totals_row and totals_row[1] is not None else 0,
        }

        daily_rows = _fetch_all_rows(
            connection,
            """
            WITH session_facts AS (
              SELECT
                DATE((last_seen_at AT TIME ZONE %s)) AS day_date,
                user_sub
              FROM tutor_sessions
              WHERE section_id = %s
                AND last_seen_at >= (CURRENT_TIMESTAMP AT TIME ZONE %s)::DATE - INTERVAL '6 days'
            ),
            daily_sessions AS (
              SELECT
                day_date,
                COUNT(*) AS sessions,
                COUNT(DISTINCT user_sub) AS active_students
              FROM session_facts
              GROUP BY day_date
            )
            SELECT TO_CHAR(day_date, 'Dy') AS day, sessions, active_students
            FROM daily_sessions
            ORDER BY day_date ASC
            """,
            (tz, section_id, tz),
        )
        for day, sessions, active_students in daily_rows:
            key = str(day)
            if key not in timeline:
                continue
            timeline[key]["sessions"] = int(sessions)
            timeline[key]["active_students"] = int(active_students)

        student_rows = _load_student_rows_for_section(connection, section_id)

    top_students = sorted(
        (
            ProfessorSectionStudent(
                user_id=_clean_text(row[0]),
                cognito_sub=_clean_text(row[1]) or None,
                email=_clean_text(row[2]),
                display_name=_clean_text(row[3]),
                membership_status=_clean_text(row[4]),
                role_in_section=_clean_text(row[5]),
                session_count=int(row[6]) if row[6] is not None else 0,
                last_session_at=_format_timestamp(row[7]),
            )
            for row in student_rows
        ),
        key=lambda student: (
            -student.session_count,
            student.last_session_at or "",
            student.display_name.casefold(),
            student.email.casefold(),
        ),
    )[:5]

    weekly_activity = [
        ProfessorSectionAnalyticsPoint(
            day=str(values["day"]),
            sessions=int(values["sessions"]),
            active_students=int(values["active_students"]),
        )
        for values in timeline.values()
    ]

    return ProfessorSectionAnalytics(
        section=section_summary,
        sessions_last_7_days=totals["sessions"],
        active_students_last_7_days=totals["active_students"],
        weekly_activity=weekly_activity,
        top_students=top_students,
        generated_at=_format_timestamp(datetime.now(timezone.utc)),
    )


def get_professor_section_student_analytics(
    current_user: CurrentUser,
    section_id: str,
    student_user_id: str,
    *,
    tz: str = "America/Los_Angeles",
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorSectionStudentAnalytics:
    """Return a student drill-down summary for one professor-managed section."""
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    import pytz

    if tz not in pytz.all_timezones:
        raise ValueError("Invalid timezone")

    pt_tz = pytz.timezone(tz)
    now = datetime.now(pt_tz)
    timeline: dict[str, dict[str, int | str]] = {}
    for days_ago in range(6, -1, -1):
        day = (now - timedelta(days=days_ago)).strftime("%a")
        timeline[day] = {"day": day, "sessions": 0, "turns": 0}

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        section_row = _load_section_by_id(connection, section_id)
        if section_row is None:
            raise SectionNotFoundError(f"Section {section_id} was not found.")
        membership_rows = _load_section_memberships_by_section(connection, section_id)
        counts = {"professor": 0, "ta": 0, "student": 0}
        for row in membership_rows:
            role_in_section = _clean_text(row[5])
            status = _clean_text(row[6])
            if status == "active" and role_in_section in counts:
                counts[role_in_section] += 1

        student_row = _load_user_by_id(connection, student_user_id)
        if student_row is None:
            raise AppUserNotFoundError(f"User {student_user_id} was not found.")

        membership_row = _fetch_one_row(
            connection,
            """
            SELECT
              sm.role_in_section,
              sm.status
            FROM section_memberships AS sm
            WHERE sm.section_id = %s
              AND sm.user_id = %s
            """,
            (section_id, student_user_id),
        )
        if membership_row is None:
            raise MembershipNotFoundError(
                f"Student {student_user_id} is not assigned to section {section_id}."
            )

        membership_role = _clean_text(membership_row[0])
        membership_status = _clean_text(membership_row[1])
        if membership_role != "student":
            raise MembershipAccessDeniedError(
                f"User {student_user_id} is not a student in section {section_id}."
            )
        if membership_status not in {"active", "invited"}:
            raise MembershipAccessDeniedError(
                f"Student {student_user_id} is not active in section {section_id}."
            )

        student_cognito_sub = _clean_text(student_row[1])
        activity_identity = student_cognito_sub or student_user_id
        activity_params = (activity_identity, student_user_id)

        session_row = _fetch_one_row(
            connection,
            """
            SELECT
              COUNT(*) AS session_count,
              MAX(last_seen_at) AS last_session_at
            FROM tutor_sessions
            WHERE section_id = %s
              AND (user_sub = %s OR app_user_id::text = %s)
            """,
            (section_id, *activity_params),
        )
        turn_row = _fetch_one_row(
            connection,
            """
            SELECT
              COUNT(*) AS turn_count,
              MAX(COALESCE(completed_at, updated_at, created_at)) AS last_turn_at
            FROM tutor_turns
            WHERE section_id = %s
              AND (user_sub = %s OR app_user_id::text = %s)
            """,
            (section_id, *activity_params),
        )
        feedback_row = _fetch_one_row(
            connection,
            """
            SELECT
              COUNT(*) FILTER (
                WHERE snapshot->'feedback'->>'thumbs_up' = 'positive'
              ) AS positive_feedback_count,
              COUNT(*) FILTER (
                WHERE snapshot->'feedback'->>'thumbs_up' = 'negative'
              ) AS negative_feedback_count,
              MAX(updated_at) AS last_feedback_at
            FROM tutor_turn_snapshots
            WHERE section_id = %s
              AND (user_sub = %s OR app_user_id::text = %s)
            """,
            (section_id, *activity_params),
        )

        daily_session_rows = _fetch_all_rows(
            connection,
            """
            WITH session_facts AS (
              SELECT
                DATE((last_seen_at AT TIME ZONE %s)) AS day_date
              FROM tutor_sessions
              WHERE section_id = %s
                AND (user_sub = %s OR app_user_id::text = %s)
                AND last_seen_at >= (CURRENT_TIMESTAMP AT TIME ZONE %s)::DATE - INTERVAL '6 days'
            ),
            daily_sessions AS (
              SELECT
                day_date,
                COUNT(*) AS sessions
              FROM session_facts
              GROUP BY day_date
            )
            SELECT TO_CHAR(day_date, 'Dy') AS day, sessions
            FROM daily_sessions
            ORDER BY day_date ASC
            """,
            (tz, section_id, *activity_params, tz),
        )
        daily_turn_rows = _fetch_all_rows(
            connection,
            """
            WITH turn_facts AS (
              SELECT
                DATE((COALESCE(completed_at, updated_at, created_at) AT TIME ZONE %s)) AS day_date
              FROM tutor_turns
              WHERE section_id = %s
                AND (user_sub = %s OR app_user_id::text = %s)
                AND COALESCE(completed_at, updated_at, created_at) >= (CURRENT_TIMESTAMP AT TIME ZONE %s)::DATE - INTERVAL '6 days'
            ),
            daily_turns AS (
              SELECT
                day_date,
                COUNT(*) AS turns
              FROM turn_facts
              GROUP BY day_date
            )
            SELECT TO_CHAR(day_date, 'Dy') AS day, turns
            FROM daily_turns
            ORDER BY day_date ASC
            """,
            (tz, section_id, *activity_params, tz),
        )

    session_count = int(session_row[0]) if session_row and session_row[0] is not None else 0
    last_session_at = session_row[1] if session_row else None
    turn_count = int(turn_row[0]) if turn_row and turn_row[0] is not None else 0
    last_turn_at = turn_row[1] if turn_row else None
    positive_feedback_count = (
        int(feedback_row[0]) if feedback_row and feedback_row[0] is not None else 0
    )
    negative_feedback_count = (
        int(feedback_row[1]) if feedback_row and feedback_row[1] is not None else 0
    )
    last_feedback_at = feedback_row[2] if feedback_row and len(feedback_row) > 2 else None

    last_activity_at = max(
        [value for value in (last_session_at, last_turn_at, last_feedback_at) if value is not None],
        default=None,
    )

    for day, sessions in daily_session_rows:
        key = str(day)
        if key in timeline:
            timeline[key]["sessions"] = int(sessions)
    for day, turns in daily_turn_rows:
        key = str(day)
        if key in timeline:
            timeline[key]["turns"] = int(turns)

    section_summary = ProfessorSectionSummary(
        **_section_summary_from_row(section_row),
        professor_count=counts["professor"],
        ta_count=counts["ta"],
        student_count=counts["student"],
    )
    student_summary = ProfessorSectionStudent(
        user_id=_clean_text(student_row[0]),
        cognito_sub=student_cognito_sub or None,
        email=_clean_text(student_row[2]),
        display_name=_clean_text(student_row[3]),
        membership_status=membership_status,
        role_in_section=membership_role,
        session_count=session_count,
        last_session_at=_format_timestamp(last_session_at or last_activity_at),
    )

    weekly_activity = [
        ProfessorSectionStudentAnalyticsPoint(
            day=str(values["day"]),
            sessions=int(values["sessions"]),
            turns=int(values["turns"]),
        )
        for values in timeline.values()
    ]

    return ProfessorSectionStudentAnalytics(
        section=section_summary,
        student=student_summary,
        total_sessions=session_count,
        total_turns=turn_count,
        sessions_last_7_days=sum(int(values["sessions"]) for values in timeline.values()),
        turns_last_7_days=sum(int(values["turns"]) for values in timeline.values()),
        positive_feedback_count=positive_feedback_count,
        negative_feedback_count=negative_feedback_count,
        last_activity_at=_format_timestamp(last_activity_at),
        weekly_activity=weekly_activity,
        generated_at=_format_timestamp(datetime.now(timezone.utc)),
    )


def list_professor_section_launch_configs(
    current_user: CurrentUser,
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[SectionLaunchConfig]:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        rows = _load_section_launch_config_rows(connection, section_id)

    return [
        _launch_config_from_row(row, model_cls=SectionLaunchConfig)
        for row in rows
    ]


def replace_professor_section_launch_configs(
    current_user: CurrentUser,
    section_id: str,
    payload: list[SectionLaunchConfig],
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[SectionLaunchConfig]:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    normalized_rows: list[tuple[Any, ...]] = []
    seen_launch_ids: set[str] = set()
    for sort_order, config in enumerate(payload):
        launch_id = _clean_text(config.launch_id)
        label = _clean_text(config.label)
        if not launch_id:
            raise ValueError("launch_id is required for each launch config.")
        if not label:
            raise ValueError("label is required for each launch config.")
        if launch_id in seen_launch_ids:
            raise ValueError(f"Duplicate launch_id '{launch_id}' in launch config payload.")
        seen_launch_ids.add(launch_id)
        normalized_rows.append(
            (
                section_id,
                launch_id,
                label,
                _clean_text(config.repo_url),
                _clean_text(config.template_url),
                _clean_text(config.default_branch) or "main",
                bool(config.enabled),
                sort_order,
            )
        )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM section_launch_configs
                WHERE section_id = %s
                """,
                (section_id,),
            )
            for row in normalized_rows:
                cursor.execute(
                    """
                    INSERT INTO section_launch_configs (
                      section_id,
                      launch_id,
                      label,
                      repo_url,
                      template_url,
                      default_branch,
                      enabled,
                      sort_order
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    row,
                )

    return list_professor_section_launch_configs(current_user, section_id, runtime=runtime)


def get_professor_section_teaching_plan(
    current_user: CurrentUser,
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlan:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        return _load_professor_section_teaching_plan(connection, section_id)


def upsert_professor_section_teaching_plan(
    current_user: CurrentUser,
    section_id: str,
    payload: ProfessorTeachingPlanUpdate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlan:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    app_user = require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        _ensure_professor_section_teaching_plan(
            connection,
            section_id=section_id,
            created_by_user_id=str(app_user["user_id"]),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE teaching_plans
                SET title = %s,
                    summary = %s,
                    updated_at = now()
                WHERE section_id = %s
                """,
                (_clean_text(payload.title), _clean_text(payload.summary), section_id),
            )

        return _load_professor_section_teaching_plan(connection, section_id)


def publish_professor_section_teaching_plan(
    current_user: CurrentUser,
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlan:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    app_user = require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        plan_row = _load_section_teaching_plan_row(connection, section_id)
        if plan_row is None:
            raise LookupError(f"Teaching plan for section {section_id} was not found.")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE teaching_plans
                SET status = 'published',
                    version = version + 1,
                    published_by = %s,
                    published_at = now(),
                    updated_at = now()
                WHERE section_id = %s
                """,
                (str(app_user["user_id"]), section_id),
            )

        return _load_professor_section_teaching_plan(connection, section_id)


def archive_professor_section_teaching_plan(
    current_user: CurrentUser,
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlan:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        plan_row = _load_section_teaching_plan_row(connection, section_id)
        if plan_row is None:
            raise LookupError(f"Teaching plan for section {section_id} was not found.")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE teaching_plans
                SET status = 'archived',
                    updated_at = now()
                WHERE section_id = %s
                """,
                (section_id,),
            )

        return _load_professor_section_teaching_plan(connection, section_id)


def get_professor_section_instruction_settings(
    current_user: CurrentUser,
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> SectionInstructionSettings:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        row = _load_section_instruction_settings_row(connection, section_id)

    if row is None:
        return SectionInstructionSettings(section_id=section_id)
    return _section_instruction_settings_from_row(row)


def upsert_professor_section_instruction_settings(
    current_user: CurrentUser,
    section_id: str,
    payload: SectionInstructionSettingsUpdate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> SectionInstructionSettings:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        current_row = _load_section_instruction_settings_row(connection, section_id)
        settings = (
            _section_instruction_settings_from_row(current_row)
            if current_row is not None
            else SectionInstructionSettings(section_id=section_id)
        )
        merged = settings.model_dump()
        merged.update(payload.model_dump(exclude_unset=True))

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO section_instruction_settings (
                  section_id,
                  student_access_enabled,
                  week_resolution_mode,
                  manual_current_week_number,
                  teaching_plan_prompt_enabled,
                  references_prompt_enabled,
                  references_retrieval_enabled
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (section_id) DO UPDATE SET
                  student_access_enabled = EXCLUDED.student_access_enabled,
                  week_resolution_mode = EXCLUDED.week_resolution_mode,
                  manual_current_week_number = EXCLUDED.manual_current_week_number,
                  teaching_plan_prompt_enabled = EXCLUDED.teaching_plan_prompt_enabled,
                  references_prompt_enabled = EXCLUDED.references_prompt_enabled,
                  references_retrieval_enabled = EXCLUDED.references_retrieval_enabled,
                  updated_at = now()
                """,
                (
                    section_id,
                    bool(merged["student_access_enabled"]),
                    _clean_text(merged["week_resolution_mode"]) or "manual",
                    merged["manual_current_week_number"],
                    bool(merged["teaching_plan_prompt_enabled"]),
                    bool(merged["references_prompt_enabled"]),
                    bool(merged["references_retrieval_enabled"]),
                ),
            )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        row = _load_section_instruction_settings_row(connection, section_id)
    return _section_instruction_settings_from_row(row) if row is not None else SectionInstructionSettings(section_id=section_id)


def get_section_instructional_context(
    section_id: str,
    *,
    mode: str,
    week: int,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Build optional section-scoped prompt context for the student chat path."""
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    policy = get_runtime_policy_config()

    context: dict[str, Any] = {
        "applied": False,
        "reason": "runtime_switch_disabled",
        "section_id": section_id,
        "mode": mode,
        "requested_week": week,
        "effective_week": week,
        "section_instruction_settings": None,
        "teaching_plan": None,
        "teaching_plan_week": None,
        "references": {
            "runtime_enabled": bool(policy.references_orchestration.enabled),
            "prompt_enabled": False,
            "retrieval_enabled": False,
            "applied": False,
            "reason": "references_runtime_disabled"
            if not policy.references_orchestration.enabled
            else "references_disabled",
            "week_reference_count": 0,
            "prompt_reference_count": 0,
            "retrieval_reference_count": 0,
            "items": [],
        },
        "prompt_block": "",
    }

    if not policy.teaching_plan_orchestration.enabled:
        return context
    if policy.teaching_plan_orchestration.homework_assist_only and mode != "Homework Assist":
        context["reason"] = "mode_not_supported"
        return context

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        settings_row = _load_section_instruction_settings_row(connection, section_id)
        if settings_row is None:
            context["reason"] = "section_instruction_settings_missing"
            return context

        settings = _section_instruction_settings_from_row(settings_row)
        context["section_instruction_settings"] = settings.model_dump()
        references_runtime_enabled = bool(policy.references_orchestration.enabled)
        references_prompt_enabled = bool(
            settings.references_prompt_enabled and references_runtime_enabled
        )
        references_retrieval_enabled = bool(
            settings.references_retrieval_enabled and references_runtime_enabled
        )
        context["references"] = {
            "runtime_enabled": references_runtime_enabled,
            "prompt_enabled": references_prompt_enabled,
            "retrieval_enabled": references_retrieval_enabled,
            "applied": False,
            "reason": "references_runtime_disabled"
            if not references_runtime_enabled
            else "references_disabled",
            "week_reference_count": 0,
            "prompt_reference_count": 0,
            "retrieval_reference_count": 0,
            "items": [],
        }

        if not settings.teaching_plan_prompt_enabled:
            context["reason"] = "teaching_plan_prompt_disabled"
            return context

        effective_week = (
            settings.manual_current_week_number
            if settings.week_resolution_mode == "manual"
            and settings.manual_current_week_number is not None
            else week
        )
        context["effective_week"] = effective_week

        plan = _load_professor_section_teaching_plan(connection, section_id)
        if plan.teaching_plan_id is None:
            context["reason"] = "teaching_plan_missing"
            return context
        context["teaching_plan"] = plan.model_dump()

        if policy.teaching_plan_orchestration.require_published_plan and plan.status != "published":
            context["reason"] = "teaching_plan_not_published"
            return context

        week_match = next(
            (plan_week for plan_week in plan.weeks if plan_week.week_number == effective_week),
            None,
        )
        if week_match is None:
            context["reason"] = "teaching_plan_week_missing"
            return context

        context["teaching_plan_week"] = week_match.model_dump()
        active_references = [
            reference
            for reference in week_match.references
            if reference.enabled
        ]
        prompt_references = [
            reference
            for reference in active_references
            if reference.include_in_prompt
        ]
        retrieval_references = [
            reference
            for reference in active_references
            if reference.include_in_retrieval
        ]
        context["references"] = {
            "runtime_enabled": references_runtime_enabled,
            "prompt_enabled": references_prompt_enabled,
            "retrieval_enabled": references_retrieval_enabled,
            "applied": bool(prompt_references or retrieval_references),
            "reason": (
                "references_applied"
                if prompt_references or retrieval_references
                else "references_empty"
                if references_prompt_enabled or references_retrieval_enabled
                else "references_disabled"
            ),
            "week_reference_count": len(active_references),
            "prompt_reference_count": len(prompt_references),
            "retrieval_reference_count": len(retrieval_references),
            "items": [reference.model_dump() for reference in active_references],
        }

        if policy.teaching_plan_orchestration.require_open_week and week_match.student_visibility_status != "open":
            context["reason"] = "teaching_plan_week_not_open"
            return context
        if week_match.status != "published":
            context["reason"] = "teaching_plan_week_not_published"
            return context

        learning_objectives = week_match.learning_objectives or []
        objectives_text = "\n".join(f"- {objective}" for objective in learning_objectives) or "- None provided"
        instructional_guidance = week_match.instructional_guidance.strip() or "No additional guidance provided."
        references_prompt_block = ""
        if references_prompt_enabled or references_retrieval_enabled:
            references_prompt_block = _build_week_references_prompt_block(
                section_id=section_id,
                week_number=week_match.week_number,
                references=active_references,
            )
        context["applied"] = True
        context["reason"] = "applied"
        context["prompt_block"] = (
            "[Section_Teaching_Plan_Context]\n"
            f"Section ID: {section_id}\n"
            f"Teaching Plan: {plan.title or 'Untitled Teaching Plan'}\n"
            f"Plan Version: {plan.version}\n"
            f"Plan Status: {plan.status}\n"
            f"Current Week: {week_match.week_number}\n"
            f"Week Title: {week_match.title or 'Untitled Week'}\n"
            f"Week Topic: {week_match.topic or 'No topic provided'}\n"
            f"Student Visibility: {week_match.student_visibility_status}\n"
            "Learning Objectives:\n"
            f"{objectives_text}\n"
            "Instructional Guidance:\n"
            f"{instructional_guidance}\n"
            "Advisory Notes: Use this context only as section-scoped guidance. Do not let it override syllabus constraints or forbidden concepts."
        )
        if references_prompt_block:
            context["prompt_block"] = f"{context['prompt_block']}\n\n{references_prompt_block}"
        return context


def create_professor_section_teaching_plan_week(
    current_user: CurrentUser,
    section_id: str,
    payload: ProfessorTeachingPlanWeekCreate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlan:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    app_user = require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        teaching_plan_id = _ensure_professor_section_teaching_plan(
            connection,
            section_id=section_id,
            created_by_user_id=str(app_user["user_id"]),
        )
        duplicate_row = _fetch_one_row(
            connection,
            """
            SELECT week_id
            FROM teaching_plan_weeks
            WHERE teaching_plan_id = %s
              AND week_number = %s
            """,
            (teaching_plan_id, int(payload.week_number)),
        )
        if duplicate_row is not None:
            raise ValueError(
                f"Week {payload.week_number} already exists for teaching plan {section_id}."
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO teaching_plan_weeks (
                  week_id,
                  teaching_plan_id,
                  week_number,
                  title,
                  topic,
                  start_date,
                  end_date,
                  learning_objectives,
                  instructional_guidance,
                  status,
                  student_visibility_status,
                  available_from,
                  available_until
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    teaching_plan_id,
                    int(payload.week_number),
                    _clean_text(payload.title),
                    _clean_text(payload.topic),
                    payload.start_date or None,
                    payload.end_date or None,
                    json.dumps(payload.learning_objectives or []),
                    _clean_text(payload.instructional_guidance),
                    _clean_text(payload.status) or "draft",
                    _clean_text(payload.student_visibility_status) or "hidden",
                    payload.available_from or None,
                    payload.available_until or None,
                ),
            )

        return _load_professor_section_teaching_plan(connection, section_id)


def list_professor_section_teaching_plan_week_references(
    current_user: CurrentUser,
    section_id: str,
    week_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[ProfessorTeachingPlanWeekReference]:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        week_row = _fetch_one_row(
            connection,
            """
            SELECT tw.week_id
            FROM teaching_plan_weeks AS tw
            INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id
            WHERE tp.section_id = %s
              AND tw.week_id = %s
            """,
            (section_id, week_id),
        )
        if week_row is None:
            raise LookupError(f"Week {week_id} was not found for section {section_id}.")
        reference_rows = _load_section_teaching_plan_week_reference_rows_for_week(
            connection,
            section_id,
            week_id,
        )

    return [
        _teaching_plan_week_reference_from_row(reference_row)
        for reference_row in reference_rows
    ]


def get_professor_section_teaching_plan_week(
    current_user: CurrentUser,
    section_id: str,
    week_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlanWeek:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        row = _load_professor_section_teaching_plan_week(connection, section_id, week_id)

    if row is None:
        raise LookupError(f"Week {week_id} was not found for section {section_id}.")
    return row


def create_professor_section_teaching_plan_week_reference(
    current_user: CurrentUser,
    section_id: str,
    week_id: str,
    payload: ProfessorTeachingPlanWeekReferenceCreate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlanWeek:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        week_row = _fetch_one_row(
            connection,
            """
            SELECT tw.week_id
            FROM teaching_plan_weeks AS tw
            INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id
            WHERE tp.section_id = %s
              AND tw.week_id = %s
            """,
            (section_id, week_id),
        )
        if week_row is None:
            raise LookupError(f"Week {week_id} was not found for section {section_id}.")

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO teaching_plan_week_references (
                  reference_id,
                  week_id,
                  section_id,
                  title,
                  reference_type,
                  url,
                  course_document_key,
                  notes,
                  enabled,
                  include_in_prompt,
                  include_in_retrieval,
                  sort_order
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    week_id,
                    section_id,
                    _clean_text(payload.title),
                    _clean_text(payload.reference_type) or "course_doc",
                    _clean_text(payload.url),
                    _clean_text(payload.course_document_key),
                    _clean_text(payload.notes),
                    bool(payload.enabled),
                    bool(payload.include_in_prompt),
                    bool(payload.include_in_retrieval),
                    int(payload.sort_order or 0),
                ),
            )

        plan_week = _load_professor_section_teaching_plan_week(connection, section_id, week_id)

    if plan_week is None:
        raise LookupError(f"Week {week_id} was not found for section {section_id}.")
    return plan_week


def update_professor_section_teaching_plan_week_reference(
    current_user: CurrentUser,
    section_id: str,
    week_id: str,
    reference_id: str,
    payload: ProfessorTeachingPlanWeekReferenceUpdate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlanWeek:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    fields: list[str] = []
    values: list[Any] = []
    if payload.title is not None:
        fields.append("title = %s")
        values.append(_clean_text(payload.title))
    if payload.reference_type is not None:
        fields.append("reference_type = %s")
        values.append(_clean_text(payload.reference_type))
    if payload.url is not None:
        fields.append("url = %s")
        values.append(_clean_text(payload.url))
    if payload.course_document_key is not None:
        fields.append("course_document_key = %s")
        values.append(_clean_text(payload.course_document_key))
    if payload.notes is not None:
        fields.append("notes = %s")
        values.append(_clean_text(payload.notes))
    if payload.enabled is not None:
        fields.append("enabled = %s")
        values.append(bool(payload.enabled))
    if payload.include_in_prompt is not None:
        fields.append("include_in_prompt = %s")
        values.append(bool(payload.include_in_prompt))
    if payload.include_in_retrieval is not None:
        fields.append("include_in_retrieval = %s")
        values.append(bool(payload.include_in_retrieval))
    if payload.sort_order is not None:
        fields.append("sort_order = %s")
        values.append(int(payload.sort_order))

    if not fields:
        raise ValueError("At least one reference field must be provided.")

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        existing = _fetch_one_row(
            connection,
            """
            SELECT r.reference_id
            FROM teaching_plan_week_references AS r
            INNER JOIN teaching_plan_weeks AS tw ON tw.week_id = r.week_id
            INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id
            WHERE tp.section_id = %s
              AND tw.week_id = %s
              AND r.reference_id = %s
            """,
            (section_id, week_id, reference_id),
        )
        if existing is None:
            raise LookupError(
                f"Reference {reference_id} was not found for week {week_id} in section {section_id}."
            )

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE teaching_plan_week_references
                SET {", ".join(fields)},
                    updated_at = now()
                WHERE reference_id = %s
                """,
                tuple(values + [reference_id]),
            )

        plan_week = _load_professor_section_teaching_plan_week(connection, section_id, week_id)

    if plan_week is None:
        raise LookupError(f"Week {week_id} was not found for section {section_id}.")
    return plan_week


def delete_professor_section_teaching_plan_week_reference(
    current_user: CurrentUser,
    section_id: str,
    week_id: str,
    reference_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlanWeek:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        existing = _fetch_one_row(
            connection,
            """
            SELECT r.reference_id
            FROM teaching_plan_week_references AS r
            INNER JOIN teaching_plan_weeks AS tw ON tw.week_id = r.week_id
            INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id
            WHERE tp.section_id = %s
              AND tw.week_id = %s
              AND r.reference_id = %s
            """,
            (section_id, week_id, reference_id),
        )
        if existing is None:
            raise LookupError(
                f"Reference {reference_id} was not found for week {week_id} in section {section_id}."
            )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM teaching_plan_week_references
                WHERE reference_id = %s
                """,
                (reference_id,),
            )

        plan_week = _load_professor_section_teaching_plan_week(connection, section_id, week_id)

    if plan_week is None:
        raise LookupError(f"Week {week_id} was not found for section {section_id}.")
    return plan_week


def update_professor_section_teaching_plan_week(
    current_user: CurrentUser,
    section_id: str,
    week_id: str,
    payload: ProfessorTeachingPlanWeekUpdate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlan:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    fields: list[str] = []
    values: list[Any] = []
    if payload.week_number is not None:
        fields.append("week_number = %s")
        values.append(int(payload.week_number))
    if payload.title is not None:
        fields.append("title = %s")
        values.append(_clean_text(payload.title))
    if payload.topic is not None:
        fields.append("topic = %s")
        values.append(_clean_text(payload.topic))
    if payload.start_date is not None:
        fields.append("start_date = %s")
        values.append(payload.start_date or None)
    if payload.end_date is not None:
        fields.append("end_date = %s")
        values.append(payload.end_date or None)
    if payload.learning_objectives is not None:
        fields.append("learning_objectives = %s::jsonb")
        values.append(json.dumps(payload.learning_objectives))
    if payload.instructional_guidance is not None:
        fields.append("instructional_guidance = %s")
        values.append(_clean_text(payload.instructional_guidance))
    if payload.status is not None:
        fields.append("status = %s")
        values.append(_clean_text(payload.status))
    if payload.student_visibility_status is not None:
        fields.append("student_visibility_status = %s")
        values.append(_clean_text(payload.student_visibility_status))
    if payload.available_from is not None:
        fields.append("available_from = %s")
        values.append(payload.available_from or None)
    if payload.available_until is not None:
        fields.append("available_until = %s")
        values.append(payload.available_until or None)

    if not fields:
        raise ValueError("At least one week field must be provided.")

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        existing = _fetch_one_row(
            connection,
            """
            SELECT tw.week_id
            FROM teaching_plan_weeks AS tw
            INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id
            WHERE tp.section_id = %s
              AND tw.week_id = %s
            """,
            (section_id, week_id),
        )
        if existing is None:
            raise LookupError(f"Week {week_id} was not found for section {section_id}.")

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE teaching_plan_weeks
                SET {", ".join(fields)},
                    updated_at = now()
                WHERE week_id = %s
                """,
                tuple(values + [week_id]),
            )

        return _load_professor_section_teaching_plan(connection, section_id)


def delete_professor_section_teaching_plan_week(
    current_user: CurrentUser,
    section_id: str,
    week_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> ProfessorTeachingPlan:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        existing = _fetch_one_row(
            connection,
            """
            SELECT tw.week_id
            FROM teaching_plan_weeks AS tw
            INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id
            WHERE tp.section_id = %s
              AND tw.week_id = %s
            """,
            (section_id, week_id),
        )
        if existing is None:
            raise LookupError(f"Week {week_id} was not found for section {section_id}.")

        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM teaching_plan_weeks
                WHERE week_id = %s
                """,
                (week_id,),
            )

        return _load_professor_section_teaching_plan(connection, section_id)


def list_professor_section_students(
    current_user: CurrentUser,
    section_id: str,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[ProfessorSectionStudent]:
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        rows = _load_student_rows_for_section(connection, section_id, include_inactive=True)

    return [ProfessorSectionStudent.model_validate(_student_row_from_tuple(row)) for row in rows]


def invite_professor_section_student(
    current_user: CurrentUser,
    section_id: str,
    payload: ProfessorSectionStudentInviteCreate,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> list[ProfessorSectionStudent]:
    """Invite or refresh a student membership for a professor-managed section."""
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    require_section_membership(
        current_user,
        section_id,
        allowed_roles={"professor", "ta"},
        runtime=runtime,
    )

    email = _normalize_email(payload.email)
    display_name = _clean_text(payload.display_name)
    if not email:
        raise ValueError("email is required.")

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        user_row = _load_user_by_email(connection, email)
        if user_row is None:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                      cognito_sub,
                      email,
                      display_name,
                      primary_role,
                      status
                    )
                    VALUES (NULL, %s, %s, %s, %s)
                    RETURNING user_id
                    """,
                    (email, display_name, "student", "invited"),
                )
                user_id = str(cursor.fetchone()[0])
        else:
            user_id = str(user_row[0])
            if _clean_text(user_row[5]) == "disabled":
                raise AppUserDisabledError(f"User with email {email} is disabled.")
            if display_name and _clean_text(user_row[3]) != display_name:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE users
                        SET display_name = %s,
                            updated_at = now()
                        WHERE user_id = %s
                        """,
                        (display_name, user_id),
                    )

        membership_row = _fetch_one_row(
            connection,
            """
            SELECT role_in_section, status
            FROM section_memberships
            WHERE section_id = %s
              AND user_id = %s
            """,
            (section_id, user_id),
        )
        if membership_row is None:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO section_memberships (
                      section_id,
                      user_id,
                      role_in_section,
                      status
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (section_id, user_id, "student", "invited"),
                )
        else:
            existing_role = _clean_text(membership_row[0])
            existing_status = _clean_text(membership_row[1])
            if existing_role != "student":
                raise MembershipConflictError(
                    f"User {email} already has a non-student membership in section {section_id}."
                )
            if existing_status != "active":
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE section_memberships
                        SET status = 'invited',
                            updated_at = now()
                        WHERE section_id = %s
                          AND user_id = %s
                        """,
                        (section_id, user_id),
                    )

    return list_professor_section_students(current_user, section_id, runtime=runtime)


def get_student_bootstrap(
    current_user: CurrentUser,
    *,
    runtime: AppRegistryRuntimeConfig | None = None,
) -> StudentBootstrapResponse:
    """Resolve the student app user, sections, and default launch context."""
    runtime = runtime or load_app_registry_runtime_config()
    database_url = _require_database_url(runtime)
    app_user = sync_application_user(current_user, runtime=runtime)
    if not app_user:
        raise AppUserNotProvisionedError("No provisioned application user is available for this identity.")
    allowed_roles = student_surface_allowed_roles(current_user.primary_role)

    with _connect_postgres(database_url, runtime.connect_timeout_seconds) as connection:
        section_rows = _load_student_section_rows(
            connection,
            app_user["user_id"],
            allowed_roles=allowed_roles,
        )
        if not section_rows:
            if allowed_roles == {"student"}:
                raise MembershipAccessDeniedError(
                    "No active student memberships are assigned to this user."
                )
            raise MembershipAccessDeniedError(
                "No active student or smoke-test memberships are assigned to this user."
            )
        section_ids = [_clean_text(row[0]) for row in section_rows]
        default_section_id = section_ids[0]
        if len(section_ids) > 1:
            recent_section_id = _load_most_recent_student_section_id(
                connection,
                _clean_text(app_user.get("cognito_sub")),
            )
            if recent_section_id in section_ids:
                default_section_id = recent_section_id
        launch_configs_by_section: dict[str, list[StudentLaunchConfig]] = {}
        for section_id in section_ids:
            launch_configs_by_section[section_id] = [
                StudentLaunchConfig(
                    launch_id=_clean_text(row[1]),
                    label=_clean_text(row[2]),
                    repo_url=_clean_text(row[3]),
                    template_url=_clean_text(row[4]),
                    default_branch=_clean_text(row[5]) or "main",
                    enabled=bool(row[6]),
                    sort_order=int(row[7] or 0),
                )
                for row in _load_section_launch_config_rows(connection, section_id)
            ]

    return StudentBootstrapResponse(
        user=StudentBootstrapUser(
            app_user_id=_clean_text(app_user["user_id"]),
            cognito_sub=_clean_text(app_user.get("cognito_sub")) or None,
            email=_clean_text(app_user["email"]),
            display_name=_clean_text(app_user.get("display_name")),
            primary_role=_clean_text(app_user["primary_role"]),
            status=_clean_text(app_user["status"]),
            consent_status=_clean_text(app_user.get("consent_status")) or "pending",
        ),

        sections=[
            _student_section_from_row(
                row,
                launch_configs=launch_configs_by_section.get(_clean_text(row[0]), []),
            )
            for row in section_rows
        ],
        default_section_id=default_section_id,
        endpoints=StudentBootstrapEndpoints(
            chat="/api/student/chat",
            telemetry="/api/student/telemetry",
            feedback="/api/student/feedback",
        ),
    )
