(function(){
    var app = angular.module('flyApp', ['ngRoute']);
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

    app.controller('smController', function($scope, $http, $routeParams)  {
        device_id = $routeParams.device_id;
        $http.get('/device/'+device_id).success(function(data){
            console.log(data);
            $scope.device = data;
        });
    });

    app.controller('sdController',  function($scope, $http,$routeParams)  {

        // create a message to display in our view
        $scope.message = 'Everyone come and see how good I look!';
        $http.get('/device/'+device_id).success(function(data){
            $scope.device = data;
        });
    });
})()
