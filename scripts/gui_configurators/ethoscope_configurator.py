#! /usr/bin/python3

import subprocess
import os
import datetime
import time

# try to load tkinter, if tk is not installed, install it first.
try:
    from tkinter import *
    import tkinter.ttk as ttk
except Exception as e:
    print(e)
    subprocess.call(["sudo", "pacman", "-Sy", "tk", "--noconfirm"])

finally:
    from tkinter import *
    import tkinter.ttk as ttk

def execute_instruction(instruction):
    subprocess.call(instruction.split(" "))

def prepare_basic_arch(sd_card_path, subnet, ethoscope_id, wlan_ssid, wlan_pass):
    #install bmap-tools
    #download and run pip
    #execute_instruction("pacman -S python-pip --noconfirm --needed")
    #execute_instruction("wget -P /tmp/ https://github.com/intel/bmap-tools/archive/master.zip")
    #execute_instruction("unzip /tmp/bmap-tools-master.zip -d /tmp/bmap-tools")
    #execute_instruction("pip3 install /tmp/bmap-tools")

    #check if enough space in tmp
    df = subprocess.Popen(["df", "/tmp"], stdout=subprocess.PIPE)
    output = df.communicate()[0]
    device, size, used, available, percent, mountpoint = output.split(b"\n")[1].split()
    if int(available) < 5000000:
        #resize tmpfs /tmp with enough space for all this
        resize = int((int(size) + 5000000) / 1000000)
        execute_instruction("mount -o remount,size={}G,noatime /tmp".format(resize))

    #get archarm iso
    if not os.path.isfile("/tmp/ArchLinuxARM-rpi-2-latest.tar.gz"):
        execute_instruction("wget -P /tmp/ http://os.archlinuxarm.org/os/ArchLinuxARM-rpi-2-latest.tar.gz")


    #prepare sd card
    execute_instruction("umount {}*".format(sd_card_path))
    instruction = "fdisk {}".format(sd_card_path)
    fdisk = subprocess.Popen(instruction.split(" "),stdin= subprocess.PIPE)
    #fdisk.communicate()
    fdisk.stdin.write(b"o\n")
    fdisk.stdin.write(b"p\n")
    fdisk.stdin.write(b"n\n")
    fdisk.stdin.write(b"p\n")
    fdisk.stdin.write(b"1\n")
    fdisk.stdin.write(b"\n")
    fdisk.stdin.write(b"+100M\n")
    fdisk.stdin.write(b"t\n")
    fdisk.stdin.write(b"c\n")
    fdisk.stdin.write(b"n\n")
    fdisk.stdin.write(b"p\n")
    fdisk.stdin.write(b"2\n")
    fdisk.stdin.write(b"\n")
    fdisk.stdin.write(b"\n")
    fdisk.stdin.write(b"w\n")
    fdisk.stdin.flush()
    fdisk.communicate()

    execute_instruction("mkfs.vfat {}1".format(sd_card_path))
    execute_instruction("rm -r /tmp/boot") #delete this folder in case it exist from previous tries
    execute_instruction("mkdir /tmp/boot")
    execute_instruction("mount {}1 /tmp/boot".format(sd_card_path))

    execute_instruction("mkfs.ext4 {}2".format(sd_card_path))
    execute_instruction("rm -r /tmp/root") #delete this folder in case it exist from previous tries
    execute_instruction("mkdir /tmp/root")
    execute_instruction("mount {}2 /tmp/root".format(sd_card_path))

    execute_instruction("bsdtar -xpf /tmp/ArchLinuxARM-rpi-2-latest.tar.gz -C /tmp/root")
    time.sleep(2)
    execute_instruction("sync")
    subprocess.Popen("mv /tmp/root/boot/* /tmp/boot", shell=True).wait()

    # Prepare preconfiguration
    ## 1. Download ethoscope software
    ### some constants
    # where to install and find our software
    TARGET_GIT_INSTALL = "/tmp/root/opt/ethoscope-git"
    UPDATER_LOCATION_IN_GIT = "scripts/ethoscope_updater"
    UPSTREAM_GIT_REPO = "https://github.com/gilestrolab/ethoscope.git"
    TARGET_UPDATER_DIR = "/tmp/root/opt/ethoscope_updater"
    BARE_GIT_NAME = "ethoscope.git"
    NODE_IP = subnet+".1"

    execute_instruction("git clone git://{0}/{1} {2}".format(NODE_IP,BARE_GIT_NAME,TARGET_GIT_INSTALL))

    ## copy services from our folder to systemd
    execute_instruction("cp {0}/scripts/ethoscope_device.service /tmp/root/etc/systemd/system/ethoscope_device.service".format(TARGET_GIT_INSTALL))
    execute_instruction("cp {0}/{1} {2} -r".format(TARGET_GIT_INSTALL,UPDATER_LOCATION_IN_GIT,TARGET_UPDATER_DIR))
    execute_instruction("cp {0}/ethoscope_update.service /tmp/root/etc/systemd/system/ethoscope_update.service".format(TARGET_UPDATER_DIR))

    ## 2. create wifi and ethernet netctl profiles
    with open("/tmp/root/etc/netctl/wlan0","w") as f:
        f.write("Description=ethoscope_wifi network\n")
        f.write("Interface=wlan0\n")
        f.write("Connection = wireless\n")
        f.write("Security = wpa\n")
        f.write("IP = dhcp\n")
        f.write("TimeoutDHCP = 60\n")
        f.write("ESSID ={}\n".format(wlan_ssid))
        f.write("Key ={}\n".format(wlan_pass))

    with open("/tmp/root/etc/netctl/eth0","w") as f:
        f.write("Description=eth0 network")
        f.write("Interface=eth0")
        f.write("Connection=ethernet")
        f.write("IP=dhcp")

    ## 3. modify boot to activate pi camera
    with open("/tmp/boot/config.txt","w") as f:
        f.write("start_file=start_x.elf\n")
        f.write("fixup_file=fixup_x.dat\n")
        f.write("disable_camera_led=1\n")
        f.write("gpu_mem=256\n")
        f.write("cma_lwm=\n")
        f.write("cma_hwm=\n")
        f.write("cma_offline_start=\n")

    ## load bcm2835-v4l2
    with open("/tmp/root/etc/modules-load.d/picamera.conf", "w") as f:
        f.write("bcm2835-v4l2")

    ## watchdog module
    with open("/tmp/root/etc/modules-load.d/bcm2835_wdt.conf", "w") as f:
        f.write("bcm2835_wdt")

    ##write test disk for watchdog
    execute_instruction("mkdir /tmp/root/etc/watchdog.d/")
    with open("/tmp/root/etc/watchdog.d/write_test.sh", "w") as f:
        f.write("#!/bin/bash\n")
        f.write("sleep 10 && touch /var/tmp/write_test\n")

    execute_instruction("chmod 755 /tmp/root/etc/watchdog.d/write_test.sh")

    ##configure watchdog
    with open("/tmp/root/etc/watchdog.conf","a") as f:
        f.write("max-load=30\n")
        f.write("watchdog-device=/dev/watchdog\n")
        f.write("watchdog-timeout=70\n")
        f.write("realtime=yes\n")
        f.write("priority=1\n")

    # Does not work in recent versions
    # disable power management for wifi
    #with open("/tmp/root/etc/modprobe.d/8192cu.conf", "w") as f:
    #    f.write("options 8192cu rtw_power_mgnt=0")

    #ramdisk as temporary storage
    with open("/tmp/root/etc/fstab","a") as f:
        f.write("tmpfs /tmp tmpfs defaults,noatime,mode=1777 0 0 ")

    #reduce logs to 250MB
    with open("/tmp/root/etc/systemd/journald.conf", "a") as f:
        f.write("SystemMaxUse=200MB")

    #change machine-id, machine-name and hostname
    #get uuid from node and append the number of ethoscope
    with open("/etc/machine-id", "r") as f:
        #machine id will be changed by the first_boot.sh script at the end. No machine-id will trigger ConditionFirstBoot
        mid = f.read().strip()
        MACHINE_ID = "{0:03d}e{1}".format(int(ethoscope_id),mid[4:])

    execute_instruction("rm /tmp/root/etc/machine-id")

    with open("/tmp/root/etc/machine-name", "w") as f:
        f.write("ETHOSCOPE_{}".format(ethoscope_id))
    with open("/tmp/root/etc/hostname", "w") as f:
        f.write("e{}".format(ethoscope_id))

    #prepare list of packages to download and be able to install them on first startup
    execute_instruction("wget http://mirror.archlinuxarm.org/armv7h/community/community.db -O /tmp/root/var/lib/pacman/sync/community.db")
    execute_instruction("wget http://mirror.archlinuxarm.org/armv7h/core/core.db -O /tmp/root/var/lib/pacman/sync/core.db")
    execute_instruction("wget http://mirror.archlinuxarm.org/armv7h/extra/extra.db -O /tmp/root/var/lib/pacman/sync/extra.db")
    execute_instruction("wget http://mirror.archlinuxarm.org/armv7h/alarm/alarm.db -O /tmp/root/var/lib/pacman/sync/alarm.db")
    execute_instruction("wget http://mirror.archlinuxarm.org/armv7h/aur/aur.db -O /tmp/root/var/lib/pacman/sync/aur.db")

    #list of dependencies or packages to install
    pkglist = ["archlinux-keyring","archlinuxarm-keyring","base-devel","git","gcc-fortran","rsync", "wget",
               "hdf5",
               "opencv", "ocl-icd","eigen","mplayer","ffmpeg", "gstreamer", "mencoder",
               "ntp","bash-completion","firmware-raspberrypi","raspberrypi-bootloader",
               "python-pip","python-numpy","python-bottle","python-pyserial","mysql-python","python-cherrypy",
               "python-scipy","python-pillow", "python-mysql-connector"
               "glibc","mariadb",
               "fake-hwclock",
               "wpa_supplicant","ifplugd",
               "libev"]
    subprocess.call("sudo pacman --sysroot /tmp/root --arch armv7h --cachedir /var/cache/pacman/pkg -Sup {} --noconfirm > /tmp/pkglist_url".format((" ").join(pkglist)), shell=True)
    execute_instruction("wget -P /tmp/root/var/cache/pacman/pkg -nv -i /tmp/pkglist_url")

    #check that all the requiered packages are there and if not try to download them again
    list_downloaded = os.listdir("/tmp/root/var/cache/pacman/pkg")
    with open("/tmp/pkglist_url","r") as f:
        list_to_download = f.read()
        list_to_download = list_to_download.split("\n")
    list_to_retry=[]
    while True:
        for entry in list_to_download:
            if len(entry)>1 and entry.split("/")[-1] not in list_downloaded:
                list_to_retry.append(entry)
        if len(list_to_retry) > 0 :
            execute_instruction("wget -P /tmp/root/var/cache/pacman/pkg -nv -i {}".format(list_to_retry))
        else:
            break

    execute_instruction("pip download -d /tmp/root/home/alarm/python picamera GitPython")

    # modify and copy file first boot and my.cnf
    content = first_boot
    content = content.replace("LIST_OF_PACKAGES", (" ").join(pkglist))
    content = content.replace("NODE_IP", NODE_IP)
    content = content.replace("NODE_SUBNET", subnet)
    content = content.replace("BARE_GIT_NAME", BARE_GIT_NAME)
    content = content.replace("UPSTREAM_GIT_REPO", UPSTREAM_GIT_REPO)
    content = content.replace("BRANCH", "python3.7")
    content = content.replace("TARGET_GIT_INSTALL", "/opt/ethoscope-git")
    content = content.replace("MACHINE_ID", MACHINE_ID)
    with open("/tmp/root/opt/first_boot.sh", "w") as f:
        f.write(content)
    #make it executable
    execute_instruction("chmod 755 /tmp/root/opt/first_boot.sh")

    with open("/tmp/root/etc/systemd/system/ethoscope_first_boot.service", "w") as f:
        f.write(unit_file)
    execute_instruction("ln -s /tmp/root/etc/systemd/system/ethoscope_first_boot.service /tmp/root/etc/systemd/system/multi-user.target.wants/ethoscope_first_boot.service")
    try:
        os.mkdir("/tmp/root/home/alarm/mysql/")
    except Exception as e:
        print(e)
        pass
    with open("/tmp/root/home/alarm/mysql/my.cnf", "w") as f:
        f.write(my_cnf)

    #make a snapshot of the OS
    execute_instruction("rm /tmp/root/var/lock")
    subprocess.Popen("cp -r /tmp/boot/* /tmp/root/boot", shell=True).wait()
    ac = datetime.datetime.today().strftime("%Y%m%d")
    instruction = "tar -zcvpf /tmp/ethoscope_os_{}.tar.gz *".format(ac)
    subprocess.Popen(instruction, cwd="/tmp/root", shell = True, stdin=subprocess.PIPE).wait()
    print("tar finished")
    subprocess.Popen("rm /tmp/root/boot/* -r", shell=True, stdin=subprocess.PIPE).wait()
    print("deleting")
    execute_instruction("umount -l /tmp/boot")
    execute_instruction("umount -l /tmp/root")
    print("unmounting")
    print("Ready!, please insert the SD card into an Ethoscope, and allow some minutes for the system to initialize.")

