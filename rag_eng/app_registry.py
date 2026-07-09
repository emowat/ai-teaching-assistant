"""Aurora-backed application users, sections, and memberships."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
import uuid

from dotenv import load_dotenv

from rag_eng.auth.models import CurrentUser
from rag_eng.course_admin import CourseNotFoundError
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
    ProfessorSectionSummary,
    ProfessorTeachingPlan,
    ProfessorTeachingPlanUpdate,
    ProfessorTeachingPlanWeek,
    ProfessorTeachingPlanWeekCreate,
    ProfessorTeachingPlanWeekUpdate,
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
        created_at,
        updated_at,
    ) = row[:8]
    return {
        "user_id": str(user_id),
        "cognito_sub": str(cognito_sub) if cognito_sub is not None else None,
        "email": _clean_text(email),
        "display_name": _clean_text(display_name),
        "primary_role": _clean_text(primary_role),
        "status": _clean_text(status),
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


def _load_student_rows_for_section(connection, section_id: str) -> list[tuple[Any, ...]]:
    return _fetch_all_rows(
        connection,
        """
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
          AND sm.status = 'active'
        ORDER BY u.display_name ASC, u.email ASC
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
        WHERE sm.user_id = %s
          AND sm.role_in_section = 'student'
          AND sm.status = 'active'
          AND s.is_active = TRUE
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
        WHERE sm.user_id = %s
          AND sm.role_in_section IN ('student', 'professor', 'ta')
          AND sm.status = 'active'
          AND s.is_active = TRUE
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
          created_at,
          updated_at
        FROM teaching_plan_weeks
        WHERE teaching_plan_id = %s
        ORDER BY week_number ASC, week_id ASC
        """,
        (teaching_plan_id,),
    )


def _teaching_plan_week_from_row(row: tuple[Any, ...]) -> ProfessorTeachingPlanWeek:
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
        created_at,
        updated_at,
    ) = row[:12]
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
        created_at=_format_timestamp(created_at),
        updated_at=_format_timestamp(updated_at),
    )


def _teaching_plan_from_row(
    row: tuple[Any, ...] | None,
    *,
    week_rows: list[tuple[Any, ...]] | None = None,
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
        weeks=[
            _teaching_plan_week_from_row(week_row)
            for week_row in (week_rows or [])
        ],
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
    return _teaching_plan_from_row(plan_row, week_rows=week_rows)


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
                  status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
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
                ),
            )

        return _load_professor_section_teaching_plan(connection, section_id)


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
        raise LookupError(f"Week {week_id} was not found for section {section_id}.")
    return _teaching_plan_week_from_row(row)


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
        rows = _load_student_rows_for_section(connection, section_id)

    return [ProfessorSectionStudent.model_validate(_student_row_from_tuple(row)) for row in rows]


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
