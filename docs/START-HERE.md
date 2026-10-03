# Start here: a homelab you can explain, rebuild and recover

This guide connects the individual examples into a practical learning sequence. Build local networking and DNS first, choose GitHub or GitLab for both source and execution, and add scoped automation in stages. Self-managed GitLab is bootstrapped independently only in the GitLab path. **Public teaching code is safe to inspect: opening it does not create accounts or apply infrastructure. Hosted CI validates it; either private deployment path is explicitly opt-in.** Commands are examples to adapt and review before running in your own lab.

## Choose one source and execution platform

| Choice | Private source of truth | Deployment execution | Cluster access |
|---|---|---|---|
| [GitHub path](docs/GITHUB-CI.md) | Your private GitHub repository | GitHub Actions and its dedicated runner | Direct scoped kubeconfig for cluster jobs; no GitLab/KAS prerequisite |
| [GitLab path](docs/GITLAB-CI.md) | Your private GitLab project | GitLab CI and its dedicated runner | Optional GitLab agent/KAS for cluster jobs |

The canonical public GitHub repository distributes examples and runs unprivileged validation. Choose one private source and runner platform for each real target; do not combine a GitHub source checkout with instructions for a GitLab runner, or let both pipelines manage the same resource. GitLab-first bootstrap applies only when you select self-managed GitLab. GitHub can bootstrap the GitLab VM as a service without depending on that service's CI. KAS is a GitLab integration, not a universal prerequisite for Kubernetes or GitOps. Flux or another chosen reconciler can use either supported Git source.


## Start small with the executable local bootstrap

Use [BOOTSTRAP.md](docs/BOOTSTRAP.md) for the actual `scripts/bootstrap-stack.sh` entrypoint: choose a GitLab-only starter or optional foundation components, prepare networking/DNS, check real Proxmox capacity, create/review protected saved plans, then explicitly provision and deploy. No GPU is needed. The optional foundation is a resource budget, not a requirement to install every service; insufficient or unknown capacity stops the run before apply. GitLab local bootstrap is required only for the self-managed GitLab execution path.

## Start small with the executable local bootstrap

