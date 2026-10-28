const state = document.getElementById('checkin-state');
const title = document.getElementById('checkin-title');
const message = document.getElementById('checkin-message');
const logout = document.getElementById('logout');

function show(result, heading, detail) {
    state.dataset.state = result;
    title.textContent = heading;
    message.textContent = detail;
}

async function currentUser() {
    const response = await fetch('/auth/me', { cache: 'no-store' });
    if (!response.ok) throw new Error('Sign-in expired. Please sign in and scan again.');
    return response.json();
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
