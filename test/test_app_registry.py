from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import uuid
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

import rag_eng.app_registry as app_registry
from rag_eng.auth.models import CurrentUser
from rag_eng.schemas import (
    AdminSectionCreate,
    AdminSectionMembershipCreate,
    AdminSectionMembershipUpdate,
    AdminSectionUpdate,
    AdminUserCreate,
    ProfessorTeachingPlanUpdate,
    ProfessorTeachingPlanWeekCreate,
    ProfessorTeachingPlanWeekReferenceCreate,
    ProfessorTeachingPlanWeekReferenceUpdate,
    ProfessorTeachingPlanWeekUpdate,
    ProfessorSectionAnalytics,
    ProfessorSectionStudentAnalytics,
    ProfessorSectionStudentInviteCreate,
    SectionLaunchConfig,
    StudentBootstrapResponse,
)


NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


@dataclass
class _State:
    courses: dict[str, dict[str, object]]
    users: dict[str, dict[str, object]]
    sections: dict[str, dict[str, object]]
    memberships: dict[tuple[str, str], dict[str, object]]
    section_instruction_settings: dict[str, dict[str, object]]
    launch_configs: dict[str, list[dict[str, object]]]
    teaching_plans: dict[str, dict[str, object]]
    teaching_plan_weeks: dict[str, dict[str, object]]
    teaching_plan_week_references: dict[str, dict[str, object]]
    tutor_sessions: list[dict[str, object]]
    tutor_turns: list[dict[str, object]]
    tutor_turn_snapshots: list[dict[str, object]]


class _FakeCognitoClient:
    def __init__(self) -> None:
        self.created_users: list[dict[str, object]] = []
        self.group_additions: list[dict[str, object]] = []
        self.deleted_usernames: list[str] = []
        self._users_by_email: dict[str, dict[str, object]] = {}

    def list_users(self, *, UserPoolId: str, Filter: str):  # noqa: N803
        del UserPoolId
        email = Filter.split('"')[1].casefold()
        user = self._users_by_email.get(email)
        return {"Users": [user]} if user is not None else {"Users": []}

    def admin_create_user(self, **kwargs):
        username = str(kwargs["Username"])
        if kwargs.get("MessageAction") == "RESEND":
            existing = self._users_by_email.get(username.casefold())
            if existing is None:
                raise ClientError(
                    {"Error": {"Code": "UserNotFoundException", "Message": "not found"}},
                    "AdminCreateUser",
                )
            self.created_users.append(kwargs)
            return {"User": existing}

        sub = f"sub-{username}"
        user = {
            "Username": username,
            "UserStatus": "FORCE_CHANGE_PASSWORD",
            "Attributes": [
                {"Name": "sub", "Value": sub},
                {"Name": "email", "Value": username},
            ],
        }
        self._users_by_email[username.casefold()] = user
        self.created_users.append(kwargs)
        return {"User": user}

    def admin_add_user_to_group(self, **kwargs):
        self.group_additions.append(kwargs)

    def admin_delete_user(self, *, UserPoolId: str, Username: str):  # noqa: N803
        del UserPoolId
        self.deleted_usernames.append(Username)
        self._users_by_email = {
            email: user
            for email, user in self._users_by_email.items()
            if user.get("Username") != Username
        }


class _FakeBoto3Session:
    def __init__(self, client: _FakeCognitoClient, **kwargs) -> None:
        self.client_kwargs = kwargs
        self._client = client

    def client(self, service_name: str):
        assert service_name == "cognito-idp"
        return self._client


