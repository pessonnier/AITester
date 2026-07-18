const gpuBox = document.querySelector('#gpu');
const ollamaBox = document.querySelector('#ollama');
const providerSelect = document.querySelector('#provider');
const modelSelect = document.querySelector('#model');
const responseBox = document.querySelector('#response');
const ollamaConfig = document.querySelector('#ollama-config');
const ollamaEndpointPreset = document.querySelector('#ollama-endpoint-preset');
const ollamaBaseUrl = document.querySelector('#ollama-base-url');
const ollamaModelStatus = document.querySelector('#ollama-model-status');
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
  ollamaConfig.hidden = isOpenAI;
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

  await loadOllamaModels();
}

async function postDestination(route, payload, allowConfirmation = true) {
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
    const authorization = await fetch('/api/destinations/allowed-hosts', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({host: data.host, confirmed: true})
    });
    const authorizationData = await authorization.json();
    if (!authorization.ok) {
      throw new Error(authorizationData.error || `HTTP ${authorization.status}`);
    }
    return postDestination(route, payload, false);
  }
  return {response, data};
}

async function loadOllamaModels() {
  ollamaModelStatus.textContent = 'Chargement…';
  if (providerSelect.value === 'ollama') setModels([], 'Chargement…');
  try {
    const {response, data} = await postDestination('/api/ollama/models', {
      base_url: ollamaBaseUrl.value
    });
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    ollamaModels = (data.models || []).map(model => model.name);
    if (providerSelect.value === 'ollama') {
      setModels(ollamaModels, 'Aucun modèle retourné');
    }
    state(ollamaBox, true,
      ollamaModels.length ? ollamaModels.map(name => `<div><strong>${escapeHtml(name)}</strong></div>`).join('') : 'Serveur joignable, aucun modèle installé');
    ollamaModelStatus.textContent = `${ollamaModels.length} modèle(s) disponible(s).`;
  } catch (error) {
    if (providerSelect.value === 'ollama') setModels([], 'Échec du chargement');
    state(ollamaBox, false, '', error.message);
    ollamaModelStatus.textContent = `Erreur : ${error.message}`;
  }
}

async function loadOpenAIModels() {
  openaiModelStatus.textContent = 'Chargement…';
  setModels([], 'Chargement…');
  try {
    const {response, data} = await postDestination('/api/openai/models', {
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
ollamaEndpointPreset.addEventListener('change', () => {
  const custom = ollamaEndpointPreset.value === 'custom';
  ollamaBaseUrl.readOnly = !custom;
  if (!custom) ollamaBaseUrl.value = ollamaEndpointPreset.value;
  if (providerSelect.value === 'ollama') loadOllamaModels();
});
document.querySelector('#refresh').addEventListener('click', refresh);
document.querySelector('#load-ollama-models').addEventListener('click', loadOllamaModels);
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
  } else {
    payload.base_url = ollamaBaseUrl.value;
  }
  try {
    const {response, data} = await postDestination(route, payload);
    responseBox.textContent = response.ok ? data.response : `Erreur : ${data.error}`;
  } catch (error) {
    responseBox.textContent = `Erreur réseau : ${error.message}`;
  }
});

applyProvider();
ollamaBaseUrl.readOnly = ollamaEndpointPreset.value !== 'custom';
refresh().catch(error => {
  gpuBox.textContent = `Erreur réseau : ${error}`;
  ollamaBox.textContent = `Erreur réseau : ${error}`;
});
