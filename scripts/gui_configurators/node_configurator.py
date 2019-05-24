#! /usr/bin/python3

import subprocess
import uuid
import time

# try to load tkinter, if tk is not installed, install it first.
try:
    from tkinter import *
    import tkinter.ttk as ttk
except Exception as e:
    subprocess.call(["sudo", "pacman", "-Sy", "tk"])

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
        filtered = list(filter(None, entry))
        interfaces_info[filtered[0]]["status"] = filtered[2]
        interfaces_info[filtered[0]]["type"] = filtered[1]
        interfaces_info[filtered[0]]["name"] = " ".join(filtered[3:])
    return interfaces_info


def get_networmanager_file(ifname, mac):
    unique = uuid.uuid4()
    if ifname[0] == "w":
        file = """[connection]
        id=ETHOSCOPE_WIFI
        uuid={0}
        type=wifi
        permissions=

        [wifi]
        mac-address={1}
        mac-address-blacklist=
        mode=infrastructure
        ssid=ETHOSCOPE_WIFI

        [wifi-security]
        auth-alg=open
        key-mgmt=wpa-psk
        psk=ETHOSCOPE_1234

        [ipv4]
        dns-search=
        method=auto

        [ipv6]
        addr-gen-mode=stable-privacy
        dns-search=
        method=auto
        """.format(unique, mac)
    elif ifname[0] == "e":
        file = """
        [connection]
        id=Wired_local
        uuid={0}
        type=ethernet
        autoconnect-priority=-999
        permissions=

        [ethernet]
        mac-address={1}
        mac-address-blacklist=

        [ipv4]
        address1=192.168.123.1/24
        dns-search=
        method=manual

        [ipv6]
        addr-gen-mode=stable-privacy
        dns-search=
        method=auto
        """.format(unique, mac)

    return file


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
    instruction = "pacman -S python2-pip python2-numpy python2-bottle python2-pyserial mysql-python python2-netifaces python2-cherrypy python2-futures --noconfirm --needed"
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
    instruction = "git checkout -b master"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL)

    # we install with pip
    instruction = "pip2 install -e ."
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/node_src")

    # 4. Network
    # see how to setup router
    NODE_IP = "{0}.{1}.{2}.1".format(ip_entry[0].get(), ip_entry[2].get(), ip_entry[4].get())

    # configure interface for local network
    INTERFACE = interfaces_var.get().split("-")[1].strip("(").strip(")")
    MAC = netinfo[INTERFACE]["mac"]
    if INTERFACE[0] == "w":
        wifi_file = get_networmanager_file(INTERFACE, MAC)
        with open("/etc/NetworkManager/system-connections/ETHOSCOPE_WIFI", "w") as f:
            f.write(wifi_file)
    elif INTERFACE[0] == "e":
        eth_file = get_networmanager_file(INTERFACE, MAC)
        with open("/etc/NetworkManager/system-connections/Wired_local", "w") as f:
            f.write(eth_file)

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
        content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/server.py",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/server.py -r {}".format(LOCAL_IP))

    with open(TARGET_GIT_INSTALL + "/scripts/ethoscope_backup.service", "r+") as f:
        content = f.read()
        content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/backup_tool.py",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/backup_tool.py -r {}".format(LOCAL_IP))

    with open(TARGET_GIT_INSTALL + "/scripts/ethoscope_video_backup.service", "r+") as f:
        content = f.read()
        content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/video_backup_tool.py",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope-git/node_src/scripts/video_backup_tool.py -r {}".format(LOCAL_IP))



    instruction = "cp ./ethoscope_node.service /etc/systemd/system/ethoscope_node.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/scripts")
    instruction = "cp ./ethoscope_backup.service /etc/systemd/system/ethoscope_backup.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/scripts")
    instruction = "cp ./ethoscope_video_backup.service /etc/systemd/system/ethoscope_video_backup.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_GIT_INSTALL + "/scripts")
    instruction = "systemctl daemon-reload"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable ethoscope_node.service"
    subprocess.call(instruction.split(" "))
    instruction = "systemctl enable ethoscope_video_backup.service"
    subprocess.call(instruction.split(" "))

    # updater for node software
    UPDATER_LOCATION_IN_GIT = "scripts/ethoscope_updater"
    instruction = "cp {0}/{1} {2} -r".format(TARGET_GIT_INSTALL, UPDATER_LOCATION_IN_GIT, TARGET_UPDATER_DIR)
    subprocess.call(instruction.split(" "))

    with open(TARGET_UPDATER_DIR + "/ethoscope_update_node.service", "r+") as f:
        content = f.read()
        content.replace("ExecStart=/usr/bin/python2  /opt/ethoscope_updater/update_server.py -g /opt/ethoscope-git -b /srv/git/ethoscope.git",
                        "ExecStart=/usr/bin/python2  /opt/ethoscope_updater/update_server.py -g /opt/ethoscope-git -b /srv/git/ethoscope.git -r {}".format(LOCAL_IP))

    instruction = "cp ethoscope_update_node.service /etc/systemd/system/ethoscope_update_node.service"
    subprocess.Popen(instruction.split(" "), cwd=TARGET_UPDATER_DIR)

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

    print("All done, system will reboot in one minute, or reboot manually now.")
    time.sleep(60)
    subprocess.run("reboot")


