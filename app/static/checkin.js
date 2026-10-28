const state = document.getElementById('checkin-state');
const title = document.getElementById('checkin-title');
const message = document.getElementById('checkin-message');
const logout = document.getElementById('logout');
const joinForm = document.getElementById('join-form');
const joinCode = document.getElementById('student-join-code');
const courseList = document.getElementById('student-course-list');
let csrf = '';

function show(result, heading, detail) {
    state.dataset.state = result;
    title.textContent = heading;
    message.textContent = detail;
}

async function currentUser() {
    const response = await fetch('/auth/me', { cache: 'no-store' });
    if (!response.ok) throw new Error('Sign-in expired. Please sign in and scan again.');
    const me = await response.json();
    csrf = me.csrf;
    return me;
}

async function loadCourses() {
    const response = await fetch('/my-courses');
    if (!response.ok) return;
    const courses = await response.json();
    courseList.replaceChildren();
    for (const course of courses) {
        const item = document.createElement('p');
        item.className = 'student-course';
        item.textContent = `${course.code} · ${course.course_name} — ${course.status}`;
        courseList.append(item);
    }
}

const code = new URLSearchParams(window.location.hash.slice(1));
const session = code.get('session');
const token = code.get('token');
history.replaceState(null, '', window.location.pathname);

if (session && token) {
    show('loading', 'Checking you in…', 'Verifying the live code and your enrollment.');
    currentUser().then(async (me) => {
        const response = await fetch('/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': me.csrf },
            body: JSON.stringify({ session, token }),
        });
        if (!response.ok) throw new Error('Check-in is unavailable. Please try again.');
        const data = await response.json();
        if (data.valid) show('success', 'You’re checked in', 'Your attendance has been recorded.');
        else if (data.result === 'duplicate') show('success', 'Already checked in', 'Your attendance was recorded earlier in this session.');
        else show('error', 'Could not check in', `${data.message}. Scan the current classroom code or ask your instructor for help.`);
    }).catch((error) => show('error', 'Could not check in', error.message));
}

currentUser().then(loadCourses).catch(() => {});

joinForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
        if (!csrf) await currentUser();
        const response = await fetch('/join', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
            body: JSON.stringify({ join_code: joinCode.value.trim() }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not request to join.');
        show('ready', 'Join request sent', `${data.course_name}: ${data.status}. Your instructor must approve you before check-in.`);
        joinForm.reset();
        await loadCourses();
    } catch (error) { show('error', 'Could not join course', error.message); }
});

logout.addEventListener('click', async () => {
    try {
        const me = await currentUser();
        const response = await fetch('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': me.csrf } });
        if (!response.ok) throw new Error('Sign-out failed. Please try again.');
        window.location.assign('/login');
    } catch (error) {
        show('error', 'Could not sign out', error.message);
    }
});
