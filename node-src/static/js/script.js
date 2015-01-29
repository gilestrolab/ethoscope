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
            $http.get('/devices').success(function(data){
                $scope.devices = data;
            })
        }
    });

    app.controller('smController', function($scope, $http, $routeParams, $interval)  {
        device_id = $routeParams.device_id;
        $scope.sm = {}
        var refresh_data = false;
        $http.get('/device/'+device_id+'/data/all').success(function(data){

            $scope.device = data;

            if ($scope.device.status == 'started'){
                        refresh_data = $interval($scope.sm.refresh, 10000);
                    }
        });
        $http.get('/device/'+device_id+'/ip').success(function(data){
                    $scope.device.ip = data;
                });

        $scope.sm.start = function(){
            $http.get('/device/'+device_id+'/controls/start')
                 .success(function(data){
                    console.log(data);
                    $scope.device.status = data.status;
                    if (data.status == 'started'){
                        refresh_data = $interval($scope.sm.refresh, 10000);
                    }
                });
        };
        $scope.sm.stop = function(){
            $http.get('/device/'+device_id+'/controls/stop')
                 .success(function(data){
                    console.log(data);
                    $scope.device.status = data.status;
                    if (data.status == 'started'){
                        $scope.sm.refresh();
                        $interval.cancel(refresh_data);
                    }
                });
        };
        $scope.sm.refresh = function(){
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
