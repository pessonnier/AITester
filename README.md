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

Prérequis : machine **x86_64**, Git, `tar`, `sha256sum` et Podman ou Docker avec un accès Internet permettant de récupérer l’image ROCm et les dépendances.

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

Pour imposer la référence de l’image produite ou une base ROCm déjà approuvée par l’organisation :

```bash
IMAGE_REF=registry.interne/ai-tester:0.1.0 \
GPU_BASE_IMAGE=registry.interne/rocm/dev-ubuntu-24.04:7.2.4@sha256:<digest-approuvé> \
CONTAINER_RUNTIME=podman \
./deploy/airgap/build-bundle.sh
```

`GPU_BASE_IMAGE` doit obligatoirement être épinglée par digest SHA-256 et fournir Python 3, `pip`, `useradd`, `/usr/sbin/nologin` et un `/opt/rocm/bin/rocm-smi` exécutable — ce dernier point est vérifié pendant le build. La base officielle par défaut fournit ROCm 7.2.4 via `rocm/dev-ubuntu-24.04:7.2.4`, épinglée par digest. Une base personnalisée relève de l’organisation et doit être qualifiée avec la version du pilote hôte. Le manifeste enregistre la référence de base, l’identifiant de l’image construite, le commit source, l’architecture inspectée et le hash du verrou de dépendances.

#### Intégrité, authenticité et conservation des preuves

Le fichier `.sha256` protège l’intégrité de l’archive externe pendant le transfert. Après extraction, `SHA256SUMS` protège l’image, le manifeste, l’installateur et le verrou de dépendances avant leur utilisation. Un checksum reçu avec l’archive détecte une corruption, mais **ne prouve pas son authenticité** face à un attaquant capable de remplacer simultanément l’archive et son checksum.

Pour une livraison contrôlée :

- construire depuis un commit Git revu et signé, avec une arborescence propre ;
- conserver ensemble le bundle, le fichier `.sha256`, le commit source et le journal de construction ;
- publier le checksum par un canal de confiance distinct ou signer l’archive avec le mécanisme approuvé par l’organisation ;
- vérifier la signature ou comparer le checksum approuvé **avant** toute extraction dans la zone isolée ;
- archiver aussi le bundle précédemment qualifié pour permettre un retour arrière.

`ALLOW_DIRTY=1` et `ALLOW_UNVERSIONED=1` sont des dérogations de développement. Un bundle produit avec l’une de ces options ne doit pas être promu en production sans procédure d’acceptation explicite.

### 2. Transférer et installer dans la zone isolée

Prérequis sur la cible : Linux x86_64, Bash, `tar`, `sha256sum` et Podman ou Docker déjà installés. Python, `uv` et un registre de conteneurs ne sont pas nécessaires sur la cible. Les pilotes GPU et, pour NVIDIA, le NVIDIA Container Toolkit doivent être préinstallés hors ligne sur l’hôte.

Copier le bundle et son fichier `.sha256` par le canal autorisé. Si le modèle de menace l’exige, transmettre ou publier le checksum par un canal de confiance distinct. Sur la machine air-gapped, vérifier le bundle **avant extraction** :

```bash
sha256sum -c ai-tester-airgap-0.1.0-x86_64.tar.gz.sha256
tar -xzf ai-tester-airgap-0.1.0-x86_64.tar.gz
cd ai-tester-airgap
sha256sum -c SHA256SUMS
cat MANIFEST
./install.sh
```

La première vérification porte sur l’archive reçue ; la seconde contrôle chaque composant extrait. Examiner ensuite `MANIFEST` et comparer au dossier de livraison approuvé au minimum `SOURCE_COMMIT`, `SOURCE_DIRTY`, `GPU_BASE_IMAGE`, `LOCK_SHA256`, `IMAGE_ID` et `ARCH`. Ne jamais exécuter `source MANIFEST` : ce fichier est une donnée de provenance, pas un script shell. L’installateur répète la vérification interne et valide les champs qu’il consomme.

L’installateur :

1. vérifie **avant chargement** tous les fichiers avec `SHA256SUMS` et refuse une architecture différente de la cible ;
2. détecte Podman ou Docker et valide les prérequis GPU explicitement demandés ;
3. charge l’archive locale avec `--pull=never`, puis compare l’identifiant de l’image chargée à celui du manifeste ;
4. effectue un `create` de prévalidation avec les options GPU et de durcissement, sans arrêter le service existant ;
5. crée ou réutilise le volume persistant `ai-tester-data` pour la politique des destinations ;
6. remplace l’ancien conteneur uniquement après cette prévalidation, puis démarre AI Tester avec les capacités supprimées, `no-new-privileges` et une racine en lecture seule ;
7. vérifie son état de disponibilité.

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

### Vérifications après installation

Conserver dans le dossier d’intervention le moteur, le mode GPU, l’URL Ollama, l’adresse d’écoute, le port et le nom de conteneur utilisés. Vérifier ensuite le service depuis l’hôte :

