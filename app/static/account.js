document.getElementById('logout').addEventListener('click', async () => {
    const me = await fetch('/auth/me').then(response => response.json());
    const response = await fetch('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': me.csrf } });
    if (response.ok) window.location.assign('/login');
});
