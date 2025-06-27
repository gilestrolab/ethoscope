(function() {
    'use strict';

    var app = angular.module('flyApp');

    // Custom tooltip directive for ethoscope interface
    app.directive('tooltip', function($compile) {
        return {
            restrict: 'A',
            link: function(scope, element, attrs) {
                // Create tooltip element
                const tooltipElement = angular.element('<div class="custom-tooltip">{{tooltipText}}</div>');
                tooltipElement.addClass('tooltip-hidden');
                element.after(tooltipElement);

                // Set tooltip text from the `tooltip` attribute
                let tooltipText = attrs.tooltip || '';
                scope.tooltipText = tooltipText;

                // Compile the tooltip element to enable Angular binding
                $compile(tooltipElement)(scope);

                // Tooltip visibility logic
                const showTooltip = () => {
                    tooltipElement.removeClass('tooltip-hidden');
                    tooltipElement.addClass('tooltip-visible');
                };

                const hideTooltip = () => {
                    tooltipElement.removeClass('tooltip-visible');
                    tooltipElement.addClass('tooltip-hidden');
                };

                // Attach mouseover and mouseleave events for tooltip visibility
                element.on('mouseenter', () => {
                    scope.$apply(showTooltip);
                });

                element.on('mouseleave', () => {
                    scope.$apply(hideTooltip);
                });

                // Clean up event listeners on destroy
                scope.$on('$destroy', () => {
                    element.off('mouseenter');
                    element.off('mouseleave');
                });
            }
        };
    });

    // URL sanitization configuration
    app.config(['$compileProvider', function($compileProvider) {
        $compileProvider.aHrefSanitizationWhitelist(/^\s*(https?|ftp|mailto|file|sms|tel|ssh):/);
    }]);

    /**
     * Ethoscope Controller - Controls individual ethoscope device interface
     * Manages tracking, recording, machine settings, and real-time updates
     */
    app.controller('ethoscopeController', function($scope, $http, $routeParams, $interval) {

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

        // UI state variables
        $scope.showLog = false;
        $scope.can_stream = false;
        $scope.isActive = false;

        // Date range picker configuration for stimulator scheduling
        $scope.dateRangeOptions = {
            timePicker: true,
            timePicker24Hour: true,
            timePickerIncrement: 30,
            drops: 'up',
            autoApply: true,
            autoUpdateInput: true,
            minDate: moment(), // Disable past dates
            locale: {
                format: 'YYYY-MM-DD HH:mm:ss',
                separator: ' > ',
                applyLabel: 'Apply',
                cancelLabel: 'Cancel',
                fromLabel: 'From',
                toLabel: 'To'
            }
        };

        // ===========================
        // DATA LOADING FUNCTIONS
        // ===========================

        /**
         * Load node-level data (users, incubators, sensors)
         */
        function loadNodeData() {
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
         * Load device-specific data
         */
        function loadDeviceData() {
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
                })
                .catch(function(error) {
                    console.error('Failed to load device data:', error);
                });

            // Load available video files
            $http.get('/device/' + device_id + '/videofiles')
                .then(function(response) {
                    $scope.videofiles = response.data.filelist;
                })
                .catch(function(error) {
                    console.error('Failed to load video files:', error);
                });
        }

        /**
         * Initialize form options with default values
         * @param {string} optionType - Type of options (tracking, recording, update_machine)
         * @param {Object} data - Raw options data from server
         */
        function initializeSelectedOptions(optionType, data) {
            $scope.selected_options[optionType] = {};

            // Get keys in server-provided order
            var keys = Object.keys(data);

            for (var i = 0; i < keys.length; i++) {
                var key = keys[i];
                if (!data[key] || !data[key][0]) continue;

                $scope.selected_options[optionType][key] = {
                    name: data[key][0].name,
                    arguments: {}
                };

                // Initialize arguments with default values
                var args = data[key][0].arguments || [];
                for (var j = 0; j < args.length; j++) {
                    var arg = args[j];

                    if (arg.type === 'date_range') {
                        // Special handling for date range fields
                        $scope.selected_options[optionType][key].arguments[arg.name] = {
                            startDate: null,
                            endDate: null,
                            formatted: arg.default || ""
                        };
                    } else {
                        // Standard default value assignment
                        $scope.selected_options[optionType][key].arguments[arg.name] = arg.default;
                    }
                }
            }
        }

        /**
         * Load user options (tracking, recording, machine update options)
         */
        function loadUserOptions() {
            $http.get('/device/' + device_id + '/user_options')
                .then(function(response) {
                    var data = response.data;

                    // Check streaming capability
                    $scope.can_stream = (typeof data.streaming !== 'undefined');

                    // Store raw options data (preserves server order)
                    $scope.user_options = {
                        tracking: data.tracking || {},
                        recording: data.recording || {},
                        update_machine: data.update_machine || {}
                    };

                    // Initialize selected options with default values
                    initializeSelectedOptions('tracking', data.tracking || {});
                    initializeSelectedOptions('recording', data.recording || {});
                    initializeSelectedOptions('update_machine', data.update_machine || {});
                })
                .catch(function(error) {
                    console.error('Failed to load user options:', error);
                });
        }

        // ===========================
        // FORM MANAGEMENT FUNCTIONS
        // ===========================

        /**
         * Update user option arguments when selection changes
         * @param {string} optionType - Type of option (tracking, recording, update_machine)
         * @param {string} name - Option category name
         * @param {string} selectedOptionName - The specific option name that was selected (optional)
         */
        $scope.ethoscope.update_user_options = function(optionType, name, selectedOptionName) {
            const data = $scope.user_options[optionType];
            if (!data || !data[name]) return;

            // Use $timeout to ensure proper timing and digest cycle
            setTimeout(function() {
                // Ensure the selected_options structure exists
                if (!$scope.selected_options[optionType]) {
                    $scope.selected_options[optionType] = {};
                }
                if (!$scope.selected_options[optionType][name]) {
                    $scope.selected_options[optionType][name] = {
                        name: '',
                        arguments: {}
                    };
                }

                // If selectedOptionName is provided, use it; otherwise use current selection
                const targetOptionName = selectedOptionName || $scope.selected_options[optionType][name].name;

                // Update the selected option name (to sync with ng-model)
                $scope.selected_options[optionType][name].name = targetOptionName;

                // Find the selected option
                for (let i = 0; i < data[name].length; i++) {
                    if (data[name][i].name === targetOptionName) {
                        // Reset and populate arguments for the selected option
                        $scope.selected_options[optionType][name].arguments = {};

                        const args = data[name][i].arguments || [];
                        for (let j = 0; j < args.length; j++) {
                            const argument = args[j];

                            if (argument.type === 'datetime') {
                                // Handle datetime arguments with moment.js formatting
                                $scope.selected_options[optionType][name].arguments[argument.name] = [
                                    moment(argument.default).format('LLLL'),
                                    argument.default
                                ];
                            } else {
                                // Set default for other argument types
                                $scope.selected_options[optionType][name].arguments[argument.name] = argument.default;
                            }
                        }
                        break;
                    }
                }

                // Force Angular to update the view
                try {
                    $scope.$apply();
                } catch (e) {
                    // Digest already in progress, no need to apply
                }
            }, 0);
        };

        // Convenience methods for different option types
        $scope.ethoscope.update_user_options.tracking = function(name, selectedOptionName) {
            $scope.ethoscope.update_user_options('tracking', name, selectedOptionName);
        };

        $scope.ethoscope.update_user_options.recording = function(name, selectedOptionName) {
            $scope.ethoscope.update_user_options('recording', name, selectedOptionName);
        };

        $scope.ethoscope.update_user_options.update_machine = function(name, selectedOptionName) {
            $scope.ethoscope.update_user_options('update_machine', name, selectedOptionName);
        };

        // ===========================
        // UTILITY FUNCTIONS
        // ===========================

        /**
         * Manage loading spinner display
         * @param {string} action - 'start' or 'stop'
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
         * @param {string} location - Sensor location name
         * @returns {string} Sensor IP address
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
         * @param {Object} device - Device object
         * @returns {boolean} True if device has valid interactor
         */
        $scope.hasValidInteractor = function(device) {
            return (
                device.status === 'running' &&
                device.hasOwnProperty('interactor') &&
                device.interactor.name !== "<class 'ethoscope.stimulators.stimulators.DefaultStimulator'>"
            );
        };

        /**
         * Calculate elapsed time from timestamp
         * @param {number} t - Unix timestamp
         * @returns {string} Formatted elapsed time string
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
         * @param {string} url - Full URL path
         * @returns {string} Shortened readable URL
         */
        $scope.ethoscope.readable_url = function(url) {
            // Initialize tooltips (POTENTIAL SIDE EFFECT - consider moving)
            $('[data-toggle="tooltip"]').tooltip();

            var parts = url.split("/");
            return ".../" + parts[parts.length - 1];
        };

        /**
         * Convert Unix timestamp to readable date string
         * @param {number} unix_timestamp - Unix timestamp
         * @returns {string} Formatted date string
         */
        $scope.ethoscope.start_date_time = function(unix_timestamp) {
            return new Date(unix_timestamp * 1000).toUTCString();
        };

        /**
         * Show alert message
         * @param {string} message - Alert message
         */
        $scope.ethoscope.alert = function(message) {
            alert(message);
        };

        // ===========================
        // TRACKING & RECORDING FUNCTIONS
        // ===========================

        /**
         * Start tracking with selected options
         * @param {Object} option - Selected tracking options
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

            // Add sensor IP if location is specified
            if (option.experimental_info && option.experimental_info.arguments && option.experimental_info.arguments.location) {
                option.experimental_info.arguments.sensor = $scope.get_ip_of_sensor(option.experimental_info.arguments.location);
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
        };

        /**
         * Start video recording with selected options
         * @param {Object} option - Selected recording options
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
         * @param {Object} option - Machine update options
         */
        $scope.ethoscope.update_machine = function(option) {
            $("#changeInfo").modal('hide');
            $http.post('/device/' + device_id + '/machineinfo', option)
                .then(function(response) {
                    $scope.machine_info = response.data;
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
         * EXPERIMENTAL FEATURE - Only available on experimental builds
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
        // OBSOLETE/DEPRECATED FUNCTIONS
        // ===========================

        /**
         * OBSOLETE: Download function - functionality unclear, may be unused
         * @deprecated This function appears to be incomplete and potentially unused
         */
        $scope.ethoscope.download = function() {
            // WARNING: This function may not work as expected
            // The $scope.result_files variable is not defined anywhere
            $http.get($scope.device.ip + ':9000/static' + $scope.result_files);
        };

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
                    $scope.device = response.data;
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
                    $scope.device = data;

                    // Initialize time display
                    $scope.node_datetime = "Node Time";
                    $scope.device_datetime = "Device Time";

                    if (data.current_timestamp) {
                        $scope.device_timestamp = new Date(data.current_timestamp * 1000);
                        $scope.device_datetime = $scope.device_timestamp.toUTCString();

                        // Check time synchronization with node
                        $http.get('/node/timestamp')
                            .then(function(node_response) {
                                var node_t = node_response.data.timestamp;
                                var node_time = new Date(node_t * 1000);
                                $scope.node_datetime = node_time.toUTCString();
                                $scope.delta_t_min = Math.abs((node_t - data.current_timestamp) / 60);

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

                    // Update device URLs with cache busting
                    var timestamp = Math.floor(new Date().getTime() / 1000.0);
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
        }

        // ===========================
        // INITIALIZATION
        // ===========================

        // Load all initial data
        loadNodeData();
        loadDeviceData();
        loadUserOptions();

        // Start periodic refresh (every 6 seconds)
        refresh_data = $interval(refresh, 6000);

        // Cleanup interval when controller is destroyed
        $scope.$on("$destroy", function() {
            if (refresh_data) {
                $interval.cancel(refresh_data);
            }
        });

    });

})();