unit_file="""
[Unit]
Description=Ethoscope first boot configuration tool
ConditionFirstBoot=true

[Service]
ExecStart=/bin/sh /opt/first_boot.sh

[Install]
WantedBy=multi-user.target 
"""

my_cnf ="""
# Example MariaDB config file for medium systems.
#
# This is for a system with little memory (32M - 64M) where MariaDB plays
# an important part, or systems up to 128M where MariaDB is used together with
# other programs (such as a web server)
#
# MariaDB programs look for option files in a set of
# locations which depend on the deployment platform.
# You can copy this option file to one of those
# locations. For information about these locations, do:
# 'my_print_defaults --help' and see what is printed under
# Default options are read from the following files in the given order:
# More information at: http://dev.mysql.com/doc/mysql/en/option-files.html
#
# In this file, you can use all long options that a program supports.
# If you want to know which options a program supports, run the program
# with the "--help" option.

# The following options will be passed to all MariaDB clients
[client]
#password	= your_password
port		= 3306
socket		= /run/mysqld/mysqld.sock

# Here follows entries for some specific programs

# The MariaDB server
[mysqld]
port		= 3306
socket		= /run/mysqld/mysqld.sock
skip-external-locking
key_buffer_size = 16M
max_allowed_packet = 1M
table_open_cache = 64
sort_buffer_size = 512K
net_buffer_length = 8K
read_buffer_size = 256K
read_rnd_buffer_size = 512K
myisam_sort_buffer_size = 8M
skip-name-resolve

# Point the following paths to different dedicated disks
#tmpdir		= /tmp/

# Don't listen on a TCP/IP port at all. This can be a security enhancement,
# if all processes that need to connect to mysqld run on the same host.
# All interaction with mysqld must be made via Unix sockets or named pipes.
# Note that using this option without enabling named pipes on Windows
# (via the "enable-named-pipe" option) will render mysqld useless!
#
#skip-networking

# Replication Master Server (default)
# binary logging is required for replication
log-bin=mysql-bin

# binary logging format - mixed recommended
binlog_format=mixed

# required unique id between 1 and 2^32 - 1
# defaults to 1 if master-host is not set
# but will not function as a master if omitted
server-id	= 1

# Replication Slave (comment out master section to use this)
#
# To configure this host as a replication slave, you can choose between
# two methods :
#
# 1) Use the CHANGE MASTER TO command (fully described in our manual) -
#    the syntax is:
#
#    CHANGE MASTER TO MASTER_HOST=<host>, MASTER_PORT=<port>,
#    MASTER_USER=<user>, MASTER_PASSWORD=<password> ;
#
#    where you replace <host>, <user>, <password> by quoted strings and
#    <port> by the master's port number (3306 by default).
#
#    Example:
#
#    CHANGE MASTER TO MASTER_HOST='125.564.12.1', MASTER_PORT=3306,
#    MASTER_USER='joe', MASTER_PASSWORD='secret';
#
# OR
#
# 2) Set the variables below. However, in case you choose this method, then
#    start replication for the first time (even unsuccessfully, for example
#    if you mistyped the password in master-password and the slave fails to
#    connect), the slave will create a master.info file, and any later
#    change in this file to the variables' values below will be ignored and
#    overridden by the content of the master.info file, unless you shutdown
#    the slave server, delete master.info and restart the slaver server.
#    For that reason, you may want to leave the lines below untouched
#    (commented) and instead use CHANGE MASTER TO (see above)
#
# required unique id between 2 and 2^32 - 1
# (and different from the master)
# defaults to 2 if master-host is set
# but will not function as a slave if omitted
#server-id       = 2
#
# The replication master for this slave - required
#master-host     =   <hostname>
#
# The username the slave will use for authentication when connecting
# to the master - required
#master-user     =   <username>
#
# The password the slave will authenticate with when connecting to
# the master - required
#master-password =   <password>
#
# The port the master is listening on.
# optional - defaults to 3306
#master-port     =  <port>
#
# binary logging - not required for slaves, but recommended
#log-bin=mysql-bin

# Uncomment the following if you are using InnoDB tables
#innodb_data_home_dir = /var/lib/mysql
#innodb_data_file_path = ibdata1:10M:autoextend
#innodb_log_group_home_dir = /var/lib/mysql
# You can set .._buffer_pool_size up to 50 - 80 %
# of RAM but beware of setting memory usage too high
innodb_buffer_pool_size = 128M
#innodb_additional_mem_pool_size = 2M
# Set .._log_file_size to 25 % of buffer pool size
innodb_log_file_size = 32M
innodb_log_buffer_size = 50M
innodb_flush_log_at_trx_commit = 1
innodb_lock_wait_timeout = 50
innodb_file_per_table=1

[mysqldump]
quick
max_allowed_packet = 16M

[mysql]
no-auto-rehash
# Remove the next comment character if you are not familiar with SQL
#safe-updates

[myisamchk]
key_buffer_size = 20M
sort_buffer_size = 20M
read_buffer = 2M
write_buffer = 2M

[mysqlhotcopy]
interactive-timeout
"""

