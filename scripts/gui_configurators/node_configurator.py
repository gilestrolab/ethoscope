#! /usr/bin/python3

import subprocess
import uuid
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

def getNetworkinfo():
    with subprocess.Popen(["ifconfig"], stdout=subprocess.PIPE) as proc:
        info = proc.stdout.read()
    interfaces = info.decode("utf8").strip().split("\n\n")
    interfaces_info = {}
    for interface in interfaces:
        ifname = interface.split(": ")[0]
        try:
            mac = interface.split(": ")[1].strip(" ").split("ether ")[1][0:17]
        except:
            mac = None
        try:
            ip = interface.split(": ")[1].strip(" ").split("inet ")[1][0:14].split(" ")[0]
        except:
            ip = None
        interfaces_info[ifname] = {"ifname": ifname, "mac": mac, "ip": ip}

    with subprocess.Popen(["nmcli", "d"], stdout=subprocess.PIPE) as proc:
        nmcli_info = proc.stdout.read()
    nmcli_info = nmcli_info.decode("utf-8").strip().split("\n")[1:]
    for entry in nmcli_info:
        entry = entry.split(' ')
        filtered = list([_f for _f in entry if _f])
        for id,obj in list(interfaces_info.items()):
            if id in filtered[0]:
                obj["status"] = filtered[2]
                obj["type"] = filtered[1]
                obj["name"] = " ".join(filtered[3:])
    return interfaces_info


def get_networmanager_file(ifname):
    local_ip = "{0}.{1}.{2}".format(ip_entry[0].get(), ip_entry[2].get(), ip_entry[4].get())
    if ifname[0] == "w":
        instruction = "nmcli connection add type wifi connection.autoconnect-priority -999 conection.id wifi_local \
connection.interface-name {0} ipv4.method manual ipv4.addr {1}.1/24 ipv4.dns 8.8.8.8 ipv4.dns-search {1}.1 wifi.ssid={2} \
wifi-security.auth-alg open wifi-security.key-mgmt wpa-psk wifi-security.psk {3}"\
        .format(ifname, local_ip,entry_ssid.get(),entry_pass.get())
        subprocess.call(instruction.split(" "))
        instruction = "nmcli connection reload"
        subprocess.call(instruction.split(" "))
    elif ifname[0] == "e":
        instruction = "nmcli connection add type ethernet connection.autoconnect-priority -999 \
connection.id wired_local connection.interface-name {0} ipv4.method manual ipv4.addr {1}.1/24 ipv4.dns 8.8.8.8 \
ipv4.dns-search {1}.1".format(ifname.strip(" "),local_ip.strip())
        subprocess.call(instruction.split(" "))
        instruction = "nmcli connection reload"
        subprocess.call(instruction.split(" "))
    
def get_dhcpd_conf():
    local_ip = "{0}.{1}.{2}".format(ip_entry[0].get(), ip_entry[2].get(), ip_entry[4].get())
    text = """
option domain-name-servers 8.8.8.8, 8.8.4.4;
option subnet-mask 255.255.255.0;
option routers {0}.1;
subnet {0}.0 netmask 255.255.255.0 {{
  range {0}.5 {0}.105;

  host unifi{{
        hardware ethernet {1};
        fixed-address {0}.254;
  }}
}}
""".format(local_ip,entry_unifi_mac.get())

    return text


