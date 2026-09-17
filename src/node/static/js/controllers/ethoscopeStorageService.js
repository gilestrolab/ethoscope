(function() {
    'use strict';

    var app = angular.module('flyApp');

    /**
     * Drives the "Free up space" modal: lists the runs stored on a device, tracks
     * which backed-up ones the user picked, and asks the node to delete them.
     *
     * The node decides what is deletable; this service only reflects that decision,
     * so a run the backend did not mark as backed up can never be selected here.
     *
     * It also asks, before a run starts, whether the device still has room. That
     * judgement is the node's too: the thresholds live in its configuration and the
     * arithmetic is unit-tested there, so nothing here parses a df figure or
     * compares it to a limit.
     */
    app.factory('ethoscopeStorageService', function($http) {

        function humanBytes(bytes) {
            if (!bytes) { return '0 B'; }
            var units = ['B', 'KB', 'MB', 'GB', 'TB'];
            var size = bytes;
            var i = 0;
            while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
            return (i === 0 ? size.toFixed(0) : size.toFixed(1)) + ' ' + units[i];
        }

        function freshState() {
            return {
                step: 'loading',   // loading | list | confirm | working | done | error
                runs: [],
                other: {files: 0, size_bytes: 0},
                totals: {},
                disk: {},
                selected: {},      // run path -> true
                error: null,
                result: null
            };
        }

        var service = {

            humanBytes: humanBytes,

            /** Percentage of the device partition in use, as a number. */
            usedPercent: function(storage) {
                var raw = storage && storage.disk ? storage.disk['Use%'] : null;
                return raw ? parseInt(String(raw).replace('%', ''), 10) : 0;
            },

            /**
             * Ask whether the device has room for a run, resolving to the node's
             * assessment or to null.
             *
             * Null means "start as usual": no warning, an unreachable or too-old
             * device, a timeout, anything. A disk check must never be the reason an
             * experiment does not begin, so every failure resolves rather than
             * rejects, and the timeout is well under the node's own 30 s for
             * listing runs.
             *
             * @param {string} device_id
             * @param {string} action 'tracking' or 'video'
             * @returns {Promise<Object|null>}
             */
            preflight: function(device_id, action) {
                return $http.get('/device/' + device_id + '/storage',
                                 {params: {action: action}, timeout: 10000})
                    .then(function(response) {
                        var data = response.data || {};
                        return data.preflight || null;
                    })
                    .catch(function(error) {
                        console.warn('Could not check free space, starting anyway:',
                                     error);
                        return null;
                    });
            },

            /** Load the device's runs and reset the modal to its list step. */
            load: function(device_id, $scope) {
                $scope.storage = freshState();

                return $http.get('/device/' + device_id + '/storage', {timeout: 60000})
                    .then(function(response) {
                        var data = response.data || {};
                        if (data.error) {
                            $scope.storage.step = 'error';
                            $scope.storage.error = data.error;
                            return;
                        }
                        $scope.storage.runs = data.runs || [];
                        $scope.storage.other = data.other || {files: 0, size_bytes: 0};
                        $scope.storage.totals = data.totals || {};
                        $scope.storage.disk = data.disk || {};
                        $scope.storage.step = 'list';
                    })
                    .catch(function(error) {
                        console.error('Failed to load device storage:', error);
                        $scope.storage.step = 'error';
                        $scope.storage.error = 'Could not read the storage of this ethoscope.';
                    });
            },

            /** Select or clear every backed-up run. */
            toggleAll: function($scope, select) {
                var selected = {};
                if (select) {
                    $scope.storage.runs.forEach(function(run) {
                        if (run.backed_up) { selected[run.path] = true; }
                    });
                }
                $scope.storage.selected = selected;
            },

            /** Paths of the runs currently ticked. */
            selectedPaths: function($scope) {
                var selected = $scope.storage.selected || {};
                return Object.keys(selected).filter(function(path) { return selected[path]; });
            },

            /** Total size of the ticked runs, in bytes. */
            selectedBytes: function($scope) {
                var selected = $scope.storage.selected || {};
                return ($scope.storage.runs || []).reduce(function(total, run) {
                    return selected[run.path] ? total + (run.size_bytes || 0) : total;
                }, 0);
            },

            /** Delete the ticked runs, then show what was freed. */
            purge: function(device_id, $scope) {
                var paths = service.selectedPaths($scope);
                if (!paths.length) { return; }

                $scope.storage.step = 'working';

                return $http.post('/device/' + device_id + '/storage/purge',
                                  {runs: paths}, {timeout: 300000})
                    .then(function(response) {
                        var data = response.data || {};
                        if (data.error) {
                            $scope.storage.step = 'error';
                            $scope.storage.error = data.error;
                            return;
                        }
                        $scope.storage.result = data;
                        $scope.storage.disk = data.disk || $scope.storage.disk;
                        $scope.storage.step = 'done';
                    })
                    .catch(function(error) {
                        console.error('Failed to free space:', error);
                        $scope.storage.step = 'error';
                        $scope.storage.error = 'The ethoscope did not complete the deletion.';
                    });
            }
        };

        return service;
    });

})();
