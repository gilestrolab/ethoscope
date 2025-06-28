from git import Repo, GitCommandError, Remote
import logging
import traceback
import os
import subprocess

from typing import Dict, Tuple

class DeviceUpdateError(Exception):
    """Custom exception raised when device updates fail."""
    pass


class DeviceUpdater:
    """
    A class to manage and update a device's Git repository.

    It handles pulling updates from the remote repository, managing branches,
    and creating Python eggs after updates.
    """

    def __init__(self, git_working_dir: str, remote_name: str = "origin"):
        """
        Initializes the DeviceUpdater with the given repository path and remote name.

        :param git_working_dir: Path to the device's Git repository.
        :param remote_name: Name of the remote to interact with (default is 'origin').
        :raises DeviceUpdateError: If the provided directory is not a Git repository
                                   or if the specified remote does not exist.
        """
        self._git_working_dir = git_working_dir
        self._remote_name = remote_name
        try:
            self._working_repo: Repo = Repo(git_working_dir)
            logging.info(f"Initialized DeviceUpdater for repository at '{git_working_dir}'.")
        except GitCommandError as e:
            logging.error(f"Failed to initialize DeviceUpdater: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError(f"The directory '{git_working_dir}' is not a valid Git repository.") from e
        except Exception as e:
            logging.error(f"Unexpected error during DeviceUpdater initialization: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("An unexpected error occurred during initialization.") from e

        # Verify that the remote exists
        try:
            self._remote: Remote = self._working_repo.remotes[self._remote_name]
            logging.debug(f"Using remote '{self._remote_name}'.")
        except IndexError:
            logging.error(f"Remote '{self._remote_name}' does not exist in the repository.")
            raise DeviceUpdateError(f"Remote '{self._remote_name}' not found in the repository.") from None

    def get_local_and_origin_commits(self) -> Tuple[Repo.commit, Repo.commit]:
        """
        Retrieves the latest commits from the local repository and the origin.

        :return: A tuple containing the local commit and the origin commit.
        """
        try:
            self._remote.fetch()
            local_commit = self._working_repo.commit()
            active_branch = self._working_repo.active_branch
            origin_commit = self._remote.refs[str(active_branch)].commit
            logging.debug(f"Local commit: {local_commit.hexsha}, Origin commit: {origin_commit.hexsha}")
            return local_commit, origin_commit
        except GitCommandError as e:
            logging.error(f"Failed to fetch commits: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("Failed to retrieve commit information.") from e
        except Exception as e:
            logging.error(f"Unexpected error while getting commits: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("An unexpected error occurred while retrieving commits.") from e

    def update_active_branch(self) -> None:
        """
        Pulls updates for the active branch and verifies the update.

        :raises DeviceUpdateError: If the update fails.
        """
        try:
            logging.info("Pulling latest changes from origin.")
            self._remote.pull()
            logging.info("Pull completed.")
            local_commit, origin_commit = self.get_local_and_origin_commits()
            logging.info(f"Local commit: {local_commit.hexsha}, Origin commit: {origin_commit.hexsha}")

            if local_commit != origin_commit:
                msg = f"Update failed. Local commit ({local_commit.hexsha}) does not match origin commit ({origin_commit.hexsha})."
                logging.error(msg)
                raise DeviceUpdateError(msg)
            else:
                self.create_python_egg()
        except GitCommandError as e:
            logging.error(f"Failed to update active branch: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("Failed to update the active branch.") from e
        except Exception as e:
            logging.error(f"Unexpected error during branch update: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("An unexpected error occurred during branch update.") from e

    @property
    def active_branch(self):
        """
        Retrieves the current active branch.

        :return: The active Git branch.
        """
        try:
            return self._working_repo.active_branch
        except TypeError as e:
            logging.error(f"No active branch found: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("No active branch found.") from e
        except Exception as e:
            logging.error(f"Unexpected error while retrieving active branch: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("An unexpected error occurred while retrieving the active branch.") from e

    def available_branches(self) -> list:
        """
        Lists all available branches from the remote repository.

        :return: A list of branch names.
        """
        try:
            self._remote.fetch()
            refs = self._remote.refs
            branches = [ref.name.replace(f"{self._remote_name}/", "") for ref in refs]
            logging.debug(f"Available branches: {branches}")
            return branches
        except GitCommandError as e:
            logging.error(f"Failed to fetch available branches: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("Failed to retrieve available branches.") from e
        except Exception as e:
            logging.error(f"Unexpected error while listing branches: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("An unexpected error occurred while listing branches.") from e

    def change_branch(self, branch: str) -> None:
        """
        Changes the working directory to the specified branch.

        :param branch: Name of the branch to switch to.
        :raises DeviceUpdateError: If the branch change fails.
        """
        if not isinstance(branch, str):
            logging.error(f"Invalid branch type: {type(branch)}. Expected 'str'.")
            raise DeviceUpdateError("Branch name must be a string.")

        try:
            logging.info(f"Checking out branch '{branch}'.")
            self._working_repo.git.checkout(branch)
            logging.info(f"Switched to branch '{branch}'.")
        except GitCommandError as e:
            logging.error(f"Failed to checkout branch '{branch}': {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError(f"Failed to checkout branch '{branch}'.") from e
        except Exception as e:
            logging.error(f"Unexpected error while changing branch to '{branch}': {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError(f"An unexpected error occurred while changing to branch '{branch}'.") from e

    def create_python_egg(self) -> None:
        """
        Installs Python packages for the 'node' and 'device' components after updates.
        Uses modern pip editable installs instead of deprecated setup.py develop.
        :raises DeviceUpdateError: If package installation fails.
        """
        package_dirs = {
            'node': os.path.join(self._git_working_dir, 'src', 'node'),
            'device': os.path.join(self._git_working_dir, 'src', 'ethoscope')
        }
        try:
            for component, path in package_dirs.items():
                if not os.path.isdir(path):
                    msg = f"Directory '{path}' does not exist."
                    logging.error(msg)
                    raise DeviceUpdateError(msg)
                
                # Check if pyproject.toml exists to confirm modern packaging
                pyproject_path = os.path.join(path, 'pyproject.toml')
                if not os.path.isfile(pyproject_path):
                    msg = f"pyproject.toml not found in '{path}'. Modern packaging required."
                    logging.error(msg)
                    raise DeviceUpdateError(msg)
                
                logging.info(f"Installing Python package for '{component}' from '{path}'.")
                
                # Use pip install -e for editable installation
                result = subprocess.run([
                    'python', '-m', 'pip', 'install', '-e', path, 
                    '--use-pep517',  # Use modern build system
                    '--no-deps',     # Optional: skip dependencies if already installed
                    '--break-system-packages'  # Allow installation in system Python
                ], capture_output=True, text=True)
                
                if result.returncode != 0:
                    msg = f"Failed to install Python package for '{component}'. Error: {result.stderr}"
                    logging.error(msg)
                    raise DeviceUpdateError(msg)
                
                logging.info(f"Python package for '{component}' installed successfully.")
                logging.debug(f"Installation output: {result.stdout}")
                
        except DeviceUpdateError:
            raise
        except Exception as e:
            logging.error(f"Unexpected error during Python package installation: {e}")
            logging.debug(traceback.format_exc())
            raise DeviceUpdateError("An unexpected error occurred while installing Python packages.") from e


class BranchUpdateError(Exception):
    """Custom exception raised when branch updates fail."""
    pass


class BareRepoUpdater:
    """
    A class to update a bare Git repository.
    
    It handles updating all visible branches and discovering new branches
    for developers. Hidden branches can be unlocked by authorized developers.
    """

    def __init__(self, git_working_dir: str, remote_name: str = "origin"):
        """
        Initializes the BareRepoUpdater with the given repository path and remote name.

        :param git_working_dir: Path to the bare Git repository.
        :param remote_name: Name of the remote to fetch from (default is 'origin').
        :raises ValueError: If the provided directory is not a Git repository.
        :raises AttributeError: If the specified remote does not exist.
        """
        self._git_working_dir = git_working_dir
        self._remote_name = remote_name

        self.add_safe_directory()

        try:
            self._working_repo: Repo = Repo(git_working_dir)
            logging.info(f"Initialized RepoUpdater for repository at '{git_working_dir}'.")
        except GitCommandError as e:
            logging.error(f"Failed to initialize RepoUpdater: {e}")
            logging.debug(traceback.format_exc())
            raise ValueError(f"The directory '{git_working_dir}' is not a valid Git repository.") from e
        except Exception as e:
            logging.error(f"Unexpected error during RepoUpdater initialization: {e}")
            logging.debug(traceback.format_exc())
            raise

        # Verify that the remote exists
        try:
            self._remote: Remote = self._working_repo.remotes[self._remote_name]
            logging.debug(f"Using remote '{self._remote_name}'.")
        except IndexError:
            logging.error(f"Remote '{self._remote_name}' does not exist in the repository.")
            raise AttributeError(f"Remote '{self._remote_name}' not found in the repository.") from None

    def add_safe_directory(self) -> None:
        """
        Adds the repository directory to Git's safe.directory configuration if it's not already present.

        This method executes the following command if the directory is not already safe:
            sudo git config --system --add safe.directory /srv/git/ethoscope.git

        :raises BranchUpdateError: If adding the safe directory fails.
        """
        try:
            # Check if the directory is already in safe.directory
            check_cmd = [
                "git",
                "config",
                "--system",
                "--get-all",
                "safe.directory"
            ]
            check_result = subprocess.run(
                check_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Handle case where no safe.directory entries exist (exit code 1)
            if check_result.returncode == 0:
                # Split the output into lines and strip whitespace
                safe_directories = [line.strip() for line in check_result.stdout.splitlines()]
                logging.debug(f"Current safe.directories: {safe_directories}")

                if self._git_working_dir in safe_directories:
                    logging.info(f"Directory '{self._git_working_dir}' is already in safe.directory.")
                    return  # Directory is already safe; no action needed
            elif check_result.returncode == 1:
                # No safe.directory entries exist yet, which is normal
                logging.debug("No safe.directory entries found, will add the first one.")
                safe_directories = []
            else:
                # Some other error occurred
                raise subprocess.CalledProcessError(check_result.returncode, check_cmd, check_result.stdout, check_result.stderr)

            # Construct the Git command to add the safe.directory
            cmd = [
                "git",
                "config",
                "--system",
                "--add",
                "safe.directory",
                self._git_working_dir
            ]
            logging.info(f"Adding '{self._git_working_dir}' to Git's safe.directory.")

            # Execute the command using subprocess
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logging.info(f"Successfully added '{self._git_working_dir}' to safe.directory.")
            logging.debug(f"Git config output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            # Handle cases where 'unsafe directory' warning appears or config already exists
            if "already exists" in e.stderr.lower() or "already exists" in e.stdout.lower():
                logging.warning(f"Directory '{self._git_working_dir}' is already in safe.directory.")
                return
            # Don't treat "not found" as an error for the initial check
            if e.cmd[0] == "git" and "config" in e.cmd and "--get-all" in e.cmd and e.returncode == 1:
                logging.debug("No existing safe.directory configuration found.")
                return
            logging.error(f"Failed to add safe.directory: {e.stderr.strip()}")
            logging.debug(traceback.format_exc())
            raise BranchUpdateError(f"Failed to add safe.directory: {e.stderr.strip()}") from e
        except FileNotFoundError:
            logging.error("Git is not installed or not found in the system PATH.")
            raise BranchUpdateError("Git is not installed or not found in the system PATH.")
        except Exception as e:
            logging.error(f"An unexpected error occurred while adding safe.directory: {e}")
            logging.debug(traceback.format_exc())
            raise BranchUpdateError("An unexpected error occurred while adding safe.directory.") from e

    def update_all_visible_branches(self) -> Dict[str, bool]:
        """
        Updates all visible branches in the repository.

        For normal users, this typically includes 'master' and 'dev'.
        Developers might have additional branches discovered via other mechanisms.

        :return: A dictionary mapping branch names to their update status (True for success, False for failure).
        :raises BranchUpdateError: If none of the branches could be updated.
        """
        branches = self._working_repo.branches
        update_results: Dict[str, bool] = {}
        any_success = False

        if not branches:
            logging.warning("No branches found in the repository to update.")
            return update_results  # Return empty dict since there are no branches

        for branch in branches:
            branch_name = branch.name
            update_results[branch_name] = False  # Assume failure initially
            try:
                self.update_branch(branch_name)
                update_results[branch_name] = True
                any_success = True
                logging.info(f"Successfully updated branch '{branch_name}'.")
            except GitCommandError as git_err:
                logging.error(f"Git command failed while updating branch '{branch_name}': {git_err}")
                logging.debug(traceback.format_exc())
            except Exception as e:
                logging.error(f"Unexpected error while updating branch '{branch_name}': {e}")
                logging.debug(traceback.format_exc())

        if not any_success:
            error_message = "Could not update any branch. Please check your internet connection and repository permissions."
            logging.critical(error_message)
            raise BranchUpdateError(error_message)

        return update_results

    def update_branch(self, branch_name: str) -> None:
        """
        Fetches updates for a specific branch from the configured remote.

        :param branch_name: The name of the branch to update.
        :raises GitCommandError: If the fetch operation fails.
        :raises TypeError: If the branch name is not a string.
        """
        if not isinstance(branch_name, str):
            logging.error(f"Invalid branch type: {type(branch_name)}. Expected 'str'.")
            raise TypeError("Branch name must be a string.")

        fetch_ref = f"{branch_name}:{branch_name}"
        try:
            logging.debug(f"Fetching '{fetch_ref}' from remote '{self._remote_name}'.")
            self._working_repo.git.fetch(self._remote_name, fetch_ref)
            logging.debug(f"Fetch command executed successfully for branch '{branch_name}'.")
        except GitCommandError as e:
            logging.error(f"Failed to fetch branch '{branch_name}': {e}")
            logging.debug(traceback.format_exc())
            raise
        except Exception as e:
            logging.error(f"An unexpected error occurred while fetching branch '{branch_name}': {e}")
            logging.debug(traceback.format_exc())
            raise

    def update_all_branches(self):
        self._working_repo.git.fetch()

    def discover_branches(self) -> Dict[str, bool]:
        """
        Discovers and updates new branches from the remote repository.

        This force-fetches all branches, allowing the local repository to recognize
        new branches that may have been created remotely.

        :return: A dictionary mapping newly discovered branch names to their update status.
        """
        try:
            logging.info("Discovering new branches by fetching all references.")
            self.fetch_all_refs()
            logging.info("Discovery fetch completed.")
        except GitCommandError as e:
            logging.error(f"Git command failed during branch discovery: {e}")
            logging.debug(traceback.format_exc())
            # Proceed to update visible branches even if discovery fails
        except Exception as e:
            logging.error(f"Unexpected error during branch discovery: {e}")
            logging.debug(traceback.format_exc())

        # Update all visible branches after discovery attempt
        return self.update_all_visible_branches()

    def fetch_all_refs(self) -> None:
        """
        Fetches all references from the remote repository to discover new branches.

        :raises GitCommandError: If the fetch operation fails.
        """
        try:
            logging.debug(f"Fetching all references from remote '{self._remote_name}'.")
            # Using refspec to fetch all branches
            self._working_repo.git.fetch(self._remote_name, '--prune', '--all')
            logging.debug("All references fetched successfully.")
        except GitCommandError as e:
            logging.error(f"Failed to fetch all references from remote '{self._remote_name}': {e}")
            logging.debug(traceback.format_exc())
            raise
        except Exception as e:
            logging.error(f"An unexpected error occurred while fetching all references: {e}")
            logging.debug(traceback.format_exc())
            raise

if __name__ == '__main__':
    # This module is designed to be imported, not run directly
    # For testing, use the update_server.py script instead
    print("This module should be imported, not run directly.")
    print("Use update_server.py to run the updater service.")