(function(){

    var experimentsController = function($scope, $http, $timeout, $routeParams, $window, $interval) {

        $scope.currentPage = 1;
        $scope.itemsPerPage = 20;

        // Get lightweight backup summary for experiments page - no individual files data
        $scope.getBackupInfo = function () { return $http.get('/backup/summary') };

        $http.get('/devices').then(function(response) { var data = response.data;
            $scope.devices = data;
        });

        $http.get('/runs_list').then(function(response) { var data = response.data;
            $scope.runs = data;
            $scope.totalRuns = 0;

            // we work syncronously so we get this data and then we process the rest
            $scope.getBackupInfo().then(function(response) {
                var backupData;
                try {
                    // response.data is already parsed by Angular, no need for JSON.parse
                    backupData = response.data;
                    $scope.backup_devices = backupData.devices || {};
                } catch (e) {
                    console.error('Error parsing backup status data:', e);
                    $scope.backup_devices = {};
                }

                for (var ix in $scope.runs) {

                    $scope.totalRuns++;

                    // reformat start and end times in a js compatible format
                    if ( $scope.runs[ix].end_time != '' ) { $scope.runs[ix].end_time = $scope.runs[ix].end_time.split(".")[0].replace(/-/g,'/') };
                    $scope.runs[ix].start_time = $scope.runs[ix]['start_time'].split(".")[0].replace(/-/g,'/') ;

                    // Get backup information for this run's ethoscope from the new backup status
                    var ethoscope_id = $scope.runs[ix].ethoscope_id;
                    var backup_info = $scope.backup_devices[ethoscope_id];

                    if (backup_info) {
                        // Determine backup type based on experimental_data file extension or database type
                        var db_name = $scope.runs[ix].experimental_data.split('\\').pop().split('/').pop();
                        var backup_type = 'sqlite'; // default

                        // Better backup type detection
                        // Check MySQL first since it's the primary backup system
                        if (backup_info.backup_types.mysql.available) {
                            backup_type = 'mysql';
                        } else if (backup_info.backup_types.sqlite.available) {
                            backup_type = 'sqlite';
                        }

                        var relevant_backup = backup_info.backup_types[backup_type];

                        if (relevant_backup.available && relevant_backup.last_backup) {
                            $scope.runs[ix].last_backup = relevant_backup.last_backup;
                            $scope.runs[ix].has_backup = true;
                            $scope.runs[ix].backup_type = backup_type;
                        } else {
                            $scope.runs[ix].has_backup = false;
                            $scope.runs[ix].backup_type = null;
                        }

                        // Store additional backup info for potential use in templates
                        $scope.runs[ix].backup_info = {
                            mysql: backup_info.backup_types.mysql,
                            sqlite: backup_info.backup_types.sqlite,
                            video: backup_info.backup_types.video
                        };
                    } else {
                        $scope.runs[ix].has_backup = false;
                        $scope.runs[ix].backup_type = null;
                        $scope.runs[ix].backup_info = null;
                    }
                }
            }).catch(function(error) {
                console.error('Error fetching backup status:', error);
                // If backup status fails, set default values for all runs
                for (var ix in $scope.runs) {
                    $scope.runs[ix].has_backup = false;
                    $scope.runs[ix].backup_type = null;
                    $scope.runs[ix].backup_info = null;
                }
            });
        });


        $scope.runstoArray = function () {
            $scope.runsArray = [];
            //transform runs from dict to array
            for (var run in $scope.runs) {
                if ($scope.runs.hasOwnProperty(run)) {
                    $scope.runsArray.push( $scope.runs[run] );
                }
            }
        };

        $scope.compare_time = function (t1, t2) {
            //compare two dates
            //t1 must be a valid date either in unix timestamp or stringformat
            //t2 can also be undefined and in that case the current time is used

            t1 = new Date (isNaN(t1) ? t1 : t1 * 1000 );

            if ( t2 == undefined )
                { t2 = new Date() }
            else
                { t2 = new Date (isNaN(t2) ? t2 : t2 * 1000) };

            return Math.floor ( (t2 - t1) / (60 * 1000) );

            }


        var refresh_data = $interval(function () {
               console.log("refresh");
           }, 10000);

         //clear interval when scope is destroyed
         $scope.$on("$destroy", function(){
             $interval.cancel(refresh_data);
             //clearInterval(refresh_data);
         });

}

 angular.module('flyApp').controller('experimentsController', experimentsController);


})()