class _FakeCursor:
    def __init__(self, state: _State):
        self.state = state
        self._rows: list[tuple[object, ...]] = []
        self.rowcount = 0

    @staticmethod
    def _normalize_sql(query: str) -> str:
        return " ".join(query.split())

    def _user_row(self, record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["user_id"],
            record.get("cognito_sub"),
            record["email"],
            record.get("display_name", ""),
            record["primary_role"],
            record["status"],
            record.get("consent_status", "pending"),
            record["created_at"],
            record["updated_at"],
        )

    def _section_row(self, record: dict[str, object]) -> tuple[object, ...]:
        course = self.state.courses[str(record["course_id"])]
        return (
            record["section_id"],
            record["course_id"],
            course["display_name"],
            record["display_name"],
            record.get("term", ""),
            record.get("is_active", True),
            record["created_at"],
            record["updated_at"],
            record.get("archived_at"),
        )

    def _membership_row_for_user(
        self,
        membership: dict[str, object],
    ) -> tuple[object, ...]:
        section = self.state.sections[str(membership["section_id"])]
        user = self.state.users[str(membership["user_id"])]
        course = self.state.courses[str(section["course_id"])]
        return (
            user["user_id"],
            section["section_id"],
            section["display_name"],
            section["course_id"],
            course["display_name"],
            membership["role_in_section"],
            membership["status"],
            membership["created_at"],
            membership["updated_at"],
        )

    def _membership_row_for_section(
        self,
        membership: dict[str, object],
    ) -> tuple[object, ...]:
        section = self.state.sections[str(membership["section_id"])]
        user = self.state.users[str(membership["user_id"])]
        course = self.state.courses[str(section["course_id"])]
        return (
            section["section_id"],
            user["user_id"],
            user.get("cognito_sub"),
            user["email"],
            user.get("display_name", ""),
            membership["role_in_section"],
            membership["status"],
            section["display_name"],
            section["course_id"],
            course["display_name"],
            membership["created_at"],
            membership["updated_at"],
        )

    def _student_row(self, membership: dict[str, object]) -> tuple[object, ...]:
        section_id = str(membership["section_id"])
        user = self.state.users[str(membership["user_id"])]
        sessions = [
            session
            for session in self.state.tutor_sessions
            if str(session.get("section_id", "")) == section_id
            and str(session.get("user_sub", "")) == str(user.get("cognito_sub", ""))
        ]
        last_session_at = None
        if sessions:
            last_session_at = max(session["last_seen_at"] for session in sessions)
        return (
            user["user_id"],
            user.get("cognito_sub"),
            user["email"],
            user.get("display_name", ""),
            membership["status"],
            membership["role_in_section"],
            len(sessions),
            last_session_at,
        )

    def _student_section_row(
        self,
        membership: dict[str, object],
    ) -> tuple[object, ...]:
        section = self.state.sections[str(membership["section_id"])]
        course = self.state.courses[str(section["course_id"])]
        return (
            section["section_id"],
            section["course_id"],
            course["display_name"],
            section["display_name"],
            section.get("term", ""),
            section.get("is_active", True),
            membership["status"],
            section["created_at"],
            section["updated_at"],
        )

    def _turn_row(self, record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["turn_id"],
            record["session_id"],
            record.get("request_id", ""),
            record.get("turn_index", 0),
            record.get("user_sub"),
            record.get("app_user_id"),
            record.get("course_id"),
            record.get("course_source", ""),
            record.get("section_id"),
            record.get("mode", ""),
            record.get("week", 0),
            record.get("status", "completed"),
            record.get("model_provider", ""),
            record.get("model_name", ""),
            record.get("retrieval_doc_count", 0),
            record.get("answer_chars", 0),
            record.get("latency_ms", 0),
            record.get("created_at"),
            record.get("updated_at"),
            record.get("completed_at"),
        )

    def _launch_config_row(self, record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["section_id"],
            record["launch_id"],
            record["label"],
            record.get("repo_url", ""),
            record.get("template_url", ""),
            record.get("default_branch", "main"),
            record.get("enabled", False),
            record.get("sort_order", 0),
        )

    def _teaching_plan_row(self, record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["teaching_plan_id"],
            record["section_id"],
            record.get("version", 1),
            record.get("status", "draft"),
            record.get("title", ""),
            record.get("summary", ""),
            record.get("created_by"),
            record.get("published_by"),
            record.get("published_at"),
            record["created_at"],
            record["updated_at"],
        )

    def _teaching_plan_week_row(self, record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["week_id"],
            record["teaching_plan_id"],
            record["week_number"],
            record.get("title", ""),
            record.get("topic", ""),
            record.get("start_date"),
            record.get("end_date"),
            record.get("learning_objectives", []),
            record.get("instructional_guidance", ""),
            record.get("status", "draft"),
            record.get("student_visibility_status", "hidden"),
            record.get("available_from"),
            record.get("available_until"),
            record["created_at"],
            record["updated_at"],
        )

    def _teaching_plan_week_reference_row(
        self,
        record: dict[str, object],
    ) -> tuple[object, ...]:
        return (
            record["reference_id"],
            record["week_id"],
            record["section_id"],
            record.get("title", ""),
            record.get("reference_type", "course_doc"),
            record.get("url", ""),
            record.get("course_document_key", ""),
            record.get("notes", ""),
            record.get("enabled", True),
            record.get("include_in_prompt", True),
            record.get("include_in_retrieval", False),
            record.get("sort_order", 0),
            record["created_at"],
            record["updated_at"],
        )

    def _section_instruction_settings_row(self, record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["section_id"],
            record.get("student_access_enabled", True),
            record.get("week_resolution_mode", "manual"),
            record.get("manual_current_week_number"),
            record.get("teaching_plan_prompt_enabled", False),
            record.get("references_prompt_enabled", False),
            record.get("references_retrieval_enabled", False),
            record["created_at"],
            record["updated_at"],
        )

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        sql = self._normalize_sql(query)
        params = params or ()
        self.rowcount = 0
        self._rows = []

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, consent_status, created_at, updated_at FROM users WHERE cognito_sub = %s"
        ):
            cognito_sub = str(params[0])
            for record in self.state.users.values():
                if str(record.get("cognito_sub", "")) == cognito_sub:
                    self._rows = [self._user_row(record)]
                    return
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, consent_status, created_at, updated_at FROM users WHERE lower(email) = lower(%s)"
        ):
            email = str(params[0]).casefold()
            for record in self.state.users.values():
                if str(record["email"]).casefold() == email:
                    self._rows = [self._user_row(record)]
                    return
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, consent_status, created_at, updated_at FROM users WHERE user_id = %s"
        ):
            user_id = str(params[0])
            record = self.state.users.get(user_id)
            if record is not None:
                self._rows = [self._user_row(record)]
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, consent_status, created_at, updated_at FROM users ORDER BY email ASC"
        ):
            self._rows = [
                self._user_row(record)
                for record in sorted(
                    self.state.users.values(),
                    key=lambda row: str(row["email"]).casefold(),
                )
            ]
            return

        if sql.startswith("INSERT INTO users"):
            user_id = str(uuid.uuid4())
            if len(params) == 5:
                cognito_sub, email, display_name, primary_role, status = params
            else:
                cognito_sub = None
                email, display_name, primary_role, status = params
            self.state.users[user_id] = {
                "user_id": user_id,
                "cognito_sub": cognito_sub,
                "email": str(email),
                "display_name": str(display_name),
                "primary_role": str(primary_role),
                "status": str(status),
                "consent_status": "pending",
                "created_at": NOW,
                "updated_at": NOW,
            }
            self._rows = [(user_id,)]
            self.rowcount = 1
            return

        if sql.startswith(
            "UPDATE users SET cognito_sub = %s, status = CASE WHEN status = 'disabled' THEN status ELSE 'active' END, updated_at = now() WHERE user_id = %s"
        ):
            cognito_sub, user_id = params
            record = self.state.users.get(str(user_id))
            if record is not None:
                record["cognito_sub"] = str(cognito_sub)
                if record["status"] != "disabled":
                    record["status"] = "active"
                record["updated_at"] = NOW
                self.rowcount = 1
            return

        if sql.startswith("UPDATE users SET status = 'active', updated_at = now() WHERE user_id = %s"):
            user_id = str(params[0])
            record = self.state.users.get(user_id)
            if record is not None:
                record["status"] = "active"
                record["updated_at"] = NOW
                self.rowcount = 1
            return

        if sql.startswith("UPDATE users SET"):
            user_id = str(params[-1])
            record = self.state.users.get(user_id)
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            for column, value in zip(columns, params[:-1]):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id ORDER BY sm.section_id ASC, u.email ASC"
        ):
            self._rows = [
                self._membership_row_for_section(self.state.memberships[key])
                for key in sorted(self.state.memberships)
            ]
            return

        if sql.startswith(
            "SELECT u.user_id, s.section_id, s.display_name, s.course_id, c.display_name, sm.role_in_section, sm.status, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id ORDER BY u.email ASC, s.section_id ASC"
        ):
            rows = [
                self._membership_row_for_user(membership)
                for membership in self.state.memberships.values()
            ]
            self._rows = sorted(rows, key=lambda row: (str(row[2]).casefold(), str(row[1])))
            return

        if sql.startswith(
            "SELECT u.user_id, s.section_id, s.display_name, s.course_id, c.display_name, sm.role_in_section, sm.status, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE u.user_id = %s ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._membership_row_for_user(membership)
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
            ]
            self._rows = sorted(rows, key=lambda row: str(row[1]))
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE sm.section_id IN ( SELECT s2.section_id FROM sections AS s2 WHERE s2.is_active = TRUE AND EXISTS ( SELECT 1 FROM section_memberships AS sm2 WHERE sm2.section_id = s2.section_id AND sm2.user_id = %s AND sm2.status = 'active' AND sm2.role_in_section IN ('professor', 'ta') ) ) ORDER BY sm.section_id ASC, u.email ASC"
        ):
            user_id = str(params[0])
            accessible_section_ids = {
                str(membership["section_id"])
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["status"]) == "active"
                and str(membership["role_in_section"]) in {"professor", "ta"}
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
            }
            rows = [
                self._membership_row_for_section(membership)
                for membership in self.state.memberships.values()
                if str(membership["section_id"]) in accessible_section_ids
            ]
            self._rows = sorted(rows, key=lambda row: (str(row[1]), str(row[3]).casefold()))
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE u.user_id = %s ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._membership_row_for_section(record)
                for record in self.state.memberships.values()
                if str(record["user_id"]) == user_id
            ]
            self._rows = sorted(rows, key=lambda row: str(row[1]))
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at, s.archived_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id ORDER BY s.section_id ASC"
        ):
            self._rows = [
                self._section_row(record)
                for record in sorted(
                    self.state.sections.values(),
                    key=lambda row: str(row["section_id"]),
                )
            ]
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at, s.archived_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id WHERE EXISTS ( SELECT 1 FROM section_memberships AS sm WHERE sm.section_id = s.section_id AND sm.user_id = %s AND sm.status = 'active' AND sm.role_in_section IN ('professor', 'ta') ) AND s.is_active = TRUE ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            section_ids = {
                str(membership["section_id"])
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["status"]) == "active"
                and str(membership["role_in_section"]) in {"professor", "ta"}
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
            }
            self._rows = [
                self._section_row(self.state.sections[section_id])
                for section_id in sorted(section_ids)
            ]
            return

        if (
            "FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id LEFT JOIN ("
            in sql
            and "sm.role_in_section = 'student'" in sql
            and "COALESCE(stats.session_count, 0) AS session_count" in sql
        ):
            section_id = str(params[0])
            include_inactive = "sm.status = 'active'" not in sql
            rows = [
                self._student_row(membership)
                for membership in self.state.memberships.values()
                if str(membership["section_id"]) == section_id
                and str(membership["role_in_section"]) == "student"
                and (include_inactive or str(membership["status"]) == "active")
            ]
            rows.sort(
                key=lambda row: (
                    {
                        "active": 0,
                        "invited": 1,
                        "dropped": 2,
                        "disabled": 3,
                    }.get(str(row[4]), 4),
                    str(row[3]).casefold(),
                    str(row[2]).casefold(),
                )
            )
            self._rows = rows
            return

        if sql.startswith(
            "SELECT COUNT(*) AS session_count, COUNT(DISTINCT user_sub) AS active_students FROM tutor_sessions WHERE section_id = %s AND last_seen_at >= (CURRENT_TIMESTAMP AT TIME ZONE %s)::DATE - INTERVAL '6 days'"
        ):
            section_id = str(params[0])
            sessions = [
                session
                for session in self.state.tutor_sessions
                if str(session.get("section_id", "")) == section_id
            ]
            self._rows = [
                (
                    len(sessions),
                    len({str(session.get("user_sub", "")) for session in sessions}),
                )
            ]
            return

        if sql.startswith(
            "SELECT COUNT(*) AS session_count, MAX(last_seen_at) AS last_session_at FROM tutor_sessions WHERE section_id = %s AND (user_sub = %s OR app_user_id::text = %s)"
        ):
            section_id, user_sub, user_id = map(str, params)
            sessions = [
                session
                for session in self.state.tutor_sessions
                if str(session.get("section_id", "")) == section_id
                and (
                    str(session.get("user_sub", "")) == user_sub
                    or str(session.get("app_user_id", "")) == user_id
                )
            ]
            if sessions:
                self._rows = [(len(sessions), max(session["last_seen_at"] for session in sessions))]
            else:
                self._rows = [(0, None)]
            return

        if sql.startswith(
            "SELECT COUNT(*) AS turn_count, MAX(COALESCE(completed_at, updated_at, created_at)) AS last_turn_at FROM tutor_turns WHERE section_id = %s AND (user_sub = %s OR app_user_id::text = %s)"
        ):
            section_id, user_sub, user_id = map(str, params)
            turns = [
                turn
                for turn in self.state.tutor_turns
                if str(turn.get("section_id", "")) == section_id
                and (
                    str(turn.get("user_sub", "")) == user_sub
                    or str(turn.get("app_user_id", "")) == user_id
                )
            ]
            if turns:
                latest = max(
                    turn.get("completed_at") or turn.get("updated_at") or turn.get("created_at")
                    for turn in turns
                )
                self._rows = [(len(turns), latest)]
            else:
                self._rows = [(0, None)]
            return

        if sql.startswith(
            "SELECT COUNT(*) FILTER ( WHERE snapshot->'feedback'->>'thumbs_up' = 'positive' ) AS positive_feedback_count, COUNT(*) FILTER ( WHERE snapshot->'feedback'->>'thumbs_up' = 'negative' ) AS negative_feedback_count, MAX(updated_at) AS last_feedback_at FROM tutor_turn_snapshots WHERE section_id = %s AND (user_sub = %s OR app_user_id::text = %s)"
        ):
            section_id, user_sub, user_id = map(str, params)
            snapshots = [
                snapshot
                for snapshot in self.state.tutor_turn_snapshots
                if str(snapshot.get("section_id", "")) == section_id
                and (
                    str(snapshot.get("user_sub", "")) == user_sub
                    or str(snapshot.get("app_user_id", "")) == user_id
                )
            ]
            positive = 0
            negative = 0
            last_feedback_at = None
            for snapshot in snapshots:
                feedback = dict(snapshot.get("snapshot", {})).get("feedback", {})
                if feedback.get("thumbs_up") == "positive":
                    positive += 1
                if feedback.get("thumbs_up") == "negative":
                    negative += 1
                updated_at = snapshot.get("updated_at")
                if updated_at is not None:
                    last_feedback_at = max(last_feedback_at, updated_at) if last_feedback_at else updated_at
            self._rows = [(positive, negative, last_feedback_at)]
            return

        if (
            "WITH session_facts AS (" in sql
            and "WITH daily_sessions AS (" not in sql
            and "COUNT(*) AS sessions" in sql
            and "TO_CHAR(day_date, 'Dy') AS day, sessions FROM daily_sessions ORDER BY day_date ASC"
            in sql
        ):
            section_id = str(params[1])
            user_sub = str(params[2])
            user_id = str(params[3])
            by_day: dict[str, int] = {}
            for session in self.state.tutor_sessions:
                if str(session.get("section_id", "")) != section_id:
                    continue
                if not (
                    str(session.get("user_sub", "")) == user_sub
                    or str(session.get("app_user_id", "")) == user_id
                ):
                    continue
                day = session["last_seen_at"].strftime("%a")
                by_day[day] = by_day.get(day, 0) + 1
            self._rows = sorted((day, sessions) for day, sessions in by_day.items())
            return

        if (
            "WITH turn_facts AS (" in sql
            and "COUNT(*) AS turns" in sql
            and "TO_CHAR(day_date, 'Dy') AS day, turns FROM daily_turns ORDER BY day_date ASC"
            in sql
        ):
            section_id = str(params[1])
            user_sub = str(params[2])
            user_id = str(params[3])
            by_day: dict[str, int] = {}
            for turn in self.state.tutor_turns:
                if str(turn.get("section_id", "")) != section_id:
                    continue
                if not (
                    str(turn.get("user_sub", "")) == user_sub
                    or str(turn.get("app_user_id", "")) == user_id
                ):
                    continue
                day = (turn.get("completed_at") or turn.get("updated_at") or turn.get("created_at")).strftime("%a")
                by_day[day] = by_day.get(day, 0) + 1
            self._rows = sorted((day, turns) for day, turns in by_day.items())
            return

        if (
            "WITH session_facts AS (" in sql
            and "COUNT(DISTINCT user_sub) AS active_students" in sql
            and "TO_CHAR(day_date, 'Dy') AS day, sessions, active_students FROM daily_sessions ORDER BY day_date ASC"
            in sql
        ):
            section_id = str(params[1])
            by_day: dict[str, dict[str, set[str] | int]] = {}
            for session in self.state.tutor_sessions:
                if str(session.get("section_id", "")) != section_id:
                    continue
                day = session["last_seen_at"].strftime("%a")
                bucket = by_day.setdefault(day, {"sessions": 0, "users": set()})
                bucket["sessions"] = int(bucket["sessions"]) + 1
                users = bucket["users"]
                assert isinstance(users, set)
                users.add(str(session.get("user_sub", "")))
            self._rows = [
                (
                    day,
                    values["sessions"],
                    len(values["users"]),
                )
                for day, values in sorted(by_day.items(), key=lambda item: item[0])
            ]
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, sm.status, s.created_at, s.updated_at FROM section_memberships AS sm INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id LEFT JOIN section_instruction_settings AS sis ON sis.section_id = s.section_id WHERE sm.user_id = %s AND sm.role_in_section = 'student' AND sm.status = 'active' AND s.is_active = TRUE AND COALESCE(sis.student_access_enabled, TRUE) = TRUE ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._student_section_row(membership)
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["role_in_section"]) == "student"
                and str(membership["status"]) == "active"
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
                and bool(
                    self.state.section_instruction_settings.get(
                        str(membership["section_id"]),
                        {},
                    ).get("student_access_enabled", True)
                )
            ]
            self._rows = sorted(rows, key=lambda row: str(row[0]))
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, sm.status, s.created_at, s.updated_at FROM section_memberships AS sm INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id LEFT JOIN section_instruction_settings AS sis ON sis.section_id = s.section_id WHERE sm.user_id = %s AND sm.role_in_section IN ('student', 'professor', 'ta') AND sm.status = 'active' AND s.is_active = TRUE AND COALESCE(sis.student_access_enabled, TRUE) = TRUE ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._student_section_row(membership)
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["status"]) == "active"
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
                and str(membership["role_in_section"]) in {"student", "professor", "ta"}
                and bool(
                    self.state.section_instruction_settings.get(
                        str(membership["section_id"]),
                        {},
                    ).get("student_access_enabled", True)
                )
            ]
            self._rows = sorted(rows, key=lambda row: str(row[0]))
            return

        if sql.startswith(
            "SELECT section_id, launch_id, label, repo_url, template_url, default_branch, enabled, sort_order FROM section_launch_configs WHERE section_id = %s ORDER BY sort_order ASC, launch_id ASC"
        ):
            section_id = str(params[0])
            rows = [
                self._launch_config_row(record)
                for record in sorted(
                    self.state.launch_configs.get(section_id, []),
                    key=lambda row: (int(row.get("sort_order", 0)), str(row.get("launch_id", ""))),
                )
            ]
            self._rows = rows
            return

        if sql.startswith(
            "SELECT section_id FROM tutor_sessions WHERE user_sub = %s AND section_id IS NOT NULL ORDER BY last_seen_at DESC, updated_at DESC LIMIT 1"
        ):
            user_sub = str(params[0])
            sessions = [
                session
                for session in self.state.tutor_sessions
                if str(session.get("user_sub", "")) == user_sub
                and session.get("section_id") is not None
            ]
            if sessions:
                latest = max(
                    sessions,
                    key=lambda row: (
                        row.get("last_seen_at"),
                        row.get("updated_at", row.get("last_seen_at")),
                    ),
                )
                self._rows = [(latest["section_id"],)]
            return

        if sql.startswith("SELECT course_id FROM courses WHERE course_id = %s"):
            course_id = str(params[0])
            if course_id in self.state.courses:
                self._rows = [(course_id,)]
            return

        if sql.startswith("SELECT launch_configs FROM courses WHERE course_id = %s"):
            course_id = str(params[0])
            record = self.state.courses.get(course_id)
            if record is not None:
                self._rows = [(record.get("launch_configs"),)]
            else:
                self._rows = []
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at, s.archived_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id WHERE s.section_id = %s"
        ):
            section_id = str(params[0])
            record = self.state.sections.get(section_id)
            if record is not None:
                self._rows = [self._section_row(record)]
            return

        if sql.startswith(
            "SELECT section_id, student_access_enabled, week_resolution_mode, manual_current_week_number, teaching_plan_prompt_enabled, references_prompt_enabled, references_retrieval_enabled, created_at, updated_at FROM section_instruction_settings WHERE section_id = %s"
        ):
            section_id = str(params[0])
            record = self.state.section_instruction_settings.get(section_id)
            if record is not None:
                self._rows = [self._section_instruction_settings_row(record)]
            return

        if sql.startswith(
            "INSERT INTO section_instruction_settings ( section_id, student_access_enabled, week_resolution_mode, manual_current_week_number, teaching_plan_prompt_enabled, references_prompt_enabled, references_retrieval_enabled ) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (section_id) DO UPDATE SET student_access_enabled = EXCLUDED.student_access_enabled, week_resolution_mode = EXCLUDED.week_resolution_mode, manual_current_week_number = EXCLUDED.manual_current_week_number, teaching_plan_prompt_enabled = EXCLUDED.teaching_plan_prompt_enabled, references_prompt_enabled = EXCLUDED.references_prompt_enabled, references_retrieval_enabled = EXCLUDED.references_retrieval_enabled, updated_at = now()"
        ):
            (
                section_id,
                student_access_enabled,
                week_resolution_mode,
                manual_current_week_number,
                teaching_plan_prompt_enabled,
                references_prompt_enabled,
                references_retrieval_enabled,
            ) = params
            record = self.state.section_instruction_settings.get(str(section_id))
            if record is None:
                self.state.section_instruction_settings[str(section_id)] = {
                    "section_id": str(section_id),
                    "student_access_enabled": bool(student_access_enabled),
                    "week_resolution_mode": str(week_resolution_mode),
                    "manual_current_week_number": manual_current_week_number,
                    "teaching_plan_prompt_enabled": bool(teaching_plan_prompt_enabled),
                    "references_prompt_enabled": bool(references_prompt_enabled),
                    "references_retrieval_enabled": bool(references_retrieval_enabled),
                    "created_at": NOW,
                    "updated_at": NOW,
                }
            else:
                record["student_access_enabled"] = bool(student_access_enabled)
                record["week_resolution_mode"] = str(week_resolution_mode)
                record["manual_current_week_number"] = manual_current_week_number
                record["teaching_plan_prompt_enabled"] = bool(teaching_plan_prompt_enabled)
                record["references_prompt_enabled"] = bool(references_prompt_enabled)
                record["references_retrieval_enabled"] = bool(references_retrieval_enabled)
                record["updated_at"] = NOW
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE sm.section_id = %s ORDER BY u.email ASC, sm.role_in_section ASC"
        ):
            section_id = str(params[0])
            rows = [
                self._membership_row_for_section(membership)
                for membership in self.state.memberships.values()
                if str(membership["section_id"]) == section_id
            ]
            self._rows = sorted(rows, key=lambda row: (str(row[3]).casefold(), str(row[5])))
            return

        if sql.startswith("INSERT INTO sections"):
            section_id, course_id, display_name, term, is_active = params
            self.state.sections[str(section_id)] = {
                "section_id": str(section_id),
                "course_id": str(course_id),
                "display_name": str(display_name),
                "term": str(term),
                "is_active": bool(is_active),
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            return

        if sql.startswith("UPDATE sections SET"):
            section_id = str(params[-1])
            record = self.state.sections.get(section_id)
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            for column, value in zip(columns, params[:-1]):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith("INSERT INTO section_memberships"):
            section_id, user_id, role_in_section, status = params
            self.state.memberships[(str(section_id), str(user_id))] = {
                "section_id": str(section_id),
                "user_id": str(user_id),
                "role_in_section": str(role_in_section),
                "status": str(status),
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            return

        if sql.startswith(
            "SELECT teaching_plan_id, section_id, version, status, title, summary, created_by, published_by, published_at, created_at, updated_at FROM teaching_plans WHERE section_id = %s"
        ):
            section_id = str(params[0])
            record = self.state.teaching_plans.get(section_id)
            if record is not None:
                self._rows = [self._teaching_plan_row(record)]
            return

        if sql.startswith(
            "SELECT week_id, teaching_plan_id, week_number, title, topic, start_date, end_date, learning_objectives, instructional_guidance, status, student_visibility_status, available_from, available_until, created_at, updated_at FROM teaching_plan_weeks WHERE teaching_plan_id = %s ORDER BY week_number ASC, week_id ASC"
        ):
            teaching_plan_id = str(params[0])
            rows = [
                self._teaching_plan_week_row(record)
                for record in self.state.teaching_plan_weeks.values()
                if str(record["teaching_plan_id"]) == teaching_plan_id
            ]
            self._rows = sorted(rows, key=lambda row: (int(row[2]), str(row[0])))
            return

        if sql.startswith(
            "SELECT r.reference_id, r.week_id, r.section_id, r.title, r.reference_type, r.url, r.course_document_key, r.notes, r.enabled, r.include_in_prompt, r.include_in_retrieval, r.sort_order, r.created_at, r.updated_at FROM teaching_plan_week_references AS r INNER JOIN teaching_plan_weeks AS tw ON tw.week_id = r.week_id WHERE tw.teaching_plan_id = %s ORDER BY tw.week_number ASC, r.sort_order ASC, r.reference_id ASC"
        ):
            teaching_plan_id = str(params[0])
            rows = [
                self._teaching_plan_week_reference_row(record)
                for record in self.state.teaching_plan_week_references.values()
                if str(record["teaching_plan_id"]) == teaching_plan_id
            ]
            self._rows = rows
            return

        if sql.startswith(
            "SELECT week_id FROM teaching_plan_weeks WHERE teaching_plan_id = %s AND week_number = %s"
        ):
            teaching_plan_id, week_number = params
            for record in self.state.teaching_plan_weeks.values():
                if str(record["teaching_plan_id"]) == str(teaching_plan_id) and int(record["week_number"]) == int(week_number):
                    self._rows = [(record["week_id"],)]
                    return
            return

        if sql.startswith(
            "SELECT tw.week_id, tw.teaching_plan_id, tw.week_number, tw.title, tw.topic, tw.start_date, tw.end_date, tw.learning_objectives, tw.instructional_guidance, tw.status, tw.student_visibility_status, tw.available_from, tw.available_until, tw.created_at, tw.updated_at FROM teaching_plan_weeks AS tw INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id WHERE tp.section_id = %s AND tw.week_id = %s"
        ):
            section_id, week_id = map(str, params)
            record = self.state.teaching_plan_weeks.get(week_id)
            if record is not None and str(record["section_id"]) == section_id:
                self._rows = [self._teaching_plan_week_row(record)]
            return

        if sql.startswith(
            "SELECT tw.week_id FROM teaching_plan_weeks AS tw INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id WHERE tp.section_id = %s AND tw.week_id = %s"
        ):
            section_id, week_id = map(str, params)
            record = self.state.teaching_plan_weeks.get(week_id)
            if record is not None and str(record["section_id"]) == section_id:
                self._rows = [(week_id,)]
            return

        if sql.startswith(
            "INSERT INTO teaching_plans ( teaching_plan_id, section_id, created_by ) VALUES (%s, %s, %s)"
        ):
            teaching_plan_id, section_id, created_by = params
            self.state.teaching_plans[str(section_id)] = {
                "teaching_plan_id": str(teaching_plan_id),
                "section_id": str(section_id),
                "version": 1,
                "status": "draft",
                "title": "",
                "summary": "",
                "created_by": str(created_by),
                "published_by": None,
                "published_at": None,
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            return

        if sql.startswith(
            "UPDATE teaching_plans SET title = %s, summary = %s, updated_at = now() WHERE section_id = %s"
        ):
            title, summary, section_id = params
            record = self.state.teaching_plans.get(str(section_id))
            if record is None:
                return
            record["title"] = str(title)
            record["summary"] = str(summary)
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith(
            "UPDATE teaching_plans SET status = 'published', version = version + 1, published_by = %s, published_at = now(), updated_at = now() WHERE section_id = %s"
        ):
            published_by, section_id = params
            record = self.state.teaching_plans.get(str(section_id))
            if record is None:
                return
            record["status"] = "published"
            record["version"] = int(record.get("version", 1)) + 1
            record["published_by"] = str(published_by)
            record["published_at"] = NOW
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith(
            "UPDATE teaching_plans SET status = 'archived', updated_at = now() WHERE section_id = %s"
        ):
            section_id = str(params[0])
            record = self.state.teaching_plans.get(section_id)
            if record is None:
                return
            record["status"] = "archived"
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith(
            "INSERT INTO teaching_plan_weeks ( week_id, teaching_plan_id, week_number, title, topic, start_date, end_date, learning_objectives, instructional_guidance, status, student_visibility_status, available_from, available_until ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)"
        ):
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
            ) = params
            section_id = None
            for plan in self.state.teaching_plans.values():
                if str(plan["teaching_plan_id"]) == str(teaching_plan_id):
                    section_id = str(plan["section_id"])
                    break
            self.state.teaching_plan_weeks[str(week_id)] = {
                "week_id": str(week_id),
                "teaching_plan_id": str(teaching_plan_id),
                "section_id": section_id,
                "week_number": int(week_number),
                "title": str(title),
                "topic": str(topic),
                "start_date": start_date,
                "end_date": end_date,
                "learning_objectives": learning_objectives,
                "instructional_guidance": str(instructional_guidance),
                "status": str(status),
                "student_visibility_status": str(student_visibility_status),
                "available_from": available_from,
                "available_until": available_until,
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            return

        if sql.startswith("UPDATE teaching_plan_weeks SET"):
            week_id = str(params[-1])
            record = self.state.teaching_plan_weeks.get(week_id)
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*(?:%s(?:::jsonb)?|now\(\))", sql)
                if match != "updated_at"
            ]
            param_index = 0
            for column in columns:
                value = params[param_index]
                param_index += 1
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith("DELETE FROM teaching_plan_weeks WHERE week_id = %s"):
            week_id = str(params[0])
            if week_id in self.state.teaching_plan_weeks:
                del self.state.teaching_plan_weeks[week_id]
                self.rowcount = 1
            return

        if sql.startswith(
            "SELECT r.reference_id, r.week_id, r.section_id, r.title, r.reference_type, r.url, r.course_document_key, r.notes, r.enabled, r.include_in_prompt, r.include_in_retrieval, r.sort_order, r.created_at, r.updated_at FROM teaching_plan_week_references AS r INNER JOIN teaching_plan_weeks AS tw ON tw.week_id = r.week_id INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id WHERE tp.section_id = %s AND tw.week_id = %s ORDER BY r.sort_order ASC, r.reference_id ASC"
        ):
            section_id, week_id = map(str, params)
            rows = [
                self._teaching_plan_week_reference_row(record)
                for record in self.state.teaching_plan_week_references.values()
                if str(record["section_id"]) == section_id and str(record["week_id"]) == week_id
            ]
            self._rows = sorted(rows, key=lambda row: (int(row[11]), str(row[0])))
            return

        if sql.startswith(
            "SELECT r.reference_id FROM teaching_plan_week_references AS r INNER JOIN teaching_plan_weeks AS tw ON tw.week_id = r.week_id INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id WHERE tp.section_id = %s AND tw.week_id = %s AND r.reference_id = %s"
        ):
            section_id, week_id, reference_id = map(str, params)
            record = self.state.teaching_plan_week_references.get(reference_id)
            if (
                record is not None
                and str(record["section_id"]) == section_id
                and str(record["week_id"]) == week_id
            ):
                self._rows = [(reference_id,)]
            return

        if sql.startswith(
            "INSERT INTO teaching_plan_week_references ( reference_id, week_id, section_id, title, reference_type, url, course_document_key, notes, enabled, include_in_prompt, include_in_retrieval, sort_order ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        ):
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
            ) = params
            week_record = self.state.teaching_plan_weeks.get(str(week_id))
            teaching_plan_id = None
            if week_record is not None:
                teaching_plan_id = str(week_record["teaching_plan_id"])
            self.state.teaching_plan_week_references[str(reference_id)] = {
                "reference_id": str(reference_id),
                "week_id": str(week_id),
                "section_id": str(section_id),
                "teaching_plan_id": teaching_plan_id,
                "title": str(title),
                "reference_type": str(reference_type),
                "url": str(url),
                "course_document_key": str(course_document_key),
                "notes": str(notes),
                "enabled": bool(enabled),
                "include_in_prompt": bool(include_in_prompt),
                "include_in_retrieval": bool(include_in_retrieval),
                "sort_order": int(sort_order),
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            return

        if sql.startswith("UPDATE teaching_plan_week_references SET"):
            reference_id = str(params[-1])
            record = self.state.teaching_plan_week_references.get(reference_id)
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            for column, value in zip(columns, params[:-1]):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith("DELETE FROM teaching_plan_week_references WHERE reference_id = %s"):
            reference_id = str(params[0])
            if reference_id in self.state.teaching_plan_week_references:
                del self.state.teaching_plan_week_references[reference_id]
                self.rowcount = 1
            return

        if sql.startswith("DELETE FROM section_launch_configs WHERE section_id = %s"):
            section_id = str(params[0])
            removed = len(self.state.launch_configs.get(section_id, []))
            self.state.launch_configs[section_id] = []
            self.rowcount = removed
            return

        if sql.startswith(
            "INSERT INTO section_launch_configs ( section_id, launch_id, label, repo_url, template_url, default_branch, enabled, sort_order ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ):
            (
                section_id,
                launch_id,
                label,
                repo_url,
                template_url,
                default_branch,
                enabled,
                sort_order,
            ) = params
            records = self.state.launch_configs.setdefault(str(section_id), [])
            records.append(
                {
                    "section_id": str(section_id),
                    "launch_id": str(launch_id),
                    "label": str(label),
                    "repo_url": str(repo_url),
                    "template_url": str(template_url),
                    "default_branch": str(default_branch),
                    "enabled": bool(enabled),
                    "sort_order": int(sort_order),
                }
            )
            self.rowcount = 1
            return

        if sql.startswith(
            "UPDATE section_memberships SET status = 'active', updated_at = now() WHERE user_id = %s AND status = 'invited'"
        ):
            user_id = str(params[0])
            activated = 0
            for record in self.state.memberships.values():
                if str(record["user_id"]) == user_id and record["status"] == "invited":
                    record["status"] = "active"
                    record["updated_at"] = NOW
                    activated += 1
            self.rowcount = activated
            return

        if sql.startswith("UPDATE section_memberships SET"):
            section_id = str(params[-2])
            user_id = str(params[-1])
            record = self.state.memberships.get((section_id, user_id))
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            for column, value in zip(columns, params[:-2]):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith("SELECT section_id FROM section_memberships WHERE section_id = %s AND user_id = %s"):
            section_id, user_id = map(str, params)
            if (section_id, user_id) in self.state.memberships:
                self._rows = [(section_id,)]
            return

        if sql.startswith("SELECT role_in_section, status FROM section_memberships WHERE section_id = %s AND user_id = %s"):
            section_id, user_id = map(str, params)
            record = self.state.memberships.get((section_id, user_id))
            if record is not None:
                self._rows = [(record["role_in_section"], record["status"])]
            return

        if sql.startswith(
            "SELECT sm.role_in_section, sm.status FROM section_memberships AS sm WHERE sm.section_id = %s AND sm.user_id = %s"
        ):
            section_id, user_id = map(str, params)
            record = self.state.memberships.get((section_id, user_id))
            if record is not None:
                self._rows = [(record["role_in_section"], record["status"])]
            return

        if "FROM tutor_sessions" in sql and "GROUP BY" in sql:
            self._rows = []
            return
            
        if "FROM tutor_turn_snapshots" in sql and "GROUP BY" in sql:
            self._rows = []
            return
            
        if "external_paste_detected" in sql:
            self._rows = []
            return
            
        if "FROM telemetry_events" in sql and "GROUP BY" in sql:
            self._rows = []
            return

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, state: _State):
        self.state = state

    def cursor(self):
        return _FakeCursor(self.state)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _state() -> _State:
    return _State(
        courses={
            "mit14": {
                "course_id": "mit14",
                "display_name": "MIT 6.0014",
            }
        },
        users={},
        sections={},
        memberships={},
        section_instruction_settings={},
        launch_configs={},
        teaching_plans={},
        teaching_plan_weeks={},
        teaching_plan_week_references={},
        tutor_sessions=[],
        tutor_turns=[],
        tutor_turn_snapshots=[],
    )


def _runtime() -> app_registry.AppRegistryRuntimeConfig:
    return app_registry.AppRegistryRuntimeConfig(
        database_url="postgresql://example",
        connect_timeout_seconds=5,
    )


def _patch_connection(monkeypatch: pytest.MonkeyPatch, state: _State) -> None:
    monkeypatch.setattr(
        app_registry,
        "_connect_postgres",
        lambda database_url, connect_timeout_seconds: _FakeConnection(state),
    )


def _user(
    *,
    user_id: str,
    email: str,
    display_name: str,
    primary_role: str,
    status: str,
    cognito_sub: str | None = None,
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "cognito_sub": cognito_sub,
        "email": email,
        "display_name": display_name,
        "primary_role": primary_role,
        "status": status,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _section(
    *,
    section_id: str,
    course_id: str = "mit14",
    display_name: str,
    term: str = "Fall 2026",
    is_active: bool = True,
) -> dict[str, object]:
    return {
        "section_id": section_id,
        "course_id": course_id,
        "display_name": display_name,
        "term": term,
        "is_active": is_active,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _membership(
    *,
    section_id: str,
    user_id: str,
    role_in_section: str,
    status: str = "active",
) -> dict[str, object]:
    return {
        "section_id": section_id,
        "user_id": user_id,
        "role_in_section": role_in_section,
        "status": status,
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_resolve_application_user_claims_by_cognito_sub_without_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-1"] = _user(
        user_id="user-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-1",
    )
    _patch_connection(monkeypatch, state)

    resolved = app_registry.resolve_application_user(
        CurrentUser(
            cognito_sub="sub-1",
            email=None,
            primary_role="professor",
        ),
        runtime=_runtime(),
    )

    assert resolved["user_id"] == "user-1"
    assert resolved["email"] == "prof@example.edu"


def test_resolve_application_user_claims_invited_user_by_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-2"] = _user(
        user_id="user-2",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
    )
    _patch_connection(monkeypatch, state)

    resolved = app_registry.resolve_application_user(
        CurrentUser(
            cognito_sub="sub-2",
            email="student@example.edu",
            primary_role="student",
        ),
        runtime=_runtime(),
    )

    assert resolved["user_id"] == "user-2"
    assert resolved["cognito_sub"] == "sub-2"
    assert state.users["user-2"]["status"] == "active"


def test_resolve_application_user_allows_admin_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["admin-1"] = _user(
        user_id="admin-1",
        email="admin@example.edu",
        display_name="Admin",
        primary_role="admin",
        status="active",
        cognito_sub="sub-admin",
    )
    _patch_connection(monkeypatch, state)

    resolved = app_registry.resolve_application_user(
        CurrentUser(
            cognito_sub="sub-admin",
            email="admin@example.edu",
            primary_role="admin",
        ),
        runtime=_runtime(),
    )

    assert resolved["user_id"] == "admin-1"
    assert resolved["email"] == "admin@example.edu"


def test_resolve_application_user_rejects_disabled_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-3"] = _user(
        user_id="user-3",
        email="disabled@example.edu",
        display_name="Disabled",
        primary_role="student",
        status="disabled",
        cognito_sub="sub-3",
    )
    _patch_connection(monkeypatch, state)

    with pytest.raises(app_registry.AppUserDisabledError):
        app_registry.resolve_application_user(
            CurrentUser(
                cognito_sub="sub-3",
                email="disabled@example.edu",
                primary_role="student",
            ),
            runtime=_runtime(),
        )


def test_get_student_bootstrap_returns_sections_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.sections["mit14-fall-002"] = _section(
        section_id="mit14-fall-002",
        display_name="MIT 6.0014 Section B",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.memberships[("mit14-fall-002", "student-1")] = _membership(
        section_id="mit14-fall-002",
        user_id="student-1",
        role_in_section="student",
    )
    state.tutor_sessions.append(
        {
            "session_id": "sess-1",
            "user_sub": "sub-student",
            "section_id": "mit14-fall-002",
            "last_seen_at": NOW,
            "updated_at": NOW,
        }
    )
    _patch_connection(monkeypatch, state)

    response = app_registry.get_student_bootstrap(
        CurrentUser(
            cognito_sub="sub-student",
            email="student@example.edu",
            primary_role="student",
        ),
        runtime=_runtime(),
    )

    assert isinstance(response, StudentBootstrapResponse)
    assert response.user.app_user_id == "student-1"
    assert [section.section_id for section in response.sections] == [
        "mit14-fall-001",
        "mit14-fall-002",
    ]
    assert response.default_section_id == "mit14-fall-002"
    assert response.endpoints.chat == "/api/student/chat"
    assert response.sections[0].launch_configs == []


def test_get_student_bootstrap_defaults_to_the_only_active_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.launch_configs["mit14-fall-001"] = [
        {
            "section_id": "mit14-fall-001",
            "launch_id": "codespaces",
            "label": "Codespaces",
            "repo_url": "https://github.com/example/repo",
            "template_url": "https://github.com/example/template",
            "default_branch": "main",
            "enabled": True,
            "sort_order": 0,
        }
    ]
    _patch_connection(monkeypatch, state)

    response = app_registry.get_student_bootstrap(
        CurrentUser(
            cognito_sub="sub-student",
            email="student@example.edu",
            primary_role="student",
        ),
        runtime=_runtime(),
    )

    assert response.default_section_id == "mit14-fall-001"
    assert response.sections[0].section_id == "mit14-fall-001"
    assert response.sections[0].launch_configs[0].launch_id == "codespaces"


def test_get_student_bootstrap_allows_staff_smoke_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Professor",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    _patch_connection(monkeypatch, state)

    response = app_registry.get_student_bootstrap(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        runtime=_runtime(),
    )

    assert response.user.primary_role == "professor"
    assert [section.section_id for section in response.sections] == [
        "mit14-fall-001",
    ]
    assert response.default_section_id == "mit14-fall-001"


def test_professor_launch_config_list_and_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Professor",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.launch_configs["mit14-fall-001"] = [
        {
            "section_id": "mit14-fall-001",
            "launch_id": "codespaces",
            "label": "Codespaces",
            "repo_url": "https://github.com/example/old",
            "template_url": "https://github.com/example/template",
            "default_branch": "main",
            "enabled": True,
            "sort_order": 0,
        }
    ]
    _patch_connection(monkeypatch, state)

    listed = app_registry.list_professor_section_launch_configs(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )

    updated = app_registry.replace_professor_section_launch_configs(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        [
            SectionLaunchConfig(
                launch_id="codespaces",
                label="Codespaces Updated",
                repo_url="https://github.com/example/new",
                template_url="https://github.com/example/template",
                default_branch="main",
                enabled=True,
                sort_order=0,
            ),
            SectionLaunchConfig(
                launch_id="fallback",
                label="Fallback",
                repo_url="",
                template_url="",
                default_branch="main",
                enabled=False,
                sort_order=1,
            ),
        ],
        runtime=_runtime(),
    )

    assert listed[0].launch_id == "codespaces"
    assert updated[0].label == "Codespaces Updated"
    assert [row["launch_id"] for row in state.launch_configs["mit14-fall-001"]] == [
        "codespaces",
        "fallback",
    ]


def test_professor_teaching_plan_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Professor",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    _patch_connection(monkeypatch, state)

    bootstrap = app_registry.get_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )
    assert bootstrap.section_id == "mit14-fall-001"
    assert bootstrap.status == "draft"
    assert bootstrap.weeks == []

    updated = app_registry.upsert_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorTeachingPlanUpdate(
            title="Pointer Safety and Memory Basics",
            summary="Week-by-week plan for the first half of the course.",
        ),
        runtime=_runtime(),
    )
    assert updated.title == "Pointer Safety and Memory Basics"
    assert updated.summary.startswith("Week-by-week plan")
    assert updated.teaching_plan_id is not None

    with_week = app_registry.create_professor_section_teaching_plan_week(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorTeachingPlanWeekCreate(
            week_number=1,
            title="C Basics",
            topic="Functions, variables, and memory",
            learning_objectives=["Understand pointer basics", "Trace a simple program"],
            instructional_guidance="Keep examples short and concrete.",
        ),
        runtime=_runtime(),
    )
    assert with_week.weeks[0].week_number == 1
    assert with_week.weeks[0].title == "C Basics"
    assert state.teaching_plans["mit14-fall-001"]["status"] == "draft"

    week = app_registry.get_professor_section_teaching_plan_week(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        with_week.weeks[0].week_id,
        runtime=_runtime(),
    )
    assert week.week_number == 1
    assert week.topic == "Functions, variables, and memory"

    patched = app_registry.update_professor_section_teaching_plan_week(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        week.week_id,
        ProfessorTeachingPlanWeekUpdate(
            topic="Variables, pointers, and stack memory",
            instructional_guidance="Keep it practical.",
        ),
        runtime=_runtime(),
    )
    assert patched.weeks[0].topic == "Variables, pointers, and stack memory"

    published = app_registry.publish_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )
    assert published.status == "published"
    assert published.published_by_user_id == "prof-1"

    archived = app_registry.archive_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )
    assert archived.status == "archived"


