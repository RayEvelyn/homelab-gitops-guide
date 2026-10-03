# GitLab source and GitLab CI execution

Choose this path when GitLab owns both your private code and CI jobs. GitHub remains the reviewed public example source; GitHub Actions, `gh` configuration and GitHub runners are not used for deployment in this path.

## Bootstrap the Git server before asking it to run CI

For self-managed GitLab, first use the local workstation Terraform and verified SSH instructions in the [GitLab VM example](https://github.com/RayEvelyn/gitlab-proxmox-terraform#readme), or its bare-metal route. Confirm DNS, HTTPS trust, startup and backup/restore access. Keep recovery outside GitLab. The first GitLab installation cannot depend on a pipeline hosted by the GitLab instance that does not yet exist. A healthy existing GitLab instance can instead host these projects immediately.

## Create the private source project with the CLI

The commands below are examples for your own instance and account. They create a private project only when you run them. Keep the public upstream remote for reference; do not overwrite it.

```bash
export GITLAB_HOST=gitlab.example.test
glab auth login --hostname "$GITLAB_HOST"
glab auth status --hostname "$GITLAB_HOST"
git clone https://github.com/RayEvelyn/homelab-gitops-guide.git
cd homelab-gitops-guide
# Use an existing writable namespace; create the group separately if needed.
export GITLAB_PROJECT=homelab/REPLACE_WITH_PROJECT
# Run once for a new project; existing private projects do not need recreation.
glab repo create "$GITLAB_PROJECT" --private --defaultBranch main --skipGitInit
git remote add homelab "ssh://git@$GITLAB_HOST/$GITLAB_PROJECT.git"
# Review staged files AND history for secrets before the first push.
git push homelab HEAD:main
project_id=$(glab api --hostname "$GITLAB_HOST" "projects/${GITLAB_PROJECT//\//%2F}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
# Inspect existing branch protection; preserve stronger rules.
glab api --hostname "$GITLAB_HOST" "projects/$project_id/protected_branches"
# Only if main has no protection yet: Maintainer pushes/merges, no force push.
glab api --hostname "$GITLAB_HOST" --method POST "projects/$project_id/protected_branches" -f name=main -F push_access_level=40 -F merge_access_level=40 --silent
```

Adjust the SSH port to the one your installation advertises and verify its host key independently. Use a scoped/expiring GitLab API token with `glab`; never embed it in a remote URL. Source import does not transfer runners, variables, cluster permissions or Terraform state.

## Own the execution host and credentials

Register a dedicated project-scoped protected GitLab runner tagged `homelab` (the guide's containerized cluster job uses `protected-deploy`). Runner tags route jobs; protection, project scope and reviewed default-branch changes control access. Do not share the deployment runner with untrusted merge requests. Keep an isolated unprivileged runner tagged `validation` for validation jobs. Use the [runner creation API](https://docs.gitlab.com/api/users/#create-a-runner) and [authentication-token registration flow](https://docs.gitlab.com/runner/register/#register-with-a-runner-authentication-token); create the runner with `access_level=ref_protected` and `run_untagged=false`. Capture the returned runner authentication token into a mode0600 local file and feed it through the registration tool's protected environment, not command history or logs. Review actual runner settings before enabling jobs. A shell runner executes repository code on its host; a Docker socket also grants host control.

Keep `DEPLOY_ENABLED=false` until source, runner, state and credentials have been reviewed. Configure protected variables in the `homelab` environment scope for VM jobs; the guide uses scope `lab`. GitLab's masked values have format restrictions: multiline SSH/CA material uses protected **file-type** variables; do not claim it is masked just because it is protected. Never enable debug shell/HTTP tracing around credentials. The helper reads file inputs into private runtime files without printing them.

## Cluster access through KAS, only in this GitLab path

Bootstrap the Kubernetes namespace/account/RBAC with an existing trusted administrative CLI. Configure the GitLab agent in a separate agent-configuration project, install agentk with the least-privilege service account from `examples/namespace-rbac.yaml`, and authorize this exact private deployment project. The agent connects outbound to trusted KAS; CI receives the agent kubeconfig/context. No long-lived admin kubeconfig belongs in this project. Agent registration tokens, runner authentication and job tokens are different credentials. CE uses scoped agent service-account permissions; CI-job impersonation has tier-specific requirements. See the README's KAS section and `.gitlab/agents/lab/config.yaml.example` for the deliberately separate bootstrap.

Use a protected Docker-executor runner tagged `protected-deploy` and a reviewed kubectl+Bash image digest. Set protected `DEPLOY_ENABLED=true`, `KUBECTL_IMAGE`, `KUBE_CONTEXT=YOUR_AGENT_PROJECT:lab` with scope `lab`; `DEPLOY_NAMESPACE` is fixed to `demo`. GitLab runner must trust KAS TLS. `KUBE_CONTEXT` is not a GitHub context or KAS registration token.

```bash
glab variable set DEPLOY_ENABLED true --repo "$GITLAB_PROJECT" --protected --scope lab
glab variable set KUBECTL_IMAGE 'YOUR_REVIEWED_IMAGE@sha256:REPLACE_DIGEST' --repo "$GITLAB_PROJECT" --protected --scope lab
glab variable set KUBE_CONTEXT 'homelab/cluster-bootstrap:lab' --repo "$GITLAB_PROJECT" --protected --scope lab
glab ci run --repo "$GITLAB_PROJECT" --branch main
glab ci list --repo "$GITLAB_PROJECT"
export PIPELINE_ID=REPLACE_WITH_PIPELINE_ID
glab ci trigger manual_lab_deploy --repo "$GITLAB_PROJECT" --pipeline-id "$PIPELINE_ID"
glab ci trace manual_lab_deploy --repo "$GITLAB_PROJECT" --pipeline-id "$PIPELINE_ID"
```

The job requires a private project, protected default ref and exact expected namespace, verifies required ConfigMap permissions and denies Secret-read permission, server-dry-runs then applies only the nonsecret ConfigMap. A manual or pending job has not applied anything; confirm its terminal status and resulting ConfigMap. This is a one-shot CI apply, not continuous GitOps reconciliation. Use one owner for these objects if adding Flux later.

Official references: [project API](https://docs.gitlab.com/api/projects/), [variables](https://docs.gitlab.com/ci/variables/), [manual job API](https://docs.gitlab.com/api/jobs/), [protected/manual jobs](https://docs.gitlab.com/ci/jobs/job_control/). Commands/configuration were checked offline; no reader account, runner, token, infrastructure or cluster was changed.

## Register the GitLab execution runner with CLI tools

Install the reviewed official GitLab Runner package on the dedicated Linux host first. The following creates a project runner and captures its token privately. Keep a separate configuration file; do not overwrite an existing runner's global `config.toml`. Run this as the dedicated execution account with the appropriate GitLab project API permission:

```bash
umask 077
runner_setup=$(mktemp -d)
export project_id
python3 - <<'PYRUNNER'
import json,os
from pathlib import Path
v={'runner_type':'project_type','project_id':int(os.environ['project_id']),
   'description':'homelab-fixed','tag_list':['protected-deploy'],'run_untagged':False,
   'locked':True,'access_level':'ref_protected'}
Path('runner-request.local.json').write_text(json.dumps(v))
PYRUNNER
glab api --hostname "$GITLAB_HOST" --method POST user/runners --input runner-request.local.json > "$runner_setup/response.json"
rm -f runner-request.local.json
export CI_SERVER_TOKEN
CI_SERVER_TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$runner_setup/response.json")
mkdir -p "$HOME/.config/gitlab-runner"
chmod 700 "$HOME/.config/gitlab-runner"
gitlab-runner register --non-interactive --url "https://$GITLAB_HOST" --executor docker --docker-image alpine:3.23 --docker-privileged=false --config "$HOME/.config/gitlab-runner/protected-deploy.toml" --description homelab-fixed
unset CI_SERVER_TOKEN
rm -rf -- "$runner_setup"
gitlab-runner run --config "$HOME/.config/gitlab-runner/protected-deploy.toml"
```

For the guide's KAS deployment use a separate protected runner with API tag `protected-deploy` and the Docker executor; its reviewed kubectl image comes from `KUBECTL_IMAGE`. The registration block above uses the protected Docker executor for this guide; VM siblings use their separately documented shell runner. Do not route container-image jobs to a shell executor expecting that `image:` will isolate execution. Register the `validation` runner separately with an isolated Docker executor and without provider/SSH credentials. `CI_SERVER_TOKEN` is the runner authentication input, not a KAS token or provider API token. Keep its persistent runner configuration private, verify project/protection/tag settings through the API, and deliberately configure the runner's service after testing it. [Runner authentication input](https://gitlab.com/gitlab-org/gitlab-runner/-/blob/main/common/config.go), [create-runner API](https://docs.gitlab.com/api/users/#create-a-runner).
