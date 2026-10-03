# Clone, check capacity, then bootstrap the chosen components

You can start with one service. The executable entrypoint is `scripts/bootstrap-stack.sh`; it clones only the selected public repositories into an explicit reader workspace, runs the read-only network/capacity gate, creates protected saved plans, and applies only when you explicitly select `provision` or `deploy`. It does not install every example or require a GPU. For the GitLab path, use it to make GitLab healthy locally before asking that instance to host deployment CI. For the GitHub path, private Actions can own later automation directly; installing GitLab is optional unless GitLab itself is the service you chose to learn.

## Prepare networking before any CI or VM apply

| Prerequisite | Check and purpose |
|---|---|
| Proxmox administrative path | Workstation/bootstrap host resolves the API hostname and reaches its HTTPS port (usually 8006); trusted CA verification stays enabled. |
| Guest addressing | Select unused VM IDs and reserved static IPv4 addresses, an existing node bridge/VLAN, matching subnet gateway and independent bootstrap DNS servers. The preflight validates IDs, bridge existence and address/gateway relationship; it does not prove an IP is unoccupied on your LAN. |
| Bootstrap DNS | Every chosen service hostname must already resolve to its planned static guest address from the bootstrap host. Use the existing router/resolver or independently managed authoritative records. Do not rely on the new GitLab or DNS VM to resolve its own first bootstrap. |
| Guest management route | After provisioning, the bootstrap host must reach guest TCP22 and independently verify host fingerprints. A successful TCP probe is not host authentication. |
| Service paths | Verify HTTPS/service ports, firewall and VLAN routing for the actual service after deployment; API/SSH reachability does not prove clients can use it. |
| Time and recovery | Keep working DNS, clock/NTP and trusted console/SSH access outside the services being created. |

These scripts cannot configure arbitrary switches, routers, DHCP reservations, storage firmware or GPU passthrough for you. Keep those settings in their owning IaC repository and complete them before this bootstrap. TEST-NET addresses and `.test` DNS names in the samples are deliberately generic; edit them to your own unused network and pre-created DNS records.

## Select a profile that fits your machine

| Sample | Components selected | Declared VM budget, before host reserves |
|---|---|---|
| `configs/gitlab-starter.example.json` | GitLab only | 4 vCPU, 8192 MiB RAM, 80 GiB cloned disks |
| `configs/optional-foundation.example.json` | GitLab, Vault, authoritative DNS, recursor, PostgreSQL | 12 vCPU, 18432 MiB RAM, 400 GiB cloned disks |

The sample file names are listed by `ls configs/`; use the optional foundation filename actually present in your checkout if renamed. These are the actual declarations in the sample profiles, not a promise that every workload fits those resources. Existing template disks must match `disk_gib`: the Terraform examples full-clone the template and do not resize disks. Resize a separately reviewed template before templating when the service needs more disk; never modify an in-use template blindly. Different disk budgets normally need corresponding prepared templates.

Preflight keeps 2048 MiB host RAM and 20 GiB selected-storage reserve by default, plus one logical CPU for the host. It compares running QEMU/LXC configured RAM against actual host usage using the larger reservation, adds selected allocations or positive deltas, and checks explicit vCPU oversubscription policy (`cpu_overcommit_ratio`, default 1.0). Configure `reserve_cpu_cores` if a different host reserve is justified. A 4-core machine cannot fit the 4-vCPU GitLab example at ratio 1.0 with a one-core host reserve; choose a smaller supported service configuration or an explicitly reviewed overcommit policy. Raising a ratio creates no extra CPU throughput. For a small machine, use `--component gitlab` or select only the roles you actually need rather than deploying the optional profile wholesale.

Selected existing matching VMs are accounted for instead of charging their full disk/RAM twice. Refresh requires that VM to exist and refuses CPU/RAM allocation increases; use allocation mode to evaluate an intentional increase. Missing capacity fields, incompatible storage, cluster-wide VM-ID conflicts or unaccountable disk sizes fail closed. Shared storage allocations are summed across selected nodes. The API inventory is a point-in-time view: unrelated administrators, future starts of other stopped VMs, jobs on other state hosts and other clients can consume capacity afterward. Verify backups and keep one owner; a preflight is not an exclusive cluster reservation.

## Run the local bootstrap on Linux