def test_professor_teaching_plan_loads_week_references_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Professor",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.section_instruction_settings["mit14-fall-001"] = {
        "section_id": "mit14-fall-001",
        "student_access_enabled": True,
        "week_resolution_mode": "manual",
        "manual_current_week_number": 1,
        "teaching_plan_prompt_enabled": True,
        "references_prompt_enabled": True,
        "references_retrieval_enabled": True,
        "created_at": NOW,
        "updated_at": NOW,
    }
    _patch_connection(monkeypatch, state)
    monkeypatch.setattr(
        app_registry,
        "get_runtime_policy_config",
        lambda: SimpleNamespace(
            teaching_plan_orchestration=SimpleNamespace(
                enabled=True,
                homework_assist_only=True,
                require_published_plan=True,
                require_open_week=True,
            ),
            references_orchestration=SimpleNamespace(enabled=True),
        ),
    )

    app_registry.upsert_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorTeachingPlanUpdate(
            title="Pointer Safety and Memory Basics",
            summary="Week-by-week plan for the first half of the course.",
        ),
        runtime=_runtime(),
    )
    with_week = app_registry.create_professor_section_teaching_plan_week(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorTeachingPlanWeekCreate(
            week_number=1,
            title="C Basics",
            topic="Functions, variables, and memory",
            learning_objectives=["Understand pointer basics", "Trace a simple program"],
            instructional_guidance="Keep examples short and concrete.",
            status="published",
            student_visibility_status="open",
        ),
        runtime=_runtime(),
    )
    app_registry.update_professor_section_teaching_plan_week(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        with_week.weeks[0].week_id,
        ProfessorTeachingPlanWeekUpdate(
            status="published",
            student_visibility_status="open",
        ),
        runtime=_runtime(),
    )
    app_registry.publish_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )
    week_id = with_week.weeks[0].week_id
    teaching_plan_id = state.teaching_plans["mit14-fall-001"]["teaching_plan_id"]
    reference_payload = ProfessorTeachingPlanWeekReferenceCreate(
        title="Lecture notes",
        reference_type="course_doc",
        course_document_key="raw/rag_sources/week-1-notes.md",
        notes="Read before trying the homework.",
        include_in_prompt=True,
        include_in_retrieval=False,
        sort_order=0,
    )
    state.teaching_plan_week_references["ref-1"] = {
        "reference_id": "ref-1",
        "week_id": week_id,
        "section_id": "mit14-fall-001",
        "teaching_plan_id": teaching_plan_id,
        **reference_payload.model_dump(),
        "created_at": NOW,
        "updated_at": NOW,
    }

    plan = app_registry.get_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )
    assert plan.weeks[0].references[0].title == "Lecture notes"
    assert plan.weeks[0].references[0].course_document_key == "raw/rag_sources/week-1-notes.md"

    context = app_registry.get_section_instructional_context(
        "mit14-fall-001",
        mode="Homework Assist",
        week=1,
        runtime=_runtime(),
    )
    assert context["references"]["week_reference_count"] == 1
    assert context["references"]["prompt_reference_count"] == 1
    assert context["references"]["applied"] is True
    assert "Section_Week_References" in context["prompt_block"]
    assert "Lecture notes" in context["prompt_block"]


