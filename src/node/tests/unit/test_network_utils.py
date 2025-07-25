"""
Unit tests for network utility functions.

Tests the network detection and IP pattern generation functionality
used for SSH configuration setup.
"""

import pytest
from unittest.mock import patch, Mock
import ipaddress
from ethoscope_node.utils.network import (
    get_primary_private_network,
    get_private_ip_pattern,
    get_local_ip_addresses,
    is_ip_in_local_network
)


class TestGetPrimaryPrivateNetwork:
    """Test primary private network detection."""
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_detects_192_168_network(self, mock_ifaddresses, mock_interfaces):
        """Test detection of 192.168.x.x network."""
        mock_interfaces.return_value = ['eth0', 'lo']
        mock_ifaddresses.side_effect = [
            {2: [{'addr': '192.168.1.50', 'netmask': '255.255.255.0'}]},  # eth0
            {2: [{'addr': '127.0.0.1', 'netmask': '255.0.0.0'}]}          # lo
        ]
        
        result = get_primary_private_network()
        assert result == "192.168.1.0/24"
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_detects_10_x_network(self, mock_ifaddresses, mock_interfaces):
        """Test detection of 10.x.x.x network."""
        mock_interfaces.return_value = ['eth0']
        mock_ifaddresses.return_value = {
            2: [{'addr': '10.0.5.100', 'netmask': '255.255.0.0'}]
        }
        
        result = get_primary_private_network()
        assert result == "10.0.0.0/16"
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_detects_172_16_network(self, mock_ifaddresses, mock_interfaces):
        """Test detection of 172.16.x.x network."""
        mock_interfaces.return_value = ['eth0']
        mock_ifaddresses.return_value = {
            2: [{'addr': '172.16.10.5', 'netmask': '255.255.255.0'}]
        }
        
        result = get_primary_private_network()
        assert result == "172.16.10.0/24"
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_skips_loopback(self, mock_ifaddresses, mock_interfaces):
        """Test that loopback interface is skipped."""
        mock_interfaces.return_value = ['lo', 'eth0']
        
        def mock_ifaddresses_side_effect(interface):
            if interface == 'lo':
                # Loopback should be skipped by name, so this shouldn't affect result
                return {2: [{'addr': '127.0.0.1', 'netmask': '255.0.0.0'}]}
            elif interface == 'eth0':
                return {2: [{'addr': '192.168.1.50', 'netmask': '255.255.255.0'}]}
            return {}
        
        mock_ifaddresses.side_effect = mock_ifaddresses_side_effect
        
        result = get_primary_private_network()
        assert result == "192.168.1.0/24"
        
        # Verify that ifaddresses was only called for eth0 (lo should be skipped)
        assert mock_ifaddresses.call_count == 1
        mock_ifaddresses.assert_called_with('eth0')
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_skips_public_networks(self, mock_ifaddresses, mock_interfaces):
        """Test that public IP networks are skipped."""
        mock_interfaces.return_value = ['eth0', 'eth1']
        mock_ifaddresses.side_effect = [
            {2: [{'addr': '8.8.8.8', 'netmask': '255.255.255.0'}]},      # public
            {2: [{'addr': '192.168.1.50', 'netmask': '255.255.255.0'}]}  # private
        ]
        
        result = get_primary_private_network()
        assert result == "192.168.1.0/24"
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    def test_returns_none_when_no_interfaces(self, mock_interfaces):
        """Test returns None when no interfaces found."""
        mock_interfaces.return_value = []
        
        result = get_primary_private_network()
        assert result is None
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_handles_missing_netmask(self, mock_ifaddresses, mock_interfaces):
        """Test handles interfaces with missing netmask."""
        mock_interfaces.return_value = ['eth0', 'eth1']
        mock_ifaddresses.side_effect = [
            {2: [{'addr': '192.168.1.50'}]},  # missing netmask
            {2: [{'addr': '10.0.0.5', 'netmask': '255.255.0.0'}]}
        ]
        
        result = get_primary_private_network()
        assert result == "10.0.0.0/16"


