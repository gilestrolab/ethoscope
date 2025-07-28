"""
Device API Module

Handles all device-related endpoints including device discovery, management,
control, and information retrieval.
"""

import bottle
import json
import tempfile
import shutil
import os
from .base import BaseAPI, error_decorator, warning_decorator


class DeviceAPI(BaseAPI):
    """API endpoints for device management and control."""
    
    def register_routes(self):
        """Register device-related routes."""
        # Device listing and management
        self.app.route('/devices', method='GET')(self._get_devices)
        self.app.route('/devices_list', method='GET')(self._get_devices_list)
        self.app.route('/devices/retire-inactive', method='POST')(self._retire_inactive_devices)
        self.app.route('/devices/cleanup-busy', method='POST')(self._cleanup_busy_devices)
        self.app.route('/device/add', method='POST')(self._manual_add_device)
        
        # Device information
        self.app.route('/device/<id>/data', method='GET')(self._get_device_info)
        self.app.route('/device/<id>/machineinfo', method='GET')(self._get_device_machine_info)
        self.app.route('/device/<id>/machineinfo', method='POST')(self._set_device_machine_info)
        self.app.route('/device/<id>/module', method='GET')(self._get_device_module)
        self.app.route('/device/<id>/user_options', method='GET')(self._get_device_options)
        self.app.route('/device/<id>/videofiles', method='GET')(self._get_device_videofiles)
        
        # Device images and streaming
        self.app.route('/device/<id>/last_img', method='GET')(self._get_device_last_img)
        self.app.route('/device/<id>/dbg_img', method='GET')(self._get_device_dbg_img)
        self.app.route('/device/<id>/stream', method='GET')(self._get_device_stream)
        
        # Device operations
        self.app.route('/device/<id>/backup', method='GET')(self._get_device_backup_info)
        self.app.route('/device/<id>/backup', method='POST')(self._force_device_backup)
        self.app.route('/device/<id>/dumpSQLdb', method='GET')(self._device_local_dump)
        self.app.route('/device/<id>/retire', method='GET')(self._retire_device)
        self.app.route('/device/<id>/controls/<instruction>', method='POST')(self._post_device_instructions)
        self.app.route('/device/<id>/log', method='POST')(self._get_log)
        
        # Mask creation endpoints
        self.app.route('/device/<id>/mask_creation/status', method='GET')(self._get_mask_creation_status)
        
        # Optimized batch endpoints
        self.app.route('/device/<id>/batch', method='GET')(self._get_device_batch)
        self.app.route('/device/<id>/batch-critical', method='GET')(self._get_device_batch_critical)
    
    @error_decorator
    def _get_devices(self):
        """Get all devices with optional inactive filter."""
        # Check if request wants inactive devices too
        include_inactive = self.get_query_param('include_inactive', '').lower() == 'true'
        return self.device_scanner.get_all_devices_info(include_inactive=include_inactive)
    
    def _get_devices_list(self):
        """Alias for _get_devices."""
        return self._get_devices()
    
    @error_decorator
    def _retire_inactive_devices(self):
        """Retire devices that haven't been seen for more than the configured threshold."""
        try:
            # Get threshold from request body or use default
            request_data = self.get_request_data().decode("utf-8")
            threshold_days = 90  # Default value
            
            if request_data:
                try:
                    data = json.loads(request_data)
                    threshold_days = data.get('threshold_days', 90)
                except (json.JSONDecodeError, ValueError):
                    # If parsing fails, use default
                    pass
            
            # First cleanup stale busy devices
            busy_cleaned_count = self.database.cleanup_stale_busy_devices(timeout_minutes=10)
            
            # Then purge unnamed and invalid devices
            purged_count = self.database.purge_unnamed_devices()
            
            # Finally retire inactive devices
            retired_count = self.database.retire_inactive_devices(threshold_days)
            
            return {
                'success': True,
                'retired_count': retired_count,
                'purged_count': purged_count,
                'busy_cleaned_count': busy_cleaned_count,
                'threshold_days': threshold_days,
                'message': f'Cleaned up {busy_cleaned_count} stale busy devices, purged {purged_count} unnamed/invalid devices, and retired {retired_count} devices that were offline for more than {threshold_days} days'
            }
            
        except Exception as e:
            self.logger.error(f"Error retiring inactive devices: {e}")
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to retire inactive devices'
            }
    
    @error_decorator
    def _cleanup_busy_devices(self):
        """Clean up devices that are stuck in 'busy' status."""
        try:
            # Get threshold from request body or use default
            request_data = self.get_request_data().decode("utf-8")
            threshold_hours = 2  # Default value
            
            if request_data:
                try:
                    data = json.loads(request_data)
                    threshold_hours = data.get('threshold_hours', 2)
                except (json.JSONDecodeError, ValueError):
                    # If parsing fails, use default
                    pass
            
            # Clean up offline busy devices
            cleaned_count = self.database.cleanup_offline_busy_devices(threshold_hours)
            
            return {
                'success': True,
                'cleaned_count': cleaned_count,
                'threshold_hours': threshold_hours,
                'message': f'Cleaned up {cleaned_count} devices that were stuck as busy for more than {threshold_hours} hours'
            }
            
        except Exception as e:
            self.logger.error(f"Error cleaning up busy devices: {e}")
            return {
                'success': False,
                'error': str(e),
                'message': 'Failed to cleanup busy devices'
            }

    def _manual_add_device(self):
        """Manually add ethoscopes using provided IPs."""
        input_string = self.get_request_data().decode("utf-8")
        added = []
        problems = []
        
        for ip_address in input_string.split(","):
            ip_address = ip_address.strip()
            try:
                self.device_scanner.add(ip_address)
                added.append(ip_address)
            except Exception:
                problems.append(ip_address)
        
        return {"added": added, "problems": problems}
    
    @warning_decorator
    def _get_device_info(self, id):
        """Get device information."""
        device = self.validate_device_exists(id)
        device_info = device.info()
        
        # Remove databases from response to avoid redundancy
        # This information is now available via /device/<id>/backup endpoint
        if 'databases' in device_info:
            device_info = device_info.copy()
            del device_info['databases']
        
        return device_info
    
    @error_decorator
    def _get_device_machine_info(self, id):
        """Get device machine information."""
        device = self.device_scanner.get_device(id)
        if not device:
            return self.device_scanner.get_all_devices_info()[id]
        return device.machine_info()
    
    @error_decorator
    def _set_device_machine_info(self, id):
        """Update device machine info."""
        post_data = self.get_request_data()
        device = self.validate_device_exists(id)
        
        # Don't try to JSON decode/encode - pass bytes directly
        response = device.send_settings(post_data)
        
        # Setup SSH key authentication after successful configuration
        if response.get('haschanged', False):
            try:
                ssh_success = device.setup_ssh_authentication()
                self.logger.info(f"SSH key setup for device {id}: {'successful' if ssh_success else 'failed'}")
            except Exception as e:
                self.logger.warning(f"Failed to setup SSH keys for device {id}: {e}")
        
        return {**device.machine_info(), "haschanged": response.get('haschanged', False)}
    
    @error_decorator
    def _get_device_module(self, id):
        """Get device connected module information."""
        device = self.device_scanner.get_device(id)
        return device.connected_module() if device else {}
    
    @error_decorator
    def _get_device_options(self, id):
        """Get device user options."""
        device = self.device_scanner.get_device(id)
        return device.user_options() if device else None
    
    @error_decorator
    def _get_device_videofiles(self, id):
        """Get device video files."""
        device = self.device_scanner.get_device(id)
        try:
            return device.videofiles() if device else []
        except Exception:
            return []
    
    @error_decorator
    def _get_device_last_img(self, id):
        """Get device last image."""
        device = self.validate_device_exists(id)
        device_info = device.info()
        
        if "status" not in device_info or device_info["status"] == "not_in_use":
            raise Exception(f"Device {id} is not in use, no image")
        
        file_like = device.last_image()
        if not file_like:
            raise Exception(f"No image for {id}")
        
        basename = os.path.join(self.tmp_imgs_dir, f"{id}_last_img.jpg")
        return self._cache_img(file_like, basename)
    
    @error_decorator
    def _get_device_dbg_img(self, id):
        """Get device debug image."""
        device = self.validate_device_exists(id)
        file_like = device.dbg_img()
        basename = os.path.join(self.tmp_imgs_dir, f"{id}_debug.png")
        return self._cache_img(file_like, basename)
    
    @error_decorator
    def _get_device_stream(self, id):
        """Get device stream."""
        device = self.validate_device_exists(id)
        bottle.response.set_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
        return device.relay_stream()

    @error_decorator
    def _get_device_backup_info(self, id):
        """Get device backup information from device databases."""
        from ethoscope_node.backup.helpers import get_device_backup_info
        
        device = self.validate_device_exists(id)
        device_info = device.info()
        
        # Extract databases information
        databases = device_info.get('databases', {})
        
        # Use backup helpers to analyze the databases and provide backup status
        backup_info = get_device_backup_info(id, databases)
        
        return backup_info
    
    @error_decorator
    def _force_device_backup(self, id):
        """Force backup on device with specified id."""
        from ethoscope_node.backup.helpers import BackupClass
        
        device_info = device.info().copy()
        
        try:
            self.logger.info(f"Initiating backup for device {device_info['id']}")
            backup_job = BackupClass(device_info, results_dir=self.results_dir)
            
            self.logger.info(f"Running backup for device {device_info['id']}")
            success = False
            for status_update in backup_job.backup():
                # Process status updates
                status = json.loads(status_update)
                self.logger.info(f"Backup status: {status}")
                if status.get('status') == 'success':
                    success = True
            
            if success:
                self.logger.info(f"Backup done for device {device_info['id']}")
            else:
                self.logger.error(f"Backup for device {device_info['id']} could not be completed")
                
            return {'success': success}
            
        except Exception as e:
            self.logger.error(f"Unexpected error in backup: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            raise
    
    @error_decorator
    def _device_local_dump(self, id):
        """Ask the device to perform a local SQL dump."""
        device = self.validate_device_exists(id)
        return device.dump_sql_db()
    
    @error_decorator
    def _retire_device(self, id):
        """Change the status of the device to inactive in the device database."""
        return self.device_scanner.retire_device(id)
    
    @error_decorator
    def _post_device_instructions(self, id, instruction):
        """Send instruction to device."""
        post_data = self.get_request_data()
        device = self.validate_device_exists(id)
        
        # Debug: log what data is being sent to device
        if instruction == 'start':
            import json
            import logging
            try:
                data_dict = json.loads(post_data.decode('utf-8')) if isinstance(post_data, bytes) else post_data
                logging.info(f"DEBUG: Node server sending start instruction to device {id}")
                logging.info(f"DEBUG: Post data: {data_dict}")
                
                # Check for experimental_info and database_to_append
                if 'experimental_info' in data_dict:
                    exp_info = data_dict['experimental_info']
                    logging.info(f"DEBUG: experimental_info section: {exp_info}")
                    if 'arguments' in exp_info and 'database_to_append' in exp_info['arguments']:
                        logging.info(f"DEBUG: Found database_to_append in node server: {exp_info['arguments']['database_to_append']}")
                    else:
                        logging.warning("DEBUG: database_to_append NOT found in node server data")
            except Exception as e:
                logging.error(f"DEBUG: Error parsing post data in node server: {e}")
        
        # Don't try to JSON decode/encode - pass bytes directly
        device.send_instruction(instruction, post_data)
        return self._get_device_info(id)
    
    @error_decorator
    def _get_log(self, id):
        """Get device logs."""
        device = self.validate_device_exists(id)
        return device.get_log()
    
    @error_decorator
    def _get_mask_creation_status(self, id):
        """Get current mask creation status and ROI parameters."""
        device = self.validate_device_exists(id)
        
        # Send get_current_rois command to device to get ROI status
        try:
            return device.send_instruction('get_current_rois', b'{}')
        except ValueError as e:
            # Handle unknown instruction error
            self.logger.error(f"Mask creation status error for device {id}: {e}")
            return {
                'error': str(e),
                'roi_count': 0,
                'targets_detected': False,
                'mask_creation_active': False
            }
        except Exception as e:
            self.logger.error(f"Failed to get mask creation status for device {id}: {e}")
            return {
                'error': str(e),
                'roi_count': 0,
                'targets_detected': False,
                'mask_creation_active': False
            }
    
    @error_decorator
    def _get_device_batch(self, id):
        """Batched endpoint that returns all critical device data in one request."""
        device = self.validate_device_exists(id)
        
        # Get all device data in parallel where possible
        batch_data = {}
        
        try:
            # Core device info (always needed)
            batch_data['data'] = device.info()
        except Exception as e:
            self.logger.error(f"Failed to get device info for {id}: {e}")
            batch_data['data'] = None
        
        try:
            # Machine info (needed for device page) - load asynchronously to avoid delays
            # Call machine_info() in background to avoid blocking the critical data
            batch_data['machineinfo'] = device.machine_info()
        except Exception as e:
            self.logger.error(f"Failed to get machine info for {id}: {e}")
            batch_data['machineinfo'] = None
        
        # Get video files and user options asynchronously in background
        # These are less critical and can be loaded separately if needed
        try:
            batch_data['user_options'] = device.user_options()
        except Exception as e:
            self.logger.error(f"Failed to get user options for {id}: {e}")
            batch_data['user_options'] = None
        
        return batch_data
    
    @error_decorator
    def _get_device_batch_critical(self, id):
        """Fast batched endpoint that returns only the most critical device data."""
        device = self.validate_device_exists(id)
        
        # Get only the most critical data for fast initial load
        batch_data = {}
        
        try:
            # Core device info (always needed and fast)
            batch_data['data'] = device.info()
        except Exception as e:
            self.logger.error(f"Failed to get device info for {id}: {e}")
            batch_data['data'] = None
        
        # Skip machine_info and user_options for the critical load
        # These will be loaded separately by the UI
        
        return batch_data
    
    def _cache_img(self, file_like, basename):
        """Cache image file locally."""
        if not file_like:
            return ""
        
        local_file = os.path.join(self.tmp_imgs_dir, basename)
        tmp_file = tempfile.mktemp(prefix="ethoscope_", suffix=".jpg")
        
        try:
            with open(tmp_file, "wb") as lf:
                lf.write(file_like.read())
            shutil.move(tmp_file, local_file)
            return self.server._serve_tmp_static(os.path.basename(local_file))
        except Exception as e:
            self.logger.error(f"Error caching image: {e}")
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
            return ""