The bootstrap host needs Bash, Python 3, Git, Terraform (matching each repository's version policy), OpenSSH and `flock`, trusted CA certificates, and private connectivity to Proxmox/guests. It can be a dedicated workstation or runner host before CI registration. Credentials remain environment inputs or protected local files; JSON contains only reviewed nonsecret values.

```bash
git clone https://github.com/RayEvelyn/homelab-gitops-guide.git
cd homelab-gitops-guide
cp configs/gitlab-starter.example.json configs/reader.local.json
# Edit node/storage/template/VM ID, network/DNS, key path and actual template disk size.
export PROXMOX_VE_ENDPOINT=https://proxmox.example.test:8006/
# Set PROXMOX_VE_API_TOKEN using your protected local secret mechanism; do not echo it.
# Optional: SSL_CERT_FILE points to a reviewed CA bundle containing your trusted Proxmox CA.
export BOOTSTRAP_WORKSPACE="$HOME/homelab-clones"
export BOOTSTRAP_STATE="$HOME/.local/state/homelab-bootstrap"
python3 scripts/preflight.py --config configs/reader.local.json --phase allocation
./scripts/bootstrap-stack.sh --config configs/reader.local.json --workspace "$BOOTSTRAP_WORKSPACE" --state-root "$BOOTSTRAP_STATE" --component gitlab --action plan
```

The API token needs audit access to the selected nodes, all cluster VM IDs, existing VM/template config and chosen storage/network. Allocation/apply additionally needs the separately reviewed provider permissions from each lab. A filtered/insufficient-permission inventory is not proof an unseen VM ID is free; Proxmox also enforces global VM IDs when creation occurs. Preflight uses GET only, verifies TLS, refuses redirects with the authorization header, bounds responses and prints no token or API body.

Inspect the reported protected saved plan with the exact `TF_DATA_DIR=... terraform show ...` command printed by bootstrap, from the corresponding clone's Terraform directory. Provider diagnostics stay in the private per-role `diagnostics.log`. Plans/state/logs can contain sensitive infrastructure data: never upload them as public artifacts. The plan receipt pins the source commit, nonsecret input hash and saved-plan hash. Changes invalidate the receipt; rerun plan and review. Deletion/replacement plans are rejected. Existing clones must be clean with the exact expected public origin; scripts never auto-pull a different commit.

```bash
# Explicit VM creation, only after reviewing the saved plan from the preceding command:
./scripts/bootstrap-stack.sh --config configs/reader.local.json --workspace "$BOOTSTRAP_WORKSPACE" --state-root "$BOOTSTRAP_STATE" --component gitlab --action provision
```

Provision reuses that saved plan and stops before guest SSH bootstrap. Retrieve the guest fingerprint through a trusted Proxmox console/guest-agent CLI, compare a candidate `ssh-keyscan` fingerprint, then keep the matching known-host line in a reader-owned mode0600 file. The existing account's private key must match the cloud-init public key declared in the profile. Do not use unchecked keyscan output as trusted host identity.

```bash
export HOMELAB_SSH_PRIVATE_KEY_FILE=/protected/path/lab-private-key
export HOMELAB_SSH_KNOWN_HOSTS_FILE=/protected/path/verified-known-hosts
# Provision consumed the previous saved plan: create/review a new plan for deploy.
./scripts/bootstrap-stack.sh --config configs/reader.local.json --workspace "$BOOTSTRAP_WORKSPACE" --state-root "$BOOTSTRAP_STATE" --component gitlab --action plan
./scripts/bootstrap-stack.sh --config configs/reader.local.json --workspace "$BOOTSTRAP_WORKSPACE" --state-root "$BOOTSTRAP_STATE" --component gitlab --action deploy
```

Deploy authenticates all selected existing guests with pinned SSH before any apply, checks capacity again before each apply, reuses the reviewed saved plan, then invokes the selected repo's actual service bootstrap script. Profiles/components do not include Kubernetes, Rancher or LGTM deployment: those labs remain optional later steps after cluster/network/storage capacity is reviewed. Vault initialization/unseal and custodian recovery material stay separate from this bootstrap; the script does not invent a root token.

## Adopt source and state before CI ownership

After GitLab is healthy, follow [the complete GitLab project/runner/variable/manual-job path](GITLAB-CI.md). That page gives `glab repo create`, separate private remote/push, protected variables and exact pipeline/manual-job monitoring. For GitHub, follow [the independent GitHub path](GITHUB-CI.md). The bootstrap state lives under `BOOTSTRAP_STATE/bootstrap-COMPONENT`; platform CI expects its own stable prefixed state ID. Do not enable CI with an empty state for an existing bootstrap VM. Back up first, deliberately migrate/adopt that state using Terraform's supported backend procedures, verify lineage/resource IDs and review a refresh-only plus ordinary plan for unexpected creates. Never run local bootstrap and CI against separate states for the same resource. Recovery must work while GitLab, runners or the cluster are down.

## Optional GPU inventory is not GPU qualification

```bash
python3 scripts/preflight.py --config configs/reader.local.json --gpu-inventory
```

Base profiles require no GPU. This optional read-only PCI count reports VRAM, IOMMU/passthrough and compute compatibility as **unknown**; API permissions may also make the inventory unavailable. No AI model server, training job or GPU passthrough is deployed by these profiles. An AI workload needs a separately reviewed resource/model budget, driver/runtime checks inside the intended guest, actual VRAM evidence and recovery plan.

Offline fixture tests cover capacity failures and phase/plan guards. They do not prove your network, API permissions, VM allocation, application health or restore procedure. Official API definitions: [Proxmox node API](https://github.com/proxmox/pve-manager/blob/master/PVE/API2/Nodes.pm), [storage status API](https://github.com/proxmox/pve-storage/blob/master/src/PVE/API2/Storage/Status.pm).
