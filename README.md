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
  "allowed_hosts": [
    "api.openai.com",
    "host.containers.internal",
    "host.docker.internal",
    "localhost",
    "ollama"
  ],
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

## Déploiement air-gapped

Le chemin recommandé consiste à construire un bundle sur une machine connectée ayant la **même architecture CPU** que la cible, puis à transférer ce bundle et son checksum dans la zone isolée. Le bundle contient l’image AI Tester, des dépendances Python verrouillées avec leurs hashes, l’installateur hors ligne, un manifeste de provenance et `SHA256SUMS`.

### 1. Construire le bundle sur une machine connectée

Prérequis : Git, `tar`, `sha256sum` et Podman ou Docker avec un accès Internet permettant de récupérer l’image Python et les dépendances.

```bash
git clone https://github.com/pessonnier/AITester.git
cd AITester
CONTAINER_RUNTIME=podman ./deploy/airgap/build-bundle.sh
```

Avec Docker :

```bash
CONTAINER_RUNTIME=docker ./deploy/airgap/build-bundle.sh
```

Le résultat est créé sous une forme comparable à :

```text
dist/ai-tester-airgap-0.1.0-x86_64.tar.gz
```

Le constructeur exige un dépôt Git et refuse par défaut une arborescence modifiée. `ALLOW_DIRTY=1` permet un bundle de développement, marqué comme tel dans le manifeste, mais n’est pas recommandé pour une livraison contrôlée. La dérogation `ALLOW_UNVERSIONED=1` existe pour une archive source sans métadonnées Git, au prix d’une provenance incomplète.

Pour imposer la référence de l’image ou une image Python déjà approuvée par l’organisation :

```bash
IMAGE_REF=registry.interne/ai-tester:0.1.0 \
PYTHON_IMAGE=registry.interne/python:3.13.5-slim-bookworm@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419 \
CONTAINER_RUNTIME=podman \
./deploy/airgap/build-bundle.sh
```

`PYTHON_IMAGE` doit obligatoirement être épinglée par digest SHA-256. Elle doit rester compatible avec l’image Debian Python prévue par le `Containerfile` et fournir Python, `pip`, `useradd` et `/usr/sbin/nologin`. Le manifeste enregistre la référence de base, le commit source, l’architecture et le hash du verrou de dépendances.

### 2. Transférer et installer dans la zone isolée

Prérequis sur la cible : Linux, Bash, `tar`, `sha256sum` et Podman ou Docker déjà installés. Python, `uv` et un registre de conteneurs ne sont pas nécessaires sur la cible.

Copier le bundle et son fichier `.sha256` par le canal autorisé. Si le modèle de menace l’exige, transmettre ou publier le checksum par un canal de confiance distinct. Sur la machine air-gapped, vérifier le bundle **avant extraction** :

```bash
sha256sum -c ai-tester-airgap-0.1.0-x86_64.tar.gz.sha256
tar -xzf ai-tester-airgap-0.1.0-x86_64.tar.gz
cd ai-tester-airgap
./install.sh
```

L’installateur :

1. vérifie **avant chargement** tous les fichiers avec `SHA256SUMS` ;
2. détecte Podman ou Docker ;
3. charge l’archive d’image locale sans téléchargement ;
4. crée le volume persistant `ai-tester-data` pour la politique des destinations ;
5. démarre AI Tester avec les capacités supprimées, `no-new-privileges` et un système de fichiers racine en lecture seule ;
6. vérifie son état de disponibilité.

Une fois le bundle transféré, aucun accès Internet ni registre de conteneurs n’est nécessaire et `--pull=never` interdit tout téléchargement implicite. Podman utilise par défaut `http://host.containers.internal:11434` et Docker `http://host.docker.internal:11434` avec l’entrée `host-gateway`.

Par sécurité, le port est publié uniquement sur `127.0.0.1`. AI Tester ne fournit pas d’authentification intégrée. Pour une exposition réseau, utiliser explicitement `--bind-address` et placer impérativement un reverse proxy authentifiant et TLS devant l’application.

Options utiles :

```bash
# Choisir explicitement le moteur et le port
./install.sh --runtime podman --port 8080

# Exposition réseau explicite — uniquement derrière un proxy authentifiant
./install.sh --bind-address 0.0.0.0

# Utiliser une autre instance Ollama (nom DNS ou adresse IPv4)
./install.sh --ollama-url http://ollama.infra.local:11434

# Charger l’image sans démarrer AI Tester
./install.sh --no-start

# Remplacer explicitement un conteneur existant de même nom
./install.sh --replace
```

Sans `--replace`, l’installateur refuse de supprimer un conteneur existant. Conserver le bundle précédent pour un retour arrière ; un remplacement provoque une brève interruption de service.

Pour reproduire le transfert sur une architecture différente, construire un bundle distinct sur cette architecture ou avec une chaîne de construction multi-architecture validée. Ne pas réutiliser aveuglément une archive `x86_64` sur une cible ARM64.

L’image générique assure le tableau de bord et les tests Ollama/OpenAI. Pour les diagnostics GPU, le moteur de conteneurs et l’image doivent également exposer les périphériques, bibliothèques et commandes correspondantes : exclusivement `rocm-smi` pour AMD, ou `nvidia-smi` pour NVIDIA. Ces composants doivent eux-mêmes être prépositionnés dans l’environnement isolé ; l’installateur ne les télécharge pas.

## Accès GPU AMD depuis un conteneur

AI Tester exécute exclusivement `rocm-smi`. Le binaire et les périphériques ROCm doivent être visibles dans le conteneur. Exemple indicatif :

```bash
docker run --device=/dev/kfd --device=/dev/dri \
  --group-add video --group-add render \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  --add-host=host.docker.internal:host-gateway \
  -p 127.0.0.1:5000:5000 ai-tester
```

Le montage exact dépend de l’image ROCm, des groupes et des permissions de l’hôte.

## Accès GPU NVIDIA depuis un conteneur

AI Tester interroge les cartes NVIDIA avec `nvidia-smi`. Le NVIDIA Container Toolkit doit être configuré sur l’hôte, puis les GPU exposés au conteneur, par exemple avec :

```bash
docker run --gpus all -p 127.0.0.1:5000:5000 ai-tester
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
