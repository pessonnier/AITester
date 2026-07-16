# AI Tester

Tableau de bord web pour diagnostiquer les GPU AMD avec `rocm-smi` et NVIDIA avec `nvidia-smi`, vérifier un serveur Ollama, lister ses modèles et exécuter un prompt de contrôle.

> Ce projet est distinct de **SentinelleFonctionnelle**, dont le rôle est de générer des tests fonctionnels à l’aide d’un LLM.

## Fonctions disponibles

- diagnostic GPU AMD et NVIDIA : constructeur, modèle, charge, température et VRAM ;
- interrogation de `GET /api/tags` sur Ollama ;
- prompt de test via `POST /api/generate` ;
- erreurs indépendantes : Ollama peut être testé même si le GPU n’est pas visible, et inversement ;
- interface web responsive et API JSON.

## Démarrage local

Prérequis : Python 3.11+, [`uv`](https://docs.astral.sh/uv/), `rocm-smi` et éventuellement Ollama.

```bash
uv sync --group dev
uv run flask --app ai_tester.web run --host 0.0.0.0 --port 5000
```

Ouvrir <http://localhost:5000>.

## Configuration Ollama

L’URL est configurable par variable d’environnement :

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
  uv run flask --app ai_tester.web run --host 0.0.0.0 --port 5000
```

Dans un conteneur Linux, `127.0.0.1` désigne le conteneur, pas l’hôte. Utiliser l’adresse de l’hôte ou un nom de service Docker, par exemple :

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Sous Linux, ajouter si nécessaire :

```bash
--add-host=host.docker.internal:host-gateway
```

Ollama doit écouter sur une adresse joignable depuis AI Tester. Vérifier la politique réseau et ne pas exposer son API sans protection sur Internet.

## Accès GPU AMD depuis un conteneur

AI Tester exécute exclusivement `rocm-smi`. Le binaire et les périphériques ROCm doivent être visibles dans le conteneur. Exemple indicatif :

```bash
docker run --device=/dev/kfd --device=/dev/dri \
  --group-add video --group-add render \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  --add-host=host.docker.internal:host-gateway \
  -p 5000:5000 ai-tester
```

Le montage exact dépend de l’image ROCm, des groupes et des permissions de l’hôte.

## Accès GPU NVIDIA depuis un conteneur

AI Tester interroge les cartes NVIDIA avec `nvidia-smi`. Le NVIDIA Container Toolkit doit être configuré sur l’hôte, puis les GPU exposés au conteneur, par exemple avec :

```bash
docker run --gpus all -p 5000:5000 ai-tester
```

L’absence d’un constructeur n’empêche pas le diagnostic de l’autre : une machine AMD n’a pas besoin de `nvidia-smi`, et inversement.

## Tests

```bash
uv run --group dev pytest
```

## API

- `GET /` : tableau de bord ;
- `GET /api/status` : état GPU et Ollama ;
- `POST /api/ollama/generate` : corps JSON `{"model":"...", "prompt":"..."}`.