def test_professor_teaching_plan_week_reference_crud_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Professor",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    _patch_connection(monkeypatch, state)

    app_registry.upsert_professor_section_teaching_plan(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorTeachingPlanUpdate(
            title="Pointer Safety and Memory Basics",
            summary="Week-by-week plan for the first half of the course.",
        ),
        runtime=_runtime(),
    )
    created = app_registry.create_professor_section_teaching_plan_week(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorTeachingPlanWeekCreate(
            week_number=1,
            title="C Basics",
            topic="Functions, variables, and memory",
            learning_objectives=["Understand pointer basics"],
            instructional_guidance="Keep examples short and concrete.",
            status="draft",
            student_visibility_status="hidden",
        ),
        runtime=_runtime(),
    )

    created_week_id = created.weeks[0].week_id
    listed_before = app_registry.list_professor_section_teaching_plan_week_references(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        created_week_id,
        runtime=_runtime(),
    )
    assert listed_before == []

    created_week = app_registry.create_professor_section_teaching_plan_week_reference(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        created_week_id,
        ProfessorTeachingPlanWeekReferenceCreate(
            title="Lecture notes",
            reference_type="course_doc",
            course_document_key="raw/rag_sources/week-1-notes.md",
            notes="Read before trying the homework.",
            include_in_prompt=True,
            include_in_retrieval=False,
            sort_order=0,
        ),
        runtime=_runtime(),
    )
    assert len(created_week.references) == 1
    assert created_week.references[0].title == "Lecture notes"

    listed_after_create = app_registry.list_professor_section_teaching_plan_week_references(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        created_week_id,
        runtime=_runtime(),
    )
    assert listed_after_create[0].course_document_key == "raw/rag_sources/week-1-notes.md"

    updated_week = app_registry.update_professor_section_teaching_plan_week_reference(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        created_week_id,
        created_week.references[0].reference_id,
        ProfessorTeachingPlanWeekReferenceUpdate(
            title="Updated lecture notes",
            notes="Now includes pointers and ownership.",
            include_in_retrieval=True,
        ),
        runtime=_runtime(),
    )
    assert updated_week.references[0].title == "Updated lecture notes"
    assert updated_week.references[0].include_in_retrieval is True

    deleted_week = app_registry.delete_professor_section_teaching_plan_week_reference(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        created_week_id,
        created_week.references[0].reference_id,
        runtime=_runtime(),
    )
    assert deleted_week.references == []


