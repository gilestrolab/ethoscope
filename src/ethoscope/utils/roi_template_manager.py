"""
ROI Template Manager for organizing and managing ROI template files.

This module provides utilities for managing ROI template files, including
loading builtin templates, validating templates, and converting legacy
ROI builders to template format.
"""

import os
import json
from typing import Dict, List, Union, Optional, Any
import warnings
import shutil

from ethoscope.roi_builders.template import ROITemplate, ROITemplateValidationError


class ROITemplateManager:
    """
    Manager class for ROI templates providing loading, validation, and migration utilities.
    """
    
    def __init__(self, builtin_templates_dir: Optional[str] = None, custom_templates_dir: Optional[str] = None):
        """
        Initialize template manager with separate builtin and custom directories.
        
        Args:
            builtin_templates_dir: Directory for builtin templates (part of codebase)
            custom_templates_dir: Directory for custom templates (in ethoscope_data)
        """
        # Builtin templates - part of the codebase, available on both node and ethoscope
        if builtin_templates_dir is None:
            self.builtin_dir = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "roi_templates", "builtin"
            ))
        else:
            self.builtin_dir = builtin_templates_dir
        
        # Custom templates - user uploaded, stored in ethoscope_data
        if custom_templates_dir is None:
            self.custom_dir = "/ethoscope_data/roi_templates"
        else:
            self.custom_dir = custom_templates_dir
        
        # Ensure custom directory exists (builtin should always exist as part of codebase)
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create custom template directory if it doesn't exist. Builtin should exist as part of codebase."""
        os.makedirs(self.custom_dir, exist_ok=True)
    
    def list_templates(self, include_custom: bool = True) -> List[Dict[str, Any]]:
        """
        List all available templates.
        
        Args:
            include_custom: Include custom templates from ethoscope_data
            
        Returns:
            List of template info dictionaries
        """
        templates = []
        
        # Always include builtin templates (part of codebase)
        templates.extend(self._scan_directory(self.builtin_dir, "builtin"))
        
        # Include custom templates if requested
        if include_custom:
            templates.extend(self._scan_directory(self.custom_dir, "custom"))
        
        return sorted(templates, key=lambda x: x["name"])
    
    def _scan_directory(self, directory: str, source_type: str) -> List[Dict[str, Any]]:
        """Scan directory for template files."""
        templates = []
        
        if not os.path.exists(directory):
            return templates
        
        for filename in os.listdir(directory):
            if not filename.endswith('.json'):
                continue
                
            filepath = os.path.join(directory, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                template_info = data.get("template_info", {})
                templates.append({
                    "name": template_info.get("name", filename[:-5]),  # Remove .json
                    "version": template_info.get("version", "unknown"),
                    "description": template_info.get("description", ""),
                    "author": template_info.get("author", ""),
                    "hardware_type": template_info.get("hardware_type", ""),
                    "filename": filename,
                    "filepath": filepath,
                    "source_type": source_type
                })
            except Exception as e:
                warnings.warn(f"Could not load template {filepath}: {e}")
        
        return templates
    
    def load_template(self, name: str) -> ROITemplate:
        """
        Load template by name. Checks builtin templates first, then custom.
        
        Args:
            name: Template name (can be filename without .json or display name)
            
        Returns:
            ROITemplate instance
            
        Raises:
            FileNotFoundError: If template is not found
            ROITemplateValidationError: If template is invalid
        """
        # Try builtin templates first (always available on both node and ethoscope)
        builtin_path = os.path.join(self.builtin_dir, f"{name}.json")
        if os.path.exists(builtin_path):
            return ROITemplate.load(builtin_path)
        
        # Try custom templates second (may need to be transferred to ethoscope)
        custom_path = os.path.join(self.custom_dir, f"{name}.json")
        if os.path.exists(custom_path):
            return ROITemplate.load(custom_path)
        
        # Try name-based search in case it's a display name
        template_file = self._find_template_file(name)
        if template_file:
            return ROITemplate.load(template_file)
        
        raise FileNotFoundError(f"Template '{name}' not found in builtin or custom directories")
    
    def is_builtin_template(self, name: str) -> bool:
        """
        Check if a template is a builtin template.
        
        Args:
            name: Template name
            
        Returns:
            True if template is builtin, False if custom or not found
        """
        builtin_path = os.path.join(self.builtin_dir, f"{name}.json")
        return os.path.exists(builtin_path)
    
    def is_custom_template(self, name: str) -> bool:
        """
        Check if a template is a custom template.
        
        Args:
            name: Template name
            
        Returns:
            True if template is custom, False if builtin or not found
        """
        custom_path = os.path.join(self.custom_dir, f"{name}.json")
        return os.path.exists(custom_path)
    
    def _find_template_file(self, name: str) -> Optional[str]:
        """Find template file by name or filename. Checks builtin first, then custom."""
        # Try exact filename match first
        for directory in [self.builtin_dir, self.custom_dir]:
            # Try with .json extension
            filepath = os.path.join(directory, f"{name}.json")
            if os.path.exists(filepath):
                return filepath
            
            # Try without extension if name already has .json
            if name.endswith('.json'):
                filepath = os.path.join(directory, name)
                if os.path.exists(filepath):
                    return filepath
        
        # Try display name match
        templates = self.list_templates()
        for template in templates:
            if template["name"] == name:
                return template["filepath"]
        
        return None
    
    def load_template_by_id(self, template_id: str) -> ROITemplate:
        """
        Load template by ID (typically MD5 hash).
        
        Args:
            template_id: Template ID to search for
            
        Returns:
            ROITemplate instance
            
        Raises:
            FileNotFoundError: If template with ID not found
            ROITemplateValidationError: If template is invalid
        """
        import hashlib
        
        # Search all directories for template with matching ID
        search_dirs = [self.builtin_dir, self.custom_dir]
        
        for directory in search_dirs:
            if not os.path.exists(directory):
                continue
                
            for filename in os.listdir(directory):
                if not filename.endswith('.json'):
                    continue
                    
                filepath = os.path.join(directory, filename)
                try:
                    with open(filepath, 'r') as f:
                        file_content = f.read()
                        template_data = json.loads(file_content)
                    
                    # Check if template has ID field matching
                    template_info = template_data.get("template_info", {})
                    if template_info.get("id") == template_id:
                        return ROITemplate.load(template_data)
                    
                    # Also check MD5 of content
                    content_md5 = hashlib.md5(file_content.encode('utf-8')).hexdigest()
                    if content_md5 == template_id:
                        return ROITemplate.load(template_data)
                        
                    # Check if filename matches ID
                    if filename[:-5] == template_id:  # Remove .json extension
                        return ROITemplate.load(template_data)
                        
                except Exception:
                    # Skip invalid files
                    continue
        
        # Try to load by filename directly
        for directory in search_dirs:
            potential_path = os.path.join(directory, f"{template_id}.json")
            if os.path.exists(potential_path):
                try:
                    return ROITemplate.load(potential_path)
                except Exception:
                    continue
        
        raise FileNotFoundError(f"Template with ID '{template_id}' not found")
    
    def validate_template(self, template_data: Union[Dict, str]) -> bool:
        """
        Validate template data or file.
        
        Args:
            template_data: Template dictionary or file path
            
        Returns:
            True if valid
            
        Raises:
            ROITemplateValidationError: If template is invalid
        """
        try:
            if isinstance(template_data, str):
                ROITemplate.load(template_data)
            else:
                ROITemplate(template_data)
            return True
        except Exception as e:
            raise ROITemplateValidationError(f"Template validation failed: {e}")
    
    def save_template(self, name: str, template_data: Dict[str, Any], 
                     template_type: str = "custom") -> str:
        """
        Save template to appropriate directory.
        
        Args:
            name: Template name (will be used as filename)
            template_data: Template data dictionary
            template_type: Type of template ("custom" or "uploaded")
            
        Returns:
            Path to saved template file
            
        Raises:
            ROITemplateValidationError: If template is invalid
            ValueError: If template_type is invalid
        """
        # Validate template first
        self.validate_template(template_data)
        
        # Determine target directory
        if template_type == "custom":
            target_dir = self.custom_dir
        else:
            raise ValueError(f"Invalid template_type: {template_type}. Use 'custom'")
        
        # Ensure name has .json extension
        if not name.endswith('.json'):
            name = f"{name}.json"
        
        filepath = os.path.join(target_dir, name)
        
        # Save template
        with open(filepath, 'w') as f:
            json.dump(template_data, f, indent=2)
        
        return filepath
    
    def delete_template(self, name: str, template_type: Optional[str] = None) -> bool:
        """
        Delete template by name.
        
        Args:
            name: Template name
            template_type: Type of template to delete from. If None, searches all non-builtin.
            
        Returns:
            True if deleted successfully
            
        Raises:
            ValueError: If trying to delete builtin template
        """
        template_file = self._find_template_file(name)
        if not template_file:
            return False
        
        # Don't allow deleting builtin templates
        if self.builtin_dir in template_file:
            raise ValueError("Cannot delete builtin templates")
        
        os.remove(template_file)
        return True
    
