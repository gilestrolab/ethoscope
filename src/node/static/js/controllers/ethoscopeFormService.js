(function() {
    'use strict';

    var app = angular.module('flyApp');

    app.factory('ethoscopeFormService', function($http, $timeout) {
        return {

            /**
             * Initialize form options with default values
             * @param {string} optionType - Type of options (tracking, recording, update_machine)
             * @param {Object} data - Raw options data from server
             * @param {Object} $scope - Controller scope
             */
            initializeSelectedOptions: function(optionType, data, $scope) {
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
                            var startDate = null;
                            var endDate = null;
                            var formatted = arg.default || '';

                            if (formatted) {
                                var dates = formatted.split(' > ');
                                if (dates.length === 2) {
                                    var m1 = moment(dates[0], 'YYYY-MM-DD HH:mm:ss');
                                    var m2 = moment(dates[1], 'YYYY-MM-DD HH:mm:ss');
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
            },

            /**
             * Update user option arguments when selection changes
             * @param {string} optionType - Type of option (tracking, recording, update_machine)
             * @param {string} name - Option category name
             * @param {string} selectedOptionName - The specific option name that was selected (optional)
             * @param {Object} $scope - Controller scope
             */
            updateUserOptions: function(optionType, name, selectedOptionName, $scope) {
                var data = $scope.user_options[optionType];
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
                    var targetOptionName = selectedOptionName || $scope.selected_options[optionType][name].name;

                    // Update the selected option name (to sync with ng-model)
                    $scope.selected_options[optionType][name].name = targetOptionName;

                    // Find the selected option
                    for (var i = 0; i < data[name].length; i++) {
                        if (data[name][i].name === targetOptionName) {
                            // Reset and populate arguments for the selected option
                            $scope.selected_options[optionType][name].arguments = {};

                            var args = data[name][i].arguments || [];
                            for (var j = 0; j < args.length; j++) {
                                var argument = args[j];

                                if (argument.type === 'datetime') {
                                    // Handle datetime arguments with moment.js formatting
                                    if (typeof moment !== 'undefined') {
                                        // Ensure moment.js locale is configured
                                        this.ensureMomentLocale();

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
            },

            /**
             * Get the selected stimulator option object
             * @param {string} name - The option category name (should be 'interactor')
             * @param {Object} $scope - Controller scope
             * @returns {Object} The selected stimulator option object
             */
            getSelectedStimulatorOption: function(name, $scope) {
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
            },

            /**
             * Get stimulator arguments for a specific stimulator class
             * @param {string} className - The stimulator class name
             * @param {Object} $scope - Controller scope
             * @returns {Array} Array of argument definitions
             */
            getStimulatorArguments: function(className, $scope) {
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
            },

            /**
             * Add a new stimulator to the sequence
             * @param {Object} $scope - Controller scope
             */
            addNewStimulator: function($scope) {
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
            },

            /**
             * Remove a stimulator from the sequence
             * @param {number} index - Index of stimulator to remove
             * @param {Object} $scope - Controller scope
             */
            removeStimulator: function(index, $scope) {
                if ($scope.selected_options.tracking &&
                    $scope.selected_options.tracking.interactor &&
                    $scope.selected_options.tracking.interactor.arguments &&
                    $scope.selected_options.tracking.interactor.arguments.stimulator_sequence) {

                    $scope.selected_options.tracking.interactor.arguments.stimulator_sequence.splice(index, 1);
                }
            },

            /**
             * Update stimulator arguments when stimulator type changes
             * @param {number} index - Index of stimulator in sequence
             * @param {Object} $scope - Controller scope
             */
            updateStimulatorArguments: function(index, $scope) {
                var sequence = $scope.selected_options.tracking.interactor.arguments.stimulator_sequence;
                if (!sequence || !sequence[index]) return;

                var stimulator = sequence[index];
                var className = stimulator.class_name;

                if (!className) {
                    stimulator.arguments = {};
                    return;
                }

                // Get the argument definitions for this stimulator class
                var argDefs = this.getStimulatorArguments(className, $scope);
                var newArguments = {};

                // Initialize arguments with default values
                for (var i = 0; i < argDefs.length; i++) {
                    var argDef = argDefs[i];
                    if (argDef.type !== 'date_range') { // Skip date_range as it's handled separately
                        newArguments[argDef.name] = argDef.default || '';
                    }
                }

                stimulator.arguments = newArguments;
            },

            /**
             * Add a new stimulator to the sequence (alternative implementation for sequence management)
             * @param {Object} $scope - Controller scope
             */
            addStimulatorToSequence: function($scope) {
                // Auto-select ComposedStimulator and initialize its arguments
                var stimulatorName = 'ComposedStimulator';
                var argDefs = this.getStimulatorArguments(stimulatorName, $scope);
                var newArguments = {};

                for (var i = 0; i < argDefs.length; i++) {
                    var argDef = argDefs[i];
                    if (argDef.type === 'date_range' && (argDef.default === '' || !argDef.default)) {
                        continue;
                    }
                    newArguments[argDef.name] = argDef.default || '';
                }

                var newStimulator = {
                    name: stimulatorName,
                    arguments: newArguments
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
            },

            /**
             * Remove a stimulator from the sequence (alternative implementation)
             * @param {number} index - Index of stimulator to remove
             * @param {Object} $scope - Controller scope
             */
            removeStimulatorFromSequence: function(index, $scope) {
                $scope.stimulatorSequence.splice(index, 1);
            },

            /**
             * Update stimulator options when selection changes
             * @param {number} index - Index of stimulator in sequence
             * @param {Object} $scope - Controller scope
             */
            updateStimulatorInSequence: function(index, $scope) {
                if (!$scope.stimulatorSequence[index]) return;

                var stimulator = $scope.stimulatorSequence[index];
                var stimulatorName = stimulator.name;

                if (!stimulatorName) {
                    stimulator.arguments = {};
                    return;
                }

                // Get the argument definitions for this stimulator
                var argDefs = this.getStimulatorArguments(stimulatorName, $scope);
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
            },

            /**
             * Get interactor option by name
             * @param {string} name - Interactor name
             * @param {Object} $scope - Controller scope
             * @returns {Object} Interactor option object
             */
            getInteractorOptionByName: function(name, $scope) {
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
            },

            /**
             * Centralized moment.js locale configuration
             */
            ensureMomentLocale: function() {
                if (typeof moment !== 'undefined' && moment.locale && !this.momentLocaleConfigured) {
                    moment.locale('en');
                    this.momentLocaleConfigured = true;
                    console.log('Moment.js locale configured to: en');
                }
                return this.momentLocaleConfigured;
            },

            /**
             * Filter action_type options based on detected module capabilities.
             * Maps each action value to the capability key it requires.
             * @param {Array} allOptions - The full options array from the argument definition
             * @param {Object} moduleInfo - Module info from /module endpoint (may be empty)
             * @returns {Array} Filtered options array
             */
            getAvailableActions: function(allOptions, moduleInfo) {
                if (!allOptions) return [];
                if (!moduleInfo || !moduleInfo.capabilities) return allOptions;

                var capabilityMap = {
                    'motor_pulse': 'motors',
                    'led_pulse': 'leds',
                    'led_pulse_train': 'leds',
                    'valve_pulse': 'valves'
                };

                return allOptions.filter(function(opt) {
                    var requiredCap = capabilityMap[opt.value];
                    if (!requiredCap) return true; // Unknown action type, show it
                    return moduleInfo.capabilities[requiredCap] > 0;
                });
            },

            /**
             * Check if an argument should be visible based on its depends_on conditions.
             * Used by ComposedStimulator to show/hide trigger- and action-specific arguments.
             * @param {Object} arg - The argument definition (may have a depends_on field)
             * @param {Object} currentArgValues - Current argument values for the stimulator
             * @returns {boolean} True if the argument should be shown
             */
            isArgumentVisible: function(arg, currentArgValues) {
                if (!arg) return false;
                // Hide arguments explicitly marked as hidden
                if (arg.hidden && arg.hidden !== "false" && arg.hidden !== false) return false;
                if (!arg.depends_on) return true;
                if (!currentArgValues) return false;

                for (var dep in arg.depends_on) {
                    if (arg.depends_on.hasOwnProperty(dep)) {
                        var allowedValues = arg.depends_on[dep];
                        var currentVal = currentArgValues[dep];
                        if (!currentVal || allowedValues.indexOf(currentVal) === -1) {
                            return false;
                        }
                    }
                }
                return true;
            },

            /**
             * Check if ROI template is properly selected for tracking
             * @param {Object} $scope - Controller scope
             * @returns {boolean} True if ROI template is properly selected
             */
            isRoiTemplateSelected: function($scope) {
                if (!$scope.selected_options || !$scope.selected_options.tracking || !$scope.selected_options.tracking.roi_builder) {
                    return false;
                }

                var roiBuilderOption = $scope.selected_options.tracking.roi_builder;

                // Check if roi_builder is FileBasedROIBuilder (which requires template selection)
                if (roiBuilderOption.name && roiBuilderOption.name.indexOf('FileBasedROIBuilder') !== -1) {
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
            },

            /**
             * Check if user is properly selected for tracking
             * @param {Object} $scope - Controller scope
             * @returns {boolean} True if user is properly selected
             */
            isUserSelected: function($scope) {
                if (!$scope.selected_options || !$scope.selected_options.tracking || !$scope.selected_options.tracking.experimental_info) {
                    return false;
                }

                var experimentalInfo = $scope.selected_options.tracking.experimental_info;
                var args = experimentalInfo.arguments || {};
                var userName = args.name;

                // Valid if we have a non-empty user name
                return userName && userName !== '' && userName !== 'None' && userName !== 'null' && userName !== undefined;
            },

            /**
             * Check if location/incubator is properly selected for tracking
             * @param {Object} $scope - Controller scope
             * @returns {boolean} True if location is properly selected
             */
            isLocationSelected: function($scope) {
                if (!$scope.selected_options || !$scope.selected_options.tracking || !$scope.selected_options.tracking.experimental_info) {
                    return false;
                }

                var experimentalInfo = $scope.selected_options.tracking.experimental_info;
                var args = experimentalInfo.arguments || {};
                var location = args.location;

                return location && location !== '' && location !== 'None' && location !== 'null' && location !== undefined;
            }
        };
    });

})();
