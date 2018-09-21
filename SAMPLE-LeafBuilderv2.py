# This is a configlet builder for Compute Leaves.
# This will rely on the following items:
#  1. DNS entry must be staged for Management IP
#  2. DNS entry must be staged for Loopback0
#  3. All Spine interfaces configured


from cvplibrary import CVPGlobalVariables as GV
from cvplibrary import GlobalVariableNames as GVN
from cvplibrary import Form
from cvplibrary import RestClient

import socket
import jsonrpclib
import json

def get_credentials(ztp=GV.getValue(GVN.ZTP_STATE)):
  if ztp == 'true':
    user = GV.getValue(GVN.ZTP_USERNAME)
    pwd = GV.getValue(GVN.ZTP_PASSWORD)
  else:
    user = GV.getValue(GVN.CVP_USERNAME)
    pwd = GV.getValue(GVN.CVP_PASSWORD)
  return (user, pwd)

def get_net_element(system_mac):
  url='http://localhost:8080/cvpservice/provisioning/getNetElementById.do?netElementId={0}'.format(system_mac)
  client = RestClient(url, 'GET')
  client.connect()
  node_info = json.loads(client.getResponse())
  return node_info

def send_command(user, pwd, ip, commands):
  url = "https://%s:%s@%s/command-api" % (user, pwd, ip)
  sw = jsonrpclib.Server(url)
  result = sw.runCmds(1, commands)
  return result

def get_leaf_routed_ips(routed_ints):
  user, pwd = get_credentials()
  sw_ip = GV.getValue(GVN.CVP_IP)
  commands = list()
  commands.append('show lldp neighbors detail')
  
  lldp_info = send_command(user, pwd, sw_ip, commands)[0]['lldpNeighbors']
  
  neighbors = dict()
  for rint in routed_ints:
    sw_name = lldp_info[rint]['lldpNeighborInfo'][0]['systemName'].split('.')[0]
    sw_mac = lldp_info[rint]['lldpNeighborInfo'][0]['chassisId'].replace('.','')
    sw_mac = ':'.join(a+b for a,b in zip(sw_mac[::2], sw_mac[1::2]))
    if sw_name not in neighbors.keys():
      neighbors[sw_name] = dict()
    port = lldp_info[rint]['lldpNeighborInfo'][0]['neighborInterfaceInfo']['interfaceId'].replace('"','')
    if port not in neighbors[sw_name].keys():
      neighbors[sw_name][port] = dict()
    neighbors[sw_name][port]['leaf_if'] = rint
    neighbors[sw_name][port]['spine_ip'] = ''
    neighbors[sw_name][port]['leaf_ip'] = ''
    neighbors[sw_name]['spine_mac'] = sw_mac
  
  for device in neighbors.keys():
    commands = list()
    for intf in neighbors[device].keys():
      if 'spine_mac' != intf:
        commands.append('show ip interface {0}'.format(intf))
    
    node = get_net_element(neighbors[device]['spine_mac'])
    _user, _pwd = get_credentials(node['ztpMode'])
    ip_info = send_command(_user, _pwd, node['ipAddress'], commands)
    for ip_intf in ip_info:
      intf = ip_intf['interfaces'].keys()[0]
      ip = ip_intf['interfaces'][intf]['interfaceAddress']['primaryIp']['address']
      neighbors[device][intf]['spine_ip'] = ip
      octect = ip.split('.')
      fourth = int(octect[3]) + 1
      leaf_ip = '{0}.{1}.{2}.{3}'.format(octect[0], octect[1], octect[2], fourth)
      neighbors[device][intf]['leaf_ip'] = leaf_ip
    
  routed_info = list()
  for device in neighbors.keys():
    for intf in neighbors[device].keys():
      if 'spine_mac' != intf:
        leaf_if = neighbors[device][intf]['leaf_if']
        leaf_ip = neighbors[device][intf]['leaf_ip']
        spine_ip = neighbors[device][intf]['spine_ip']
        routed_info.append((leaf_if, device, intf.replace('/','_'), leaf_ip, spine_ip))

  return routed_info

### Start of Script
mgmt_ip = Form.getFieldById('mgmt_ip').getValue()
bgp_as = Form.getFieldById('bgp_as').getValue()
loop_1 = Form.getFieldById('loop_1').getValue()
routed_ints = ['Ethernet2', 'Ethernet3']
snmp_info = Form.getFieldById('snmp_info').getValue()

# Build Managemennt Configuration
mgmt_lookup = socket.gethostbyaddr(mgmt_ip)
hostname = mgmt_lookup[0].split('.')[0]
mgmt_config = '''
hostname {0}

vrf definition mgmt
ip routing vrf mgmt
ip route vrf mgmt 0.0.0.0/0 192.168.1.1

interface Management1
   vrf forwarding mgmt
   ip address {1}/24
   
management api http-commands
   no shutdown
   vrf mgmt
      no shutdown

'''.format(hostname, mgmt_ip)

# Build MLAG configuration
if list(hostname)[-1] == "1":
  mlag_ip = '192.168.0.1'
  mlag_peer = '192.168.0.2'
else:
  mlag_ip = '192.168.0.2'
  mlag_peer = '192.168.0.1'

mlag_config = '''
vlan 4094
   name mlag-peer-link
   trunk group mlagpeer
   
no spanning-tree vlan 4094

interface Vlan4094
   description peer-link-svi
   ip address {0}/30

interface Ethernet5
   description mlag-peer-link
   channel-group 100 mode active

interface Ethernet6
   description mlag-peer-link
   channel-group 100 mode active

interface Port-Channel100
   description mlag-peer-link
   switchport mode trunk
   switchport trunk group mlagpeer

mlag configuration
   domain-id tharpie
   local-interface Vlan4094
   peer-address {1}
   peer-link Port-Channel100
   reload-delay mlag 360
   reload-delay non-mlag 300
'''.format(mlag_ip, mlag_peer)

#Build Loopback Configuration
loop_0 = socket.gethostbyname('{0}'.format(hostname)).strip()
loopback_config = '''
interface Loopback0
   ip address {0}/32

interface Loopback1
   ip address {1}/32

'''.format(loop_0, loop_1)

# Build Routed Ethernet Configuration
routed_info = get_leaf_routed_ips(routed_ints)
ethernet_config = ''
for item in routed_info:
  ethernet_config += '''
interface {0}
   description {1}-{2}
   no switchport
   ip address {3}/31
'''.format(item[0], item[1], item[2], item[3])

#Build BGP Configuration
bgp_config = '''
ip routing

router bgp {1}
   router-id {0}
   distance bgp 20 200 200
   maximum-paths 64 ecmp 64
   neighbor spines peer-group
   neighbor spines fall-over bfd
   neighbor spines send-community
   neighbor spines remote-as 65001
   neighbor spines maximum-routes 0
   neighbor {2} remote-as {1}
   neighbor {2} next-hop-self
   neighbor {2} send-community
   neighbor {2} maximum-routes 0'''.format(loop_0, bgp_as, mlag_peer)
   
for item in routed_info:
  bgp_config += '''
   neighbor {0} peer-group spines
   neighbor {0} description {1} '''.format(item[4], item[1])
bgp_config += '''
   redistribute connected
   redistribute static
   redistribute attached-host

'''.format(bgp_as)

print loopback_config
print ethernet_config
print mlag_config
print bgp_config
print mgmt_config