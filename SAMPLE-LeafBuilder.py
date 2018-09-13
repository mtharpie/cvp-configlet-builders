from cvplibrary import CVPGlobalVariables as cvp_vars
from cvplibrary import GlobalVariableNames as cvp_names
from cvplibrary import RestClient
from cvplibrary import Form

import netaddr
import jsonrpclib
import json
import requests

# Set Form Variables and static
lo0 = Form.getFieldById('lo0').getValue()
lo0 = netaddr.IPNetwork('%s/32' % lo0)
lo1 = Form.getFieldById('lo1').getValue()
lo1 = netaddr.IPNetwork('%s/32' % lo1)
lo1_sec = Form.getFieldById('lo1_sec').getValue()
lo1_sec = netaddr.IPNetwork('%s/32' % lo1_sec)
mlag_subnet = Form.getFieldById('mlag_subnet').getValue()
mlag_subnet = netaddr.IPNetwork(mlag_subnet)
leaf_asn = Form.getFieldById('leaf_asn').getValue()
spine_asn = Form.getFieldById('spine_asn').getValue()
mac = cvp_vars.getValue(cvp_names.CVP_MAC)
routed_ints = list()
routed_ints.append('Ethernet2')
routed_ints.append('Ethernet3')
mlag_peer_ints = list()
mlag_peer_ints.append('Ethernet1')
mlag_ints = list()
mlag_ints.append('Ethernet4')

# Functions to build leaf configuration
def get_net_element(system_mac):
    url='http://localhost:8080/cvpservice/provisioning/getNetElementById.do?netElementId=%s' % system_mac
    client = RestClient(url,'GET')
    client.connect()
    node_info = json.loads(client.getResponse())
    return node_info

def get_credentials(ztp=cvp_vars.getValue(cvp_names.ZTP_STATE)):
    if ztp == 'true':
        user = cvp_vars.getValue(cvp_names.ZTP_USERNAME)
        pwd = cvp_vars.getValue(cvp_names.ZTP_PASSWORD)
    else:
        user = cvp_vars.getValue(cvp_names.CVP_USERNAME)
        pwd = cvp_vars.getValue(cvp_names.CVP_PASSWORD)
    return (user, pwd)

def send_command(user, pwd, ip, commands, https=False):
    if https:
        url = 'https://%s:%s@%s/command-api' % (user, pwd, ip)
    else:
        url = 'http://%s:%s@%s/command-api' % (user, pwd, ip)
    sw = jsonrpclib.Server(url)
    result = sw.runCmds(1, commands)
    return result

def get_routed_info(interfaces):
    routed_info = list()
    user, pwd = get_credentials()
    sw_ip = cvp_vars.getValue(cvp_names.CVP_IP)
    commands = ['show lldp neighbors detail']
    lldp_info = send_command(user, pwd, sw_ip, commands)[0]['lldpNeighbors']
    
    for _int in interfaces:
        lldp_neigh = lldp_info[_int]['lldpNeighborInfo'][0]
        neigh_mac = lldp_neigh['chassisId'].replace('.','')
        neigh_mac = ':'.join(a+b for a,b in zip(neigh_mac[::2], neigh_mac[1::2]))
        neigh_int = lldp_neigh['neighborInterfaceInfo']['interfaceId'].replace('"','')
        
        node = get_net_element(neigh_mac)
        _user, _pwd = get_credentials(node['ztpMode'])
        _commands = ['show ip interface %s' % neigh_int]
        int_info = send_command(_user, _pwd, node['ipAddress'], _commands)[0]['interfaces']
        cidr = int_info[neigh_int]['interfaceAddress']['primaryIp']['maskLen']
        neigh_ip = int_info[neigh_int]['interfaceAddress']['primaryIp']['address']
        ip_info = neigh_ip.split('.')
        local_ip = '%s.%s' % ('.'.join(ip_info[:3]), str(int(ip_info[-1])+1))
        
        entry = dict()
        entry['localInt'] = _int
        entry['localIp'] = local_ip
        entry['neighMac'] = neigh_mac
        entry['neighInt'] = neigh_int
        entry['neighIp'] = neigh_ip
        entry['cidr'] = cidr
        entry['systemName'] = node['fqdn'].split('.')[0]
        
        routed_info.append(entry)
        
    return routed_info

# Start of Script
node_info = get_net_element(cvp_vars.getValue(cvp_names.CVP_MAC))
hostname = node_info['fqdn'].split('.')[0]
routed_info = get_routed_info(routed_ints)

num = int(hostname[-1])
mlag_ip = mlag_subnet[2] if num % 2 == 0 else mlag_subnet[1]
mlag_peer = mlag_subnet[1] if num % 2 == 0 else mlag_subnet[2]

print ''
print 'ip routing'
print ''
print 'no spanning-tree vlan 4094'
print ''
print 'vlan 4094'
print '   name MLAG_PEERLINK'
print '   trunk group mlagpeer'
print ''
print 'interface Vlan4094'
print '   description MLAG_SVI'
print '   ip address %s/%s' % (mlag_ip, mlag_subnet.prefixlen)
print ''

for _int in mlag_peer_ints:
  print 'interface %s' % _int
  print '   switchport mode trunk'
  print '   channel-group 10 mode active'
  print ''

for _int in mlag_ints:
  num = _int[-1]
  print 'interface %s' % _int
  print '   channel-group %s mode active' % num
  print ''
for _int in mlag_ints:
  num = _int[-1]
  print 'interface Port-Channel%s' % num
  print '   switchport mode trunk'
  print '   mlag %s' % num
  print ''

  
print 'interface Port-Channe10'
print '   description MLAG-PEERLINK'
print '   switchport mode trunk'
print '   switchport trunk group mlagpeer'
print ''
print 'mlag configuration'
print '   domain-id mlagDomain'
print '   local-interface Vlan4094'
print '   peer-address %s' % mlag_peer
print '   peer-link Port-Channel10'
print ''

for item in routed_info:
  print 'interface %s' % item['localInt']
  print '   description %s_%s' % (item['systemName'], item['neighInt'])
  print '   no switchport'
  print '   ip address %s/%s' % (item['localIp'], item['cidr'])
  print ''
  
print 'interface Loopback0'
print '   ip address %s' % lo0
print ''
print 'interface Loopback1'
print '   description VTEP'
print '   ip address %s' % lo1
print '   ip address %s secondary' % lo1_sec
print ''

print 'router bgp %s' % leaf_asn
print '   router-id %s' % lo0[0]
print '   distance bgp 20 200 200'
print '   maximum-paths 64 ecmp 64'
print '   neighbor spines peer-group'
print '   neighbor spines send-community'
print '   neighbor spines remote-as %s' % spine_asn
for item in routed_info:
  print '   neighbor %s peer-group spines' % item['neighIp']
print '   neighbor %s remote-as %s' % (mlag_peer, leaf_asn)
print '   neighbor %s next-hop-self' % mlag_peer
print '   neighbor %s send-community' % mlag_peer
print '   network %s' % lo0
print '   network %s' % lo1
print '   network %s' % lo1_sec
print ''