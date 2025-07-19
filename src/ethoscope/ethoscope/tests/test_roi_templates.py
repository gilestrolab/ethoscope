"""
Unit tests for ROI template system.

This module contains comprehensive tests for the new external ROI template system,
including template loading, validation, and ROI generation.
"""

import unittest
import tempfile
import os
import json
from unittest.mock import Mock, patch
import numpy as np

from ethoscope.roi_builders.template import ROITemplate, ROITemplateValidationError
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder
from ethoscope.utils.roi_template_manager import ROITemplateManager, convert_legacy_to_template


class TestROITemplate(unittest.TestCase):
    """Test the ROITemplate class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.valid_template_data = {
            "template_info": {
                "name": "Test Template",
                "version": "1.0",
                "description": "Test template for unit tests",
                "author": "Test Suite"
            },
            "roi_definition": {
                "type": "grid_with_targets",
                "grid": {
                    "n_rows": 2,
                    "n_cols": 2,
                    "orientation": "vertical"
                },
                "alignment": {
                    "target_detection": True,
                    "expected_targets": 3
                },
                "positioning": {
                    "margins": {
                        "top": 0.1,
                        "bottom": 0.1,
                        "left": 0.1,
                        "right": 0.1
                    },
                    "fill_ratios": {
                        "horizontal": 0.8,
                        "vertical": 0.8
                    }
                }
            }
        }
        
        self.manual_template_data = {
            "template_info": {
                "name": "Manual Test Template",
                "version": "1.0"
            },
            "roi_definition": {
                "type": "manual_polygons",
                "manual_rois": [
                    {
                        "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]],
                        "value": 0
                    },
                    {
                        "polygon": [[200, 0], [300, 0], [300, 100], [200, 100]],
                        "value": 1
                    }
                ]
            }
        }
    
    def test_valid_template_creation(self):
        """Test creating a valid template."""
        template = ROITemplate(self.valid_template_data)
        self.assertEqual(template.name, "Test Template")
        self.assertEqual(template.version, "1.0")
    
    def test_template_validation_missing_required_fields(self):
        """Test template validation with missing required fields."""
        # Missing template_info
        invalid_data = {"roi_definition": {"type": "grid_with_targets"}}
        with self.assertRaises(ROITemplateValidationError):
            ROITemplate(invalid_data)
        
        # Missing roi_definition
        invalid_data = {"template_info": {"name": "test", "version": "1.0"}}
        with self.assertRaises(ROITemplateValidationError):
            ROITemplate(invalid_data)
    
    def test_template_validation_invalid_roi_type(self):
        """Test template validation with invalid ROI type."""
        invalid_data = self.valid_template_data.copy()
        invalid_data["roi_definition"]["type"] = "invalid_type"
        with self.assertRaises(ROITemplateValidationError):
            ROITemplate(invalid_data)
    
    def test_grid_template_validation(self):
        """Test validation of grid-based templates."""
        # Missing grid configuration
        invalid_data = self.valid_template_data.copy()
        del invalid_data["roi_definition"]["grid"]
        with self.assertRaises(ROITemplateValidationError):
            ROITemplate(invalid_data)
        
        # Invalid grid parameters
        invalid_data = self.valid_template_data.copy()
        invalid_data["roi_definition"]["grid"]["n_rows"] = 0
        with self.assertRaises(ROITemplateValidationError):
            ROITemplate(invalid_data)
    
    def test_manual_template_validation(self):
        """Test validation of manual polygon templates."""
        # Valid manual template
        template = ROITemplate(self.manual_template_data)
        self.assertEqual(template.name, "Manual Test Template")
        
        # Invalid manual template - missing manual_rois
        invalid_data = self.manual_template_data.copy()
        del invalid_data["roi_definition"]["manual_rois"]
        with self.assertRaises(ROITemplateValidationError):
            ROITemplate(invalid_data)
        
        # Invalid polygon - too few points
        invalid_data = self.manual_template_data.copy()
        invalid_data["roi_definition"]["manual_rois"][0]["polygon"] = [[0, 0], [100, 0]]
        with self.assertRaises(ROITemplateValidationError):
            ROITemplate(invalid_data)
    
    def test_load_from_file(self):
        """Test loading template from JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.valid_template_data, f)
            temp_file = f.name
        
        try:
            template = ROITemplate.load(temp_file)
            self.assertEqual(template.name, "Test Template")
        finally:
            os.unlink(temp_file)
    
    def test_load_from_dict(self):
        """Test loading template from dictionary."""
        template = ROITemplate.load(self.valid_template_data)
        self.assertEqual(template.name, "Test Template")
    
    def test_load_nonexistent_file(self):
        """Test loading from non-existent file."""
        with self.assertRaises(FileNotFoundError):
            ROITemplate.load("/nonexistent/file.json")
    
    def test_to_legacy_params(self):
        """Test conversion to legacy parameters."""
        template = ROITemplate(self.valid_template_data)
        legacy_params = template.to_legacy_params()
        
        expected_params = {
            "n_rows": 2,
            "n_cols": 2,
            "top_margin": 0.1,
            "bottom_margin": 0.1,
            "left_margin": 0.1,
            "right_margin": 0.1,
            "horizontal_fill": 0.8,
            "vertical_fill": 0.8
        }
        
        self.assertEqual(legacy_params, expected_params)
    
    def test_save_template(self):
        """Test saving template to file."""
        template = ROITemplate(self.valid_template_data)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_file = f.name
        
        try:
            template.save(temp_file)
            
            # Load and verify
            with open(temp_file, 'r') as f:
                saved_data = json.load(f)
            
            self.assertEqual(saved_data["template_info"]["name"], "Test Template")
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)


