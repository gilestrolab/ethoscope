"""
File Management API Module

Handles file management operations including browsing, downloading, and file removal.
"""

import bottle
import os
import datetime
import zipfile
import subprocess
import fnmatch
from .base import BaseAPI, error_decorator


class FileAPI(BaseAPI):
    """API endpoints for file management operations."""

    def register_routes(self):
        """Register file management routes."""
        self.app.route("/resultfiles/<type>", method="GET")(self._result_files)
        self.app.route("/browse/<folder>", method="GET")(self._browse)
        self.app.route("/download/<what>", method="POST")(self._download)
        self.app.route("/remove_files", method="POST")(self._remove_files)

    @error_decorator
    def _result_files(self, type):
        """Get result files of specified type."""
        if type == "all":
            pattern = "*"
        else:
            pattern = f"*.{type}"

        matches = []
        for root, dirnames, filenames in os.walk(self.results_dir):
            for f in fnmatch.filter(filenames, pattern):
                matches.append(os.path.join(root, f))

        return {"files": matches}

    @error_decorator
    def _browse(self, folder):
        """Browse directory contents."""
        directory = self.results_dir if folder == "null" else f"/{folder}"
        files = {}

        for dirpath, dirnames, filenames in os.walk(directory):
            for name in filenames:
                abs_path = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(abs_path)
                    mtime = os.path.getmtime(abs_path)
                    files[name] = {"abs_path": abs_path, "size": size, "mtime": mtime}
                except Exception:
                    # Skip files that can't be accessed
                    continue

        return {"files": files}

    @error_decorator
    def _download(self, what):
        """Create download archives."""
        if what == "files":
            req_files = bottle.request.json
            timestamp = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
            zip_file_name = os.path.join(self.results_dir, f"results_{timestamp}.zip")

            with zipfile.ZipFile(zip_file_name, mode="a") as zf:
                self.logger.info(f"Creating archive: {zip_file_name}")
                for f in req_files["files"]:
                    try:
                        zf.write(f["url"])
                    except Exception as e:
                        self.logger.warning(f"Failed to add {f['url']} to archive: {e}")

            return {"url": zip_file_name}
        else:
            raise NotImplementedError(f"Download type '{what}' not supported")

    @error_decorator
    def _remove_files(self):
        """Remove specified files."""
        req = bottle.request.json
        results = []

        for f in req["files"]:
            try:
                rm = subprocess.run(["rm", f["url"]], capture_output=True, text=True)
                if rm.returncode == 0:
                    results.append(f["url"])
                    self.logger.info(f"Removed file: {f['url']}")
                else:
                    self.logger.error(f"Failed to remove {f['url']}: {rm.stderr}")
            except Exception as e:
                self.logger.error(f"Error removing {f['url']}: {e}")

        return {"result": results}
