# GitHub source and Actions execution

This path uses GitHub alone for private source and runner execution. It needs no GitLab instance, GitLab Runner, agent or KAS. Public upstream runs hosted unprivileged validation. Choose a private copy before attaching a runner inside your network.

```bash
git clone https://github.com/RayEvelyn/homelab-gitops-guide.git
cd homelab-gitops-guide
gh repo create YOUR_USER/homelab-guide-private --private --source . --remote deployment --push
export DEPLOY_REPO=YOUR_USER/homelab-guide-private
```

On a dedicated Linux host, register a project-scoped GitHub Actions runner with labels `self-hosted,linux,homelab` using GitHub's runner registration API/tooling. It requires kubectl compatible with your cluster and network access to its private API. Do not attach it to public or untrusted PR execution. A runner label routes work; private repository scope, reviewed default branch, explicit enablement and environment policies control who can execute it. Review supported protections for your account; naming an environment does not configure approval rules.

An existing cluster administrator bootstraps the reviewed namespace/RBAC from `examples/namespace-rbac.yaml` using a trusted local CLI. Issue a dedicated scoped kubeconfig for that account using your cluster's supported credential process; do not upload an admin kubeconfig. Preserve trusted API CA verification and choose the exact context name. The example permits ConfigMap get/create/patch in `demo`, and should deny Secret reads. Token lifetime and rotation remain owner responsibilities.

```bash
gh secret set HOMELAB_KUBECONFIG --repo "$DEPLOY_REPO" < /protected/path/demo-scoped-kubeconfig
gh variable set EXPECTED_CONTEXT --repo "$DEPLOY_REPO" --body demo-workload
gh variable set DEPLOY_ENABLED --repo "$DEPLOY_REPO" --body true
gh workflow run deploy.yml --repo "$DEPLOY_REPO" --ref main
gh run list --repo "$DEPLOY_REPO" --workflow deploy.yml
# Choose the exact returned run ID, then inspect terminal status/logs.
gh run watch RUN_ID --repo "$DEPLOY_REPO" --exit-status
```

The workflow refuses a public repository, nondefault branch or missing enablement. The helper creates a protected temporary kubeconfig, selects the exact context, tests required permissions and rejects Secret-read access, server-dry-runs then applies only the nonsecret demo ConfigMap. It removes the temporary kubeconfig on exit. A queued/running job is not deployment success; verify the resulting ConfigMap through the scoped identity after success. This one-shot CI apply is not continuous GitOps reconciliation. For Flux, configure the chosen Git source and give the controller exclusive ownership of its resources.

Official references: [GitHub runners](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job), [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/). No actual runner, credential or cluster deployment was performed by these examples.

## Register the GitHub execution runner with CLI tools

Install a reviewed official Actions runner distribution on the dedicated Linux host first and run as its dedicated account. Keep that directory private; preserve an existing registration instead of replacing it. The current runner accepts `ACTIONS_RUNNER_INPUT_TOKEN`, avoiding token arguments/history. This setup belongs only to the private GitHub repository:

```bash
# On the dedicated host, with gh authenticated for your private repository:
umask 077
cd /path/to/reviewed/actions-runner
registration_file=$(mktemp)
gh api --method POST "repos/$DEPLOY_REPO/actions/runners/registration-token" > "$registration_file"
export ACTIONS_RUNNER_INPUT_TOKEN
ACTIONS_RUNNER_INPUT_TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$registration_file")
./config.sh --unattended --url "https://github.com/$DEPLOY_REPO" --labels homelab --name homelab-fixed --work _work
unset ACTIONS_RUNNER_INPUT_TOKEN
rm -f -- "$registration_file"
./run.sh
```

The final command runs the registered runner in the foreground; configure its service with the official `svc.sh` tool when you deliberately want persistence. Do not run it as root or accept public jobs. The CLI example creates a runner registration when you execute it; validation of this repository does not register anything. [Official runner input implementation](https://github.com/actions/runner/blob/main/src/Runner.Listener/CommandSettings.cs).
