const courseSelect = document.getElementById('records-course');
const joinCode = document.getElementById('join-code');
const rosterList = document.getElementById('roster-list');
const sessionList = document.getElementById('session-list');
const attendanceSection = document.getElementById('attendance-section');
const attendanceList = document.getElementById('attendance-list');
const attendanceCount = document.getElementById('attendance-count');
const auditList = document.getElementById('audit-list');
const notice = document.getElementById('records-notice');
const reasonInput = document.getElementById('correction-reason');
const exportLink = document.getElementById('export-link');
const sessionTitle = document.getElementById('selected-session-title');

let csrf = '';
let courses = [];
let selectedSession = null;
let refreshTimer = null;

function say(text, error = false) {
    notice.textContent = text;
    notice.dataset.error = String(error);
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: { ...(options.method ? { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf } : {}), ...options.headers },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
}

function node(tag, text, className) {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
}

function row(title, subtitle, badge) {
    const wrapper = node('div', '', 'list-row');
    const text = node('div', '', 'list-row-text');
    text.append(node('strong', title), node('small', subtitle));
    wrapper.append(text);
    if (badge) wrapper.append(node('span', badge, 'row-badge'));
    return wrapper;
}

async function loadCourses(preferredId) {
    courses = await api('/courses');
    const previous = preferredId || courseSelect.value;
    courseSelect.replaceChildren(new Option('Select a course', ''));
    for (const course of courses) courseSelect.add(new Option(`${course.code} · ${course.course_name}`, course.course_id));
    courseSelect.value = courses.some(course => course.course_id === previous) ? previous : (courses[0]?.course_id || '');
    await selectCourse();
}

async function selectCourse() {
    clearTimeout(refreshTimer);
    selectedSession = null;
    attendanceSection.hidden = true;
    const course = courses.find(item => item.course_id === courseSelect.value);
    joinCode.hidden = !course;
    joinCode.textContent = course ? `Class join code: ${course.join_code}` : '';
    rosterList.replaceChildren();
    sessionList.replaceChildren();
    if (!course) {
        rosterList.append(node('p', 'Create a course to get started.', 'empty-message'));
        return;
    }
    await Promise.all([loadRoster(course.course_id), loadSessions(course.course_id)]);
}

async function loadRoster(courseId) {
    const data = await api(`/courses/${encodeURIComponent(courseId)}/roster`);
    rosterList.replaceChildren();
    if (!data.students.length) rosterList.append(node('p', 'No students yet. Share the class join code.', 'empty-message'));
    for (const student of data.students) {
        const item = row(student.username, student.email, student.status);
        if (student.status !== 'approved') {
            const approve = node('button', 'Approve', 'mini-button');
            approve.type = 'button';
            approve.addEventListener('click', () => decideEnrollment(courseId, student.user_id, 'approved'));
            item.append(approve);
        }
        if (student.status !== 'removed') {
            const remove = node('button', 'Remove', 'mini-button mini-danger');
            remove.type = 'button';
            remove.addEventListener('click', () => decideEnrollment(courseId, student.user_id, 'removed'));
            item.append(remove);
        }
        rosterList.append(item);
    }
}

async function decideEnrollment(courseId, studentId, status) {
    try {
        await api(`/courses/${encodeURIComponent(courseId)}/enrollments/${encodeURIComponent(studentId)}`, {
            method: 'POST', body: JSON.stringify({ status }),
        });
        say(`Student ${status}.`);
        await loadRoster(courseId);
        if (selectedSession) await loadAttendance(selectedSession);
    } catch (error) { say(error.message, true); }
}

async function loadSessions(courseId) {
    const sessions = await api(`/courses/${encodeURIComponent(courseId)}/sessions`);
    sessionList.replaceChildren();
    if (!sessions.length) sessionList.append(node('p', 'No sessions yet. Start one from the live display.', 'empty-message'));
    for (const item of sessions) {
        const button = node('button', `${new Date(item.started_at).toLocaleString()} · ${item.status}`, 'session-button');
        button.type = 'button';
        button.addEventListener('click', () => selectSession(item.session_id, item.started_at));
        sessionList.append(button);
    }
}

