#!/usr/bin/env python3
"""Read-only Proxmox network/capacity gate. Never prints credentials or API bodies."""
import argparse
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

class PreflightError(ValueError):
    """Only explicitly sanitized public diagnostic messages."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PreflightError('API redirects are refused to protect the authorization header')


MIB = 1024 ** 2
GIB = 1024 ** 3


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise PreflightError(f'{label} must be a positive finite number')
    return value


def config_load(path):
    config = json.loads(Path(path).read_text())
    components = config['components']
    if not isinstance(components, list) or not components:
        raise PreflightError('Select at least one component')
    seen = set()
    for c in components:
        for key in ['name', 'repo', 'node', 'storage']:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', c[key]):
                raise PreflightError('Component identifiers must be simple names')
        inputs = c['terraform_inputs']
        if c['repo'] not in ['gitlab-proxmox-terraform', 'vault-proxmox-lab', 'postgres-flyway-lab', 'powerdns-authoritative-lab', 'powerdns-recursor-lab']:
            raise PreflightError('This single-VM preflight supports the reviewed single-VM GitLab, Vault, Postgres and PowerDNS profiles only')
        for key, tfkey in [('node', 'node_name'), ('storage', 'datastore_id'), ('cpu_cores', 'cores'), ('memory_mb', 'memory_mb')]:
            if c[key] != inputs[tfkey]:
                raise PreflightError(f'Component {key} must match its Terraform input')
        for key in ['cpu_cores', 'memory_mb', 'disk_gib']:
            positive(c[key], key)
        for key in ['vm_id', 'template_id']:
            if not isinstance(inputs[key], int) or inputs[key] <= 0:
                raise PreflightError('VM/template IDs must be positive integers')
        identity = inputs['vm_id']
        if identity in seen or inputs['vm_id'] == inputs['template_id']:
            raise PreflightError('VM IDs must be unique and differ from template IDs')
        seen.add(identity)
        address = ipaddress.ip_interface(inputs['ip_cidr'])
        gateway = ipaddress.ip_address(inputs['gateway'])
        if address.version != 4 or gateway not in address.network or address.ip == gateway:
            raise PreflightError('IPv4 guest/gateway must share the declared subnet and differ')
        if not inputs.get('dns_servers'):
            raise PreflightError('Configure bootstrap DNS servers before deployment')
        for server in inputs['dns_servers']:
            ipaddress.ip_address(server)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]+', c['lab_hostname']):
            raise PreflightError('Configure a valid service DNS hostname')
    for key, default in [('reserve_memory_mb', 2048), ('reserve_storage_gib', 20), ('cpu_overcommit_ratio', 1.0), ('reserve_cpu_cores', 1.0)]:
        config[key] = positive(config.get(key, default), key)
    return config


class API:
    def __init__(self):
        endpoint = os.environ.get('PROXMOX_VE_ENDPOINT', '')
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PreflightError('Set an HTTPS Proxmox endpoint without embedded credentials')
        self.host = parsed.hostname
        self.port = parsed.port or 443
        self.base = endpoint.rstrip('/')
        if not self.base.endswith('/api2/json'):
            self.base += '/api2/json'
        self.token = os.environ.get('PROXMOX_VE_API_TOKEN', '')
        if not self.token or '\n' in self.token or '\r' in self.token:
            raise PreflightError('Set a nonempty Proxmox API token environment value')
        self.context = ssl.create_default_context(cafile=os.environ.get('SSL_CERT_FILE') or None)
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=self.context))

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers={'Authorization': 'PVEAPIToken=' + self.token})
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(4 * MIB + 1)
            if len(raw) > 4 * MIB:
                raise PreflightError('API response exceeds the bounded limit')
            return json.loads(raw)['data']
        except (urllib.error.URLError, json.JSONDecodeError, KeyError):
            raise PreflightError('Read-only Proxmox API/TLS request failed; check trust, route and token permissions') from None


def tcp(host, port):
    try:
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        with socket.create_connection((host, port), timeout=5):
            pass
    except OSError:
        raise PreflightError('DNS/TCP connectivity failed for an explicitly configured endpoint') from None


def disks(config):
    result = defaultdict(float)
    for key, value in config.items():
        if not re.fullmatch(r'(scsi|virtio|sata|ide)\d+', key) or 'media=cdrom' in value or 'cloudinit' in value:
            continue
        store = value.split(':', 1)[0]
        size = re.search(r'(?:^|,)size=(\d+(?:\.\d+)?)([KMGT])(?:,|$)', value)
        if not size:
            raise PreflightError('Cannot account for a template/VM disk: explicit reported size required')
        result[store] += float(size[1]) * {'K': 1024, 'M': MIB, 'G': GIB, 'T': 1024 * GIB}[size[2]]
    if not result:
        raise PreflightError('No writable VM disks found; template accounting unavailable')
    return result


def inspect(api, config, phase, check_guest, gpu):
    allocations = defaultdict(lambda: {'ram': 0, 'cpu': 0, 'storage': defaultdict(float)})
    cluster = api.get('/cluster/resources?type=vm')
    if not isinstance(cluster, list):
        raise PreflightError('Cluster VM inventory is unavailable')
    for item in cluster:
        if not isinstance(item, dict) or not isinstance(item.get('vmid'), int) or not item.get('node') or item.get('type') not in ['qemu', 'lxc']:
            raise PreflightError('Cluster VM inventory lacks required identity fields')
    for component in config['components']:
        collisions = [v for v in cluster if v['vmid'] == component['terraform_inputs']['vm_id']]
        if any(v['node'] != component['node'] or v['type'] != 'qemu' for v in collisions):
            raise PreflightError('VM ID is already allocated elsewhere in the cluster')
    shared_storage = {}
    by_node = defaultdict(list)
    for component in config['components']:
        by_node[component['node']].append(component)
    for node, components in by_node.items():
        path = '/nodes/' + urllib.parse.quote(node, safe='')
        status = api.get(path + '/status')
        qemu = api.get(path + '/qemu')
        lxc = api.get(path + '/lxc')
        hosts = qemu + lxc
        running = [v for v in hosts if v.get('status') == 'running']
        total_ram = positive(status['memory']['total'], 'node total RAM')
        used_ram = status['memory']['used']
        if isinstance(used_ram, bool) or not isinstance(used_ram, (int, float)) or not math.isfinite(used_ram) or used_ram < 0 or used_ram > total_ram:
            raise PreflightError('Node used RAM must be finite, nonnegative and within total')
        for vm in running:
            positive(vm['maxmem'], 'every running guest configured RAM')
            positive(vm['cpus'], 'every running guest vCPUs')
        occupied_ram = max(used_ram, sum(v['maxmem'] for v in running))
        occupied_cpu = sum(v['cpus'] for v in running)
        physical_cpu = positive(status['cpuinfo']['cpus'], 'physical logical CPUs')
        for c in components:
            inputs = c['terraform_inputs']
            found = [v for v in qemu if v['vmid'] == inputs['vm_id']]
            inventory_match = [v for v in cluster if v['vmid'] == inputs['vm_id']]
            if inventory_match and not found:
                raise PreflightError('Selected VM is present in cluster inventory but missing from node inventory')
            template = api.get(path + '/qemu/' + str(inputs['template_id']) + '/config')
            if not template.get('template'):
                raise PreflightError('Clone source is not an actual Proxmox template')
            source_disks = disks(template)
            template_bytes = sum(source_disks.values())
            # These Terraform examples full-clone disks but do not resize them.
            if abs(template_bytes - c['disk_gib'] * GIB) > MIB:
                raise PreflightError('disk_gib must match actual template disks; resize the reviewed template before templating if needed')
            existing = None
            if found:
                existing = api.get(path + '/qemu/' + str(inputs['vm_id']) + '/config')
                if existing.get('name') != inputs['vm_name'] or existing.get('template'):
                    raise PreflightError('Selected VM ID already belongs to another name/template; refusing')
                if phase == 'refresh':
                    configured_ram = positive(existing['memory'], 'existing configured memory')
                    configured_cpu = positive(existing['cores'], 'existing configured cores') * positive(existing.get('sockets', 1), 'existing configured sockets')
                    if c['memory_mb'] > configured_ram or c['cpu_cores'] > configured_cpu:
                        raise PreflightError('Refresh refuses positive RAM/CPU allocation changes; use allocation preflight')
            elif phase == 'refresh':
                raise PreflightError('Refresh requires the selected VM to exist already')
            current_disks = disks(existing) if existing else {}
            if current_disks and (set(current_disks) != {c['storage']} or abs(sum(current_disks.values()) - template_bytes) > MIB):
                raise PreflightError('Existing VM disk allocation differs from selected storage/template; review independently')
            is_running = bool(found and found[0].get('status') == 'running')
            current_ram = float(found[0].get('maxmem', 0)) if is_running else 0
            current_cpu = float(found[0].get('cpus', 0)) if is_running else 0
            allocations[node]['ram'] += max(0, c['memory_mb'] * MIB - current_ram)
            allocations[node]['cpu'] += max(0, c['cpu_cores'] - current_cpu)
            allocations[node]['storage'][c['storage']] += max(0, template_bytes - sum(current_disks.values()))
            networks = api.get(path + '/network')
            if not any(n.get('iface') == inputs['bridge'] and n.get('type') in ['bridge', 'OVSBridge'] for n in networks):
                raise PreflightError('Selected VM bridge does not exist on the Proxmox node')
            try:
                resolved = {x[4][0] for x in socket.getaddrinfo(c['lab_hostname'], None, type=socket.SOCK_STREAM)}
            except OSError:
                raise PreflightError('Service hostname must resolve through bootstrap DNS before deployment') from None
            if str(ipaddress.ip_interface(inputs['ip_cidr']).ip) not in resolved:
                raise PreflightError('Service DNS does not resolve to the declared guest address')
            if check_guest:
                if not existing:
                    raise PreflightError('Guest SSH check is only valid after provisioning')
                tcp(str(ipaddress.ip_interface(inputs['ip_cidr']).ip), 22)
        available_ram = total_ram - occupied_ram - config['reserve_memory_mb'] * MIB
        if allocations[node]['ram'] > available_ram:
            raise PreflightError('Insufficient conservative node RAM after configured reserve')
        if occupied_cpu + allocations[node]['cpu'] + config.get('reserve_cpu_cores', 1.0) > physical_cpu * config['cpu_overcommit_ratio']:
            raise PreflightError('Planned running vCPUs exceed the explicit overcommit policy')
        for storage, added in allocations[node]['storage'].items():
            info = api.get(path + '/storage/' + urllib.parse.quote(storage, safe='') + '/status')
            if not info.get('active') or 'images' not in info.get('content', '').split(','):
                raise PreflightError('Selected storage is not active VM-image storage')
            if added + config['reserve_storage_gib'] * GIB > float(info['avail']):
                raise PreflightError('Insufficient selected storage capacity after reserve')
            if info.get('shared'):
                pooled = shared_storage.setdefault(storage, {'added': 0, 'avail': float(info['avail'])})
                pooled['added'] += added
                pooled['avail'] = min(pooled['avail'], float(info['avail']))
            remaining = (float(info['avail']) - added - config['reserve_storage_gib'] * GIB) / GIB
            print(f'{node}: storage {storage}, additional {added / GIB:.1f} GiB, free after allocation/reserve {remaining:.1f} GiB')
        print(f'{node}: additional RAM {allocations[node]["ram"] / GIB:.1f} GiB, free after allocation/reserve {(available_ram - allocations[node]["ram"]) / GIB:.1f} GiB; running/planned vCPUs {occupied_cpu + allocations[node]["cpu"]:g}/{physical_cpu:g}; reserve {config["reserve_memory_mb"]:.0f} MiB, CPU ratio {config["cpu_overcommit_ratio"]:g}, host CPU reserve {config.get("reserve_cpu_cores", 1):g}')
        if gpu:
            try:
                devices = api.get(path + '/hardware/pci')
                count = sum(1 for d in devices if str(d.get('class', '')).lower().startswith('0x03') or str(d.get('class', '')).startswith('03'))
                print(f'{node}: {count} PCI display-class devices observed; VRAM, IOMMU, passthrough and compute compatibility UNKNOWN')
            except ValueError:
                print(f'{node}: optional GPU inventory unavailable; compute suitability UNKNOWN')
    for storage, pooled in shared_storage.items():
        if pooled['added'] + config['reserve_storage_gib'] * GIB > pooled['avail']:
            raise PreflightError('Combined selected-node allocations exceed shared storage capacity')
    print('Read-only preflight passed. Network reachability is not SSH host authentication, backup recovery or workload readiness.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--phase', choices=['allocation', 'refresh'], default='allocation')
    parser.add_argument('--check-guest-ssh', action='store_true')
    parser.add_argument('--gpu-inventory', action='store_true')
    args = parser.parse_args()
    try:
        config = config_load(args.config)
        api = API()
        tcp(api.host, api.port)
        inspect(api, config, args.phase, args.check_guest_ssh, args.gpu_inventory)
    except (ValueError, KeyError, TypeError, OSError) as error:
        # Only our sanitized messages are emitted; never raw API response/credentials.
        print('Preflight failed: ' + (str(error) if isinstance(error, PreflightError) else 'Configuration or required capacity data is missing/invalid'), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
