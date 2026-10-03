"""Boundary tests; no network, Terraform provider, or infrastructure apply."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap', Path(__file__).resolve().parents[1] / 'scripts/bootstrap-stack.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BootstrapTests(unittest.TestCase):
    def test_replacement_and_delete_denied(self):
        for actions in [['delete'], ['delete', 'create'], ['create', 'delete']]:
            with self.assertRaises(ValueError):
                b.reject_destructive({'resource_changes': [{'change': {'actions': actions}}]})
        b.reject_destructive({'resource_changes': [{'change': {'actions': ['update']}}]})

    def test_filter_and_secret_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); key = root / 'key.pub'; key.write_text('ssh-ed25519 AAAA example\n')
            c = {'name': 'gitlab', 'repo': 'gitlab-proxmox-terraform', 'image': 'gitlab/gitlab-ce:19.4.1-ce.0', 'terraform_inputs': {'ssh_public_key_path': str(key), 'ip_cidr': '192.0.2.110/24'}}
            path = root / 'config.json'; path.write_text(json.dumps({'components': [c]}))
            self.assertEqual(b.selected_config(path, ['gitlab'])['components'][0]['name'], 'gitlab')
            with self.assertRaises(ValueError): b.selected_config(path, ['missing'])
            c['terraform_inputs']['password'] = 'not-a-real-secret'
            path.write_text(json.dumps({'components': [c]}))
            with self.assertRaises(ValueError): b.selected_config(path, [])

    def test_ephemeral_state_denied_before_commands(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(config=str(Path(d) / 'config'), workspace=str(Path(d) / 'clones'), state_root=str(Path.home() / '.local/state/test-bootstrap-never-created'), action='plan', component=[])
            Path(args.config).write_text('{}')
            # Refusal of ephemeral state happens before cloning or invoking Terraform.
            args.state_root = str(Path(d) / 'state')
            with patch.object(b, 'selected_config', return_value={'components': []}), patch.object(b.sys, 'platform', 'linux'), patch.object(b.shutil, 'which', return_value='/mock'), patch.object(b, 'run') as run:
                with self.assertRaises(ValueError): b.bootstrap(args)
                run.assert_not_called()

    def phase_mock(self, action, fail_preflight=False):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            public = root / 'key.pub'; public.write_text('ssh-ed25519 AAAA example\n')
            config = json.loads((Path(__file__).resolve().parents[1] / 'configs/gitlab-starter.example.json').read_text())
            config['components'][0]['terraform_inputs']['ssh_public_key_path'] = str(public)
            path = root / 'config.json'; path.write_text(json.dumps(config))
            args = argparse.Namespace(config=str(path), workspace=str(root / 'clones'), state_root=str(root / 'state'), action=action, component=[])
            calls = []
            def command(argv, cwd=None, env=None, capture=False):
                argv = [str(x) for x in argv]; calls.append(argv)
                if argv[:2] == ['git', 'clone']:
                    clone = Path(argv[-1]); clone.mkdir(parents=True); (clone / 'main.tf').write_text('mock')
                if argv[:3] == ['git', 'remote', 'get-url']: return 'https://github.com/RayEvelyn/gitlab-proxmox-terraform.git\n'
                if argv[:2] == ['git', 'status']: return ''
                if argv[:2] == ['git', 'rev-parse']: return 'a' * 40
                if argv[:2] == ['terraform', 'plan']:
                    Path(next(x[5:] for x in argv if x.startswith('-out='))).touch()
                if argv[:2] == ['terraform', 'show']: return json.dumps({'resource_changes': [{'change': {'actions': ['create']}}]})
                return ''
            with patch.object(b.sys, 'platform', 'linux'), patch.object(b.shutil, 'which', return_value='/mock'), patch.object(b.tempfile, 'gettempdir', return_value='/tmp'), patch.dict(b.os.environ, {'PROXMOX_VE_ENDPOINT': 'https://pve.example:8006', 'PROXMOX_VE_API_TOKEN': 'mock-only'}, clear=True), patch.object(b, 'run', side_effect=command), patch.object(b, 'preflight', side_effect=ValueError('mock denied') if fail_preflight else None) as preflight:
                if fail_preflight:
                    with self.assertRaises(ValueError): b.bootstrap(args)
                    self.assertEqual(calls, [])
                else:
                    if action == 'provision':
                        args.action = 'plan'; b.bootstrap(args); args.action = action
                        calls.clear(); preflight.reset_mock()
                    b.bootstrap(args)
                    self.assertFalse(any(x[0] == 'ssh' for x in calls))
                    self.assertEqual(any(x[:2] == ['terraform', 'apply'] for x in calls), action == 'provision')
                    phases = [x.args[1] for x in preflight.call_args_list]
                    self.assertEqual(phases, ['allocation'] if action == 'plan' else ['allocation', 'allocation', 'refresh'])

    def test_plan_never_applies(self): self.phase_mock('plan')
    def test_provision_never_ssh_connects(self): self.phase_mock('provision')
    def test_preflight_failure_stops_all_commands(self): self.phase_mock('plan', fail_preflight=True)

    def test_deploy_credentials_require_private_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'known'; p.write_text('public-host-key\n'); p.chmod(0o644)
            with patch.dict(b.os.environ, {'HOMELAB_SSH_KNOWN_HOSTS_FILE': str(p)}):
                with self.assertRaises(ValueError): b.protected_file('HOMELAB_SSH_KNOWN_HOSTS_FILE')
                p.chmod(0o600)
                self.assertEqual(b.protected_file('HOMELAB_SSH_KNOWN_HOSTS_FILE'), p.resolve())


if __name__ == '__main__': unittest.main()
