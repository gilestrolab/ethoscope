__author__ = 'quentin'

from git import Repo
import logging


class BaseUpdater(object):

    _daemon = None

    def __init__(self,
                 git_working_dir):

        self._git_working_dir = git_working_dir
        self._working_repo = Repo(git_working_dir)
        self._origin = self._working_repo.remotes.origin


    def get_local_and_origin_commits(self):
        local_commit = self._working_repo.commit()
        active_branch = self._working_repo.active_branch
        origin_commit = self._origin.refs[str(active_branch)].commit
        # .committed_date
        return local_commit, origin_commit

    def update_active_branch(self):
        logging.info("Pulling origin")
        self._origin.pull()
        logging.info("Pulled")
        c_local, c_orig = self.get_local_and_origin_commits()
        logging.info("local is at %s, origin at %s" % ( str(c_local), str(c_orig)))
        if c_local != c_orig:
            msg = "Update failed. Local is at %s" % str(c_local)
            logging.error(msg)
            raise Exception(msg)

    def available_branches(self):
        self._origin.fetch()
        refs = self._origin.refs
        return [str(r).split("/")[-1] for r in refs[1:]]

    def change_branch(self, branch):
        self._origin.fetch()
        self._working_repo.git.checkout(branch)


class DeviceUpdater(BaseUpdater):
    _daemon = "device.service"
    pass


updater = DeviceUpdater("/tmp/dummy_repo")
print updater.available_branches()
updater.change_branch("dev")
updater.update_active_branch()

