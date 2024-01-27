(function(){
    var resourcesController = function($scope, $http, $timeout, $routeParams, $window){
        
        var resourcesURL = "https://ethoscope-resources.lab.gilest.ro/resources";
        var newsURL = "https://ethoscope-resources.lab.gilest.ro/news";
        $scope.resources = {};
        $scope.notifications = {};
        $scope.hasAccess = false;
        
        $http.get(resourcesURL)
             .success(function(data, status, headers, config){
                $scope.resources = data;
                $scope.hasAccess = true;
        });

        $http.get(newsURL)
             .success(function(data, status, headers, config){
                $scope.notifications = data.news;
        });

}

 angular.module('flyApp').controller('resourcesController',resourcesController);

})()

