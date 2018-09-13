# This is a configlet builder for a Remote Building.
# This will rely on the following items:
# 1. Loopback and MLAG subnets will be last /31 from base_net
# 2. The Arista device will always be the 2nd IP in wan_p2p subnet
# 3. Port-Channel 100 is the MLAG Peer-Link
# 4. Loopback0 will be used as the source for Monitoring, Telemetry, TACACS, etc

#from cvplibrary import Form
import netaddr
import os

# Set Variables based on Form
hostname = Form.getFieldById('hostname').getValue().upper()
base_net = netaddr.IPNetwork(Form.getFieldById('base_net').getValue())
floors = int(Form.getFieldById('floors').getValue())
wan_p2p = netaddr.IPNetwork(Form.getFieldById('wan_p2p').getValue())
wan_intf = Form.getFieldById('wan_intf').getValue()
peerlink = Form.getFieldById('peerlink').getValue()
peerlink_ints = peerlink.split(',')
wan_as = Form.getFieldById('wan_as').getValue()
local_as = Form.getFieldById('local_as').getValue()
rp = Form.getFieldById('rp').getValue()
dhcp_ip = Form.getFieldById('dhcp').getValue()


# Function to find next subnet based on cidr
# returns updated subnets list and subnet
def get_subnet(subnets, cidr):
    found = False
    while not found:
        subnet = subnets.pop(0)
        if cidr == subnet.prefixlen:
            found = True
        elif cidr < subnet.prefixlen:
            continue
        elif cidr > subnet.prefixlen:
            new_subnets = sorted(list(subnet.subnet(cidr)))
            subnet = new_subnets.pop(0)
            found = True
            subnets.extend(new_subnets)
            subnets = sorted(list(netaddr.cidr_merge(subnets)))
            
    return subnets, subnet


# Define vlans
# per floor vlans will start with the specified number and add 1 to the end for the floor
# global vlans will always use the specified vlan number
base_vlans = [
{'number':100, 'name':'DESKTOP', 'type':'per_floor', 'cidr':22, 'dhcp': True},
{'number':200, 'name':'WIRELESS', 'type':'per_floor', 'cidr':25, 'dhcp': True},
{'number':300, 'name':'VOICE', 'type':'per_floor', 'cidr':24, 'dhcp': True},
{'number':470, 'name':'NETWORK_MGMT', 'type':'global', 'cidr':26, 'dhcp': False}
]

# Define networks, types and associate metadata
networks = dict()
networks['base'] = dict()
networks['base']['vlans'] = base_vlans
networks['base']['supernet'] = base_net
networks['base']['subnets'] = sorted(list(base_net.subnet(22)))

# Generate all details for each vlan in built_vlans
built_vlans = dict()
floor_vlans = dict()
global_vlans = list()

for net_type in networks.keys():
    subnets = networks[net_type]['subnets']
    for vlan in networks[net_type]['vlans']:
        if vlan['type'] == 'per_floor':  
            for floor in range(1, floors+1):
                if floor not in floor_vlans.keys():
                    floor_vlans[floor] = list()
                    
                number = vlan['number'] + floor
                desc = '%s_%sFLOOR' % (vlan['name'], floor)
                subnets, subnet = get_subnet(subnets, vlan['cidr'])
                built_vlans[number] = dict()
                built_vlans[number]['desc'] = desc
                built_vlans[number]['subnet'] = subnet
                built_vlans[number]['dhcp'] = vlan['dhcp']
                floor_vlans[floor].append(number)
                
        elif vlan['type'] == 'global':
            number = vlan['number']
            desc = '%s' % vlan['name']
            subnets, subnet = get_subnet(subnets, vlan['cidr'])
            built_vlans[number] = dict()
            built_vlans[number]['desc'] = desc
            built_vlans[number]['subnet'] = subnet
            built_vlans[number]['dhcp'] = vlan['dhcp']
            global_vlans.append(number)


# Set MLAG base network
mlag_net = sorted(list(networks['base']['supernet'].subnet(31)))[-1]

