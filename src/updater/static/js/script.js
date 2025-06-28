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
            console.log(data);
            if ('error' in data) {
                $scope.system.error = data.error;
                console.log($scope.system.isUpdated);
            } else {
                $scope.system.isUpdated = true;
                $scope.system.status = data;
                console.log($scope.system.isUpdated);
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

            console.log($scope.devices);
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
            $scope.selected_devices = [];

            angular.forEach($scope.devices, function(device) {
                if (device.status === 'stopped') {
                    device.selected = $scope.selectAll;
                    if ($scope.selectAll) {
                        $scope.selected_devices.push(device);
                    }
                }
            });

            console.log('Selected devices length:', $scope.selected_devices.length);
        };

        $scope.updateSelection = function(device) {
            if (device.selected) {
                const index = $scope.selected_devices.indexOf(device);
                if (index > -1) {
                    $scope.selected_devices.splice(index, 1);
                }
            } else {
                $scope.selected_devices.push(device);
            }

            device.selected = !device.selected;
            console.log('Selected devices length:', $scope.selected_devices.length);
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
                    for (device in devices) {
                        devices[device]['new_branch'] = $scope.modal.branch_to_switch;
                    }
                    url = '/group/swBranch';

                    break;
            }
            data = {
                "devices": devices
            };
            $http.post(url, data)
                .then(function(response) {
                    var data = response.data;
                    var error = check_error(data);
                    $scope.update_result = data;
                    spin("stop");
                    if (!error) {
                        $window.location.reload();
                    }
                }).catch(function(error) {
                    $scope.system.error = 'Operation failed: ' + (error.data && error.data.error ? error.data.error : error.statusText);
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

            var error = false;
            $scope.system.modal_error = "";
            if (devices.length == 0) {
                $scope.system.modal_error = "No device selected. Please tick some boxes!";
                return true;
            }


            for (device in devices) {
                if (!(devices[device]["status"] in states_dic)) {
                    //console.log(devices[device]["status"])
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