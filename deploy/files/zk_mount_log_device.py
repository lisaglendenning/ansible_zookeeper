#!/usr/bin/env python

# Requires >=2.6

import sys
import optparse
import os.path
import subprocess
import re

#############################################################################
#############################################################################

def execute(argv, opts, dry_run=False, **args):

    returncode = 0
    stdout = ''
    stderr = ''

    if opts.verbose:
        sys.stdout.write("Executing: %s..." % \
                         (argv if isinstance(argv, str) else ' '.join(argv)))
        sys.stdout.flush()
    
    if (not opts.dry_run) or dry_run:
        # bubble up OSError
        try:
            proc = subprocess.Popen(argv, 
                                    stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE,
                                    **args)
        except OSError as e:
            if opts.verbose:
                sys.stdout.write("%s\n" % e.errno)
            raise
        stdout, stderr = proc.communicate()
        returncode = proc.returncode
        if opts.verbose:
            sys.stdout.write("%d\n" % returncode)
            sys.stdout.write(stdout)
            sys.stdout.flush()
            sys.stderr.write(stderr)
            sys.stderr.flush()
    else:
        if opts.verbose:
            sys.stdout.write("\n")
        
    return returncode, stdout, stderr

#############################################################################
#############################################################################

def mount(opts):
    stats = os.stat(opts.mount)
    argv = ["mount", opts.mount]
    ret = execute(argv, opts)
    if ret[0] != 0:
        sys.stderr.write(ret[2])
    else:
        # fix permissions
        if not opts.dry_run:
            new_stats = os.stat(opts.mount)
            if new_stats.st_uid != stats.st_uid or new_stats.st_gid != stats.st_gid:
                os.chown(opts.mount, stats.st_uid, stats.st_gid)
            if new_stats.st_mode != stats.st_mode:
                os.chmod(opts.mount, stats.st_mode)
    return ret[0]

#############################################################################
#############################################################################

def select_disk(opts, disks):

    # determine mounted devices
    argv = "df -l | grep -E '^/dev/' | cut -d ' ' -f 1 | sed 's/[0-9]*$//' | sort -u"
    mounted_disks = execute(argv, opts, dry_run=True, shell=True)[1].splitlines()
    
    # candidate disks are not mounted
    candidate_disks = [d for d in disks if d[0] not in mounted_disks]
    
    # heuristic: choose largest disk
    disk = None
    for d in candidate_disks:
        if disk is None or d[2] > disk[2]:
            disk = d
    if disk:
        disk = disk[0]
    if opts.verbose:
        sys.stdout.write('Selected %s out of %s\n' % (disk, candidate_disks))
    return disk

#############################################################################
#############################################################################

def configure(argv):
    
    defaults = {'verbose': False, 'dry_run': False,}
    
    usage = "usage: %prog [options] MOUNT"
    
    optparser = optparse.OptionParser(usage=usage)
    
    optparser.add_option('-q', '--quiet', dest='verbose',
                         action="store_false", default=defaults['verbose'])
    optparser.add_option('-v', '--verbose', dest='verbose',
                         action="store_true", default=defaults['verbose'])
    optparser.add_option('-n', '--dry-run', dest='dry_run',
                         action="store_true", default=defaults['dry_run'],
                         help="Minimal side effects")
    optparser.add_option('-d', '--device', dest='device',
                         action="store", type="string", default='',
                         help="device specifier")
    
    opts, args = optparser.parse_args(argv)
    if len(args) != 2:
        optparser.error("missing required argument: mount point\n")
        sys.exit(1)
    
    opts.mount = os.path.abspath(args[1])

    return opts

#############################################################################
#############################################################################

def main(argv):
    returncode = 0

    opts = configure(argv)
    
    # check if already mounted
    argv = "df -l | grep ' %s$' | cut -d ' ' -f 1" % opts.mount
    ret = execute(argv, opts, dry_run=True, shell=True)
    if ret[1]:
        if opts.verbose:
            sys.stdout.write('Already mounted: %s %s\n' % (ret[1].strip(), opts.mount))
        return 0
    
    # try to mount
    argv = "grep -E '[[:space:]]+%s[[:space:]]+' /etc/fstab | cut -d ' ' -f 1" % opts.mount
    ret = execute(argv, opts, dry_run=True, shell=True)
    if ret[1]:
        if opts.verbose:
            sys.stdout.write('Mount already specified: %s\n' % ret[1].strip())
        return mount(opts)
    
    # determine available disks
    fdisk_output = r'^Disk ([/\w]*): (\d+(?:\.\d+)? [A-Za-z]+), (\d+) bytes$'
    argv = "fdisk 2>&1 -l | grep '^Disk /dev/.*:'"
    ret = execute(argv, opts, dry_run=True, shell=True)
    disks = [re.match(fdisk_output, line).groups() \
             for line in ret[1].splitlines()]
    
    # select a disk
    disk = None
    disk_names = [d[0] for d in disks]
    for name in (opts.device, "/dev/%s" % opts.device):
        if name in disk_names:
            disk = name
            break
    else:
        disk = select_disk(opts, disks)
    if disk is None:
        sys.stderr.write("Error: no available disks\n")
        return 2
    assert disk in disk_names
    
    # TODO: take option for maximum size of partition
    # TODO: check existing partitioning of device
    # partition device
    partition = 1
    argv = "echo -e 'd\n1\nn\np\n1\n\n\nw\n' | sudo fdisk %s > /dev/null" % disk
    ret = execute(argv, opts, shell=True)
    if (ret[0] != 0):
        sys.stderr.write(ret[2])
        return ret[0]
    device = '%s%d' % (disk, partition)
    
    # format device
    fstype = 'ext3'
    argv = "mkfs.%s %s > /dev/null" % (fstype, device)
    ret = execute(argv, opts, shell=True)
    if (ret[0] != 0):
        sys.stderr.write(ret[2])
        return ret[0]
    
    # determine blkid
    blkid = None
    argv = "blkid %s | cut -d ' ' -f 2" % device
    ret = execute(argv, opts, shell=True)
    if ret[1]:
        blkid = ret[1].strip().split('=')[1].strip('"')
    
    # append new entry to fstab
    mount_opts = 'rw,auto,user,async'
    mount_source = 'UUID=%s' % blkid if blkid else device
    mount_entry = [mount_source, opts.mount, fstype, mount_opts, '0', '0']
    fstab_line = '%s\n' % '\t'.join(mount_entry)
    if opts.verbose:
        sys.stdout.write('Appending to /etc/fstab: %s' % fstab_line)
    if not opts.dry_run:
        with open('/etc/fstab', 'a') as f:
            f.write(fstab_line)
    
    # mount device
    returncode = mount(opts)
    
    return returncode
    
#############################################################################
#############################################################################

if __name__ == '__main__':
    sys.exit(main(sys.argv))

#############################################################################
#############################################################################
