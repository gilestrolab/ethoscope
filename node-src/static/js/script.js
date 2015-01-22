// script.js

    // create the module and name it scotchApp
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
            .when('/sm', {
                templateUrl : '/static/pages/sm.html',
                controller  : 'smController'
            })

            // route for the sleep deprivator page
            .when('/sd', {
                templateUrl : '/static/pages/sd.html',
                controller  : 'sdController'
            });
        // use the HTML5 History API
        $locationProvider.html5Mode(true);
    });

    // create the controller and inject Angular's $scope
    app.controller('mainController', function($scope) {

        // create a message to display in our view
        $scope.message = 'Everyone come and see how good I look!';
        //Scan for SM or SD connected, first try local connexion, if not possible try through PT-Node.
        //1. Ask for the ip address of the PT-Node
        /*http.get('/ipAddress').success(function(data){
         IP_PT_Node = data;
        });
        for(var i=0; i<256; i++){
            http.get('/piDiscover')
        }*/
    });

    app.controller('smController', function($scope) {

        // create a message to display in our view
        $scope.message = 'Everyone come and see how good I look!';
    });

    app.controller('sdController', function($scope) {

        // create a message to display in our view
        $scope.message = 'Everyone come and see how good I look!';
    });
