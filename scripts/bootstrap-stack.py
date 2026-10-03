#!/usr/bin/env python3
"""Bootstrap selected foundation roles. Plan by default; never destroys infrastructure."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPOS = {'gitlab-proxmox-terraform', 'vault-proxmox-lab', 'postgres-flyway-lab',
         'powerdns-authoritative-lab', 'powerdns-recursor-lab'}
SCRIPT = Path(__file__).resolve().parent


def run(args, cwd=None, env=None, capture=False):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    logfile = (env or {}).get('BOOTSTRAP_DIAGNOSTICS')
    if logfile:
        with Path(logfile).open('a') as log:
            Path(logfile).chmod(0o600)
            log.write(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError(f'{Path(str(args[0])).name} operation failed; inspect configuration and permissions privately')
    return result.stdout if capture else None


def reject_destructive(plan):
    for change in plan.get('resource_changes', []):
        if 'delete' in change.get('change', {}).get('actions', []):
            raise ValueError('Delete/replacement plan refused. Review recovery or lifecycle changes separately')


def selected_config(path, selected):
    config = json.loads(path.read_text())
    components = config.get('components', [])
    names = [c.get('name') for c in components]
    if len(set(names)) != len(names) or not names:
        raise ValueError('Unique named component roles required')
    if selected and not set(selected) <= set(names):
        raise ValueError('Requested component does not exist in config')
    config['components'] = [c for c in components if not selected or c['name'] in selected]
    for c in config['components']:
        if c['repo'] not in REPOS or not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', c['name']):
            raise ValueError('Unsupported repository or unsafe role name')
        values = c['terraform_inputs']
        if any(re.search(r'token|password|secret|private_key', key, re.I) for key in values):
            raise ValueError('Credentials must be environment or protected files, not Terraform JSON')
        public = Path(values['ssh_public_key_path']).expanduser()
        if not public.is_absolute():
            public = path.parent / public
        public = public.resolve(strict=True)
        if not public.read_text().strip().startswith(('ssh-ed25519 ', 'ssh-rsa ', 'ecdsa-sha2-')):
            raise ValueError('ssh_public_key_path must contain an OpenSSH public key')
        values['ssh_public_key_path'] = str(public)
        ipaddress.ip_interface(values['ip_cidr'])
        if c['repo'] in {'gitlab-proxmox-terraform', 'vault-proxmox-lab'}:
            image = c.get('image', '')
            if not re.fullmatch(r'[A-Za-z0-9./:@_-]+', image) or image.endswith(':latest'):
                raise ValueError('Pinned service image required')
        if c['repo'] == 'powerdns-recursor-lab':
            nets = c.get('dns_allowed_cidrs', [])
            if not nets or any(ipaddress.ip_network(n, strict=True).prefixlen == 0 for n in nets):
                raise ValueError('Recursor requires explicit trusted dns_allowed_cidrs; open resolver denied')
    return config


def protected_file(variable):
    value = os.environ.get(variable)
    if not value:
        raise ValueError(f'Set {variable} to a protected absolute file path for deploy')
    path = Path(value).expanduser().resolve(strict=True)
    if path.stat().st_mode & 0o077:
        raise ValueError(f'{variable} must have mode 0600 or stricter')
    if not path.read_text().strip():
        raise ValueError(f'{variable} must not be empty')
    return path


def ssh_config(runtime, private, known):
    path = runtime / 'ssh_config'
    # Paths are quoted; reject line breaks and quotes before entering SSH syntax.
    for p in [private, known]:
        if any(ch in str(p) for ch in ['\n', '\r', '"', '%']):
            raise ValueError('Unsupported SSH file path')
    path.write_text(f'Host *\n  IdentityFile "{private}"\n  UserKnownHostsFile "{known}"\n'
                    '  StrictHostKeyChecking yes\n  IdentitiesOnly yes\n  BatchMode yes\n'
                    '  ConnectTimeout 10\n  PasswordAuthentication no\n')
    path.chmod(0o600)
    return path


def preflight(config_path, phase, deploy=False):
    args = [sys.executable, SCRIPT / 'preflight.py', '--config', config_path, '--phase', phase]
    if deploy:
        args.append('--check-guest-ssh')
    # This helper emits only sanitized capacity/network summaries.
    subprocess.run([str(x) for x in args], check=True)


def bootstrap(args):
    if sys.platform != 'linux':
        raise ValueError('Bootstrap runs on Linux; validation and planning need Linux tools and Proxmox reachability')
    for tool in ['git', 'terraform', 'flock', 'ssh', 'scp']:
        if not shutil.which(tool):
            raise ValueError(f'Install required CLI: {tool}')
    config = selected_config(Path(args.config).expanduser().resolve(strict=True), args.component)
    workspace = Path(args.workspace).expanduser().resolve()
    state = Path(args.state_root).expanduser().resolve()
    if not Path(args.state_root).expanduser().is_absolute():
        raise ValueError('State root must be absolute')
    if state == workspace or state.is_relative_to(workspace) or workspace.is_relative_to(state) or state.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError('State must be permanent and outside workspace and temporary directories')
    if os.environ.get('PROXMOX_VE_INSECURE', '').lower() in {'1', 'true', 'yes'}:
        raise ValueError('Proxmox TLS verification must remain enabled')
    for ephemeral in [Path('/var/tmp'), Path(os.environ.get('RUNNER_TEMP', '/tmp'))]:
        if state.is_relative_to(ephemeral.resolve()):
            raise ValueError('State root must be outside ephemeral runner directories')
    workspace.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True); state.chmod(0o700)
    with (state / 'stack.lock').open('a') as stack_lock:
        fcntl.flock(stack_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = os.environ.copy()
        for required in ['PROXMOX_VE_ENDPOINT', 'PROXMOX_VE_API_TOKEN']:
            if not env.get(required):
                raise ValueError(f'Set {required} in the environment')
        # Terraform inputs cannot be overridden invisibly by inherited TF_VAR values or CLI flags.
        env = {k: v for k, v in env.items() if not k.startswith(('TF_VAR_', 'TF_CLI_ARGS'))}
        env['TF_IN_AUTOMATION'] = 'true'
        with tempfile.TemporaryDirectory(prefix='homelab-bootstrap-') as temp:
            runtime = Path(temp); runtime.chmod(0o700)
            config_path = runtime / 'selected.json'; config_path.write_text(json.dumps(config)); config_path.chmod(0o600)
            private = known = ssh = None
            if args.action == 'deploy':
                private = protected_file('HOMELAB_SSH_PRIVATE_KEY_FILE')
                known = protected_file('HOMELAB_SSH_KNOWN_HOSTS_FILE')
                derived = run(['ssh-keygen', '-y', '-f', private], capture=True).split()[:2]
                for c in config['components']:
                    declared = Path(c['terraform_inputs']['ssh_public_key_path']).read_text().split()[:2]
                    if derived != declared:
                        raise ValueError('Deployment private key does not match configured cloud-init public key')
                ssh = ssh_config(runtime, private, known)
                # Authenticate every selected existing guest before any apply. Provision first for new VMs.
                for c in config['components']:
                    host = str(ipaddress.ip_interface(c['terraform_inputs']['ip_cidr']).ip)
                    run(['ssh', '-F', ssh, 'ubuntu@' + host, 'true'])
            preflight(config_path, 'allocation')
            for c in config['components']:
                name = c['name']; role = state / ('bootstrap-' + name)
                role.mkdir(exist_ok=True); role.chmod(0o700)
                with (role / 'bootstrap.lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    identity = role / 'identity.json'
                    expected = {'repo': c['repo'], 'node': c['node'], 'vm_id': c['terraform_inputs']['vm_id']}
                    if identity.exists() and json.loads(identity.read_text()) != expected:
                        raise ValueError('Role state identity changed; explicit state migration required')
                    checkout = workspace / name
                    url = 'https://github.com/RayEvelyn/' + c['repo'] + '.git'
                    if not checkout.exists():
                        run(['git', 'clone', '--', url, checkout])
                    if run(['git', 'remote', 'get-url', 'origin'], cwd=checkout, capture=True).strip() != url:
                        raise ValueError('Existing clone origin differs from allowlisted public repository')
                    if run(['git', 'status', '--porcelain'], cwd=checkout, capture=True).strip():
                        raise ValueError('Existing clone has changes; preserve and review before bootstrap')
                    # Never auto-pull: reruns use the reviewed local commit and report its identity.
                    commit = run(['git', 'rev-parse', 'HEAD'], cwd=checkout, capture=True).strip()
                    print(f'{name}: reviewed source commit {commit}', flush=True)
                    tf = checkout if (checkout / 'main.tf').exists() else checkout / 'terraform'
                    if not tf.is_dir():
                        raise ValueError('Repository Terraform scaffold unavailable')
                    role_env = env.copy(); role_env['TF_DATA_DIR'] = str(role / 'terraform-data')
                    role_env['BOOTSTRAP_DIAGNOSTICS'] = str(role / 'diagnostics.log')
                    inputs = runtime / (name + '.tfvars.json'); inputs.write_text(json.dumps(c['terraform_inputs'])); inputs.chmod(0o600)
                    plan = role / 'reviewed.tfplan'
                    run(['terraform', 'init', '-input=false', '-lockfile=readonly', '-reconfigure', '-backend-config=path=' + str(role / 'terraform.tfstate')], cwd=tf, env=role_env)
                    run(['terraform', 'validate'], cwd=tf, env=role_env)
                    receipt_path = role / 'review-receipt.json'
                    input_hash = hashlib.sha256(json.dumps(c['terraform_inputs'], sort_keys=True).encode()).hexdigest()
                    if args.action == 'plan':
                        run(['terraform', 'plan', '-input=false', '-lock-timeout=60s', '-out=' + str(plan), '-var-file=' + str(inputs)], cwd=tf, env=role_env)
                        plan.chmod(0o600)
                    elif not plan.exists() or not receipt_path.exists():
                        raise ValueError('Run plan and review the protected saved plan before provision/deploy')
                    plan_hash = hashlib.sha256(plan.read_bytes()).hexdigest()
                    expected_receipt = {'commit': commit, 'input_sha256': input_hash, 'plan_sha256': plan_hash}
                    if args.action != 'plan' and json.loads(receipt_path.read_text()) != expected_receipt:
                        raise ValueError('Reviewed plan source, inputs, or file changed; run plan again and review')
                    data = json.loads(run(['terraform', 'show', '-json', plan], cwd=tf, env=role_env, capture=True))
                    reject_destructive(data)
                    for change in data.get('resource_changes', []):
                        address = change.get('address', '')
                        if not re.fullmatch(r'[A-Za-z0-9_.\[\]"-]+', address):
                            address = '(resource address withheld)'
                        print(f'{name}: {address}: {", ".join(change.get("change", {}).get("actions", []))}', flush=True)
                    identity.write_text(json.dumps(expected)); identity.chmod(0o600)
                    if args.action == 'plan':
                        receipt_path.write_text(json.dumps(expected_receipt)); receipt_path.chmod(0o600)
                        print(f'{name}: plan only; review TF_DATA_DIR={role / "terraform-data"} terraform show {plan} from {tf}', flush=True)
                        print(f'{name}: private diagnostics: {role / "diagnostics.log"}; never upload state, plans, or logs', flush=True)
                        continue
                    # Recheck whole selected allocation immediately before each apply.
                    preflight(config_path, 'allocation')
                    run(['terraform', 'apply', '-input=false', '-lock-timeout=60s', plan], cwd=tf, env=role_env)
                    one = dict(config, components=[c]); one_path = runtime / (name + '.json'); one_path.write_text(json.dumps(one))
                    preflight(one_path, 'refresh', args.action == 'deploy')
                    if args.action == 'provision':
                        print(f'{name}: provisioned; verify guest host keys independently before deploy', flush=True)
                        continue
                    deploy_env = role_env.copy()
                    host = str(ipaddress.ip_interface(c['terraform_inputs']['ip_cidr']).ip)
                    deploy_env.update(TARGET='ubuntu@' + host, HOMELAB_SSH_CONFIG=str(ssh), LAB_HOSTNAME=c['lab_hostname'], IMAGE=c.get('image', ''))
                    script = checkout / 'scripts' / 'deploy.sh'
                    if c['repo'].startswith('powerdns-'):
                        script = checkout / 'scripts' / 'deploy-bare-metal.sh'
                        deploy_env.update(HOMELAB_SSH_HOST=host, SSH_PRIVATE_KEY=private.read_text(), SSH_KNOWN_HOSTS=known.read_text(), DNS_BIND_IP=host)
                        if c['repo'] == 'powerdns-recursor-lab':
                            deploy_env['DNS_ALLOWED_CIDRS'] = ','.join(c['dns_allowed_cidrs'])
                    run(['bash', script], cwd=checkout, env=deploy_env)
                    print(f'{name}: deployment script completed; service backup/restore remains a separate operational check', flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--workspace', required=True, help='Directory for public source clones; never stores state')
    parser.add_argument('--state-root', default=str(Path.home() / '.local/state/homelab-bootstrap'), help='Permanent absolute state directory, outside checkout and /tmp')
    parser.add_argument('--action', choices=['plan', 'provision', 'deploy'], default='plan')
    parser.add_argument('--component', action='append', help='Select named role; repeat to select several')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        bootstrap(args)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        # No raw provider output, secret file content, API bodies, or subprocess exceptions.
        print('Bootstrap stopped safely: check profile, tools, network/TLS, SSH trust, capacity, or private command diagnostics. No destroy is supported.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