class TestFileBasedROIBuilder(unittest.TestCase):
    """Test the FileBasedROIBuilder class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.template_data = {
            "template_info": {
                "name": "Test Builder Template",
                "version": "1.0"
            },
            "roi_definition": {
                "type": "manual_polygons",
                "manual_rois": [
                    {
                        "polygon": [[10, 10], [50, 10], [50, 50], [10, 50]],
                        "value": 0
                    }
                ]
            }
        }
        
        self.mock_camera = Mock()
        self.mock_camera.grab_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
    
    def test_create_with_template_data(self):
        """Test creating builder with template data."""
        builder = FileBasedROIBuilder(template_data=self.template_data)
        self.assertIsNotNone(builder.template)
        self.assertEqual(builder.template.name, "Test Builder Template")
    
    def test_create_with_no_source(self):
        """Test creating builder with no template source."""
        with self.assertRaises(ValueError):
            FileBasedROIBuilder()
    
    def test_create_with_multiple_sources(self):
        """Test creating builder with multiple template sources."""
        with self.assertRaises(ValueError):
            FileBasedROIBuilder(template_file="test.json", template_data=self.template_data)
    
    @patch('ethoscope.roi_builders.file_based_roi_builder.ROITemplateManager')
    def test_create_with_template_name(self, mock_manager_class):
        """Test creating builder with template name."""
        mock_manager = Mock()
        mock_template = Mock()
        mock_template.name = "Builtin Template"
        mock_manager.load_template.return_value = mock_template
        mock_manager_class.return_value = mock_manager
        
        builder = FileBasedROIBuilder(template_name="test_template")
        mock_manager.load_template.assert_called_once_with("test_template")
    
    def test_create_with_invalid_file(self):
        """Test creating builder with invalid template file."""
        with self.assertRaises(ROITemplateValidationError):
            FileBasedROIBuilder(template_file="/nonexistent/file.json")
    
    def test_build_manual_rois(self):
        """Test building ROIs from manual polygon template."""
        builder = FileBasedROIBuilder(template_data=self.template_data)
        rois = builder.build(self.mock_camera)
        
        self.assertEqual(len(rois), 1)
        self.assertEqual(rois[0].value, 0)
        # Check that polygon was set correctly
        expected_polygon = np.array([[10, 10], [50, 10], [50, 50], [10, 50]], dtype=np.float32)
        np.testing.assert_array_equal(rois[0].polygon, expected_polygon)
    
    def test_get_template_info(self):
        """Test getting template information."""
        builder = FileBasedROIBuilder(template_data=self.template_data)
        info = builder.get_template_info()
        
        self.assertEqual(info["name"], "Test Builder Template")
        self.assertEqual(info["version"], "1.0")
        self.assertEqual(info["source"], "inline_data")
    
    def test_to_legacy_params(self):
        """Test conversion to legacy parameters."""
        grid_template_data = {
            "template_info": {"name": "Grid Template", "version": "1.0"},
            "roi_definition": {
                "type": "grid_with_targets",
                "grid": {"n_rows": 5, "n_cols": 3},
                "positioning": {
                    "margins": {"top": 0.2, "bottom": 0.2, "left": 0.1, "right": 0.1},
                    "fill_ratios": {"horizontal": 0.9, "vertical": 0.85}
                }
            }
        }
        
        builder = FileBasedROIBuilder(template_data=grid_template_data)
        legacy_params = builder.to_legacy_params()
        
        self.assertEqual(legacy_params["n_rows"], 5)
        self.assertEqual(legacy_params["n_cols"], 3)
        self.assertEqual(legacy_params["top_margin"], 0.2)


class TestROITemplateManager(unittest.TestCase):
    """Test the ROITemplateManager class."""
    
    def setUp(self):
        """Set up test fixtures with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = ROITemplateManager(templates_dir=self.temp_dir)
        
        # Create sample template
        self.sample_template = {
            "template_info": {
                "name": "Sample Template",
                "version": "1.0",
                "description": "A sample template for testing"
            },
            "roi_definition": {
                "type": "manual_polygons",
                "manual_rois": [
                    {"polygon": [[0, 0], [10, 0], [10, 10], [0, 10]], "value": 0}
                ]
            }
        }
    
    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_save_and_load_template(self):
        """Test saving and loading templates."""
        # Save template
        saved_path = self.manager.save_template("test_template", self.sample_template, "custom")
        self.assertTrue(os.path.exists(saved_path))
        
        # Load template
        template = self.manager.load_template("test_template")
        self.assertEqual(template.name, "Sample Template")
    
    def test_list_templates(self):
        """Test listing available templates."""
        # Save a template first
        self.manager.save_template("test_template", self.sample_template, "custom")
        
        # List templates
        templates = self.manager.list_templates()
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["name"], "Sample Template")
        self.assertEqual(templates[0]["source_type"], "custom")
    
    def test_validate_template(self):
        """Test template validation."""
        # Valid template
        self.assertTrue(self.manager.validate_template(self.sample_template))
        
        # Invalid template
        invalid_template = {"invalid": "template"}
        with self.assertRaises(ROITemplateValidationError):
            self.manager.validate_template(invalid_template)
    
    def test_delete_template(self):
        """Test deleting templates."""
        # Save template
        self.manager.save_template("test_template", self.sample_template, "custom")
        
        # Delete template
        success = self.manager.delete_template("test_template")
        self.assertTrue(success)
        
        # Verify deletion
        templates = self.manager.list_templates()
        self.assertEqual(len(templates), 0)
    
    def test_delete_nonexistent_template(self):
        """Test deleting non-existent template."""
        success = self.manager.delete_template("nonexistent")
        self.assertFalse(success)
    
    def test_save_invalid_template_type(self):
        """Test saving with invalid template type."""
        with self.assertRaises(ValueError):
            self.manager.save_template("test", self.sample_template, "invalid_type")


