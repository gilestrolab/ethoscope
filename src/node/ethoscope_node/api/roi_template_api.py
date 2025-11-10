"""
ROI Template API Module

Handles ROI template management including listing, uploading, and deployment
to devices. Supports both built-in and custom templates.
"""

import hashlib
import json
import os

import bottle

from .base import BaseAPI
from .base import error_decorator


class ROITemplateAPI(BaseAPI):
    """API endpoints for ROI template management."""

    def register_routes(self):
        """Register ROI template-related routes."""
        self.app.route("/roi_templates", method="GET")(self._list_roi_templates)
        self.app.route("/roi_template/<template_name>", method="GET")(
            self._get_roi_template
        )
        self.app.route("/upload_roi_template", method="POST")(self._upload_roi_template)
        self.app.route("/device/<id>/upload_template", method="POST")(
            self._upload_template_to_device
        )

    @error_decorator
    def _list_roi_templates(self):
        """List available ROI templates, separating builtin and custom."""
        templates = []

        # Builtin templates directory (part of ethoscope package)
        # Look for builtin templates in the ethoscope package roi_builders directory
        builtin_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "ethoscope",
            "ethoscope",
            "roi_builders",
            "roi_templates",
            "builtin",
        )
        builtin_dir = os.path.abspath(builtin_dir)

        # Custom templates directory (in ethoscope_data)
        custom_dir = self.roi_templates_dir
        os.makedirs(custom_dir, exist_ok=True)

        try:
            # Scan builtin templates first
            if os.path.exists(builtin_dir):
                for filename in os.listdir(builtin_dir):
                    if filename.endswith(".json"):
                        filepath = os.path.join(builtin_dir, filename)
                        template_info = self._parse_template_file(filepath, "builtin")
                        if template_info:
                            templates.append(template_info)

            # Scan custom templates second
            for filename in os.listdir(custom_dir):
                if filename.endswith(".json"):
                    filepath = os.path.join(custom_dir, filename)
                    template_info = self._parse_template_file(filepath, "custom")
                    if template_info:
                        templates.append(template_info)

            # Sort by display text
            templates.sort(key=lambda x: x["text"])

        except Exception as e:
            self.logger.error(f"Error listing ROI templates: {e}")

        return {"templates": templates}

    def _parse_template_file(self, filepath: str, template_type: str):
        """Parse a template file and return template info."""
        try:
            with open(filepath) as f:
                file_content = f.read()
                template_data = json.loads(file_content)

            # Calculate MD5 hash of the file content
            md5_hash = hashlib.md5(file_content.encode("utf-8")).hexdigest()

            template_info = template_data.get("template_info", {})
            filename = os.path.basename(filepath)

            # Use existing template ID or generate from MD5
            template_id = template_info.get("id", md5_hash)

            return {
                "value": filename[:-5],  # Remove .json extension
                "text": template_info.get("name", filename[:-5]),
                "description": template_info.get("description", ""),
                "filename": filename,
                "id": template_id,
                "md5": md5_hash,
                "type": template_type,  # "builtin" or "custom"
                "is_default": template_info.get(
                    "default", False
                ),  # Check for default flag
            }
        except Exception as e:
            self.logger.warning(f"Could not load template {filepath}: {e}")
            return None

    @error_decorator
    def _get_roi_template(self, template_name):
        """Get specific ROI template content from builtin or custom directories."""
        # Try builtin templates first
        builtin_dir = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "ethoscope",
            "ethoscope",
            "roi_builders",
            "roi_templates",
            "builtin",
        )
        builtin_dir = os.path.abspath(builtin_dir)
        builtin_path = os.path.join(builtin_dir, f"{template_name}.json")

        if os.path.exists(builtin_path):
            try:
                with open(builtin_path) as f:
                    return json.load(f)
            except Exception as e:
                self.abort_with_error(500, f"Error loading builtin template: {e}")

        # Try custom templates second
        custom_path = os.path.join(self.roi_templates_dir, f"{template_name}.json")
        if os.path.exists(custom_path):
            try:
                with open(custom_path) as f:
                    return json.load(f)
            except Exception as e:
                self.abort_with_error(500, f"Error loading custom template: {e}")

        self.abort_with_error(
            404,
            f"Template '{template_name}' not found in builtin or custom directories",
        )

    @error_decorator
    def _upload_roi_template(self):
        """Handle ROI template uploads from web interface."""
        upload = bottle.request.files.get("template")
        if not upload:
            self.abort_with_error(400, "No template file uploaded")

        if not upload.filename.endswith(".json"):
            self.abort_with_error(400, "Template must be a JSON file")

        # Ensure roi_templates directory exists
        os.makedirs(self.roi_templates_dir, exist_ok=True)

        # Save uploaded file
        filepath = os.path.join(self.roi_templates_dir, upload.filename)
        try:
            upload.save(filepath)

            # Validate template
            with open(filepath) as f:
                template_data = json.load(f)

            # Basic validation
            if (
                "template_info" not in template_data
                or "roi_definition" not in template_data
            ):
                os.remove(filepath)
                self.abort_with_error(400, "Invalid template format")

            return {"success": True, "filename": upload.filename}

        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            self.abort_with_error(500, f"Error saving template: {e}")

    @error_decorator
    def _upload_template_to_device(self, id):
        """Upload custom template from node to device."""
        template_name = bottle.request.json.get("template_name")
        if not template_name:
            self.abort_with_error(400, "Template name required")

        # Get template from node (should be a custom template)
        template_data = self._get_roi_template(template_name)

        # Get device info
        try:
            device = self.validate_device_exists(id)

            # Upload template to device using unified upload API
            device_url = f"http://{device.ip()}:{device._port}/upload/{id}"
            import requests

            # Send template data as JSON POST with explicit Content-Type
            payload = {"template_data": template_data, "template_name": template_name}

            headers = {"Content-Type": "application/json"}
            response = requests.post(
                device_url, json=payload, headers=headers, timeout=10
            )
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": f"Custom template {template_name} uploaded to device {id}",
                }
            else:
                self.abort_with_error(500, f"Device upload failed: {response.text}")

        except Exception as e:
            self.abort_with_error(500, f"Error uploading to device: {e}")
