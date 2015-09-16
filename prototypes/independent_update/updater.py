__author__ = 'quentin'

from git import Repo
from git import GitCommandError
import logging
import traceback




class BaseUpdater(object):

    _daemon = None

    def __init__(self,
                 git_working_dir):

        self._git_working_dir = git_working_dir
        self._working_repo = Repo(git_working_dir)
        self._origin = self._working_repo.remotes.origin


    def get_local_and_origin_commits(self):
        """
        Gets the id of the local head and the origin's.
        returned object are Commits, not strings. their unix TS can be access through``.committed_date``.
        """

        local_commit = self._working_repo.commit()
        active_branch = self._working_repo.active_branch
        origin_commit = self._origin.refs[str(active_branch)].commit
        # .committed_date
        return local_commit, origin_commit

    def update_active_branch(self):
        """
        Pull the new available files obly for the current branch. Then checks that commit matches
        """
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
        """
        Lists available branches. Useful in order to offer user the possibility to change branch.

        """
        self._origin.fetch()
        refs = self._origin.refs
        return [str(r).split("/")[-1] for r in refs[1:]]

    def change_branch(self, branch):
        """
        Change WD to a branch

        :param branch: name of the branch
        :type branch: str
        """

        self._origin.fetch()
        self._working_repo.git.checkout(branch)

    def restart_daemon(self):
        # TODO
        # I am not sure this class should actually deal with restarting any daemon. this should be handled by the parent bottle server
        pass


class DeviceUpdater(BaseUpdater):
    _daemon = "device.service"
    pass


class BareRepoUpdater(object):
    """
    A simple class to update the bare repo.
    All visible branches are updated.
    Hidden branches can be unlocked bu developers.
    """
    def __init__(self,git_working_dir):
        self._git_working_dir = git_working_dir
        self._working_repo = Repo(git_working_dir)
        self._origin = self._working_repo.remotes.origin


    def update_all_visible_branches(self):
        """
        Update all visible branches (for normal users, this will be master and dev).
        For developers, new branches can be discovered (see ``discover_branches``).
        :return:
        """
        branches = self._working_repo.branches

        for b in branches:
            try:
                self._origin.fetch(b)
            except GitCommandError as e:
                logging.error(traceback.format_exc(e))



    def discover_branches(self):
        """
        Force bare to discover new branches in the remote and sync them locally
        :return:
        """
        try:
            self._working_repo.git.fetch("origin","*:*")
        except GitCommandError as e:
            logging.error(traceback.format_exc(e))




# #This works, but mind root permission
# bare_updater = BareRepoUpdater("/srv/git/dummy_repo_bare.git")
# print bare_updater._working_repo.branches
# bare_updater.discover_branches()
# bare_updater.update_all_visible_branches()
#


#
updater = DeviceUpdater("/tmp/dummy_repo")
print updater.available_branches()
updater.change_branch("another_branch")
updater.update_active_branch()
#
