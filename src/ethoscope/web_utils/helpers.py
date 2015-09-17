
import subprocess
import random
import logging
import traceback
import git
import datetime
import os

def get_machine_info(path):
    """
    Reads the machine NAME file and returns the value.
    """
    try:
        with open(path,'r') as f:
            info = f.readline().rstrip()
        return info
    except Exception as e:
        logging.warning(traceback.format_exc(e))
        return 'Debug-'+str(random.randint(1,100))


def get_commit_version(commit):
    return {"id":str(commit),
            "date":datetime.datetime.utcfromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S')
                    }
def get_version():
    wd = os.getcwd()
    while wd != "/":
        try:
            repo = git.Repo(wd)
            commit = repo.commit()
            get_commit_version(commit)
        except git.InvalidGitRepositoryError:
            wd = os.path.dirname(wd)
    raise Exception("Not in a git Tree")





