#!/usr/bin/env python3
"""
Script to detect the network IP range/subnet for ethoscope devices.

This script analyzes the network interfaces and determines what IP range
the ethoscopes are likely to be on, which can be used for SSH configuration.
"""

import netifaces
import ipaddress
import socket
import sys
from typing import List, Tuple, Dict, Optional

def get_network_interfaces() -> Dict[str, Dict]:
    """Get all network interfaces with their IP addresses and network information."""
    interfaces = {}

    for interface in netifaces.interfaces():
        if interface.startswith(('lo', 'docker', 'br-')):
            # Skip loopback, docker, and bridge interfaces
            continue

        addr_info = netifaces.ifaddresses(interface)

        # Check for IPv4 addresses
        if netifaces.AF_INET in addr_info:
            ipv4_info = addr_info[netifaces.AF_INET][0]
            ip = ipv4_info.get('addr')
            netmask = ipv4_info.get('netmask')

            if ip and netmask and not ip.startswith('127.'):
                try:
                    # Calculate network from IP and netmask
                    network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                    interfaces[interface] = {
                        'ip': ip,
                        'netmask': netmask,
                        'network': str(network),
                        'network_address': str(network.network_address),
                        'broadcast': str(network.broadcast_address),
                        'hosts': list(network.hosts()) if network.num_addresses <= 256 else f"{network.num_addresses} hosts"
                    }
                except ValueError as e:
                    print(f"Error processing {interface}: {e}")

    return interfaces

def get_default_gateway() -> Optional[str]:
    """Get the default gateway IP address."""
    try:
        gateways = netifaces.gateways()
        default_gateway = gateways.get('default', {}).get(netifaces.AF_INET)
        if default_gateway:
            return default_gateway[0]  # Gateway IP
    except Exception:
        pass
    return None

def determine_ethoscope_networks(interfaces: Dict[str, Dict]) -> List[str]:
    """Determine which networks are likely to contain ethoscopes."""
    candidate_networks = []

    # Common private network ranges for local ethoscope deployments
    common_ranges = [
        '192.168.0.0/16',   # Most common home/lab networks
        '10.0.0.0/8',       # Corporate networks
        '172.16.0.0/12'     # Docker default, some corporate
    ]

    for interface, info in interfaces.items():
        network = ipaddress.IPv4Network(info['network'])

        # Check if this network is in a private range commonly used for ethoscopes
        for common_range in common_ranges:
            common_net = ipaddress.IPv4Network(common_range)
            if network.subnet_of(common_net):
                candidate_networks.append(info['network'])
                break

    return candidate_networks

def generate_ssh_config_patterns(networks: List[str]) -> List[Tuple[str, str]]:
    """Generate SSH config Host patterns for the given networks."""
    patterns = []

    for network in networks:
        net = ipaddress.IPv4Network(network)
        if net.prefixlen >= 24:  # /24 or smaller (fewer hosts)
            # For small networks, we can use a wildcard pattern
            base_ip = str(net.network_address)
            parts = base_ip.split('.')
            pattern = f"{parts[0]}.{parts[1]}.{parts[2]}.*"
            patterns.append((pattern, f"Network: {network}"))
        else:
            # For larger networks, suggest common ethoscope subnets
            base_ip = str(net.network_address)
            parts = base_ip.split('.')
            if net.prefixlen <= 16:  # Very large network
                # Suggest common patterns within the range
                common_subnets = [
                    f"{parts[0]}.{parts[1]}.1.*",
                    f"{parts[0]}.{parts[1]}.2.*",
                    f"{parts[0]}.{parts[1]}.10.*"
                ]
                for subnet in common_subnets:
                    # Check if the subnet is within our network
                    test_ip = subnet.replace('*', '1')
                    try:
                        if ipaddress.IPv4Address(test_ip) in net:
                            patterns.append((subnet, f"Common subnet in {network}"))
                    except:
                        pass
            else:
                # Medium network, suggest /24 subnets
                pattern = f"{parts[0]}.{parts[1]}.{parts[2]}.*"
                patterns.append((pattern, f"Subnet of {network}"))

    return patterns

def main():
    print("Ethoscope Network Range Detection")
    print("=" * 40)

    # Get network interfaces
    interfaces = get_network_interfaces()

    if not interfaces:
        print("No suitable network interfaces found!")
        sys.exit(1)

    print("\nActive Network Interfaces:")
    for interface, info in interfaces.items():
        print(f"  {interface}:")
        print(f"    IP: {info['ip']}")
        print(f"    Network: {info['network']}")
        print(f"    Network Address: {info['network_address']}")
        print(f"    Broadcast: {info['broadcast']}")
        if isinstance(info['hosts'], list) and len(info['hosts']) <= 10:
            print(f"    Host Range: {info['hosts'][0]} - {info['hosts'][-1]}")
        elif isinstance(info['hosts'], list):
            print(f"    Host Range: {info['hosts'][0]} - {info['hosts'][-1]} ({len(info['hosts'])} total hosts)")
        else:
            print(f"    Hosts: {info['hosts']}")
        print()

    # Get default gateway
    gateway = get_default_gateway()
    if gateway:
        print(f"Default Gateway: {gateway}")

    # Determine likely ethoscope networks
    ethoscope_networks = determine_ethoscope_networks(interfaces)

    print(f"\nLikely Ethoscope Networks:")
    if ethoscope_networks:
        for network in ethoscope_networks:
            print(f"  - {network}")
    else:
        print("  No obvious ethoscope networks detected.")
        print("  Ethoscopes are likely on one of the active networks above.")

    # Generate SSH config patterns
    all_networks = ethoscope_networks if ethoscope_networks else [info['network'] for info in interfaces.values()]
    ssh_patterns = generate_ssh_config_patterns(all_networks)

    print(f"\nSuggested SSH Config Host Patterns:")
    for pattern, description in ssh_patterns:
        print(f"  Host {pattern}  # {description}")

    print(f"\nExample SSH Config Entry:")
    primary_pattern = ssh_patterns[0][0] if ssh_patterns else "192.168.1.*"
    print(f"""Host {primary_pattern}
    User ethoscope
    IdentityFile ~/.ssh/ethoscope_key
    StrictHostKeyChecking no
    ConnectTimeout 10""")

    # Show how this was determined
    print(f"\nHow this was determined:")
    print(f"- Used netifaces to enumerate network interfaces")
    print(f"- Filtered out loopback, docker, and bridge interfaces")
    print(f"- Identified private network ranges commonly used for ethoscopes")
    print(f"- Generated wildcard patterns for SSH configuration")

    print(f"\nNote: Ethoscopes use Zeroconf/mDNS for automatic discovery.")
    print(f"They will be discoverable on any network they're connected to.")

if __name__ == "__main__":
    main()