```bash
RUNTIME=podman                  # ou docker
NAME=ai-tester                  # valeur passée à --name
PORT=5000                       # valeur passée à --port
BIND_ADDRESS=127.0.0.1          # valeur passée à --bind-address

$RUNTIME ps --filter "name=${NAME}"
$RUNTIME exec "$NAME" python3 -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3).read(1)"
$RUNTIME logs --tail 50 "$NAME"
```

Si `curl` est disponible sur l’hôte, vérifier aussi l’adresse réellement publiée :

```bash
CHECK_ADDRESS=$BIND_ADDRESS      # utiliser une adresse concrète de l’hôte si 0.0.0.0
curl --fail --show-error "http://${CHECK_ADDRESS}:${PORT}/"
```

Contrôler les options de moindre privilège appliquées au conteneur :

```bash
$RUNTIME inspect --format \
  'read_only={{.HostConfig.ReadonlyRootfs}} privileged={{.HostConfig.Privileged}} cap_drop={{json .HostConfig.CapDrop}} security_opt={{json .HostConfig.SecurityOpt}}' \
  "$NAME"
$RUNTIME volume inspect ai-tester-data
```

Le résultat attendu comprend `read_only=true`, `privileged=false`, `ALL` dans `cap_drop` et `no-new-privileges` dans `security_opt`. Vérifier également que le port reste lié à `127.0.0.1`, sauf exposition explicitement approuvée derrière un reverse proxy authentifiant et TLS. Pour un mode GPU, exécuter ensuite la commande matérielle correspondant au fournisseur comme indiqué plus bas ; un état HTTP sain ne valide pas à lui seul l’accès au GPU.

### Retour arrière contrôlé

La prévalidation protège le conteneur existant pendant le contrôle des options communes, GPU et de durcissement. Concrètement, le `create` de prévalidation transmet uniquement les tableaux `COMMON_ARGS` et `GPU_ARGS` du script. Elle **ne prévalide ni le nom définitif ni la publication du port**, qui ne sont appliqués qu’après suppression du conteneur à remplacer. Vérifier donc auparavant que le nom et le port choisis sont disponibles. Après suppression de l’ancien conteneur, l’installateur **n’effectue pas de retour arrière automatique** si la création, le démarrage ou le contrôle de disponibilité du nouveau conteneur échoue.

Avant une mise à niveau, conserver le bundle précédent avec son checksum, son manifeste et les options exactes d’installation. Pour revenir à la version qualifiée précédente :

```bash
NAME=ai-tester                  # reprendre la valeur enregistrée
PORT=5000                       # reprendre la valeur enregistrée
BIND_ADDRESS=127.0.0.1          # reprendre la valeur enregistrée
GPU_MODE=none                   # reprendre none, auto, amd, nvidia ou all

# Paire par défaut pour Podman :
RUNTIME=podman
OLLAMA_URL=http://host.containers.internal:11434

# Paire par défaut pour Docker (décommenter ensemble si Docker était utilisé) :
# RUNTIME=docker
# OLLAMA_URL=http://host.docker.internal:11434

cd /chemin/vers/le-bundle-precedent/ai-tester-airgap
sha256sum -c SHA256SUMS
./install.sh \
  --runtime "$RUNTIME" \
  --name "$NAME" \
  --port "$PORT" \
  --bind-address "$BIND_ADDRESS" \
  --ollama-url "$OLLAMA_URL" \
  --gpu "$GPU_MODE" \
  --replace
```

Réutiliser le même `--name`, `--port`, `--bind-address`, `--ollama-url` et mode `--gpu` que lors de l’installation précédente. Le volume nommé `ai-tester-data` est conservé et réutilisé ; ne pas le supprimer pendant le retour arrière. L’archive précédente est rechargée, puis son `IMAGE_ID` est comparé à son manifeste avant remplacement. Réexécuter enfin toutes les vérifications post-installation. Si une évolution de format des données persistantes est introduite ultérieurement, elle devra fournir une procédure de sauvegarde et de restauration distincte avant déploiement.

L’image GPU est distribuée uniquement pour **x86_64/amd64**, car la base ROCm officielle utilisée n’est pas multi-architecture. Il faut produire et qualifier une autre image de base avant tout support ARM64.

### Accès GPU AMD

L’image contient réellement ROCm 7.2.4 et `rocm-smi`. Le pilote noyau AMD reste obligatoirement sur l’hôte : un conteneur partage le noyau de celui-ci et ne doit pas embarquer `amdgpu-dkms`.

Référence officielle : [exécution de conteneurs ROCm](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/how-to/docker.html). Consulter et archiver cette documentation depuis la machine connectée avant l’intervention en zone isolée.

Prérequis sur l’hôte isolé :

- GPU pris en charge et pilote `amdgpu` opérationnel ;
- périphériques `/dev/kfd` et `/dev/dri` présents ;
- compte qui lance Podman membre des groupes donnant accès à ces périphériques, généralement `video` et `render` ;
- paquets pilotes/ROCm hôtes préparés et installés hors ligne avant le transfert d’AI Tester.

Vérifier les droits de l’hôte :

```bash
ls -l /dev/kfd /dev/dri/renderD*
id
```

Démarrage AMD avec Podman, chemin recommandé :

```bash
./install.sh --runtime podman --gpu amd
podman exec ai-tester rocm-smi
```

