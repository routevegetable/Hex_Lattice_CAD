// v3: effects down the left, whatever they hold on the right.

const get = (p) => fetch(p).then(r => r.json());

async function drawStats() {
  const s = await get('/stats');
  document.getElementById('fps').textContent = `${s.fps.toFixed(0)} fps`;
}

drawStats();
setInterval(drawStats, 1000);