def test_professor_instruction_settings_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Professor",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    _patch_connection(monkeypatch, state)

    defaults = app_registry.get_professor_section_instruction_settings(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )
    assert defaults.student_access_enabled is True
    assert defaults.week_resolution_mode == "manual"
    assert defaults.manual_current_week_number is None

    updated = app_registry.upsert_professor_section_instruction_settings(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        app_registry.SectionInstructionSettingsUpdate(
            student_access_enabled=False,
            week_resolution_mode="date_driven",
            manual_current_week_number=3,
            teaching_plan_prompt_enabled=True,
            references_prompt_enabled=True,
            references_retrieval_enabled=True,
        ),
        runtime=_runtime(),
    )
    assert updated.student_access_enabled is False
    assert updated.week_resolution_mode == "date_driven"
    assert updated.manual_current_week_number == 3
    assert state.section_instruction_settings["mit14-fall-001"]["student_access_enabled"] is False


def test_professor_launch_config_routes_allow_ta_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["ta-1"] = _user(
        user_id="ta-1",
        email="ta@example.edu",
        display_name="TA",
        primary_role="professor",
        status="active",
        cognito_sub="sub-ta",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "ta-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="ta-1",
        role_in_section="ta",
    )
    state.launch_configs["mit14-fall-001"] = [
        {
            "section_id": "mit14-fall-001",
            "launch_id": "codespaces",
            "label": "Codespaces",
            "repo_url": "https://github.com/example/repo",
            "template_url": "https://github.com/example/template",
            "default_branch": "main",
            "enabled": True,
            "sort_order": 0,
        }
    ]
    _patch_connection(monkeypatch, state)

    listed = app_registry.list_professor_section_launch_configs(
        CurrentUser(
            cognito_sub="sub-ta",
            email="ta@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )

    updated = app_registry.replace_professor_section_launch_configs(
        CurrentUser(
            cognito_sub="sub-ta",
            email="ta@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        [
            SectionLaunchConfig(
                launch_id="codespaces",
                label="Codespaces for TA",
                repo_url="https://github.com/example/repo",
                template_url="https://github.com/example/template",
                default_branch="main",
                enabled=True,
                sort_order=0,
            ),
        ],
        runtime=_runtime(),
    )

    assert listed[0].launch_id == "codespaces"
    assert updated[0].label == "Codespaces for TA"


def test_get_student_bootstrap_respects_paused_student_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.section_instruction_settings["mit14-fall-001"] = {
        "section_id": "mit14-fall-001",
        "student_access_enabled": False,
        "week_resolution_mode": "manual",
        "manual_current_week_number": None,
        "teaching_plan_prompt_enabled": False,
        "references_prompt_enabled": False,
        "references_retrieval_enabled": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    _patch_connection(monkeypatch, state)

    with pytest.raises(app_registry.MembershipAccessDeniedError):
        app_registry.get_student_bootstrap(
            CurrentUser(
                cognito_sub="sub-student",
                email="student@example.edu",
                primary_role="student",
            ),
            runtime=_runtime(),
        )


def test_get_student_bootstrap_includes_launch_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.launch_configs["mit14-fall-001"] = [
        {
            "section_id": "mit14-fall-001",
            "launch_id": "codespaces",
            "label": "Codespaces",
            "repo_url": "https://github.com/example/repo",
            "template_url": "https://github.com/example/template",
            "default_branch": "main",
            "enabled": True,
            "sort_order": 1,
        }
    ]
    _patch_connection(monkeypatch, state)

    response = app_registry.get_student_bootstrap(
        CurrentUser(
            cognito_sub="sub-student",
            email="student@example.edu",
            primary_role="student",
        ),
        runtime=_runtime(),
    )

    assert response.sections[0].launch_configs[0].launch_id == "codespaces"
    assert response.sections[0].launch_configs[0].enabled is True


def test_get_student_bootstrap_requires_active_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    _patch_connection(monkeypatch, state)

    with pytest.raises(app_registry.MembershipAccessDeniedError):
        app_registry.get_student_bootstrap(
            CurrentUser(
                cognito_sub="sub-student",
                email="student@example.edu",
                primary_role="student",
            ),
            runtime=_runtime(),
        )


def test_admin_user_and_section_crud_with_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-1"] = _user(
        user_id="user-1",
        email="existing@example.edu",
        display_name="Existing User",
        primary_role="student",
        status="active",
        cognito_sub="sub-existing",
    )
    _patch_connection(monkeypatch, state)

    created_user = app_registry.create_admin_user(
        AdminUserCreate(
            email="invite@example.edu",
            display_name="Invite User",
            primary_role="professor",
        ),
        runtime=_runtime(),
    )
    created_section = app_registry.create_admin_section(
        AdminSectionCreate(
            section_id="mit14-fall-001",
            course_id="mit14",
            display_name="MIT 6.0014 Section A",
            term="Fall 2026",
        ),
        runtime=_runtime(),
    )
    updated_section = app_registry.update_admin_section(
        "mit14-fall-001",
        AdminSectionUpdate(display_name="MIT 6.0014 Section A+", is_active=False),
        runtime=_runtime(),
    )
    membership_section = app_registry.create_section_membership(
        "mit14-fall-001",
        AdminSectionMembershipCreate(
            user_id=created_user.user_id,
            role_in_section="professor",
        ),
        runtime=_runtime(),
    )
    updated_membership = app_registry.update_section_membership(
        "mit14-fall-001",
        created_user.user_id,
        AdminSectionMembershipUpdate(status="disabled"),
        runtime=_runtime(),
    )

    users = app_registry.list_admin_users(runtime=_runtime())
    sections = app_registry.list_admin_sections(runtime=_runtime())

    assert created_user.email == "invite@example.edu"
    assert created_section.section_id == "mit14-fall-001"
    assert updated_section.is_active is False
    assert membership_section.section_id == "mit14-fall-001"
    assert updated_membership.memberships[0].status == "disabled"
    assert users[0].email == "existing@example.edu"
    assert users[1].section_memberships[0].section_id == "mit14-fall-001"
    assert sections[0].memberships[0].section_id == "mit14-fall-001"


def test_professor_views_return_active_sections_and_rosters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.sections["mit14-fall-002"] = _section(
        section_id="mit14-fall-002",
        display_name="Inactive Section",
        is_active=False,
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.memberships[("mit14-fall-002", "prof-1")] = _membership(
        section_id="mit14-fall-002",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.tutor_sessions.append(
        {
            "session_id": "sess-1",
            "user_sub": "sub-student",
            "section_id": "mit14-fall-001",
            "last_seen_at": NOW,
        }
    )
    _patch_connection(monkeypatch, state)

    sections = app_registry.list_professor_sections(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        runtime=_runtime(),
    )
    students = app_registry.list_professor_section_students(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )

    assert [section.section_id for section in sections] == ["mit14-fall-001"]
    assert students[0].email == "student@example.edu"
    assert students[0].session_count == 1


def test_professor_section_analytics_uses_live_section_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.tutor_sessions.append(
        {
            "session_id": "sess-1",
            "user_sub": "sub-student",
            "section_id": "mit14-fall-001",
            "last_seen_at": NOW,
        }
    )
    state.tutor_sessions.append(
        {
            "session_id": "sess-2",
            "user_sub": "sub-student",
            "section_id": "mit14-fall-001",
            "last_seen_at": NOW,
        }
    )
    _patch_connection(monkeypatch, state)

    analytics = app_registry.get_professor_section_analytics(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )

    assert isinstance(analytics, ProfessorSectionAnalytics)
    assert analytics.section.section_id == "mit14-fall-001"
    assert analytics.sessions_last_7_days == 2
    assert analytics.active_students_last_7_days == 1
    assert len(analytics.weekly_activity) == 7
    assert analytics.top_students[0].email == "student@example.edu"


def test_professor_can_invite_student_into_assigned_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.users["student-1"] = _user(
        user_id="student-1",
        email="new.student@example.edu",
        display_name="New Student",
        primary_role="student",
        status="invited",
        cognito_sub=None,
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    fake_cognito = _FakeCognitoClient()
    monkeypatch.setenv("COGNITO_REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_test_pool")
    monkeypatch.setattr(
        "rag_eng.app_registry.boto3.Session",
        lambda **kwargs: _FakeBoto3Session(fake_cognito, **kwargs),
    )
    _patch_connection(monkeypatch, state)

    roster = app_registry.invite_professor_section_student(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorSectionStudentInviteCreate(
            email="new.student@example.edu",
            display_name="New Student",
        ),
        runtime=_runtime(),
    )

    assert any(student.email == "new.student@example.edu" for student in roster)
    invited = next(student for student in roster if student.email == "new.student@example.edu")
    assert invited.membership_status == "invited"
    assert invited.role_in_section == "student"
    assert fake_cognito.created_users
    assert state.users["student-1"]["cognito_sub"] == "sub-new.student@example.edu"
    assert any(
        membership["status"] == "invited"
        for membership in state.memberships.values()
        if membership["user_id"] != "prof-1"
    )


def test_professor_invite_student_creates_cognito_user_and_group_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    fake_cognito = _FakeCognitoClient()
    monkeypatch.setenv("COGNITO_REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_test_pool")
    monkeypatch.setattr(
        "rag_eng.app_registry.boto3.Session",
        lambda **kwargs: _FakeBoto3Session(fake_cognito, **kwargs),
    )
    _patch_connection(monkeypatch, state)

    roster = app_registry.invite_professor_section_student(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        ProfessorSectionStudentInviteCreate(
            email="new.student@example.edu",
            display_name="New Student",
        ),
        runtime=_runtime(),
    )

    invited = next(student for student in roster if student.email == "new.student@example.edu")
    user_row = next(
        record for record in state.users.values() if record["email"] == "new.student@example.edu"
    )

    assert invited.membership_status == "invited"
    assert invited.role_in_section == "student"
    assert user_row["status"] == "invited"
    assert user_row["cognito_sub"] == "sub-new.student@example.edu"
    assert fake_cognito.created_users
    assert fake_cognito.created_users[0]["Username"] == "new.student@example.edu"
    assert fake_cognito.group_additions
    assert fake_cognito.group_additions[0]["GroupName"] == "Students"


def _resend_invite_base_state() -> _State:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    return state


def _patch_cognito(
    monkeypatch: pytest.MonkeyPatch, fake_cognito: _FakeCognitoClient
) -> None:
    monkeypatch.setenv("COGNITO_REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_test_pool")
    monkeypatch.setattr(
        "rag_eng.app_registry.boto3.Session",
        lambda **kwargs: _FakeBoto3Session(fake_cognito, **kwargs),
    )


def test_professor_can_resend_invitation_to_same_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _resend_invite_base_state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
        cognito_sub="sub-student@example.edu",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
        status="invited",
    )

    fake_cognito = _FakeCognitoClient()
    fake_cognito._users_by_email["student@example.edu"] = {
        "Username": "student@example.edu",
        "UserStatus": "FORCE_CHANGE_PASSWORD",
        "Attributes": [
            {"Name": "sub", "Value": "sub-student@example.edu"},
            {"Name": "email", "Value": "student@example.edu"},
        ],
    }
    _patch_cognito(monkeypatch, fake_cognito)
    _patch_connection(monkeypatch, state)

    roster = app_registry.resend_professor_section_student_invite(
        CurrentUser(
            cognito_sub="sub-prof", email="prof@example.edu", primary_role="professor"
        ),
        "mit14-fall-001",
        "student-1",
        ProfessorSectionStudentInviteCreate(
            email="student@example.edu", display_name="Student"
        ),
        runtime=_runtime(),
    )

    assert any(student.email == "student@example.edu" for student in roster)
    resend_calls = [
        call
        for call in fake_cognito.created_users
        if call.get("MessageAction") == "RESEND"
    ]
    assert len(resend_calls) == 1
    assert resend_calls[0]["Username"] == "student@example.edu"
    assert fake_cognito.deleted_usernames == []
    assert state.users["student-1"]["email"] == "student@example.edu"
    assert state.users["student-1"]["cognito_sub"] == "sub-student@example.edu"


def test_professor_resend_invite_sends_fresh_invite_when_no_cognito_account_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression test: a student whose Aurora row predates the invite flow
    # (e.g. added via admin section-assignment with only an Aurora entry,
    # cognito_sub NULL) has no Cognito account to RESEND to. Same-email
    # "resend" must fall back to creating a fresh invite instead of raising
    # CognitoInviteError("No pending Cognito invitation exists ...").
    state = _resend_invite_base_state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
        cognito_sub=None,
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
        status="invited",
    )

    fake_cognito = _FakeCognitoClient()
    _patch_cognito(monkeypatch, fake_cognito)
    _patch_connection(monkeypatch, state)

    roster = app_registry.resend_professor_section_student_invite(
        CurrentUser(
            cognito_sub="sub-prof", email="prof@example.edu", primary_role="professor"
        ),
        "mit14-fall-001",
        "student-1",
        ProfessorSectionStudentInviteCreate(
            email="student@example.edu", display_name="Student"
        ),
        runtime=_runtime(),
    )

    assert any(student.email == "student@example.edu" for student in roster)
    fresh_creates = [
        call
        for call in fake_cognito.created_users
        if call.get("MessageAction") != "RESEND"
    ]
    assert len(fresh_creates) == 1
    assert fresh_creates[0]["Username"] == "student@example.edu"
    assert state.users["student-1"]["cognito_sub"] == "sub-student@example.edu"


def test_professor_can_resend_invitation_with_corrected_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _resend_invite_base_state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="typo@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
        cognito_sub="sub-typo@example.edu",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
        status="invited",
    )

    fake_cognito = _FakeCognitoClient()
    fake_cognito._users_by_email["typo@example.edu"] = {
        "Username": "typo@example.edu",
        "UserStatus": "FORCE_CHANGE_PASSWORD",
        "Attributes": [
            {"Name": "sub", "Value": "sub-typo@example.edu"},
            {"Name": "email", "Value": "typo@example.edu"},
        ],
    }
    _patch_cognito(monkeypatch, fake_cognito)
    _patch_connection(monkeypatch, state)

    roster = app_registry.resend_professor_section_student_invite(
        CurrentUser(
            cognito_sub="sub-prof", email="prof@example.edu", primary_role="professor"
        ),
        "mit14-fall-001",
        "student-1",
        ProfessorSectionStudentInviteCreate(
            email="corrected@example.edu", display_name="Student"
        ),
        runtime=_runtime(),
    )

    assert fake_cognito.deleted_usernames == ["typo@example.edu"]
    fresh_creates = [
        call
        for call in fake_cognito.created_users
        if call.get("MessageAction") != "RESEND"
    ]
    assert len(fresh_creates) == 1
    assert fresh_creates[0]["Username"] == "corrected@example.edu"
    assert state.users["student-1"]["email"] == "corrected@example.edu"
    assert state.users["student-1"]["cognito_sub"] == "sub-corrected@example.edu"
    assert any(student.email == "corrected@example.edu" for student in roster)


def test_professor_cannot_resend_invitation_for_confirmed_student(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _resend_invite_base_state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student@example.edu",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
        status="active",
    )

    fake_cognito = _FakeCognitoClient()
    fake_cognito._users_by_email["student@example.edu"] = {
        "Username": "student@example.edu",
        "UserStatus": "CONFIRMED",
        "Attributes": [
            {"Name": "sub", "Value": "sub-student@example.edu"},
            {"Name": "email", "Value": "student@example.edu"},
        ],
    }
    _patch_cognito(monkeypatch, fake_cognito)
    _patch_connection(monkeypatch, state)

    with pytest.raises(app_registry.AppUserConflictError):
        app_registry.resend_professor_section_student_invite(
            CurrentUser(
                cognito_sub="sub-prof",
                email="prof@example.edu",
                primary_role="professor",
            ),
            "mit14-fall-001",
            "student-1",
            ProfessorSectionStudentInviteCreate(
                email="student@example.edu", display_name="Student"
            ),
            runtime=_runtime(),
        )

    assert fake_cognito.deleted_usernames == []
    assert fake_cognito.created_users == []


def test_professor_cannot_resend_invitation_to_email_used_by_another_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _resend_invite_base_state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="typo@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
        cognito_sub="sub-typo@example.edu",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
        status="invited",
    )
    state.users["other-student"] = _user(
        user_id="other-student",
        email="taken@example.edu",
        display_name="Other",
        primary_role="student",
        status="active",
        cognito_sub="sub-taken@example.edu",
    )

    fake_cognito = _FakeCognitoClient()
    fake_cognito._users_by_email["typo@example.edu"] = {
        "Username": "typo@example.edu",
        "UserStatus": "FORCE_CHANGE_PASSWORD",
        "Attributes": [
            {"Name": "sub", "Value": "sub-typo@example.edu"},
            {"Name": "email", "Value": "typo@example.edu"},
        ],
    }
    _patch_cognito(monkeypatch, fake_cognito)
    _patch_connection(monkeypatch, state)

    with pytest.raises(app_registry.AppUserConflictError):
        app_registry.resend_professor_section_student_invite(
            CurrentUser(
                cognito_sub="sub-prof",
                email="prof@example.edu",
                primary_role="professor",
            ),
            "mit14-fall-001",
            "student-1",
            ProfessorSectionStudentInviteCreate(
                email="taken@example.edu", display_name="Student"
            ),
            runtime=_runtime(),
        )

    assert fake_cognito.deleted_usernames == []
    assert fake_cognito.created_users == []


def test_professor_can_view_student_analytics_for_assigned_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.tutor_sessions.extend(
        [
            {
                "session_id": "sess-1",
                "user_sub": "sub-student",
                "app_user_id": "student-1",
                "section_id": "mit14-fall-001",
                "last_seen_at": NOW,
                "updated_at": NOW,
            },
            {
                "session_id": "sess-2",
                "user_sub": "sub-student",
                "app_user_id": "student-1",
                "section_id": "mit14-fall-001",
                "last_seen_at": NOW - timedelta(days=1),
                "updated_at": NOW - timedelta(days=1),
            },
        ]
    )
    state.tutor_turns.extend(
        [
            {
                "turn_id": "turn-1",
                "session_id": "sess-1",
                "request_id": "req-1",
                "turn_index": 1,
                "user_sub": "sub-student",
                "app_user_id": "student-1",
                "section_id": "mit14-fall-001",
                "created_at": NOW,
                "updated_at": NOW,
                "completed_at": NOW,
            },
            {
                "turn_id": "turn-2",
                "session_id": "sess-2",
                "request_id": "req-2",
                "turn_index": 2,
                "user_sub": "sub-student",
                "app_user_id": "student-1",
                "section_id": "mit14-fall-001",
                "created_at": NOW - timedelta(days=1),
                "updated_at": NOW - timedelta(days=1),
                "completed_at": NOW - timedelta(days=1),
            },
        ]
    )
    state.tutor_turn_snapshots.extend(
        [
            {
                "turn_id": "turn-1",
                "session_id": "sess-1",
                "request_id": "req-1",
                "turn_index": 1,
                "user_sub": "sub-student",
                "app_user_id": "student-1",
                "section_id": "mit14-fall-001",
                "snapshot": {"feedback": {"thumbs_up": "positive"}},
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "turn_id": "turn-2",
                "session_id": "sess-2",
                "request_id": "req-2",
                "turn_index": 2,
                "user_sub": "sub-student",
                "app_user_id": "student-1",
                "section_id": "mit14-fall-001",
                "snapshot": {"feedback": {"thumbs_up": "negative"}},
                "created_at": NOW - timedelta(days=1),
                "updated_at": NOW - timedelta(days=1),
            },
        ]
    )
    _patch_connection(monkeypatch, state)

    analytics = app_registry.get_professor_section_student_analytics(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        "student-1",
        runtime=_runtime(),
    )

    assert isinstance(analytics, ProfessorSectionStudentAnalytics)
    assert analytics.section.section_id == "mit14-fall-001"
    assert analytics.student.email == "student@example.edu"
    assert analytics.total_sessions == 2
    assert analytics.total_turns == 2
    assert analytics.positive_feedback_count == 1
    assert analytics.negative_feedback_count == 1
    assert len(analytics.weekly_activity) == 7
    assert sum(point.sessions for point in analytics.weekly_activity) == 2
    assert sum(point.turns for point in analytics.weekly_activity) == 2


# --- Admin-driven student enrollment (Parts 1-4) ---


def test_login_activates_all_invited_section_memberships_by_cognito_sub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.sections["mit14-fall-002"] = _section(
        section_id="mit14-fall-002",
        display_name="MIT 6.0014 Section B",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
        status="invited",
    )
    state.memberships[("mit14-fall-002", "student-1")] = _membership(
        section_id="mit14-fall-002",
        user_id="student-1",
        role_in_section="student",
        status="invited",
    )
    _patch_connection(monkeypatch, state)

    app_registry.resolve_application_user(
        CurrentUser(
            cognito_sub="sub-student",
            email="student@example.edu",
            primary_role="student",
        ),
        runtime=_runtime(),
    )

    assert state.users["student-1"]["status"] == "active"
    assert state.memberships[("mit14-fall-001", "student-1")]["status"] == "active"
    assert state.memberships[("mit14-fall-002", "student-1")]["status"] == "active"


def test_login_activates_invited_section_memberships_by_email_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-2"] = _user(
        user_id="student-2",
        email="student2@example.edu",
        display_name="Student Two",
        primary_role="student",
        status="invited",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.memberships[("mit14-fall-001", "student-2")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-2",
        role_in_section="student",
        status="invited",
    )
    _patch_connection(monkeypatch, state)

    app_registry.resolve_application_user(
        CurrentUser(
            cognito_sub="sub-student-2",
            email="student2@example.edu",
            primary_role="student",
        ),
        runtime=_runtime(),
    )

    assert state.users["student-2"]["status"] == "active"
    assert state.memberships[("mit14-fall-001", "student-2")]["status"] == "active"


def test_create_section_membership_derives_active_status_for_already_active_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    _patch_connection(monkeypatch, state)

    app_registry.create_section_membership(
        "mit14-fall-001",
        AdminSectionMembershipCreate(user_id="prof-1", role_in_section="professor"),
        runtime=_runtime(),
    )

    assert state.memberships[("mit14-fall-001", "prof-1")]["status"] == "active"


def test_create_section_membership_derives_invited_status_for_not_yet_active_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    _patch_connection(monkeypatch, state)

    app_registry.create_section_membership(
        "mit14-fall-001",
        AdminSectionMembershipCreate(user_id="student-1", role_in_section="student"),
        runtime=_runtime(),
    )

    assert state.memberships[("mit14-fall-001", "student-1")]["status"] == "invited"


def test_admin_invite_section_student_creates_cognito_and_aurora_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    fake_cognito = _FakeCognitoClient()
    _patch_cognito(monkeypatch, fake_cognito)
    _patch_connection(monkeypatch, state)

    result = app_registry.invite_admin_section_student(
        "mit14-fall-001",
        ProfessorSectionStudentInviteCreate(
            email="newstudent@example.edu", display_name="New Student"
        ),
        runtime=_runtime(),
    )

    assert result.section_id == "mit14-fall-001"
    invite_calls = [
        call
        for call in fake_cognito.created_users
        if call.get("MessageAction") != "RESEND"
    ]
    assert len(invite_calls) == 1
    assert invite_calls[0]["Username"] == "newstudent@example.edu"

    created_user = next(
        record
        for record in state.users.values()
        if record["email"] == "newstudent@example.edu"
    )
    assert created_user["status"] == "invited"
    assert created_user["primary_role"] == "student"
    membership = state.memberships[("mit14-fall-001", created_user["user_id"])]
    assert membership["status"] == "invited"
    assert membership["role_in_section"] == "student"
    assert any(m.user_id == created_user["user_id"] for m in result.memberships)


def test_admin_invite_section_student_does_not_require_admin_section_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression guard: unlike the professor invite path, the admin path must
    # not call require_section_membership — admins are not necessarily
    # members of every section they administer.
    state = _state()
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    fake_cognito = _FakeCognitoClient()
    _patch_cognito(monkeypatch, fake_cognito)
    _patch_connection(monkeypatch, state)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("require_section_membership should not be called for admin invites")

    monkeypatch.setattr(
        app_registry, "require_section_membership", _fail_if_called
    )

    result = app_registry.invite_admin_section_student(
        "mit14-fall-001",
        ProfessorSectionStudentInviteCreate(email="another@example.edu"),
        runtime=_runtime(),
    )

    created_user = next(
        record
        for record in state.users.values()
        if record["email"] == "another@example.edu"
    )
    assert any(m.user_id == created_user["user_id"] for m in result.memberships)


def test_create_admin_user_rejects_student_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    _patch_connection(monkeypatch, state)

    with pytest.raises(ValueError):
        app_registry.create_admin_user(
            AdminUserCreate(
                email="student@example.edu",
                display_name="Student",
                primary_role="student",
            ),
            runtime=_runtime(),
        )


# --- Aurora password-rotation recovery (app_registry._connect_postgres) ---


def test_app_registry_connect_postgres_refreshes_on_password_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    import rag_eng.aurora_secret_refresh as aurora_secret_refresh

    aurora_secret_refresh._refreshed_database_url = None
    calls: list[str] = []
    sentinel_connection = object()

    def fake_connect(database_url, *, connect_timeout):
        calls.append(database_url)
        if database_url == "postgresql://stale":
            raise RuntimeError('FATAL:  password authentication failed for user "cr_app"')
        return sentinel_connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setattr(
        app_registry, "refresh_database_url_from_secrets_manager", lambda: "postgresql://fresh"
    )

    connection = app_registry._connect_postgres("postgresql://stale", 5)

    assert connection is sentinel_connection
    assert calls == ["postgresql://stale", "postgresql://fresh"]

    aurora_secret_refresh._refreshed_database_url = None


def test_app_registry_connect_postgres_does_not_refresh_on_non_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    import rag_eng.aurora_secret_refresh as aurora_secret_refresh

    aurora_secret_refresh._refreshed_database_url = None
    refresh_calls: list[bool] = []

    def fake_connect(database_url, *, connect_timeout):
        raise RuntimeError("connection timeout expired")

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setattr(
        app_registry,
        "refresh_database_url_from_secrets_manager",
        lambda: refresh_calls.append(True) or "postgresql://fresh",
    )

    with pytest.raises(RuntimeError, match="connection timeout expired"):
        app_registry._connect_postgres("postgresql://example", 5)

    assert refresh_calls == []


def test_app_registry_connect_postgres_prefers_previously_cached_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg
    import rag_eng.aurora_secret_refresh as aurora_secret_refresh

    aurora_secret_refresh._refreshed_database_url = "postgresql://already-fresh"
    calls: list[str] = []
    sentinel_connection = object()

    def fake_connect(database_url, *, connect_timeout):
        calls.append(database_url)
        return sentinel_connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    connection = app_registry._connect_postgres("postgresql://stale-from-env", 5)

    assert connection is sentinel_connection
    assert calls == ["postgresql://already-fresh"]

    aurora_secret_refresh._refreshed_database_url = None