# Define WAN Peer
wan_peer = wan_p2p[0] if wan_p2p.prefixlen == 31 else wan_p2p[1]

# Determine if Device is 1 or 2
device_one = True if int(hostname[-1]) % 2 == 0 else False

# Set Loopback base network
if device_one:
    loop_net = sorted(list(networks['base']['supernet'].subnet(32)))[-5]
else:
    loop_net = sorted(list(networks['base']['supernet'].subnet(32)))[-4]

## Print out Variables used in Form
print '!! Variables from Builder'
print '! hostname: %s' % hostname
print '! base_net: %s' % base_net
print '! floors: %s' % floors
print '! wan_p2p: %s' % wan_p2p
print '! wan_as: %s' % wan_as
print '! local_as: %s' % local_as
print ''

# Build Unicast and Mcast Routing Configuration
print 'hostname %s' % hostname
print ''
print 'ip routing'
print ''
print 'router multicast'
print '   ip multicast-routing'
print ''
print 'router pim sparse-mode'
print '   ip pim ssm range standard'
print '   ip pim rp-address %s' % rp
print ''

# Configure static routes
for net_type in networks.keys():
    supernet = networks[net_type]['supernet']
    print 'ip route %s/%s Null0' % (supernet.network, supernet.prefixlen)
print 'ip route 0.0.0.0/0 %s 250' % wan_peer
print ''

# Build VLAN and Spanning-Tree Configuration
print 'spanning-tree mode rapid-pvst'
print 'no spanning-tree vlan 4094'
print 'spanning-tree vlan 1-4093 priority 4096'
print ''
for vlan in sorted(built_vlans.keys()):
    print 'vlan %s' % vlan
    print '   name %s' % built_vlans[vlan]['desc']
    print ''

# Configure MLAG VLAN and iBGP VLAN
print 'vlan 4094'
print '   name MLAG_PEERLINK'
print '   trunk group mlag-peerlink'
print ''

# Build Switched Virtual Interface Configuration and Loopbacks
# Configure virtual-router mac-address
mlag_ip = mlag_net[0] if device_one else mlag_net[1]

for vlan in sorted(built_vlans.keys()):
    addr = built_vlans[vlan]['subnet'][2] if device_one else built_vlans[vlan]['subnet'][3]
    gw = built_vlans[vlan]['subnet'][1]
    cidr = built_vlans[vlan]['subnet'].prefixlen
    
    print 'interface Vlan%s' % vlan
    print '   description %s' % built_vlans[vlan]['desc']
    print '   no autostate'
    print '   ip address %s/%s' % (addr, cidr)
    
    if built_vlans[vlan]['dhcp']:
        print '   ip helper-address %s' % dhcp_ip
        
    print '   ip pim sparse-mode'
    print '   ip virtual-router address %s' % gw
    print ''

print 'interface Vlan4094'
print '   description MLAG_SVI'
print '   no autostate'
print '   ip address %s/%s' % (mlag_ip, mlag_net.prefixlen)
print ''
print 'ip virtual-router mac-address 00:1C:73:00:00:01'
print ''
print 'interface Loopback0'
print '   ip address %s' % loop_net
print ''

# Build Physical Port Configuration
# Determines how many ports to reserve for downlinks per floor
switches_per_floor = 2
# This defines the number of interfaces on a given device
interfaces = range(1,47)
wan_ip = wan_p2p[1] if wan_p2p.prefixlen == 31 else wan_p2p[2]

for floor in range(1, floors+1):
    for sw in range(1, switches_per_floor+1):
        int_number = interfaces.pop(0)
        print 'interface Ethernet%s' % int_number
        print '   channel-group 10%s mode active' % int_number
        print ''

print 'interface %s' % wan_intf
print '   ip address %s/%s' % (wan_ip, wan_p2p.prefixlen)
print '   ip pim sparse-mode'
print ''
for intf in sorted(peerlink_ints):
    print 'interface %s' % intf
    print '   channel-group 100 mode active'
    print ''

# Build out MLAG details
# Build Port-Channels configuration for each floor and peer-link
interfaces = range(1,47)
mlag_peer = mlag_net[1] if device_one else mlag_net[0]

