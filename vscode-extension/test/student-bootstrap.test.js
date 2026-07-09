const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildStudentApiUrl,
  selectStudentSectionId,
  getStudentSection,
} = require('../out/student/bootstrap.js');
const {
  STUDENT_SECTION_STATE_KEY,
  loadStoredStudentSectionId,
  storeSelectedStudentSectionId,
  clearStoredStudentSectionId,
} = require('../out/student/sectionState.js');

const bootstrap = {
  user: {
    app_user_id: 'user-1',
    email: 'student@example.com',
    display_name: 'Student Example',
    primary_role: 'student',
    status: 'active',
  },
  default_section_id: 'sec-2',
  endpoints: {
    chat: '/api/student/chat',
    telemetry: '/api/student/telemetry',
    feedback: '/api/student/feedback',
  },
  sections: [
    {
      section_id: 'sec-1',
      course_id: 'mit14',
      course_display_name: 'MIT 6.0001',
      display_name: 'Section A',
      term: 'Fall 2026',
      is_active: true,
      membership_status: 'active',
      launch_configs: [],
    },
    {
      section_id: 'sec-2',
      course_id: 'mit14',
      course_display_name: 'MIT 6.0001',
      display_name: 'Section B',
      term: 'Fall 2026',
      is_active: true,
      membership_status: 'active',
      launch_configs: [],
    },
    {
      section_id: 'sec-3',
      course_id: 'mit14',
      course_display_name: 'MIT 6.0001',
      display_name: 'Archived',
      term: 'Fall 2025',
      is_active: false,
      membership_status: 'active',
      launch_configs: [],
    },
  ],
};

test('selectStudentSectionId prefers an explicitly selected active section', () => {
  assert.equal(selectStudentSectionId(bootstrap, 'sec-1'), 'sec-1');
});

test('selectStudentSectionId falls back to the default active section', () => {
  assert.equal(selectStudentSectionId(bootstrap, undefined), 'sec-2');
});

test('selectStudentSectionId ignores inactive sections when restoring selection', () => {
  const selected = selectStudentSectionId(bootstrap, 'sec-3');
  assert.equal(selected, 'sec-2');
});

test('getStudentSection returns the matching section object', () => {
  assert.equal(getStudentSection(bootstrap, 'sec-1')?.display_name, 'Section A');
});

test('buildStudentApiUrl joins base URLs and endpoint paths cleanly', () => {
  assert.equal(
    buildStudentApiUrl('https://example.com/', '/api/student/bootstrap'),
    'https://example.com/api/student/bootstrap',
  );
});

test('loadStoredStudentSectionId trims persisted values and ignores blanks', () => {
  const workspaceState = {
    get(key) {
      return key === STUDENT_SECTION_STATE_KEY ? '  sec-1  ' : undefined;
    },
  };

  assert.equal(loadStoredStudentSectionId(workspaceState), 'sec-1');

  const blankState = {
    get(key) {
      return key === STUDENT_SECTION_STATE_KEY ? '   ' : undefined;
    },
  };

  assert.equal(loadStoredStudentSectionId(blankState), null);
});

test('storeSelectedStudentSectionId and clearStoredStudentSectionId update workspace state', async () => {
  const updates = [];
  const workspaceState = {
    get() {
      return undefined;
    },
    update(key, value) {
      updates.push({ key, value });
      return Promise.resolve();
    },
  };

  await storeSelectedStudentSectionId(workspaceState, '  sec-2  ');
  await clearStoredStudentSectionId(workspaceState);

  assert.deepEqual(updates, [
    { key: STUDENT_SECTION_STATE_KEY, value: 'sec-2' },
    { key: STUDENT_SECTION_STATE_KEY, value: undefined },
  ]);
});