if __name__ == "__main__":
    # get the network information
    netinfo = getNetworkinfo()

    window = Tk()
    window.title("Node configuration tool")
    window.geometry("1024x600")
    frame_network = Frame(window)
    frame_network.grid(column=0, row=0, columnspan=3)
    lb_network = Label(frame_network, text="Network parameters for local network (ethoscopes):", font=("verdana", 15))
    lb_network.grid(column=0, row=0, columnspan=3, sticky=W)

    available_interfaces = []
    for ifname, info in netinfo.items():
        if info["ifname"] != "lo" and info["mac"] != None and info["status"] == "connected":
            # available interface
            available_interfaces.append(info["name"] + "-(" + info["ifname"] + ")")

    if len(available_interfaces) < 1:
        print("No available interfaces detected. Please attach a new ethernet card or wifi dongle to the computer.")
        exit()

    interfaces_var = StringVar(window)
    interfaces_var.set(available_interfaces[0])

    option_interface = OptionMenu(window, interfaces_var, *available_interfaces)
    option_interface.grid(column=0, row=1)

    interface = StringVar()
    interface.set("eth")
    r = 2
    for text, value in [("Wifi", "wifi"), ("Ethernet", "eth")]:
        Radiobutton(frame_network, text=text, value=value, variable=interface).grid(column=0, row=r, sticky=W)
        r += 1

    lb_ssid = Label(frame_network, text="SSID").grid(column=1, row=1, sticky=E)
    lb_pass = Label(frame_network, text="Pass").grid(column=3, row=1, sticky=W)
    entry_ssid = Entry(frame_network, width=20).grid(column=2, row=1, sticky=W)
    entry_pass = Entry(frame_network, width=20).grid(column=4, row=1, sticky=W)

    lb_ip = ttk.LabelFrame(frame_network, text="Subnet ip range:")
    lb_ip.grid(column=0, row=4, padx=1)
    ip_entry = [Entry(lb_ip, width=3), Label(lb_ip, text="."), Entry(lb_ip, width=3), Label(lb_ip, text="."),
                Entry(lb_ip, width=3), Label(lb_ip, text=".0")]
    c = 0
    defaultip = ["192", "168", "123"]
    i = 0
    for range in ip_entry:
        if isinstance(range, Entry):
            range.insert(END, defaultip[i])
            i += 1
        range.grid(column=c, row=0)
        c += 1

    lb_directories = Label(window, text="Directories:", font=("verdana", 15), anchor=W).grid(column=0, row=5, sticky=W)
    lb_result_dir = Label(window, text="Results directory:").grid(column=0, row=6, sticky=W)
    entry_result_dir = Entry(window)
    entry_result_dir.insert(END, "/ethoscope_results")
    entry_result_dir.grid(column=1, row=6, sticky=W)

    lb_timezone = Label(window, text="Time Zone: GMT").grid(column=0, row=7, sticky=W)
    entry_timezone = Entry(window, width=4)
    entry_timezone.insert(END, "+0")
    entry_timezone.grid(column=1, row=7, padx=0)
    lb_timezone_help = Label(window, text="Format + or - differene with GMT i.e +5,-1,...").grid(column=2, row=7)

    btn_configure = Button(window, text="Configure", command=configure)
    btn_configure.grid(column=4, row=8)
    window.mainloop()
