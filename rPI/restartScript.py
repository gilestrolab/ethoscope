from subprocess import call

call(["ps axf | grep server.py | grep -v grep | awk '{print \"kill -2 \" $1}' | sh"],shell=True)

call(["python2 server.py"],shell=True)
