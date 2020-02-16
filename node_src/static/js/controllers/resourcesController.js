(function(){
    var resourcesController = function($scope, $http, $timeout, $routeParams, $window){
        
        var URL = "http://lab.gilest.ro:8001/resources";
        $scope.resources = {};
        $scope.announcement = "";
        $scope.hasAccess = false;
        
        $http.get(URL)
             .success(function(data, status, headers, config){
                $scope.resources = data;
                $scope.hasAccess = true;
        });
        
}

 angular.module('flyApp').controller('resourcesController',resourcesController);

})()