class TestLegacyMigration(unittest.TestCase):
    """Test legacy ROI builder migration functionality."""
    
    def test_convert_legacy_to_template(self):
        """Test converting legacy builder to template format."""
        from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
        
        template_data = convert_legacy_to_template(
            TargetGridROIBuilder,
            n_rows=5,
            n_cols=2,
            top_margin=0.1,
            bottom_margin=0.1,
            horizontal_fill=0.8,
            vertical_fill=0.7
        )
        
        self.assertEqual(template_data["roi_definition"]["type"], "grid_with_targets")
        self.assertEqual(template_data["roi_definition"]["grid"]["n_rows"], 5)
        self.assertEqual(template_data["roi_definition"]["grid"]["n_cols"], 2)
        self.assertEqual(template_data["roi_definition"]["positioning"]["margins"]["top"], 0.1)
        self.assertEqual(template_data["roi_definition"]["positioning"]["fill_ratios"]["horizontal"], 0.8)


class TestTemplateIntegration(unittest.TestCase):
    """Integration tests for the complete template system."""
    
    def setUp(self):
        """Set up integration test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = ROITemplateManager(templates_dir=self.temp_dir)
        
        self.mock_camera = Mock()
        self.mock_camera.grab_frame.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
    
    def tearDown(self):
        """Clean up integration test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_end_to_end_workflow(self):
        """Test complete workflow from template creation to ROI generation."""
        # Create and save template
        template_data = {
            "template_info": {
                "name": "Integration Test Template",
                "version": "1.0",
                "description": "End-to-end test template"
            },
            "roi_definition": {
                "type": "manual_polygons",
                "manual_rois": [
                    {"polygon": [[50, 50], [150, 50], [150, 150], [50, 150]], "value": 0},
                    {"polygon": [[200, 50], [300, 50], [300, 150], [200, 150]], "value": 1}
                ]
            },
            "validation": {
                "min_roi_area": 100
            }
        }
        
        # Save template
        saved_path = self.manager.save_template("integration_test", template_data, "custom")
        self.assertTrue(os.path.exists(saved_path))
        
        # Create ROI builder from saved template
        builder = FileBasedROIBuilder(template_name="integration_test")
        
        # Generate ROIs
        rois = builder.build(self.mock_camera)
        
        # Verify results
        self.assertEqual(len(rois), 2)
        self.assertEqual(rois[0].value, 0)
        self.assertEqual(rois[1].value, 1)
        
        # Verify ROI areas are above minimum
        for roi in rois:
            self.assertGreater(roi.area, 100)


if __name__ == '__main__':
    unittest.main()