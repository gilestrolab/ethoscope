(function() {
    var app = angular.module('flyApp', ['ngRoute', 'daterangepicker', 'angularUtils.directives.dirPagination', 'ui.bootstrap']);

    app.filter("toArray", function() {
        return function(obj) {
            var result = [];
            angular.forEach(obj, function(val, key) {
                result.push(val);
            });
            return result;
        };
    });

    app.filter('orderObjectBy', function() {
        return function(items, field, reverse) {
            var filtered = [];
            angular.forEach(items, function(item) {
                filtered.push(item);
            });
            filtered.sort(function(a, b) {
                return (a[field] > b[field] ? 1 : -1);
            });
            if (reverse) filtered.reverse();
            return filtered;
        };
    });

    app.directive('ngEnter', function() {
        return function(scope, element, attrs) {
            element.on("keydown keypress", function(event) {
                if (event.which === 13) {
                    scope.$apply(function() {
                        scope.$eval(attrs.ngEnter);
                    });
                    event.preventDefault();
                }
            });
        };
    });


    // configure our routes

    app.config(function($routeProvider, $locationProvider) {
        $routeProvider

            // route for the home page
            .when('/', {
                templateUrl: '/static/pages/home.html',
                controller: 'mainController'
            })

            // route for the sleep monitor page
            .when('/ethoscope/:device_id', {
                templateUrl: '/static/pages/ethoscope.html',
                controller: 'ethoscopeController'
            })

            // route for the management page
            .when('/more/:option', {
                templateUrl: '/static/pages/more.html',
                controller: 'moreController',
            })

            // route for the experiments database page
            .when('/experiments', {
                templateUrl: '/static/pages/experiments.html',
                controller: 'experimentsController',
            })

            // route for the experiments database page
            .when('/resources', {
                templateUrl: '/static/pages/resources.html',
                controller: 'resourcesController',
            })

            // route for the sensors plotting
            .when('/sensors_data', {
                templateUrl: '/static/pages/sensors_data.html',
                controller: 'sensorsController',
            })


        // route for the help page
        /*.when('/help', {
            templateUrl : '/static/pages/help.html',
            controller  : 'helpController'
        })*/
        ;
        // use hash-based routing for better compatibility
        $locationProvider.html5Mode(false);
        $locationProvider.hashPrefix('!');
    });

    // create the controller and inject Angular's $scope
    app.controller('mainController', function($scope, $http, $interval, $timeout) {
        $scope.sortType = 'name'; // set the default sort type
        $scope.sortReverse = false; // set the default sort order
        $scope.filterEthoscopes = ''; // set the default search/filter term
        $scope.notifications = {};

        $scope.groupActions = {};
        //        $http.get('/node/time').success(function(data){
        //            t = new Date(data.time);
        //            $scope.time = t.toString();
        //        });

        var spin = function(action) {
            if (action == "start") {
                $scope.spinner = new Spinner(opts).spin();
                var loadingContainer = document.getElementById('userInputs');
                loadingContainer.appendChild($scope.spinner.el);
            } else if (action == "stop") {
                $scope.spinner.stop();
                $scope.spinner = false;
            }
        }

        $http.get('/devices').then(function(response) {
            var data = response.data;
            $scope.devices = data;
        });

        $http.get("https://ethoscope-resources.lab.gilest.ro/news").then(function(response) {
            var data = response.data;
            $scope.notifications = data.news;
        });

        var get_sensors = function() {
            $http.get('/sensors').then(function(response) {
            var data = response.data;
                $scope.sensors = data;
                $scope.has_sensors = Object.keys($scope.sensors).length;
            })
        };

        var get_backup_status = function() {
            // Get backup status via proxy to avoid CORS issues
            $http.get('/backup/status').then(function(response) {
                $scope.backup_status = response.data;
                $scope.backup_service_available = true;
            }).catch(function(error) {
                $scope.backup_status = {};
                $scope.backup_service_available = false;
            });
        };

        var formatConciseTime = function(date) {
            var options = {
                weekday: 'short',   // Mon
                month: 'short',     // Jun  
                day: 'numeric',     // 28
                hour: '2-digit',    // 14
                minute: '2-digit',  // 25
                timeZoneName: 'short' // BST
            };
            return date.toLocaleString('en-GB', options);
        };

        var update_local_times = function() {
            $http.get('/node/time').then(function(response) {
            var data = response.data;
                var t = new Date(data.time);
                $scope.time = formatConciseTime(t);
            });
            var t = new Date();
            $scope.localtime = formatConciseTime(t);
        };

        var get_devices = function() {
            $http.get('/devices').then(function(response) {
            var data = response.data;

                var data_list = [];

                for (var d in data) {
                    data_list.push(data[d]);
                }

                $scope.devices = data_list;
                $scope.n_devices = $scope.devices.length;
                var status_summary = {};

                for (var d in $scope.devices) {

                    var dev = $scope.devices[d]

                    if (!(dev.status in status_summary))
                        status_summary[dev.status] = 0;
                    status_summary[dev.status] += 1;
                }


                $scope.status_n_summary = status_summary
            })
        };

        $scope.secToDate = function(secs) {
            var d = new Date(isNaN(secs) ? secs : secs * 1000);
            return formatConciseTime(d);
        };

        $scope.getBackupStatusClass = function(device) {
            if (!$scope.backup_service_available) {
                return 'backup-status-offline';  // black circle
            }
            
            var backup_info = $scope.backup_status[device.id];
            if (!backup_info) {
                return 'backup-status-unknown';  // grey circle
            }
            
            if (backup_info.progress && backup_info.progress.status === 'success') {
                return 'backup-status-success';  // green circle
            } else if (backup_info.progress && backup_info.progress.status === 'error') {
                return 'backup-status-error';  // red circle
            } else if (backup_info.processing) {
                return 'backup-status-processing';  // yellow/orange circle
            } else {
                return 'backup-status-unknown';  // grey circle
            }
        };

        $scope.getBackupStatusTitle = function(device) {
            if (!$scope.backup_service_available) {
                return 'Backup service offline';
            }
            
            var backup_info = $scope.backup_status[device.id];
            if (!backup_info) {
                return 'No backup information available';
            }
            
            var title = 'Backup Status: ' + (backup_info.status || 'unknown');
            if (backup_info.progress && backup_info.progress.message) {
                title += ' - ' + backup_info.progress.message;
            }
            if (backup_info.count) {
                title += ' (Backup #' + backup_info.count + ')';
            }
            return title;
        };

        $scope.elapsedtime = function(t) {
            // Calculate the number of days left
            var days = Math.floor(t / 86400);
            // After deducting the days calculate the number of hours left
            var hours = Math.floor((t - (days * 86400)) / 3600)
            // After days and hours , how many minutes are left
            var minutes = Math.floor((t - (days * 86400) - (hours * 3600)) / 60)
            // Finally how many seconds left after removing days, hours and minutes.
            var secs = Math.floor((t - (days * 86400) - (hours * 3600) - (minutes * 60)))

            if (days > 0) {
                var x = days + " days, " + hours + "h, " + minutes + "min,  " + secs + "s ";
            } else if (days == 0 && hours > 0) {
                var x = hours + "h, " + minutes + "min,  " + secs + "s ";
            } else if (days == 0 && hours == 0 && minutes > 0) {
                var x = minutes + "min,  " + secs + "s ";
            } else if (days == 0 && hours == 0 && minutes == 0 && secs > 0) {
                var x = secs + " s ";
            }
            return x;

        };

        /**
         * Format bytes as human-readable text.
         * 
         * @param bytes Number of bytes.
         * @param si True to use metric (SI) units, aka powers of 1000. False to use 
         *           binary (IEC), aka powers of 1024.
         * @param dp Number of decimal places to display.
         * 
         * @return Formatted string.
         */
        $scope.humanFileSize = function(bytes, si = false, dp = 1) {
            const thresh = si ? 1000 : 1024;

            if (Math.abs(bytes) < thresh) {
                return bytes + ' B';
            }

            const units = si ? ['kB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'] : ['KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB'];
            let u = -1;
            const r = 10 ** dp;

            do {
                bytes /= thresh;
                ++u;
            } while (Math.round(Math.abs(bytes) * r) / r >= thresh && u < units.length - 1);


            return bytes.toFixed(dp) + ' ' + units[u];
        };


        $scope.groupActions.checkStart = function(selected_devices) {
            var softwareVersion = "";
            var device_version = "";
            checkVersionLoop:
                for (var i = 0; i < selected_devices.length(); i++) {
                    $http.get('/device/' + selected_devices[i] + '/data').then(function(response) {
            var data = response.data;
                        device_version = data.version.id
                    });
                    if (i == 0) {
                        softwareVersion = device_version;
                    }
                    if (softwareVersion != device_version) {
                        break checkVersionLoop;
                    }
                }
        };

        $scope.groupActions.start = function() {
            $("#startModal").modal('hide');
            var spStart = new Spinner(opts).spin();
            starting_tracking.appendChild(spStart.el);
            $http.post('/device/' + device_id + '/controls/start', data = option)
                .then(function(response) {
            var data = response.data;
                    $scope.device.status = data.status;
                });
            $http.get('/devices').then(function(response) {
            var data = response.data;
                $http.get('/device/' + device_id + '/data').then(function(response) {
            var data = response.data;
                    $scope.device = data;

                });

                $http.get('/device/' + device_id + '/ip').then(function(response) {
            var data = response.data;
                    $scope.device.ip = data;
                    var device_ip = data;
                });
                $("#startModal").modal('hide');
            });
        };

        $scope.$on('$viewContentLoaded', $scope.get_devices);

        $('#editSensorModal').on('show.bs.modal', function(e) {
            $scope.sensoredit = $(e.relatedTarget).data('sensor');
        });

        $scope.editSensor = function() {
            console.log($scope.sensoredit);
            $http.post('/sensor/set', data = $scope.sensoredit)
                .success(function(res) {
                    refresh_platform();
                })
        };

        $scope.manuallyAdd = function() {

            spin('start');
            $http.post('/device/add', data = $scope.ip_to_add)
                .success(function(res) {
                    spin('stop');
                    if (res.problems && res.problems.length) {
                        $scope.alertMessage = "The following entries could not be added: " + res.problems.join();
                        $('#IPAlertModal').modal('show');
                    }
                })
                .catch(function() {
                    spin('stop');
                })
        };

        var refresh_platform = function() {
            if (document.visibilityState == "visible") {
                get_devices();
                update_local_times();
                get_sensors();
                get_backup_status();
                //console.log("refresh platform", new Date());

                // For some reason that I don't understand, angularjs templates cannot access scope from the header so 
                // we need to use jquery to change the value of the notification badge. We do that only if news is newer than a week.
                //console.log($scope.notifications.length); // 1
                //console.log($scope.notifications[0]); // {content: "Latest news here", date: "2020-02-15"}

                $('.notification-badge').html($scope.notifications.length);

            }
        };

        // Initialize backup status on page load
        get_backup_status();

        // refresh every 5 seconds
        var refresh_data = $interval(refresh_platform, 5 * 1000);

        //clear interval when scope is destroyed
        $scope.$on("$destroy", function() {
            $interval.cancel(refresh_data);
            //clearInterval(refresh_data);
        });
    });
})()