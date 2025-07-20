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
            $scope.stimulatorSequence = []; // Array for stimulator sequence

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

                            // CRITICAL: Display timestamp immediately on load
                            updateTimestampDisplay(data.data);
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

                        // Initialize selected options with default values
                        initializeSelectedOptions('tracking', userOptions.tracking || {});
                        initializeSelectedOptions('recording', userOptions.recording || {});
                        initializeSelectedOptions('update_machine', userOptions.update_machine || {});
                        
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
                            let startDate = null;
                            let endDate = null;
                            let formatted = arg.default || '';

                            if (formatted) {
                                const dates = formatted.split(' > ');
                                if (dates.length === 2) {
                                    const m1 = moment(dates[0], 'YYYY-MM-DD HH:mm:ss');
                                    const m2 = moment(dates[1], 'YYYY-MM-DD HH:mm:ss');
                                    if (m1.isValid() && m2.isValid()) {
                                        startDate = m1;
                                        endDate = m2;
                                    }
                                }
                            }

                            // To prevent the error, if startDate is still null, initialize it.
                            if (startDate === null) {
                                startDate = moment();
                                endDate = moment();
                                // Also clear formatted string if we are using a default moment object
                                // because there was no valid default.
                                formatted = '';
                            }

                            $scope.selected_options[optionType][key].arguments[arg.name] = {
                                startDate: startDate,
                                endDate: endDate,
                                formatted: formatted
                            };
                        } else {
                            // Standard default value assignment
                            $scope.selected_options[optionType][key].arguments[arg.name] = arg.default;
                        }
                    }
                }
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
                                    if (typeof moment !== 'undefined') {
                                        // Ensure moment.js locale is configured
                                        ensureMomentLocale();

                                        // Validate the default value before using it
                                        var defaultValue = argument.default;
                                        var momentObj = moment(defaultValue);

                                        if (momentObj.isValid()) {
                                            $scope.selected_options[optionType][name].arguments[argument.name] = [
                                                momentObj.format('LLLL'),
                                                defaultValue
                                            ];
                                        } else {
                                            // Use current time if default is invalid
                                            var fallbackMoment = moment();
                                            $scope.selected_options[optionType][name].arguments[argument.name] = [
                                                fallbackMoment.format('LLLL'),
                                                fallbackMoment.unix()
                                            ];
                                            console.warn('Invalid datetime default value for ' + argument.name + ':', defaultValue, 'Using current time instead.');
                                        }
                                    } else {
                                        // Fallback if moment isn't available
                                        $scope.selected_options[optionType][name].arguments[argument.name] = argument.default;
                                    }
                                } else {
                                    // Set default for other argument types
                                    $scope.selected_options[optionType][name].arguments[argument.name] = argument.default;
                                }
                            }
                            break;
                        }
                    }

                    // Special handling for MultiStimulator
                    if (optionType === 'tracking' && name === 'interactor' && targetOptionName === 'MultiStimulator') {
                        // Initialize MultiStimulator configuration
                        if (!$scope.selected_options[optionType][name].arguments.stimulator_sequence) {
                            $scope.selected_options[optionType][name].arguments.stimulator_sequence = [];
                            // Add one default stimulator to start
                            setTimeout(function() {
                                $scope.addNewStimulator();
                                try {
                                    $scope.$apply();
                                } catch (e) {
                                    // Digest already in progress
                                }
                            }, 100);
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
            // MULTI-STIMULATOR FUNCTIONS
            // ===========================

            /**
             * Get the selected stimulator option object
             * @param {string} name - The option category name (should be 'interactor')
             * @returns {Object} The selected stimulator option object
             */
            $scope.getSelectedStimulatorOption = function(name) {
                if (!$scope.user_options.tracking || !$scope.user_options.tracking[name] || !$scope.selected_options.tracking || !$scope.selected_options.tracking[name]) {
                    return {};
                }
                
                var selectedName = $scope.selected_options.tracking[name]['name'];
                if (!selectedName) return {};
                
                var options = $scope.user_options.tracking[name];
                for (var i = 0; i < options.length; i++) {
                    if (options[i].name === selectedName) {
                        return options[i];
                    }
                }
                return {};
            };

            /**
             * Get stimulator arguments for a specific stimulator class
             * @param {string} className - The stimulator class name
             * @returns {Array} Array of argument definitions
             */
            $scope.getStimulatorArguments = function(className) {
                if (!$scope.user_options.tracking || !$scope.user_options.tracking.interactor) {
                    return [];
                }
                
                var options = $scope.user_options.tracking.interactor;
                for (var i = 0; i < options.length; i++) {
                    if (options[i].name === className) {
                        return options[i].arguments || [];
                    }
                }
                return [];
            };

            /**
             * Add a new stimulator to the sequence
             */
            $scope.addNewStimulator = function() {
                if (!$scope.selected_options.tracking) {
                    $scope.selected_options.tracking = {};
                }
                if (!$scope.selected_options.tracking.interactor) {
                    $scope.selected_options.tracking.interactor = {
                        name: 'MultiStimulator',
                        arguments: {}
                    };
                }
                if (!$scope.selected_options.tracking.interactor.arguments.stimulator_sequence) {
                    $scope.selected_options.tracking.interactor.arguments.stimulator_sequence = [];
                }

                var newStimulator = {
                    class_name: '',
                    arguments: {},
                    date_range: ''
                };

                $scope.selected_options.tracking.interactor.arguments.stimulator_sequence.push(newStimulator);
            };

            /**
             * Remove a stimulator from the sequence
             * @param {number} index - Index of stimulator to remove
             */
            $scope.removeStimulator = function(index) {
                if ($scope.selected_options.tracking && 
                    $scope.selected_options.tracking.interactor && 
                    $scope.selected_options.tracking.interactor.arguments &&
                    $scope.selected_options.tracking.interactor.arguments.stimulator_sequence) {
                    
                    $scope.selected_options.tracking.interactor.arguments.stimulator_sequence.splice(index, 1);
                }
            };

            /**
             * Update stimulator arguments when stimulator type changes
             * @param {number} index - Index of stimulator in sequence
             */
            $scope.updateStimulatorArguments = function(index) {
                var sequence = $scope.selected_options.tracking.interactor.arguments.stimulator_sequence;
                if (!sequence || !sequence[index]) return;

                var stimulator = sequence[index];
                var className = stimulator.class_name;
                
                if (!className) {
                    stimulator.arguments = {};
                    return;
                }

                // Get the argument definitions for this stimulator class
                var argDefs = $scope.getStimulatorArguments(className);
                var newArguments = {};

                // Initialize arguments with default values
                for (var i = 0; i < argDefs.length; i++) {
                    var argDef = argDefs[i];
                    if (argDef.type !== 'date_range') { // Skip date_range as it's handled separately
                        newArguments[argDef.name] = argDef.default || '';
                    }
                }

                stimulator.arguments = newArguments;
            };

            /**
             * Initialize MultiStimulator configuration when selected
             */
            $scope.initializeMultiStimulator = function() {
                if (!$scope.selected_options.tracking.interactor.arguments.stimulator_sequence) {
                    $scope.selected_options.tracking.interactor.arguments.stimulator_sequence = [];
                    // Add one default stimulator to start
                    $scope.addNewStimulator();
                }
            };

            // ===========================
            // STIMULATOR SEQUENCE FUNCTIONS
            // ===========================

            /**
             * Add a new stimulator to the sequence
             */
            $scope.addStimulatorToSequence = function() {
                var newStimulator = {
                    name: '',
                    arguments: {}
                };
                
                $scope.stimulatorSequence.push(newStimulator);
                
                // Set a default interactor selection to avoid validation issues
                if (!$scope.selected_options.tracking) {
                    $scope.selected_options.tracking = {};
                }
                if (!$scope.selected_options.tracking.interactor) {
                    $scope.selected_options.tracking.interactor = {
                        name: 'DefaultStimulator',
                        arguments: {}
                    };
                }
            };

            /**
             * Remove a stimulator from the sequence
             * @param {number} index - Index of stimulator to remove
             */
            $scope.removeStimulatorFromSequence = function(index) {
                $scope.stimulatorSequence.splice(index, 1);
            };

            /**
             * Update stimulator options when selection changes
             * @param {number} index - Index of stimulator in sequence
             */
            $scope.updateStimulatorInSequence = function(index) {
                if (!$scope.stimulatorSequence[index]) return;

                var stimulator = $scope.stimulatorSequence[index];
                var stimulatorName = stimulator.name;
                
                if (!stimulatorName) {
                    stimulator.arguments = {};
                    return;
                }

                // Get the argument definitions for this stimulator
                var argDefs = $scope.getStimulatorArguments(stimulatorName);
                var newArguments = {};

                // Initialize arguments with default values
                for (var i = 0; i < argDefs.length; i++) {
                    var argDef = argDefs[i];
                    if (argDef.type === 'date_range' && (argDef.default === '' || !argDef.default)) {
                        // Don't set date_range arguments with empty defaults - leave undefined to avoid daterangepicker errors
                        continue;
                    }
                    newArguments[argDef.name] = argDef.default || '';
                }

                stimulator.arguments = newArguments;
            };

            /**
             * Get interactor option by name
             * @param {string} name - Interactor name
             * @returns {Object} Interactor option object
             */
            $scope.getInteractorOptionByName = function(name) {
                if (!$scope.user_options.tracking || !$scope.user_options.tracking.interactor) {
                    return {};
                }
                
                var options = $scope.user_options.tracking.interactor;
                for (var i = 0; i < options.length; i++) {
                    if (options[i].name === name) {
                        return options[i];
                    }
                }
                return {};
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
                if (!url) return '';
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

            // Check if ROI template is properly selected for tracking
            $scope.isRoiTemplateSelected = function() {
                if (!$scope.selected_options || !$scope.selected_options.tracking || !$scope.selected_options.tracking.roi_builder) {
                    return false;
                }

                var roiBuilderOption = $scope.selected_options.tracking.roi_builder;

                // Check if roi_builder is FileBasedROIBuilder (which requires template selection)
                if (roiBuilderOption.name && roiBuilderOption.name.includes('FileBasedROIBuilder')) {
                    var args = roiBuilderOption.arguments || {};
                    var templateName = args.template_name;

                    // Valid if we have a non-empty template_name
                    if (templateName && templateName !== '' && templateName !== 'None' && templateName !== 'null' && templateName !== undefined) {
                        return true;
                    }

                    return false;
                }

                // For other ROI builders, no template validation needed
                return true;
            };

            // Check if user is properly selected for tracking
            $scope.isUserSelected = function() {
                if (!$scope.selected_options || !$scope.selected_options.tracking || !$scope.selected_options.tracking.experimental_info) {
                    return false;
                }
                
                var experimentalInfo = $scope.selected_options.tracking.experimental_info;
                var args = experimentalInfo.arguments || {};
                var userName = args.name;
                
                // Valid if we have a non-empty user name
                return userName && userName !== '' && userName !== 'None' && userName !== 'null' && userName !== undefined;
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

                // Add sensor IP based on selected incubator name
                if (option.experimental_info && option.experimental_info.arguments && option.experimental_info.arguments.location) {
                    var selectedIncubatorName = option.experimental_info.arguments.location; // This field contains the incubator name
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
                    
                    // Replace the interactor section with MultiStimulator configuration
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
                // This would be populated from the dropdown options
                // For now, we can check if there are any custom templates
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
            }

            // ===========================
            // INITIALIZATION
            // ===========================

            // Load all initial data - OPTIMIZED
            loadNodeData();
            loadDeviceData();
            // Note: loadUserOptions() is now called within loadDeviceData() via batch endpoint

            // Start periodic refresh (every 10 seconds - reduced from 6 seconds)
            // Only refresh when page is visible to reduce unnecessary load
            refresh_data = $interval(refresh, 10000);

            // Cleanup interval when controller is destroyed
            $scope.$on("$destroy", function() {
                if (refresh_data) {
                    $interval.cancel(refresh_data);
                }
            });

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

        });

})();