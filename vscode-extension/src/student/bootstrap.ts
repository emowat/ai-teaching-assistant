export interface StudentLaunchConfig {
    launch_id: string;
    label: string;
    repo_url: string;
    template_url: string;
    default_branch: string;
    enabled: boolean;
    sort_order: number;
}

export interface StudentBootstrapSection {
    section_id: string;
    course_id: string;
    course_display_name: string;
    display_name: string;
    term: string;
    is_active: boolean;
    membership_status: 'invited' | 'active' | 'dropped' | 'disabled';
    launch_configs: StudentLaunchConfig[];
}

export interface StudentBootstrapUser {
    app_user_id: string;
    cognito_sub?: string | null;
    email: string;
    display_name: string;
    primary_role: 'admin' | 'professor' | 'student';
    status: 'invited' | 'active' | 'disabled';
}

export interface StudentBootstrapEndpoints {
    chat: string;
    telemetry: string;
    feedback: string;
}

export interface StudentBootstrapResponse {
    user: StudentBootstrapUser;
    sections: StudentBootstrapSection[];
    default_section_id?: string | null;
    endpoints: StudentBootstrapEndpoints;
}

export interface StudentTurnContext {
    requestId: string;
    turnId: string;
    turnIndex: number;
    sectionId: string;
    courseId: string;
}

function normalizeId(value: string | null | undefined): string {
    return (value ?? '').trim();
}

function getActiveSections(bootstrap: StudentBootstrapResponse): StudentBootstrapSection[] {
    return bootstrap.sections.filter(section => section.is_active && section.membership_status === 'active');
}

export function selectStudentSectionId(
    bootstrap: StudentBootstrapResponse,
    preferredSectionId: string | null | undefined,
): string | null {
    const activeSections = getActiveSections(bootstrap);
    if (activeSections.length === 0) {
        return null;
    }

    const preferred = normalizeId(preferredSectionId);
    if (preferred) {
        const preferredSection = activeSections.find(section => section.section_id === preferred);
        if (preferredSection) {
            return preferredSection.section_id;
        }
    }

    const defaultSectionId = normalizeId(bootstrap.default_section_id);
    if (defaultSectionId) {
        const defaultSection = activeSections.find(section => section.section_id === defaultSectionId);
        if (defaultSection) {
            return defaultSection.section_id;
        }
    }

    return activeSections[0]?.section_id ?? null;
}

export function getStudentSection(
    bootstrap: StudentBootstrapResponse,
    sectionId: string | null | undefined,
): StudentBootstrapSection | null {
    const normalized = normalizeId(sectionId);
    if (!normalized) {
        return null;
    }
    return bootstrap.sections.find(section => section.section_id === normalized) ?? null;
}

export function buildStudentApiUrl(baseUrl: string, endpointPath: string): string {
    const trimmedBaseUrl = baseUrl.replace(/\/$/, '');
    const trimmedPath = endpointPath.startsWith('/') ? endpointPath : `/${endpointPath}`;
    return `${trimmedBaseUrl}${trimmedPath}`;
}