def configure():
    # 1. install needed packages not included in normal distro
    # 1.1 update whole system
    subprocess.call(["sudo", "pacman", "-Syu", "--noconfirm"])
    # 1.2 tools for developers
    instruction = "pacman -S base-devel git gcc-fortran rsync wget fping --noconfirm --needed"
    subprocess.call(instruction.split(" "))
    # 1.3 utilities
    instruction = "pacman -S ntp bash-completion openssh --noconfirm --needed"
    subprocess.call(instruction.split(" "))
    # 1.4 so we can set up a dns
    instruction = "pacman -S dnsmasq --noconfirm --needed"
    subprocess.call(instruction.split(" "))
    # 1.5 pre-installing dependencies will save compiling time on python packages
    instruction = "pacman -S python-pip python-numpy python-bottle python-pyserial mysql-python python-netifaces python-cherrypy python-zeroconf --noconfirm --needed"
    subprocess.call(instruction.split(" "))
    # 1.6 mariadb
    instruction = "pacman -S mariadb --noconfirm --needed"
    subprocess.call(instruction.split(" "))
    # 1.7 setup Wifi
    instruction = "pacman -S wpa_supplicant libev --noconfirm --needed"
    subprocess.call(instruction.split(" "))

    # 2. create the bare repository
    UPSTREAM_GIT_REPO = "https://github.com/gilestrolab/ethoscope.git"
    LOCAL_BARE_PATH = "/srv/git/ethoscope.git"

    instruction = "mkdir -p /srv/git"
    subprocess.call(instruction.split(" "))
    instruction = "git clone --bare {0} {1}".format(UPSTREAM_GIT_REPO, LOCAL_BARE_PATH)
    subprocess.call(instruction.split(" "))

    # 3. Node Software
    # variables
    TARGET_UPDATER_DIR = "/opt/ethoscope_updater"
    TARGET_GIT_INSTALL = "/opt/ethoscope-git"

    # Create a local working copy from the bare repo on node
    print('Installing ethoscope package')

    instruction = "git clone {0} {1}".format(LOCAL_BARE_PATH, TARGET_GIT_INSTALL)
    subprocess.call(instruction.split(" "))

    # IMPORTANT this is if you want to work on the "dev" branch otherwise, you are using "master"
    instruction = "git checkout python3.7"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL).wait()

    # we install with pip
    instruction = "pip2 install -e ."
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/node_src").wait()

    # 4. Network
    # see how to setup router
    NODE_IP = "{0}.{1}.{2}.1".format(ip_entry[0].get(), ip_entry[2].get(), ip_entry[4].get())

    # configure interface for local network
    INTERFACE = interfaces_var.get().split(":")[1].strip("(").strip(")")
    MAC = netinfo[INTERFACE]["mac"]
    get_networmanager_file(INTERFACE)

    #network manager reload
    subprocess.call(["nmcli", "connection", "reload"])

    # configuring dns server:
    with open("/etc/dnsmasq.conf", "w") as f:
        f.write("interface={}\n".format(INTERFACE))
        f.write("dhcp-option=6,{}\n".format(NODE_IP))
        f.write("no-hosts\n")
        f.write("addn-hosts=/etc/hosts\n")

    # so that http://node can be our homepage
    with open("/etc/hosts", "a") as f:
        f.write("{} node\n".format(NODE_IP))

    # 5. Daemons
    instruction = "systemctl start ntpd.service"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable ntpd.service"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl start sshd.service"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable sshd.service"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl start git-daemon.socket"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable git-daemon.socket"
    subprocess.call(instruction.split(" "))

    # 6. specif daemons
    # modify .service file to add the desired local ip range.
    LOCAL_IP = "{}.{}.{}.0".format(ip_entry[0].get(), ip_entry[2].get(), ip_entry[4].get())


    with open(TARGET_GIT_INSTALL + "/scripts/ethoscope_node.service", "r+") as f:
        content = f.read()
        content = content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/server.py",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/server.py -r {}".format(LOCAL_IP))
        f.seek(0)
        f.write(content)

    with open(TARGET_GIT_INSTALL + "/scripts/ethoscope_backup.service", "r+") as f:
        content = f.read()
        content = content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/backup_tool.py",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/backup_tool.py -r {}".format(LOCAL_IP))
        f.seek(0)
        f.write(content)

    with open(TARGET_GIT_INSTALL + "/scripts/ethoscope_video_backup.service", "r+") as f:
        content = f.read()
        content = content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/video_backup_tool.py",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/video_backup_tool.py -r {}".format(LOCAL_IP))
        f.seek(0)
        f.write(content)



    instruction = "cp ./ethoscope_node.service /etc/systemd/system/ethoscope_node.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/scripts").wait()
    instruction = "cp ./ethoscope_backup.service /etc/systemd/system/ethoscope_backup.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/scripts").wait()
    instruction = "cp ./ethoscope_video_backup.service /etc/systemd/system/ethoscope_video_backup.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/scripts").wait()
    instruction = "systemctl daemon-reload"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable ethoscope_node.service"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable ethoscope_video_backup.service"
    subprocess.call(instruction.split(" "))

    # updater for node software
    UPDATER_LOCATION_IN_GIT = "scripts/ethoscope_updater"
    ROUTER_IP = "{}.{}.{}.254".format(ip_entry[0].get(), ip_entry[2].get(), ip_entry[4].get())

    instruction = "ln -s {0}/{1} {2} -r".format(TARGET_GIT_INSTALL, UPDATER_LOCATION_IN_GIT, TARGET_UPDATER_DIR)
    subprocess.call(instruction.split(" "))

    with open(TARGET_UPDATER_DIR + "/ethoscope_update_node.service", "r+") as f:
        content = f.read()
        content = content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope_updater/update_server.py -g /opt/ethoscope-git -b /srv/git/ethoscope.git",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope_updater/update_server.py -g /opt/ethoscope-git -b /srv/git/ethoscope.git -r {}".format(ROUTER_IP))
        f.write(content)

    instruction = "cp ethoscope_update_node.service /etc/systemd/system/ethoscope_update_node.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_UPDATER_DIR).wait()

    instruction = "systemctl daemon-reload"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable ethoscope_update_node.service"
    subprocess.call(instruction.split(" "))

    # 7. Time
    instruction = "timedatectl set-timezone Etc/GMT{}".format(entry_timezone.get().strip(" "))
    subprocess.call(instruction.split(" "))

    # 8. keep time also without internet in node
    with open("/etc/ntp.conf", "a") as f:
        f.write("server 127.127.1.1\n")
        f.write("fudge 127.127.1.1 stratum 12\n")

    # 9. CONFIGURING DHCPD (only if not router)
    if router.get() == "unifi":
        #set up and enable dhcpd
        instruction = "pacman -S dhcp --noconfirm --needed"
        subprocess.call(instruction.split(" "))
        with open("/etc/dhcpd.conf","w") as f:
            t = get_dhcpd_conf()
            f.write(t)
        instruction = "systemctl enable dhcpd4.service"
        subprocess.call(instruction.split(" "))

    time.sleep(10)
    print("All done, system will reboot in one minute, or reboot manually now.")
    time.sleep(60)
    #subprocess.run("reboot")
    exit()

