(function() {
    'use strict';

    var app = angular.module('flyApp');

    /**
     * Ethoscope Controller - Controls individual ethoscope device interface
     * Manages tracking, recording, machine settings, and real-time updates
     */
    app.controller('ethoscopeController', function($scope, $http, $routeParams, $interval, ethoscopeBackupService, ethoscopeFormService) {

        // ===========================
        // INITIALIZATION & VARIABLES
        // ===========================

        var device_id = $routeParams.device_id;
        var refresh_data = null;
        var spStart = null; // Initialize spinner when needed
        var starting_tracking = document.getElementById('starting');
        var $attempt = 0; // Time sync attempt counter

        // Initialize scope variables
        $scope.device = {}; // Device information and status
        $scope.ethoscope = {}; // Device control functions
        $scope.machine_info = {}; // Hardware and system information
        $scope.user_options = {}; // Available tracking/recording options from server
        $scope.selected_options = {}; // Currently selected options for forms
        $scope.node = { // Node-level data (users, incubators, sensors)
            users: {},
            incubators: {},
            sensors: {}
        };
        $scope.stimulatorSequence = []; // Array for stimulator sequence

        // Backup status cache
        $scope.backupSummary = null; // Cached backup summary to prevent digest loops
        $scope.lastBackupStatusLoad = 0; // Timestamp of last backup status load

        // UI state variables
        $scope.showLog = false;
        $scope.can_stream = false;
        $scope.isActive = false;

        // Cache for static data to reduce repeated requests
        var nodeConfigCache = {
            data: null,
            timestamp: 0,
            maxAge: 5 * 60 * 1000 // Cache for 5 minutes
        };

        // Cache node server timestamp to avoid repeated requests
        var nodeTimestampCache = {
            timestamp: 0,
            cachedAt: 0,
            maxAge: 30 * 1000 // Cache for 30 seconds
        };

        // Date range picker configuration for stimulator scheduling
        // Initialize with safe defaults, will be updated when moment.js is available
        $scope.dateRangeOptions = {
            timePicker: true,
            timePicker24Hour: true,
            timePickerIncrement: 30,
            drops: 'up',
            autoApply: true,
            autoUpdateInput: false, // Prevent auto-update to avoid setStartDate errors
            minDate: new Date(), // Will be updated to moment() when available
            locale: {
                format: 'YYYY-MM-DD HH:mm:ss',
                separator: ' > ',
                applyLabel: 'Apply',
                cancelLabel: 'Cancel',
                fromLabel: 'From',
                toLabel: 'To'
            }
        };

        // Centralized moment.js locale configuration
        var momentLocaleConfigured = false;

        function ensureMomentLocale() {
            if (typeof moment !== 'undefined' && moment.locale && !momentLocaleConfigured) {
                moment.locale('en');
                momentLocaleConfigured = true;
                console.log('Moment.js locale configured to: en');
            }
            return momentLocaleConfigured;
        }

        // Update dateRangeOptions when moment.js becomes available
        var momentCheckAttempts = 0;
        var maxMomentCheckAttempts = 50; // Max 5 seconds (50 * 100ms)

        function updateDateRangeOptions() {
            if (typeof moment !== 'undefined' && moment.locale) {
                // Ensure moment.js locale is configured
                ensureMomentLocale();
                $scope.dateRangeOptions.minDate = moment();
                // Force Angular to update the view
                if (!$scope.$$phase) {
                    $scope.$apply();
                }
                console.log('Date range picker updated with moment.js');
                return; // Exit successfully
            } else {
                momentCheckAttempts++;
                if (momentCheckAttempts < maxMomentCheckAttempts) {
                    // Retry after a short delay if moment isn't ready yet
                    setTimeout(updateDateRangeOptions, 100);
                } else {
                    console.warn('Moment.js not available after ' + maxMomentCheckAttempts + ' attempts. Using fallback date configuration.');
                    // Fallback to native Date for minDate
                    $scope.dateRangeOptions.minDate = new Date();
                }
            }
        }

        // Start the check
        updateDateRangeOptions();

        // ===========================
        // DATA LOADING FUNCTIONS
        // ===========================

        /**
         * Load node-level data (users, incubators, sensors) - OPTIMIZED WITH CACHING
         */
        function loadNodeData() {
            var now = new Date().getTime();

            // Check if we have cached data that's still valid
            if (nodeConfigCache.data && (now - nodeConfigCache.timestamp) < nodeConfigCache.maxAge) {
                console.log('Using cached node configuration data');
                $scope.node.users = nodeConfigCache.data.users;
                $scope.node.incubators = nodeConfigCache.data.incubators;
                $scope.node.sensors = nodeConfigCache.data.sensors;
                $scope.node.timestamp = nodeConfigCache.data.timestamp;
                return;
            }

            // Use batched endpoint to load all node config in one request
            $http.get('/node/config')
                .then(function(response) {
                    // Update cache
                    nodeConfigCache.data = response.data;
                    nodeConfigCache.timestamp = now;

                    // Update scope
                    $scope.node.users = response.data.users;
                    $scope.node.incubators = response.data.incubators;
                    $scope.node.sensors = response.data.sensors;
                    $scope.node.timestamp = response.data.timestamp;

                    // Cache the node timestamp for time sync operations
                    nodeTimestampCache.timestamp = response.data.timestamp;
                    nodeTimestampCache.cachedAt = now;
                })
                .catch(function(error) {
                    console.error('Failed to load node configuration:', error);
                    // Fallback to individual requests if batch fails
                    loadNodeDataFallback();
                });
        }

        /**
         * Fallback to individual requests if batched endpoint fails
         */
        function loadNodeDataFallback() {
            // Load users
            $http.get('/node/users')
                .then(function(response) {
                    $scope.node.users = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to load users:', error);
                });

            // Load incubators
            $http.get('/node/incubators')
                .then(function(response) {
                    $scope.node.incubators = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to load incubators:', error);
                });

            // Load sensors
            $http.get('/sensors')
                .then(function(response) {
                    $scope.node.sensors = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to load sensors:', error);
                });
        }

        /**
         * Load device-specific data - OPTIMIZED FOR SPEED
         */
        function loadDeviceData() {
            // First, load the critical data immediately (device info + timestamp)
            $http.get('/device/' + device_id + '/batch-critical')
                .then(function(response) {
                    var data = response.data;

                    // Set device data immediately
                    if (data.data) {
                        $scope.device = data.data;
                        // Device is active if it doesn't end with "_000"
                        $scope.isActive = ($scope.device.name.split("_").pop() !== "000");

                        // Update backup summary cache
                        ethoscopeBackupService.updateBackupSummary($scope);

                        // CRITICAL: Display timestamp immediately on load
                        updateTimestampDisplay(data.data);

                        // Initialize image URLs immediately for fast loading
                        var timestamp = Math.floor(new Date().getTime() / 30000.0) * 30;
                        $scope.device.url_img = "/device/" + $scope.device.id + "/last_img?" + timestamp;
                        $scope.device.url_stream = '/device/' + device_id + '/stream';
                    }

                    // Now load the non-critical data in the background
                    loadNonCriticalDeviceData();
                })
                .catch(function(error) {
                    console.error('Failed to load critical device data:', error);
                    // Fallback to individual requests if batch fails
                    loadDeviceDataFallback();
                });

            // Load video files asynchronously (less critical)
            loadVideoFilesAsync();
        }

        /**
         * Load non-critical device data in background after critical data is loaded
         */
        function loadNonCriticalDeviceData() {
            // Load machine info asynchronously
            $http.get('/device/' + device_id + '/machineinfo')
                .then(function(response) {
                    $scope.machine_info = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to load machine info:', error);
                });

            // Load user options asynchronously
            $http.get('/device/' + device_id + '/user_options')
                .then(function(response) {
                    var userOptions = response.data;

                    // Check streaming capability
                    $scope.can_stream = (typeof userOptions.streaming !== 'undefined');

                    // Store raw options data (preserves server order)
                    $scope.user_options = {
                        tracking: userOptions.tracking || {},
                        recording: userOptions.recording || {},
                        update_machine: userOptions.update_machine || {}
                    };

                    // Initialize selected options with default values using service
                    ethoscopeFormService.initializeSelectedOptions('tracking', userOptions.tracking || {}, $scope);
                    ethoscopeFormService.initializeSelectedOptions('recording', userOptions.recording || {}, $scope);
                    ethoscopeFormService.initializeSelectedOptions('update_machine', userOptions.update_machine || {}, $scope);

                    // Check database availability for append functionality
                    checkDatabaseAvailability();

                    // Populate node.database_list for frontend dropdown
                    updateNodeDatabaseList();

                    // Load ROI templates AFTER user options are initialized
                    $scope.loadRoiTemplates();
                })
                .catch(function(error) {
                    console.error('Failed to load user options:', error);
                });
        }

        /**
         * Fallback to individual requests if batched endpoint fails
         */
        function loadDeviceDataFallback() {
            // Load machine information
            $http.get('/device/' + device_id + '/machineinfo')
                .then(function(response) {
                    $scope.machine_info = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to load machine info:', error);
                });

            // Load device data and determine if device is active
            $http.get('/device/' + device_id + '/data')
                .then(function(response) {
                    $scope.device = response.data;
                    // Device is active if it doesn't end with "_000"
                    $scope.isActive = ($scope.device.name.split("_").pop() !== "000");

                    // Update backup summary cache
                    ethoscopeBackupService.updateBackupSummary($scope);

                    // Initialize image URLs immediately for fast loading
                    var timestamp = Math.floor(new Date().getTime() / 30000.0) * 30;
                    $scope.device.url_img = "/device/" + $scope.device.id + "/last_img?" + timestamp;
                    $scope.device.url_stream = '/device/' + device_id + '/stream';
                })
                .catch(function(error) {
                    console.error('Failed to load device data:', error);
                });
        }

        /**
         * Load video files asynchronously (can be slow, so load separately)
         */
        function loadVideoFilesAsync() {
            $http.get('/device/' + device_id + '/videofiles')
                .then(function(response) {
                    $scope.videofiles = response.data.filelist;
                })
                .catch(function(error) {
                    console.error('Failed to load video files:', error);
                    $scope.videofiles = [];
                });
        }

        // ===========================
        // FORM MANAGEMENT FUNCTIONS (Using Service)
        // ===========================

        /**
         * Update user option arguments when selection changes
         */
        $scope.ethoscope.update_user_options = function(optionType, name, selectedOptionName) {
            ethoscopeFormService.updateUserOptions(optionType, name, selectedOptionName, $scope);
        };

        // Convenience methods for different option types
        $scope.ethoscope.update_user_options.tracking = function(name, selectedOptionName) {
            ethoscopeFormService.updateUserOptions('tracking', name, selectedOptionName, $scope);
        };

        $scope.ethoscope.update_user_options.recording = function(name, selectedOptionName) {
            ethoscopeFormService.updateUserOptions('recording', name, selectedOptionName, $scope);
        };

        $scope.ethoscope.update_user_options.update_machine = function(name, selectedOptionName) {
            ethoscopeFormService.updateUserOptions('update_machine', name, selectedOptionName, $scope);
        };

        // Multi-stimulator functions (delegated to service)
        $scope.getSelectedStimulatorOption = function(name) {
            return ethoscopeFormService.getSelectedStimulatorOption(name, $scope);
        };

        $scope.getStimulatorArguments = function(className) {
            return ethoscopeFormService.getStimulatorArguments(className, $scope);
        };

        $scope.addNewStimulator = function() {
            ethoscopeFormService.addNewStimulator($scope);
        };

        $scope.removeStimulator = function(index) {
            ethoscopeFormService.removeStimulator(index, $scope);
        };

        $scope.updateStimulatorArguments = function(index) {
            ethoscopeFormService.updateStimulatorArguments(index, $scope);
        };

        $scope.addStimulatorToSequence = function() {
            ethoscopeFormService.addStimulatorToSequence($scope);
        };

        $scope.removeStimulatorFromSequence = function(index) {
            ethoscopeFormService.removeStimulatorFromSequence(index, $scope);
        };

        $scope.updateStimulatorInSequence = function(index) {
            ethoscopeFormService.updateStimulatorInSequence(index, $scope);
        };

        $scope.getInteractorOptionByName = function(name) {
            return ethoscopeFormService.getInteractorOptionByName(name, $scope);
        };

        $scope.isRoiTemplateSelected = function() {
            return ethoscopeFormService.isRoiTemplateSelected($scope);
        };

        $scope.isUserSelected = function() {
            return ethoscopeFormService.isUserSelected($scope);
        };

        // ===========================
        // BACKUP STATUS FUNCTIONS (Using Service)
        // ===========================

        function loadBackupInfo(forceLoad) {
            ethoscopeBackupService.loadBackupInfo(device_id, $scope, forceLoad);
        }

        function updateBackupSummary() {
            ethoscopeBackupService.updateBackupSummary($scope);
        }

        /**
         * Get the keys of an object (helper for ng-repeat)
         */
        $scope.getObjectKeys = function(obj) {
            return obj ? Object.keys(obj) : [];
        };

        /**
         * Format file size in human readable format
         */
        $scope.formatFileSize = function(bytes) {
            if (!bytes || bytes === 0) return '0 B';

            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));

            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        };

        /**
         * Format date from Unix timestamp
         */
        $scope.formatDate = function(timestamp) {
            if (!timestamp) return 'Unknown';

            const date = new Date(timestamp * 1000);
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        };

        /**
         * Extract datetime from database filename
         */
        $scope.extractDateTimeFromFilename = function(filename) {
            if (!filename) return 'Unknown';

            // Pattern to match database files like "device_2024-01-15_14-30-45.db"
            var dateTimePattern = /(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})/;
            var match = filename.match(dateTimePattern);

            if (match) {
                var dateTimeStr = match[1];
                // Convert format from YYYY-MM-DD_HH-MM-SS to readable format
                var parts = dateTimeStr.split('_');
                if (parts.length === 2) {
                    var datePart = parts[0]; // YYYY-MM-DD
                    var timePart = parts[1].replace(/-/g, ':'); // HH:MM:SS

                    try {
                        var date = new Date(datePart + 'T' + timePart);
                        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
                    } catch (e) {
                        // If parsing fails, return the extracted datetime string
                        return datePart + ' ' + timePart;
                    }
                }
            }

            // If no datetime pattern found, return just the base filename without extension
            return filename.replace(/\.[^/.]+$/, "");
        };

        /**
         * Get time since backup in human readable format
         */
        $scope.getTimeSinceBackup = function(timestamp) {
            if (!timestamp) return 'Never';

            const now = Math.floor(Date.now() / 1000);
            const elapsed = now - timestamp;

            if (elapsed < 60) {
                return 'Just now';
            } else if (elapsed < 3600) {
                const minutes = Math.floor(elapsed / 60);
                return minutes + ' minute' + (minutes > 1 ? 's' : '') + ' ago';
            } else if (elapsed < 86400) {
                const hours = Math.floor(elapsed / 3600);
                return hours + ' hour' + (hours > 1 ? 's' : '') + ' ago';
            } else {
                const days = Math.floor(elapsed / 86400);
                return days + ' day' + (days > 1 ? 's' : '') + ' ago';
            }
        };

        /**
         * Get backup status class for progress bar
         */
        $scope.getBackupBarClass = function(dbInfo, backupType) {
            if (!dbInfo) return 'unknown';

            // If using backup info
            if ($scope.backupSummary && $scope.backupSummary.useBackupInfo && backupType && $scope.device.backup_info) {
                const backupStatus = $scope.device.backup_info.backup_status[backupType];
                if (backupStatus) {
                    if (backupStatus.available && backupStatus.database_count > 0) {
                        return 'backed-up';
                    } else {
                        return 'missing-backup';
                    }
                }
            }

            // Legacy fallback
            if (dbInfo.file_exists === true) {
                return 'backed-up';
            } else if (dbInfo.file_exists === false) {
                return 'missing-backup';
            } else if (dbInfo.db_status === 'tracking') {
                return 'processing';
            } else {
                return 'unknown';
            }
        };

        /**
         * Get backup progress style for the progress bar fill
         */
        $scope.getBackupProgressStyle = function(dbInfo, dbType) {
            if (!dbInfo) return {
                width: '0%'
            };

            let width = '0%';

            // If using backup info
            if ($scope.backupSummary && $scope.backupSummary.useBackupInfo && $scope.device.backup_info) {
                const backupTypeMap = {
                    'mariadb': 'mysql',
                    'sqlite': 'sqlite',
                    'video': 'video'
                };
                const mappedType = backupTypeMap[dbType] || dbType;
                const backupStatus = $scope.device.backup_info.backup_status[mappedType];

                if (backupStatus) {
                    if (backupStatus.available && backupStatus.database_count > 0) {
                        width = '100%';
                    } else {
                        width = '100%';
                    }
                }
            } else {
                // Legacy fallback
                if (dbInfo.file_exists === true) {
                    width = '100%';
                } else if (dbInfo.file_exists === false) {
                    width = '100%';
                } else if (dbInfo.db_status === 'tracking') {
                    width = '75%';
                } else {
                    width = '25%';
                }
            }

            return {
                width: width
            };
        };

        /**
         * Get backup status text for tooltip
         */
        $scope.getBackupStatusText = function(dbInfo, backupType) {
            if (!dbInfo) return 'Unknown';

            // If using backup info, try to get file path/name
            if ($scope.backupSummary && $scope.backupSummary.useBackupInfo && backupType && $scope.device.backup_info) {
                
                // For MySQL, get the backup filename from MariaDB databases
                if (backupType === 'mysql' && $scope.device.databases && $scope.device.databases.MariaDB) {
                    var filePaths = [];
                    for (var dbName in $scope.device.databases.MariaDB) {
                        if ($scope.device.databases.MariaDB.hasOwnProperty(dbName)) {
                            var dbData = $scope.device.databases.MariaDB[dbName];
                            if (dbData.backup_filename) {
                                filePaths.push(dbData.backup_filename);
                            } else if (dbData.path) {
                                filePaths.push(dbData.path);
                            } else {
                                filePaths.push(dbName);
                            }
                        }
                    }
                    if (filePaths.length > 0) {
                        return filePaths.join(', ');
                    }
                }
                
                const backupStatus = $scope.device.backup_info.backup_status[backupType];
                if (backupStatus) {
                    if (backupStatus.available && backupStatus.database_count > 0) {
                        return 'Available (' + backupStatus.database_count + ' db' + (backupStatus.database_count > 1 ? 's' : '') + ')';
                    } else {
                        return 'Not Available';
                    }
                }
            }

            // Legacy fallback
            if (dbInfo.file_exists === true) {
                return 'Backed Up';
            } else if (dbInfo.file_exists === false) {
                return 'Missing';
            } else if (dbInfo.db_status === 'tracking') {
                return 'In Progress';
            } else {
                return 'Unknown';
            }
        };

        /**
         * Get overall backup status class for the toggle icon
         */
        $scope.getBackupStatusClass = function() {
            if (!$scope.backupSummary) {
                return 'backup-status-unknown';
            }

            // Use backup info if available
            if ($scope.backupSummary.useBackupInfo && $scope.device.backup_info) {
                const recommendedType = $scope.device.backup_info.recommended_backup_type;
                if (recommendedType === 'mysql' || recommendedType === 'sqlite') {
                    return 'backup-status-success';
                } else {
                    return 'backup-status-warning';
                }
            }

            // Legacy fallback
            if ($scope.backupSummary.backedUp === $scope.backupSummary.total && $scope.backupSummary.total > 0) {
                return 'backup-status-success';
            } else if ($scope.backupSummary.backedUp === 0 && $scope.backupSummary.total > 0) {
                return 'backup-status-error';
            } else if ($scope.backupSummary.backedUp > 0) {
                return 'backup-status-warning';
            } else {
                return 'backup-status-unknown';
            }
        };

        /**
         * Get backup summary statistics (cached)
         */
        $scope.getBackupSummary = function() {
            return $scope.backupSummary;
        };

        /**
         * Get overall status CSS class
         */
        $scope.getOverallStatusClass = function() {
            if (!$scope.backupSummary) return 'overall-status-unknown';

            // Use backup info if available
            if ($scope.backupSummary.useBackupInfo && $scope.device.backup_info) {
                const recommendedType = $scope.device.backup_info.recommended_backup_type;
                if (recommendedType === 'mysql' || recommendedType === 'sqlite') {
                    return 'overall-status-success';
                } else {
                    return 'overall-status-warning';
                }
            }

            // Legacy fallback
            if ($scope.backupSummary.backedUp === $scope.backupSummary.total && $scope.backupSummary.total > 0) {
                return 'overall-status-success';
            } else if ($scope.backupSummary.backedUp === 0 && $scope.backupSummary.total > 0) {
                return 'overall-status-error';
            } else if ($scope.backupSummary.backedUp > 0) {
                return 'overall-status-warning';
            } else {
                return 'overall-status-unknown';
            }
        };

        // ===========================
        // UTILITY FUNCTIONS
        // ===========================

        /**
         * Manage loading spinner display
         */
        function manageSpinner(action) {
            if (action === 'start' && starting_tracking) {
                spStart = new Spinner(opts).spin();
                starting_tracking.appendChild(spStart.el);
            } else if (action === 'stop' && spStart) {
                spStart.stop();
                spStart = null;
            }
        }

        /**
         * Get sensor IP address by location
         */
        $scope.get_ip_of_sensor = function(location) {
            if (!location || !$scope.node.sensors) return null;

            location = location.replace(/\s+/g, '_');
            for (var sensor in $scope.node.sensors) {
                if ($scope.node.sensors[sensor].location === location) {
                    return $scope.node.sensors[sensor].ip;
                }
            }
            return null;
        };

        /**
         * Check if device has a valid (non-default) interactor
         */
        $scope.hasValidInteractor = function(device) {
            return (
                device.status === 'running' &&
                device.experimental_info &&
                device.experimental_info.current &&
                device.experimental_info.current.interactor &&
                device.experimental_info.current.interactor.name !== "<class 'ethoscope.stimulators.stimulators.DefaultStimulator'>"
            );
        };

        /**
         * Calculate elapsed time from timestamp
         */
        $scope.ethoscope.elapsedtime = function(t) {
            var now = Math.floor(Date.now() / 1000);
            var elapsed = now - t;

            var days = Math.floor(elapsed / 86400);
            var hours = Math.floor((elapsed - (days * 86400)) / 3600);
            var minutes = Math.floor((elapsed - (days * 86400) - (hours * 3600)) / 60);
            var secs = Math.floor(elapsed - (days * 86400) - (hours * 3600) - (minutes * 60));

            var result = "";
            if (days > 0) result += days + " days, ";
            if (hours > 0 || days > 0) result += hours + "h, ";
            if (minutes > 0 || hours > 0 || days > 0) result += minutes + "min, ";
            result += secs + "s";

            return result;
        };

        /**
         * Create readable URL from full path
         */
        $scope.ethoscope.readable_url = function(url) {
            if (!url) return '';
            var parts = url.split("/");
            return ".../"+parts[parts.length-1];
        };

        /**
         * Convert Unix timestamp to readable date string
         */
        $scope.ethoscope.start_date_time = function(unix_timestamp) {
            return new Date(unix_timestamp * 1000).toUTCString();
        };

        /**
         * Show alert message
         */
        $scope.ethoscope.alert = function(message) {
            alert(message);
        };

        // Watch for changes in template selection to update UI
        $scope.$watch('selected_options.tracking.roi_builder.arguments.template_name', function(newValue, oldValue) {
            if (newValue !== oldValue) {
                // Force UI update when template selection changes
                $scope.$evalAsync();
            }
        });

        // ===========================
        // TRACKING & RECORDING FUNCTIONS
        // ===========================

        /**
         * Start tracking with selected options
         */
        $scope.ethoscope.start_tracking = function(option) {
            $("#startModal").modal('hide');
            manageSpinner('start');

            // Process arguments - extract formatted values from date range pickers
            for (var opt in option) {
                for (var arg in option[opt].arguments) {
                    // Extract formatted field from date range picker objects
                    if (option[opt].arguments[arg] &&
                        typeof option[opt].arguments[arg] === 'object' &&
                        option[opt].arguments[arg].hasOwnProperty('formatted')) {
                        option[opt].arguments[arg] = option[opt].arguments[arg].formatted;
                    }
                }
            }

            // Add sensor IP based on selected incubator name
            if (option.experimental_info && option.experimental_info.arguments && option.experimental_info.arguments.location) {
                var selectedIncubatorName = option.experimental_info.arguments.location;
                option.experimental_info.arguments.sensor = $scope.get_ip_of_sensor(selectedIncubatorName);
            }

            // Include stimulator sequence in the data sent to backend
            if ($scope.stimulatorSequence && $scope.stimulatorSequence.length > 0) {
                // Process stimulator sequence date range pickers
                for (var i = 0; i < $scope.stimulatorSequence.length; i++) {
                    var stimulator = $scope.stimulatorSequence[i];
                    if (stimulator.arguments) {
                        for (var argName in stimulator.arguments) {
                            // Extract formatted field from date range picker objects
                            if (stimulator.arguments[argName] &&
                                typeof stimulator.arguments[argName] === 'object' &&
                                stimulator.arguments[argName].hasOwnProperty('formatted')) {
                                stimulator.arguments[argName] = stimulator.arguments[argName].formatted;
                            }
                        }
                    }
                }

                // If only one stimulator, use it directly without MultiStimulator wrapper
                if ($scope.stimulatorSequence.length === 1) {
                    var singleStimulator = $scope.stimulatorSequence[0];
                    
                    // Create arguments object including date_range
                    var stimulatorArguments = {};
                    if (singleStimulator.arguments) {
                        for (var key in singleStimulator.arguments) {
                            stimulatorArguments[key] = singleStimulator.arguments[key];
                        }
                    }
                    
                    option.interactor = {
                        name: singleStimulator.name,
                        arguments: stimulatorArguments
                    };
                    
                    console.log('Configured single stimulator:', singleStimulator.name, 'with arguments:', stimulatorArguments);
                    
                } else {
                    // Multiple stimulators - use MultiStimulator configuration
                    option.interactor = {
                        name: 'MultiStimulator',
                        arguments: {
                            stimulator_sequence: $scope.stimulatorSequence.map(function(stim) {
                                // Create a clean copy of arguments without the date_range
                                var cleanArguments = {};
                                if (stim.arguments) {
                                    for (var key in stim.arguments) {
                                        if (key !== 'date_range') {
                                            cleanArguments[key] = stim.arguments[key];
                                        }
                                    }
                                }

                                return {
                                    class_name: stim.name,
                                    arguments: cleanArguments,
                                    date_range: (stim.arguments && stim.arguments.date_range) ?
                                        (typeof stim.arguments.date_range === 'string' ? stim.arguments.date_range : '') : ''
                                };
                            })
                        }
                    };
                    
                    // Sanitize the data to prevent JSON errors
                    try {
                        JSON.stringify(option.interactor.arguments.stimulator_sequence);
                        console.log('Configured MultiStimulator with sequence:', option.interactor.arguments.stimulator_sequence);
                    } catch (jsonError) {
                        console.error('JSON serialization error in stimulator sequence:', jsonError);
                        console.log('Raw stimulator sequence:', $scope.stimulatorSequence);
                        // Fallback to DefaultStimulator if JSON serialization fails
                        option.interactor = {
                            name: 'DefaultStimulator',
                            arguments: {}
                        };
                    }
                }
            } else {
                // If no stimulators in sequence, use DefaultStimulator
                if (!option.interactor || !option.interactor.name) {
                    option.interactor = {
                        name: 'DefaultStimulator',
                        arguments: {}
                    };
                }
            }

            // Check if we need to handle custom template transfer for FileBasedROIBuilder
            var templateName = null;
            var isCustomTemplate = false;

            if (option.roi_builder && option.roi_builder.arguments && option.roi_builder.arguments.template_name) {
                templateName = option.roi_builder.arguments.template_name;

                // Check if this is a custom template by looking at the selected option
                var selectedTemplateInfo = $scope.getSelectedTemplateInfo(templateName);
                isCustomTemplate = selectedTemplateInfo && selectedTemplateInfo.type === 'custom';

                if (isCustomTemplate && templateName) {
                    // For custom templates, ensure they're transferred to the device
                    console.log("Custom template detected: " + templateName + ". Uploading to device if needed.");
                    $scope.uploadTemplateToDevice(templateName, function(success) {
                        if (success) {
                            console.log("Custom template uploaded successfully");
                        } else {
                            console.log("Custom template upload failed, proceeding anyway");
                        }
                        startTrackingWithData();
                    });
                } else {
                    // For builtin templates, no transfer needed
                    if (templateName) {
                        console.log("Builtin template detected: " + templateName + ". No transfer needed.");
                    }

                    console.log('Starting tracking with options:', option);

                    // Send start command to ethoscope
                    $http.post('/device/' + device_id + '/controls/start', option)
                        .then(function(response) {
                            $scope.device.status = response.data.status;
                            // Refresh device data after starting
                            refreshDeviceStatus();
                        })
                        .catch(function(error) {
                            console.error('Failed to start tracking:', error);
                            manageSpinner('stop');
                        });
                }
            }
        };

        // Helper function to get template information by name
        $scope.getSelectedTemplateInfo = function(templateName) {
            if ($scope.available_templates) {
                for (var i = 0; i < $scope.available_templates.length; i++) {
                    if ($scope.available_templates[i].value === templateName) {
                        return $scope.available_templates[i];
                    }
                }
            }
            return null;
        };

        // Load ROI templates from node server
        $scope.loadRoiTemplates = function() {
            $http.get('/roi_templates').then(function(response) {
                var data = response.data;
                // Store template information for later use
                $scope.available_templates = data.templates;

                // Find default template if any
                var defaultTemplate = null;
                for (var k = 0; k < data.templates.length; k++) {
                    if (data.templates[k].is_default === true) {
                        defaultTemplate = data.templates[k].value;
                        break;
                    }
                }

                // Store default template for later use
                $scope.defaultTemplate = defaultTemplate;

                // Update template dropdown options for FileBasedROIBuilder
                if ($scope.user_options && $scope.user_options.tracking &&
                    $scope.user_options.tracking.roi_builder) {

                    for (var i = 0; i < $scope.user_options.tracking.roi_builder.length; i++) {
                        var roiBuilder = $scope.user_options.tracking.roi_builder[i];

                        // Check if this is a FileBasedROIBuilder
                        if (roiBuilder.name === 'FileBasedROIBuilder' ||
                            roiBuilder.class === 'FileBasedROIBuilder') {

                            // Find template_name argument
                            for (var j = 0; j < roiBuilder.arguments.length; j++) {
                                var arg = roiBuilder.arguments[j];
                                if (arg.name === 'template_name') {
                                    // Separate builtin and custom templates
                                    var builtinTemplates = data.templates.filter(function(template) {
                                        return template.type === 'builtin';
                                    }).map(function(template) {
                                        return {
                                            value: template.value,
                                            text: template.text
                                        };
                                    });

                                    var customTemplates = data.templates.filter(function(template) {
                                        return template.type === 'custom';
                                    }).map(function(template) {
                                        return {
                                            value: template.value,
                                            text: template.text
                                        };
                                    });

                                    // Create grouped structure
                                    var groups = [];
                                    if (builtinTemplates.length > 0) {
                                        groups.push({
                                            group: "builtin",
                                            label: "Built-in Templates",
                                            options: builtinTemplates
                                        });
                                    }
                                    if (customTemplates.length > 0) {
                                        groups.push({
                                            group: "custom",
                                            label: "Custom Templates",
                                            options: customTemplates
                                        });
                                    }

                                    // Set the groups structure
                                    arg.groups = groups;
                                    // Remove old options if it exists
                                    delete arg.options;

                                    // Apply default template selection
                                    $scope.applyDefaultTemplate();
                                    break;
                                }
                            }
                        }
                    }
                }
            }, function(error) {
                console.log("Could not load ROI templates from node server");
            });
        };

        // Helper function to apply default template selection
        $scope.applyDefaultTemplate = function() {
            if (!$scope.defaultTemplate) {
                console.log('No default template found');
                return;
            }

            if (!$scope.selected_options || !$scope.selected_options.tracking || !$scope.selected_options.tracking.roi_builder) {
                console.log('ROI builder not initialized yet');
                return;
            }

            // Check if FileBasedROIBuilder is selected
            var roiBuilderName = $scope.selected_options.tracking.roi_builder.name;
            if (!roiBuilderName || roiBuilderName.indexOf('FileBasedROIBuilder') === -1) {
                console.log('FileBasedROIBuilder not selected, current:', roiBuilderName);
                return;
            }

            // Ensure arguments object exists
            if (!$scope.selected_options.tracking.roi_builder.arguments) {
                $scope.selected_options.tracking.roi_builder.arguments = {};
            }

            // Only set default if no template is currently selected or if it's empty
            var currentTemplate = $scope.selected_options.tracking.roi_builder.arguments.template_name;
            if (!currentTemplate || currentTemplate === '' || currentTemplate === 'null' || currentTemplate === 'undefined') {
                $scope.selected_options.tracking.roi_builder.arguments.template_name = $scope.defaultTemplate;
                console.log('Default ROI template applied:', $scope.defaultTemplate);

                // Force Angular digest cycle
                setTimeout(function() {
                    if (!$scope.$$phase) {
                        $scope.$apply();
                    }
                }, 0);
            } else {
                console.log('Template already selected:', currentTemplate);
            }
        };

        // Upload template to device when needed
        $scope.uploadTemplateToDevice = function(templateName, callback) {
            $http.post('/device/' + device_id + '/upload_template', {
                    template_name: templateName
                })
                .then(function(response) {
                    var data = response.data;
                    console.log("Template uploaded to device: " + templateName);
                    if (callback) callback(true);
                }, function(error) {
                    console.log("Failed to upload template to device: " + templateName);
                    if (callback) callback(false);
                });
        };

        /**
         * Start video recording with selected options
         */
        $scope.ethoscope.start_recording = function(option) {
            $("#recordModal").modal('hide');
            manageSpinner('start');

            // Process datetime arguments - extract timestamp from Date objects
            for (var opt in option) {
                for (var arg in option[opt].arguments) {
                    if (option[opt].arguments[arg] &&
                        Array.isArray(option[opt].arguments[arg]) &&
                        option[opt].arguments[arg][0] instanceof Date) {
                        option[opt].arguments[arg] = option[opt].arguments[arg][1]; // Use timestamp
                    }
                }
            }

            $http.post('/device/' + device_id + '/controls/start_record', option)
                .then(function(response) {
                    $scope.device.status = response.data.status;
                    $scope.device.countdown = response.data.autostop;
                    refreshDeviceStatus();
                })
                .catch(function(error) {
                    console.error('Failed to start recording:', error);
                    manageSpinner('stop');
                });
        };

        /**
         * Stop current tracking or recording
         */
        $scope.ethoscope.stop = function() {
            console.log("Stopping tracking/recording");
            $http.post('/device/' + device_id + '/controls/stop', {})
                .then(function(response) {
                    $scope.device.status = response.data.status;
                })
                .catch(function(error) {
                    console.error('Failed to stop:', error);
                });
        };

        // ===========================
        // DEVICE CONTROL FUNCTIONS
        // ===========================

        /**
         * Update machine settings
         */
        $scope.ethoscope.update_machine = function(option) {
            $("#changeInfo").modal('hide');
            $http.post('/device/' + device_id + '/machineinfo', option)
                .then(function(response) {
                    $scope.machine_info = response.data;

                    // Immediately refresh device data to show updated time/settings
                    refreshDeviceStatus();

                    if (response.data.haschanged) {
                        $scope.ethoscope.alert("Some settings have changed. Please REBOOT your ethoscope now.");
                    }
                })
                .catch(function(error) {
                    console.error('Failed to update machine info:', error);
                });
        };

        /**
         * Power off the ethoscope device
         */
        $scope.ethoscope.poweroff = function() {
            $http.post('/device/' + device_id + '/controls/poweroff', {})
                .then(function(response) {
                    $scope.device = response.data;
                    window.close();
                })
                .catch(function(error) {
                    console.error('Failed to power off:', error);
                });
        };

        /**
         * Reboot the ethoscope device
         */
        $scope.ethoscope.reboot = function() {
            console.log("Rebooting ethoscope");
            $http.post('/device/' + device_id + '/controls/reboot', {})
                .then(function(response) {
                    $scope.device = response.data;
                    window.close();
                })
                .catch(function(error) {
                    console.error('Failed to reboot:', error);
                });
        };

        /**
         * Restart ethoscope software (without rebooting hardware)
         */
        $scope.ethoscope.restart = function() {
            console.log("Restarting ethoscope software");
            $http.post('/device/' + device_id + '/controls/restart', {})
                .then(function(response) {
                    $scope.device = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to restart:', error);
                });
        };

        // ===========================
        // STREAMING & VIDEO FUNCTIONS
        // ===========================

        /**
         * Start real-time video streaming
         */
        $scope.ethoscope.stream = function() {
            if (!$scope.can_stream) {
                console.warn("Streaming not available for this device");
                return;
            }

            console.log("Starting real-time stream");
            $http.post('/device/' + device_id + '/controls/stream', {
                    recorder: {
                        name: "Streamer",
                        arguments: {}
                    }
                })
                .then(function(response) {
                    $scope.device.status = response.data.status;
                    window.location.reload();
                })
                .catch(function(error) {
                    console.error('Failed to start stream:', error);
                });
        };

        /**
         * Convert H264 video chunks to MP4 format
         */
        $scope.ethoscope.convertvideos = function() {
            console.log("Converting H264 chunks to MP4");
            $http.post('/device/' + device_id + '/controls/convertvideos')
                .then(function(response) {
                    $scope.device.status = response.data.status;
                    window.location.reload();
                })
                .catch(function(error) {
                    console.error('Failed to convert videos:', error);
                });
        };

        // ===========================
        // MAINTENANCE FUNCTIONS
        // ===========================

        /**
         * Create device backup
         */
        $scope.ethoscope.backup = function() {
            $http.post('/device/' + device_id + '/backup', {})
                .then(function(response) {
                    $scope.device = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to create backup:', error);
                });
        };

        /**
         * Dump SQL database with progress tracking
         */
        $scope.ethoscope.SQLdump = function() {
            function checkDumpStatus() {
                $http.get('/device/' + device_id + '/dumpSQLdb')
                    .then(function(response) {
                        $scope.SQLdumpStatus = response.data.Status;
                        $scope.SQLdumpStarted = response.data.Started;
                    })
                    .catch(function(error) {
                        console.error('Failed to check SQL dump status:', error);
                    });
            }

            // Poll dump status every 2 seconds until finished
            var timer = setInterval(function() {
                if ($scope.SQLdumpStatus !== 'Finished') {
                    checkDumpStatus();
                } else {
                    clearInterval(timer);
                }
            }, 2000);
        };

        /**
         * Test connected hardware module
         */
        $scope.ethoscope.testModule = function() {
            console.log("Testing attached hardware module");
            $http.post('/device/' + device_id + '/controls/test_module')
                .then(function(response) {
                    $scope.device.status = response.data.status;
                    window.location.reload();
                })
                .catch(function(error) {
                    console.error('Failed to test module:', error);
                });
        };

        /**
         * Toggle device log display
         */
        $scope.ethoscope.log = function() {
            // Always refresh machine info when accessing logs
            $http.get('/device/' + device_id + '/machineinfo')
                .then(function(response) {
                    $scope.machine_info = response.data;
                })
                .catch(function(error) {
                    console.error('Failed to load machine info:', error);
                });

            if (!$scope.showLog) {
                // Show logs
                var log_file_path = $scope.device.log_file;
                $http.post('/device/' + device_id + '/log', {
                        file_path: log_file_path
                    })
                    .then(function(response) {
                        $scope.log = response.data;
                        $scope.showLog = true;
                    })
                    .catch(function(error) {
                        console.error('Failed to load logs:', error);
                    });
            } else {
                // Hide logs
                $scope.showLog = false;
            }
        };

        // ===========================
        // TIMESTAMP DISPLAY FUNCTIONS
        // ===========================

        /**
         * Update timestamp display immediately when device data is available
         */
        function updateTimestampDisplay(deviceData) {
            // Initialize time display immediately - don't wait for node timestamp
            if (deviceData.current_timestamp) {
                $scope.device_timestamp = new Date(deviceData.current_timestamp * 1000);
                $scope.device_datetime = $scope.device_timestamp.toUTCString();

                // Show local node time immediately (no HTTP request needed)
                var local_time = new Date();
                $scope.node_datetime = local_time.toUTCString();
                $scope.delta_t_min = Math.abs((local_time.getTime() / 1000 - deviceData.current_timestamp) / 60);
            } else {
                $scope.node_datetime = "Node Time";
                $scope.device_datetime = "Device Time";
            }

            // Check time synchronization with node asynchronously (don't block UI)
            if (deviceData.current_timestamp) {
                var now = new Date().getTime();
                var useCache = nodeTimestampCache.timestamp &&
                    (now - nodeTimestampCache.cachedAt) < nodeTimestampCache.maxAge;

                if (useCache) {
                    // Use cached timestamp - no HTTP request needed
                    var node_t = nodeTimestampCache.timestamp;
                    var node_time = new Date(node_t * 1000);
                    $scope.node_datetime = node_time.toUTCString();
                    $scope.delta_t_min = Math.abs((node_t - deviceData.current_timestamp) / 60);

                    // Auto-correct time if difference > 3 minutes (max 3 attempts)
                    if ($scope.delta_t_min > 3 && $attempt < 3) {
                        $scope.ethoscope.update_machine({
                            machine_options: {
                                arguments: {
                                    datetime: new Date().getTime() / 1000
                                },
                                name: 'datetime'
                            }
                        });
                        $attempt++;
                        console.log("Auto-correcting device time. Attempt:", $attempt);
                    }
                } else {
                    // Fetch fresh timestamp
                    $http.get('/node/timestamp')
                        .then(function(node_response) {
                            var node_t = node_response.data.timestamp;
                            var node_time = new Date(node_t * 1000);
                            $scope.node_datetime = node_time.toUTCString();
                            $scope.delta_t_min = Math.abs((node_t - deviceData.current_timestamp) / 60);

                            // Update cache
                            nodeTimestampCache.timestamp = node_t;
                            nodeTimestampCache.cachedAt = now;

                            // Auto-correct time if difference > 3 minutes (max 3 attempts)
                            if ($scope.delta_t_min > 3 && $attempt < 3) {
                                $scope.ethoscope.update_machine({
                                    machine_options: {
                                        arguments: {
                                            datetime: new Date().getTime() / 1000
                                        },
                                        name: 'datetime'
                                    }
                                });
                                $attempt++;
                                console.log("Auto-correcting device time. Attempt:", $attempt);
                            }
                        })
                        .catch(function(error) {
                            console.error('Failed to get node timestamp:', error);
                        });
                }
            }
        }

        // ===========================
        // REAL-TIME UPDATE FUNCTIONS
        // ===========================

        /**
         * Refresh device status after operations
         */
        function refreshDeviceStatus() {
            $http.get('/devices')
                .then(function() {
                    return $http.get('/device/' + device_id + '/data');
                })
                .then(function(response) {
                    // Preserve backup_info and backup_status_detailed during device refresh
                    var existingBackupInfo = $scope.device ? $scope.device.backup_info : null;
                    var existingBackupStatusDetailed = $scope.device ? $scope.device.backup_status_detailed : null;

                    $scope.device = response.data;

                    // Restore preserved backup info
                    if (existingBackupInfo) {
                        $scope.device.backup_info = existingBackupInfo;
                    }

                    // Restore preserved detailed backup status
                    if (existingBackupStatusDetailed) {
                        $scope.device.backup_status_detailed = existingBackupStatusDetailed;
                    }

                    // Update backup summary cache when device data changes
                    updateBackupSummary();
                })
                .catch(function(error) {
                    console.error('Failed to refresh device status:', error);
                });
        }

        /**
         * Main refresh function - updates device data and handles time synchronization
         */
        function refresh() {
            // Only refresh when page is visible (performance optimization)
            if (document.visibilityState !== "visible") return;

            $http.get('/device/' + device_id + '/data')
                .then(function(response) {
                    var data = response.data;

                    // Preserve backup_info, backup_status_detailed, and databases during device refresh
                    var existingBackupInfo = $scope.device ? $scope.device.backup_info : null;
                    var existingBackupStatusDetailed = $scope.device ? $scope.device.backup_status_detailed : null;
                    var existingDatabases = $scope.device ? $scope.device.databases : null;

                    $scope.device = data;

                    // Restore preserved backup info
                    if (existingBackupInfo) {
                        $scope.device.backup_info = existingBackupInfo;
                    }

                    // Restore preserved detailed backup status
                    if (existingBackupStatusDetailed) {
                        $scope.device.backup_status_detailed = existingBackupStatusDetailed;
                    }

                    // Restore preserved databases info (if not present in fresh data)
                    if (existingDatabases && (!data.databases || Object.keys(data.databases).length === 0)) {
                        $scope.device.databases = existingDatabases;
                    }

                    console.log('DEBUG: Data received in refresh function:', data);

                    // Update backup summary cache when device data changes
                    updateBackupSummary();

                    // Update node.database_list for frontend dropdown
                    updateNodeDatabaseList();

                    // Update timestamp display using the extracted function
                    updateTimestampDisplay(data);

                    // Update device URLs with reduced cache busting (every 30 seconds instead of every refresh)
                    var timestamp = Math.floor(new Date().getTime() / 30000.0) * 30;
                    $scope.device.url_img = "/device/" + $scope.device.id + "/last_img?" + timestamp;
                    $scope.device.url_stream = '/device/' + device_id + '/stream';

                    // TODO: Fix upload URL to point to local server
                    $scope.device.url_upload = "http://" + $scope.device.ip + ":9000/upload/" + $scope.device.id;

                    // Stop spinner when device is no longer initializing/stopping
                    var status = $scope.device.status;
                    if (spStart &&
                        status !== 'initialising' &&
                        status !== 'stopping') {
                        manageSpinner('stop');
                    }
                })
                .catch(function(error) {
                    console.error('Failed to refresh device data:', error);
                });

            // Also refresh backup info periodically to keep visualization up to date
            loadBackupInfo(); // Load backup info on every refresh (throttled to 10s anyway)
        }

        // ===========================
        // INITIALIZATION
        // ===========================

        // Load all initial data - OPTIMIZED
        loadNodeData();
        loadDeviceData();
        loadBackupInfo(true); // Load backup info (force on initial load)

        /**
         * Formats raw database information into a simplified list of dictionaries.
         */
        function formatDatabasesInfo(databasesData) {
            var databaseList = [];

            // Process MariaDB (MySQL) databases
            if (databasesData && databasesData.MariaDB) {
                for (var dbName in databasesData.MariaDB) {
                    if (databasesData.MariaDB.hasOwnProperty(dbName)) {
                        var dbInfo = databasesData.MariaDB[dbName];
                        databaseList.push({
                            name: dbName,
                            type: "MySQL",
                            active: true,
                            size: dbInfo.db_size_bytes || 0,
                            status: dbInfo.db_status || "unknown"
                        });
                    }
                }
            }

            // Process SQLite databases
            if (databasesData && databasesData.SQLite) {
                for (var dbName in databasesData.SQLite) {
                    if (databasesData.SQLite.hasOwnProperty(dbName)) {
                        var dbInfo = databasesData.SQLite[dbName];
                        databaseList.push({
                            name: dbName,
                            type: "SQLite",
                            active: true,
                            size: dbInfo.filesize || 0,
                            status: dbInfo.db_status || "unknown",
                            path: dbInfo.path || ""
                        });
                    }
                }
            }

            return {
                "database_list": databaseList
            };
        }

        /**
         * Update node.database_list for frontend dropdown from device data
         */
        function updateNodeDatabaseList() {
            // Populate node.database_list from device.databases for dropdown
            console.log('DEBUG: $scope.device.databases before formatting:', $scope.device.databases);
            if ($scope.device && $scope.device.databases) {
                $scope.node.database_list = formatDatabasesInfo($scope.device.databases).database_list;
                console.log('Updated node.database_list with', $scope.node.database_list.length, 'databases');
            } else {
                $scope.node.database_list = [];
                console.log('No databases found on device, setting empty array');
            }
        }

        /**
         * Check database availability for append functionality and provide user feedback
         */
        function checkDatabaseAvailability() {
            // Initialize database status tracking
            $scope.database_status = {
                loading: false,
                available: false,
                error: null,
                last_check: null
            };

            // Check if device has database_list in its data
            if ($scope.device && $scope.device.database_list) {
                $scope.database_status.available = $scope.device.database_list.length > 0;
                $scope.database_status.last_check = new Date();

                if (!$scope.database_status.available) {
                    $scope.database_status.error = "No previous experiments found for database appending";
                }
            } else {
                // Database list not yet loaded, mark as loading
                $scope.database_status.loading = true;
                $scope.database_status.error = "Database information is still loading...";
            }
        }

        /**
         * Refresh database availability status
         */
        $scope.refreshDatabaseStatus = function() {
            $scope.database_status.loading = true;
            $scope.database_status.error = null;

            // Reload device data to get fresh database list
            $http.get('/device/' + device_id + '/data')
                .then(function(response) {
                    $scope.device = response.data;
                    // Update backup summary cache when device data changes
                    updateBackupSummary();
                    updateNodeDatabaseList();
                    checkDatabaseAvailability();
                })
                .catch(function(error) {
                    $scope.database_status.loading = false;
                    $scope.database_status.error = "Failed to refresh database information: " + error.data;
                    console.error('Failed to refresh database status:', error);
                });
        };

        /**
         * Get user-friendly message for database availability status
         */
        $scope.getDatabaseStatusMessage = function() {
            if ($scope.database_status.loading) {
                return "Loading database information...";
            } else if ($scope.database_status.available) {
                return "Databases available for appending";
            } else if ($scope.database_status.error) {
                return $scope.database_status.error;
            } else {
                return "Database status unknown";
            }
        };

        // Start periodic refresh (every 10 seconds - reduced from 6 seconds)
        // Only refresh when page is visible to reduce unnecessary load
        refresh_data = $interval(refresh, 10000);

        // Cleanup interval when controller is destroyed
        $scope.$on("$destroy", function() {
            if (refresh_data) {
                $interval.cancel(refresh_data);
            }
        });

        // ===========================
        // VIDEO BACKUP FUNCTIONS
        // ===========================

        /**
         * Load enhanced video information from rsync status
         */
        function loadEnhancedVideoInfo() {
            $http.get('http://localhost:8093/status', { timeout: 3000 })
                .then(function(response) {
                    var rsyncData = response.data;
                    var deviceData = rsyncData.devices && rsyncData.devices[device_id];
                    
                    if (deviceData && deviceData.transfer_details && deviceData.transfer_details.videos) {
                        var videoFiles = deviceData.transfer_details.videos.files || {};
                        var videoFileArray = [];
                        
                        for (var filename in videoFiles) {
                            if (videoFiles.hasOwnProperty(filename)) {
                                var fileInfo = videoFiles[filename];
                                videoFileArray.push({
                                    name: filename,
                                    size_bytes: fileInfo.size_bytes || 0,
                                    size_human: fileInfo.size_human || $scope.formatFileSize(fileInfo.size_bytes || 0),
                                    status: fileInfo.status || 'unknown',
                                    path: fileInfo.path || '',
                                    is_h264: filename.endsWith('.h264')
                                });
                            }
                        }
                        
                        $scope.device.backup_status_detailed.individual_files.videos = {
                            files: videoFileArray
                        };
                        
                        console.log('DEBUG: Loaded video transfer details:', videoFileArray.length, 'files');
                    }
                })
                .catch(function(error) {
                    console.log('Enhanced video info not available:', error);
                });
        }

        /**
         * Filter function to show only h264 files
         */
        $scope.filterH264Files = function(videoFile) {
            return videoFile.is_h264 || videoFile.name.endsWith('.h264');
        };

        /**
         * Get video backup tooltip
         */
        $scope.getVideoBackupTooltip = function() {
            if ($scope.device.backup_status_detailed && 
                $scope.device.backup_status_detailed.individual_files && 
                $scope.device.backup_status_detailed.individual_files.videos) {
                var videos = $scope.device.backup_status_detailed.individual_files.videos.files;
                var h264Files = videos.filter($scope.filterH264Files);
                return h264Files.length + ' h264 video files';
            }
            return 'Video backup status';
        };

        /**
         * Get video segment style for proportional width
         */
        $scope.getVideoSegmentStyle = function(currentFile, allVideoFiles) {
            var h264Files = allVideoFiles.filter($scope.filterH264Files);
            var segmentWidth = h264Files.length > 0 ? (100 / h264Files.length) : 100;
            
            return {
                'width': segmentWidth + '%',
                'min-width': '2px'
            };
        };

        // Add click handler for radio button labels after DOM is ready
        setTimeout(function() {
            // Make strong labels clickable to trigger radio buttons
            $(document).on('click', '.modal .option-list li strong', function(e) {
                e.preventDefault();
                var $radioButton = $(this).siblings('input[type="radio"]');
                if ($radioButton.length) {
                    $radioButton.click();
                }
            });

            // Apply default template when tracking modal is shown
            $('#startModal').on('show.bs.modal', function() {
                setTimeout(function() {
                    $scope.applyDefaultTemplate();
                }, 200);
            });
        }, 100);

        // ===========================
        // STIMULATOR STATUS FUNCTIONS
        // ===========================

        /**
         * Get a human-readable stimulator name from the class name
         */
        $scope.getReadableStimulatorName = function(className) {
            if (!className) return 'None';
            
            // Extract class name from full path format
            var match = className.match(/class '([^']+)'/);
            if (match) {
                className = match[1];
            }
            
            // Extract just the class name without module path
            var parts = className.split('.');
            var shortName = parts[parts.length - 1];
            
            // Convert common stimulator names to readable format
            var nameMapping = {
                'DefaultStimulator': 'Default (No Stimulation)',
                'MultiStimulator': 'Multi-Stimulator Sequence',
                'mAGO': 'mAGO Sleep Depriver',
                'AGO': 'AGO Sleep Depriver',
                'SleepDepStimulator': 'Sleep Deprivation',
                'OptomotorSleepDepriver': 'Optomotor Sleep Depriver',
                'MiddleCrossingStimulator': 'Middle Crossing Stimulator',
                'ExperimentalSleepDepStimulator': 'Experimental Sleep Depriver',
                'DynamicOdourSleepDepriver': 'Dynamic Odour Sleep Depriver',
                'OptoMidlineCrossStimulator': 'Optomotor Midline Cross',
                'OptomotorSleepDepriverSystematic': 'Systematic Optomotor Sleep Depriver',
                'MiddleCrossingOdourStimulator': 'Middle Crossing Odour Stimulator',
                'MiddleCrossingOdourStimulatorFlushed': 'Flushed Odour Stimulator'
            };
            
            return nameMapping[shortName] || shortName;
        };

        /**
         * Format date range string for display
         */
        $scope.formatDateRange = function(dateRange) {
            if (!dateRange || dateRange.trim() === '') {
                return 'Always Active';
            }
            
            try {
                // Parse the date range format "YYYY-MM-DD HH:mm:ss > YYYY-MM-DD HH:mm:ss"
                var parts = dateRange.split('>');
                if (parts.length === 2) {
                    var startStr = parts[0].trim();
                    var endStr = parts[1].trim();
                    
                    if (startStr && endStr) {
                        // Format dates to be more readable
                        var startDate = new Date(startStr.replace(/ /, 'T'));
                        var endDate = new Date(endStr.replace(/ /, 'T'));
                        
                        var formatDate = function(date) {
                            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                        };
                        
                        return formatDate(startDate) + ' → ' + formatDate(endDate);
                    }
                }
                
                return dateRange;
            } catch (e) {
                return dateRange;
            }
        };

        /**
         * Check if stimulator is currently scheduled to be active
         */
        $scope.isStimulatorScheduled = function() {
            if (!$scope.device || !$scope.device.experimental_info || 
                !$scope.device.experimental_info.current || 
                !$scope.device.experimental_info.current.interactor) {
                return false;
            }
            
            var dateRange = $scope.device.experimental_info.current.interactor.arguments.date_range;
            if (!dateRange || dateRange.trim() === '') {
                return true; // Always active if no date range specified
            }
            
            try {
                var parts = dateRange.split('>');
                if (parts.length === 2) {
                    var startStr = parts[0].trim();
                    var endStr = parts[1].trim();
                    
                    if (startStr && endStr) {
                        var startDate = new Date(startStr.replace(/ /, 'T'));
                        var endDate = new Date(endStr.replace(/ /, 'T'));
                        var now = new Date();
                        
                        return now >= startDate && now <= endDate;
                    }
                }
            } catch (e) {
                console.error('Error parsing date range:', e);
            }
            
            return false;
        };

        /**
         * Get device time as a formatted string
         */
        $scope.getDeviceTimeString = function() {
            if ($scope.device_datetime) {
                return $scope.device_datetime;
            }
            return new Date().toLocaleString();
        };

        /**
         * Format configuration values for display
         */
        $scope.formatConfigValue = function(value) {
            if (value === null || value === undefined) {
                return 'null';
            }
            
            if (typeof value === 'object') {
                try {
                    return JSON.stringify(value, null, 2);
                } catch (e) {
                    return '[Object]';
                }
            }
            
            if (typeof value === 'string' && value.length > 100) {
                return value.substring(0, 100) + '...';
            }
            
            return String(value);
        };

    });

})();