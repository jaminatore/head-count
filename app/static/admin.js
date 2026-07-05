// Admin.js
// Description: Admin commands for running QR Code 

const img = document.getElementById('qr');
const status = document.getElementById('status');
const btn = document.getElementById('start');
let poll = null;
let endsAt = null;

btn.addEventListener('click', async () => {
    const res = await fetch('session/start', {method: 'POST'});
    const data = await res.json();
    endsAt = data.ends_at;
    btn.disabled = true;
    poll = setInterval(tick, 1000);
    tick();
});

async function tick() {
    const res = await fetch('/current');
    const data = await res.json();
    if (!data.active) {
        clearInterval(poll);
        img.style.display = 'none';
        status.textContent = 'Attendance closed';
        return;
    }
    img.src = data.qr;
    const remaining = Math.max(0, Math.ceil(endsAt - Date.now() / 1000));
    status.textContent = `${remaining}s remaining`;
}