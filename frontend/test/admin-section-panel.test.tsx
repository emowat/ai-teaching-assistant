import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SectionManagementPanel } from "../src/components/admin/SectionManagementPanel";
import {
  createAdminSection,
  createAdminSectionMembership,
  listAdminSections,
  removeAdminSectionMembership,
  updateAdminSection,
  updateAdminSectionMembership,
} from "../src/api/adminSectionsApi";
import { listAdminUsers } from "../src/api/adminUsersApi";

vi.mock("../src/api/adminSectionsApi", () => ({
  createAdminSection: vi.fn(),
  createAdminSectionMembership: vi.fn(),
  listAdminSections: vi.fn(),
  removeAdminSectionMembership: vi.fn(),
  updateAdminSection: vi.fn(),
  updateAdminSectionMembership: vi.fn(),
}));

vi.mock("../src/api/adminUsersApi", () => ({
  listAdminUsers: vi.fn(),
}));

const mockedListAdminSections = vi.mocked(listAdminSections);
const mockedListAdminUsers = vi.mocked(listAdminUsers);
const mockedCreateAdminSection = vi.mocked(createAdminSection);
const mockedUpdateAdminSection = vi.mocked(updateAdminSection);
const mockedCreateAdminSectionMembership = vi.mocked(createAdminSectionMembership);
const mockedUpdateAdminSectionMembership = vi.mocked(updateAdminSectionMembership);
const mockedRemoveAdminSectionMembership = vi.mocked(removeAdminSectionMembership);

describe("SectionManagementPanel", () => {
  beforeEach(() => {
    mockedListAdminSections.mockReset();
    mockedListAdminUsers.mockReset();
    mockedCreateAdminSection.mockReset();
    mockedUpdateAdminSection.mockReset();
    mockedCreateAdminSectionMembership.mockReset();
    mockedUpdateAdminSectionMembership.mockReset();
    mockedRemoveAdminSectionMembership.mockReset();
  });

  it("refreshes the section roster from Aurora", async () => {
    mockedListAdminSections
      .mockResolvedValueOnce([
        {
          section_id: "mit14-fall-001",
          course_id: "mit14",
          course_display_name: "MIT 6.0014",
          display_name: "Section A",
          term: "Fall 2026",
          is_active: true,
          professor_count: 1,
          ta_count: 0,
          student_count: 1,
          memberships: [],
          created_at: "2026-07-09T00:00:00Z",
          updated_at: "2026-07-09T00:00:00Z",
        },
      ])
      .mockResolvedValueOnce([
        {
          section_id: "mit14-fall-001",
          course_id: "mit14",
          course_display_name: "MIT 6.0014",
          display_name: "Section A",
          term: "Fall 2026",
          is_active: true,
          professor_count: 1,
          ta_count: 0,
          student_count: 1,
          memberships: [],
          created_at: "2026-07-09T00:00:00Z",
          updated_at: "2026-07-09T00:00:00Z",
        },
        {
          section_id: "mit14-fall-002",
          course_id: "mit14",
          course_display_name: "MIT 6.0014",
          display_name: "Section B",
          term: "Fall 2026",
          is_active: true,
          professor_count: 0,
          ta_count: 0,
          student_count: 0,
          memberships: [],
          created_at: "2026-07-09T00:00:00Z",
          updated_at: "2026-07-09T00:00:00Z",
        },
      ]);

    mockedListAdminUsers.mockResolvedValue([
      {
        user_id: "user-1",
        cognito_sub: null,
        email: "student@example.edu",
        display_name: "Student One",
        primary_role: "student",
        status: "invited",
        section_memberships: [],
        created_at: "2026-07-09T00:00:00Z",
        updated_at: "2026-07-09T00:00:00Z",
      },
    ]);

    render(<SectionManagementPanel accessToken="access-token-1" />);

    expect(await screen.findByText("Sections")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();

    screen.getByRole("button", { name: /refresh/i }).click();

    expect(await screen.findByText("Refreshed 2 sections.")).toBeInTheDocument();
    expect(await screen.findByText("2 total")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockedListAdminSections).toHaveBeenCalledTimes(2);
      expect(mockedListAdminUsers).toHaveBeenCalledTimes(2);
    });
  });

  it("removes a membership from the section entirely", async () => {
    const membership = {
      section_id: "mit14-fall-001",
      user_id: "user-1",
      section_display_name: "Section A",
      course_id: "mit14",
      course_display_name: "MIT 6.0014",
      role_in_section: "professor" as const,
      status: "active" as const,
      created_at: "2026-07-09T00:00:00Z",
      updated_at: "2026-07-09T00:00:00Z",
    };
    const section = {
      section_id: "mit14-fall-001",
      course_id: "mit14",
      course_display_name: "MIT 6.0014",
      display_name: "Section A",
      term: "Fall 2026",
      is_active: true,
      professor_count: 1,
      ta_count: 0,
      student_count: 0,
      memberships: [membership],
      created_at: "2026-07-09T00:00:00Z",
      updated_at: "2026-07-09T00:00:00Z",
      archived_at: "",
    };

    mockedListAdminSections.mockResolvedValue([section]);
    mockedListAdminUsers.mockResolvedValue([
      {
        user_id: "user-1",
        cognito_sub: "sub-1",
        email: "prof@example.edu",
        display_name: "Prof One",
        primary_role: "professor",
        status: "active",
        section_memberships: [],
        created_at: "2026-07-09T00:00:00Z",
        updated_at: "2026-07-09T00:00:00Z",
      },
    ]);
    mockedRemoveAdminSectionMembership.mockResolvedValue({
      ...section,
      memberships: [],
    });

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<SectionManagementPanel accessToken="access-token-1" />);

    const removeButton = await screen.findByRole("button", { name: "Remove from section" });
    removeButton.click();

    await waitFor(() => {
      expect(mockedRemoveAdminSectionMembership).toHaveBeenCalledWith(
        "mit14-fall-001",
        "user-1",
        "access-token-1"
      );
    });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Remove from section" })).not.toBeInTheDocument();
    });
    expect(screen.getByText("Select a membership to edit it.")).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it("does not call the API when the removal confirm dialog is cancelled", async () => {
    const membership = {
      section_id: "mit14-fall-001",
      user_id: "user-1",
      section_display_name: "Section A",
      course_id: "mit14",
      course_display_name: "MIT 6.0014",
      role_in_section: "professor" as const,
      status: "active" as const,
      created_at: "2026-07-09T00:00:00Z",
      updated_at: "2026-07-09T00:00:00Z",
    };
    mockedListAdminSections.mockResolvedValue([
      {
        section_id: "mit14-fall-001",
        course_id: "mit14",
        course_display_name: "MIT 6.0014",
        display_name: "Section A",
        term: "Fall 2026",
        is_active: true,
        professor_count: 1,
        ta_count: 0,
        student_count: 0,
        memberships: [membership],
        created_at: "2026-07-09T00:00:00Z",
        updated_at: "2026-07-09T00:00:00Z",
        archived_at: "",
      },
    ]);
    mockedListAdminUsers.mockResolvedValue([]);

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<SectionManagementPanel accessToken="access-token-1" />);

    const removeButton = await screen.findByRole("button", { name: "Remove from section" });
    removeButton.click();

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(mockedRemoveAdminSectionMembership).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
