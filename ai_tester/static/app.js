const gpuBox = document.querySelector('#gpu');
const ollamaBox = document.querySelector('#ollama');
const providerSelect = document.querySelector('#provider');
const modelSelect = document.querySelector('#model');
const responseBox = document.querySelector('#response');
const openaiConfig = document.querySelector('#openai-config');
const openaiParameters = document.querySelector('#openai-parameters');
const openaiModelStatus = document.querySelector('#openai-model-status');
let ollamaModels = [];

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[character]);
}

function state(box, available, html, error) {
  box.className = `status ${available ? 'ok' : 'error'}`;
  box.innerHTML = available ? html : `<strong>Indisponible</strong><p>${escapeHtml(error || 'Aucune donnée')}</p>`;
}

function setModels(models, emptyLabel = 'Aucun modèle détecté') {
  modelSelect.replaceChildren();
  if (!models.length) {
    modelSelect.add(new Option(emptyLabel, ''));
    return;
  }
  models.forEach(name => modelSelect.add(new Option(name, name)));
}

function applyProvider() {
  const isOpenAI = providerSelect.value === 'openai';
  openaiConfig.hidden = !isOpenAI;
  openaiParameters.hidden = !isOpenAI;
  if (isOpenAI) {
    setModels([], 'Chargez les modèles OpenAI');
  } else {
    setModels(ollamaModels);
  }
}

async function refresh() {
  const response = await fetch('/api/status');
  const data = await response.json();
  const devices = data.gpu.devices || [];
  state(gpuBox, data.gpu.available,
    devices.length ? devices.map(g => `<div><strong>${escapeHtml(g.name)}</strong> [${escapeHtml(g.vendor || 'GPU')}:${escapeHtml(g.id)}] — ${escapeHtml(g.temperature_c ?? '?')} °C, charge ${escapeHtml(g.utilization_percent ?? '?')} %</div>`).join('') : 'Aucun GPU détecté',
    data.gpu.error);

  ollamaModels = (data.ollama.models || []).map(model => model.name);
  state(ollamaBox, data.ollama.available,
    ollamaModels.length ? ollamaModels.map(name => `<div><strong>${escapeHtml(name)}</strong></div>`).join('') : 'Serveur joignable, aucun modèle installé',
    data.ollama.error);
  if (providerSelect.value === 'ollama') setModels(ollamaModels);
}

async function postOpenAI(route, payload, allowConfirmation = true) {
  const response = await fetch(route, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  if (response.status === 403 && data.confirmation_required && allowConfirmation) {
    const addresses = (data.addresses || []).join(', ') || 'adresse inconnue';
    const approved = window.confirm(
      `Le domaine ${data.host} (${addresses}) n’est pas encore autorisé.\n\n` +
      'Voulez-vous l’ajouter durablement à la configuration des destinations autorisées ?'
    );
    if (!approved) throw new Error('Ajout du domaine refusé par l’utilisateur');
    const authorization = await fetch('/api/openai/allowed-hosts', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({host: data.host, confirmed: true})
    });
    const authorizationData = await authorization.json();
    if (!authorization.ok) {
      throw new Error(authorizationData.error || `HTTP ${authorization.status}`);
    }
    return postOpenAI(route, payload, false);
  }
  return {response, data};
}

async function loadOpenAIModels() {
  openaiModelStatus.textContent = 'Chargement…';
  setModels([], 'Chargement…');
  try {
    const {response, data} = await postOpenAI('/api/openai/models', {
      base_url: document.querySelector('#openai-base-url').value,
      api_key: document.querySelector('#openai-api-key').value
    });
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    setModels(data.models || [], 'Aucun modèle retourné');
    openaiModelStatus.textContent = `${(data.models || []).length} modèle(s) disponible(s).`;
  } catch (error) {
    setModels([], 'Échec du chargement');
    openaiModelStatus.textContent = `Erreur : ${error.message}`;
  }
}

providerSelect.addEventListener('change', applyProvider);
document.querySelector('#refresh').addEventListener('click', refresh);
document.querySelector('#load-openai-models').addEventListener('click', loadOpenAIModels);
document.querySelector('#prompt-form').addEventListener('submit', async event => {
  event.preventDefault();
  responseBox.textContent = 'Génération en cours…';
  const isOpenAI = providerSelect.value === 'openai';
  const route = isOpenAI ? '/api/openai/chat' : '/api/ollama/generate';
  const payload = {
    model: modelSelect.value,
    prompt: document.querySelector('#prompt').value
  };
  if (isOpenAI) {
    Object.assign(payload, {
      base_url: document.querySelector('#openai-base-url').value,
      api_key: document.querySelector('#openai-api-key').value,
      system_prompt: document.querySelector('#system-prompt').value,
      temperature: Number(document.querySelector('#temperature').value),
      top_p: Number(document.querySelector('#top-p').value),
      max_tokens: Number(document.querySelector('#max-tokens').value)
    });
  }
  try {
    const {response, data} = isOpenAI
      ? await postOpenAI(route, payload)
      : await (async () => {
          const result = await fetch(route, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
          });
          return {response: result, data: await result.json()};
        })();
    responseBox.textContent = response.ok ? data.response : `Erreur : ${data.error}`;
  } catch (error) {
    responseBox.textContent = `Erreur réseau : ${error.message}`;
  }
});

applyProvider();
refresh().catch(error => {
  gpuBox.textContent = `Erreur réseau : ${error}`;
  ollamaBox.textContent = `Erreur réseau : ${error}`;
});