The [bootstrap entrypoint and network/capacity guide](https://github.com/RayEvelyn/homelab-gitops-guide/blob/main/docs/BOOTSTRAP.md) provides a GitLab-only starter and optional foundation roles, protected saved-plan review and explicit local provisioning. No GPU is required; you choose the components that fit your actual capacity. Local GitLab bootstrap applies only to the self-managed GitLab path.

## Why GitOps?

An understandable lab is more valuable than a collection of services that happen to be running. Versioned configuration lets you review a change, explain who owns it, and rebuild from a known starting point. Pull-based reconciliation can detect drift and repeatedly bring runtime configuration toward the approved desired state. Those benefits require deliberate boundaries, safe credentials and recovery practice; they do not remove operational responsibility.

[OpenGitOps](https://opengitops.dev/) describes four principles: declarative desired state, versioned and immutable history, automatic pull, and continuous reconciliation. A CI job that runs `kubectl apply` once is a useful deployment workflow, but does not continuously reconcile later drift. Similarly, a scheduled Terraform plan can detect differences without automatically correcting them. Call these workflows accurately. This series starts with reviewed CI deployments; optional Flux adds a true pull/reconcile loop later.

## Shared prerequisites, then the selected platform

| Stage | Build and prove | Why it comes first |
|---|---|---|
| 0. Recovery basics | Administrative SSH/console path, inventory, safe backups, independent clock/NTP | You need a way to recover when automation is unavailable. |
| 1. Network + bootstrap DNS | LAN/VLAN addressing, routing, reserved IPs, trusted resolver, local authoritative zones | GitLab and cluster names must resolve before their services exist. |
| 2. Selected source platform | GitHub private source immediately; or independent local GitLab with HTTPS/data/restore | Self-managed GitLab cannot bootstrap through its own unavailable CI. GitHub has no local GitLab prerequisite. |
| 3. Your private repositories | Create/import reviewed code into the chosen private GitHub repository or GitLab project | Your deployment configuration now has a reachable owner and history. |
| 4. Scoped runners | Dedicated execution host, trusted builds, protected secrets, isolated untrusted jobs | Automation runs with only the access it needs. |
| 5. Infrastructure plans | State locking, full plan review, protected manual apply | Learn destructive-change review before handing it to a pipeline. |
| 6. Kubernetes, then Rancher | kubeadm networking/storage/readiness, tested recovery; optional Rancher management | Management software depends on a healthy cluster, not the reverse. |
| 7. Cluster access + workloads | GitHub scoped kubeconfig; or GitLab KAS agent, namespace RBAC, explicit context | Use the integration belonging to your chosen CI platform. |
| 8. Data + observability | Reviewed Flyway changes, Loki/Grafana/Tempo/Mimir, alerts and retention | Verify application behavior and recovery, not only green job status. |
| 9. Optional Flux | Narrow Git sources, reconciliation scope and rollback/prune policy | Add continuous convergence after you understand the deployed resources. |

Keep enough DNS/time/admin access outside the platform to restore GitLab and Kubernetes. Running an authoritative DNS container is not automatically a client resolver: authoritative service answers its zones, a recursor resolves client queries. Do not make a recursor depend on its own unavailable authoritative server for all upstream lookups. Validate routing and name resolution from the workstation, runner and cluster separately. Record CIDRs and avoid DHCP/static-address collisions.

The sibling labs are independent starting points: [GitLab](https://github.com/RayEvelyn/gitlab-proxmox-terraform#readme), [authoritative DNS](https://github.com/RayEvelyn/powerdns-authoritative-lab#readme), [recursor](https://github.com/RayEvelyn/powerdns-recursor-lab#readme), [Vault](https://github.com/RayEvelyn/vault-proxmox-lab#readme), [kubeadm](https://github.com/RayEvelyn/kubeadm-proxmox-lab#readme), [Rancher](https://github.com/RayEvelyn/rancher-proxmox-lab#readme), [Flyway](https://github.com/RayEvelyn/postgres-flyway-lab#readme), [LGTM](https://github.com/RayEvelyn/lgtm-kubernetes-lab#readme), and [Cloudflare](https://github.com/RayEvelyn/cloudflare-homelab-tunnel#readme). Each link opens the cloneable public code and its README. Vault can be introduced after GitLab, but retain an independent secret/recovery path: do not require a sealed Vault to recover the GitLab host it depends on.

## Public examples versus your private source of truth

A public GitHub example is a teaching artifact with generic values. Your chosen private GitHub repositories or GitLab projects own your real IPs, release pins and reviewed configuration. Even a **private** repository must not contain tokens, passwords, unseal shares, private keys, kubeconfigs or Terraform state. Maintain your own fork/configuration; do not enable an upstream example's deployment pipeline blindly.

The following import block belongs only to the GitLab path, after that instance is healthy. The separate GitHub path is in [GITHUB-CI.md](docs/GITHUB-CI.md):

```bash
export GITLAB_HOST=gitlab.example.test
# Authenticate interactively with your own scoped/expiring token; trust local TLS.
glab auth login --hostname "$GITLAB_HOST"
glab auth status --hostname "$GITLAB_HOST"
# Existing group 'homelab' must already exist and be writable by you.
# A private project is deliberately separate from public example hosting.
glab repo create homelab/network-terraform --private --defaultBranch main --skipGitInit
cd /path/to/your/reviewed/network-terraform
git remote -v
# Add a separate remote; do not replace an existing public-example origin.
git remote add homelab ssh://git@gitlab.example.test:2222/homelab/network-terraform.git
git push homelab HEAD:main
```

The create/push commands above change your GitLab when **you run them**. Repeat for the reviewed repositories you choose, not as a blind estate-wide loop. Choose your actual SSH port. Inspect `.gitignore`, staged files and history for secrets before the first push; deletion in a later commit does not remove a leaked secret from history. Revoke any exposed credential.

## Repository boundaries and ownership

| Repository | Owns | Does not own |
|---|---|---|
| `service-app` | Source, tests, Dockerfile, immutable release image | Cluster-wide permissions or schema history |
| `service-terraform` | VM/network/storage desired configuration and protected state backend | Application passwords or one-shot data migrations |
| `service-manifests` | Namespace workloads, service/ingress, release image reference | Another service's resources or database contents |
| `service-flyway` | Ordered reviewed SQL migrations and schema validation | Infrastructure destruction or fabricated rollback guarantees |
| `cluster-bootstrap` | Cluster-level prerequisites and bounded agent installation | Routine application changes |
| `observability-manifests` | Collectors, dashboards/rules, storage/retention configuration | Unlimited retention or proof an alert reaches an operator |

Name one owner for every resource. A small lab may combine directories in one repository; preserve the logical boundaries and separate jobs/permissions. Two controllers must not own the same Deployment or Terraform resource. Keep database migrations forward-only where appropriate; never silently rewrite an applied migration to remove a failure. Compare desired files, actual runtime, data compatibility and operator receipts separately.

## Runners, plans and changes with consequences

Use dedicated runners for privileged infrastructure jobs. A Docker socket mount gives effective host control; a shell executor runs on the host. Avoid sharing those execution environments with untrusted merge-request code. A runner tag routes jobs; it is not an authorization boundary. Configure project scope, protected refs and credential access explicitly using the selected platform API/CLI for your version. Protect the actual default branch and require review before merging.

For Terraform, start with validate/format in merge requests and plans with the lowest necessary provider permissions. Plans and state may contain sensitive infrastructure values: do not publish plan artifacts or logs publicly. Apply only a reviewed saved plan for the same commit/provider lock/state lineage, with remote state locking and one serialized apply lane. Use a protected manual job; manual alone does not mean authorized. Re-plan after drift or stale artifacts. A green plan does not prove an apply is safe; inspect replacements, deletes, cloud-init changes and disk/network effects.

Use env/secret-manager credentials, short lifetimes and separate read/plan versus write/apply authority when the provider supports them. Protected/masked variables reduce accidental access/output; they cannot make a malicious script safe. Back up affected configuration before changes and verify the recovery path. Keep a documented emergency administrative path independent of GitLab jobs.

## Optional GitLab path: KAS and agentk

KAS means **Kubernetes Agent Server** (current docs also call it GitLab Relay). It runs on the GitLab side; `agentk` runs in Kubernetes. The usual agent establishes an outbound connection to KAS. An administrator must configure the self-managed endpoint and trusted TLS; confirm the exact URL for your GitLab installation. [KAS administration](https://docs.gitlab.com/administration/clusters/kas/)

The agent registration token authenticates agentk to GitLab. It is distinct from a CI job token and from GitLab Runner authentication. Keep it in a Kubernetes Secret/approved secret store, never in a manifest committed to Git. The default agent Helm chart can grant broad cluster access: explicitly supply a least-privilege service account rather than accepting that default. Register/install using the supported CLI/API/Helm flow for your release. [Agent installation](https://docs.gitlab.com/user/clusters/agent/install/), [agent API](https://docs.gitlab.com/api/cluster_agents/)

Copy [.gitlab/agents/lab/config.yaml.example](.gitlab/agents/lab/config.yaml.example) to `config.yaml` in your **agent configuration project**, after replacing the exact authorized project. Authorized CI jobs receive a `$KUBECONFIG` with an agent context named `<agent-config-project>:<agent-name>`, for example `homelab/cluster-bootstrap:lab`. Select it explicitly; never print the kubeconfig. `ci_access` permits connection sharing, while Kubernetes RBAC bounds operations. In CE this example uses agent service-account permissions; CI-job impersonation has separate tier requirements. [CI/CD agent workflow](https://docs.gitlab.com/user/clusters/agent/ci_cd_workflow/)

[examples/namespace-rbac.yaml](examples/namespace-rbac.yaml) illustrates a narrow `demo` namespace ConfigMap deployer without Secret/RBAC/workload/cluster-admin permissions. An existing administrator creates the namespace/account/binding as a reviewed bootstrap step, then configures the agent chart to use that account. Chart flags/schema vary: inspect the pinned chart with `helm show values` and render it before installation. This example does not install an agent or create a token.

The functional [.gitlab-ci.yml](.gitlab-ci.yml) (with an optional disabled [.example copy](.gitlab-ci.yml.example)) deploys only the included non-secret ConfigMap through a protected-default-branch manual job, fixed namespace and explicit `kubectl auth can-i` checks. Set a **reviewed kubectl image digest** as `KUBECTL_IMAGE`, protect the branch/runner, and enable only after adapting the manifests. Environment protection is a separate GitLab feature with tier restrictions; do not assume CE has every approval gate. [Protected environments](https://docs.gitlab.com/ci/environments/protected_environments/)

## Add reconciliation when you are ready

Flux is optional here. A Flux source watches an approved Git repository; reconciliation applies selected declarations repeatedly. Review source credentials, namespaces, pruning and deletion behavior, health dependencies and reconciliation intervals. Keep emergency pause/recovery instructions. Do not let Flux and a CI apply job race over the same objects. GitLab describes Flux integration separately from agent-based CI access. [GitLab GitOps](https://docs.gitlab.com/user/clusters/agent/gitops/)

KAS transports authorized access; it does not continually reconcile every VM, database and workload. Terraform apply and Flyway migrate have their own state/ordering semantics and destructive consequences. Introduce each automation loop deliberately.

## Prove recovery and runtime behavior

A Git revert changes configuration history; it **does not undo database writes, schema migration, deleted disks or lost backups**. A prior image may be incompatible with a new schema. Restore databases using tested application-consistent backups; use forward fixes when rollback is unsafe. Test GitLab restore without needing its own CI, preserve Vault recovery material outside the service, and practice cluster recovery on an isolated target.

For Loki/Grafana/Tempo/Mimir, first prove collection and retention, then dashboards, actionable alerts and an actual notification receipt. These services use storage, networks and credentials too. A live probe, deployment rollout status, usable application path and verified restore are different evidence from lint/CI success.

## Review checklist before enabling anything

- Workstation/runner/cluster resolve local names, trust certificates and agree on time.
- When choosing self-managed GitLab, it works independently of Kubernetes; recovery access is documented.
- Repositories have clear owners; public examples and real private configuration are separate.
- State, tokens and private keys are outside Git; backups are encrypted off-host and restore-tested.
- Runner and agent permissions are scoped; expected `can-i` operations succeed and forbidden operations fail.
- Plan/deploy/migration changes have review and serialization; controller ownership does not overlap.
- Startup, health, alert delivery and recovery are verified for the actual target.

This guide was checked against official documentation on 2026-10-03. YAML syntax and embedded Bash can be checked locally; no account, runner, cluster, permission, deployment or recovery behavior is claimed as executed here.

## Functional CI and platform ownership

Hosted GitHub validation checks the public examples without deployment credentials. For private execution choose [GitHub source + Actions + scoped kubeconfig](docs/GITHUB-CI.md) or [GitLab source + CI + KAS](docs/GITLAB-CI.md). Both demo deploy jobs apply the same nonsecret ConfigMap with namespace/RBAC checks, and both require explicit enablement. Neither is continuous reconciliation. VM state belongs to one chosen platform/runner path; changing platforms requires a reviewed state migration, not two simultaneous owners.
