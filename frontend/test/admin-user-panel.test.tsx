import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserManagementPanel } from "../src/components/admin/UserManagementPanel";
import {
  createAdminUser,
  listAdminUsers,
  updateAdminUser,
} from "../src/api/adminUsersApi";

vi.mock("../src/api/adminUsersApi", () => ({
  listAdminUsers: vi.fn(),
  createAdminUser: vi.fn(),
  updateAdminUser: vi.fn(),
}));

const mockedListAdminUsers = vi.mocked(listAdminUsers);
const mockedCreateAdminUser = vi.mocked(createAdminUser);
const mockedUpdateAdminUser = vi.mocked(updateAdminUser);

describe("UserManagementPanel", () => {
  beforeEach(() => {
    mockedListAdminUsers.mockReset();
    mockedCreateAdminUser.mockReset();
    mockedUpdateAdminUser.mockReset();
  });

  it("shows the provisioning note and refreshes the user roster", async () => {
    mockedListAdminUsers
      .mockResolvedValueOnce([
        {
          user_id: "user-1",
          cognito_sub: null,
          email: "old@example.edu",
          display_name: "Old User",
          primary_role: "student",
          status: "invited",
          section_memberships: [],
          created_at: "2026-07-09T00:00:00Z",
          updated_at: "2026-07-09T00:00:00Z",
        },
      ])
      .mockResolvedValueOnce([
        {
          user_id: "user-2",
          cognito_sub: "cognito-sub-2",
          email: "new@example.edu",
          display_name: "New User",
          primary_role: "professor",
          status: "active",
          section_memberships: [],
          created_at: "2026-07-09T00:00:00Z",
          updated_at: "2026-07-09T00:00:00Z",
        },
      ]);

    render(<UserManagementPanel accessToken="access-token-1" />);

    expect(
      await screen.findByText(/invite users in aurora first/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();

    screen.getByRole("button", { name: /refresh/i }).click();

    expect(await screen.findByText("Refreshed 1 users.")).toBeInTheDocument();
    expect(screen.queryByText("old@example.edu")).not.toBeInTheDocument();
    expect(screen.getAllByText("new@example.edu").length).toBeGreaterThan(0);

    await waitFor(() => {
      expect(mockedListAdminUsers).toHaveBeenCalledTimes(2);
    });
  });
});
