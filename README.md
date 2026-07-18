# AI Tester

Tableau de bord web pour diagnostiquer les GPU AMD avec `rocm-smi` et NVIDIA avec `nvidia-smi`, vérifier un serveur Ollama et tester une API OpenAI-compatible.

> Ce projet est distinct de **SentinelleFonctionnelle**, dont le rôle est de générer des tests fonctionnels à l’aide d’un LLM.

## Fonctions disponibles

- diagnostic GPU AMD et NVIDIA : constructeur, modèle, charge, température et VRAM ;
- interrogation de `GET /api/tags` sur Ollama ;
- prompt de test via `POST /api/generate` ;
- configuration d’une API OpenAI ou compatible OpenAI depuis l’interface ;
- récupération et sélection des modèles exposés par `/v1/models` ;
- test de `/v1/chat/completions` avec instruction système, température, `top_p` et limite de tokens ;
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

Par défaut, AI Tester contacte Ollama sur la machine hôte depuis un conteneur Podman :

```text
http://host.containers.internal:11434
```

Le tableau de bord permet de sélectionner directement :

| Environnement | URL |
|---|---|
| Podman — hôte (défaut) | `http://host.containers.internal:11434` |
| Docker — hôte | `http://host.docker.internal:11434` |
| Réseau partagé | `http://ollama:11434` |
| Boucle locale | `http://127.0.0.1:11434` |
| Personnalisé | URL saisie dans l’interface |

Sous Docker Linux, le conteneur doit généralement être lancé avec :

```bash
--add-host=host.docker.internal:host-gateway
```

`OLLAMA_BASE_URL` permet également de remplacer le profil utilisé au démarrage :

```bash
OLLAMA_BASE_URL=http://ollama:11434 \
  uv run flask --app ai_tester.web run --host 0.0.0.0 --port 5000
```

Une destination personnalisée inconnue doit être confirmée avant d’être ajoutée durablement aux destinations autorisées. Les redirections HTTP Ollama sont désactivées et les réponses sont limitées à 10 Mio. Dans un conteneur, `127.0.0.1` désigne le conteneur lui-même et ne joint l’hôte que si le réseau de l’hôte est explicitement partagé.

Ollama doit écouter sur une adresse joignable depuis AI Tester. Vérifier la politique réseau et ne pas exposer son API sans protection sur Internet.

## Configuration OpenAI-compatible

Dans **Test d’inférence LLM**, sélectionner **OpenAI / API compatible OpenAI**, puis renseigner :

- l’URL de base, par exemple `https://api.openai.com/v1` ;
- la clé API, obligatoire pour OpenAI et facultative pour certaines API locales ;
- le modèle chargé depuis l’endpoint `/models` ;
- l’instruction système ;
- `temperature` entre 0 et 2 ;
- `top_p` entre 0 et 1 ;
- `max_tokens`, entier strictement positif.

La clé est transmise au backend uniquement pour la requête courante. AI Tester ne l’écrit pas sur disque et ne la renvoie pas au navigateur. Une instance partagée doit être placée derrière une authentification : la confirmation d’un domaine modifie une configuration serveur et doit donc rester réservée à un utilisateur de confiance.

### Destinations autorisées

La politique réseau est enregistrée dans `config/allowed_destinations.json`. Son emplacement peut être remplacé avec `AI_TESTER_ALLOWED_DESTINATIONS`. Le fichier contient deux listes :

```json
{
  "allowed_hosts": ["api.openai.com", "localhost"],
  "allowed_networks": [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7"
  ]
}
```

Les boucles locales, les réseaux privés IPv4 et les adresses IPv6 locales uniques sont donc autorisés par défaut. Les plages link-local, notamment `169.254.0.0/16` qui peut contenir un service de métadonnées cloud, ne le sont pas automatiquement.

Lorsqu’une URL utilise un autre domaine public, le backend renvoie une demande de confirmation avec le nom et les adresses résolues. L’interface demande alors une confirmation explicite. Si elle est acceptée, le nom normalisé est ajouté atomiquement à `allowed_hosts`, puis l’appel est retenté. Les jokers sont interdits et aucune clé API n’est écrite dans ce fichier.

Les redirections HTTP restent désactivées. Une clé API ne peut être envoyée qu’en HTTPS ; HTTP sans clé reste possible pour une API locale compatible. L’autorisation explicite d’un domaine signifie que l’administrateur lui fait confiance, y compris si sa résolution DNS change. Pour une instance exposée, compléter cette politique par un pare-feu de sortie ou une passerelle LLM.

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
- `POST /api/ollama/models` : modèles de l’URL sélectionnée, corps JSON `{"base_url":"..."}` ;
- `POST /api/ollama/generate` : corps JSON `{"base_url":"...", "model":"...", "prompt":"..."}` ;
- `POST /api/openai/models` : modèles d’une API OpenAI-compatible ;
- `POST /api/openai/chat` : test de complétion configurable ;
- `POST /api/destinations/allowed-hosts` : ajout persistant d’un domaine après confirmation explicite ;
- `POST /api/openai/allowed-hosts` : alias rétrocompatible de la route précédente.
