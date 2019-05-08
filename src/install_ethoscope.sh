#!/bin/bash
#================================================================
# HEADER
#================================================================
#% SYNOPSIS
#+    ${SCRIPT_NAME} [-h] [-o[SD_PATH]] [-i[ethoscope_ID]]
#%
#% DESCRIPTION
#%    Ethoscope Installation script
#%    Creates an SD card ready to go into an ethoscope
#%
#% OPTIONS
#%    -o [path]                 Set the pat to the SD CARD
#%    -i [id]                   Specify the ethoscope ID (integer)
#%    -f [filename]             Use the specidied filename
#%    -h                        Print this help
#%
#% EXAMPLES
#%    ${SCRIPT_NAME} -o /dev/mmcblk0 -i 12
#%
#================================================================
#- IMPLEMENTATION
#-    version         ${SCRIPT_NAME} 1.0
#-    author          Giorgio Gilestro
#-    copyright       Copyright (c) http://lab.gilest.ro
#-    license         GNU General Public License
#-
#================================================================
#  HISTORY
#     2018/10/03 : ggilestro : Script created and released
#     2018/10/07 : ggilestro : added automatic check for BSD and changed shebang
# 
#================================================================
# END_OF_HEADER
#================================================================


   #== usage functions ==#
SCRIPT_HEADSIZE=$(head -200 ${0} |grep -n "^# END_OF_HEADER" | cut -f1 -d:)
SCRIPT_NAME="$(basename ${0})"

usage() { printf "Usage: "; head -${SCRIPT_HEADSIZE:-99} ${0} | grep -e "^#+" | sed -e "s/^#+[ ]*//g" -e "s/\${SCRIPT_NAME}/${SCRIPT_NAME}/g" ; }
usagefull() { head -${SCRIPT_HEADSIZE:-99} ${0} | grep -e "^#[%+-]" | sed -e "s/^#[%+-]//g" -e "s/\${SCRIPT_NAME}/${SCRIPT_NAME}/g" ; exit 1;}
scriptinfo() { head -${SCRIPT_HEADSIZE:-99} ${0} | grep -e "^#-" | sed -e "s/^#-//g" -e "s/\${SCRIPT_NAME}/${SCRIPT_NAME}/g"; }


WEB_URL="https://s3.amazonaws.com/ethoscope/"
OS_FILE="ethoscope_os_20160721.tar.gz"
TMP_DIR=/tmp
MIN_CARD_SIZE=8589934592 #8GB


TAR_CMD=`which bsdtar || which tar || exit 127`

prompt_confirm() {
  while true; do
    read -r -n 1 -p "${1:-Continue?} [y/n]: " REPLY
    case $REPLY in
      [yY]) echo ; return 0 ;;
      [nN]) echo ; return 1 ;;
      *) printf " \033[31m %s \n\033[0m" "invalid input"
    esac 
  done  
}

#Check if options were passed
while getopts o:i:f:h: option
  do
    case "${option}"
    in
      o) SDCARD=${OPTARG};;
      i) ID=${OPTARG};;
      i) LOCAL_FILE=${OPTARG};;
      h) usagefull;;
    esac
  done

#Check root permissions or exit
if [[ $EUID -ne 0 ]]; then
   echo "Error: This script must be run as root. Exiting now." 
   exit 1
fi


echo "Welcome to the ETHOSCOPE installation script".
echo "This program will help you create a new SD card for your machine."
read -p "Please press the Enter key to get started."


#if SD CARD Path is not passed by the user, try to detect it automatically
if [[ -z $SDCARD ]]; then
   echo "You have not passed a path to your SD card." 
   echo "I will try to identify this automatically for you"
   echo "To start, make sure your SD card is NOT inserted into this machine".
   read -p "If it is currently inserted, please remove it now, then press the Enter key to continue"
   lsblk -dp | grep -o '^/dev[^ ]*' > ${TMP_DIR}/before-sd

   read -p "Now please insert the card and press the Enter key when ready."
   sleep 2
   lsblk -dp | grep -o '^/dev[^ ]*' > ${TMP_DIR}/after-sd

   NUMCARD=`diff ${TMP_DIR}/before-sd ${TMP_DIR}/after-sd | grep "^>" | wc -l`
   SDCARD=`diff ${TMP_DIR}/before-sd ${TMP_DIR}/after-sd | egrep "^>" | sed "s/> //"`
    
   if (( $NUMCARD > 1 )); then
      echo "Something is wrong. I found more than 1 card. Exiting now"
      exit 1
   fi

   if [[ -z $SDCARD ]]; then
      echo "I could not find any card. Exiting now."
      exit 1
   fi

   CARDSIZE=`blockdev --getsize64 $SDCARD`
   if (( $CARDSIZE <= $MIN_CARD_SIZE )); then
      echo "The card size is too small. You should be using a card with at least 8GB capacity (32GB reccomended). Exiting now."
      exit 1
   fi
   
   echo "I found a card on path $SDCARD with size ${CARDSIZE} byte"
   prompt_confirm "Do you want to continue using this card?" || exit 0
