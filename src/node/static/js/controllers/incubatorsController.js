(function(){
    var incubatorsController = function($scope, $http, $timeout){

        // Initialize scope variables
        $scope.incubators = {};
        $scope.sensors = {};
        $scope.activeUsers = [];
        $scope.selectedIncubator = {};
        $scope.incubatorToDelete = null;
        $scope.searchText = '';
        $scope.showAll = false;
        $scope.sortType = 'name';
        $scope.sortReverse = false;

        // Filter function for incubators
        $scope.incubatorFilter = function(incubators, searchText, showAll) {
            if (!incubators) return [];

            var filtered = [];

            for (var key in incubators) {
                var inc = incubators[key];
                inc.key = key;

                if (!showAll && !inc.active) {
                    continue;
                }

                filtered.push(inc);
            }

            if (searchText) {
                filtered = filtered.filter(function(inc) {
                    var s = searchText.toLowerCase();
                    return (inc.name && inc.name.toLowerCase().indexOf(s) !== -1) ||
                           (inc.location && inc.location.toLowerCase().indexOf(s) !== -1) ||
                           (inc.owner && inc.owner.toLowerCase().indexOf(s) !== -1) ||
                           (inc.description && inc.description.toLowerCase().indexOf(s) !== -1);
                });
            }

            return filtered;
        };

        // Load incubators data
        var loadIncubators = function() {
            $http.get('/node/incubators')
                .then(function(response) {
                    $scope.incubators = response.data;
                })
                .catch(function(error) {
                    console.error('Error loading incubators:', error);
                });
        };

        // Load active users for owner dropdown
        var loadUsers = function() {
            $http.get('/node/users')
                .then(function(response) {
                    var users = response.data;
                    $scope.activeUsers = [];
                    for (var key in users) {
                        if (users[key].active) {
                            $scope.activeUsers.push(users[key].fullname || users[key].name);
                        }
                    }
                    $scope.activeUsers.sort();
                })
                .catch(function(error) {
                    console.error('Error loading users:', error);
                });
        };

        // Load sensors to show association with incubators
        var loadSensors = function() {
            $http.get('/node/sensors')
                .then(function(response) {
                    $scope.sensors = response.data;
                })
                .catch(function(error) {
                    console.error('Error loading sensors:', error);
                });
        };

        // Get sensor associated with an incubator (matched by location field)
        $scope.getSensorForIncubator = function(incubatorName) {
            if (!incubatorName || !$scope.sensors) return null;
            var normalized = incubatorName.replace(/\s+/g, '_');
            for (var key in $scope.sensors) {
                if ($scope.sensors[key].location === normalized) {
                    return $scope.sensors[key];
                }
            }
            return null;
        };

        // Confirm delete incubator
        $scope.confirmDeleteIncubator = function(incubator) {
            $scope.incubatorToDelete = incubator;
        };

        // Delete incubator permanently
        $scope.deleteIncubator = function() {
            if (!$scope.incubatorToDelete) return;

            $http.post('/setup/delete-incubator', { name: $scope.incubatorToDelete.name })
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $('#deleteIncubatorModal').modal('hide');
                        loadIncubators();
                    } else {
                        alert('Error deleting incubator: ' + (response.data.message || 'Unknown error'));
                    }
                })
                .catch(function(error) {
                    console.error('Error deleting incubator:', error);
                    alert('Error deleting incubator. Please try again.');
                });

            $scope.incubatorToDelete = null;
        };

        // Clear selected incubator (for add new)
        $scope.clearSelectedIncubator = function() {
            $scope.selectedIncubator = {
                active: true,
                lights_on: null,
                lights_off: null,
                owner: ''
            };
        };

        // Edit incubator - convert DB types to Angular model types
        $scope.editIncubator = function(incubator) {
            $scope.selectedIncubator = angular.copy(incubator);
            $scope.selectedIncubator._editing = true;
            $scope.selectedIncubator._originalName = incubator.name;

            // Convert active from integer (0/1) to boolean for checkbox
            $scope.selectedIncubator.active = !!incubator.active;

            // Convert time strings ("HH:MM") to Date objects for input[type=time]
            $scope.selectedIncubator.lights_on = timeStringToDate(incubator.lights_on);
            $scope.selectedIncubator.lights_off = timeStringToDate(incubator.lights_off);
        };

        // Save incubator (add or update)
        $scope.saveIncubator = function() {
            var data = $scope.selectedIncubator;

            // Convert Date objects back to HH:MM strings for the API
            var lightsOn = dateToTimeString(data.lights_on);
            var lightsOff = dateToTimeString(data.lights_off);

            var onSuccess = function() {
                $('#incubatorModal').modal('hide');
                loadIncubators();
                $scope.clearSelectedIncubator();
            };

            if (data._editing) {
                var updatePayload = {
                    original_name: data._originalName,
                    name: data.name,
                    location: data.location || '',
                    owner: data.owner || '',
                    description: data.description || '',
                    lights_on: lightsOn,
                    lights_off: lightsOff,
                    active: data.active ? 1 : 0
                };

                $http.post('/setup/update-incubator', updatePayload)
                    .then(function(response) {
                        if (response.data.result === 'success') {
                            onSuccess();
                        } else {
                            alert('Error updating incubator: ' + (response.data.message || 'Unknown error'));
                        }
                    })
                    .catch(function(error) {
                        console.error('Error updating incubator:', error);
                        alert('Error updating incubator. Please try again.');
                    });
            } else {
                var addPayload = {
                    name: data.name,
                    location: data.location || '',
                    owner: data.owner || '',
                    description: data.description || '',
                    lights_on: lightsOn,
                    lights_off: lightsOff
                };

                $http.post('/setup/add-incubator', addPayload)
                    .then(function(response) {
                        if (response.data.result === 'success') {
                            onSuccess();
                        } else {
                            alert('Error adding incubator: ' + (response.data.message || 'Unknown error'));
                        }
                    })
                    .catch(function(error) {
                        console.error('Error adding incubator:', error);
                        alert('Error adding incubator. Please try again.');
                    });
            }
        };

        /**
         * Convert an HH:MM time string to a Date object for Angular input[type=time].
         * Angular requires Date objects for time inputs, not strings.
         * Returns null if the value is empty or invalid.
         */
        function timeStringToDate(val) {
            if (!val || val === '') return null;
            var str = String(val);
            // Handle ISO date strings like "1970-01-01T08:00:00.000Z"
            var tIndex = str.indexOf('T');
            if (tIndex !== -1) {
                str = str.substring(tIndex + 1);
            }
            var parts = str.split(':');
            if (parts.length >= 2) {
                var h = parseInt(parts[0], 10);
                var m = parseInt(parts[1], 10);
                if (!isNaN(h) && !isNaN(m) && h >= 0 && h <= 23 && m >= 0 && m <= 59) {
                    var d = new Date(1970, 0, 1, h, m, 0);
                    return d;
                }
            }
            return null;
        }

        /**
         * Convert a Date object (or string) back to HH:MM string for the API.
         */
        function dateToTimeString(val) {
            if (!val) return '';
            if (val instanceof Date) {
                var h = ('0' + val.getHours()).slice(-2);
                var m = ('0' + val.getMinutes()).slice(-2);
                return h + ':' + m;
            }
            // Already a string - normalize
            var str = String(val);
            var tIndex = str.indexOf('T');
            if (tIndex !== -1) {
                str = str.substring(tIndex + 1);
            }
            var parts = str.split(':');
            if (parts.length >= 2) {
                return ('0' + parseInt(parts[0], 10)).slice(-2) + ':' + ('0' + parseInt(parts[1], 10)).slice(-2);
            }
            return '';
        }

        /**
         * Format a time value for display in templates.
         * Handles Date objects, ISO strings, and HH:MM strings.
         */
        $scope.formatTime = function(val) {
            return dateToTimeString(val);
        };

        // Initial load
        loadIncubators();
        loadUsers();
        loadSensors();
    };

    angular.module('flyApp').controller('incubatorsController', incubatorsController);
}());