first_boot ="""
#!/bin/sh
# This has to be done in the ethoscope first initlization

#Install packages
#rm -R /root/.gnupg
#gpg --refresh-keys

pacman-key --init
pacman-key --populate
pacman-key --populate archlinuxarm
pacman -S archlinux-keyring archlinuxarm-keyring --noconfirm
pacman -Su --noconfirm

pacman -S LIST_OF_PACKAGES --noconfirm --needed

#manual install (no sure why we need this)
pacman -S glibc --noconfirm
pacman -S mariadb --noconfirm

#Uninstall packages
pacman -R logrotate --noconfirm

#install python packages
pip2 install --no-index --find-links=/home/alarm/python/ picamera MySQL-python GitPython

#Disable services
systemctl disable systemd-networkd

#Enable and start services
ip link set eth0 down
systemctl start ntpd.service
systemctl enable ntpd.service
systemctl enable fake-hwclock fake-hwclock-save.timer
systemctl start fake-hwclock
systemctl enable sshd.service
systemctl start sshd.service
netctl-auto enable wlan0
netctl-auto start wlan0
systemctl enable netctl-auto@wlan0.service
systemctl start netctl-auto@wlan0.service
systemctl enable netctl-ifplugd@wlan0.service
systemctl start netctl-ifplugd@wlan0.service
netctl enable eth0
netctl start eth0
systemctl enable netctl@eth0.service
systemctl start netctl@eth0.service
systemctl enable netctl-ifplugd@eth0.service
systemctl start netctl-ifplugd@eth0.service
systemctl enable ethoscope_device.service
systemctl enable ethoscope_update.service
systemctl disable auditd

#MYSQL
cp /home/alarm/mysql/my.cnf /etc/mysql/my.cnf
mysql_install_db --user=mysql --basedir=/usr --datadir=/var/lib/mysql
systemctl start mysqld.service
systemctl enable mysqld.service

# mysql credentials
USER_NAME=ethoscope
PASSWORD=ethoscope
DB_NAME=ethoscope_db

mysql -u root -e "CREATE USER \"$USER_NAME\"@'localhost' IDENTIFIED BY \"$PASSWORD\""
mysql -u root -e "CREATE USER \"$USER_NAME\"@'%' IDENTIFIED BY \"$PASSWORD\""
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO \"$USER_NAME\"@'localhost' WITH GRANT OPTION;"
mysql -u root -e "GRANT ALL PRIVILEGES ON *.* TO \"$USER_NAME\"@'%' WITH GRANT OPTION;"



#Ethoscope software
cd TARGET_GIT_INSTALL
# this allows to pull from other nodes
for i in $(seq 2 5); do git remote set-url origin --add git://NODE_SUBNET.$i/BARE_GIT_NAME; done

git remote set-url origin --add UPSTREAM_GIT_REPO
git remote get-url --all origin

##Reserved for future use
cd TARGET_GIT_INSTALL/src
git checkout BRANCH

cd TARGET_GIT_INSTALL/src
pip install -e .[device]

echo MACHINE_ID > /etc/machine-id

#rm -- $0
"""



if __name__=="__main__":
    prepare_basic_arch("/dev/sdb","192.168.123","001", "ETHOSCOPE_WIFI","ETHOSCOPE_1234")