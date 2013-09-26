#!/usr/bin/python

DOCUMENTATION = """
---
#module: 
#author: Lisa Glendenning
#short_description: 
#description:
#requirements:
#version_added: null
notes:
    - "Last used with Ansible v1.3 on Fedora 16."
#options:
"""

EXAMPLES = """
"""

ARGUMENTS = {
    'devices': {'required': True,},
    'device': {'required': True,}
}

#############################################################################
#############################################################################

import os

#############################################################################
#############################################################################

class Module(object):
    
    def __init__(self, module):
        self.module = module

    def main(self):
    
        result = {
            'changed': False,
            'device': None,
        }
        
        if self.module.params['device'] in self.module.params['devices']:
            device = self.module.params['device']
            partition = None # TODO
            raise Exception("Partition selection not implemented")
        else:
            for device, attrs in self.module.params['devices'].iteritems():
                if self.module.params['device'] in attrs['partitions']:
                    partition = self.module.params['device']
                    break
            else:
                raise Exception("Device selection not implemented")
        
        result['device'] = '/dev/%s' % partition
        if not os.path.exists(result['device']):
            block_dev = '/sys/block/%s/%s/dev' % (device, partition)
            major = self.module.run_command("sed 's/:.*//' < %s" % block_dev, True)[1].strip()
            minor = self.module.run_command("sed 's/.*://' < %s" % block_dev, True)[1].strip()
            self.module.run_command('mknod -m 0666 %s b %s %s' % (result['device'], major, minor), True)
            result['changed'] = True
        
        return result

#############################################################################
#############################################################################

def main():
    mod = AnsibleModule(argument_spec=ARGUMENTS)#,supports_check_mode=True)
    try:
        result = Module(mod).main()
    except Exception:
        msg = traceback.format_exc()
        mod.fail_json(msg=msg)
    else:
        mod.exit_json(**result)

#############################################################################
#############################################################################

# include magic from lib/ansible/module_common.py
#<<INCLUDE_ANSIBLE_MODULE_COMMON>>
main()