async function selectSession(id, startedAt) {
    clearTimeout(refreshTimer);
    selectedSession = id;
    attendanceSection.hidden = false;
    sessionTitle.textContent = `Attendance · ${new Date(startedAt).toLocaleString()}`;
    exportLink.href = `/sessions/${encodeURIComponent(id)}/export`;
    await Promise.all([loadAttendance(id), loadAudit(id)]);
    scheduleRefresh(id);
}

function scheduleRefresh(id) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(async () => {
        if (selectedSession !== id) return;
        try { await loadAttendance(id); }
        catch (error) { say(`Could not refresh attendance: ${error.message}`, true); }
        scheduleRefresh(id);
    }, 5000);
}

async function loadAttendance(id) {
    const data = await api(`/sessions/${encodeURIComponent(id)}/attendance`);
    if (selectedSession !== id) return;
    attendanceCount.textContent = `${data.present_count} of ${data.roster_count} approved students present`;
    attendanceList.replaceChildren();
    if (!data.students.length) attendanceList.append(node('p', 'No students on this roster.', 'empty-message'));
    for (const student of data.students) {
        const detail = student.present
            ? `${student.email} · ${student.source} · ${new Date(student.marked_at).toLocaleString()}`
            : `${student.email} · ${student.enrollment_status}`;
        const item = row(student.username, detail, student.present ? 'Present' : 'Absent');
        if (student.enrollment_status === 'approved') {
            const action = node('button', student.present ? 'Void' : 'Mark present', student.present ? 'mini-button mini-danger' : 'mini-button');
            action.type = 'button';
            action.addEventListener('click', () => correctAttendance(id, student.user_id, student.present));
            item.append(action);
        }
        attendanceList.append(item);
    }
}

async function correctAttendance(id, studentId, present) {
    const reason = reasonInput.value.trim();
    if (reason.length < 3) { say('Enter a reason before changing attendance.', true); reasonInput.focus(); return; }
    const url = `/sessions/${encodeURIComponent(id)}/attendance/${encodeURIComponent(studentId)}${present ? '/void' : ''}`;
    try {
        await api(url, { method: 'POST', body: JSON.stringify({ reason }) });
        reasonInput.value = '';
        say(present ? 'Attendance voided with an audit entry.' : 'Student marked present with an audit entry.');
        await Promise.all([loadAttendance(id), loadAudit(id)]);
    } catch (error) { say(error.message, true); }
}

async function loadAudit(id) {
    const events = await api(`/sessions/${encodeURIComponent(id)}/audit`);
    if (selectedSession !== id) return;
    auditList.replaceChildren();
    if (!events.length) auditList.append(node('p', 'No audit events yet.', 'empty-message'));
    for (const event of events) {
        auditList.append(row(event.event_type.replaceAll('_', ' '), `${new Date(event.created_at).toLocaleString()}${event.reason ? ` · ${event.reason}` : ''}`, ''));
    }
}

courseSelect.addEventListener('change', () => selectCourse().catch(error => say(error.message, true)));

document.getElementById('create-course-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const course_name = document.getElementById('new-course-name').value.trim();
    const code = document.getElementById('new-course-code').value.trim();
    try {
        const course = await api('/courses', { method: 'POST', body: JSON.stringify({ course_name, code }) });
        event.target.reset();
        say('Course created. Share its join code with your students.');
        await loadCourses(course.course_id);
    } catch (error) { say(error.message, true); }
});

document.getElementById('logout').addEventListener('click', async () => {
    const response = await fetch('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
    if (response.ok) window.location.assign('/login');
    else say('Could not sign out.', true);
});

api('/auth/me').then(async me => {
    csrf = me.csrf;
    await loadCourses();
}).catch(error => say(`Could not load records: ${error.message}`, true));
