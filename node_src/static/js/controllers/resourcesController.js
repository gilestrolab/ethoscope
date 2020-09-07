(function(){
    var resourcesController = function($scope, $http, $timeout, $routeParams, $window){
        
        var resourcesURL = "https://lab.gilest.ro:8001/resources";
        var newsURL = "https://lab.gilest.ro:8001/news";
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

