from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import uuid

import pytest

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
    ProfessorTeachingPlanWeekUpdate,
    ProfessorSectionAnalytics,
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
    launch_configs: dict[str, list[dict[str, object]]]
    teaching_plans: dict[str, dict[str, object]]
    teaching_plan_weeks: dict[str, dict[str, object]]
    tutor_sessions: list[dict[str, object]]


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
            record["created_at"],
            record["updated_at"],
        )

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        sql = self._normalize_sql(query)
        params = params or ()
        self.rowcount = 0
        self._rows = []

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users WHERE cognito_sub = %s"
        ):
            cognito_sub = str(params[0])
            for record in self.state.users.values():
                if str(record.get("cognito_sub", "")) == cognito_sub:
                    self._rows = [self._user_row(record)]
                    return
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users WHERE lower(email) = lower(%s)"
        ):
            email = str(params[0]).casefold()
            for record in self.state.users.values():
                if str(record["email"]).casefold() == email:
                    self._rows = [self._user_row(record)]
                    return
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users WHERE user_id = %s"
        ):
            user_id = str(params[0])
            record = self.state.users.get(user_id)
            if record is not None:
                self._rows = [self._user_row(record)]
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users ORDER BY email ASC"
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
            email, display_name, primary_role, status = params
            self.state.users[user_id] = {
                "user_id": user_id,
                "cognito_sub": None,
                "email": str(email),
                "display_name": str(display_name),
                "primary_role": str(primary_role),
                "status": str(status),
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
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id ORDER BY s.section_id ASC"
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
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id WHERE EXISTS ( SELECT 1 FROM section_memberships AS sm WHERE sm.section_id = s.section_id AND sm.user_id = %s AND sm.status = 'active' AND sm.role_in_section IN ('professor', 'ta') ) AND s.is_active = TRUE ORDER BY s.section_id ASC"
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

        if sql.startswith(
            "SELECT u.user_id, u.cognito_sub, u.email, u.display_name, sm.status, sm.role_in_section, COALESCE(stats.session_count, 0) AS session_count, stats.last_session_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id LEFT JOIN ( SELECT user_sub, COUNT(*) AS session_count, MAX(last_seen_at) AS last_session_at FROM tutor_sessions WHERE section_id = %s GROUP BY user_sub ) AS stats ON stats.user_sub = u.cognito_sub WHERE sm.section_id = %s AND sm.role_in_section = 'student' AND sm.status = 'active' ORDER BY u.display_name ASC, u.email ASC"
        ):
            section_id = str(params[0])
            rows = [
                self._student_row(membership)
                for membership in self.state.memberships.values()
                if str(membership["section_id"]) == section_id
                and str(membership["role_in_section"]) == "student"
                and str(membership["status"]) == "active"
            ]
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
            "SELECT TO_CHAR((last_seen_at AT TIME ZONE %s), 'Dy') AS day, COUNT(*) AS sessions, COUNT(DISTINCT user_sub) AS active_students FROM tutor_sessions WHERE section_id = %s AND last_seen_at >= (CURRENT_TIMESTAMP AT TIME ZONE %s)::DATE - INTERVAL '6 days' GROUP BY DATE((last_seen_at AT TIME ZONE %s)), day ORDER BY DATE((last_seen_at AT TIME ZONE %s)) ASC"
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
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, sm.status, s.created_at, s.updated_at FROM section_memberships AS sm INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE sm.user_id = %s AND sm.role_in_section = 'student' AND sm.status = 'active' AND s.is_active = TRUE ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._student_section_row(membership)
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["role_in_section"]) == "student"
                and str(membership["status"]) == "active"
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
            ]
            self._rows = sorted(rows, key=lambda row: str(row[0]))
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, sm.status, s.created_at, s.updated_at FROM section_memberships AS sm INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE sm.user_id = %s AND sm.role_in_section IN ('student', 'professor', 'ta') AND sm.status = 'active' AND s.is_active = TRUE ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._student_section_row(membership)
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["status"]) == "active"
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
                and str(membership["role_in_section"]) in {"student", "professor", "ta"}
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

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id WHERE s.section_id = %s"
        ):
            section_id = str(params[0])
            record = self.state.sections.get(section_id)
            if record is not None:
                self._rows = [self._section_row(record)]
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
            "SELECT week_id, teaching_plan_id, week_number, title, topic, start_date, end_date, learning_objectives, instructional_guidance, status, created_at, updated_at FROM teaching_plan_weeks WHERE teaching_plan_id = %s ORDER BY week_number ASC, week_id ASC"
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
            "SELECT week_id FROM teaching_plan_weeks WHERE teaching_plan_id = %s AND week_number = %s"
        ):
            teaching_plan_id, week_number = params
            for record in self.state.teaching_plan_weeks.values():
                if str(record["teaching_plan_id"]) == str(teaching_plan_id) and int(record["week_number"]) == int(week_number):
                    self._rows = [(record["week_id"],)]
                    return
            return

        if sql.startswith(
            "SELECT tw.week_id, tw.teaching_plan_id, tw.week_number, tw.title, tw.topic, tw.start_date, tw.end_date, tw.learning_objectives, tw.instructional_guidance, tw.status, tw.created_at, tw.updated_at FROM teaching_plan_weeks AS tw INNER JOIN teaching_plans AS tp ON tp.teaching_plan_id = tw.teaching_plan_id WHERE tp.section_id = %s AND tw.week_id = %s"
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
            "INSERT INTO teaching_plan_weeks ( week_id, teaching_plan_id, week_number, title, topic, start_date, end_date, learning_objectives, instructional_guidance, status ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)"
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
        launch_configs={},
        teaching_plans={},
        teaching_plan_weeks={},
        tutor_sessions=[],
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
