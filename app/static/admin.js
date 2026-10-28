const STORAGE_KEY = 'headcount.activeSession';
const POLL_INTERVAL_MS = 1000;

const form = document.getElementById('session-form');
const courseSelect = document.getElementById('course');
const reloadInput = document.getElementById('reload-time');
const startButton = document.getElementById('start');
const endButton = document.getElementById('end');
const details = document.getElementById('session-details');
const activeCourse = document.getElementById('active-course');
const activeReload = document.getElementById('active-reload');
const sessionId = document.getElementById('session-id');
const liveState = document.getElementById('live-state');
const stateLabel = document.getElementById('state-label');
const qr = document.getElementById('qr');
const placeholder = document.getElementById('qr-placeholder');
const status = document.getElementById('status');

let session = null;
let coursesLoaded = false;
let busy = false;
let pollTimer = null;
let pollGeneration = 0;

function setStatus(message, error = false) {
    status.textContent = message;
    status.dataset.error = String(error);
}

function setState(state, label) {
    liveState.dataset.state = state;
    stateLabel.textContent = label;
}

function showQr(dataUrl) {
    qr.src = dataUrl;
    qr.hidden = false;
    placeholder.hidden = true;
}

function hideQr() {
    qr.removeAttribute('src');
    qr.hidden = true;
    placeholder.hidden = false;
}

function renderSession() {
    const active = session !== null;
    details.hidden = !active;
    courseSelect.disabled = active || busy || !coursesLoaded;
    reloadInput.disabled = active || busy;
    startButton.disabled = active || busy || !coursesLoaded;
    endButton.disabled = !active || busy;
    if (active) {
        activeCourse.textContent = session.courseLabel;
        activeReload.textContent = `${session.reloadTime} seconds`;
        sessionId.textContent = session.id;
    }
}

async function api(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok || data.status === 'error') {
        const message = typeof data.detail === 'string' ? data.detail : data.message;
        throw new Error(message || `Request failed (${response.status})`);
    }
    return data;
}

function saveSession() {
    try {
        if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
        else localStorage.removeItem(STORAGE_KEY);
    } catch (_) {
        // Private browsing can disable storage; the current page still works.
    }
}

function stopPolling() {
    pollGeneration += 1;
    clearTimeout(pollTimer);
    pollTimer = null;
}

function closeSession(message) {
    stopPolling();
    session = null;
    saveSession();
    hideQr();
    setState('idle', 'Not started');
    setStatus(message);
    renderSession();
}

async function pollCurrent(generation) {
    if (!session || generation !== pollGeneration) return;
    const id = session.id;
    try {
        const data = await api(`/current?${new URLSearchParams({ session_id: id })}`);
        if (generation !== pollGeneration || !session || session.id !== id) return;
        if (!data.active) {
            closeSession('This attendance session is no longer active.');
            return;
        }
        showQr(data.qr);
        setState('live', 'Live now');
        setStatus(`QR code updates every ${session.reloadTime} seconds.`);
    } catch (error) {
        if (generation !== pollGeneration) return;
        hideQr();
        setState('error', 'Connection issue');
        setStatus(`Could not refresh the code: ${error.message}. Retrying…`, true);
    } finally {
        if (generation === pollGeneration && session) {
            pollTimer = setTimeout(() => pollCurrent(generation), POLL_INTERVAL_MS);
        }
    }
}

function startPolling() {
    stopPolling();
    pollCurrent(pollGeneration);
}

async function loadCourses() {
    try {
        const courses = await api('/courses');
        courseSelect.replaceChildren();
        if (!courses.length) {
            courseSelect.add(new Option('No courses available', ''));
            if (!session) setStatus('No courses found. Add a course before starting attendance.', true);
            return;
        }
        courseSelect.add(new Option('Select a course', ''));
        for (const course of courses) {
            courseSelect.add(new Option(`${course.code} · ${course.course_name}`, course.course_id));
        }
        coursesLoaded = true;
    } catch (error) {
        courseSelect.replaceChildren(new Option('Could not load courses', ''));
        if (!session) setStatus(`Could not load courses: ${error.message}. Reload the page to retry.`, true);
    } finally {
        renderSession();
    }
}

form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy || session || !form.reportValidity()) return;

    const courseId = courseSelect.value;
    const reloadTime = Number(reloadInput.value);
    const courseLabel = courseSelect.selectedOptions[0].textContent;
    if (!courseId || !Number.isInteger(reloadTime) || reloadTime < 1) return;

    busy = true;
    renderSession();
    setStatus('Starting attendance…');
    try {
        const params = new URLSearchParams({ course_id: courseId, reload_time: String(reloadTime) });
        const data = await api(`/session/start?${params}`, { method: 'POST' });
        session = { id: data.session_id, courseLabel, reloadTime: data.reload_time };
        saveSession();
        setState('live', 'Starting');
        setStatus('Fetching the live QR code…');
        startPolling();
    } catch (error) {
        setState('error', 'Start failed');
        setStatus(`Could not start attendance: ${error.message}`, true);
    } finally {
        busy = false;
        renderSession();
    }
});

endButton.addEventListener('click', async () => {
    if (busy || !session) return;
    busy = true;
    stopPolling();
    renderSession();
    setStatus('Ending attendance…');
    try {
        const params = new URLSearchParams({ session_id: session.id });
        await api(`/session/end?${params}`, { method: 'POST' });
        closeSession('Attendance ended. You can start another session.');
    } catch (error) {
        setState('error', 'End failed');
        setStatus(`Could not end attendance: ${error.message}`, true);
        startPolling();
    } finally {
        busy = false;
        renderSession();
    }
});

try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved && typeof saved.id === 'string' && typeof saved.courseLabel === 'string' && Number.isInteger(saved.reloadTime)) {
        session = saved;
        setState('live', 'Reconnecting');
        setStatus('Checking your saved session…');
        startPolling();
    }
} catch (_) {
    // Ignore invalid or unavailable browser storage.
}

renderSession();
loadCourses();
