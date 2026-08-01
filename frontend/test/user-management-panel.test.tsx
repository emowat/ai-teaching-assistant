import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UserManagementPanel } from "../src/components/admin/UserManagementPanel";
import { listAdminUsers, type AdminUser } from "../src/api/adminUsersApi";

vi.mock("../src/api/adminUsersApi", async () => {
  const actual = await vi.importActual<typeof import("../src/api/adminUsersApi")>(
    "../src/api/adminUsersApi"
  );
  return {
    ...actual,
    listAdminUsers: vi.fn(),
    createAdminUser: vi.fn(),
    updateAdminUser: vi.fn(),
  };
});

const mockedListAdminUsers = vi.mocked(listAdminUsers);

const admin: AdminUser = {
  user_id: "admin-1",
  cognito_sub: "sub-admin-1",
  email: "admin1@example.edu",
  display_name: "Admin One",
  primary_role: "admin",
  status: "active",
  section_memberships: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const professor: AdminUser = {
  user_id: "prof-1",
  cognito_sub: "sub-prof-1",
  email: "prof1@example.edu",
  display_name: "Prof One",
  primary_role: "professor",
  status: "active",
  section_memberships: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("UserManagementPanel", () => {
  it("shows the invite form when '-- Invite New User --' is selected", async () => {
    mockedListAdminUsers.mockResolvedValue([professor]);

    render(<UserManagementPanel accessToken="test-token" />);

    await waitFor(() => expect(screen.getByDisplayValue("Prof One")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Select User to Manage"), {
      target: { value: "NEW" },
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Invite user" })).toBeInTheDocument();
      expect(screen.getByText("Email")).toBeInTheDocument();
    });
  });

  it("resyncs the selection when a role filter excludes the currently-selected user", async () => {
    // Regression: the API returns the admin first, so it's auto-selected on
    // load. Filtering to "professor" then drops that admin out of the "Select
    // User to Manage" option list. Before the fix, selectedUserId stayed
    // pointed at the filtered-out admin, so the dropdown fell back to
    // displaying "-- Invite New User --" (the browser's default when the
    // controlled value has no matching option) while React's state still
    // showed the admin's edit form underneath - clicking the already-displayed
    // "Invite New User" option fired no change event, so nothing happened.
    mockedListAdminUsers.mockResolvedValue([admin, professor]);

    render(<UserManagementPanel accessToken="test-token" />);

    await waitFor(() => expect(screen.getByDisplayValue("Admin One")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Role filter"), {
      target: { value: "professor" },
    });

    // The selection should resync to the first remaining match (the professor),
    // not silently keep the filtered-out admin selected underneath a desynced dropdown.
    await waitFor(() => expect(screen.getByDisplayValue("Prof One")).toBeInTheDocument());

    const userSelect = screen.getByLabelText("Select User to Manage") as HTMLSelectElement;
    expect(userSelect.value).toBe("prof-1");

    fireEvent.change(userSelect, { target: { value: "NEW" } });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Invite user" })).toBeInTheDocument();
      expect(screen.getByText("Email")).toBeInTheDocument();
    });
  });

  it("leaves the invite form alone when a filter changes while already on it", async () => {
    mockedListAdminUsers.mockResolvedValue([admin, professor]);

    render(<UserManagementPanel accessToken="test-token" />);

    await waitFor(() => expect(screen.getByDisplayValue("Admin One")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Select User to Manage"), {
      target: { value: "NEW" },
    });
    await waitFor(() => expect(screen.getByText("Email")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Role filter"), {
      target: { value: "professor" },
    });

    // Still on the invite form - a filter change shouldn't yank you off it
    // mid-fill just because it happens to also affect the user list.
    expect(screen.getByRole("button", { name: "Invite user" })).toBeInTheDocument();
    expect(screen.getByText("Email")).toBeInTheDocument();
  });
});
