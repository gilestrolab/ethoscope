"""
Network utilities for ethoscope_node.

This module provides network-related utility functions for discovering
and managing network interfaces and IP ranges.
"""

import socket
import ipaddress
import logging
from typing import Optional, List, Tuple
import netifaces


logger = logging.getLogger(__name__)


def get_primary_private_network() -> Optional[str]:
    """
    Get the primary private network range for the current node.
    
    Finds the first private network interface and returns its network
    in CIDR notation (e.g., "192.168.1.0/24").
    
    Returns:
        Network range in CIDR notation, or None if no private network found
    """
    try:
        # Get all network interfaces
        interfaces = netifaces.interfaces()
        
        for interface in interfaces:
            # Skip loopback interface
            if interface == 'lo':
                continue
                
            # Get addresses for this interface
            addrs = netifaces.ifaddresses(interface)
            
            # Check IPv4 addresses
            if netifaces.AF_INET in addrs:
                for addr_info in addrs[netifaces.AF_INET]:
                    ip = addr_info.get('addr')
                    netmask = addr_info.get('netmask')
                    
                    if ip and netmask:
                        try:
                            # Create network object
                            network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                            
                            # Check if this is a private network
                            if network.is_private and not network.is_loopback:
                                logger.info(f"Found private network: {network} on interface {interface}")
                                return str(network)
                                
                        except (ipaddress.AddressValueError, ValueError) as e:
                            logger.debug(f"Invalid network {ip}/{netmask}: {e}")
                            continue
                            
        logger.warning("No private network interfaces found")
        return None
        
    except Exception as e:
        logger.error(f"Error detecting private network: {e}")
        return None


def get_private_ip_pattern() -> str:
    """
    Get a wildcard pattern for SSH config based on the primary private network.
    
    Returns:
        IP pattern suitable for SSH config Host directive (e.g., "192.168.1.*")
        Falls back to "192.168.1.*" if detection fails
    """
    network_cidr = get_primary_private_network()
    
    if network_cidr:
        try:
            network = ipaddress.IPv4Network(network_cidr, strict=False)
            # Convert network to wildcard pattern
            # e.g., 192.168.1.0/24 -> 192.168.1.*
            network_parts = str(network.network_address).split('.')
            
            # For /24 networks, use last octet wildcard
            if network.prefixlen >= 24:
                pattern = f"{'.'.join(network_parts[:3])}.*"
            # For /16 networks, use last two octets wildcard  
            elif network.prefixlen >= 16:
                pattern = f"{'.'.join(network_parts[:2])}.*.*"
            # For /8 networks, use last three octets wildcard
            elif network.prefixlen >= 8:
                pattern = f"{network_parts[0]}.*.*.*"
            else:
                # Very large network, use full wildcard
                pattern = "*.*.*.*"
                
            logger.info(f"Generated IP pattern: {pattern} from network {network_cidr}")
            return pattern
            
        except Exception as e:
            logger.error(f"Error generating IP pattern from {network_cidr}: {e}")
    
    # Fallback to common private network pattern
    logger.warning("Using fallback IP pattern: 192.168.1.*")
    return "192.168.1.*"


def get_local_ip_addresses() -> List[str]:
    """
    Get all local IP addresses for this node.
    
    Returns:
        List of IP addresses assigned to local interfaces
    """
    addresses = []
    
    try:
        interfaces = netifaces.interfaces()
        
        for interface in interfaces:
            addrs = netifaces.ifaddresses(interface)
            
            if netifaces.AF_INET in addrs:
                for addr_info in addrs[netifaces.AF_INET]:
                    ip = addr_info.get('addr')
                    if ip and ip != '127.0.0.1':
                        addresses.append(ip)
                        
    except Exception as e:
        logger.error(f"Error getting local IP addresses: {e}")
    
    return addresses


def is_ip_in_local_network(ip: str) -> bool:
    """
    Check if an IP address is in the same network as this node.
    
    Args:
        ip: IP address to check
        
    Returns:
        True if IP is in local network, False otherwise
    """
    network_cidr = get_primary_private_network()
    
    if not network_cidr:
        return False
        
    try:
        network = ipaddress.IPv4Network(network_cidr, strict=False)
        target_ip = ipaddress.IPv4Address(ip)
        
        return target_ip in network
        
    except (ipaddress.AddressValueError, ValueError) as e:
        logger.error(f"Error checking IP {ip} against network {network_cidr}: {e}")
        return False