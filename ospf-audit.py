#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSPF аудит MikroTik (ROS v6/v7): сбор соседей и стоимостей, построение графа, отчёт.

Запуск:
  python3 /usr/local/bin/ospf-audit.py --out-dir /var/tmp

Выходные файлы:
  ospf_topology.dot
  ospf_topology.svg  (если установлен graphviz `dot`)
  ospf_report.json
"""
import os
import re
import sys
import json
import csv
import subprocess
from fnmatch import fnmatch
from dataclasses import dataclass, field
import ipaddress
from typing import Dict, List, Tuple, Set, Optional, Any
from argparse import ArgumentParser

CONFIG_PATH = '/etc/infra/config.json'

# === Базовые утилиты из sync-lists.py ===

def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_map(map_file: str) -> Dict[str, str]:
    ip_to_name: Dict[str, str] = {}
    with open(map_file, 'r', encoding='utf-8') as f:
        first = f.readline()
        f.seek(0)
        if '|' in first:
            for line in f:
                line = line.strip()
                if not line or '|' not in line:
                    continue
                ip, name = line.split('|', 1)
                ip_to_name[ip.strip()] = name.strip()
        else:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 2:
                    continue
                identity = (row[0] or '').strip()
                ip = (row[1] or '').strip()
                if not ip or ip.lower() == 'ip':
                    continue
                ip_to_name[ip] = identity or ip
    return ip_to_name


def ssh_cmd(ip: str, cmd: str, ssh_user: str, ssh_key: str, timeout_sec: int = 20) -> Tuple[int, str, str]:
    ssh_command = [
        'ssh',
        '-i', ssh_key,
        '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/root/.ssh/known_hosts',
        '-o', 'PreferredAuthentications=publickey',
        '-o', 'PasswordAuthentication=no',
        '-o', 'KbdInteractiveAuthentication=no',
        '-o', 'ConnectTimeout=8',
        '-o', 'ConnectionAttempts=1',
        '-o', 'ServerAliveInterval=5',
        '-o', 'ServerAliveCountMax=2',
        f'{ssh_user}@{ip}',
        cmd
    ]
    try:
        p = subprocess.run(ssh_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
        return p.returncode, p.stdout.decode('utf-8', 'ignore'), p.stderr.decode('utf-8', 'ignore')
    except subprocess.TimeoutExpired:
        return 124, '', f'Timeout after {timeout_sec}s'
    except Exception as e:
        return 255, '', f'Exception: {e}'

# === Доменные типы ===

@dataclass
class IfCost:
    interface: str
    cost: Optional[int]
    area: Optional[str] = None
    networks: List[str] = field(default_factory=list)

@dataclass
class Neighbor:
    router_id: Optional[str]
    address: Optional[str]
    interface: Optional[str]
    state: Optional[str]

@dataclass
class RouterInfo:
    mgmt_ip: str
    identity: str
    ros_version: str
    ros_major: int
    router_id: Optional[str]
    if_costs: Dict[str, IfCost] = field(default_factory=dict)
    neighbors: List[Neighbor] = field(default_factory=list)
    diags: List[str] = field(default_factory=list)
    addresses: Set[str] = field(default_factory=set)
    if_nets: Dict[str, List[str]] = field(default_factory=dict)

@dataclass
class Edge:
    a_id: str
    b_id: str
    a_if: Optional[str] = None
    b_if: Optional[str] = None
    a_cost: Optional[int] = None
    b_cost: Optional[int] = None
    problems: List[str] = field(default_factory=list)

    def label(self) -> str:
        ac = '?' if self.a_cost is None else str(self.a_cost)
        bc = '?' if self.b_cost is None else str(self.b_cost)
        return f'{ac}/{bc}'

# === Парсинг ===

KV_RE = re.compile(r"(\S+?)=\"([^\"]*)\"|(\S+?)=(\S+)")
BLANK_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n+")

def find_kv_pairs(s: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in KV_RE.finditer(s):
        k = m.group(1) or m.group(3)
        v = m.group(2) or m.group(4)
        out[k] = v
    return out


def grep_val(pattern: str, s: str) -> Optional[str]:
    m = re.search(pattern, s, re.IGNORECASE)
    return m.group(1).strip() if m else None

# Парсинг адресов интерфейсов (в духе sync-lists.py)
ADDRESS_RE = re.compile(r'address=([0-9.]+)/[0-9]{1,2}')
ADDRESS_COL_RE = re.compile(r'^\s*(?:\d+\s+)?([0-9]{1,3}(?:\.[0-9]{1,3}){3})/\d{1,2}\b')

def parse_ip_address_detail(raw: str) -> Set[str]:
    res: Set[str] = set()
    for line in raw.splitlines():
        m = ADDRESS_RE.search(line)
        if m:
            res.add(m.group(1))
    return res

def parse_ip_address_table(raw: str) -> Set[str]:
    res: Set[str] = set()
    for line in raw.splitlines():
        m = ADDRESS_COL_RE.search(line)
        if m:
            res.add(m.group(1))
    return res

def get_all_addresses(router_ip: str, ssh_user: str, ssh_key: str) -> Tuple[Set[str], List[str]]:
    diags: List[str] = []
    variants = [
        '/ip address print detail without-paging',
        '/ip address print detail',
        '/ip address print',
    ]
    for cmd in variants:
        rc, out, err = ssh_cmd(router_ip, cmd, ssh_user, ssh_key)
        if rc != 0:
            diags.append(f"cmd='{cmd}' rc={rc} {err.strip()}")
            continue
        s_detail = parse_ip_address_detail(out)
        if s_detail:
            return s_detail, diags
        s_table = parse_ip_address_table(out)
        if s_table:
            return s_table, diags
        diags.append(f"cmd='{cmd}' -> no address parsed")
    return set(), diags

def get_if_networks(router_ip: str, ssh_user: str, ssh_key: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """Возвращает карту интерфейс -> список CIDR из /ip address print detail."""
    diags: List[str] = []
    nets: Dict[str, List[str]] = {}
    for cmd in [
        '/ip address print detail without-paging',
        '/ip address print detail',
    ]:
        rc, out, err = ssh_cmd(router_ip, cmd, ssh_user, ssh_key)
        if rc != 0:
            diags.append(f"cmd='{cmd}' rc={rc} {err.strip()}")
            continue
        cnt = 0
        for block in BLANK_BLOCK_SPLIT_RE.split(out.strip()):
            if not block.strip():
                continue
            kv_all: Dict[str, str] = {}
            for line in block.splitlines():
                if not line.strip():
                    continue
                kv = find_kv_pairs(line)
                if kv:
                    kv_all.update(kv)
            iface = kv_all.get('interface')
            addr = kv_all.get('address')  # вида 10.10.30.1/24
            if iface and addr and '/' in addr:
                nets.setdefault(iface, []).append(addr)
                cnt += 1
        if cnt:
            diags.append(f"if_nets_parsed={cnt} via '{cmd}'")
            break
    return nets, diags

# === Опрос роутера ===

def get_ros_version(ip: str, ssh_user: str, ssh_key: str) -> Tuple[str, int, List[str]]:
    diags: List[str] = []
    rc, out, err = ssh_cmd(ip, '/system resource print', ssh_user, ssh_key)
    if rc == 0:
        ver = grep_val(r'version[:=]\s*([0-9]+\.[0-9A-Za-z.\-]+)', out)
        if ver:
            try:
                major = int(ver.split('.')[0])
            except Exception:
                major = 0
            return ver, major, diags
        diags.append('resource_print_no_version')
    else:
        diags.append(f'resource_print_rc={rc} {err.strip()}')
    rc, out, err = ssh_cmd(ip, '/system package print where name=routeros', ssh_user, ssh_key)
    if rc == 0:
        ver = grep_val(r'version[:=]\s*([0-9]+\.[0-9A-Za-z.\-]+)', out)
        if ver:
            try:
                major = int(ver.split('.')[0])
            except Exception:
                major = 0
            return ver, major, diags
        diags.append('package_print_no_version')
    else:
        diags.append(f'package_print_rc={rc} {err.strip()}')
    return 'unknown', 0, diags


def get_identity(ip: str, ssh_user: str, ssh_key: str, fallback: str) -> Tuple[str, List[str]]:
    diags: List[str] = []
    rc, out, err = ssh_cmd(ip, '/system identity print', ssh_user, ssh_key)
    if rc == 0:
        name = grep_val(r'name[:=]\s*([^\r\n]+)', out)
        if name:
            return name, diags
        diags.append('identity_parse_fail')
    else:
        diags.append(f'identity_rc={rc} {err.strip()}')
    return fallback, diags


def get_router_id(ip: str, ssh_user: str, ssh_key: str) -> Tuple[Optional[str], List[str]]:
    diags: List[str] = []
    for cmd in [
        '/routing ospf instance print detail without-paging',
        '/routing ospf instance print detail',
        '/routing ospf instance print',
    ]:
        rc, out, err = ssh_cmd(ip, cmd, ssh_user, ssh_key)
        if rc != 0:
            diags.append(f"cmd='{cmd}' rc={rc} {err.strip()}")
            continue
        rid = grep_val(r'router-id[:=]\s*([0-9.]+)', out)
        if rid:
            return rid, diags
    diags.append('router_id_not_found')
    return None, diags


def get_ospf_neighbors(ip: str, ssh_user: str, ssh_key: str) -> Tuple[List[Neighbor], List[str]]:
    diags: List[str] = []
    neighbors: List[Neighbor] = []

    def pick(patterns: List[str], text: str) -> Optional[str]:
        for pat in patterns:
            v = grep_val(pat, text)
            if v:
                return v
        return None

    for cmd in [
        '/routing ospf neighbor print detail without-paging',
        '/routing ospf neighbor print detail',
        '/routing ospf neighbor print',
    ]:
        rc, out, err = ssh_cmd(ip, cmd, ssh_user, ssh_key)
        if rc != 0:
            diags.append(f"cmd='{cmd}' rc={rc} {err.strip()}")
            continue
        cnt = 0
        for block in BLANK_BLOCK_SPLIT_RE.split(out.strip()):
            if not block.strip():
                continue
            rid = pick([r'router-id[:=]\s*([0-9.]+)'], block)
            addr = pick([r'address[:=]\s*([0-9.]+)'], block)
            iface = pick([r'interface[:=]\s*"([^"\r\n]+)"', r'interface[:=]\s*([^\s\r\n]+)'], block)
            state = pick([r'(?:state|status)[:=]\s*([^\r\n]+)'], block)
            neighbors.append(Neighbor(router_id=rid, address=addr, interface=iface, state=state))
            cnt += 1
        if cnt:
            diags.append(f"neighbors_parsed={cnt} via '{cmd}'")
            break
    return neighbors, diags


def get_ospf_interface_costs(ip: str, ssh_user: str, ssh_key: str) -> Tuple[Dict[str, IfCost], List[str]]:
    diags: List[str] = []
    costs: Dict[str, IfCost] = {}

    def split_names(s: str) -> List[str]:
        s = (s or '').strip()
        if not s:
            return []
        # Разделители: запятая и/или пробел
        parts = re.split(r"[,\s]+", s)
        return [p for p in parts if p]

    def parse_blocks(out: str) -> int:
        cnt = 0
        if not out.strip():
            return 0
        for block in BLANK_BLOCK_SPLIT_RE.split(out.strip()):
            if not block.strip():
                continue
            kv_all: Dict[str, str] = {}
            for line in block.splitlines():
                if not line.strip():
                    continue
                kv = find_kv_pairs(line)
                if kv:
                    kv_all.update(kv)
            iface_field = kv_all.get('interface') or kv_all.get('interfaces') or kv_all.get('name')
            area = kv_all.get('area') or kv_all.get('area-id')
            cost_s = kv_all.get('cost')
            nets_field = kv_all.get('networks') or kv_all.get('network')
            nets = split_names(nets_field) if nets_field else []
            try:
                icost = int(cost_s) if (cost_s is not None) else None
            except Exception:
                icost = None
            if not iface_field:
                continue
            for iface in split_names(iface_field):
                costs[iface] = IfCost(interface=iface, cost=icost, area=area, networks=nets)
                cnt += 1
        return cnt

    for cmd in [
        '/routing ospf interface print detail without-paging',
        '/routing ospf interface print detail',
        '/routing ospf interface print',
        '/routing ospf interface-template print detail without-paging',
        '/routing ospf interface-template print detail',
        '/routing ospf interface-template print',
    ]:
        rc, out, err = ssh_cmd(ip, cmd, ssh_user, ssh_key)
        if rc != 0:
            diags.append(f"cmd='{cmd}' rc={rc} {err.strip()}")
            continue
        got = parse_blocks(out)
        if got:
            diags.append(f"interfaces_parsed={got} via '{cmd}'")
            break
    return costs, diags

# === Топология и анализ ===

def _resolve_cost_for_iface(ri: RouterInfo, iface: Optional[str]) -> Optional[int]:
    if not iface:
        return None
    ic = ri.if_costs.get(iface)
    if ic and ic.cost is not None:
        return ic.cost
    # fallback: шаблоны/маски и 'all'
    ic_all = ri.if_costs.get('all')
    if ic_all and ic_all.cost is not None:
        return ic_all.cost
    for k, v in ri.if_costs.items():
        if '*' in k and fnmatch(iface, k) and v.cost is not None:
            return v.cost
    for k, v in ri.if_costs.items():
        if k != 'all' and iface.startswith(k) and v.cost is not None:
            return v.cost
    return None

def _resolve_cost_for_address(ri: RouterInfo, addr: Optional[str]) -> Optional[int]:
    if not addr:
        return None
    try:
        ip = ipaddress.ip_address(addr)
    except Exception:
        return None
    best: Optional[int] = None
    # Ищем интерфейсы/шаблоны, сеть которых содержит адрес соседа
    for ifname, ifc in ri.if_costs.items():
        for net in ifc.networks:
            try:
                if ip in ipaddress.ip_network(net, strict=False):
                    if ifc.cost is not None:
                        best = ifc.cost
                        break
            except Exception:
                continue
        if best is not None:
            break
    # Fallback: 'all'
    if best is None:
        ic_all = ri.if_costs.get('all')
        if ic_all and ic_all.cost is not None:
            best = ic_all.cost
    return best

def _guess_iface_by_peer_name(ri: RouterInfo, peer_identity: str, prefer_cost: Optional[int] = None) -> Optional[str]:
    """Подбирает интерфейс по токенам из имени удалённого роутера.
    Сначала ищет совпадение токена в названии интерфейса, затем (если задано) единственный интерфейс с нужной стоимостью.
    """
    name = (peer_identity or '').lower()
    tokens = [t for t in re.split(r'[^a-z0-9]+', name) if len(t) >= 2]
    if tokens:
        # Сортируем по длине токена, длиннее — приоритетнее
        tokens.sort(key=len, reverse=True)
        for ifname in ri.if_costs.keys():
            low = ifname.lower()
            if any(tok in low for tok in tokens):
                return ifname
    if prefer_cost is not None:
        cands = [ifn for ifn, ic in ri.if_costs.items() if ic.cost == prefer_cost]
        if len(cands) == 1:
            return cands[0]
    return None

def build_edges(routers: Dict[str, RouterInfo]) -> List[Edge]:
    rid2id: Dict[str, str] = {r.router_id: r.identity for r in routers.values() if r.router_id}
    # Доп. сопоставление по IP-адресам интерфейсов и mgmt_ip
    addr2id: Dict[str, str] = {}
    for r in routers.values():
        addr2id.setdefault(r.mgmt_ip, r.identity)
        for ip in r.addresses:
            addr2id.setdefault(ip, r.identity)
    pairs: Dict[Tuple[str, str], Edge] = {}

    for r in routers.values():
        for nb in r.neighbors:
            if not nb.router_id:
                continue
            other = rid2id.get(nb.router_id)
            if (not other) and nb.address:
                # Попытка сопоставить по адресу соседа
                try:
                    nb_ip = nb.address.split('/')[0]
                except Exception:
                    nb_ip = nb.address
                other = addr2id.get(nb_ip)
            if not other:
                continue
            a, b = sorted([r.identity, other])
            key = (a, b)
            e = pairs.get(key)
            # Сначала пытаемся по имени интерфейса, затем по адресу соседа через сети интерфейса
            cost_here = _resolve_cost_for_iface(r, nb.interface)
            if cost_here is None:
                # извлекаем чистый IP без маски
                nb_ip = None
                if nb.address:
                    nb_ip = nb.address.split('/')[0]
                cost_here = _resolve_cost_for_address(r, nb_ip)
            if not e:
                e = Edge(a_id=a, b_id=b)
                pairs[key] = e
            # Уточняем интерфейс: если не пришёл из соседей — пытаемся найти по адресу соседа и локальным сетям
            iface_here = nb.interface if nb.interface else None
            if iface_here is None and nb.address:
                nb_ip = nb.address.split('/')[0]
                try:
                    ip_obj = ipaddress.ip_address(nb_ip)
                except Exception:
                    ip_obj = None
                if ip_obj is not None:
                    for ifname, nets in r.if_nets.items():
                        for cidr in nets:
                            try:
                                if ip_obj in ipaddress.ip_network(cidr, strict=False):
                                    iface_here = ifname
                                    break
                            except Exception:
                                continue
                        if iface_here is not None:
                            break
            # fallback по имени удалённого узла
            if iface_here is None:
                iface_here = _guess_iface_by_peer_name(r, other, cost_here)
            if r.identity == a:
                if e.a_cost is None:
                    e.a_cost = cost_here
                if e.a_if is None and iface_here is not None:
                    e.a_if = iface_here
            else:
                if e.b_cost is None:
                    e.b_cost = cost_here
                if e.b_if is None and iface_here is not None:
                    e.b_if = iface_here
            state_lower = nb.state.lower() if nb.state else ''
            if state_lower and not state_lower.startswith('full'):
                e.problems.append('neighbor_not_full')

    edges = list(pairs.values())
    for e in edges:
        if (e.a_cost is not None) and (e.b_cost is not None) and (e.a_cost != e.b_cost):
            e.problems.append('asymmetric_cost')
    return edges


def make_recommendations(edges: List[Edge]) -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    # Если стоимости равны или отсутствует одна из сторон, предложим повысить cost на «запасном» линке на +1.
    for e in edges:
        if e.a_cost is None or e.b_cost is None:
            # нет данных — пропуск
            continue
        if e.a_cost == e.b_cost:
            # Выбираем сторону для повышения cost: по умолчанию B, иначе A, если у B нет интерфейса
            side = 'b' if e.b_if else ('a' if e.a_if else None)
            if side is None:
                # нет интерфейсов на обеих сторонах — рекомендацию дать невозможно
                continue
            if side == 'b':
                target_cost = e.b_cost + 1
                v6_cmd = f"/routing ospf interface set [ find where interface=\"{e.b_if}\" ] cost={target_cost}" if e.b_if else None
                v7_cmd = f"/routing ospf interface-template set [ find where interfaces=\"{e.b_if}\" ] cost={target_cost}" if e.b_if else None
                suggested = {'a': None, 'b': target_cost}
            else:
                target_cost = e.a_cost + 1
                v6_cmd = f"/routing ospf interface set [ find where interface=\"{e.a_if}\" ] cost={target_cost}" if e.a_if else None
                v7_cmd = f"/routing ospf interface-template set [ find where interfaces=\"{e.a_if}\" ] cost={target_cost}" if e.a_if else None
                suggested = {'a': target_cost, 'b': None}

            recs.append({
                'pair': f'{e.a_id}<->{e.b_id}',
                'reason': 'equal_costs_make_paths_ambiguous',
                'interfaces': {'a_if': e.a_if, 'b_if': e.b_if},
                'suggested_costs': suggested,
                'commands_examples': {
                    'v6': {
                        side: v6_cmd
                    },
                    'v7': {
                        side: v7_cmd
                    }
                }
            })
    return recs

# === Визуализация ===

def to_dot(routers: Dict[str, RouterInfo], edges: List[Edge]) -> str:
    lines = [
        'graph OSPF {',
        '  rankdir=LR;',
        '  fontname="Arial";',
        '  node [shape=ellipse, fontname="Arial", fontsize=10];',
        '  edge [fontname="Arial", fontsize=9];'
    ]
    for r in routers.values():
        rid = r.router_id or 'unknown'
        label = (r.identity + '\n' + rid).replace('"', '\"')
        lines.append(f'  "{r.identity}" [label="{label}"];')
    for e in edges:
        attrs = { 'label': e.label() }
        if 'asymmetric_cost' in e.problems:
            attrs['color'] = 'red'
            attrs['penwidth'] = '2.0'
        elif 'neighbor_not_full' in e.problems:
            attrs['color'] = 'orange'
        attr = ', '.join([f'{k}="{v}"' for k, v in attrs.items()])
        lines.append(f'  "{e.a_id}" -- "{e.b_id}" [{attr}];')
    lines.append('}')
    return '\n'.join(lines)

# === CLI ===

def main():
    ap = ArgumentParser()
    ap.add_argument('--out-dir', default='/var/tmp', help='Каталог для результатов')
    args = ap.parse_args()

    conf = load_config()
    ssh_user = conf['remote_host']['mikrotik']['ssh_user']
    ssh_key = conf['remote_host']['mikrotik']['ssh_key']
    if not os.path.isfile(ssh_key):
        print(f'[FATAL] SSH key not found: {ssh_key}', file=sys.stderr)
        sys.exit(2)

    router_access_ips: List[str] = conf.get('mikrotik', {}).get('router_access_ips', [])
    if not router_access_ips:
        print('[WARN] mikrotik.router_access_ips пуст — нечего опрашивать.')
        return

    ip2name: Dict[str, str] = {}
    map_path = conf.get('paths', {}).get('mikrotik_map')
    if map_path and os.path.isfile(map_path):
        ip2name = load_map(map_path)

    routers: Dict[str, RouterInfo] = {}

    for ip in router_access_ips:
        ver, major, d1 = get_ros_version(ip, ssh_user, ssh_key)
        identity, d2 = get_identity(ip, ssh_user, ssh_key, ip2name.get(ip, ip))
        rid, d3 = get_router_id(ip, ssh_user, ssh_key)
        nbs, d4 = get_ospf_neighbors(ip, ssh_user, ssh_key)
        costs, d5 = get_ospf_interface_costs(ip, ssh_user, ssh_key)
        addrs, d6 = get_all_addresses(ip, ssh_user, ssh_key)
        if_nets, d7 = get_if_networks(ip, ssh_user, ssh_key)
        # Fallback router-id: максимальный IP интерфейса, если router-id пустой/0.0.0.0
        if (not rid or rid == '0.0.0.0') and addrs:
            try:
                def ip_key(s: str):
                    return tuple(int(x) for x in s.split('.'))
                rid = sorted(addrs, key=ip_key)[-1]
                d3.append('router_id_fallback_by_max_ip')
            except Exception:
                pass

        ri = RouterInfo(
            mgmt_ip=ip,
            identity=identity,
            ros_version=ver,
            ros_major=major,
            router_id=rid,
            if_costs=costs,
            neighbors=nbs,
            diags=d1 + d2 + d3 + d4 + d5 + d6 + d7,
            addresses=addrs,
            if_nets=if_nets
        )
        routers[identity] = ri
        print(f"[{ip}] {identity} ROS={ver} RID={rid} nbs={len(nbs)} ifs={len(costs)} addrs={len(addrs)} if_nets={sum(len(v) for v in if_nets.values())}")

    edges = build_edges(routers)
    recs = make_recommendations(edges)

    os.makedirs(args.out_dir, exist_ok=True)
    dot_path = os.path.join(args.out_dir, 'ospf_topology.dot')
    svg_path = os.path.join(args.out_dir, 'ospf_topology.svg')
    json_path = os.path.join(args.out_dir, 'ospf_report.json')

    dot = to_dot(routers, edges)
    with open(dot_path, 'w', encoding='utf-8') as f:
        f.write(dot)

    # Попробуем отрисовать SVG, если установлен graphviz dot
    try:
        p = subprocess.run(['dot', '-Tsvg', dot_path, '-o', svg_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            print(f"[WARN] dot render failed rc={p.returncode}: {p.stderr.decode('utf-8','ignore')[:200]}")
    except FileNotFoundError:
        print('[WARN] graphviz dot не найден — SVG не будет создан.')

    # JSON отчёт
    report = {
        'routers': {
            k: {
                'mgmt_ip': v.mgmt_ip,
                'identity': v.identity,
                'ros_version': v.ros_version,
                'router_id': v.router_id,
                'if_costs': {ik: {'cost': iv.cost, 'area': iv.area} for ik, iv in v.if_costs.items()},
                'neighbors': [vars(nb) for nb in v.neighbors],
                'diags': v.diags,
                'addresses': sorted(list(v.addresses)),
                'if_nets': v.if_nets,
            } for k, v in routers.items()
        },
        'edges': [
            {
                'a': e.a_id,
                'b': e.b_id,
                'a_cost': e.a_cost,
                'b_cost': e.b_cost,
                'a_if': e.a_if,
                'b_if': e.b_if,
                'problems': e.problems,
            } for e in edges
        ],
        'recommendations': recs,
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Готово. DOT: {dot_path}  SVG: {svg_path}  JSON: {json_path}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n[INTERRUPTED] Прервано пользователем.', file=sys.stderr)
        sys.exit(130)