fi

#If Ethoscope ID was not passed on commandline, prompt the user for it
if [[ -z $ID ]]; then
   echo "You have not passed an ID for the ethoscope you are making." 
   read -p "Which number do you want to assign to this machine? If this is the first machine you are creating, use 1: " ID

   if ! [[ "$ID" =~ ^[0-9]+$ ]]
      then
        echo "Sorry integers only"
        exit 1
   fi

   prompt_confirm "This will be ethoscope_`printf "%03d" $ID`. Do you want to continue?" || exit 0
fi

ID=`printf "%03d" $ID`

#All the info are gathered, proceed.
echo "I will now create a card for ethoscope $ID using the card in $SDCARD"
echo "The current content of the card is going to be completely erased"
prompt_confirm "Are you sure this is what you want to do?" || exit 0

#Create partitions
echo -e "Creating partitions\n"

# to create the partitions programatically (rather than manually)
# we're going to simulate the manual input to fdisk
# The sed script strips off all the comments so that we can 
# document what we're doing in-line with the actual commands
# Note that a blank line (commented as "default" will send a empty
# line terminated with a newline to take the fdisk default.
sed -e 's/\s*\([\+0-9a-zA-Z]*\).*/\1/' << EOF | fdisk ${SDCARD}
  o # clear the in memory partition table
  n # new partition
  p # primary partition
  1 # partition number 1
    # default - start at beginning of disk 
  +100M # 100 MB boot parttion
  t # set partition type to
  c # DOS
  n # new partition
  p # primary partition
  2 # partion number 2
    # default, start immediately after preceding partition
    # default, extend partition to end of disk
  p # print the in-memory partition table
  w # write the partition table
  q # and we're done
EOF

echo -e "Partitions succesfully created\n"

#Formatting partitions
echo "Formatting the partitions"
mkdir -p ${TMP_DIR}/{boot,root}

if [[ $SDCARD = *"mmcbl"*  ]] ; then
   PART1=${SDCARD}p1
   PART2=${SDCARD}p2
fi

if [[ $SDCARD == "/dev/sd"* ]] ; then
   PART1=${SDCARD}1
   PART2=${SDCARD}2
fi

if [[ -z $PART1 ]]; then
   echo "Problem finding partitions. Exiting"
   exit 1
fi

umount ${PART1} || [ $? -eq 1 ]
umount ${PART2} || [ $? -eq 1 ]

mkfs.vfat ${PART1} || exit 1
mount ${PART1} ${TMP_DIR}/boot || exit 1
mkfs.ext4 ${PART2} || exit 1 
mount ${PART2} ${TMP_DIR}/root || exit 1

if [[ -z $LOCAL_FILE ]]; then
  echo "Downloading latest version of the ethoscope OS (if not already present). This may take a while"
  wget -c ${WEB_URL}${OS_FILE} -P ${TMP_DIR} || exit 1
  LOCAL_FILE=${TMP_DIR}/${OS_FILE}
fi

echo "Uncompressing the file - this may take some time. Please wait"

${TAR_CMD} -vxpf ${LOCAL_FILE} -C ${TMP_DIR}/root || exit 1
sync
mv ${TMP_DIR}/root/boot/* ${TMP_DIR}/boot/

echo "now writing the information regarding ID"
<<<<<<< HEAD
UUID=`blkid $PART1 | egrep '[0-9A-F]{4}-[0-9A-F]{4}' -o`
echo ${ID}-${UUID} > ${TMP_DIR}/root/etc/machine-id
echo "ethoscope_$ID" > ${TMP_DIR}/root/etc/machine-name
echo "ethoscope_$ID" > ${TMP_DIR}/root/etc/hostname
=======
mid="$ID`uuidgen`"
echo ${mid//-/} | cut -c 1-32 > ${TMP_DIR}/root/etc/machine-id
echo "ETHOSCOPE_$ID" > ${TMP_DIR}/root/etc/machine-name
echo "ETHOSCOPE_$ID" > ${TMP_DIR}/root/etc/hostname
>>>>>>> 4f1c7ea... Update install_ethoscope.sh

umount ${TMP_DIR}/{boot,root}
rm -f ${TMP_DIR}/{before-sd,after-sd}

echo "All done! You can now remove the card and insert it into your new ethoscope"
