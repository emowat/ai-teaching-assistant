export type CognitoGroup = "Admins" | "Professors" | "Students";

export interface AppUser {
  sub: string;
  email?: string;
  groups: CognitoGroup[];
  primary_role?: string;
}