for floor in range(1, floors+1):
    floor_vlans[floor].extend(global_vlans)
    vlans = sorted(floor_vlans[floor])
    for sw in range(1, switches_per_floor+1):
        int_number = interfaces.pop(0)
        print 'interface Port-Channel10%s' % int_number
        print '   switchport trunk allowed vlan %s' % (','.join(str(x) for x in vlans))
        print '   switchport mode trunk'
        print '   mlag 10%s' % int_number
        print ''

print 'interface Port-Channel100'
print '   description MLAG-PEERLINK'
print '   switchport mode trunk'
print '   switchport trunk group mlag-peerlink'
print ''
print 'mlag configuration'
print '   domain-id ARISTA4THEWIN'
print '   local-interface Vlan4094'
print '   peer-address %s' % mlag_peer
print '   peer-link Port-Channel100'
## For fixed devices use value below
print '   reload-delay mlag 360'
print '   reload-delay non-mlag 300'
## For Chassis use value below
#print '   reload-delay mlag 1500'
#print '   reload-delay non-mlag 1200'
print ''

# Build BGP Configuration and advertise networks
print 'router bgp %s' % local_as
print '   router-id %s' % loop_net[0]
print '   distance bgp 20 200 200'
print '   maximum-paths 64 ecmp 64'
print '   neighbor %s remote-as %s' % (mlag_peer, local_as)
print '   neighbor %s next-hop-self' % mlag_peer
print '   neighbor %s send-community' % mlag_peer
print '   neighbor %s remote-as %s' % (wan_peer, wan_as)
print '   neighbor %s fall-over bfd' % wan_peer
print '   neighbor %s send-community' % wan_peer
print '   network %s' % loop_net
for net_type in networks.keys():
  base = networks[net_type]['supernet']
  print '   network %s/%s' % (base.network, base.prefixlen)
print ''

print '''
banner motd

 **********************************************************************
                        LEGAL NOTIFICATION
 **********************************************************************
            UNAUTHORIZED USE OF THIS SYSTEM IS PROHIBITED
 **********************************************************************

                          GET OFF MY LAWN 

 **********************************************************************
 EOF
'''

# Set Telemetry details
### Using the CVP device interface for receiving telemetry data
ip_list = list()
ip_list.append(os.environ.get('PRIMARY_DEVICE_INTF_IP', None))
ip_list.append(os.environ.get('SECONDARY_DEVICE_INTF_IP', None))
ip_list.append(os.environ.get('TERTIARY_DEVICE_INTF_IP', None))
ingest_grpc = ','.join( [ '%s:9910' % ip for ip in ip_list if ip ] )

### Smash tables to exclude
smash_exclude_list = list()
smash_exclude_list.append('ale')
smash_exclude_list.append('flexCounter')
smash_exclude_list.append('hardware')
smash_exclude_list.append('kni')
smash_exclude_list.append('pulse')
smash_exclude_list.append('strata')
smash_exclude = ','.join(smash_exclude_list)

### Paths to exclude from the ingest stream
ingest_exclude_list = list()
ingest_exclude_list.append('/Sysdb/cell/1/agent')
ingest_exclude_list.append('/Sysdb/cell/2/agent')
ingest_exclude = ','.join(ingest_exclude_list)

### Getting the Ingest Key
### Changing CVP's Ingest key requires a CVP restart
ingest_key = os.environ.get('AERIS_INGEST_KEY', '')

print 'daemon TerminAttr'
print '   exec /usr/bin/TerminAttr -ingestgrpcurl=%s -taillogs ' \
      '-ingestauth=key,%s -smashexcludes=%s -ingestexclude=%s ' \
      '-ingestvrf=default -cvcompression=gzip' % (ingest_grpc, ingest_key, smash_exclude, ingest_exclude)
print '   no shutdown'
print ''
print 'management api http-commands'
print '   no shutdown'
print '   protocol https port 443' 
print '   protocol unix-socket'
print ''
print 'management ssh'
print '   idle-timeout 5'
print ''
print 'management console'
print '   idle-timeout 5'
print ''