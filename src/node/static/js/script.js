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

            // route for the users management page
            .when('/users', {
                templateUrl: '/static/pages/users.html',
                controller: 'usersController',
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
            // Get unified backup status from both MySQL and rsync backup daemons
            $http.get('/backup/status').then(function(response) {
                var data = response.data;

                // Store the full response for debugging/advanced use
                $scope.backup_status_full = data;

                // Extract devices for easy access by device ID
                $scope.backup_status = data.devices || {};

                // Check backup service availability from summary
                var summary = data.summary || {};
                $scope.mysql_backup_available = summary.services && summary.services.mysql_service_available || false;
                $scope.rsync_backup_available = summary.services && summary.services.rsync_service_available || false;
                $scope.backup_service_available = $scope.mysql_backup_available || $scope.rsync_backup_available;

            }).catch(function(error) {
                $scope.backup_status = {};
                $scope.backup_service_available = false;
                $scope.mysql_backup_available = false;
                $scope.rsync_backup_available = false;
            });
        };

        var formatConciseTime = function(date) {
            var options = {
                weekday: 'short', // Mon
                month: 'short', // Jun  
                day: 'numeric', // 28
                hour: '2-digit', // 14
                minute: '2-digit', // 25
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
            // Prioritize comprehensive backup status if available
            if (!$scope.backup_service_available) {
                return 'backup-status-offline'; // black circle
            }

            var backup_info = $scope.backup_status[device.id];
            if (backup_info && backup_info.backup_types) {
                // Use new structured backup information (same as tooltip)
                var mysql = backup_info.backup_types.mysql;
                var sqlite = backup_info.backup_types.sqlite;
                var video = backup_info.backup_types.video;

                // Check if any backup is currently processing
                if ((mysql && mysql.processing) || (sqlite && sqlite.processing) || (video && video.processing)) {
                    return 'backup-status-processing'; // orange breathing circle
                }

                // Use the calculated overall_status
                switch (backup_info.overall_status) {
                    case 'success':
                        return 'backup-status-success'; // green circle
                    case 'partial':
                        return 'backup-status-partial'; // golden circle
                    case 'error':
                        return 'backup-status-error'; // red circle
                    case 'processing':
                        return 'backup-status-processing'; // orange circle
                    case 'no_backups':
                        return 'backup-status-unknown'; // grey circle
                    default:
                        return 'backup-status-unknown'; // grey circle
                }
            }

            // Fall back to legacy device backup status for backwards compatibility
            if (device.backup_status !== undefined) {
                if (device.backup_status === 'processing') {
                    return 'backup-status-processing';
                } else if (typeof device.backup_status === 'number') {
                    if (device.backup_status >= 90) {
                        return 'backup-status-success';
                    } else if (device.backup_status >= 50) {
                        return 'backup-status-partial';
                    } else if (device.backup_status > 0) {
                        return 'backup-status-processing';
                    } else {
                        return 'backup-status-error';
                    }
                } else if (typeof device.backup_status === 'string') {
                    switch (device.backup_status.toLowerCase()) {
                        case 'success':
                        case 'completed':
                            return 'backup-status-success';
                        case 'processing':
                        case 'running':
                            return 'backup-status-processing';
                        case 'error':
                        case 'failed':
                            return 'backup-status-error';
                        default:
                            return 'backup-status-unknown';
                    }
                }
            }

            // Final fallback
            return 'backup-status-unknown'; // grey circle
        };

        $scope.getBackupStatusTitle = function(device) {
            // Check if device has new backup fields directly (for backwards compatibility)
            if (device.backup_status !== undefined && !($scope.backup_status && $scope.backup_status[device.id] && $scope.backup_status[device.id].backup_types)) {
                var title = 'Backup Status: ';

                if (typeof device.backup_status === 'number') {
                    title += device.backup_status + '%';
                } else {
                    title += device.backup_status;
                }

                if (device.backup_size !== undefined) {
                    title += '\nBackup Size: ' + $scope.humanFileSize(device.backup_size);
                }

                if (device.time_since_backup !== undefined) {
                    title += '\nTime Since Backup: ' + $scope.elapsedtime(device.time_since_backup);
                }

                return title;
            }

            // Use new structured backup information
            if (!$scope.backup_service_available) {
                return 'Backup service offline';
            }

            var backup_info = $scope.backup_status && $scope.backup_status[device.id];
            if (!backup_info || !backup_info.backup_types) {
                return 'No backup information available';
            }

            var title = 'Backup Status: ' + (backup_info.overall_status || 'unknown').toUpperCase();
            title += '\n' + '─'.repeat(30);

            // Helper function to extract folder name from path
            function getFolderName(directory) {
                if (!directory) return null;
                var parts = directory.split('/');
                return parts[parts.length - 1] || parts[parts.length - 2]; // Handle trailing slash
            }

            // Add MySQL backup details
            var mysql = backup_info.backup_types.mysql;
            if (mysql && mysql.available) {
                title += '\n📊 MySQL: ' + mysql.status.toUpperCase();
                if (mysql.records > 0) {
                    title += ' (' + mysql.records.toLocaleString() + ' records)';
                }
                if (mysql.size > 0) {
                    title += '\n   Size: ' + $scope.humanFileSize(mysql.size);
                }
                var mysqlFolder = getFolderName(mysql.directory);
                if (mysqlFolder) {
                    title += '\n   Folder: ' + mysqlFolder;
                }
                if (mysql.last_backup) {
                    var lastBackupTime = (Date.now() / 1000) - mysql.last_backup;
                    title += '\n   Last: ' + $scope.elapsedtime(lastBackupTime) + ' ago';
                }
                if (mysql.message && mysql.message !== 'Backup completed successfully') {
                    title += '\n   Note: ' + mysql.message;
                }
            } else {
                title += '\n📊 MySQL: NOT AVAILABLE';
            }

            // Add SQLite backup details
            var sqlite = backup_info.backup_types.sqlite;
            if (sqlite && sqlite.available) {
                title += '\n🗃️ SQLite: ' + sqlite.status.toUpperCase();
                if (sqlite.files > 0) {
                    title += ' (' + sqlite.files + ' files)';
                }
                if (sqlite.size > 0) {
                    title += '\n   Size: ' + $scope.humanFileSize(sqlite.size);
                }
                var sqliteFolder = getFolderName(sqlite.directory);
                if (sqliteFolder) {
                    title += '\n   Folder: ' + sqliteFolder;
                }
                if (sqlite.last_backup) {
                    var lastBackupTime = (Date.now() / 1000) - sqlite.last_backup;
                    title += '\n   Last: ' + $scope.elapsedtime(lastBackupTime) + ' ago';
                }
            } else {
                title += '\n🗃️ SQLite: NOT AVAILABLE';
            }

            // Add Video backup details
            var video = backup_info.backup_types.video;
            if (video && video.available) {
                title += '\n🎥 Video: ' + video.status.toUpperCase();
                if (video.files > 0) {
                    title += ' (' + video.files.toLocaleString() + ' files)';
                }
                if (video.size_human) {
                    title += '\n   Size: ' + video.size_human;
                } else if (video.size > 0) {
                    title += '\n   Size: ' + $scope.humanFileSize(video.size);
                }
                var videoFolder = getFolderName(video.directory);
                if (videoFolder) {
                    title += '\n   Folder: ' + videoFolder;
                }
                if (video.last_backup) {
                    var lastBackupTime = (Date.now() / 1000) - video.last_backup;
                    title += '\n   Last: ' + $scope.elapsedtime(lastBackupTime) + ' ago';
                }
            } else {
                title += '\n🎥 Video: NOT AVAILABLE';
            }

            // Add processing status if any backup is currently running
            var processing = [];
            if (mysql && mysql.processing) processing.push('MySQL');
            if (sqlite && sqlite.processing) processing.push('SQLite');
            if (video && video.processing) processing.push('Video');

            if (processing.length > 0) {
                title += '\n' + '─'.repeat(30);
                title += '\n🔄 Currently processing: ' + processing.join(', ');
            }

            return title;
        };

        $scope.getDatabaseBackupStatusClass = function(device) {
            // Check backup service availability
            if (!$scope.backup_service_available) {
                return 'backup-status-offline';
            }

            var backup_info = $scope.backup_status[device.id];
            if (!backup_info || !backup_info.backup_types) {
                return 'backup-status-unknown';
            }

            var mysql = backup_info.backup_types.mysql;
            var sqlite = backup_info.backup_types.sqlite;

            // Check if any database backup is processing
            if ((mysql && mysql.processing) || (sqlite && sqlite.processing)) {
                return 'backup-status-processing';
            }

            // Determine combined database status
            var mysqlStatus = mysql && mysql.available ? mysql.status : 'not_available';
            var sqliteStatus = sqlite && sqlite.available ? sqlite.status : 'not_available';

            var successStatuses = ['success', 'completed'];
            var errorStatuses = ['error', 'failed'];

            var mysqlOk = successStatuses.includes(mysqlStatus);
            var sqliteOk = successStatuses.includes(sqliteStatus);
            var mysqlError = errorStatuses.includes(mysqlStatus);
            var sqliteError = errorStatuses.includes(sqliteStatus);

            // Both available and successful
            if (mysql && mysql.available && sqlite && sqlite.available && mysqlOk && sqliteOk) {
                return 'backup-status-success';
            }
            // At least one available and successful
            else if ((mysql && mysql.available && mysqlOk) || (sqlite && sqlite.available && sqliteOk)) {
                // But check if other has error
                if (mysqlError || sqliteError) {
                    return 'backup-status-partial';
                }
                return 'backup-status-success';
            }
            // Any error
            else if (mysqlError || sqliteError) {
                return 'backup-status-error';
            }
            // No databases available
            else {
                return 'backup-status-unknown';
            }
        };

        $scope.getVideoBackupStatusClass = function(device) {
            // Check backup service availability
            if (!$scope.backup_service_available) {
                return 'backup-status-offline';
            }

            var backup_info = $scope.backup_status[device.id];
            if (!backup_info || !backup_info.backup_types) {
                return 'backup-status-unknown';
            }

            var video = backup_info.backup_types.video;

            if (!video || !video.available) {
                return 'backup-status-unknown';
            }

            if (video.processing) {
                return 'backup-status-processing';
            }

            // If there are no video files, show as unknown/nothing to do
            if (video.files === 0) {
                return 'backup-status-unknown';
            }

            switch (video.status) {
                case 'success':
                case 'completed':
                    return 'backup-status-success';
                case 'error':
                case 'failed':
                    return 'backup-status-error';
                case 'processing':
                case 'running':
                    return 'backup-status-processing';
                default:
                    return 'backup-status-unknown';
            }
        };

        $scope.getDatabaseBackupStatusTitle = function(device) {
            if (!$scope.backup_service_available) {
                return 'Database backup service offline';
            }

            var backup_info = $scope.backup_status[device.id];
            if (!backup_info || !backup_info.backup_types) {
                return 'No database backup information available';
            }

            var mysql = backup_info.backup_types.mysql;
            var sqlite = backup_info.backup_types.sqlite;

            var title = 'Database Backups';
            title += '\n' + '─'.repeat(20);

            // MySQL info
            if (mysql && mysql.available) {
                title += '\n📊 MySQL: ' + mysql.status.toUpperCase();
                if (mysql.records > 0) {
                    title += ' (' + mysql.records.toLocaleString() + ' records)';
                }
                if (mysql.size > 0) {
                    title += '\n   Size: ' + $scope.humanFileSize(mysql.size);
                }
                if (mysql.last_backup) {
                    var lastBackupTime = (Date.now() / 1000) - mysql.last_backup;
                    title += '\n   Last: ' + $scope.elapsedtime(lastBackupTime) + ' ago';
                }
            } else {
                title += '\n📊 MySQL: NOT AVAILABLE';
            }

            // SQLite info
            if (sqlite && sqlite.available) {
                title += '\n🗃️ SQLite: ' + sqlite.status.toUpperCase();
                if (sqlite.files > 0) {
                    title += ' (' + sqlite.files + ' files)';
                }
                if (sqlite.size > 0) {
                    title += '\n   Size: ' + $scope.humanFileSize(sqlite.size);
                }
                if (sqlite.last_backup) {
                    var lastBackupTime = (Date.now() / 1000) - sqlite.last_backup;
                    title += '\n   Last: ' + $scope.elapsedtime(lastBackupTime) + ' ago';
                }
            } else {
                title += '\n🗃️ SQLite: NOT AVAILABLE';
            }

            return title;
        };

        $scope.getVideoBackupStatusTitle = function(device) {
            if (!$scope.backup_service_available) {
                return 'Video backup service offline';
            }

            var backup_info = $scope.backup_status[device.id];
            if (!backup_info || !backup_info.backup_types) {
                return 'No video backup information available';
            }

            var video = backup_info.backup_types.video;

            if (!video || !video.available) {
                return 'Video backup not available';
            }

            // Special case: no video files to backup
            if (video.files === 0) {
                return 'Video Backup: Nothing to do\nNo video files found';
            }

            var title = 'Video Backup: ' + video.status.toUpperCase();

            if (video.files > 0) {
                title += '\nFiles: ' + video.files.toLocaleString();
            }

            if (video.size_human) {
                title += '\nSize: ' + video.size_human;
            } else if (video.size > 0) {
                title += '\nSize: ' + $scope.humanFileSize(video.size);
            }

            if (video.last_backup) {
                var lastBackupTime = (Date.now() / 1000) - video.last_backup;
                title += '\nLast backup: ' + $scope.elapsedtime(lastBackupTime) + ' ago';
            }

            if (video.processing) {
                title += '\n🔄 Currently processing...';
            }

            return title;
        };

        $scope.getBackupStatusText = function(device) {
            if (!$scope.backup_service_available) {
                return 'Service offline';
            }

            var backup_info = $scope.backup_status[device.id];
            if (!backup_info || !backup_info.backup_types) {
                return 'No backup info';
            }

            var mysql = backup_info.backup_types.mysql;
            var sqlite = backup_info.backup_types.sqlite;
            var video = backup_info.backup_types.video;

            var text = '';
            var parts = [];

            // Check if any backup is processing
            if ((mysql && mysql.processing) || (sqlite && sqlite.processing) || (video && video.processing)) {
                return 'Processing...';
            }

            // Calculate total size for display
            var totalSize = 0;
            if (mysql && mysql.available && mysql.size) totalSize += mysql.size;
            if (sqlite && sqlite.available && sqlite.size) totalSize += sqlite.size;
            if (video && video.available && video.size) totalSize += video.size;

            // Show size if we have any backups
            if (totalSize > 0) {
                text = $scope.humanFileSize(totalSize);
            }

            // Show last backup time if available (take the most recent)
            var lastBackupTime = 0;
            if (mysql && mysql.last_backup) lastBackupTime = Math.max(lastBackupTime, mysql.last_backup);
            if (sqlite && sqlite.last_backup) lastBackupTime = Math.max(lastBackupTime, sqlite.last_backup);
            if (video && video.last_backup) lastBackupTime = Math.max(lastBackupTime, video.last_backup);

            if (lastBackupTime > 0) {
                var timeSinceBackup = (Date.now() / 1000) - lastBackupTime;
                if (text) text += ' - ';
                text += $scope.elapsedtime(timeSinceBackup) + ' ago';
            }

            // If no meaningful info, show overall status
            if (!text) {
                switch (backup_info.overall_status) {
                    case 'success':
                        return 'All backups OK';
                    case 'partial':
                        return 'Partial backup';
                    case 'error':
                        return 'Backup failed';
                    case 'no_backups':
                        return 'No backups configured';
                    default:
                        return 'Unknown status';
                }
            }

            return text;
        };

        // Helper function for folder name extraction (used in video tooltip)
        function getFolderName(directory) {
            if (!directory) return null;
            var parts = directory.split('/');
            return parts[parts.length - 1] || parts[parts.length - 2];
        }

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
                var x = days + " days, " + hours + "h ";
            } else if (days == 0 && hours > 0) {
                var x = hours + "h, " + minutes + "min ";
            } else if (days == 0 && hours == 0 && minutes > 0) {
                var x = minutes + "min ";
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
            // Clear previous sensor data to show loading state
            $scope.sensoredit = null;
            $scope.$apply();

            // Set sensor data after a brief delay to ensure loading state is visible
            setTimeout(function() {
                $scope.sensoredit = $(e.relatedTarget).data('sensor');
                $scope.$apply();
            }, 100);
        });

        $('#editSensorModal').on('hidden.bs.modal', function(e) {
            // Clear sensor data when modal is closed
            $scope.sensoredit = null;
            $scope.$apply();
        });

        $scope.editSensor = function() {
            console.log($scope.sensoredit);
            $http.post('/sensor/set', data = $scope.sensoredit)
                .then(function(response) {
                    refresh_platform();
                })
        };

        $scope.manuallyAdd = function() {

            spin('start');
            $http.post('/device/add', data = $scope.ip_to_add)
                .then(function(response) {
                    spin('stop');
                    var res = response.data;
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