L’installateur ajoute de façon ciblée :

```text
--device=/dev/kfd
--device=/dev/dri
--group-add=keep-groups
```

`keep-groups` conserve les groupes supplémentaires de l’utilisateur hôte avec Podman rootless ; il nécessite un runtime OCI compatible, généralement `crun`. Sur un hôte SELinux en mode enforcing, `setsebool -P container_use_devices true` est parfois nécessaire, mais cette bascule autorise globalement l’accès des domaines conteneurs aux périphériques : elle doit être approuvée selon la politique de sécurité locale. Ne pas contourner SELinux avec `--privileged`.

Démarrage AMD avec Docker :

```bash
./install.sh --runtime docker --gpu amd
docker exec ai-tester rocm-smi
```

Pour Docker, l’installateur transmet `/dev/kfd` et `/dev/dri`, puis ajoute automatiquement les GID numériques propriétaires de `/dev/kfd` et des nœuds de périphérique DRI. Cela évite de supposer que les noms ou numéros des groupes `video` et `render` sont identiques dans l’image et sur l’hôte. Pour Podman comme Docker, l’installation refuse un périphérique appartenant au GID 0 ou dépourvu des bits de groupe lecture/écriture : corriger alors les règles `udev` ou les groupes de l’hôte plutôt que d’élargir les privilèges du conteneur.

L’option `--privileged` n’est ni utilisée ni recommandée. L’option `seccomp=unconfined`, parfois indiquée pour certains workloads ROCm/HPC, n’est pas nécessaire au simple diagnostic `rocm-smi` et affaiblirait le durcissement par défaut.

### Accès GPU NVIDIA

L’image contient la commande relais `nvidia-smi`, mais **pas une copie figée du binaire du pilote NVIDIA**. NVIDIA Container Toolkit injecte au démarrage le vrai `/usr/bin/nvidia-smi`, les bibliothèques et les périphériques correspondant exactement au pilote installé sur l’hôte. Cette méthode évite les incompatibilités entre un utilitaire embarqué et le pilote noyau.

Référence officielle : [prise en charge CDI de NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html). Les paquets, leur intégrité et une copie de la procédure doivent être préparés sur la machine connectée ; ils ne font pas partie du bundle AI Tester.

Prérequis sur l’hôte isolé :

- pilote NVIDIA opérationnel et `nvidia-smi` fonctionnel sur l’hôte ;
- NVIDIA Container Toolkit préinstallé avec ses paquets hors ligne ;
- pour Podman, spécification CDI générée et visible par le moteur.

Contrôles préalables :

```bash
nvidia-smi
nvidia-ctk cdi list       # requis pour le chemin CDI Podman
```

Avec NVIDIA Container Toolkit 1.18 ou plus récent, `nvidia-cdi-refresh` génère normalement `/var/run/cdi/nvidia.yaml` après installation du toolkit, mise à jour du pilote ou redémarrage.

Démarrage NVIDIA avec Podman/CDI :

```bash
./install.sh --runtime podman --gpu nvidia
podman exec ai-tester nvidia-smi
```

L’installateur ajoute :

```text
--device=nvidia.com/gpu=all
NVIDIA_DRIVER_CAPABILITIES=utility
```

Démarrage NVIDIA avec Docker :

```bash
./install.sh --runtime docker --gpu nvidia
docker exec ai-tester nvidia-smi
```

L’installateur ajoute `--gpus=all` et la capacité NVIDIA `utility`. Docker doit avoir été configuré pour NVIDIA Container Toolkit avant le passage en zone isolée. Avant tout chargement ou remplacement, l’installateur vérifie que Docker annonce bien le runtime `nvidia`.

### Sélection automatique et hôtes hybrides

Par moindre privilège, le mode par défaut est `--gpu none` : aucun périphérique GPU n’est accordé sans choix explicite. Le mode `--gpu auto` active AMD lorsque `/dev/kfd` et `/dev/dri` existent et sont exploitables, puis NVIDIA lorsque `nvidia-smi -L` et l’intégration du runtime fonctionnent. Les choix sont :

```bash
./install.sh --gpu none       # aucun périphérique GPU
./install.sh --gpu auto       # détecter et activer les GPU exploitables
./install.sh --gpu amd        # AMD uniquement
./install.sh --gpu nvidia     # NVIDIA uniquement
./install.sh --gpu all        # AMD et NVIDIA sur un hôte hybride
```

Un choix explicite échoue avant le chargement ou le remplacement du conteneur si les périphériques AMD ou `nvidia-smi` sont absents de l’hôte. Les protections existantes restent actives : utilisateur non-root, capacités supprimées, `no-new-privileges`, racine en lecture seule et absence de `--privileged`.

La présence d’une commande dans le conteneur ne prouve pas à elle seule que le GPU est accessible. La validation finale doit exécuter `rocm-smi` ou `nvidia-smi` avec `podman exec`/`docker exec` sur un hôte réellement équipé. Le bundle AI Tester contient l’espace utilisateur ROCm, mais n’installe jamais les pilotes noyau ni NVIDIA Container Toolkit sur la cible.

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
