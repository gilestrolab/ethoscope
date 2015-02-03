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
            console.log(data);
        })
        //Scan for SM or SD connected.
        $scope.get_devices = function(){
            $http.get('/devices').success(function(data){
                $scope.devices = data;
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
            $http.get('/devices').success(function(data){
                $scope.devices = data;
            })
        }
    });

    app.controller('smController', function($scope, $http, $routeParams, $interval, $timeout)  {
        device_id = $routeParams.device_id;
        $scope.sm = {}
        var refresh_data = false;
        $http.get('/device/'+device_id+'/data/all').success(function(data){

            $scope.device = data;

            if ($scope.device.status == 'started'){
                        refresh_data = $interval(refresh, 10000);
                    }
        });
        $http.get('/device/'+device_id+'/ip').success(function(data){
                    $scope.device.ip = data;
                });

        $scope.sm.start = function(){
            $http.post('/device/'+device_id+'/controls/start', data={"time":Date.now() / 1000.})
                 .success(function(data){
                    console.log(data);
                    $scope.device.status = data.status;
                    if (data.status == 'started'){
                        $http.post('/devices_list', data={"device_id":device_id,"status":"started"})
                        $timeout(refresh,1000);
                        refresh_data = $interval(refresh, 10000);
                    }
                });
        };
        $scope.sm.stop = function(){
            $http.post('/device/'+device_id+'/controls/stop', data={})
                 .success(function(data){
                    $scope.device.status = data.status;
                    if (data.status == 'stopped'){
                        $http.post('/devices_list', data={"device_id":device_id,"status":"stopped"})
                        $interval.cancel(refresh_data);
                    }
                });
        };

        $scope.sm.download = function(){
            $http.get($scope.device.ip+':9000/static/tmp/out.csv.gz');
        };

        $scope.sm.log = function(){
            var log_file_path = ''
            if ($scope.showLog == false){
            $http.get('/device/'+device_id+'/data/log_file_path')
                .success(function(data){
                    log_file_path = data.log_file;
                    console.log(log_file_path);
                    $http.post('/device/'+device_id+'/log', data={"file_path":log_file_path})
                        .success(function(data, status, headers, config){
                            $scope.device.log = data;
                            $scope.showLog = true;
                        });
            });
            }else{
                $scope.showLog = false;
            }
        };


       var refresh = function(){
            $http.get('/device/'+device_id+'/data/last_drawn_img')
                 .success(function(data){
                    console.log(data);
                    $scope.device.last_drawn_img = data.last_drawn_img+'?' + new Date().getTime();
                });
            $http.get('/device/'+device_id+'/data/last_positions')
                 .success(function(data){
                    console.log(data);
                    $scope.device.last_positions = data.last_positions;
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
