from cvplibrary import CVPGlobalVariables as cvp_vars
from cvplibrary import GlobalVariableNames as cvp_names
from cvplibrary import RestClient
from cvplibrary import Form

import netaddr
import jsonrpclib
import json


# Set Variables based on Form and static
base_net = Form.getFieldById('supernet').getValue()
base_net = netaddr.IPNetwork(base_net)
lo0 = Form.getFieldById('lo0').getValue()
lo0 = netaddr.IPNetwork('%s/32' % lo0)
asn = Form.getFieldById('asn').getValue().upper()
leaf_asn = Form.getFieldById('leaf_asn').getValue()
start = int(leaf_asn.split('-')[0])
end = int(leaf_asn.split('-')[-1])
leaf_asn = range(start, end+1)
mac = cvp_vars.getValue(cvp_names.CVP_MAC)

# Can be changed to fit environment
p2p_cidr = 31

# Functions
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

def get_interfaces():
    ## If interfaces need to be excluded, add to exempt_ints
    exempt_ints = list()
    exempt_ints.append('Management0')
    exempt_ints.append('Management1')
    exempt_ints.append('Management1/1')
    exempt_ints.append('Management1/2')
    exempt_ints.append('Management2/1')
    exempt_ints.append('Management2/2')
    
    interfaces = list()
    user, pwd = get_credentials()
    sw_ip = cvp_vars.getValue(cvp_names.CVP_IP)
    commands = ['show interfaces status']
    int_status = send_command(user, pwd, sw_ip, commands)[0]['interfaceStatuses']
    
    for key in int_status.keys():
        if key in exempt_ints:
            continue
        else:
            interfaces.append(key)
            
    return sorted(interfaces)


# Start of Configuration Output
print 'ip routing'
print ''

interfaces = get_interfaces()
subnets = sorted(base_net.subnet(p2p_cidr))

for _int in interfaces:
    subnet = subnets.pop(0)
    ip = subnet[0] if subnet.prefixlen == 31 else subnet[1]
    print 'interface %s' % _int
    print '   no switchport'
    print '   ip address %s/%s' % (ip, subnet.prefixlen)
    print ''
  
print 'interface Loopback0'
print '   ip address %s' % lo0
print ''
print 'peer-filter leaves-asn'
print '   match as-range %s-%s result accept' % (leaf_asn[0], leaf_asn[-1])
print ''

print 'router bgp %s' % asn
print '   router-id %s' % lo0[0]
print '   distance bgp 20 200 200'
print '   maximum-paths 64 ecmp 64'
print '   neighbor leaves peer-group'
print '   neighbor leaves send-community'
print '   bgp listen range %s peer-group leaves peer-filter leaves-asn' % base_net
print '   network %s' % lo0
print ''
