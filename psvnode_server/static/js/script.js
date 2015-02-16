(function(){
    var app = angular.module('flyApp', ['ngRoute']);
    app.filter("toArray", function(){
        return function(obj) {
            var result = [];
            angular.forEach(obj, function(val, key) {
                result.push(val);
            });
            return result;
        };
    });

    // configure our routes

    app.config(function($routeProvider, $locationProvider) {
        $routeProvider

            // route for the home page
            .when('/', {
                templateUrl : '/static/pages/home.html',
                controller  : 'mainController'
            })
            .when('/list/:device_type', {
                templateUrl : '/static/pages/list.html',
                controller  : 'listController'
            })

            // route for the sleep monitor page
            .when('/sm/:device_id', {
                templateUrl : '/static/pages/sm.html',
                controller  : 'smController'
            })

            // route for the sleep deprivator page
            .when('/sd/:device_id', {
                templateUrl : '/static/pages/sd.html',
                controller  : 'sdController'
            });
        // use the HTML5 History API
        $locationProvider.html5Mode(true);
    });

    // create the controller and inject Angular's $scope
    app.controller('mainController', function($scope, $http) {
        $http.get('/devices_list').success(function(data){
            $scope.devices = data;

        })
        //Scan for SM or SD connected.
        $scope.get_devices = function(){
            var spinner= new Spinner(opts).spin();
            var loadingContainer = document.getElementById('loading_devices');
            loadingContainer.appendChild(spinner.el);
            $scope.loading_devices = true;
            $http.get('/devices').success(function(data){
                $scope.devices = data;
                spinner.stop();
                $scope.loading_devices = false;

            })
        }
    });


    app.controller('listController', function($scope, $http, $routeParams, $interval)  {
        $scope.req_device_type = $routeParams.device_type;
        if ($scope.req_device_type == "sm"){
            $scope.device_type = "Sleep Monitor";
        }else if ($scope.req_device_type == 'sd'){
            $scope.device_type = "Sleep Deprivator";
        }
        $http.get('/devices_list').success(function(data){
            $scope.devices = data;
        })

        $scope.get_devices = function(){
            var spinner= new Spinner(opts).spin();
            var loadingContainer = document.getElementById('loading_devices');
            loadingContainer.appendChild(spinner.el);
            $scope.loading_devices = true;
            $http.get('/devices').success(function(data){
                $scope.devices = data;
                spinner.stop();
                $scope.loading_devices = false;

            })
        }
    });

    app.controller('smController', function($scope, $http, $routeParams, $interval, $timeout)  {
        device_id = $routeParams.device_id;
        var device_ip;
        $scope.sm = {}
        var refresh_data = false;
        var spStart= new Spinner(opts).spin();
        var starting_tracking= document.getElementById('starting');


        $http.get('/device/'+device_id+'/data').success(function(data){
            $scope.device = data;
            if ($scope.device.status == 'running'){
                        refresh();
                        refresh_data = $interval(refresh, 3000);
                    }
        });

        $http.get('/device/'+device_id+'/ip').success(function(data){
                    $scope.device.ip = data;
                    device_ip = data;
                });

        $scope.sm.start = function(){
            $scope.starting = true;
            starting_tracking.appendChild(spStart.el);

            $http.post('/device/'+device_id+'/controls/start', data={"time":Date.now() / 1000.})
                 .success(function(data){

                    $scope.device.status = data.status;
                    if (data.status == 'started'){
                        $http.post('/devices_list', data={"device_id":device_id,"status":"running"})
                        $timeout(refresh,1000);
                        refresh_data = $interval(refresh, 3000);

                    }
                });
        };

        $scope.sm.stop = function(){
            $http.post('/device/'+device_id+'/controls/stop', data={})
                 .success(function(data){
                    $scope.device.status = data.status;
                    if (data.status == 'stopped'){
                        $http.post('/devices_list', data={"device_id":device_id,"status":"stopped"})
                        //TODO: does not stop.
                        $interval.cancel(refresh_data);
                    }
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

            })
        }

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
         $scope.sm.start_date_time = function(unix_timestamp){

            var date = new Date(unix_timestamp*1000);

            return date.toUTCString();
        };

       var refresh = function(){
            $http.get('/device/'+device_id+'/data')
                 .success(function(data){
                    $scope.device= data;
                    $scope.device.img = device_ip+':9000/static'+$scope.device.last_drawn_img + '?' + new Date().getTime();
                    $scope.device.ip = device_ip;
                if ($scope.starting == true && $scope.device.status == 'running'){
                    $scope.starting= false;
                    spStart.stop();
                }
                });
        }

    });

    app.controller('sdController',  function($scope, $http,$routeParams)  {

        // create a message to display in our view
        $scope.message = 'Everyone come and see how good I look!';
        $http.get('/device/'+device_id+'/all').success(function(data){
            $scope.device = data;
        });
    });
})()
