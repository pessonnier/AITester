const gpuBox = document.querySelector('#gpu');
const ollamaBox = document.querySelector('#ollama');
const modelSelect = document.querySelector('#model');
const responseBox = document.querySelector('#response');

function state(box, available, html, error) {
  box.className = `status ${available ? 'ok' : 'error'}`;
  box.innerHTML = available ? html : `<strong>Indisponible</strong><p>${error || 'Aucune donnée'}</p>`;
}

async function refresh() {
  const response = await fetch('/api/status');
  const data = await response.json();
  const devices = data.gpu.devices || [];
  state(gpuBox, data.gpu.available,
    devices.length ? devices.map(g => `<div><strong>${g.name}</strong> (${g.id}) — ${g.temperature_c ?? '?'} °C, charge ${g.utilization_percent ?? '?'} %</div>`).join('') : 'Aucun GPU détecté',
    data.gpu.error);

  const models = data.ollama.models || [];
  state(ollamaBox, data.ollama.available,
    models.length ? models.map(m => `<div><strong>${m.name}</strong></div>`).join('') : 'Serveur joignable, aucun modèle installé',
    data.ollama.error);
  modelSelect.innerHTML = models.length
    ? models.map(m => `<option value="${m.name}">${m.name}</option>`).join('')
    : '<option value="">Aucun modèle détecté</option>';
}

document.querySelector('#refresh').addEventListener('click', refresh);
document.querySelector('#prompt-form').addEventListener('submit', async event => {
  event.preventDefault();
  responseBox.textContent = 'Génération en cours…';
  const response = await fetch('/api/ollama/generate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model: modelSelect.value, prompt: document.querySelector('#prompt').value})
  });
  const data = await response.json();
  responseBox.textContent = data.response || `Erreur : ${data.error}`;
});

refresh().catch(error => {
  gpuBox.textContent = `Erreur réseau : ${error}`;
  ollamaBox.textContent = `Erreur réseau : ${error}`;
});
