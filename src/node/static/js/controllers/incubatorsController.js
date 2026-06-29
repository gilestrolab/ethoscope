(function(){
    var incubatorsController = function($scope, $http, $timeout){

        // Statuses that count as "device is currently running an experiment"
        // for the purpose of locking incubator edits. Mirrors the API.
        var RUNNING_STATUSES = ['running', 'recording', 'streaming', 'initialising'];

        // Initialize scope variables
        $scope.incubators = {};
        $scope.liveIncubators = {};   // live telemetry of discovered WiFi units, keyed by hostname
        $scope.sensors = {};
        $scope.devices = {};       // keyed by device id; carries status + experimental_info
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

        // Load device list so the modal can show a "locked while running" banner.
        var loadDevices = function() {
            $http.get('/node/ethoscopes')
                .then(function(response) {
                    $scope.devices = response.data || {};
                })
                .catch(function(error) {
                    console.error('Error loading ethoscopes:', error);
                });
        };

        // Return the array of device names currently running in the given
        // incubator (matched by experimental_info.current.location).
        $scope.runningDevicesInIncubator = function(incubatorName) {
            var matches = [];
            if (!incubatorName || !$scope.devices) return matches;
            for (var id in $scope.devices) {
                var dev = $scope.devices[id];
                if (!dev) continue;
                var status = (dev.status || '').toLowerCase();
                if (RUNNING_STATUSES.indexOf(status) === -1) continue;
                var expInfo = dev.experimental_info || {};
                var current = expInfo.current || expInfo;
                if (current && current.location === incubatorName) {
                    matches.push(dev.name || dev.id || id);
                }
            }
            return matches;
        };

        // True if the currently selected incubator has running devices.
        $scope.isIncubatorLocked = function() {
            if (!$scope.selectedIncubator || !$scope.selectedIncubator._editing) return false;
            var name = $scope.selectedIncubator._originalName || $scope.selectedIncubator.name;
            return $scope.runningDevicesInIncubator(name).length > 0;
        };

        // Load live telemetry of discovered WiFi incubators, re-keyed by hostname.
        var loadLive = function() {
            $http.get('/incubators/live')
                .then(function(response) {
                    var live = response.data || {};
                    var byHost = {};
                    for (var id in live) {
                        var info = live[id];
                        var host = info.hostname || id;
                        byHost[host] = info;
                    }
                    $scope.liveIncubators = byHost;
                })
                .catch(function(error) {
                    console.error('Error loading live incubators:', error);
                });
        };

        // Live telemetry for a DB incubator record (bound by hostname), or null.
        $scope.liveForIncubator = function(incubator) {
            if (!incubator || !incubator.hostname) return null;
            return $scope.liveIncubators[incubator.hostname] || null;
        };

        // True if the live unit was successfully polled (status not offline).
        $scope.isLiveOnline = function(live) {
            return !!live && (live.status && live.status !== 'offline');
        };

        // Discovered WiFi units not yet bound to any incubator record.
        $scope.discoveredUnbound = function() {
            var bound = {};
            for (var key in $scope.incubators) {
                var h = $scope.incubators[key].hostname;
                if (h) bound[h] = true;
            }
            var out = [];
            for (var host in $scope.liveIncubators) {
                if (!bound[host]) out.push($scope.liveIncubators[host]);
            }
            return out;
        };

        // All discovered hostnames (for the bind dropdown in the modal).
        $scope.availableHostnames = function() {
            return Object.keys($scope.liveIncubators);
        };

        // Comma-joined hostnames of discovered-but-unbound units (for the banner).
        $scope.discoveredUnboundNames = function() {
            return $scope.discoveredUnbound().map(function(u) { return u.hostname; }).join(', ');
        };

        // Bind (or, with hostname null/empty, unbind) a DB record to a physical unit.
        // Pushes the incubator name into the unit's sensor location server-side.
        $scope.bindIncubator = function(name, hostname) {
            if (!name) return;
            $http.post('/incubator/bind', { name: name, hostname: hostname || null })
                .then(function(response) {
                    if (response.data.result === 'success') {
                        if ($scope.selectedIncubator) {
                            $scope.selectedIncubator.hostname = hostname || null;
                        }
                        loadIncubators();
                        loadLive();
                    } else {
                        alert('Error binding incubator: ' + (response.data.message || 'Unknown error'));
                    }
                })
                .catch(function(error) {
                    console.error('Error binding incubator:', error);
                    alert('Error binding incubator. Please try again.');
                });
        };

        // Manual schedule re-push to the bound firmware. Auto-push fires on save,
        // and the reconciler covers reboots — this is a power-user button.
        $scope.pushIncubatorSchedule = function(name) {
            if (!name) return;
            $http.post('/incubator/push-schedule', { name: name })
                .then(function(response) {
                    if (response.data.result === 'success') {
                        loadLive();
                    } else {
                        alert('Could not push schedule: ' +
                              (response.data.message || 'unit offline or unbound'));
                    }
                })
                .catch(function(error) {
                    console.error('Error pushing schedule:', error);
                    alert('Network error while pushing schedule.');
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

        // Clear selected incubator (for add new). New incubators default to the
        // 'normal' category (manual, light only); binding a unit makes them smart.
        $scope.clearSelectedIncubator = function() {
            $scope.selectedIncubator = {
                active: true,
                type: 'normal',
                set_temp: null,
                lights_on: null,
                lights_off: null,
                light_period_hours: 24,
                light_cycle_anchor: null,
                fade_in_seconds: 1,
                fade_out_seconds: 1,
                max_light: 100,
                crepuscular: false,
                owner: ''
            };
        };

        // --- Category helpers --------------------------------------------------

        // An incubator is 'smart' when its category is smart or it is bound to a
        // physical WiFi unit. Falls back to 'normal' for legacy/unset records.
        $scope.isSmart = function(incubator) {
            if (!incubator) return false;
            return incubator.type === 'smart' || !!incubator.hostname;
        };

        // Display category for a record: 'smart' | 'normal' | 'virtual'.
        $scope.incubatorType = function(incubator) {
            if (!incubator) return 'normal';
            if ($scope.isSmart(incubator)) return 'smart';
            return incubator.type === 'virtual' ? 'virtual' : 'normal';
        };

        $scope.incubatorTypeTitle = function(type) {
            if (type === 'smart') return 'Smart: firmware-backed, light and temperature control';
            if (type === 'virtual') return 'Virtual: short-lived "shoe box", light only';
            return 'Normal: manually added, light only';
        };

        // Convert firmware minutes-of-day (0–1440) to an HH:MM display string.
        $scope.minutesToTime = function(mins) {
            var m = parseInt(mins, 10);
            if (!Number.isFinite(m)) return '—';
            m = ((m % 1440) + 1440) % 1440;
            return ('0' + Math.floor(m / 60)).slice(-2) + ':' + ('0' + (m % 60)).slice(-2);
        };

        // Adopt a discovered (unbound) smart unit: create a smart record bound to
        // the unit, seeding the node record from the unit's current firmware state
        // so we do not disrupt a running schedule. One-click "Add & bind".
        $scope.adoptDiscovered = function(unit) {
            if (!unit || !unit.hostname) return;
            var payload = {
                name: unit.name || unit.hostname,
                hostname: unit.hostname,
                type: 'smart'
            };
            // Seed schedule + temperature from live telemetry where available.
            if (unit.lights_on !== undefined && unit.lights_off !== undefined) {
                payload.lights_on = $scope.minutesToTime(unit.lights_on);
                payload.lights_off = $scope.minutesToTime(unit.lights_off);
            }
            if (unit.light_period_minutes) payload.light_period_minutes = parseInt(unit.light_period_minutes, 10);
            if (unit.max_light !== undefined) payload.max_light = parseInt(unit.max_light, 10);
            if (unit.crepuscular !== undefined) payload.crepuscular = unit.crepuscular ? 1 : 0;
            if (unit.fade_in_ms !== undefined) payload.fade_in_seconds = Math.round(unit.fade_in_ms / 1000);
            if (unit.fade_out_ms !== undefined) payload.fade_out_seconds = Math.round(unit.fade_out_ms / 1000);
            if (unit.set_temp !== undefined && unit.set_temp !== null) payload.set_temp = unit.set_temp;

            $http.post('/setup/add-incubator', payload)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        loadIncubators();
                        loadLive();
                    } else {
                        alert('Error adopting incubator: ' + (response.data.message || 'Unknown error'));
                    }
                })
                .catch(function(error) {
                    console.error('Error adopting incubator:', error);
                    alert('Error adopting incubator. Please try again.');
                });
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

            // Period: stored in minutes, edited in whole hours.
            var periodMin = parseInt(incubator.light_period_minutes, 10);
            if (!Number.isFinite(periodMin) || periodMin <= 0) periodMin = 1440;
            $scope.selectedIncubator.light_period_hours = Math.round(periodMin / 60);

            // Anchor: keep raw unix timestamp (REAL in DB); template renders it.
            $scope.selectedIncubator.light_cycle_anchor =
                (incubator.light_cycle_anchor !== undefined && incubator.light_cycle_anchor !== null)
                    ? Number(incubator.light_cycle_anchor)
                    : null;

            // Phase-2 fade timing + peak brightness. Defaults match the firmware.
            $scope.selectedIncubator.fade_in_seconds =
                Number.isFinite(parseInt(incubator.fade_in_seconds, 10))
                    ? parseInt(incubator.fade_in_seconds, 10) : 1;
            $scope.selectedIncubator.fade_out_seconds =
                Number.isFinite(parseInt(incubator.fade_out_seconds, 10))
                    ? parseInt(incubator.fade_out_seconds, 10) : 1;
            $scope.selectedIncubator.max_light =
                Number.isFinite(parseInt(incubator.max_light, 10))
                    ? parseInt(incubator.max_light, 10) : 100;
            // Crepuscular toggle — bool in the UI, int 0/1 on the wire.
            $scope.selectedIncubator.crepuscular = !!incubator.crepuscular;

            // Category + temperature setpoint. Default legacy/unset records to
            // 'normal'; a bound record reads as 'smart' via isSmart().
            $scope.selectedIncubator.type = incubator.type || 'normal';
            $scope.selectedIncubator.set_temp =
                (incubator.set_temp !== undefined && incubator.set_temp !== null)
                    ? Number(incubator.set_temp)
                    : null;
        };

        // Format a unix timestamp for display in the modal. Returns '—' if absent.
        $scope.formatAnchor = function(ts) {
            if (ts === null || ts === undefined || ts === '') return '—';
            var d = new Date(Number(ts) * 1000);
            if (isNaN(d.getTime())) return '—';
            return d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
        };

        // Re-stamp the cycle anchor on the server. Used to phase-lock a
        // T-cycle (or a 24 h cycle) to "now". Blocked server-side if devices
        // are running in this incubator.
        $scope.resetIncubatorAnchor = function() {
            var name = $scope.selectedIncubator._originalName || $scope.selectedIncubator.name;
            if (!name) return;
            $http.post('/setup/reset-incubator-anchor', { name: name })
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.selectedIncubator.light_cycle_anchor =
                            Number(response.data.light_cycle_anchor);
                        loadIncubators();
                    } else if (response.data.code === 'incubator_busy') {
                        alert('Cannot reset cycle: device(s) currently running — '
                              + (response.data.devices || []).join(', '));
                    } else {
                        alert('Error resetting cycle anchor: ' + (response.data.message || 'Unknown error'));
                    }
                })
                .catch(function(error) {
                    console.error('Error resetting cycle anchor:', error);
                });
        };

        // Save incubator (add or update)
        $scope.saveIncubator = function() {
            var data = $scope.selectedIncubator;

            // Convert Date objects back to HH:MM strings for the API
            var lightsOn = dateToTimeString(data.lights_on);
            var lightsOff = dateToTimeString(data.lights_off);

            // Period in hours → minutes. Reject NaN/non-finite back to 24h.
            var hours = parseInt(data.light_period_hours, 10);
            if (!Number.isFinite(hours) || hours <= 0) hours = 24;
            var periodMinutes = hours * 60;

            var onSuccess = function() {
                $('#incubatorModal').modal('hide');
                loadIncubators();
                $scope.clearSelectedIncubator();
            };

            var onLocked = function(devices) {
                alert('Cannot save: light schedule is locked because device(s) '
                      + 'currently running in this incubator: ' + (devices || []).join(', '));
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
                    light_period_minutes: periodMinutes,
                    active: data.active ? 1 : 0,
                    fade_in_seconds: parseInt(data.fade_in_seconds, 10) || 0,
                    fade_out_seconds: parseInt(data.fade_out_seconds, 10) || 0,
                    max_light: Math.max(0, Math.min(100, parseInt(data.max_light, 10) || 100)),
                    crepuscular: data.crepuscular ? 1 : 0,
                    type: data.type || 'normal'
                };
                // Temperature setpoint — smart units only. Empty clears it.
                if ($scope.isSmart(data)) {
                    updatePayload.set_temp =
                        (data.set_temp === null || data.set_temp === undefined || data.set_temp === '')
                            ? '' : Number(data.set_temp);
                }
                // Anchor is server-managed when period changes; only emit it
                // explicitly if the user has one (so we don't accidentally
                // clear an existing T-cycle anchor by omission).
                if (data.light_cycle_anchor !== null && data.light_cycle_anchor !== undefined) {
                    updatePayload.light_cycle_anchor = Number(data.light_cycle_anchor);
                }

                $http.post('/setup/update-incubator', updatePayload)
                    .then(function(response) {
                        if (response.data.result === 'success') {
                            onSuccess();
                        } else if (response.data.code === 'incubator_busy') {
                            onLocked(response.data.devices);
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
                    lights_off: lightsOff,
                    light_period_minutes: periodMinutes,
                    fade_in_seconds: parseInt(data.fade_in_seconds, 10) || 0,
                    fade_out_seconds: parseInt(data.fade_out_seconds, 10) || 0,
                    max_light: Math.max(0, Math.min(100, parseInt(data.max_light, 10) || 100)),
                    crepuscular: data.crepuscular ? 1 : 0,
                    type: data.type || 'normal'
                };
                if ($scope.isSmart(data) && data.set_temp !== null && data.set_temp !== undefined && data.set_temp !== '') {
                    addPayload.set_temp = Number(data.set_temp);
                }

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

        // Live telemetry polling (every 15 s). Rescheduled recursively and
        // cancelled on view destroy.
        var livePoll = null;
        var startLivePolling = function() {
            loadLive();
            livePoll = $timeout(startLivePolling, 15000);
        };
        $scope.$on('$destroy', function() {
            if (livePoll) $timeout.cancel(livePoll);
        });

        // Initial load
        loadIncubators();
        loadUsers();
        loadSensors();
        loadDevices();
        startLivePolling();
    };

    angular.module('flyApp').controller('incubatorsController', incubatorsController);
}());
