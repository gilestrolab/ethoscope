(function() {
    var app = angular.module('updater', ['ngRoute']);
    app.filter("toArray", function() {
        return function(obj) {
            var result = [];
            angular.forEach(obj, function(val, key) {
                result.push(val);
            });
            return result;
        };
    });

    // create the controller and inject Angular's $scope
    app.controller('mainController', function($scope, $window, $http, $interval, $timeout) {
        $scope.system = {};
        $scope.system.isUpdated = false;
        $scope.node = {};
        $scope.devices = {};
        $scope.devices_to_update_selected = [];
        $scope.selected_devices = [];
        $scope.modal = {
            title: 'Device Action',
            info: 'Please select an action',
            action_text: 'Execute',
            action: 'none',
        };

        $scope.branch_to_switch = null;
        $scope.system.modal_error = "";
        $scope.spinner = new Spinner(opts).spin();
        var loadingContainer = document.getElementById('loading_devices');
        loadingContainer.appendChild($scope.spinner.el);
        $scope.spinner_text = 'Fetching, please wait...';

        $scope.spinner_scan = new Spinner(opts).spin();
        var loadingContainer_scan = document.getElementById('scanning_devices');
        loadingContainer_scan.appendChild($scope.spinner_scan.el);


        $http.get('/bare/update').then(function(response) {
            var data = response.data;
            if ('error' in data) {
                $scope.system.error = data.error;
            } else {
                $scope.system.isUpdated = true;
                $scope.system.status = data;
            }
            $scope.spinner.stop();
            $scope.spinner = false;
            $scope.spinner_text = null;
        }).catch(function(error) {
            $scope.system.error = 'Failed to update bare repository: ' + (error.data && error.data.error ? error.data.error : error.statusText);
            $scope.spinner.stop();
            $scope.spinner = false;
            $scope.spinner_text = null;
        });
        $http.get('/devices').then(function(response) {
            var data = response.data;
            if (!check_error(data)) {
                $scope.devices = data;
            }

            //slower method is the one that has to stop the spinner
            $scope.spinner_scan.stop();
            $scope.spinner_scan = false;

        }).catch(function(error) {
            $scope.system.error = 'Failed to load devices: ' + (error.data && error.data.error ? error.data.error : error.statusText);
            $scope.spinner_scan.stop();
            $scope.spinner_scan = false;
        });
        $http.get('/device/check_update/node').then(function(response) {
            var data = response.data;
            if (!check_error(data)) {
                $scope.node.check_update = data;
            }
        }).catch(function(error) {
            $scope.system.error = 'Failed to check node updates: ' + (error.data && error.data.error ? error.data.error : error.statusText);
        });
        $http.get('/device/active_branch/node').then(function(response) {
            var data = response.data;
            if (!check_error(data)) {
                $scope.node.active_branch = data.active_branch;
            }
        }).catch(function(error) {
            $scope.system.error = 'Failed to get active branch: ' + (error.data && error.data.error ? error.data.error : error.statusText);
        });
        //aADD A call to node/info
        $http.get('/node_info').then(function(response) {
            var data = response.data;
            if (!check_error(data)) {
                $scope.node.ip = data.ip;
                $scope.node.status = data.status;
                $scope.node.id = data.id;
            }
        }).catch(function(error) {
            $scope.system.error = 'Failed to get node info: ' + (error.data && error.data.error ? error.data.error : error.statusText);
        });

        $scope.toggleAll = function() {
            // Valid states for updates (same as used in activate_modal)
            var validStates = ['stopped', 'NA', 'Software broken'];

            // Use $evalAsync to ensure this runs after current digest cycle
            $scope.$evalAsync(function() {
                // PRESERVE the array reference - modify in place

                // First, clear all existing items (preserve reference)
                $scope.selected_devices.splice(0, $scope.selected_devices.length);

                if ($scope.selectAll) {
                    // Add valid devices to the SAME array - must match the HTML filter condition
                    angular.forEach($scope.devices, function(device) {
                        // Match the HTML filter: (device.status == 'stopped' && device.up_to_date == false) || showAll
                        var shouldInclude = (device.status == 'stopped' && device.up_to_date == false) || $scope.showAll;

                        if (shouldInclude && validStates.includes(device.status)) {
                            $scope.selected_devices.push(device);
                        }
                    });
                }
            });
        };



        //modal controller
        $scope.activate_modal = function(devices, action) {
            spin("start");
            // error == false => at least one device  is NOT {stopped, NA, Software broken}
            var error = check_devices_state(devices, ["stopped", "NA", "Software broken"]);
            if (!error) {
                switch (action) {
                    case 'update':
                        $scope.modal = {
                            title: 'Update devices',
                            info: 'These devices are going to be updated. Do not disconnect them.',
                            action_text: 'Update',
                            action: 'update',
                        }
                        break;
                    case 'restart':
                        $scope.modal = {
                            title: 'Restart devices',
                            info: 'The following devices are going to be restarted.',
                            action_text: 'Restart',
                            action: 'restart',
                        }
                        break;
                    case 'swBranch':
                        $scope.modal = {
                            title: 'Switch Branch devices',
                            info: 'Select branch to switch selected devices:',
                            action_text: 'Switch Branch',
                            action: 'swBranch',
                        }
                        break;
                }

            }
            $("#Modal").modal('show');
            spin("stop");
        }

        $scope.modal_action = function(devices, action) {
            // Add confirmation for destructive operations
            var confirmationMessage = '';
            switch (action) {
                case 'update':
                    confirmationMessage = 'Are you sure you want to update ' + devices.length + ' device(s)? This operation cannot be undone.';
                    break;
                case 'restart':
                    confirmationMessage = 'Are you sure you want to restart ' + devices.length + ' device(s)? This will interrupt any running experiments.';
                    break;
                case 'swBranch':
                    confirmationMessage = 'Are you sure you want to switch branches on ' + devices.length + ' device(s)? This may affect running experiments.';
                    break;
            }

            if (confirmationMessage && !confirm(confirmationMessage)) {
                $("#Modal").modal('hide');
                return; // User cancelled
            }

            $("#Modal").modal('hide');
            spin("start");
            switch (action) {
                case 'update':
                    url = '/group/update';
                    break;
                case 'restart':
                    url = '/group/restart';
                    break;
                case 'swBranch':
                    for (var i = 0; i < devices.length; i++) {
                        devices[i]['new_branch'] = $scope.modal.branch_to_switch;
                    }
                    url = '/group/swBranch';

                    break;
            }
            data = {
                "devices": devices
            };

            // Show better progress message
            $scope.system.info = 'Processing ' + action + ' for ' + devices.length + ' device(s). This may take several minutes...';
            $scope.system.error = ''; // Clear any previous errors
            $scope.system.success = ''; // Clear any previous success messages

            // Configure longer timeout for update operations (10 minutes)
            var config = {
                timeout: 600000 // 10 minutes in milliseconds
            };

            console.log('Starting', action, 'operation for', devices.length, 'devices');

            $http.post(url, data, config)
                .then(function(response) {
                    console.log('Operation completed successfully for', devices.length, 'devices');
                    var data = response.data;
                    var error = check_error(data);
                    $scope.update_result = data;
                    $scope.system.info = ''; // Clear progress message
                    spin("stop");
                    if (!error) {
                        $scope.system.success = 'Operation completed successfully!';
                        // Delay reload to show success message
                        $timeout(function() {
                            $window.location.reload();
                        }, 2000);
                    }
                }).catch(function(error) {
                    console.log('Operation failed for', devices.length, 'devices:', error.statusText || 'Unknown error');
                    $scope.system.info = ''; // Clear progress message

                    // Better error handling for different types of failures
                    var errorMessage = 'Operation failed: ';
                    if (error.status === 504) {
                        errorMessage += 'Gateway timeout - the operation may still be running. Please check device status manually.';
                    } else if (error.status === 408 || error.status === -1) {
                        errorMessage += 'Request timeout - the operation took too long. Please check if devices are accessible.';
                    } else if (error.data && error.data.error) {
                        errorMessage += error.data.error;
                    } else if (error.statusText) {
                        errorMessage += error.statusText;
                    } else {
                        errorMessage += 'Unknown error occurred';
                    }

                    $scope.system.error = errorMessage;
                    spin("stop");
                });
        }


        //HELPERS
        $scope.secToDate = function(secs) {
            d = new Date(secs * 1000);
            return d.toString();
        };

        var spin = function(action) {
            if (action == "start") {
                $scope.spinner = new Spinner(opts).spin();
                var loadingContainer = document.getElementById('loading_devices');
                loadingContainer.appendChild($scope.spinner.el);
            } else if (action == "stop") {
                $scope.spinner.stop();
                $scope.spinner = false;
            }
        };

        var check_devices_state = function(devices, states) {
            var states_dic = {};
            for (var i = 0; i < states.length; i++) {
                states_dic[states[i]] = "";
            }

            $scope.system.modal_error = "";
            if (devices.length == 0) {
                $scope.system.modal_error = "No device selected. Please tick some boxes!";
                return true;
            }


            for (device in devices) {
                if (!(devices[device]["status"] in states_dic)) {
                    $scope.system.modal_error = "One or more selected devices not one of: {" + states.join(", ") + "} ( so cannot be updated, remove them from the selection)."
                    return true;

                }
            };
            return false;
        };

        var check_error = function(data) {
            if ('error' in data) {
                $scope.system.error = data.error;
                return true;
            }
            return false;
        };

    });

})()