if __name__ == "__main__":
    # get the network information
    netinfo = getNetworkinfo()

    window = Tk()
    window.title("Node configuration tool")
    window.geometry("400x350")
    frame_network = Frame(window)

    #ROW 0
    frame_network.pack() #.grid(column=0, row=0, columnspan=3)
    lb_network = Label(frame_network, text="Local Network:", font=("verdana", 15))
    lb_network.grid(column=0, row=0, columnspan=3)

    #ROW 1
    available_interfaces = []
    for ifname, info in list(netinfo.items()):
        if info["ifname"] != "lo" and info["mac"] != None and info["status"] != "connected":
            # available interface
            available_interfaces.append(info["name"] + ":(" + info["ifname"] + ")")

    if len(available_interfaces) < 1:
        print("No available interfaces detected. Please attach a new ethernet card or wifi dongle to the computer.")
        exit()

    interfaces_var = StringVar(frame_network)
    interfaces_var.set(available_interfaces[0])

    lb_option_interface = Label(frame_network,text="Select interface to use:").grid(column=0,row=1)
    option_interface = OptionMenu(frame_network, interfaces_var, *available_interfaces)
    option_interface.grid(column=1, row=1, sticky=W)

    # ROW 5
    lb_ssid = Label(frame_network, text="SSID").grid(column=0, row=2)
    lb_pass = Label(frame_network, text="Password:").grid(column=0, row=3)
    entry_ssid = Entry(frame_network, width=20)
    entry_ssid.grid(column=1, row=2, sticky=W)
    entry_pass = Entry(frame_network, width=20)
    entry_pass.grid(column=1, row=3, sticky=W)
    entry_ssid.insert(END,"ETHOSCOPE_WIFI")
    entry_pass.insert(END,"ETHOSCOPE_1234")

    #ROW 2
    lb_ip = ttk.LabelFrame(frame_network, text="Local ip range:")
    lb_ip.grid(column=0, row=4,columnspan=2)
    ip_entry = [Entry(lb_ip, width=3), Label(lb_ip, text="."), Entry(lb_ip, width=3), Label(lb_ip, text="."),
                Entry(lb_ip, width=3), Label(lb_ip, text=".0")]
    c = 0
    defaultip = ["192", "168", "123"]
    i = 0
    for range in ip_entry:
        if isinstance(range, Entry):
            range.insert(END, defaultip[i])
            i += 1
        range.grid(column=c, row=2)
        c += 1



    # ROW 4
    lb_router = Label(window,text="Type of access point for local network:").pack(pady=10)
    frame_router = Frame(window)
    frame_router.pack() #.grid(column=0,row=4,columnspan=4)


    router = StringVar()
    router.set("unifi")
    default_MAC = "00:AB:CD:EF:00:00"
    r = 5
    for text, value in [("Unifi -> Unifi MAC_Address:", "unifi"), ("Router", "router")]:
        Radiobutton(frame_router, text=text, value=value, variable=router, anchor=W).grid(column=0, row=r)
        r += 1


    entry_unifi_mac = Entry(frame_router,width=15)
    entry_unifi_mac.grid(column=1,row=5)
    entry_unifi_mac.insert(END,default_MAC)


    #lb_directories = Label(window, text="Directories:", font=("verdana", 15), anchor=W).grid(column=0, row=5, sticky=W)
    #lb_result_dir = Label(window, text="Results directory:").grid(column=0, row=6, sticky=E)
    #entry_result_dir = Entry(window)
    #entry_result_dir.insert(END, "/ethoscope_results")
    #entry_result_dir.grid(column=1, row=6, sticky=W)

    frame_time = Frame(window)
    frame_time.pack() #.grid(column=0, row=5, columnspan=4)
    lb_time = Label(frame_time,text="Local time for the system:",font=("verdana", 15)).grid(column=0,row=0, columnspan=4)
    lb_timezone = Label(frame_time, text="Time Zone: GMT").grid(column=0, row=7, sticky=E)
    entry_timezone = Entry(frame_time, width=4)
    entry_timezone.insert(END, "+0")
    entry_timezone.grid(column=1, row=7, padx=0,sticky=W)
    lb_timezone_help = Label(frame_time, text="+ or - differene with GMT i.e +5,-1,...").grid(column=2, row=7, sticky=W)

    btn_configure = Button(window, text="Configure", command=configure)
    btn_configure.pack(pady=10) #.grid(column=2, row=8)
    window.mainloop()
