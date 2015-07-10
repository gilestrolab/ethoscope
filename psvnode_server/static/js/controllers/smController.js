(function(){
    var app = angular.module('flyApp');
app.controller('smController', function($scope, $http, $routeParams, $interval, $timeout, $location)  {
        device_id = $routeParams.device_id;
        var device_ip;
        $scope.device = {};
        $scope.sm = {};
        var refresh_data = false;
        var spStart= new Spinner(opts).spin();
        var starting_tracking= document.getElementById('starting');
        $http.get('/device/'+device_id+'/data').success(function(data){
            $scope.device = data;
        });

        $http.get('/device/'+device_id+'/ip').success(function(data){
                    $scope.device.ip = data;
                    device_ip = data;
                });


        $scope.sm.start = function(option){
                            spStart= new Spinner(opts).spin();
                            starting_tracking.appendChild(spStart.el);
                            $http.post('/device/'+device_id+'/controls/start', data=option)
                                 .success(function(data){$scope.device.status = data.status;});
             $http.get('/devices').success(function(data){
                    $http.get('/device/'+device_id+'/data').success(function(data){
                        $scope.device = data;
                    });

                    $http.get('/device/'+device_id+'/ip').success(function(data){
                        $scope.device.ip = data;
                        device_ip = data;
                    });
            });
        };

        $scope.sm.stop = function(){
                            $http.post('/device/'+device_id+'/controls/stop', data={})
                            .success(function(data){
                                $scope.device.status = data.status;
                            });
        };

        $scope.sm.download = function(){
            $http.get($scope.device.ip+':9000/static'+$scope.result_files);
        };

        $scope.sm.log = function(){
            var log_file_path = ''
            if ($scope.showLog == false){
                log_file_path = $scope.device.log_file;
                $http.post('/device/'+device_id+'/log', data={"file_path":log_file_path})
                     .success(function(data, status, headers, config){
                        $scope.log = data;
                        $scope.showLog = true;
                     });
            }else{
                $scope.showLog = false;
            }
        };

        $scope.sm.poweroff = function(){
                $http.post('/device/'+device_id+'/controls/poweroff', data={})
                     .success(function(data){
                        $location.path( "/" );
                })
        };

        $scope.sm.alert= function(message){alert(message);};

        $scope.sm.elapsedtime = function(t){
            // Calculate the number of days left
            var days=Math.floor(t / 86400);
            // After deducting the days calculate the number of hours left
            var hours = Math.floor((t - (days * 86400 ))/3600)
            // After days and hours , how many minutes are left
            var minutes = Math.floor((t - (days * 86400 ) - (hours *3600 ))/60)
            // Finally how many seconds left after removing days, hours and minutes.
            var secs = Math.floor((t - (days * 86400 ) - (hours *3600 ) - (minutes*60)))

            if (days>0){
                var x =  days + " days, " + hours + "h, " + minutes + "min,  " + secs + "s ";
            }else if ( days==0 && hours>0){
                var x =   hours + "h, " + minutes + "min,  " + secs + "s ";
            }else if(days==0 && hours==0 && minutes>0){
                var x =  minutes + "min,  " + secs + "s ";
            }else if(days==0 && hours==0 && minutes==0 && secs > 0){
                var x =  secs + " s ";
            }
            return x;

        };
        $scope.sm.readable_url = function(url){
                //start tooltips
        $('[data-toggle="tooltip"]').tooltip()
            readable = url.split("/");
            len = readable.length;
            readable = ".../"+readable[len - 1];
            return readable;
        };
         $scope.sm.start_date_time = function(unix_timestamp){
            var date = new Date(unix_timestamp*1000);
            return date.toUTCString();
        };


       var refresh = function(){
            $http.get('/device/'+device_id+'/data')
                 .success(function(data){
                console.log(data);
                    $scope.device= data;
                    $scope.device.img = device_ip+':9000/static'+$scope.device.last_drawn_img + '?' + new Date().getTime();
                    $scope.device.ip = device_ip;
                    if (typeof spStart != undefined && $scope.device.status == 'running' || $scope.device.status=='stopped'){
                        spStart.stop();
                    }
                 });
       }

       //tracking selection
        $scope.tracking={"options":{
                            "32_arena":{name:"32_arena", kwargs:""},
                            "20_tubes":{name:"20_tubes", kwargs:""},
                            "72_wells":{name:"72_wells", kwargs:""},
                            "custom":{name:"custom", kwargs:""}
                        }};


        refresh_data = $interval(refresh, 3000);
        //clear interval when scope is destroyed
        $scope.$on("$destroy", function(){
        $interval.cancel(refresh_data);
        //clearInterval(refresh_data);
    });

    });
})()
