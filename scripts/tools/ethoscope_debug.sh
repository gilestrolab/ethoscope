#!/bin/bash
FILENAME=ethoscope_debug.log
uname -a > ${FILENAME}
ifconfig -a >> ${FILENAME}
python --version >> ${FILENAME}
ping -c 1 8.8.8.8 >> ${FILENAME}
systemctl status {ethoscope_node, ethoscope_backup, 
ethoscope_results.mount}, 
ethoscope_update_node, ethoscope_video_backup, ethoscope_videos.mount} 
>> ${FILENAME}