class TestGetPrivateIpPattern:
    """Test IP pattern generation for SSH config."""
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_generates_24_bit_pattern(self, mock_get_network):
        """Test pattern generation for /24 networks."""
        mock_get_network.return_value = "192.168.1.0/24"
        
        result = get_private_ip_pattern()
        assert result == "192.168.1.*"
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_generates_16_bit_pattern(self, mock_get_network):
        """Test pattern generation for /16 networks."""
        mock_get_network.return_value = "10.0.0.0/16"
        
        result = get_private_ip_pattern()
        assert result == "10.0.*.*"
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_generates_8_bit_pattern(self, mock_get_network):
        """Test pattern generation for /8 networks."""
        mock_get_network.return_value = "10.0.0.0/8"
        
        result = get_private_ip_pattern()
        assert result == "10.*.*.*"
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_generates_large_network_pattern(self, mock_get_network):
        """Test pattern generation for very large networks."""
        mock_get_network.return_value = "0.0.0.0/4"
        
        result = get_private_ip_pattern()
        assert result == "*.*.*.*"
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_fallback_when_no_network(self, mock_get_network):
        """Test fallback pattern when no network detected."""
        mock_get_network.return_value = None
        
        result = get_private_ip_pattern()
        assert result == "192.168.1.*"
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_fallback_on_invalid_network(self, mock_get_network):
        """Test fallback pattern on invalid network string."""
        mock_get_network.return_value = "invalid-network"
        
        result = get_private_ip_pattern()
        assert result == "192.168.1.*"


class TestGetLocalIpAddresses:
    """Test local IP address collection."""
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_collects_all_addresses(self, mock_ifaddresses, mock_interfaces):
        """Test collection of all local IP addresses."""
        mock_interfaces.return_value = ['eth0', 'eth1', 'lo']
        mock_ifaddresses.side_effect = [
            {2: [{'addr': '192.168.1.50'}]},
            {2: [{'addr': '10.0.0.5'}]},
            {2: [{'addr': '127.0.0.1'}]}  # should be filtered out
        ]
        
        result = get_local_ip_addresses()
        assert '192.168.1.50' in result
        assert '10.0.0.5' in result
        assert '127.0.0.1' not in result
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    @patch('ethoscope_node.utils.network.netifaces.ifaddresses')
    @patch('ethoscope_node.utils.network.netifaces.AF_INET', 2)
    def test_handles_interfaces_without_ipv4(self, mock_ifaddresses, mock_interfaces):
        """Test handles interfaces without IPv4 addresses."""
        mock_interfaces.return_value = ['eth0', 'eth1']
        mock_ifaddresses.side_effect = [
            {},  # no IPv4
            {2: [{'addr': '192.168.1.50'}]}
        ]
        
        result = get_local_ip_addresses()
        assert result == ['192.168.1.50']
    
    @patch('ethoscope_node.utils.network.netifaces.interfaces')
    def test_handles_exception(self, mock_interfaces):
        """Test handles exceptions gracefully."""
        mock_interfaces.side_effect = Exception("Network error")
        
        result = get_local_ip_addresses()
        assert result == []


class TestIsIpInLocalNetwork:
    """Test IP network membership checking."""
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_ip_in_network(self, mock_get_network):
        """Test IP address is in local network."""
        mock_get_network.return_value = "192.168.1.0/24"
        
        result = is_ip_in_local_network("192.168.1.100")
        assert result is True
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_ip_not_in_network(self, mock_get_network):
        """Test IP address is not in local network."""
        mock_get_network.return_value = "192.168.1.0/24"
        
        result = is_ip_in_local_network("10.0.0.1")
        assert result is False
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_no_network_detected(self, mock_get_network):
        """Test when no network is detected."""
        mock_get_network.return_value = None
        
        result = is_ip_in_local_network("192.168.1.100")
        assert result is False
    
    @patch('ethoscope_node.utils.network.get_primary_private_network')
    def test_invalid_ip_address(self, mock_get_network):
        """Test with invalid IP address."""
        mock_get_network.return_value = "192.168.1.0/24"
        
        result = is_ip_in_local_network("invalid-ip")
        assert result is False


class TestNetworkIntegration:
    """Integration tests for network utilities."""
    
    def test_pattern_matches_detected_network(self):
        """Test that generated pattern would match IPs from detected network."""
        # This test runs against actual network interfaces if available
        network = get_primary_private_network()
        pattern = get_private_ip_pattern()
        
        if network:
            # Verify pattern makes sense for the detected network
            net = ipaddress.IPv4Network(network, strict=False)
            
            # Generate a test IP from the network
            test_ip = str(list(net.hosts())[0] if list(net.hosts()) else net.network_address)
            
            # Convert pattern to regex-like check (simple validation)
            pattern_parts = pattern.split('.')
            ip_parts = test_ip.split('.')
            
            for i, (pattern_part, ip_part) in enumerate(zip(pattern_parts, ip_parts)):
                if pattern_part != '*':
                    assert pattern_part == ip_part, f"Pattern {pattern} should match IP {test_ip}"
        else:
            # If no network detected, should use fallback
            assert pattern == "192.168.1.*"