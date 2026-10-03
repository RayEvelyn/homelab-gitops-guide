"""Offline API fixtures: no network, tokens, infrastructure or subprocess apply."""
import contextlib
import copy
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('preflight', Path(__file__).resolve().parents[1] / 'scripts/preflight.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class Capacity(unittest.TestCase):
    def setUp(self):
        self.c = {'reserve_memory_mb': 2048, 'reserve_storage_gib': 20, 'cpu_overcommit_ratio': 1,
                  'components': [{'name': 'gitlab', 'node': 'pve', 'storage': 'local-lvm', 'cpu_cores': 4,
                                  'memory_mb': 8192, 'disk_gib': 80, 'lab_hostname': 'gitlab.example.test',
                                  'terraform_inputs': {'vm_id': 250, 'template_id': 9000, 'vm_name': 'gitlab',
                                                       'bridge': 'vmbr0', 'ip_cidr': '192.0.2.50/24'}}]}
        self.data = {'/cluster/resources?type=vm': [], '/nodes/pve/status': {'memory': {'total': 32 * p.GIB, 'used': 8 * p.GIB}, 'cpuinfo': {'cpus': 8}},
                     '/nodes/pve/qemu': [], '/nodes/pve/lxc': [],
                     '/nodes/pve/qemu/9000/config': {'template': 1, 'scsi0': 'local-lvm:vm-9000-disk-0,size=80G'},
                     '/nodes/pve/network': [{'iface': 'vmbr0', 'type': 'bridge'}],
                     '/nodes/pve/storage/local-lvm/status': {'active': 1, 'content': 'images', 'avail': 200 * p.GIB}}

    def run_check(self, phase='allocation'):
        class Fake:
            def get(_, path):
                return copy.deepcopy(self.data[path])
        with patch.object(p.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('192.0.2.50', 0))]), contextlib.redirect_stdout(io.StringIO()):
            p.inspect(Fake(), self.c, phase, False, False)

    def test_new_vm_with_capacity(self):
        self.run_check()

    def test_ram_reserve_failure(self):
        self.data['/nodes/pve/status']['memory']['total'] = 16 * p.GIB
        with self.assertRaisesRegex(p.PreflightError, 'RAM'):
            self.run_check()

    def test_cpu_policy_failure(self):
        self.data['/nodes/pve/status']['cpuinfo']['cpus'] = 2
        with self.assertRaisesRegex(p.PreflightError, 'vCPUs'):
            self.run_check()

    def test_storage_reserve_failure(self):
        self.data['/nodes/pve/storage/local-lvm/status']['avail'] = 90 * p.GIB
        with self.assertRaisesRegex(p.PreflightError, 'storage capacity'):
            self.run_check()

    def test_template_disk_mismatch_failure(self):
        self.data['/nodes/pve/qemu/9000/config']['scsi0'] = 'local-lvm:disk,size=20G'
        with self.assertRaisesRegex(p.PreflightError, 'disk_gib'):
            self.run_check()

    def test_existing_vm_not_double_counted(self):
        self.data['/nodes/pve/qemu'] = [{'vmid': 250, 'status': 'running', 'maxmem': 8 * p.GIB, 'cpus': 4}]
        self.data['/nodes/pve/qemu/250/config'] = {'name': 'gitlab', 'memory': 8192, 'cores': 4, 'scsi0': 'local-lvm:disk,size=80G'}
        self.data['/nodes/pve/storage/local-lvm/status']['avail'] = 25 * p.GIB
        self.run_check('refresh')

    def test_unrelated_vm_id_refused(self):
        self.data['/nodes/pve/qemu'] = [{'vmid': 250, 'status': 'running', 'maxmem': 8 * p.GIB, 'cpus': 4}]
        self.data['/nodes/pve/qemu/250/config'] = {'name': 'another-service', 'scsi0': 'local-lvm:disk,size=80G'}
        with self.assertRaisesRegex(p.PreflightError, 'another name'):
            self.run_check()

    def test_refresh_requires_existing(self):
        with self.assertRaisesRegex(p.PreflightError, 'exist already'):
            self.run_check('refresh')

    def test_shared_pool_is_aggregated_across_nodes(self):
        second = copy.deepcopy(self.c['components'][0]); second['node'] = 'pve2'
        second['terraform_inputs'].update(vm_id=251, template_id=9001)
        self.c['components'].append(second)
        for key, value in list(self.data.items()):
            if key.startswith('/nodes/pve/'):
                self.data[key.replace('/nodes/pve/', '/nodes/pve2/').replace('/9000/', '/9001/')] = copy.deepcopy(value)
        for node in ['pve', 'pve2']:
            self.data[f'/nodes/{node}/storage/local-lvm/status'].update(shared=1, avail=170 * p.GIB)
        with self.assertRaisesRegex(p.PreflightError, 'Combined'):
            self.run_check()

    def test_missing_running_guest_capacity_fails_closed(self):
        self.data['/nodes/pve/qemu'] = [{'vmid': 300, 'status': 'running'}]
        with self.assertRaises(KeyError):
            self.run_check()

    def test_nonfinite_node_ram_fails(self):
        self.data['/nodes/pve/status']['memory']['used'] = float('nan')
        with self.assertRaisesRegex(p.PreflightError, 'finite'):
            self.run_check()

    def test_clusterwide_id_collision_fails(self):
        self.data['/cluster/resources?type=vm'] = [{'vmid': 250, 'type': 'qemu', 'node': 'other'}]
        with self.assertRaisesRegex(p.PreflightError, 'elsewhere'):
            self.run_check()

    def test_refresh_resource_increase_fails(self):
        self.data['/nodes/pve/qemu'] = [{'vmid': 250, 'status': 'running', 'maxmem': 4 * p.GIB, 'cpus': 2}]
        self.data['/nodes/pve/qemu/250/config'] = {'name': 'gitlab', 'memory': 4096, 'cores': 2, 'scsi0': 'local-lvm:disk,size=80G'}
        with self.assertRaisesRegex(p.PreflightError, 'Refresh refuses'):
            self.run_check('refresh')

    def test_lxc_allocations_reduce_available(self):
        self.data['/nodes/pve/lxc'] = [{'vmid': 300, 'status': 'running', 'maxmem': 24 * p.GIB, 'cpus': 2}]
        with self.assertRaisesRegex(p.PreflightError, 'RAM'):
            self.run_check()


if __name__ == '__main__':
    unittest.main()
