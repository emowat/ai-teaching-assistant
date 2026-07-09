import * as vscode from 'vscode';

export const STUDENT_SECTION_STATE_KEY = 'codingRabbit.student.sectionId';

function normalizeSectionId(value: string | null | undefined): string | null {
    const trimmed = (value ?? '').trim();
    return trimmed || null;
}

export function loadStoredStudentSectionId(workspaceState: vscode.Memento): string | null {
    return normalizeSectionId(workspaceState.get<string>(STUDENT_SECTION_STATE_KEY));
}

export function storeSelectedStudentSectionId(
    workspaceState: vscode.Memento,
    sectionId: string,
): Thenable<void> {
    return workspaceState.update(STUDENT_SECTION_STATE_KEY, normalizeSectionId(sectionId));
}

export function clearStoredStudentSectionId(workspaceState: vscode.Memento): Thenable<void> {
    return workspaceState.update(STUDENT_SECTION_STATE_KEY, undefined);
}
