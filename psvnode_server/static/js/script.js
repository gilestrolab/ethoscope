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

            // route for the sleep depriver page
            .when('/sd/:device_id', {
                templateUrl : '/static/pages/sd.html',
                controller  : 'sdController'
            })
        // route for the sleep depriver page
            .when('/more', {
                templateUrl : '/static/pages/more.html',
                controller  : 'moreController as ctrl',
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


    app.controller('sdController',  function($scope, $http,$routeParams)  {

        // create a message to display in our view
        $scope.message = 'Everyone come and see how good I look!';
        $http.get('/device/'+device_id+'/all').success(function(data){
            $scope.device = data;
        });
    });
}
)()
